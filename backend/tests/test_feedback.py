import io
import os
import unittest
import wave

os.environ["AI_STUB"] = "1"
os.environ["RECRUITER_PASSCODE"] = "smoke-pass"
os.environ["DATABASE_URL"] = "sqlite:////tmp/airec-unit.db"
os.environ["GROQ_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
os.environ["ELEVENLABS_API_KEY"] = ""
os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
os.environ.pop("LANGFUSE_SECRET_KEY", None)
os.environ.pop("LANGFUSE_HOST", None)

from fastapi.testclient import TestClient

from feedback_export import render_csv
from main import app


def _wav_bytes() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 1600)
    return buffer.getvalue()


class FeedbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def _answered_interview(self):
        created = self.client.post(
            "/mock-interview",
            data={
                "candidate_name": "Ada Lovelace",
                "jd_text": "Job Title: Product Manager\nOwn the checkout roadmap.",
                "resume_text": "Ada Lovelace\nada@example.com\nI led a checkout rewrite.",
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        interview_id = created.json()["interview_id"]
        answer = self.client.post(
            "/talk-video",
            data={"interview_id": interview_id},
            files={"file": ("answer.wav", _wav_bytes(), "audio/wav")},
        )
        self.assertEqual(answer.status_code, 200, answer.text)
        report = self.client.get(f"/interview/{interview_id}/results")
        self.assertEqual(report.status_code, 200, report.text)
        body = report.json()
        response = body["questions"][0]["responses"][0]
        return interview_id, body, response

    def test_feedback_is_stored_exported_and_shown_on_the_report(self):
        interview_id, body, response = self._answered_interview()
        self.assertEqual(response["model"], "stub")
        self.assertEqual(response["cost_usd"], 0)
        self.assertEqual(response["prompt_version"], "rubric-v1.1")
        self.assertIsNone(response["fallback_used"])
        self.assertEqual(response["confidence"]["level"], "high")
        self.assertTrue(response["confidence"]["checks"]["evidence_in_transcript"])
        self.assertEqual(body["observability"]["trace_id"], response["trace_id"])
        self.assertIsNone(body["observability"]["trace_url"])

        rejected = self.client.post(
            f"/interview/{interview_id}/responses/{response['id']}/feedback",
            json={"vote": "sideways"},
        )
        self.assertEqual(rejected.status_code, 400)

        saved = self.client.post(
            f"/interview/{interview_id}/responses/{response['id']}/feedback",
            json={
                "vote": "down",
                "reason": "evidence_not_in_answer",
                "score_override": 6,
                "note": "The quote is a paraphrase.",
            },
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertFalse(saved.json()["langfuse_score"])
        self.assertEqual(saved.json()["feedback"]["vote"], "down")
        self.assertEqual(saved.json()["feedback"]["score_override"], 6)

        again = self.client.post(
            f"/interview/{interview_id}/responses/{response['id']}/feedback",
            json={"vote": "up", "score_override": 11},
        )
        self.assertEqual(again.status_code, 400)

        report = self.client.get(f"/interview/{interview_id}/details")
        self.assertEqual(report.status_code, 200, report.text)
        shown = report.json()["questions"][0]["responses"][0]["feedback"]
        self.assertEqual(shown["vote"], "down")
        self.assertEqual(shown["reason"], "evidence_not_in_answer")

        exported = self.client.get("/recruiter/feedback.csv")
        self.assertEqual(exported.status_code, 200, exported.text)
        self.assertIn("text/csv", exported.headers["content-type"])
        self.assertIn(interview_id, exported.text)
        self.assertIn("evidence_not_in_answer", exported.text)
        self.assertIn(response["trace_id"], exported.text)
        self.assertIn("The quote is a paraphrase.", exported.text)

    def test_csv_quotes_commas(self):
        payload = render_csv(
            [
                {
                    "interview_id": "iv",
                    "response_id": "rs",
                    "trace_id": "tr",
                    "created_at": "2026-01-01T00:00:00",
                    "vote": "down",
                    "reason": "other",
                    "score_override": 4,
                    "note": "needs, a comma",
                    "model": "stub",
                    "latency_ms": 0,
                    "cost_usd": 0,
                    "fallback_used": "",
                    "prompt_version": "rubric-v1",
                    "question": 'Say "hello"',
                    "evidence": "",
                    "transcript": "line",
                }
            ]
        )
        self.assertIn('"needs, a comma"', payload)
        self.assertIn('"Say ""hello"""', payload)

    def test_langfuse_probe_reports_that_keys_are_missing(self):
        response = self.client.post("/recruiter/langfuse/test")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertFalse(body["configured"])
        self.assertFalse(body["ok"])
        self.assertNotIn("sk-", response.text)
        self.assertNotIn("pk-", response.text)


if __name__ == "__main__":
    unittest.main()
