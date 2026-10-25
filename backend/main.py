from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy import or_
import logging
import os
import uuid
import requests
from datetime import datetime
from typing import Optional

from file_processing import process_jd_file, process_resume_file
from question_generation import analyze_response, generate_interview_questions, generate_job_description
from models import (
    CandidateResponse,
    CandidateResume,
    InterviewQuestion,
    InterviewSession,
    JobDescription,
)
from database import build_session_factory
from auth import TOKEN_TTL_SECONDS, issue_token, recruiter_passcode, require_recruiter
from settings import ELEVENLABS_API_KEY, OPENAI_API_KEY, ai_stub_enabled, missing_ai_keys

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_missing_keys = missing_ai_keys()
if _missing_keys:
    raise ValueError(
        "Missing environment variables: "
        + ", ".join(_missing_keys)
        + ". Set them, or set AI_STUB=1 to run without external AI services."
    )

app = FastAPI(title="AI Recruiter API")

_default_origins = [
    "https://ai-recruiter-one-sigma.vercel.app",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
]
_extra_origins = [item.strip() for item in os.getenv("CORS_ORIGINS", "").split(",") if item.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_default_origins + _extra_origins,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Interview-Status", "X-Total-Questions", "X-Answered-Questions"],
)

engine, SessionLocal, NORMALIZED_DATABASE_URL = build_session_factory()
logger.info("Database ready (%s)", NORMALIZED_DATABASE_URL.split("://", 1)[0])

ALLOWED_DOCUMENT_TYPES = {".pdf", ".docx", ".doc", ".txt", ".rtf"}
MAX_FILE_SIZE = 5 * 1024 * 1024
MAX_AUDIO_BYTES = 5 * 1024 * 1024
MOCK_CANDIDATE_NAME = "Mock Candidate"

_SILENCE_PATH = os.path.join(os.path.dirname(__file__), "assets", "silence.mp3")
with open(_SILENCE_PATH, "rb") as _silence_file:
    SILENT_MP3 = _silence_file.read()


class LoginBody(BaseModel):
    passcode: str


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/")
async def root():
    return {"message": "Welcome to the AI Recruiter API"}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/recruiter/login")
async def recruiter_login(body: LoginBody):
    expected = recruiter_passcode()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Recruiter access is not configured. Set RECRUITER_PASSCODE on the server.",
        )
    supplied = body.passcode or ""
    # compare_digest requires equal types; length differences return False.
    import hmac

    if not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="That passcode is incorrect.")
    return {
        "token": issue_token(expected),
        "token_type": "bearer",
        "expires_in": TOKEN_TTL_SECONDS,
    }


def validate_file(file: UploadFile, allowed_types: set, max_size: int) -> None:
    file_ext = os.path.splitext(file.filename or "")[1].lower()
    if file_ext not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed types are: {', '.join(sorted(allowed_types))}",
        )
    if not (file.content_type or "").startswith(("application/", "text/")):
        raise HTTPException(status_code=400, detail="Invalid content type. Must be a document file.")
    try:
        file_size = len(file.file.read())
        file.file.seek(0)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="The file could not be read.") from exc
    if file_size > max_size:
        raise HTTPException(
            status_code=400,
            detail=f"That file is too large. Please keep it under {max_size / 1024 / 1024:.0f} MB.",
        )


def _get_interview_or_404(db: Session, interview_id: str) -> InterviewSession:
    interview = (
        db.query(InterviewSession)
        .filter(InterviewSession.id == (interview_id or "").strip())
        .first()
    )
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    return interview


def _ordered_questions(interview: InterviewSession):
    return sorted(interview.questions, key=lambda question: question.sequence_number or 0)


def _is_mock(interview: InterviewSession) -> bool:
    resume = interview.candidate_resume
    return bool(resume and resume.candidate_name == MOCK_CANDIDATE_NAME)


def _mean(values):
    numbers = [float(value) for value in values if value is not None]
    if not numbers:
        return None
    return sum(numbers) / len(numbers)


