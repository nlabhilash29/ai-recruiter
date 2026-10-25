import io
import os
import wave

# Configure the app before importing it. Empty provider keys keep the suite
# offline even if a developer .env is present. AI_STUB exercises the interview
# loop without calling Groq, OpenAI, or ElevenLabs.
os.environ["DATABASE_URL"] = "sqlite:////tmp/ai-recruiter-test.db"
os.environ["AI_STUB"] = "1"
os.environ["GROQ_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
os.environ["ELEVENLABS_API_KEY"] = ""
os.environ["GROQ_MODEL"] = "openai/gpt-oss-120b"
os.environ["ELEVENLABS_MODEL_ID"] = "eleven_flash_v2_5"

db_path = "/tmp/ai-recruiter-test.db"
if os.path.exists(db_path):
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


def test_retired_provider_models_are_not_the_defaults():
    assert "llama3-70b" not in GROQ_MODEL
    assert main.ELEVENLABS_MODEL_ID != "eleven_monolingual_v1"
    assert main.ELEVENLABS_MODEL_ID == "eleven_flash_v2_5"


def test_question_parser_accepts_markdown_labels():
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
    assert len(questions) == 5
    assert questions[0]["question_text"] == "How did you design the API?"
    assert questions[0]["question_type"] == "technical"

    analysis = parse_response_analysis("Relevance Score: 8/10\nClarity Score: 7\nTechnical Score: 6\nOverall Feedback: Clear example")
    assert analysis["relevance_score"] == 8
    assert analysis["feedback"] == "Clear example"


def test_root_and_cors_do_not_require_credentials():
    response = client.get("/", headers={"Origin": "https://ai-recruiter-tau.vercel.app"})
    assert response.status_code == 200
    assert response.json()["message"]
    assert response.headers["access-control-allow-origin"] == "*"
    assert response.headers.get("access-control-allow-credentials") != "true"


def test_recruiter_upload_edit_and_confirm_flow():
    jd = client.post(
        "/upload/jd",
        files={"file": ("jd.txt", b"Job Title: Backend Engineer\nCompany: Example Corp\nBuild reliable APIs.", "text/plain")},
    )
    assert jd.status_code == 200, jd.text
    assert jd.json()["title"] == "Backend Engineer"
    assert jd.json()["company"] == "Example Corp"

    resume = client.post(
        "/upload/resume",
        files={"file": ("resume.txt", b"Jane Doe\njane@example.com\nBackend engineer who ships APIs.\n", "text/plain")},
    )
    assert resume.status_code == 200, resume.text
    assert resume.json()["candidate_name"] == "Jane Doe"
    assert resume.json()["email"] == "jane@example.com"

    rejected = client.post(
        "/upload/jd",
        files={"file": ("notes.doc", b"legacy", "application/msword")},
    )
    assert rejected.status_code == 400

    untitled = client.post(
        "/upload/jd",
        files={"file": ("plain.txt", b"We need someone who can write Python services.", "text/plain")},
    )
    assert untitled.status_code == 200
    assert untitled.json()["title"] == "Untitled Position"
    assert untitled.json()["company"] == "Unknown Company"

    created = client.post(
        "/interview/create",
        data={"jd_id": jd.json()["jd_id"], "resume_id": resume.json()["resume_id"]},
    )
    assert created.status_code == 200, created.text
    interview_id = created.json()["interview_id"]
    assert len(created.json()["questions"]) == 5
    assert created.json()["status"] == "draft"

    not_ready = client.get(f"/interview/validate/{interview_id}")
    assert not_ready.status_code == 400
    assert not_ready.json()["valid"] is False

    question_id = created.json()["questions"][0]["id"]
    empty = client.put(f"/interview/questions/{question_id}", json={"question_text": "   "})
    assert empty.status_code == 400

    updated = client.put(
        f"/interview/questions/{question_id}",
        json={"question_text": "Walk me through an API you designed."},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["question_text"] == "Walk me through an API you designed."

    confirmed = client.post(f"/interview/{interview_id}/confirm")
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "ready"

    ready = client.get(f"/interview/validate/{interview_id}")
    assert ready.status_code == 200
    assert ready.json()["valid"] is True
    assert ready.json()["current_question"] == 0

    found = client.get("/interview/search", params={"candidate_name": "Jane"})
    assert found.status_code == 200
    assert any(item["interview_id"] == interview_id for item in found.json())


def test_mock_interview_and_video_loop_without_provider_keys():
    created = client.post("/mock-interview", data={"job_role": "Frontend Engineer"})
    assert created.status_code == 200, created.text
    interview_id = created.json()["interview_id"]
    assert len(created.json()["questions"]) == 5

    missing_key = client.post(
        "/talk-video",
        data={"interview_id": interview_id},
        files={"file": ("answer.wav", wav_bytes(), "audio/wav")},
        headers={"X-Test": "placeholder"},
    )
    # The suite enables AI_STUB, so this first call is the introduction.
    assert missing_key.status_code == 200, missing_key.text
    assert missing_key.headers["content-type"].startswith("audio/wav")
    assert missing_key.content.startswith(b"RIFF")
    assert missing_key.headers["x-interview-status"] == "in_progress"
    assert missing_key.headers["x-answered-questions"] == "0"
    assert missing_key.headers["x-current-question"] == "1"
    assert missing_key.headers["x-assistant-text"]

    resumed = client.get(f"/interview/validate/{interview_id}")
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "in_progress"
    assert resumed.json()["current_question"] == 1

    for expected_answer_count in range(1, 6):
        answer = client.post(
            "/talk-video",
            data={"interview_id": interview_id},
            files={"file": ("answer.webm", b"\x1a\x45\xdf\xa3" + b"\x00" * 32, "audio/webm")},
        )
        assert answer.status_code == 200, answer.text
        assert answer.headers["x-answered-questions"] == str(expected_answer_count)

    assert answer.headers["x-interview-status"] == "completed"

    details = client.get(f"/interview/{interview_id}/details")
    assert details.status_code == 200, details.text
    body = details.json()
    assert body["status"] == "completed"
    assert body["candidate"]["name"] == "Mock Candidate"
    assert len(body["questions"]) == 5
    assert all(question["responses"] for question in body["questions"])
    assert body["scoring"]["cultural_fit_score"] > 0
    assert body["scoring"]["technical_score"] > 0
    assert isinstance(body["interview_summary"]["strengths"], list)

    completed = client.get("/interview/check-completed")
    assert completed.json()["has_completed_interviews"] is True

    blocked = client.get(f"/interview/validate/{interview_id}")
    assert blocked.status_code == 400


def test_video_requires_openai_key_when_stub_is_off(monkeypatch):
    monkeypatch.setenv("AI_STUB", "0")
    created = client.post("/mock-interview", data={"job_role": "Data Analyst"})
    assert created.status_code == 200, created.text
    response = client.post(
        "/talk-video",
        data={"interview_id": created.json()["interview_id"]},
        files={"file": ("answer.wav", wav_bytes(), "audio/wav")},
    )
    assert response.status_code == 503
    assert "OPENAI_API_KEY" in response.json()["detail"]
