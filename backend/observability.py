"""One trace per interview.

The trace id is the interview id with dashes removed, so every request in that
interview lands on the same trace. The Langfuse session id is the interview id.

Spans are written to a local JSONL file whenever tracing is on. They are also
sent to Langfuse as OpenTelemetry traces (``POST /api/public/otel/v1/traces``
with ``x-langfuse-ingestion-version: 4``) when ``LANGFUSE_PUBLIC_KEY``,
``LANGFUSE_SECRET_KEY``, and ``LANGFUSE_HOST`` are all set. The legacy
``/api/public/ingestion`` batch stopped accepting traces on 16 November 2026
and answers HTTP 207 while dropping every event. A failed export is logged
and swallowed: tracing never changes the interview response.

Tracing stays off under unittest and pytest unless ``AI_RECRUITER_TRACES=1``.
Emails and phone numbers are masked before anything is written.
"""

from __future__ import annotations

import atexit
import base64
import contextvars
import json
import logging
import os
import queue
import re
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)

MAX_TEXT = 8000
SERVICE = "ai-recruiter"

# USD per 1,000,000 tokens. These are demo estimates for Groq gpt-oss-120b.
# Replace them with invoice rates via MODEL_PRICES_JSON without a code change.
DEFAULT_PRICES = {
    "openai/gpt-oss-120b": {"input_per_million": 0.15, "output_per_million": 0.60},
    "default": {"input_per_million": 0.15, "output_per_million": 0.60},
}

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
_PHONE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{8,}\d(?!\w)")

_session: contextvars.ContextVar[str | None] = contextvars.ContextVar("obs_session", default=None)
_stack: contextvars.ContextVar[tuple] = contextvars.ContextVar("obs_stack", default=())
_llm_log: contextvars.ContextVar[list | None] = contextvars.ContextVar("obs_llm_log", default=None)
_notes: contextvars.ContextVar[dict | None] = contextvars.ContextVar("obs_notes", default=None)

_queue: queue.Queue | None = None
_worker_started = False
_worker_lock = threading.Lock()
_file_lock = threading.Lock()
_project_cache: tuple[str, str, str] | None = None
_project_lock = threading.Lock()
_logged_ingestion_success = False
_SECRET_RE = re.compile(r"(?:pk|sk)-lf-[A-Za-z0-9_\-]+")
_BASIC_RE = re.compile(r"Basic\s+[A-Za-z0-9+/=]+", re.IGNORECASE)


def _flag(name: str) -> str:
    return os.getenv(name, "").strip()


def _under_test() -> bool:
    if os.getenv("PYTEST_CURRENT_TEST"):
        return True
    argv = " ".join(sys.argv).lower()
    if "unittest" in argv or "pytest" in argv:
        return True
    return any(Path(part).name.startswith("test_") for part in sys.argv)


def tracing_enabled() -> bool:
    flag = _flag("AI_RECRUITER_TRACES").lower()
    if flag in {"0", "false", "no", "off"}:
        return False
    if flag in {"1", "true", "yes", "on"}:
        return True
    return not _under_test()


def langfuse_configured() -> bool:
    return bool(_flag("LANGFUSE_PUBLIC_KEY") and _flag("LANGFUSE_SECRET_KEY") and _flag("LANGFUSE_HOST"))


def langfuse_host() -> str:
    return _flag("LANGFUSE_HOST").rstrip("/")


def traces_dir() -> Path:
    raw = _flag("TRACES_DIR")
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parent / ".traces"


def trace_id_for(interview_id: str) -> str:
    cleaned = re.sub(r"[^0-9a-fA-F]", "", interview_id or "")
    if len(cleaned) >= 32:
        return cleaned[:32].lower()
    return uuid.uuid5(uuid.NAMESPACE_URL, interview_id or "interview").hex


def trace_url(trace_id: str | None) -> str | None:
    """Link Langfuse actually opens: ``/project/<projectId>/traces/<traceId>``."""
    if not trace_id or not langfuse_configured():
        return None
    project = cached_project_id()
    if not project:
        return None
    return f"{langfuse_host()}/project/{project}/traces/{trace_id}"


