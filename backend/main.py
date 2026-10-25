from fastapi import FastAPI, UploadFile, Depends, HTTPException, Query, File, Form
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError
from dotenv import load_dotenv
import os
import logging
from groq import Groq
import json
import requests
import uuid
from typing import List, Optional, Set
import shutil
from datetime import datetime
import base64
import io
import math
import struct
import wave

# Import custom modules
from file_processing import process_jd_file, process_resume_file
from question_generation import (
    AIConfigurationError,
    ai_stub_enabled,
    analyze_response,
    complete_chat,
    generate_interview_questions,
)

# Import models
from models import (
    Base, JobDescription, CandidateResume, InterviewSession,
    InterviewQuestion, CandidateResponse, init_db
)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Initialize FastAPI app
app = FastAPI(title="AI Recruiter API")

@app.get("/")
async def root():
    return {"message": "Welcome to the AI Recruiter API"}

# Wildcard origins cannot be combined with credentialed CORS. This API uses
# no cookies, so reflect every origin without Allow-Credentials.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database setup
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./test.db")
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Initialize database
init_db(engine)

# API keys are optional at startup. Routes that call a provider return 503
# with the missing variable named, unless AI_STUB=1 is set for local demos.
GROQ_API_KEY = (os.getenv("GROQ_API_KEY") or "").strip() or None
ELEVENLABS_API_KEY = (os.getenv("ELEVENLABS_API_KEY") or "").strip() or None
OPENAI_API_KEY = (os.getenv("OPENAI_API_KEY") or "").strip() or None
# eleven_monolingual_v1 was removed on 2026-07-09.
ELEVENLABS_MODEL_ID = (os.getenv("ELEVENLABS_MODEL_ID") or "eleven_flash_v2_5").strip()
ELEVENLABS_VOICE_ID = (os.getenv("ELEVENLABS_VOICE_ID") or "pNInz6obpgDQGcFmaJgB").strip()

for missing_name, missing_value in (
    ("OPENAI_API_KEY", OPENAI_API_KEY),
    ("GROQ_API_KEY", GROQ_API_KEY),
    ("ELEVENLABS_API_KEY", ELEVENLABS_API_KEY),
):
    if not missing_value:
        logger.warning("%s is not set. Endpoints that need it will fail until it is configured.", missing_name)

# Initialize Groq client only when a key is present.
client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# Constants for file validation
ALLOWED_DOCUMENT_TYPES: Set[str] = {'.pdf', '.docx', '.txt'}
MAX_FILE_SIZE: int = 5 * 1024 * 1024  # 5 MB in bytes

# Dependency to get database session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def validate_file(file: UploadFile, allowed_types: Set[str], max_size: int) -> None:
    """
    Validate file type and size
    """
    # Check file extension
    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed types are: {', '.join(allowed_types)}"
        )
    
    # Check content type. Browsers sometimes omit it or send octet-stream
    # for otherwise valid documents, so only reject an explicit mismatch.
    content_type = (file.content_type or "").lower()
    if content_type and not content_type.startswith(('application/', 'text/')):
        raise HTTPException(
            status_code=400,
            detail="Invalid content type. Must be a document file."
        )
    
    # Check file size (requires reading the file into memory)
    file_size = 0
    try:
        file_size = len(file.file.read())
        file.file.seek(0)  # Reset file pointer to beginning
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Error reading file: {str(e)}"
        )
    
    if file_size > max_size:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size allowed is {max_size/1024/1024:.1f}MB"
        )

