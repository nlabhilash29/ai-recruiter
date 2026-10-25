"""Deployment fixes from the provider-model update, checked against the current API.

The first recording is the answer to question 1. The candidate page shows that
question before recording, so it is scored rather than stored as an introduction.
"""

import io
import os
import sys
import unittest
import wave

os.environ["AI_STUB"] = "1"
os.environ["RECRUITER_PASSCODE"] = "smoke-pass"
db_path = "/tmp/airec-unit.db"
os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
os.environ["GROQ_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
os.environ["ELEVENLABS_API_KEY"] = ""
os.environ["GROQ_MODEL"] = "openai/gpt-oss-120b"
os.environ["ELEVENLABS_MODEL_ID"] = "eleven_flash_v2_5"

if "main" not in sys.modules and os.path.exists(db_path):
    os.remove(db_path)

from fastapi.testclient import TestClient

import main
from question_generation import GROQ_MODEL, parse_generated_questions, parse_response_analysis

client = TestClient(main.app)


def wav_bytes():
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(8000)
        wav_file.writeframes(b"\x00\x00" * 800)
    return buffer.getvalue()


def auth_headers():
    login = client.post("/recruiter/login", json={"passcode": "smoke-pass"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['token']}"}


class ProviderConfigurationTests(unittest.TestCase):
    def test_retired_provider_models_are_not_the_defaults(self):
        self.assertNotIn("llama3-70b", GROQ_MODEL)
        self.assertNotEqual(main.ELEVENLABS_MODEL_ID, "eleven_monolingual_v1")
        self.assertEqual(main.ELEVENLABS_MODEL_ID, "eleven_flash_v2_5")
        self.assertTrue(main.ELEVENLABS_VOICE_ID)

    def test_recordings_keep_their_real_whisper_type(self):
        self.assertEqual(main.audio_extension(b"RIFF" + b"\x00" * 20, "answer.webm", "audio/webm"), "wav")
        self.assertEqual(main.audio_media_type("wav"), "audio/wav")
        webm = b"\x1a\x45\xdf\xa3" + b"\x00" * 32
        self.assertEqual(main.audio_extension(webm, "answer.webm", "audio/webm"), "webm")
        self.assertEqual(main.audio_media_type("webm"), "audio/webm")
        self.assertEqual(main.audio_extension(b"ID3" + b"\x00" * 16, "answer.mp3", ""), "mp3")
        self.assertEqual(main.audio_media_type("mp3"), "audio/mpeg")

    def test_question_parser_accepts_markdown_labels(self):
        text = """
        **1. Question:** How did you design the API?
           **Type:** technical
           **Assesses:** API design
           **Key Points:** contracts, errors, versioning
        2. Question: Tell me about a launch you owned.
           Type: experience
           Assesses: ownership
           Key Points: scope, tradeoffs, result
        3. Question: How would you debug a timeout?
           Type: problem-solving
           Assesses: debugging
           Key Points: evidence, hypothesis, fix
        4. Question: How do you handle disagreement?
           Type: behavioral
           Assesses: collaboration
           Key Points: listening, decision, follow-through
        5. Question: What kind of team do you do your best work with?
           Type: cultural-fit
           Assesses: working style
           Key Points: feedback, pace, ownership
        """
        questions = parse_generated_questions(text)
        self.assertEqual(len(questions), 5)
        self.assertEqual(questions[0]["question_text"], "How did you design the API?")
        self.assertEqual(questions[0]["question_type"], "technical")

        analysis = parse_response_analysis(
            "Relevance Score: 8/10\nClarity Score: 7\nTechnical Score: 6\nOverall Feedback: Clear example"
        )
        self.assertEqual(analysis["relevance_score"], 8)
        self.assertEqual(analysis["feedback"], "Clear example")

    def test_root_and_cors_do_not_require_credentials(self):
        response = client.get("/", headers={"Origin": "https://ai-recruiter-one-sigma.vercel.app"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["message"])
        self.assertEqual(response.headers["access-control-allow-origin"], "https://ai-recruiter-one-sigma.vercel.app")
        self.assertNotEqual(response.headers.get("access-control-allow-credentials"), "true")


class RecruiterDocumentFlowTests(unittest.TestCase):
    def test_recruiter_upload_edit_and_confirm_flow(self):
        headers = auth_headers()
        jd = client.post(
            "/upload/jd",
            headers=headers,
            files={"file": ("jd.txt", b"Job Title: Backend Engineer\nCompany: Example Corp\nBuild reliable APIs.", "text/plain")},
        )
        self.assertEqual(jd.status_code, 200, jd.text)
        self.assertEqual(jd.json()["title"], "Backend Engineer")
        self.assertEqual(jd.json()["company"], "Example Corp")

        resume = client.post(
            "/upload/resume",
            headers=headers,
            files={"file": ("resume.txt", b"Jane Doe\njane@example.com\nBackend engineer who ships APIs.\n", "text/plain")},
        )
        self.assertEqual(resume.status_code, 200, resume.text)
        self.assertEqual(resume.json()["candidate_name"], "Jane Doe")
        self.assertEqual(resume.json()["email"], "jane@example.com")

        rejected = client.post(
            "/upload/jd",
            headers=headers,
            files={"file": ("notes.doc", b"legacy", "application/msword")},
        )
        self.assertEqual(rejected.status_code, 400)

        untitled = client.post(
            "/upload/jd",
            headers=headers,
            files={"file": ("plain.txt", b"We need someone who can write Python services.", "text/plain")},
        )
        self.assertEqual(untitled.status_code, 200, untitled.text)
        self.assertEqual(untitled.json()["title"], "Untitled Position")
        self.assertEqual(untitled.json()["company"], "Unknown Company")

        missing_type = client.post(
            "/upload/jd",
            headers=headers,
            files={"file": ("plain.txt", b"Job Title: Analyst\nCompany: Contoso\nNotes.", "")},
        )
        self.assertEqual(missing_type.status_code, 200, missing_type.text)

        created = client.post(
            "/interview/create",
            headers=headers,
            data={
                "jd_id": jd.json()["jd_id"],
                "resume_id": resume.json()["resume_id"],
                "question_mode": "preset",
                "main_question_target": "4",
                "role_family": "sales",
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        interview_id = created.json()["interview_id"]
        self.assertEqual(created.json()["question_mode"], "dynamic")
        self.assertEqual(created.json()["status"], "ready")
        self.assertEqual(created.json()["main_question_target"], 5)
        self.assertEqual(created.json()["role_family"], "software_developer")
        self.assertEqual(len(created.json()["questions"]), 1)
        self.assertEqual(len(created.json()["evaluation"]), 5)
        self.assertTrue(created.json()["message"])

        ready = client.get(f"/interview/validate/{interview_id}")
        self.assertEqual(ready.status_code, 200)
        self.assertTrue(ready.json()["valid"])

        question_id = created.json()["questions"][0]["id"]
        empty = client.put(
            f"/interview/questions/{question_id}",
            headers=headers,
            json={"question_text": "   "},
        )
        self.assertEqual(empty.status_code, 400)

        updated = client.put(
            f"/interview/questions/{question_id}",
            headers=headers,
            json={"question_text": "Walk me through an API you designed."},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["question_text"], "Walk me through an API you designed.")

        confirmed = client.post(f"/interview/{interview_id}/confirm", headers=headers)
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertEqual(confirmed.json()["status"], "ready")

        found = client.get("/interview/search", headers=headers, params={"candidate_name": "Jane"})
        self.assertEqual(found.status_code, 200, found.text)
        self.assertTrue(any(item["interview_id"] == interview_id for item in found.json()))


def practice_documents(**overrides):
    data = {
        "candidate_name": "Alex Rivera",
        "jd_text": "Job Title: Frontend Engineer\nCompany: Example\nBuild user interfaces.",
        "resume_text": "Alex Rivera\nalex@example.com\nFrontend engineer who ships UI.",
    }
    data.update(overrides)
    return data


class InterviewLoopTests(unittest.TestCase):
    def test_mock_interview_scores_each_answer_without_provider_keys(self):
        created = client.post("/mock-interview", data=practice_documents())
        self.assertEqual(created.status_code, 200, created.text)
        interview_id = created.json()["interview_id"]
        self.assertEqual(created.json()["question_mode"], "dynamic")
        self.assertEqual(created.json()["main_question_target"], 5)
        self.assertEqual(len(created.json()["questions"]), 1)

        for expected_answer_count in range(1, 6):
            answer = client.post(
                "/talk-video",
                data={"interview_id": interview_id},
                files={"file": ("answer.wav", wav_bytes(), "audio/wav")},
            )
            self.assertEqual(answer.status_code, 200, answer.text)
            self.assertTrue(answer.headers["content-type"].startswith("audio/mpeg"))
            self.assertTrue(answer.content.startswith(b"ID3"))
            self.assertEqual(answer.headers["x-answered-questions"], str(expected_answer_count))

        self.assertEqual(answer.headers["x-interview-status"], "completed")

        login = auth_headers()
        details = client.get(f"/interview/{interview_id}/details", headers=login)
        self.assertEqual(details.status_code, 200, details.text)
        body = details.json()
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["candidate"]["name"], "Alex Rivera")
        self.assertEqual(len(body["questions"]), 5)
        self.assertTrue(all(question["responses"] for question in body["questions"]))
        self.assertGreater(body["scoring"]["cultural_fit_score"], 0)
        self.assertGreater(body["scoring"]["technical_score"], 0)
        self.assertIsInstance(body["interview_summary"]["strengths"], list)

        blocked = client.get(f"/interview/validate/{interview_id}")
        self.assertEqual(blocked.status_code, 400)
        self.assertFalse(body["scoring"]["legacy"])
        self.assertGreater(body["scoring"]["dimension_scores"]["communication"], 0)
        self.assertIn("advance", body["interview_summary"]["overall_recommendation"].lower())

    def test_no_speech_moves_on_without_a_score(self):
        created = client.post(
            "/mock-interview",
            data=practice_documents(
                jd_text="Job Title: Product Manager\nPrioritize the roadmap and talk to customers.",
                resume_text="I led a checkout rewrite with design and engineering.",
                main_question_target="3",
                role_family="product_manager",
            ),
        )
        self.assertEqual(created.status_code, 200, created.text)
        interview_id = created.json()["interview_id"]
        answer = client.post(
            "/talk-video",
            data={"interview_id": interview_id, "no_speech": "true"},
            files={"file": ("empty.wav", b"", "audio/wav")},
        )
        self.assertEqual(answer.status_code, 200, answer.text)
        self.assertEqual(answer.headers["x-interview-status"], "in_progress")
        self.assertEqual(answer.headers["x-answered-questions"], "1")
        session = client.get(f"/interview/{interview_id}/session")
        self.assertEqual(session.json()["current_question"]["main_index"], 2)
        self.assertEqual(session.json()["current_question"]["progress_label"], "Question 2 of 5")
        report = client.get(f"/interview/{interview_id}/results")
        response = report.json()["questions"][0]["responses"][0]
        self.assertIn("not scored", response["ai_feedback"].lower())
        self.assertTrue(response["improvement_suggestions"].strip())
        self.assertIsNone(response["score"])

    def test_practice_ignores_preset_and_uses_optional_text(self):
        created = client.post(
            "/mock-interview",
            data={
                "job_role": "",
                "jd_text": "Product manager for the checkout team. Prioritize the roadmap.",
                "resume_text": "I shipped a checkout rewrite with design and engineering.",
                "candidate_name": "Ada Lovelace",
                "question_mode": "preset",
                "main_question_target": "8",
                "role_family": "sales",
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(created.json()["question_mode"], "dynamic")
        self.assertEqual(created.json()["main_question_target"], 5)
        self.assertEqual(created.json()["role_family"], "product_manager")
        self.assertEqual(len(created.json()["questions"]), 1)
        self.assertEqual(len(created.json()["evaluation"]), 5)

    def test_candidate_name_and_short_role_title(self):
        long_jd = (
            "We are hiring a product manager who will own the checkout roadmap and work with "
            "design and engineering every day to ship the right things for customers across the company."
        )
        missing_name = client.post(
            "/mock-interview",
            data={"jd_text": long_jd, "resume_text": "I shipped a checkout rewrite."},
        )
        self.assertEqual(missing_name.status_code, 400)
        self.assertIn("name", missing_name.json()["detail"].lower())

        created = client.post(
            "/mock-interview",
            data={
                "candidate_name": "Ada Lovelace",
                "jd_text": long_jd,
                "resume_text": "I shipped a checkout rewrite with design and engineering.",
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        self.assertLessEqual(len(created.json()["job_title"]), 60)
        self.assertNotIn("engineering every day", created.json()["job_title"])
        interview_id = created.json()["interview_id"]
        report = client.get(f"/interview/{interview_id}/results")
        self.assertEqual(report.status_code, 200, report.text)
        self.assertEqual(report.json()["candidate"]["name"], "Ada Lovelace")
        self.assertLessEqual(len(report.json()["job_description"]["title"]), 60)

        headers = auth_headers()
        recruiter = client.post(
            "/interview/create",
            headers=headers,
            data={
                "jd_text": "Job Title: Backend Engineer\nCompany: Example Corp\nBuild reliable APIs.",
                "resume_text": "Name missing on the resume body.",
            },
        )
        self.assertEqual(recruiter.status_code, 200, recruiter.text)
        named = client.post(
            f"/interview/{recruiter.json()['interview_id']}/candidate",
            data={"candidate_name": "Grace Hopper"},
        )
        self.assertEqual(named.status_code, 200, named.text)
        session = client.get(f"/interview/{recruiter.json()['interview_id']}/session")
        self.assertEqual(session.json()["candidate_name"], "Grace Hopper")
        self.assertEqual(session.json()["job_title"], "Backend Engineer")

        sentence = client.post(
            "/mock-interview",
            data={
                "candidate_name": "Ada Lovelace",
                "jd_text": "Product manager for the checkout team. Own the roadmap and prioritize experiments with design.",
                "resume_text": "Led a checkout redesign that raised completion.",
            },
        )
        self.assertEqual(sentence.status_code, 200, sentence.text)
        self.assertEqual(sentence.json()["job_title"], "Product manager for the checkout team")

    def test_practice_and_create_require_both_documents(self):
        role_only = client.post("/mock-interview", data={"job_role": "Frontend Engineer"})
        self.assertEqual(role_only.status_code, 400)
        self.assertIn("resume", role_only.json()["detail"].lower())
        self.assertIn("job description", role_only.json()["detail"].lower())

        resume_only = client.post("/mock-interview", data={"resume_text": "I shipped a product."})
        self.assertEqual(resume_only.status_code, 400)

        headers = auth_headers()
        missing = client.post(
            "/interview/create",
            headers=headers,
            data={"jd_text": "Build reliable APIs for the billing team."},
        )
        self.assertEqual(missing.status_code, 400)
        self.assertIn("resume", missing.json()["detail"].lower())

        created = client.post(
            "/interview/create",
            headers=headers,
            data={
                "jd_text": "Job Title: Backend Engineer\nCompany: Example Corp\nBuild reliable APIs.",
                "resume_text": "Jane Doe\njane@example.com\nBackend engineer who ships APIs.",
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(created.json()["question_mode"], "dynamic")
        self.assertEqual(created.json()["main_question_target"], 5)
        self.assertEqual(created.json()["candidate_name"], "Jane Doe")
        self.assertEqual(created.json()["job_title"], "Backend Engineer")

    def test_video_requires_openai_key_when_stub_is_off(self):
        previous = os.environ.get("AI_STUB")
        os.environ["AI_STUB"] = "0"
        try:
            created = client.post(
                "/mock-interview",
                data=practice_documents(
                    jd_text="Job Title: Data Analyst\nMeasure product usage.",
                    resume_text="Sam Lee\nsam@example.com\nData analyst.",
                ),
            )
            self.assertEqual(created.status_code, 200, created.text)
            response = client.post(
                "/talk-video",
                data={"interview_id": created.json()["interview_id"]},
                files={"file": ("answer.wav", wav_bytes(), "audio/wav")},
            )
            self.assertEqual(response.status_code, 503)
            self.assertIn("OPENAI_API_KEY", response.json()["detail"])
        finally:
            if previous is None:
                os.environ.pop("AI_STUB", None)
            else:
                os.environ["AI_STUB"] = previous


if __name__ == "__main__":
    unittest.main()