def mask_text(value: str) -> str:
    masked = _EMAIL.sub("[email]", value or "")

    def _phone(match: re.Match) -> str:
        digits = re.sub(r"\D", "", match.group(0))
        if 10 <= len(digits) <= 15:
            return "[phone]"
        return match.group(0)

    return _PHONE.sub(_phone, masked)


def _clip(value: str) -> str:
    if len(value) <= MAX_TEXT:
        return value
    extra = len(value) - MAX_TEXT
    return value[:MAX_TEXT] + f"... [{extra} more characters]"


def mask_value(value: Any) -> Any:
    if isinstance(value, str):
        return _clip(mask_text(value))
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, dict):
        return {str(key): mask_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [mask_value(item) for item in value]
    return _clip(mask_text(str(value)))


def price_table() -> dict:
    table = {key: dict(value) for key, value in DEFAULT_PRICES.items()}
    raw = _flag("MODEL_PRICES_JSON")
    if not raw:
        return table
    try:
        overlay = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("MODEL_PRICES_JSON could not be parsed. Using the built-in price table.")
        return table
    if not isinstance(overlay, dict):
        return table
    for model, rates in overlay.items():
        if isinstance(rates, dict):
            table[str(model)] = {
                "input_per_million": float(rates.get("input_per_million") or 0),
                "output_per_million": float(rates.get("output_per_million") or 0),
            }
    return table


def estimate_cost(model: str | None, input_tokens: int | None, output_tokens: int | None) -> float | None:
    if input_tokens is None and output_tokens is None:
        return None
    table = price_table()
    rates = table.get(model or "") or table.get("default")
    if not rates:
        return None
    cost = (input_tokens or 0) * float(rates.get("input_per_million") or 0) / 1_000_000
    cost += (output_tokens or 0) * float(rates.get("output_per_million") or 0) / 1_000_000
    return round(cost, 6)


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class _NullSpan:
    def set(self, **_attrs) -> None:
        return None

    def event(self, _name: str, **_attrs) -> None:
        return None

    def fail(self, _message: str) -> None:
        return None


class _Span:
    def __init__(self, name: str, parent_id: str | None, trace_id: str, session_id: str | None):
        self.name = name
        self.parent_id = parent_id
        self.trace_id = trace_id
        self.session_id = session_id
        self.span_id = uuid.uuid4().hex[:16]
        self.attributes: dict[str, Any] = {}
        self.events: list[dict] = []
        self.status = "OK"
        self.status_message = ""
        self.started = time.time()
        self.ended = self.started

    def set(self, **attrs) -> None:
        for key, value in attrs.items():
            if value is not None:
                self.attributes[key] = value

    def event(self, name: str, **attrs) -> None:
        self.events.append({"name": name, "attributes": {key: value for key, value in attrs.items() if value is not None}})

    def fail(self, message: str) -> None:
        self.status = "ERROR"
        self.status_message = str(message)[:300]


def _current() -> _Span | None:
    stack = _stack.get()
    if not stack:
        return None
    span = stack[-1]
    return span if isinstance(span, _Span) else None


def _ensure_log() -> list:
    log = _llm_log.get()
    if log is None:
        log = []
        _llm_log.set(log)
    return log


def remember_llm(record: dict) -> None:
    try:
        _ensure_log().append(dict(record))
    except Exception:
        logger.exception("Could not record LLM metadata")


def llm_mark() -> int:
    try:
        return len(_llm_log.get() or [])
    except Exception:
        return 0


def llm_since(mark: int) -> list:
    try:
        return list((_llm_log.get() or [])[mark:])
    except Exception:
        return []


def summarize_llm(calls: list, *, stub: bool = False, prompt_version: str | None = None) -> dict:
    if stub:
        return {
            "model": "stub",
            "latency_ms": 0,
            "cost_usd": 0.0,
            "prompt_version": prompt_version,
            "calls": 0,
            "fallback_used": None,
        }
    usable = list(calls or [])
    if not usable:
        return {
            "model": None,
            "latency_ms": None,
            "cost_usd": None,
            "prompt_version": prompt_version,
            "calls": 0,
            "fallback_used": None,
        }
    latency = sum(int(item.get("latency_ms") or 0) for item in usable)
    costs = [item.get("cost_usd") for item in usable if isinstance(item.get("cost_usd"), (int, float))]
    model = next((item.get("model") for item in usable if item.get("ok") and item.get("model")), None)
    if model is None:
        model = usable[-1].get("model")
    return {
        "model": model,
        "latency_ms": latency,
        "cost_usd": round(sum(costs), 6) if costs else None,
        "prompt_version": prompt_version,
        "calls": len(usable),
        "fallback_used": None,
    }


def remember(key: str, value: dict) -> None:
    try:
        notes = _notes.get()
        if notes is None:
            notes = {}
            _notes.set(notes)
        notes[key] = dict(value)
    except Exception:
        logger.exception("Could not remember trace summary")


def recall(key: str) -> dict | None:
    try:
        notes = _notes.get() or {}
        value = notes.get(key)
        return dict(value) if isinstance(value, dict) else None
    except Exception:
        logger.exception("Could not recall trace summary")
        return None


@contextmanager
def interview(interview_id: str) -> Iterator[str]:
    """Bind later spans to this interview. Safe to use when tracing is off."""
    tokens = []
    try:
        tokens.append((_session, _session.set(str(interview_id))))
        tokens.append((_llm_log, _llm_log.set([])))
        tokens.append((_notes, _notes.set({})))
        yield trace_id_for(interview_id)
    finally:
        for var, token in reversed(tokens):
            try:
                var.reset(token)
            except Exception:
                logger.exception("Could not reset interview trace context")


@contextmanager
def span(name: str, **attrs) -> Iterator[Any]:
    if not tracing_enabled():
        yield _NullSpan()
        return
    handle = None
    token = None
    try:
        parent = _current()
        session_id = _session.get()
        trace_id = trace_id_for(session_id) if session_id else uuid.uuid4().hex
        handle = _Span(name, parent.span_id if parent else None, trace_id, session_id)
        handle.set(**attrs)
        token = _stack.set(_stack.get() + (handle,))
    except Exception:
        logger.exception("Could not start span %s", name)
        yield _NullSpan()
        return
    try:
        yield handle
    except Exception as exc:
        try:
            handle.fail(exc.__class__.__name__)
        except Exception:
            logger.exception("Could not mark span %s failed", name)
        raise
    finally:
        try:
            handle.ended = time.time()
            _export(handle)
        except Exception:
            logger.exception("Could not export span %s", name)
        if token is not None:
            try:
                _stack.reset(token)
            except Exception:
                logger.exception("Could not close span %s", name)


def event(name: str, **attrs) -> None:
    try:
        current = _current()
        if current is not None:
            current.event(name, **attrs)
    except Exception:
        logger.exception("Could not record event %s", name)


def note_fallback(kind: str, detail: str = "") -> None:
    """Record an error event for a fallback. Never raises."""
    try:
        current = _current()
        if current is None:
            return
        safe_detail = mask_text(detail or "")[:300]
        current.set(fallback_used=kind)
        current.event("error", kind=kind, detail=safe_detail)
        if kind in {"scoring_unavailable", "default_questions"}:
            current.fail(f"fallback:{kind}")
    except Exception:
        logger.exception("Could not record fallback %s", kind)


def _span_dict(span_obj: _Span) -> dict:
    return {
        "trace_id": span_obj.trace_id,
        "span_id": span_obj.span_id,
        "parent_id": span_obj.parent_id,
        "session_id": span_obj.session_id,
        "name": span_obj.name,
        "start": _iso(span_obj.started),
        "end": _iso(span_obj.ended),
        "ms": round((span_obj.ended - span_obj.started) * 1000, 2),
        "status": span_obj.status,
        "status_message": mask_text(span_obj.status_message or ""),
        "attributes": mask_value(span_obj.attributes),
        "events": mask_value(span_obj.events),
    }


def _write_jsonl(payload: dict) -> None:
    folder = traces_dir()
    folder.mkdir(parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    line = json.dumps(payload, ensure_ascii=False, default=str) + "\n"
    with _file_lock, open(folder / f"{day}.jsonl", "a", encoding="utf-8") as handle:
        handle.write(line)


def load(trace_id: str, folder: Path | None = None) -> list[dict]:
    root = Path(folder or traces_dir())
    if not root.exists():
        return []
    spans = []
    for path in sorted(root.glob("*.jsonl")):
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if item.get("trace_id") == trace_id:
                    spans.append(item)
    return spans


def redact_langfuse_text(value: str) -> str:
    """Drop keys and Authorization headers before a Langfuse body is logged."""
    cleaned = _SECRET_RE.sub("[redacted-key]", value or "")
    cleaned = _BASIC_RE.sub("Basic [redacted]", cleaned)
    return cleaned[:2000]


def _auth_headers(*, otel: bool = False, content_type: bool = True) -> dict:
    token = base64.b64encode(f"{_flag('LANGFUSE_PUBLIC_KEY')}:{_flag('LANGFUSE_SECRET_KEY')}".encode()).decode()
    headers = {"Authorization": f"Basic {token}"}
    if content_type:
        headers["Content-Type"] = "application/json"
    if otel:
        headers["x-langfuse-ingestion-version"] = "4"
    return headers


def post_langfuse(url: str, body: dict | None, headers: dict, method: str = "POST") -> tuple[int, str]:
    """Return ``(status, body)``. HTTP errors are returned, not raised."""
    data = None if body is None or method == "GET" else json.dumps(body, default=str).encode()
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return int(response.status), raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return int(exc.code), raw
    except Exception as exc:
        return 0, exc.__class__.__name__


def langfuse_errors(status: int, body: str) -> tuple[bool, list[str]]:
    """Whether Langfuse accepted the call, plus messages safe to log.

    HTTP 207 is the legacy ingestion response. It is a failure when the body
    lists per-event errors, which is how trace events are rejected after the
    November 2026 sunset while the status still looks successful.
    """
    messages: list[str] = []
    parsed: Any = None
    if body:
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = None
    if isinstance(parsed, dict):
        errors = parsed.get("errors")
        if isinstance(errors, list):
            for item in errors:
                if isinstance(item, dict):
                    code = item.get("status")
                    detail = item.get("message") or item.get("error") or ""
                    label = item.get("error") or "error"
                    text = f"{label}: {detail}".strip(": ").strip()
                    try:
                        numeric = int(code) if code is not None else 400
                    except (TypeError, ValueError):
                        numeric = 400
                    if numeric >= 400:
                        messages.append(redact_langfuse_text(text or "event rejected"))
                elif item:
                    messages.append(redact_langfuse_text(str(item)))
        if status >= 400:
            for key in ("message", "error"):
                if parsed.get(key) and str(parsed[key]) not in messages:
                    messages.append(redact_langfuse_text(str(parsed[key])))
    if status >= 400 or status == 0:
        if not messages:
            messages.append(redact_langfuse_text(body or f"HTTP {status}"))
        return False, messages
    if messages:
        return False, messages
    if 200 <= status < 300:
        return True, []
    return False, [redact_langfuse_text(body or f"HTTP {status}")]


def _otel_value(value: Any) -> dict:
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return {"arrayValue": {"values": [{"stringValue": item} for item in value]}}
    if isinstance(value, (dict, list)):
        return {"stringValue": json.dumps(value, ensure_ascii=False, default=str)[:MAX_TEXT]}
    return {"stringValue": str(value)[:MAX_TEXT]}


def _otel_attributes(pairs: dict) -> list[dict]:
    attributes = []
    for key, value in pairs.items():
        if value is None:
            continue
        attributes.append({"key": key, "value": _otel_value(value)})
    return attributes


def _json_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def otel_traces(payload: dict) -> dict:
    """One finished span as an OTLP/HTTP JSON export body.

    Attribute names follow Langfuse's OpenTelemetry mapping: session id,
    observation type, model, token usage, and cost. Integer attributes use
    strings because OTLP JSON encodes int64 that way. Nulls are omitted.
    """
    attributes = payload.get("attributes") or {}
    is_generation = payload.get("name") == "llm.chat"
    pairs: dict[str, Any] = {
        "langfuse.observation.type": "generation" if is_generation else "span",
        "langfuse.trace.name": "interview",
        "langfuse.trace.tags": ["ai-recruiter"],
        "langfuse.session.id": payload.get("session_id"),
        "langfuse.observation.level": "ERROR" if payload.get("status") == "ERROR" else "DEFAULT",
        "langfuse.observation.status_message": payload.get("status_message") or None,
    }
    observed_input = attributes.get("prompt")
    if observed_input is None:
        observed_input = attributes.get("text")
    if observed_input is None:
        observed_input = attributes.get("transcript")
    pairs["langfuse.observation.input"] = _json_text(observed_input)
    pairs["langfuse.observation.output"] = _json_text(attributes.get("reply"))
    if attributes.get("model"):
        pairs["gen_ai.request.model"] = attributes["model"]
        pairs["langfuse.observation.model.name"] = attributes["model"]
    usage: dict[str, int] = {}
    if attributes.get("input_tokens") is not None:
        usage["input"] = int(attributes["input_tokens"])
        pairs["gen_ai.usage.input_tokens"] = usage["input"]
    if attributes.get("output_tokens") is not None:
        usage["output"] = int(attributes["output_tokens"])
        pairs["gen_ai.usage.output_tokens"] = usage["output"]
    if usage:
        pairs["langfuse.observation.usage_details"] = json.dumps(usage)
    if isinstance(attributes.get("cost_usd"), (int, float)):
        pairs["langfuse.observation.cost_details"] = json.dumps({"total": attributes["cost_usd"]})
    reserved = {
        "prompt",
        "reply",
        "text",
        "transcript",
        "model",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cost_usd",
    }
    for key, value in attributes.items():
        if key in reserved or value is None:
            continue
        pairs[f"langfuse.observation.metadata.{key}"] = value if isinstance(value, str) else json.dumps(value, default=str)
    started = float(payload.get("started") or time.time())
    ended = float(payload.get("ended") or started)
    if ended < started:
        ended = started
    span: dict[str, Any] = {
        "traceId": payload["trace_id"],
        "spanId": payload["span_id"],
        "name": payload.get("name") or "span",
        "startTimeUnixNano": str(int(started * 1_000_000_000)),
        "endTimeUnixNano": str(int(ended * 1_000_000_000)),
        "attributes": _otel_attributes(pairs),
        "status": {"code": 2 if payload.get("status") == "ERROR" else 1},
    }
    if payload.get("status_message"):
        span["status"]["message"] = redact_langfuse_text(str(payload["status_message"]))
    if payload.get("parent_id"):
        span["parentSpanId"] = payload["parent_id"]
    events = []
    for item in payload.get("events") or []:
        events.append(
            {
                "timeUnixNano": span["endTimeUnixNano"],
                "name": item.get("name") or "event",
                "attributes": _otel_attributes(item.get("attributes") or {}),
            }
        )
    if events:
        span["events"] = events
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": _otel_attributes({"service.name": SERVICE})},
                "scopeSpans": [{"scope": {"name": SERVICE}, "spans": [span]}],
            }
        ]
    }