@app.post("/upload/jd")
async def upload_jd(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    Upload and process a job description document with enhanced data extraction
    """
    try:
        # Validate file before processing
        validate_file(file, ALLOWED_DOCUMENT_TYPES, MAX_FILE_SIZE)
        
        # Process file content with enhanced extraction
        processed_data = await process_jd_file(file)
        jd_id = str(uuid.uuid4())
        
        # Create job description record with extracted information
        jd = JobDescription(
            id=jd_id,
            content=processed_data["content"],
            file_name=file.filename,
            file_type=os.path.splitext(file.filename)[1].lower(),
            title=processed_data["title"],
            company=processed_data["company"],
            requirements=processed_data.get("metadata", {})
        )
        
        db.add(jd)
        db.commit()
        
        return {
            "jd_id": jd_id,
            "title": processed_data["title"],
            "company": processed_data["company"],
            "file_name": file.filename,
            "file_size": len(processed_data["content"]),
            "message": "Job description uploaded successfully"
        }
        
    except HTTPException as he:
        raise he
    except Exception as e:
        db.rollback()
        logger.error(f"Error uploading JD: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error processing job description: {str(e)}"
        )
    finally:
        await file.close()

@app.post("/upload/resume")
async def upload_resume(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    Upload and process a resume with enhanced candidate information extraction
    """
    try:
        # Validate file before processing
        validate_file(file, ALLOWED_DOCUMENT_TYPES, MAX_FILE_SIZE)
        
        # Process file content with enhanced extraction
        processed_data = await process_resume_file(file)
        resume_id = str(uuid.uuid4())
        
        # Create resume record with extracted information
        resume = CandidateResume(
            id=resume_id,
            content=processed_data["content"],
            file_name=file.filename,
            file_type=os.path.splitext(file.filename)[1].lower(),
            candidate_name=processed_data["candidate_name"],
            email=processed_data["email"],
            skills=processed_data.get("skills", []),
            experience=processed_data.get("experience", [])
        )
        
        db.add(resume)
        db.commit()
        
        return {
            "resume_id": resume_id,
            "candidate_name": processed_data["candidate_name"],
            "email": processed_data["email"],
            "file_name": file.filename,
            "file_size": len(processed_data["content"]),
            "message": "Resume uploaded successfully"
        }
        
    except HTTPException as he:
        raise he
    except Exception as e:
        db.rollback()
        logger.error(f"Error uploading resume: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error processing resume: {str(e)}"
        )
    finally:
        await file.close()

# Interview Management Endpoints
@app.post("/interview/create")
async def create_interview_session(
    jd_id: str = Form(...),
    resume_id: str = Form(...),
    db: Session = Depends(get_db)
):
    """
    Create interview session with 5 questions
    """
    try:
        logger.info(f"Creating interview session with JD ID: {jd_id} and Resume ID: {resume_id}")
        
        # Verify JD and Resume exist
        job_description = db.query(JobDescription).filter(JobDescription.id == jd_id).first()
        candidate_resume = db.query(CandidateResume).filter(CandidateResume.id == resume_id).first()
        
        if not job_description:
            logger.error(f"Job Description not found with ID: {jd_id}")
            raise HTTPException(status_code=404, detail="Job Description not found")
            
        if not candidate_resume:
            logger.error(f"Resume not found with ID: {resume_id}")
            raise HTTPException(status_code=404, detail="Resume not found")
        
        # Create interview session
        session_id = str(uuid.uuid4())
        interview_session = InterviewSession(
            id=session_id,
            jd_id=jd_id,
            resume_id=resume_id,
            status="draft",  # Initial status is draft until questions are confirmed
            scheduled_datetime=datetime.utcnow()
        )
        db.add(interview_session)
        db.flush()
        
        # Generate exactly 5 questions
        generated_questions = await generate_interview_questions(
            job_description.content,
            candidate_resume.content
        )
        
        # Add questions
        questions = []
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
                scoring_rubric={"key_points": question_data.get("key_points", [])}
            )
            db.add(question)
            
            questions.append({
                "id": question.id,
                "question_text": question.question_text,
                "question_type": question.question_type,
                "category": question.category,
                "sequence_number": idx
            })
        
        db.commit()
        logger.info(f"Successfully created interview session with ID: {session_id}")
        
        return {
            "interview_id": session_id,
            "status": "draft",
            "candidate_name": candidate_resume.candidate_name,
            "job_title": job_description.title,
            "questions": questions,
            "message": "Interview session created with generated questions"
        }
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating interview: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/interview/{interview_id}/details")
async def get_interview_details(interview_id: str, db: Session = Depends(get_db)):
    """
    Get comprehensive interview details including questions, responses, and analysis
    """
    try:
        # Get interview session with related data
        interview_session = db.query(InterviewSession).filter(
            InterviewSession.id == interview_id
        ).first()
        
        if not interview_session:
            raise HTTPException(status_code=404, detail="Interview session not found")
        
        # Prepare questions with responses and analysis
        questions_with_responses = []
        total_questions = len(interview_session.questions)
        answered_questions = 0
        
        ordered_questions = sorted(
            interview_session.questions,
            key=lambda question: question.sequence_number or 0,
        )
        for question in ordered_questions:
            # Get responses for this question
            responses = [
                {
                    "response_text": response.response_text,
                    "score": response.score,
                    "timestamp": response.timestamp.isoformat() if response.timestamp else None,
                    "ai_feedback": response.ai_feedback,
                    "technical_accuracy": response.technical_accuracy,
                    "clarity_score": response.clarity_score,
                    "improvement_suggestions": response.improvement_suggestions,
                    "keywords_matched": response.keywords_matched
                }
                for response in question.responses
            ]
            
            if responses:
                answered_questions += 1
            
            questions_with_responses.append({
                "id": question.id,
                "question_text": question.question_text,
                "question_type": question.question_type,
                "category": question.category,
                "sequence_number": question.sequence_number,
                "is_modified": question.is_modified,
                "original_question": question.original_question if question.is_modified else None,
                "expected_answer_keywords": question.expected_answer_keywords,
                "scoring_rubric": question.scoring_rubric,
                "responses": responses
            })
        
        # Calculate interview progress
        progress = {
            "total_questions": total_questions,
            "answered_questions": answered_questions,
            "completion_percentage": (answered_questions / total_questions * 100) if total_questions > 0 else 0
        }
        
        # Calculate average scores
        scores = {
            "overall_score": interview_session.overall_score,
            "technical_score": interview_session.technical_score,
            "communication_score": interview_session.communication_score,
            "cultural_fit_score": interview_session.cultural_fit_score,
            "score_breakdown": {
                "technical_proficiency": interview_session.technical_score,
                "communication_skills": interview_session.communication_score,
                "problem_solving": sum((q.responses[0].score or 0) for q in interview_session.questions if q.responses and q.question_type == "technical") / total_questions if total_questions > 0 else 0,
                "experience_relevance": sum((q.responses[0].score or 0) for q in interview_session.questions if q.responses and q.question_type == "experience") / total_questions if total_questions > 0 else 0
            }
        }
        
        # Get timing information
        timing = {
            "created_at": interview_session.created_at.isoformat() if interview_session.created_at else None,
            "scheduled_datetime": interview_session.scheduled_datetime.isoformat() if interview_session.scheduled_datetime else None,
            "actual_start_time": interview_session.actual_start_time.isoformat() if interview_session.actual_start_time else None,
            "actual_end_time": interview_session.actual_end_time.isoformat() if interview_session.actual_end_time else None,
            "duration_minutes": (interview_session.actual_end_time - interview_session.actual_start_time).total_seconds() / 60 if interview_session.actual_end_time and interview_session.actual_start_time else None
        }
        
        return {
            "interview_id": interview_session.id,
            "status": interview_session.status,
            "progress": progress,
            "timing": timing,
            "job_description": {
                "id": interview_session.job_description.id,
                "title": interview_session.job_description.title,
                "company": interview_session.job_description.company,
                "content": interview_session.job_description.content,
                "requirements": interview_session.job_description.requirements
            },
            "candidate": {
                "id": interview_session.candidate_resume.id,
                "name": interview_session.candidate_resume.candidate_name,
                "email": interview_session.candidate_resume.email,
                "skills": interview_session.candidate_resume.skills,
                "experience": interview_session.candidate_resume.experience
            },
            "scoring": scores,
            "questions": questions_with_responses,
            "interview_summary": {
                "strengths": [
                    response.ai_feedback 
                    for question in ordered_questions
                    for response in question.responses 
                    if response.score is not None and response.score >= 8 and response.ai_feedback
                ],
                "areas_for_improvement": [
                    response.improvement_suggestions
                    for question in ordered_questions
                    for response in question.responses
                    if response.score is not None and response.score < 6 and response.improvement_suggestions
                ],
                "overall_recommendation": "Recommended for next round" if interview_session.overall_score >= 7 else "Consider other candidates" if interview_session.overall_score < 5 else "Requires further evaluation"
            }
        }
        
    except SQLAlchemyError as e:
        logger.error(f"Database error getting interview details: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Database error occurred while fetching interview details"
        )
    except Exception as e:
        logger.error(f"Error getting interview details: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving interview details: {str(e)}"
        )