def _recommendation(overall):
    if overall is None:
        return "Not enough answers to recommend yet"
    if overall >= 7:
        return "Recommended for next round"
    if overall < 5:
        return "Consider other candidates"
    return "Requires further evaluation"


def build_report(interview: InterviewSession, include_documents: bool = True) -> dict:
    questions = _ordered_questions(interview)
    questions_with_responses = []
    answered_questions = 0
    strengths = []
    improvements = []
    technical_values = []
    clarity_values = []
    cultural_values = []

    for question in questions:
        responses = []
        for response in question.responses:
            responses.append(
                {
                    "response_text": response.response_text,
                    "score": response.score,
                    "timestamp": response.timestamp.isoformat() if response.timestamp else None,
                    "ai_feedback": response.ai_feedback or "",
                    "technical_accuracy": response.technical_accuracy,
                    "clarity_score": response.clarity_score,
                    "improvement_suggestions": response.improvement_suggestions or "",
                    "keywords_matched": response.keywords_matched,
                }
            )
            if response.score is not None and response.score >= 8 and (response.ai_feedback or "").strip():
                strengths.append(response.ai_feedback.strip())
            if response.score is not None and response.score < 6 and (response.improvement_suggestions or "").strip():
                improvements.append(response.improvement_suggestions.strip())
            if response.technical_accuracy is not None:
                technical_values.append(response.technical_accuracy)
            if response.clarity_score is not None:
                clarity_values.append(response.clarity_score)
            if (question.question_type or "").lower() == "cultural-fit" and response.score is not None:
                cultural_values.append(response.score)
        if responses:
            answered_questions += 1
        questions_with_responses.append(
            {
                "id": question.id,
                "question_text": question.question_text,
                "question_type": question.question_type,
                "category": question.category,
                "sequence_number": question.sequence_number,
                "is_modified": question.is_modified,
                "original_question": question.original_question if question.is_modified else None,
                "expected_answer_keywords": question.expected_answer_keywords,
                "scoring_rubric": question.scoring_rubric,
                "responses": responses,
            }
        )

    total_questions = len(questions)
    technical = _mean(technical_values)
    communication = _mean(clarity_values)
    if technical is not None and communication is not None:
        overall = (technical + communication) / 2
    else:
        overall = technical if technical is not None else communication
    cultural = _mean(cultural_values)

    job = interview.job_description
    resume = interview.candidate_resume
    report = {
        "interview_id": interview.id,
        "status": interview.status,
        "is_mock": _is_mock(interview),
        "progress": {
            "total_questions": total_questions,
            "answered_questions": answered_questions,
            "completion_percentage": (answered_questions / total_questions * 100) if total_questions else 0,
        },
        "timing": {
            "created_at": interview.created_at.isoformat() if interview.created_at else None,
            "scheduled_datetime": interview.scheduled_datetime.isoformat() if interview.scheduled_datetime else None,
            "actual_start_time": interview.actual_start_time.isoformat() if interview.actual_start_time else None,
            "actual_end_time": interview.actual_end_time.isoformat() if interview.actual_end_time else None,
            "duration_minutes": (
                (interview.actual_end_time - interview.actual_start_time).total_seconds() / 60
                if interview.actual_end_time and interview.actual_start_time
                else None
            ),
        },
        "job_description": {
            "id": job.id if job else None,
            "title": job.title if job else None,
            "company": job.company if job else None,
        },
        "candidate": {
            "id": resume.id if resume else None,
            "name": resume.candidate_name if resume else None,
            "email": resume.email if resume else None,
        },
        "scoring": {
            "overall_score": overall,
            "technical_score": technical,
            "communication_score": communication,
            "cultural_fit_score": cultural,
            "score_scale": 10,
            "score_note": (
                "Each answer's score is how relevant that answer was, from 0 to 10. "
                "The overall score is the average of technical accuracy and communication (clarity) "
                "across every answer, also from 0 to 10. A single question can sit above or below the overall score."
            ),
        },
        "questions": questions_with_responses,
        "interview_summary": {
            "strengths": strengths,
            "areas_for_improvement": improvements,
            "overall_recommendation": _recommendation(overall if interview.status == "completed" else overall),
        },
    }
    if include_documents:
        report["job_description"]["content"] = job.content if job else None
        report["job_description"]["requirements"] = job.requirements if job else None
        report["candidate"]["skills"] = resume.skills if resume else None
        report["candidate"]["experience"] = resume.experience if resume else None
    return report