def _export_payload(span_obj: _Span, payload: dict) -> dict:
    exported = dict(payload)
    exported["trace_id"] = span_obj.trace_id
    exported["span_id"] = span_obj.span_id
    exported["parent_id"] = span_obj.parent_id
    exported["session_id"] = span_obj.session_id
    exported["name"] = span_obj.name
    exported["started"] = span_obj.started
    exported["ended"] = span_obj.ended
    return exported


def _note_ingestion(status: int, ok: bool, errors: list[str]) -> None:
    global _logged_ingestion_success
    if ok:
        if not _logged_ingestion_success:
            _logged_ingestion_success = True
            logger.info("Langfuse ingestion accepted a span (HTTP %s)", status)
        return
    detail = "; ".join(errors) if errors else "no error body"
    logger.warning("Langfuse export was rejected (HTTP %s): %s", status, detail)


def _post_batch(batch: dict) -> tuple[bool, int, list[str]]:
    status, body = post_langfuse(
        langfuse_host() + "/api/public/otel/v1/traces",
        batch,
        _auth_headers(otel=True),
    )
    ok, errors = langfuse_errors(status, body)
    _note_ingestion(status, ok, errors)
    return ok, status, errors


def _ensure_worker() -> queue.Queue:
    global _queue, _worker_started
    with _worker_lock:
        if _queue is None:
            _queue = queue.Queue(maxsize=500)
        if not _worker_started:
            thread = threading.Thread(target=_worker, name="langfuse-export", daemon=True)
            thread.start()
            _worker_started = True
        return _queue


