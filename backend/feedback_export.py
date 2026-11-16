"""CSV export of recruiter feedback joined to the trace fields stored on the answer."""

from __future__ import annotations

import csv
import io

from sqlalchemy.orm import Session

from models import CandidateResponse, InterviewQuestion, RecruiterFeedback


COLUMNS = (
    "interview_id",
    "response_id",
    "trace_id",
    "created_at",
    "vote",
    "reason",
    "score_override",
    "note",
    "model",
    "latency_ms",
    "cost_usd",
    "fallback_used",
    "prompt_version",
    "question",
    "evidence",
    "transcript",
)


def feedback_records(db: Session) -> list[dict]:
    rows = (
        db.query(RecruiterFeedback, CandidateResponse, InterviewQuestion)
        .join(CandidateResponse, CandidateResponse.id == RecruiterFeedback.response_id)
        .join(InterviewQuestion, InterviewQuestion.id == CandidateResponse.question_id)
        .order_by(RecruiterFeedback.created_at, RecruiterFeedback.id)
        .all()
    )
    records = []
    for feedback, response, question in rows:
        records.append(
            {
                "interview_id": feedback.interview_session_id,
                "response_id": feedback.response_id,
                "trace_id": feedback.trace_id or response.trace_id or "",
                "created_at": feedback.created_at.isoformat() if feedback.created_at else "",
                "vote": feedback.vote or "",
                "reason": feedback.reason or "",
                "score_override": "" if feedback.score_override is None else feedback.score_override,
                "note": feedback.note or "",
                "model": response.model or "",
                "latency_ms": "" if response.latency_ms is None else response.latency_ms,
                "cost_usd": "" if response.cost_usd is None else response.cost_usd,
                "fallback_used": response.fallback_used or "",
                "prompt_version": response.prompt_version or "",
                "question": question.question_text or "",
                "evidence": response.evidence or "",
                "transcript": response.response_text or "",
            }
        )
    return records


def render_csv(records: list[dict]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    for record in records:
        writer.writerow({column: record.get(column, "") for column in COLUMNS})
    return buffer.getvalue()


def feedback_csv(db: Session) -> str:
    return render_csv(feedback_records(db))