def _candidate_view(interview: InterviewSession) -> dict:
    questions = _ordered_questions(interview)
    answered = len(interview.responses or [])
    current = next((question for question in questions if question.sequence_number == answered + 1), None)
    ready = interview.status in {"ready", "in_progress"} and current is not None
    if interview.status == "completed":
        ready = False
        current = None
    return {
        "interview_id": interview.id,
        "status": interview.status,
        "job_title": interview.job_description.title if interview.job_description else None,
        "company": interview.job_description.company if interview.job_description else None,
        "is_mock": _is_mock(interview),
        "total_questions": len(questions),
        "answered_questions": min(answered, len(questions)),
        "current_question": None
        if not current
        else {
            "id": current.id,
            "sequence_number": current.sequence_number,
            "question_text": current.question_text,
            "question_type": current.question_type,
        },
        "ready": ready,
    }


@app.post("/upload/jd")
async def upload_jd(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: None = Depends(require_recruiter),
):
    try:
        validate_file(file, ALLOWED_DOCUMENT_TYPES, MAX_FILE_SIZE)
        processed_data = await process_jd_file(file)
        jd_id = str(uuid.uuid4())
        jd = JobDescription(
            id=jd_id,
            content=processed_data["content"],
            file_name=file.filename,
            file_type=os.path.splitext(file.filename or "")[1].lower(),
            title=processed_data["title"],
            company=processed_data["company"],
            requirements=processed_data.get("metadata", {}),
        )
        db.add(jd)
        db.commit()
        return {
            "jd_id": jd_id,
            "title": processed_data["title"],
            "company": processed_data["company"],
            "file_name": file.filename,
            "file_size": len(processed_data["content"]),
            "message": "Job description uploaded successfully",
        }
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.error("Error uploading JD: %s", exc)
        raise HTTPException(status_code=500, detail="The job description could not be processed.")
    finally:
        await file.close()


@app.post("/upload/resume")
async def upload_resume(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: None = Depends(require_recruiter),
):
    try:
        validate_file(file, ALLOWED_DOCUMENT_TYPES, MAX_FILE_SIZE)
        processed_data = await process_resume_file(file)
        resume_id = str(uuid.uuid4())
        resume = CandidateResume(
            id=resume_id,
            content=processed_data["content"],
            file_name=file.filename,
            file_type=os.path.splitext(file.filename or "")[1].lower(),
            candidate_name=processed_data["candidate_name"],
            email=processed_data["email"],
            skills=processed_data.get("skills", []),
            experience=processed_data.get("experience", []),
        )
        db.add(resume)
        db.commit()
        return {
            "resume_id": resume_id,
            "candidate_name": processed_data["candidate_name"],
            "email": processed_data["email"],
            "file_name": file.filename,
            "file_size": len(processed_data["content"]),
            "message": "Resume uploaded successfully",
        }
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.error("Error uploading resume: %s", exc)
        raise HTTPException(status_code=500, detail="The resume could not be processed.")
    finally:
        await file.close()


def _store_questions(db: Session, session_id: str, generated_questions):
    stored = []
    for idx, question_data in enumerate(generated_questions, 1):
        question = InterviewQuestion(
            id=str(uuid.uuid4()),
            interview_session_id=session_id,
            question_text=question_data["question_text"],
            question_type=question_data.get("question_type", "general"),
            category=question_data.get("assesses", "general"),
            sequence_number=idx,
            is_generated=True,
            expected_answer_keywords=question_data.get("key_points", ""),
            scoring_rubric={"key_points": question_data.get("key_points", [])},
        )
        db.add(question)
        stored.append(
            {
                "id": question.id,
                "question_text": question.question_text,
                "question_type": question.question_type,
                "category": question.category,
                "sequence_number": idx,
            }
        )
    return stored


