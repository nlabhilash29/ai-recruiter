"""One trace per interview.

The trace id is the interview id with dashes removed, so every request in that
interview lands on the same trace. The Langfuse session id is the interview id.

Spans are written to a local JSONL file whenever tracing is on. They are also
posted to Langfuse's public ingestion API when ``LANGFUSE_PUBLIC_KEY``,
``LANGFUSE_SECRET_KEY``, and ``LANGFUSE_HOST`` are all set. That is the same
API the Langfuse Python SDK uses. A failed export is logged and swallowed:
tracing never changes the interview response.

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
    if not trace_id or not langfuse_configured():
        return None
    return f"{langfuse_host()}/trace/{trace_id}"


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


def _langfuse_headers() -> dict:
    token = base64.b64encode(f"{_flag('LANGFUSE_PUBLIC_KEY')}:{_flag('LANGFUSE_SECRET_KEY')}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}


def post_langfuse(url: str, body: dict, headers: dict) -> int:
    request = urllib.request.Request(url, data=json.dumps(body, default=str).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=3) as response:
        return int(response.status)


def _langfuse_batch(span_obj: _Span, payload: dict) -> dict:
    attributes = payload["attributes"]
    metadata = {
        key: value
        for key, value in attributes.items()
        if key not in {"prompt", "reply", "transcript", "text"}
    }
    level = "ERROR" if payload["status"] == "ERROR" else "DEFAULT"
    observation = {
        "id": span_obj.span_id,
        "traceId": span_obj.trace_id,
        "name": span_obj.name,
        "startTime": payload["start"],
        "endTime": payload["end"],
        "metadata": metadata,
        "level": level,
        "statusMessage": payload["status_message"] or None,
    }
    if span_obj.parent_id:
        observation["parentObservationId"] = span_obj.parent_id
    if span_obj.name == "llm.chat":
        observation["input"] = attributes.get("prompt")
        observation["output"] = attributes.get("reply")
        observation["model"] = attributes.get("model")
        usage = {}
        if attributes.get("input_tokens") is not None:
            usage["input"] = attributes.get("input_tokens")
        if attributes.get("output_tokens") is not None:
            usage["output"] = attributes.get("output_tokens")
        if attributes.get("total_tokens") is not None:
            usage["total"] = attributes.get("total_tokens")
        if attributes.get("cost_usd") is not None:
            usage["totalCost"] = attributes.get("cost_usd")
        if usage:
            usage["unit"] = "TOKENS"
            observation["usage"] = usage
        event_type = "generation-create"
    else:
        observation["input"] = attributes.get("prompt") or attributes.get("text") or attributes.get("transcript")
        observation["output"] = attributes.get("reply")
        event_type = "span-create"
    batch = [
        {
            "id": str(uuid.uuid4()),
            "type": "trace-create",
            "timestamp": payload["start"],
            "body": {
                "id": span_obj.trace_id,
                "timestamp": payload["start"],
                "name": "interview",
                "sessionId": span_obj.session_id,
                "tags": ["ai-recruiter"],
                "metadata": {"service": SERVICE},
            },
        },
        {
            "id": str(uuid.uuid4()),
            "type": event_type,
            "timestamp": payload["start"],
            "body": observation,
        },
    ]
    for item in payload["events"]:
        batch.append(
            {
                "id": str(uuid.uuid4()),
                "type": "event-create",
                "timestamp": payload["end"],
                "body": {
                    "id": uuid.uuid4().hex[:16],
                    "traceId": span_obj.trace_id,
                    "parentObservationId": span_obj.span_id,
                    "name": item.get("name") or "event",
                    "startTime": payload["end"],
                    "metadata": item.get("attributes") or {},
                    "level": "ERROR" if item.get("name") == "error" else "DEFAULT",
                },
            }
        )
    return {"batch": batch}


def _post_batch(batch: dict) -> None:
    post_langfuse(langfuse_host() + "/api/public/ingestion", batch, _langfuse_headers())


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
        _schedule_remote(_langfuse_batch(span_obj, payload))
    except Exception:
        logger.exception("Could not schedule the Langfuse export")


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
        status = post_langfuse(langfuse_host() + "/api/public/scores", body, _langfuse_headers())
        return 200 <= status < 300
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