def _worker() -> None:
    assert _queue is not None
    while True:
        batch = _queue.get()
        try:
            _post_batch(batch)
        except Exception:
            logger.exception("Langfuse export failed")
        finally:
            _queue.task_done()


def _schedule_remote(batch: dict) -> None:
    if not langfuse_configured():
        return
    sync = _flag("LANGFUSE_SYNC").lower() in {"1", "true", "yes", "on"}
    if sync:
        _post_batch(batch)
        return
    sink = _ensure_worker()
    try:
        sink.put_nowait(batch)
    except queue.Full:
        logger.warning("Langfuse export queue is full. This span stayed in the local trace only.")


def _export(span_obj: _Span) -> None:
    payload = _span_dict(span_obj)
    try:
        _write_jsonl(payload)
    except Exception:
        logger.exception("Could not write the local trace")
    try:
        _schedule_remote(otel_traces(_export_payload(span_obj, payload)))
    except Exception:
        logger.exception("Could not schedule the Langfuse export")


def cached_project_id() -> str | None:
    host = langfuse_host()
    public = _flag("LANGFUSE_PUBLIC_KEY")
    cached = _project_cache
    if cached and cached[0] == host and cached[1] == public and cached[2]:
        return cached[2]
    return None


def _remember_project(project_id: str) -> None:
    global _project_cache
    _project_cache = (langfuse_host(), _flag("LANGFUSE_PUBLIC_KEY"), project_id)