@app.post("/interview/create")
async def create_interview_session(
    jd_id: str = Form(...),
    resume_id: str = Form(...),
    db: Session = Depends(get_db),
    _: None = Depends(require_recruiter),
):
    try:
        job_description = db.query(JobDescription).filter(JobDescription.id == jd_id).first()
        candidate_resume = db.query(CandidateResume).filter(CandidateResume.id == resume_id).first()
        if not job_description:
            raise HTTPException(status_code=404, detail="Job description not found")
        if not candidate_resume:
            raise HTTPException(status_code=404, detail="Resume not found")

        session_id = str(uuid.uuid4())
        interview_session = InterviewSession(
            id=session_id,
            jd_id=jd_id,
            resume_id=resume_id,
            status="draft",
            scheduled_datetime=datetime.utcnow(),
        )
        db.add(interview_session)
        db.flush()
        generated_questions = await generate_interview_questions(job_description.content, candidate_resume.content)
        questions = _store_questions(db, session_id, generated_questions)
        db.commit()
        return {
            "interview_id": session_id,
            "status": "draft",
            "candidate_name": candidate_resume.candidate_name,
            "job_title": job_description.title,
            "questions": questions,
            "message": "Interview session created with generated questions",
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.error("Error creating interview: %s", exc)
        raise HTTPException(status_code=500, detail="The interview could not be created.")


@app.get("/interview/{interview_id}/details")
async def get_interview_details(
    interview_id: str,
    db: Session = Depends(get_db),
    _: None = Depends(require_recruiter),
):
    try:
        interview_session = _get_interview_or_404(db, interview_id)
        return build_report(interview_session, include_documents=True)
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        logger.error("Database error getting interview details: %s", exc)
        raise HTTPException(status_code=500, detail="The interview report could not be loaded.")
    except Exception as exc:
        logger.error("Error getting interview details: %s", exc)
        raise HTTPException(status_code=500, detail="The interview report could not be loaded.")


@app.get("/interview/{interview_id}/results")
async def get_interview_results(
    interview_id: str,
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(default=None),
):
    """Practice interviews are readable with the link. Real reports need recruiter sign-in."""
    try:
        interview = _get_interview_or_404(db, interview_id)
        if not _is_mock(interview):
            require_recruiter(authorization)
        return build_report(interview, include_documents=False)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error getting interview results: %s", exc)
        raise HTTPException(status_code=500, detail="The interview report could not be loaded.")


@app.get("/interview/{interview_id}/session")
async def get_candidate_session(interview_id: str, db: Session = Depends(get_db)):
    interview = _get_interview_or_404(db, interview_id)
    return _candidate_view(interview)


@app.post("/interview/{interview_id}/speak")
async def speak_current_question(interview_id: str, db: Session = Depends(get_db)):
    interview = _get_interview_or_404(db, interview_id)
    view = _candidate_view(interview)
    if interview.status == "completed" or not view["current_question"]:
        raise HTTPException(status_code=400, detail="Interview is already completed")
    if not view["ready"]:
        raise HTTPException(status_code=400, detail="This interview is not ready yet.")
    audio_output = text_to_speech(view["current_question"]["question_text"])
    return StreamingResponse(iter([audio_output]), media_type="audio/mpeg")


@app.put("/interview/questions/{question_id}")
async def update_interview_question(
    question_id: str,
    question_update: dict,
    db: Session = Depends(get_db),
    _: None = Depends(require_recruiter),
):
    try:
        question = db.query(InterviewQuestion).filter(InterviewQuestion.id == question_id).first()
        if not question:
            raise HTTPException(status_code=404, detail="Question not found")
        if "question_text" in question_update:
            question.question_text = question_update["question_text"]
            question.is_modified = True
            question.modified_at = datetime.utcnow()
        db.commit()
        return {
            "id": question.id,
            "question_text": question.question_text,
            "question_type": question.question_type,
            "category": question.category,
            "sequence_number": question.sequence_number,
        }
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.error("Error updating question: %s", exc)
        raise HTTPException(status_code=500, detail="The question could not be saved.")


@app.post("/interview/{interview_id}/confirm")
async def confirm_interview_questions(
    interview_id: str,
    db: Session = Depends(get_db),
    _: None = Depends(require_recruiter),
):
    try:
        interview = _get_interview_or_404(db, interview_id)
        questions = (
            db.query(InterviewQuestion)
            .filter(InterviewQuestion.interview_session_id == interview.id)
            .all()
        )
        if len(questions) != 5:
            raise HTTPException(
                status_code=400,
                detail=f"Interview must have exactly 5 questions. Current count: {len(questions)}",
            )
        interview.status = "ready"
        interview.updated_at = datetime.utcnow()
        db.commit()
        return {
            "interview_id": interview.id,
            "status": "ready",
            "message": "Interview questions confirmed and ready for use",
            "total_questions": len(questions),
        }
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.error("Error confirming interview: %s", exc)
        raise HTTPException(status_code=500, detail="The interview could not be confirmed.")


@app.get("/interview/search")
async def search_interviews(
    candidate_name: str = None,
    company: str = None,
    status: str = None,
    q: str = None,
    date_from: datetime = None,
    date_to: datetime = None,
    db: Session = Depends(get_db),
    _: None = Depends(require_recruiter),
):
    query = db.query(InterviewSession).join(CandidateResume).join(JobDescription)
    if candidate_name:
        query = query.filter(CandidateResume.candidate_name.ilike(f"%{candidate_name}%"))
    if company:
        query = query.filter(JobDescription.company.ilike(f"%{company}%"))
    if status:
        query = query.filter(InterviewSession.status == status)
    if q and q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(
                CandidateResume.candidate_name.ilike(like),
                JobDescription.company.ilike(like),
                JobDescription.title.ilike(like),
                InterviewSession.id.ilike(like),
            )
        )
    if date_from:
        query = query.filter(InterviewSession.created_at >= date_from)
    if date_to:
        query = query.filter(InterviewSession.created_at <= date_to)
    interviews = query.order_by(InterviewSession.created_at.desc()).all()
    return [
        {
            "interview_id": interview.id,
            "candidate_name": interview.candidate_resume.candidate_name if interview.candidate_resume else None,
            "company": interview.job_description.company if interview.job_description else None,
            "job_title": interview.job_description.title if interview.job_description else None,
            "status": interview.status,
            "created_at": interview.created_at.isoformat() if interview.created_at else None,
            "overall_score": interview.overall_score,
            "is_mock": _is_mock(interview),
            "question_count": len(interview.questions or []),
            "answered_count": len(interview.responses or []),
        }
        for interview in interviews
    ]


