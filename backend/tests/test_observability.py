import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, inspect, text

from database import ensure_columns
import observability
from observability import estimate_cost, load, mask_text, trace_id_for


class MaskAndCostTests(unittest.TestCase):
    def test_masks_email_and_phone_and_leaves_scores_alone(self):
        text = "Email ada@example.com or call (415) 555-0199 about the 8.5 score in 2024."
        masked = mask_text(text)
        self.assertNotIn("ada@example.com", masked)
        self.assertNotIn("555-0199", masked)
        self.assertIn("[email]", masked)
        self.assertIn("[phone]", masked)
        self.assertIn("8.5", masked)
        self.assertIn("2024", masked)

    def test_price_table_is_configurable(self):
        self.assertEqual(estimate_cost("openai/gpt-oss-120b", 1_000_000, 2_000_000), 1.35)
        self.assertIsNone(estimate_cost("openai/gpt-oss-120b", None, None))
        previous = os.environ.get("MODEL_PRICES_JSON")
        os.environ["MODEL_PRICES_JSON"] = '{"custom-model":{"input_per_million":2,"output_per_million":4}}'
        try:
            self.assertEqual(estimate_cost("custom-model", 1_000_000, 500_000), 4.0)
        finally:
            if previous is None:
                os.environ.pop("MODEL_PRICES_JSON", None)
            else:
                os.environ["MODEL_PRICES_JSON"] = previous

    def test_trace_id_follows_the_interview_id(self):
        interview_id = "12345678-1234-1234-1234-123456789abc"
        self.assertEqual(trace_id_for(interview_id), "12345678123412341234123456789abc")
        self.assertEqual(len(trace_id_for("practice")), 32)


class TraceTests(unittest.TestCase):
    def setUp(self):
        self.previous = {
            name: os.environ.get(name)
            for name in (
                "AI_RECRUITER_TRACES",
                "TRACES_DIR",
                "LANGFUSE_PUBLIC_KEY",
                "LANGFUSE_SECRET_KEY",
                "LANGFUSE_HOST",
                "LANGFUSE_SYNC",
            )
        }
        self.folder = tempfile.mkdtemp(prefix="airec-traces-")
        os.environ["TRACES_DIR"] = self.folder
        os.environ["AI_RECRUITER_TRACES"] = "1"
        os.environ["LANGFUSE_SYNC"] = "1"
        for name in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST"):
            os.environ.pop(name, None)

    def tearDown(self):
        for name, value in self.previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_tracing_is_off_under_unittest_until_enabled(self):
        os.environ.pop("AI_RECRUITER_TRACES", None)
        self.assertFalse(observability.tracing_enabled())
        os.environ["AI_RECRUITER_TRACES"] = "1"
        self.assertTrue(observability.tracing_enabled())

    def test_span_writes_jsonl_and_masks_the_prompt(self):
        with observability.interview("12345678-1234-1234-1234-123456789abc"):
            with observability.span("llm.chat", model="openai/gpt-oss-120b") as current:
                current.set(prompt="Reach me at ada@example.com or 415-555-0199", reply="Thanks")
                current.event("fallback", kind="structured_output", path="json_object")
        trace_id = trace_id_for("12345678-1234-1234-1234-123456789abc")
        spans = load(trace_id, self.folder)
        self.assertEqual([item["name"] for item in spans], ["llm.chat"])
        self.assertEqual(spans[0]["session_id"], "12345678-1234-1234-1234-123456789abc")
        prompt = spans[0]["attributes"]["prompt"]
        self.assertNotIn("ada@example.com", prompt)
        self.assertNotIn("415-555-0199", prompt)
        self.assertEqual(spans[0]["events"][0]["attributes"]["path"], "json_object")

    def test_fallback_emits_an_error_event(self):
        with observability.interview("interview-fallback"):
            with observability.span("scoring"):
                observability.note_fallback("scoring_unavailable", "RuntimeError")
                observability.note_fallback("thin_analysis", "short answer")
        spans = load(trace_id_for("interview-fallback"), self.folder)
        events = spans[0]["events"]
        kinds = [event["attributes"]["kind"] for event in events if event["name"] == "error"]
        self.assertEqual(kinds, ["scoring_unavailable", "thin_analysis"])
        self.assertEqual(spans[0]["status"], "ERROR")

    def test_a_failing_export_does_not_raise(self):
        with patch("observability._write_jsonl", side_effect=OSError("disk full")):
            with observability.span("tts") as current:
                current.set(text="hello")

    def test_langfuse_post_includes_usage_and_is_skipped_without_keys(self):
        self.assertFalse(observability.langfuse_configured())
        self.assertFalse(observability.score("abc", "recruiter.vote", True))
        os.environ["LANGFUSE_PUBLIC_KEY"] = "pk-test"
        os.environ["LANGFUSE_SECRET_KEY"] = "sk-test"
        os.environ["LANGFUSE_HOST"] = "https://cloud.langfuse.com"
        posts = []

        def fake_post(url, body, headers):
            posts.append((url, body, headers))
            return 207

        with patch("observability.post_langfuse", side_effect=fake_post):
            with observability.interview("12345678-1234-1234-1234-123456789abc"):
                with observability.span("llm.chat", model="openai/gpt-oss-120b") as current:
                    current.set(prompt="hello", reply="world", input_tokens=20, output_tokens=10, cost_usd=0.000012)
            posted = observability.record_recruiter_feedback(
                trace_id_for("12345678-1234-1234-1234-123456789abc"),
                response_id="response-1",
                vote="down",
                reason="score_too_high",
                score_override=6,
                note="Quote was not in the answer",
            )
        self.assertTrue(posted)
        ingestion = [item for item in posts if item[0].endswith("/api/public/ingestion")]
        self.assertTrue(ingestion)
        batch = ingestion[0][1]["batch"]
        types = [event["type"] for event in batch]
        self.assertIn("trace-create", types)
        self.assertIn("generation-create", types)
        generation = next(event["body"] for event in batch if event["type"] == "generation-create")
        self.assertEqual(generation["usage"]["input"], 20)
        self.assertEqual(generation["usage"]["output"], 10)
        self.assertEqual(generation["model"], "openai/gpt-oss-120b")
        scores = [item for item in posts if item[0].endswith("/api/public/scores")]
        self.assertEqual(len(scores), 3)
        self.assertTrue(ingestion[0][2]["Authorization"].startswith("Basic "))


class SchemaTests(unittest.TestCase):
    def test_trace_columns_are_added_on_sqlite(self):
        engine = create_engine("sqlite://")
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE interview_sessions (id VARCHAR(36) PRIMARY KEY)"))
            connection.execute(text("CREATE TABLE interview_questions (id VARCHAR(36) PRIMARY KEY)"))
            connection.execute(text("CREATE TABLE candidate_responses (id VARCHAR(36) PRIMARY KEY)"))
        ensure_columns(engine)
        ensure_columns(engine)
        response_columns = {column["name"] for column in inspect(engine).get_columns("candidate_responses")}
        session_columns = {column["name"] for column in inspect(engine).get_columns("interview_sessions")}
        for name in ("trace_id", "prompt_version", "model", "latency_ms", "cost_usd", "fallback_used"):
            self.assertIn(name, response_columns)
            self.assertIn(name, session_columns)


if __name__ == "__main__":
    unittest.main()