def _project_id_from_body(body: str) -> str | None:
    try:
        parsed = json.loads(body) if body else None
    except json.JSONDecodeError:
        return None
    rows = None
    if isinstance(parsed, dict):
        rows = parsed.get("data") or parsed.get("projects")
        if isinstance(parsed.get("id"), str) and not rows:
            return parsed["id"]
    elif isinstance(parsed, list):
        rows = parsed
    if not isinstance(rows, list) or not rows:
        return None
    first = rows[0]
    if isinstance(first, dict) and isinstance(first.get("id"), str):
        return first["id"]
    return None


def fetch_project_id() -> tuple[bool, int, str | None, list[str]]:
    """GET /api/public/projects. Caches the id used in trace links."""
    if not langfuse_configured():
        return False, 0, None, ["Langfuse keys are not set"]
    known = cached_project_id()
    if known:
        return True, 200, known, []
    with _project_lock:
        known = cached_project_id()
        if known:
            return True, 200, known, []
        status, body = post_langfuse(
            langfuse_host() + "/api/public/projects",
            None,
            _auth_headers(content_type=False),
            method="GET",
        )
        ok, errors = langfuse_errors(status, body)
        project_id = _project_id_from_body(body) if ok else None
        if ok and not project_id:
            ok = False
            errors = ["Langfuse did not return a project id"]
        if ok and project_id:
            _remember_project(project_id)
            logger.info("Langfuse accepted the keys (HTTP %s, project %s)", status, project_id)
        elif not ok:
            logger.warning("Langfuse rejected the keys (HTTP %s): %s", status, "; ".join(errors))
        return ok, status, project_id, errors