def get_or_create_mock_resume(db: Session) -> CandidateResume:
    mock_resume = db.query(CandidateResume).filter(CandidateResume.candidate_name == MOCK_CANDIDATE_NAME).first()
    if not mock_resume:
        mock_resume = CandidateResume(
            id=str(uuid.uuid4()),
            candidate_name=MOCK_CANDIDATE_NAME,
            email="mock@candidate.com",
            content="This is a placeholder resume for practice interviews.",
            file_name="mock_resume.txt",
            file_type="generated",
        )
        db.add(mock_resume)
        db.commit()
    return mock_resume


@app.post("/mock-interview")
async def create_mock_interview(job_role: str = Form(...), db: Session = Depends(get_db)):
    try:
        role = (job_role or "").strip()
        if not role:
            raise HTTPException(status_code=400, detail="Please enter a job role.")
        jd_content = await generate_job_description(role)
        jd_id = str(uuid.uuid4())
        job_description = JobDescription(
            id=jd_id,
            title=role,
            company="Mock Company",
            content=jd_content,
            file_name=None,
            file_type="generated",
        )
        db.add(job_description)
        db.flush()
        generated_questions = await generate_interview_questions(jd_content, resume_content="Mock Candidate")
        mock_resume = get_or_create_mock_resume(db)
        session_id = str(uuid.uuid4())
        interview_session = InterviewSession(
            id=session_id,
            jd_id=jd_id,
            resume_id=mock_resume.id,
            status="ready",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(interview_session)
        db.flush()
        _store_questions(db, session_id, generated_questions)
        db.commit()
        return {
            "interview_id": session_id,
            "job_role": role,
            "questions": generated_questions,
            "message": "Practice interview created.",
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.error("Error creating mock interview: %s", exc)
        raise HTTPException(status_code=500, detail="The practice interview could not be created.")


def _finish_scores(db: Session, interview_session: InterviewSession) -> None:
    responses = (
        db.query(CandidateResponse)
        .filter(CandidateResponse.interview_session_id == interview_session.id)
        .all()
    )
    if not responses:
        return
    interview_session.technical_score = sum(r.technical_accuracy or 0 for r in responses) / len(responses)
    interview_session.communication_score = sum(r.clarity_score or 0 for r in responses) / len(responses)
    interview_session.overall_score = (
        interview_session.technical_score + interview_session.communication_score
    ) / 2
    cultural = []
    for response in responses:
        question = response.question
        if question and (question.question_type or "").lower() == "cultural-fit" and response.score is not None:
            cultural.append(response.score)
    if cultural:
        interview_session.cultural_fit_score = sum(cultural) / len(cultural)


@app.post("/talk-video")
async def process_video(
    file: UploadFile = File(...),
    interview_id: str = Form(...),
    db: Session = Depends(get_db),
):
    """Transcribe the candidate's audio and score it. Video is not accepted or stored."""
    try:
        interview_session = _get_interview_or_404(db, interview_id)
        content = await file.read()
        if len(content) > MAX_AUDIO_BYTES:
            raise HTTPException(
                status_code=400,
                detail="That file is too large. Please keep recordings under 5 MB.",
            )
        if not content:
            raise HTTPException(status_code=400, detail="The recording was empty. Please record again.")

        all_questions = (
            db.query(InterviewQuestion)
            .filter(InterviewQuestion.interview_session_id == interview_session.id)
            .order_by(InterviewQuestion.sequence_number)
            .all()
        )
        if not all_questions:
            raise HTTPException(status_code=400, detail="No questions found for this interview")
        if interview_session.status == "completed":
            raise HTTPException(status_code=400, detail="Interview is already completed")
        if interview_session.status == "draft":
            raise HTTPException(status_code=400, detail="This interview is not ready yet.")

        answered_questions = (
            db.query(CandidateResponse)
            .filter(CandidateResponse.interview_session_id == interview_session.id)
            .count()
        )
        if answered_questions >= len(all_questions):
            interview_session.status = "completed"
            db.commit()
            raise HTTPException(status_code=400, detail="Interview is already completed")

        if interview_session.status != "in_progress":
            interview_session.status = "in_progress"
            interview_session.actual_start_time = datetime.utcnow()

        user_message = await transcribe_audio_bytes(content, file.filename or "answer.webm", file.content_type or "")
        current_question = next(
            (question for question in all_questions if question.sequence_number == answered_questions + 1),
            None,
        )
        if current_question is None:
            raise HTTPException(status_code=400, detail="Interview is already completed")

        response = CandidateResponse(
            interview_session_id=interview_session.id,
            question_id=current_question.id,
            response_text=user_message,
            response_audio_url="",
            timestamp=datetime.utcnow(),
        )
        db.add(response)
        analysis = await analyze_response(current_question.question_text, user_message)
        response.score = analysis.get("relevance_score", 0)
        response.technical_accuracy = analysis.get("technical_score", 0)
        response.clarity_score = analysis.get("clarity_score", 0)
        response.ai_feedback = analysis.get("feedback", "")
        response.improvement_suggestions = analysis.get("improvement_areas", "")

        if answered_questions + 1 >= len(all_questions):
            interview_session.status = "completed"
            interview_session.actual_end_time = datetime.utcnow()
            db.flush()
            _finish_scores(db, interview_session)
            ai_response = (
                "Thank you for completing the interview. Your responses have been recorded. "
                "We will review them and get back to you soon. Have a great day!"
            )
        else:
            next_question = next(
                (question for question in all_questions if question.sequence_number == answered_questions + 2),
                None,
            )
            if next_question:
                ai_response = f"Thank you for your response. Here's your next question: {next_question.question_text}"
            else:
                ai_response = "Thank you for your response."

        db.commit()
        audio_output = text_to_speech(ai_response)
        headers = {
            "X-Interview-Status": interview_session.status,
            "X-Total-Questions": str(len(all_questions)),
            "X-Answered-Questions": str(answered_questions + 1),
            "Access-Control-Expose-Headers": "X-Interview-Status, X-Total-Questions, X-Answered-Questions",
        }
        return StreamingResponse(iter([audio_output]), media_type="audio/mpeg", headers=headers)
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.error("Error processing video: %s", exc)
        raise HTTPException(status_code=500, detail="The answer could not be processed. Please try again.")


@app.get("/interview/check-completed")
async def check_completed_interviews(
    db: Session = Depends(get_db),
    _: None = Depends(require_recruiter),
):
    try:
        completed_count = db.query(InterviewSession).filter(InterviewSession.status == "completed").count()
        return {"has_completed_interviews": completed_count > 0}
    except Exception as exc:
        logger.error("Error checking completed interviews: %s", exc)
        raise HTTPException(status_code=500, detail="Completed interviews could not be checked.")


@app.get("/interview/validate/{interview_id}")
async def validate_interview_id(interview_id: str, db: Session = Depends(get_db)):
    try:
        interview = (
            db.query(InterviewSession)
            .filter(InterviewSession.id == interview_id.strip())
            .first()
        )
        if not interview:
            return JSONResponse(status_code=404, content={"valid": False, "message": "Interview not found"})
        if interview.status not in {"ready", "in_progress"}:
            return JSONResponse(
                status_code=400,
                content={
                    "valid": False,
                    "message": f"Interview is not ready (current status: {interview.status})",
                },
            )
        questions = (
            db.query(InterviewQuestion)
            .filter(InterviewQuestion.interview_session_id == interview.id)
            .all()
        )
        if not questions or len(questions) != 5:
            return JSONResponse(
                status_code=400,
                content={"valid": False, "message": "Interview is not properly set up (missing questions)"},
            )
        return {
            "valid": True,
            "message": "Interview ID is valid and ready to start",
            "total_questions": len(questions),
            "status": interview.status,
        }
    except Exception as exc:
        logger.error("Error validating interview ID: %s", exc)
        raise HTTPException(status_code=500, detail="The interview could not be validated.")


def _audio_suffix(content: bytes, filename: str, content_type: str) -> str:
    name = (filename or "").lower()
    ctype = (content_type or "").lower()
    if content[:4] == b"RIFF" or name.endswith(".wav") or "wav" in ctype:
        return ".wav"
    if name.endswith(".mp3") or "mpeg" in ctype or content[:3] == b"ID3":
        return ".mp3"
    if name.endswith(".m4a") or name.endswith(".mp4") or "mp4" in ctype:
        return ".m4a"
    return ".webm"


async def transcribe_audio_bytes(content: bytes, filename: str = "answer.webm", content_type: str = "") -> str:
    if ai_stub_enabled():
        return (
            "I led the work to build an AI interview product. I broke the problem into transcription, "
            "scoring, and a clear candidate experience, and I checked the result against real interviews."
        )
    suffix = _audio_suffix(content, filename, content_type)
    temp_file_path = f"temp_{uuid.uuid4()}{suffix}"
    try:
        with open(temp_file_path, "wb") as temp_file:
            temp_file.write(content)
        with open(temp_file_path, "rb") as audio_file:
            response = requests.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                files={"file": (os.path.basename(temp_file_path), audio_file, content_type or "application/octet-stream")},
                data={"model": "whisper-1", "response_format": "text", "language": "en"},
                timeout=90,
            )
        if response.status_code == 200:
            transcription = (response.text or "").strip()
            if not transcription:
                raise HTTPException(status_code=502, detail="The transcription service returned an empty transcript. Please try again.")
            return transcription
        logger.error("Whisper error %s: %s", response.status_code, response.text[:500])
        if response.status_code in (401, 403):
            raise HTTPException(
                status_code=502,
                detail="The transcription service is having trouble right now. Please try again in a moment.",
            )
        if response.status_code == 429:
            raise HTTPException(status_code=429, detail="The transcription service is busy right now. Please wait a moment and try again.")
        raise HTTPException(
            status_code=502,
            detail="The transcription service is having trouble right now. Please try again in a moment.",
        )
    except HTTPException:
        raise
    except requests.Timeout as exc:
        logger.error("Transcription timed out: %s", exc)
        raise HTTPException(status_code=504, detail="Transcription timed out. Please try again.")
    except requests.RequestException as exc:
        logger.error("Transcription network error: %s", exc)
        raise HTTPException(status_code=502, detail="The transcription service could not be reached. Please try again.")
    finally:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)


