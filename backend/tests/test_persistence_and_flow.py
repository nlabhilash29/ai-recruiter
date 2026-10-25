import io
import os
import sys
import unittest
import wave

# Configure before the app imports its database and AI clients.
# test_api.py uses the same file. Do not delete it once the app is imported,
# or the two modules end up pointing at a removed database.
os.environ["AI_STUB"] = "1"
os.environ["RECRUITER_PASSCODE"] = "smoke-pass"
db_path = "/tmp/airec-unit.db"
os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
os.environ["GROQ_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
os.environ["ELEVENLABS_API_KEY"] = ""

if "main" not in sys.modules and os.path.exists(db_path):
    os.remove(db_path)

from fastapi.testclient import TestClient

from auth import issue_token, token_is_valid
from database import normalize_database_url
from main import app
from models import InterviewSession


def _wav_bytes() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 1600)
    return buffer.getvalue()


class DatabaseUrlTests(unittest.TestCase):
    def test_render_postgres_scheme_is_normalized(self):
        self.assertEqual(
            normalize_database_url("postgres://user:p@host:5432/app"),
            "postgresql+psycopg2://user:p@host:5432/app",
        )

    def test_postgresql_scheme_gets_driver(self):
        self.assertTrue(
            normalize_database_url("postgresql://user:p@host/app").startswith("postgresql+psycopg2://")
        )

    def test_sqlite_default(self):
        self.assertEqual(normalize_database_url(""), "sqlite:///./test.db")
        self.assertEqual(normalize_database_url("sqlite:///./local.db"), "sqlite:///./local.db")


class TokenTests(unittest.TestCase):
    def test_round_trip(self):
        token = issue_token("smoke-pass", now=1_700_000_000)
        self.assertTrue(token_is_valid(token, "smoke-pass", now=1_700_000_100))
        self.assertFalse(token_is_valid(token, "other-pass", now=1_700_000_100))
        self.assertFalse(token_is_valid(token, "smoke-pass", now=1_700_000_000 + 13 * 60 * 60))


class InterviewFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_fresh_database_has_no_sample_interviews(self):
        from database import build_session_factory

        path = "/tmp/airec-empty-check.db"
        if os.path.exists(path):
            os.remove(path)
        _, factory, _ = build_session_factory(f"sqlite:///{path}")
        db = factory()
        try:
            self.assertEqual(db.query(InterviewSession).count(), 0)
        finally:
            db.close()

    def test_recruiter_is_closed_without_configuration_and_without_a_token(self):
        previous = os.environ.pop("RECRUITER_PASSCODE")
        try:
            response = self.client.post("/recruiter/login", json={"passcode": "anything"})
            self.assertEqual(response.status_code, 503)
            self.assertIn("RECRUITER_PASSCODE", response.json()["detail"])
            blocked = self.client.get("/interview/search")
            self.assertEqual(blocked.status_code, 503)
        finally:
            os.environ["RECRUITER_PASSCODE"] = previous

    def test_mock_interview_answer_and_report(self):
        created = self.client.post("/mock-interview", data={"job_role": "Backend Engineer"})
        self.assertEqual(created.status_code, 200, created.text)
        interview_id = created.json()["interview_id"]

        session = self.client.get(f"/interview/{interview_id}/session")
        self.assertEqual(session.status_code, 200, session.text)
        body = session.json()
        self.assertTrue(body["ready"])
        self.assertTrue(body["is_mock"])
        self.assertEqual(body["current_question"]["sequence_number"], 1)
        self.assertTrue(body["current_question"]["question_text"])

        spoken = self.client.post(f"/interview/{interview_id}/speak")
        self.assertEqual(spoken.status_code, 200, spoken.text)
        self.assertGreater(len(spoken.content), 100)

        anonymous = self.client.get("/interview/search")
        self.assertEqual(anonymous.status_code, 401)

        login = self.client.post("/recruiter/login", json={"passcode": "nope"})
        self.assertEqual(login.status_code, 401)
        login = self.client.post("/recruiter/login", json={"passcode": "smoke-pass"})
        self.assertEqual(login.status_code, 200, login.text)
        token = login.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        for expected in range(1, 6):
            answer = self.client.post(
                "/talk-video",
                data={"interview_id": interview_id},
                files={"file": ("answer.wav", _wav_bytes(), "audio/wav")},
            )
            self.assertEqual(answer.status_code, 200, answer.text)
            self.assertEqual(answer.headers["x-answered-questions"], str(expected))
            self.assertGreater(len(answer.content), 100)

        again = self.client.post(
            "/talk-video",
            data={"interview_id": interview_id},
            files={"file": ("answer.wav", _wav_bytes(), "audio/wav")},
        )
        self.assertEqual(again.status_code, 400)
        self.assertIn("already completed", again.json()["detail"].lower())

        report = self.client.get(f"/interview/{interview_id}/results")
        self.assertEqual(report.status_code, 200, report.text)
        payload = report.json()
        self.assertEqual(payload["status"], "completed")
        self.assertIsNotNone(payload["scoring"]["overall_score"])
        self.assertIsNotNone(payload["scoring"]["cultural_fit_score"])
        self.assertEqual(len(payload["questions"]), 5)
        for question in payload["questions"]:
            response = question["responses"][0]
            self.assertTrue(response["ai_feedback"].strip())
            self.assertTrue(response["improvement_suggestions"].strip())

        hidden = self.client.get(f"/interview/{interview_id}/details")
        self.assertEqual(hidden.status_code, 401)
        visible = self.client.get(f"/interview/{interview_id}/details", headers=headers)
        self.assertEqual(visible.status_code, 200, visible.text)

        listing = self.client.get("/interview/search", headers=headers, params={"q": "Backend"})
        self.assertEqual(listing.status_code, 200, listing.text)
        self.assertTrue(any(item["interview_id"] == interview_id for item in listing.json()))

        filtered = self.client.get("/interview/search", headers=headers, params={"status": "completed"})
        self.assertTrue(filtered.json())

    def test_recruiter_can_create_a_real_interview_the_candidate_cannot_report(self):
        login = self.client.post("/recruiter/login", json={"passcode": "smoke-pass"})
        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        jd = self.client.post(
            "/upload/jd",
            headers=headers,
            files={"file": ("jd.txt", b"Job Title: Platform Engineer\nCompany: Northwind\nBuild APIs.", "text/plain")},
        )
        self.assertEqual(jd.status_code, 200, jd.text)
        resume = self.client.post(
            "/upload/resume",
            headers=headers,
            files={"file": ("resume.txt", b"Ada Lovelace\nada@example.com\nBuilt compilers.", "text/plain")},
        )
        self.assertEqual(resume.status_code, 200, resume.text)
        created = self.client.post(
            "/interview/create",
            headers=headers,
            data={"jd_id": jd.json()["jd_id"], "resume_id": resume.json()["resume_id"]},
        )
        self.assertEqual(created.status_code, 200, created.text)
        interview_id = created.json()["interview_id"]
        confirmed = self.client.post(f"/interview/{interview_id}/confirm", headers=headers)
        self.assertEqual(confirmed.status_code, 200, confirmed.text)

        blocked = self.client.get(f"/interview/{interview_id}/results")
        self.assertEqual(blocked.status_code, 401)
        opened = self.client.get(f"/interview/{interview_id}/session")
        self.assertEqual(opened.status_code, 200, opened.text)
        self.assertFalse(opened.json()["is_mock"])
        self.assertTrue(opened.json()["ready"])
        self.assertIn("question_text", opened.json()["current_question"])


if __name__ == "__main__":
    unittest.main()