def send_test_trace() -> dict:
    """Post one synthetic span and return Langfuse's status without secrets."""
    if not langfuse_configured():
        return {"ok": False, "configured": False, "http_status": None, "errors": ["Langfuse keys are not set"], "trace_id": None, "trace_url": None, "project_id": None}
    project_ok, project_status, project_id, project_errors = fetch_project_id()
    now = time.time()
    trace_id = uuid.uuid4().hex
    span_payload = {
        "trace_id": trace_id,
        "span_id": uuid.uuid4().hex[:16],
        "parent_id": None,
        "session_id": "langfuse-connectivity",
        "name": "langfuse.connectivity",
        "started": now,
        "ended": now,
        "status": "OK",
        "status_message": "",
        "attributes": {"text": "AI Recruiter Langfuse connectivity check"},
        "events": [],
    }
    ok, status, errors = _post_batch(otel_traces(span_payload))
    combined = []
    if not project_ok:
        combined.extend(project_errors)
    if not ok:
        combined.extend(errors)
    return {
        "ok": bool(ok and project_ok),
        "configured": True,
        "http_status": status,
        "project_http_status": project_status,
        "errors": combined,
        "trace_id": trace_id,
        "trace_url": f"{langfuse_host()}/project/{project_id}/traces/{trace_id}" if project_id else None,
        "project_id": project_id,
    }