@app.put("/interview/questions/{question_id}")
async def update_interview_question(
    question_id: str,
    question_update: dict,
    db: Session = Depends(get_db)
):
    """
    Update a specific interview question
    """
    try:
        question = db.query(InterviewQuestion).filter(
            InterviewQuestion.id == question_id
        ).first()
        
        if not question:
            raise HTTPException(status_code=404, detail="Question not found")
        
        # Update question fields
        if "question_text" in question_update:
            new_text = str(question_update.get("question_text") or "").strip()
            if not new_text:
                raise HTTPException(status_code=400, detail="question_text cannot be empty")
            if not question.is_modified:
                question.original_question = question.question_text
            question.question_text = new_text
            question.is_modified = True
            question.updated_at = datetime.utcnow()
        
        db.commit()
        
        return {
            "id": question.id,
            "question_text": question.question_text,
            "question_type": question.question_type,
            "category": question.category,
            "sequence_number": question.sequence_number
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating question: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/interview/{interview_id}/confirm")
async def confirm_interview_questions(
    interview_id: str,
    db: Session = Depends(get_db)
):
    """
    Confirm the interview questions and mark the session as ready
    """
    try:
        logger.info(f"Confirming questions for interview: {interview_id}")
        
        interview = db.query(InterviewSession).filter(
            InterviewSession.id == interview_id.strip()
        ).first()
        
        if not interview:
            raise HTTPException(status_code=404, detail="Interview session not found")
        
        # Verify we have exactly 5 questions
        questions = db.query(InterviewQuestion).filter(
            InterviewQuestion.interview_session_id == interview_id
        ).all()
        
        if len(questions) != 5:
            raise HTTPException(
                status_code=400,
                detail=f"Interview must have exactly 5 questions. Current count: {len(questions)}"
            )
        
        # Update interview status to ready
        interview.status = "ready"
        interview.updated_at = datetime.utcnow()
        
        # Log the change
        logger.info(f"Setting interview {interview_id} status to ready")
        
        db.commit()
        
        return {
            "interview_id": interview_id,
            "status": "ready",
            "message": "Interview questions confirmed and ready for use",
            "total_questions": len(questions)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error confirming interview: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/interview/search")
async def search_interviews(
    candidate_name: str = None,
    company: str = None,
    status: str = None,
    date_from: datetime = None,
    date_to: datetime = None,
    db: Session = Depends(get_db)
):
    query = db.query(InterviewSession)
    
    if candidate_name:
        query = query.join(CandidateResume).filter(
            CandidateResume.candidate_name.ilike(f"%{candidate_name}%")
        )
    
    if company:
        query = query.join(JobDescription).filter(
            JobDescription.company.ilike(f"%{company}%")
        )
    
    if status:
        query = query.filter(InterviewSession.status == status)
    
    if date_from:
        query = query.filter(InterviewSession.created_at >= date_from)
    
    if date_to:
        query = query.filter(InterviewSession.created_at <= date_to)
    
    interviews = query.all()
    
    return [
        {
            "interview_id": interview.id,
            "candidate_name": interview.candidate_resume.candidate_name,
            "company": interview.job_description.company,
            "job_title": interview.job_description.title,
            "status": interview.status,
            "created_at": interview.created_at,
            "overall_score": interview.overall_score
        }
        for interview in interviews
    ]

def fallback_job_description(job_role: str) -> str:
    role = (job_role or "Software Engineer").strip()
    return (
        f"Job Title: {role}\n"
        "Company: Mock Company\n\n"
        f"We are hiring a {role} to design, build, and improve production software with a small team.\n"
        "Responsibilities include shipping features, reviewing code, debugging production issues, "
        "and collaborating with product and design.\n"
        "Required skills: clear communication, relevant project experience, and the core tools of the role.\n"
        "Qualifications: hands-on experience in a similar position and examples of work you can discuss.\n"
    )


async def generate_mock_job_description(job_role: str) -> str:
    """Build a mock job description, using Groq when it is configured."""
    if client is None:
        logger.warning("GROQ_API_KEY is not configured. Using a template job description.")
        return fallback_job_description(job_role)
    try:
        jd_prompt = f"""
        Write a concise and detailed job description for the role of {job_role}.
        Include key responsibilities, required skills, and qualifications.
        """
        return complete_chat(
            [{"role": "user", "content": jd_prompt}],
            max_completion_tokens=1200,
        )
    except Exception as exc:
        logger.error("Falling back to a template job description: %s", exc)
        return fallback_job_description(job_role)


def get_or_create_mock_resume(db):
    """
    Retrieve or create a mock resume for mock interviews.
    """
    mock_resume = db.query(CandidateResume).filter(CandidateResume.candidate_name == "Mock Candidate").first()
    if not mock_resume:
        mock_resume = CandidateResume(
            id=str(uuid.uuid4()),
            candidate_name="Mock Candidate",
            email="mock@candidate.com",
            content="This is a placeholder resume for mock interviews.",
            file_name="mock_resume.txt",
            file_type="generated"
        )
        db.add(mock_resume)
        db.flush()
    return mock_resume

@app.post("/mock-interview")
async def create_mock_interview(job_role: str = Form(...), db: Session = Depends(get_db)):
    """
    Create a mock interview session for a specified job role.
    """
    try:
        logger.info(f"Creating mock interview for job role: {job_role}")

        jd_content = await generate_mock_job_description(job_role)
        logger.info(f"Generated JD for role {job_role}: {jd_content[:100]}...")

        # Save the generated JD
        jd_id = str(uuid.uuid4())
        job_description = JobDescription(
            id=jd_id,
            title=job_role,
            company="Mock Company",
            content=jd_content,
            file_name=None,
            file_type="generated"
        )
        db.add(job_description)
        db.flush()

        # Generate mock questions
        generated_questions = await generate_interview_questions(jd_content, resume_content="Mock Candidate")

        # Get or create a mock resume
        mock_resume = get_or_create_mock_resume(db)

        # Create the interview session
        session_id = str(uuid.uuid4())
        interview_session = InterviewSession(
            id=session_id,
            jd_id=jd_id,
            resume_id=mock_resume.id,
            status="ready",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.add(interview_session)
        db.flush()

        # Add generated questions
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
                scoring_rubric={"key_points": question_data.get("key_points", [])}
            )
            db.add(question)

        db.commit()

        return {
            "interview_id": session_id,
            "job_role": job_role,
            "questions": generated_questions,
            "message": "Mock interview created successfully. Use the interview ID to start."
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating mock interview: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to create mock interview")


# Modified talk-video endpoint to use interview session
def audio_extension(content: bytes, filename: Optional[str], content_type: Optional[str]) -> str:
    """Pick a Whisper-supported extension from the recording itself."""
    header = content[:16]
    content_type = (content_type or "").lower()
    if header.startswith(b"RIFF") or "wav" in content_type:
        return "wav"
    if header.startswith(b"\x1a\x45\xdf\xa3") or "webm" in content_type or "matroska" in content_type:
        return "webm"
    if header.startswith(b"OggS") or "ogg" in content_type:
        return "ogg"
    if header.startswith(b"ID3") or header[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2") or "mpeg" in content_type or "mp3" in content_type:
        return "mp3"
    if b"ftyp" in header or "mp4" in content_type or "m4a" in content_type:
        return "m4a" if "m4a" in content_type else "mp4"
    if filename and "." in filename:
        extension = filename.rsplit(".", 1)[-1].lower()
        if extension in {"wav", "webm", "mp3", "ogg", "m4a", "mp4", "flac", "mpeg"}:
            return extension
    return "wav"


def audio_media_type(extension: str) -> str:
    return {
        "wav": "audio/wav",
        "webm": "audio/webm",
        "mp3": "audio/mpeg",
        "mpeg": "audio/mpeg",
        "ogg": "audio/ogg",
        "mp4": "audio/mp4",
        "m4a": "audio/mp4",
        "flac": "audio/flac",
    }.get(extension, "application/octet-stream")


def tone_wav(seconds: float = 0.5, frequency: float = 440.0) -> bytes:
    """A short playable WAV so the browser can finish the interview without ElevenLabs."""
    framerate = 16000
    frames = int(seconds * framerate)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(framerate)
        pcm = bytearray()
        for index in range(frames):
            sample = int(1200 * math.sin(2 * math.pi * frequency * index / framerate))
            pcm.extend(struct.pack("<h", sample))
        wav_file.writeframes(bytes(pcm))
    return buffer.getvalue()


def as_score(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "; ".join(str(item) for item in value)
    return str(value)


@app.post("/talk-video")
async def process_video(
    file: UploadFile = File(...),
    interview_id: str = Form(...),
    db: Session = Depends(get_db)
):
    """
    Process one recorded answer and return spoken feedback plus the next prompt.
    The first recording is the candidate's introduction and is not scored.
    """
    interview_session = None
    try:
        interview_session = db.query(InterviewSession).filter(
            InterviewSession.id == interview_id.strip()
        ).first()

        if not interview_session:
            raise HTTPException(status_code=404, detail="Interview session not found")
        if interview_session.status == "completed":
            raise HTTPException(status_code=400, detail="Interview is already completed")
        if interview_session.status not in ("ready", "in_progress"):
            raise HTTPException(
                status_code=400,
                detail=f"Interview is not ready (current status: {interview_session.status})"
            )

        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Audio file is empty")
        if len(content) > 5 * 1024 * 1024:
            raise HTTPException(
                status_code=400,
                detail="File too large. Please limit recordings to 5MB or less."
            )

        all_questions = db.query(InterviewQuestion).filter(
            InterviewQuestion.interview_session_id == interview_session.id
        ).order_by(InterviewQuestion.sequence_number).all()
        if len(all_questions) != 5:
            raise HTTPException(status_code=400, detail="No questions found for this interview")

        user_message = await transcribe_audio(content, file.filename, file.content_type)
        logger.info("Transcribed message: %s...", user_message[:100])

        answered_questions = db.query(CandidateResponse).filter(
            CandidateResponse.interview_session_id == interview_session.id
        ).count()
        is_introduction = interview_session.status == "ready" and answered_questions == 0

        if interview_session.status == "ready":
            interview_session.status = "in_progress"
            if interview_session.actual_start_time is None:
                interview_session.actual_start_time = datetime.utcnow()

        if is_introduction:
            interview_session.transcript = user_message
            ai_response = (
                "Thank you for introducing yourself. Let's begin the interview. "
                f"Here's your first question: {all_questions[0].question_text}"
            )
            answered_header = 0
            current_question_number = 1
        else:
            current_question = next(
                (question for question in all_questions if question.sequence_number == answered_questions + 1),
                None
            )
            if current_question is None:
                raise HTTPException(status_code=400, detail="No further questions are available for this interview")

            response = CandidateResponse(
                interview_session_id=interview_session.id,
                question_id=current_question.id,
                response_text=user_message,
                response_audio_url="",
                timestamp=datetime.utcnow()
            )
            db.add(response)
            analysis = await analyze_response(current_question.question_text, user_message)
            response.score = as_score(analysis.get("relevance_score"))
            response.technical_accuracy = as_score(analysis.get("technical_score"))
            response.clarity_score = as_score(analysis.get("clarity_score"))
            response.ai_feedback = as_text(analysis.get("feedback"))
            response.improvement_suggestions = as_text(analysis.get("improvement_areas"))

            if answered_questions + 1 >= len(all_questions):
                interview_session.status = "completed"
                interview_session.actual_end_time = datetime.utcnow()
                db.flush()
                responses = db.query(CandidateResponse).filter(
                    CandidateResponse.interview_session_id == interview_session.id
                ).all()
                count = len(responses) or 1
                interview_session.technical_score = sum(r.technical_accuracy or 0 for r in responses) / count
                interview_session.communication_score = sum(r.clarity_score or 0 for r in responses) / count
                interview_session.overall_score = (
                    interview_session.technical_score + interview_session.communication_score
                ) / 2
                questions_by_id = {question.id: question for question in all_questions}
                cultural_scores = [
                    r.score or 0
                    for r in responses
                    if questions_by_id.get(r.question_id)
                    and questions_by_id[r.question_id].question_type == "cultural-fit"
                ]
                interview_session.cultural_fit_score = (
                    sum(cultural_scores) / len(cultural_scores)
                    if cultural_scores else interview_session.overall_score
                )
                ai_response = (
                    "Thank you for completing the interview. Your responses have been recorded. "
                    "We will review them and get back to you soon. Have a great day!"
                )
                current_question_number = len(all_questions)
            else:
                next_question = next(
                    (question for question in all_questions if question.sequence_number == answered_questions + 2),
                    None
                )
                ai_response = (
                    f"Thank you for your response. Here's your next question: {next_question.question_text}"
                    if next_question else "Thank you for your response."
                )
                current_question_number = answered_questions + 2
            answered_header = answered_questions + 1

        audio_output, media_type = text_to_speech(ai_response)
        db.commit()
        logger.info("Processing completed, generating audio response: %s...", ai_response[:100])

        headers = {
            "X-Interview-Status": interview_session.status,
            "X-Total-Questions": str(len(all_questions)),
            "X-Answered-Questions": str(answered_header),
            "X-Current-Question": str(current_question_number),
            "X-Assistant-Text": base64.b64encode(ai_response.encode("utf-8")).decode("ascii"),
            "Access-Control-Expose-Headers": (
                "X-Interview-Status, X-Total-Questions, X-Answered-Questions, "
                "X-Current-Question, X-Assistant-Text"
            ),
        }
        return StreamingResponse(iter([audio_output]), media_type=media_type, headers=headers)

    except HTTPException:
        db.rollback()
        raise
    except AIConfigurationError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        db.rollback()
        logger.error("Error processing video: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/interview/check-completed")
async def check_completed_interviews(db: Session = Depends(get_db)):
    """
    Check if there are any completed interviews in the system
    """
    try:
        completed_count = db.query(InterviewSession).filter(
            InterviewSession.status == "completed"
        ).count()
        
        return {
            "has_completed_interviews": completed_count > 0
        }
    except Exception as e:
        logger.error(f"Error checking completed interviews: {str(e)}")
        raise HTTPException(
            status_code=500, 
            detail="Failed to check completed interviews"
        )

@app.get("/interview/validate/{interview_id}")
async def validate_interview_id(interview_id: str, db: Session = Depends(get_db)):
    """
    Validate if an interview ID exists and is ready for interview
    """
    try:
        # Log the received ID for debugging
        logger.info(f"Validating interview ID: {interview_id}")
        
        # Get interview session
        interview = db.query(InterviewSession).filter(
            InterviewSession.id == interview_id.strip()
        ).first()
        
        logger.info(f"Found interview: {interview is not None}")
        
        if not interview:
            logger.warning(f"Interview not found with ID: {interview_id}")
            return JSONResponse(
                status_code=404,
                content={
                    "valid": False,
                    "message": "Interview ID not found"
                }
            )
        
        logger.info(f"Interview status: {interview.status}")
        
        # Ready sessions can start. In-progress sessions can be resumed after a
        # dropped connection. Completed sessions cannot be recorded again.
        if interview.status == "completed":
            return JSONResponse(
                status_code=400,
                content={
                    "valid": False,
                    "message": "Interview is already completed"
                }
            )
        if interview.status not in ("ready", "in_progress"):
            logger.warning(f"Interview {interview_id} is in {interview.status} state, not ready")
            return JSONResponse(
                status_code=400,
                content={
                    "valid": False,
                    "message": f"Interview is not ready (current status: {interview.status})"
                }
            )
        
        # Get questions count
        questions = db.query(InterviewQuestion).filter(
            InterviewQuestion.interview_session_id == interview_id
        ).all()
        
        logger.info(f"Found {len(questions)} questions")
        
        if not questions or len(questions) != 5:
            logger.warning(f"Interview {interview_id} has {len(questions)} questions, expected 5")
            return JSONResponse(
                status_code=400,
                content={
                    "valid": False,
                    "message": "Interview is not properly set up (missing questions)"
                }
            )
        
        answered = db.query(CandidateResponse).filter(
            CandidateResponse.interview_session_id == interview.id
        ).count()
        current_question = 0 if interview.status == "ready" else min(answered + 1, len(questions))

        return {
            "valid": True,
            "message": "Interview ID is valid and ready to start" if interview.status == "ready" else "Interview is in progress",
            "status": interview.status,
            "total_questions": len(questions),
            "answered_questions": answered,
            "current_question": current_question,
        }
        
    except Exception as e:
        logger.error(f"Error validating interview ID: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to validate interview ID: {str(e)}"
        )

async def transcribe_audio(content: bytes, filename: Optional[str], content_type: Optional[str]) -> str:
    """
    Transcribe audio with OpenAI Whisper. The bytes are sent with their real format.
    """
    if ai_stub_enabled():
        return (
            "I have several years of relevant experience. I work with teammates, "
            "break a problem into smaller pieces, and follow through until the result is shipped."
        )
    if not OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured")

    extension = audio_extension(content, filename, content_type)
    temp_file_path = f"temp_{uuid.uuid4()}.{extension}"
    try:
        with open(temp_file_path, "wb") as temp_file:
            temp_file.write(content)

        url = "https://api.openai.com/v1/audio/transcriptions"
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
        data = {
            "model": "whisper-1",
            "response_format": "text",
            "language": "en",
        }
        logger.info("Sending request to OpenAI Whisper API...")
        with open(temp_file_path, "rb") as audio_file:
            files = {
                "file": (os.path.basename(temp_file_path), audio_file, audio_media_type(extension))
            }
            response = requests.post(url, headers=headers, files=files, data=data, timeout=120)

        logger.info("OpenAI API response status: %s", response.status_code)
        if response.status_code == 200:
            transcription = response.text.strip()
            if not transcription:
                raise HTTPException(status_code=422, detail="Transcription is empty")
            return transcription
        if response.status_code == 401:
            raise HTTPException(status_code=401, detail="Unauthorized: Check your OpenAI API key")
        if response.status_code == 429:
            raise HTTPException(status_code=429, detail="Rate limit exceeded: Please try again later")
        raise HTTPException(
            status_code=502,
            detail=f"Transcription request failed with status {response.status_code}",
        )
    except HTTPException:
        raise
    except requests.RequestException as exc:
        logger.error("Transcription network error: %s", exc)
        raise HTTPException(status_code=502, detail="Error reaching the transcription service")
    finally:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
            logger.info("Temporary audio file removed")


def load_messages(session_id, role):
    session_file = f'sessions/{session_id}.json'
    if os.path.exists(session_file) and os.stat(session_file).st_size > 0:
        with open(session_file) as db_file:
            return json.load(db_file)
    else:
        return [{
            "role": "system",
            "content": f"""
You are ai-recruiter, an experienced interviewer conducting a preliminary interview for the role of {role}. Your goal is to
assess the candidate's suitability for {role} role based on specific criteria, including their communication skills,
relevant experience, and alignment with the company's values. You will ask a series of tailored questions to
evaluate these aspects, encouraging the candidate to provide detailed responses. You will also observe non-verbal
cues such as tone, enthusiasm, and clarity of speech. Begin the interview by introducing yourself and then asking the interviewee to introduce themselves
briefly, then proceed with questions related to the candidate's experience, skills, and motivation for applying.
Use follow-up questions to delve deeper into their answers if needed. Ensure that the interaction is professional,
engaging, and respectful, making the candidate feel comfortable while maintaining a focus on extracting relevant
information. Conclude the interview by thanking the candidate for their time and asking them to wait for
the result of this interview and next steps in the hiring process.
            """
        }]

def save_messages(session_id, messages):
    os.makedirs('sessions', exist_ok=True)
    session_file = f'sessions/{session_id}.json'
    with open(session_file, 'w') as f:
        json.dump(messages, f)

def get_chat_response(session_id: str, user_message: str, job_context: str):
    """
    Get chat response from Groq API with enhanced error handling
    
    Args:
        session_id (str): Unique session identifier
        user_message (str): User's message to process
        job_context (str): Job description context
    
    Returns:
        tuple: (ai_response, ai_question)
    
    Raises:
        HTTPException: For various error conditions with appropriate status codes
    """
    try:
        # Load previous messages
        try:
            messages = load_messages(session_id, job_context)
            messages.append({"role": "user", "content": user_message})
        except Exception as e:
            logger.error(f"Error loading messages for session {session_id}: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail="Failed to load conversation history"
            )

        # Send request to Groq API
        try:
            logger.info(f"Sending request to Groq API for session {session_id}")
            ai_response = complete_chat(messages, max_completion_tokens=2000)
            logger.info(f"Received response from Groq API for session {session_id}: {ai_response[:100]}...")
        except AIConfigurationError as e:
            raise HTTPException(status_code=503, detail=str(e))
        except Exception as e:
            logger.error(f"Groq API error for session {session_id}: {str(e)}")
            raise HTTPException(
                status_code=502,
                detail="Failed to get response from AI service"
            )

        if not ai_response:
            raise HTTPException(
                status_code=502,
                detail="Invalid response format from AI service"
            )

        # Extract question
        try:
            ai_question = extract_question(ai_response)
            logger.info(f"Extracted question for session {session_id}: {ai_question}")
        except Exception as e:
            logger.error(f"Error extracting question: {str(e)}")
            ai_question = "Could not generate a follow-up question. Please continue the conversation."

        # Save conversation history
        try:
            messages.append({"role": "assistant", "content": ai_response})
            save_messages(session_id, messages)
        except Exception as e:
            logger.error(f"Error saving messages for session {session_id}: {str(e)}")
            # Don't raise an exception here as we still want to return the response
            # Just log the error

        return ai_response, ai_question

    except HTTPException:
        # Re-raise HTTP exceptions without modification
        raise
    except Exception as e:
        # Catch any unexpected errors
        logger.error(f"Unexpected error in get_chat_response: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while processing your request"
        )

def text_to_speech(text: str):
    """Return (audio_bytes, media_type) for the interviewer prompt."""
    if ai_stub_enabled() or not ELEVENLABS_API_KEY:
        if ai_stub_enabled():
            return tone_wav(), "audio/wav"
        raise HTTPException(status_code=503, detail="ELEVENLABS_API_KEY is not configured")

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"
    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": ELEVENLABS_API_KEY,
    }
    data = {
        "text": text,
        "model_id": ELEVENLABS_MODEL_ID,
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.5,
        },
    }
    try:
        logger.info("Sending request to ElevenLabs API with text: %s...", text[:100])
        response = requests.post(url, json=data, headers=headers, timeout=120)
        logger.info("ElevenLabs API response status: %s", response.status_code)
        if response.status_code == 200:
            logger.info("Received audio response, size: %s bytes", len(response.content))
            return response.content, "audio/mpeg"
        logger.error("ElevenLabs API error: %s", response.status_code)
        raise HTTPException(
            status_code=502,
            detail=f"Text-to-speech failed with status {response.status_code}",
        )
    except HTTPException:
        raise
    except requests.RequestException as exc:
        logger.error("Network error in text-to-speech request: %s", exc)
        raise HTTPException(status_code=502, detail="Error reaching the text-to-speech service")


def calculate_score(response):
    # Implement your scoring logic here
    # This is a placeholder implementation
    return len(response) / 100  # Simple score based on response length

def extract_question(ai_response):
    # Split the response into sentences
    sentences = ai_response.split('.')
    questions = []

    for sentence in sentences:
        # Strip whitespace and check if the sentence contains a question mark
        sentence = sentence.strip()
        if '?' in sentence:
            # Ensure the sentence ends with a question mark
            if not sentence.endswith('?'):
                sentence += '?'
            questions.append(sentence)

    # If questions were found, return the last one (usually the most relevant)
    if questions:
        return questions[-1]
    
    # If no questions were found, return a default message
    return "No explicit question found in the AI response. The AI may be waiting for more information or clarification."

if __name__ == "__main__":
    import uvicorn
    logger.info("Starting the FastAPI server")
    uvicorn.run(app, host="0.0.0.0", port=8000)