def text_to_speech(text: str) -> bytes:
    if ai_stub_enabled():
        return SILENT_MP3
    url = "https://api.elevenlabs.io/v1/text-to-speech/pNInz6obpgDQGcFmaJgB"
    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": ELEVENLABS_API_KEY,
    }
    data = {
        "text": text,
        "model_id": "eleven_monolingual_v1",
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.5,
            "style": 0.5,
            "use_speaker_boost": True,
        },
    }
    try:
        response = requests.post(url, json=data, headers=headers, timeout=60)
        if response.status_code == 200 and response.content:
            return response.content
        logger.error("ElevenLabs API error: %s", response.status_code)
        if response.status_code == 429:
            raise HTTPException(status_code=429, detail="The voice service is busy right now. Please wait a moment and try again.")
        raise HTTPException(
            status_code=502,
            detail="The voice service is having trouble right now. Please try again in a moment.",
        )
    except HTTPException:
        raise
    except requests.Timeout as exc:
        logger.error("Text-to-speech timed out: %s", exc)
        raise HTTPException(status_code=504, detail="The voice service timed out. Please try again.")
    except requests.RequestException as exc:
        logger.error("Text-to-speech network error: %s", exc)
        raise HTTPException(status_code=502, detail="The voice service could not be reached. Please try again.")


def load_messages(session_id, role):
    session_file = f"sessions/{session_id}.json"
    if os.path.exists(session_file) and os.stat(session_file).st_size > 0:
        import json

        with open(session_file) as db_file:
            return json.load(db_file)
    return [
        {
            "role": "system",
            "content": (
                f"You are ai-recruiter, an experienced interviewer conducting a preliminary interview for the role of {role}."
            ),
        }
    ]


def save_messages(session_id, messages):
    import json

    os.makedirs("sessions", exist_ok=True)
    with open(f"sessions/{session_id}.json", "w") as handle:
        json.dump(messages, handle)


def extract_question(ai_response):
    sentences = ai_response.split(".")
    questions = []
    for sentence in sentences:
        sentence = sentence.strip()
        if "?" in sentence:
            if not sentence.endswith("?"):
                sentence += "?"
            questions.append(sentence)
    if questions:
        return questions[-1]
    return "No explicit question found in the AI response."


if __name__ == "__main__":
    import uvicorn

    logger.info("Starting the FastAPI server")
    uvicorn.run(app, host="0.0.0.0", port=8000)