def start_background_check() -> None:
    """Confirm the Langfuse keys once, without blocking process startup."""
    if not langfuse_configured():
        return

    def _run() -> None:
        try:
            fetch_project_id()
        except Exception:
            logger.exception("Langfuse startup check failed")

    threading.Thread(target=_run, name="langfuse-check", daemon=True).start()


def score(trace_id: str, name: str, value: bool | float | str, comment: str | None = None, score_id: str | None = None) -> bool:
    """Attach a score to a Langfuse trace. False when Langfuse is unset or the call fails."""
    if not langfuse_configured() or not trace_id:
        return False
    if isinstance(value, bool):
        kind = "BOOLEAN"
        sent: bool | float | str = float(value)
    elif isinstance(value, (int, float)):
        kind = "NUMERIC"
        sent = float(value)
    else:
        kind = "CATEGORICAL"
        sent = str(value)[:200]
    body = {
        "id": (score_id or f"{trace_id}-{name}")[:200],
        "traceId": trace_id,
        "name": name,
        "value": sent,
        "dataType": kind,
    }
    if comment:
        body["comment"] = mask_text(comment)[:1000]
    try:
        status, raw = post_langfuse(langfuse_host() + "/api/public/scores", body, _auth_headers())
        ok, errors = langfuse_errors(status, raw)
        if not ok:
            logger.warning("Langfuse score %s was rejected (HTTP %s): %s", name, status, "; ".join(errors))
        return ok
    except Exception:
        logger.exception("Could not send Langfuse score %s", name)
        return False


def record_recruiter_feedback(
    trace_id: str | None,
    *,
    response_id: str,
    vote: str,
    reason: str | None = None,
    score_override: float | None = None,
    note: str | None = None,
) -> bool:
    if not trace_id:
        return False
    comment_parts = [part for part in (reason, note, f"response {response_id}") if part]
    comment = "; ".join(comment_parts)
    posted = score(
        trace_id,
        "recruiter.vote",
        vote == "up",
        comment,
        score_id=f"{trace_id}-{response_id}-vote",
    )
    if reason:
        score(
            trace_id,
            "recruiter.reason",
            reason,
            comment,
            score_id=f"{trace_id}-{response_id}-reason",
        )
    if score_override is not None:
        score(
            trace_id,
            "recruiter.score_override",
            float(score_override),
            comment,
            score_id=f"{trace_id}-{response_id}-override",
        )
    return posted


def flush(timeout: float = 2.0) -> None:
    sink = _queue
    if sink is None:
        return
    deadline = time.time() + timeout
    while sink.unfinished_tasks and time.time() < deadline:
        time.sleep(0.05)


atexit.register(flush)
