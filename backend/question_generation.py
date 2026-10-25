import json
import logging
import re
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from rubric import (
    DIMENSIONS,
    clean_dimension_scores,
    follow_up_reason,
    next_dimension,
    rubric_for,
    weighted_overall,
)
from settings import GROQ_API_KEY, GROQ_MODEL, GROQ_REASONING_EFFORT, ai_stub_enabled

load_dotenv()

logger = logging.getLogger(__name__)

_client = None

_ANALYSIS_LABELS = {
    "relevance score": "relevance_score",
    "clarity score": "clarity_score",
    "technical score": "technical_score",
    "technical accuracy": "technical_score",
    "key points covered": "key_points",
    "key points": "key_points",
    "improvement suggestions": "improvement_areas",
    "improvement areas": "improvement_areas",
    "areas for improvement": "improvement_areas",
    "what to improve": "improvement_areas",
    "overall feedback": "feedback",
    "feedback": "feedback",
}
_LABEL_RE = re.compile(
    r"^[\s#>*_\-\d.]*("
    + "|".join(re.escape(label) for label in sorted(_ANALYSIS_LABELS, key=len, reverse=True))
    + r")\s*(?:[:\-\u2013\u2014]\s*(.*))?$",
    re.IGNORECASE,
)

_EMPTY_MARKERS = {
    "",
    "n/a",
    "na",
    "none",
    "null",
    "undefined",
    "[feedback]",
    "[areas]",
    "[points]",
    "[score]",
}

ANALYSIS_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "response_analysis",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "relevance_score": {"type": "number"},
                "clarity_score": {"type": "number"},
                "technical_score": {"type": "number"},
                "key_points": {"type": "string"},
                "improvement_areas": {"type": "string"},
                "feedback": {"type": "string"},
                "evidence": {"type": "string"},
                "dimension_scores": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "problem_solving": {"type": "number"},
                        "communication": {"type": "number"},
                        "role_knowledge": {"type": "number"},
                        "ownership": {"type": "number"},
                        "collaboration": {"type": "number"},
                    },
                    "required": [
                        "problem_solving",
                        "communication",
                        "role_knowledge",
                        "ownership",
                        "collaboration",
                    ],
                },
            },
            "required": [
                "relevance_score",
                "clarity_score",
                "technical_score",
                "key_points",
                "improvement_areas",
                "feedback",
                "evidence",
                "dimension_scores",
            ],
        },
    },
}

QUESTION_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "interview_questions",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "questions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "question_text": {"type": "string"},
                            "question_type": {"type": "string"},
                            "assesses": {"type": "string"},
                            "key_points": {"type": "string"},
                        },
                        "required": ["question_text", "question_type", "assesses", "key_points"],
                    },
                }
            },
            "required": ["questions"],
        },
    },
}

FEEDBACK_RETRY_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "feedback_retry",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "feedback": {"type": "string"},
                "improvement_areas": {"type": "string"},
            },
            "required": ["feedback", "improvement_areas"],
        },
    },
}


def get_client():
    global _client
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY is not configured")
    if _client is None:
        from groq import Groq

        _client = Groq(api_key=GROQ_API_KEY)
    return _client


def _message_text(message) -> str:
    content = getattr(message, "content", "") or ""
    if not str(content).strip():
        content = getattr(message, "reasoning", "") or ""
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                parts.append(str(part.get("text") or ""))
            else:
                parts.append(str(getattr(part, "text", "") or ""))
        content = "\n".join(parts)
    return str(content).strip()


def complete_chat(
    messages: List[Dict[str, str]],
    *,
    max_completion_tokens: int = 2000,
    temperature: float = 0.4,
    response_format: Optional[dict] = None,
) -> str:
    """Call Groq. Prefer JSON schema, then JSON mode, then plain text.

    gpt-oss spends completion budget on reasoning, so a short cap can come
    back with an empty answer. Empty completions are retried.
    """
    client = get_client()
    formats: List[Optional[dict]] = []
    if response_format:
        formats.append(response_format)
        if response_format.get("type") == "json_schema":
            formats.append({"type": "json_object"})
    formats.append(None)

    last_error: Optional[Exception] = None
    for fmt in formats:
        payloads = []
        base = {
            "model": GROQ_MODEL,
            "messages": messages,
            "temperature": temperature,
            "max_completion_tokens": max_completion_tokens,
        }
        if fmt:
            base["response_format"] = fmt
        if GROQ_REASONING_EFFORT:
            payloads.append({**base, "reasoning_effort": GROQ_REASONING_EFFORT})
        payloads.append(base)
        legacy = {
            "model": GROQ_MODEL,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_completion_tokens,
        }
        if fmt:
            legacy["response_format"] = fmt
        payloads.append(legacy)

        for payload in payloads:
            try:
                response = client.chat.completions.create(**payload)
                text = _message_text(response.choices[0].message)
                if text:
                    return text
                last_error = ValueError("Model returned an empty completion")
                logger.warning("Empty completion from %s", GROQ_MODEL)
            except Exception as exc:
                last_error = exc
                logger.warning("Groq completion attempt failed: %s", exc)
    if last_error:
        raise last_error
    raise ValueError("Model returned an empty completion")


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "; ".join(part for part in (_as_text(item) for item in value) if part)
    if isinstance(value, dict):
        return "; ".join(part for part in (_as_text(item) for item in value.values()) if part)
    return str(value).strip()


def _meaningful(value: Any) -> str:
    text = _as_text(value).strip().strip("*_` ")
    if text.lower() in _EMPTY_MARKERS:
        return ""
    if re.fullmatch(r"\[[^\]]+\]", text):
        return ""
    return text


def _parse_score(raw: Any, default: float = 5.0) -> float:
    if isinstance(raw, bool) or raw is None:
        return default
    if isinstance(raw, (int, float)):
        value = float(raw)
    else:
        match = re.search(r"(\d+(?:\.\d+)?)", str(raw))
        if not match:
            return default
        value = float(match.group(1))
    if value < 0:
        return default
    return round(min(value, 10.0), 2)


def _try_json(text: str) -> Optional[dict]:
    candidate = (text or "").strip()
    if not candidate:
        return None
    candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", candidate, flags=re.IGNORECASE).strip()
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(candidate[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _analysis_from_mapping(data: dict) -> Dict[str, Any]:
    improvement = (
        data.get("improvement_areas")
        or data.get("improvement_suggestions")
        or data.get("areas_for_improvement")
        or data.get("what_to_improve")
    )
    feedback = data.get("feedback") or data.get("overall_feedback")
    key_points = data.get("key_points") or data.get("key_points_covered")
    return {
        "relevance_score": _parse_score(data.get("relevance_score", data.get("relevance"))),
        "clarity_score": _parse_score(data.get("clarity_score", data.get("clarity"))),
        "technical_score": _parse_score(data.get("technical_score", data.get("technical_accuracy", data.get("technical")))),
        "key_points": _meaningful(key_points),
        "improvement_areas": _meaningful(improvement),
        "feedback": _meaningful(feedback),
        "evidence": _meaningful(data.get("evidence")),
        "dimension_scores": data.get("dimension_scores") if isinstance(data.get("dimension_scores"), dict) else {},
    }


def parse_response_analysis(text: str) -> Dict[str, Any]:
    """Parse JSON or labelled analysis.

    A label's value may sit on the same line or on the following lines
    (bullets or paragraphs) until the next label. Markdown headings are labels.
    """
    analysis = {
        "relevance_score": 5.0,
        "clarity_score": 5.0,
        "technical_score": 5.0,
        "key_points": "",
        "improvement_areas": "",
        "feedback": "",
    }
    try:
        payload = _try_json(text or "")
        if payload and any(key in payload for key in ("feedback", "overall_feedback", "relevance_score", "improvement_areas")):
            analysis.update(_analysis_from_mapping(payload))
            return analysis

        sections: Dict[str, List[str]] = {}
        current = None
        cleaned = (text or "").replace("**", "").replace("__", "")
        for raw in cleaned.split("\n"):
            match = _LABEL_RE.match(raw.strip())
            if match:
                current = _ANALYSIS_LABELS[match.group(1).lower()]
                value = (match.group(2) or "").strip()
                sections[current] = [value] if value else []
            elif current and raw.strip() and raw.strip() not in {"---", "***"}:
                sections[current].append(raw.strip().lstrip("-*\u2022 ").strip())
        for key, lines in sections.items():
            separator = " " if key == "feedback" else "; "
            value = separator.join(line for line in lines if line).strip()
            if key.endswith("_score"):
                analysis[key] = _parse_score(value)
            else:
                analysis[key] = _meaningful(value)
    except Exception as exc:
        logger.error("Error parsing analysis: %s", exc)
    return analysis


def finalize_analysis(analysis: Dict[str, Any]) -> Dict[str, Any]:
    """Guarantee feedback and improvement text are never blank."""
    result = {
        "relevance_score": _parse_score(analysis.get("relevance_score")),
        "clarity_score": _parse_score(analysis.get("clarity_score")),
        "technical_score": _parse_score(analysis.get("technical_score")),
        "key_points": _meaningful(analysis.get("key_points")),
        "improvement_areas": _meaningful(analysis.get("improvement_areas")),
        "feedback": _meaningful(analysis.get("feedback")),
    }
    if not result["feedback"]:
        if result["improvement_areas"]:
            result["feedback"] = (
                "Automatic feedback was unavailable for this answer. "
                f"Areas to improve: {result['improvement_areas']}"
            )
        else:
            result["feedback"] = (
                "Automatic feedback was unavailable for this answer. Please review the transcript."
            )
    if not result["improvement_areas"]:
        result["improvement_areas"] = (
            "Add a specific example from your experience and describe the result."
        )
    return result


def _stub_analysis(role_family: str = "general") -> Dict[str, Any]:
    scores = {
        "problem_solving": 7.5,
        "communication": 8.0,
        "role_knowledge": 7.0,
        "ownership": 7.0,
        "collaboration": 6.5,
    }
    overall = weighted_overall(scores, role_family)
    analysis = finalize_analysis(
        {
            "relevance_score": overall if overall is not None else 7.2,
            "clarity_score": scores["communication"],
            "technical_score": scores["role_knowledge"],
            "key_points": "Described the work, their role, and how they approached it.",
            "improvement_areas": "Add a measurable result and one tradeoff you considered.",
            "feedback": (
                "You gave a clear example and explained your role. "
                "The answer would be stronger with a measurable result."
            ),
        }
    )
    analysis["dimension_scores"] = scores
    analysis["evidence"] = "I led the work to build an AI interview product."
    analysis["not_assessed"] = False
    return analysis


def _unscored_analysis() -> Dict[str, Any]:
    analysis = finalize_analysis(
        {
            "relevance_score": 5,
            "clarity_score": 5,
            "technical_score": 5,
            "key_points": "",
            "improvement_areas": "Answer out loud with one specific example and the result.",
            "feedback": "No speech was detected for this question, so it was not scored.",
        }
    )
    analysis["relevance_score"] = None
    analysis["clarity_score"] = None
    analysis["technical_score"] = None
    analysis["dimension_scores"] = {key: None for key in DIMENSIONS}
    analysis["evidence"] = ""
    analysis["not_assessed"] = True
    return analysis


def _attach_dimensions(analysis: Dict[str, Any], role_family: str) -> Dict[str, Any]:
    scores = clean_dimension_scores(analysis.get("dimension_scores"))
    if scores.get("communication") is None and analysis.get("clarity_score") is not None:
        scores["communication"] = analysis.get("clarity_score")
    if scores.get("role_knowledge") is None and analysis.get("technical_score") is not None:
        scores["role_knowledge"] = analysis.get("technical_score")
    if scores.get("problem_solving") is None and analysis.get("relevance_score") is not None:
        scores["problem_solving"] = analysis.get("relevance_score")
    if analysis.get("not_assessed"):
        scores = {key: None for key in DIMENSIONS}
    analysis["dimension_scores"] = scores
    if not analysis.get("not_assessed"):
        overall = weighted_overall(scores, role_family)
        if overall is not None:
            analysis["relevance_score"] = overall
        analysis["clarity_score"] = scores.get("communication")
        analysis["technical_score"] = scores.get("role_knowledge")
    analysis["evidence"] = (analysis.get("evidence") or analysis.get("key_points") or "").strip()
    return analysis


async def analyze_response(
    question: str,
    response: str,
    role_family: str = "general",
    dimension: str | None = None,
    no_speech: bool = False,
) -> Dict[str, Any]:
    """Score an answer and always return feedback plus improvement text."""
    if no_speech or not (response or "").strip() or response.strip().lower().startswith("the candidate did not speak"):
        return _unscored_analysis()
    if ai_stub_enabled():
        return _stub_analysis(role_family)
    plan = rubric_for(role_family)
    focus = dimension or "the dimension this question was meant to test"
    try:
        prompt = f"""Score this interview answer against the rubric. Use only the transcript.
If a dimension has no evidence in the answer, set it to null. Do not guess.
Scores are 1 to 10. Anchors live at 2, 4, 6, 8, and 10.
evidence is a short quote or close paraphrase from the answer that justifies the scores.
feedback is 2-3 sentences on what worked and what to add, and must be non-empty.
improvement_areas is concrete advice, and must be non-empty.
relevance_score is the weighted overall of the dimensions you could score.
clarity_score copies communication. technical_score copies role_knowledge.

Role: {plan["role_label"]}
Primary dimension for this question: {focus}
Descriptors: {plan["descriptors"]}

Question: {question}
Response: {response}
"""
        raw = complete_chat(
            [
                {
                    "role": "system",
                    "content": "You are an expert interviewer. Return only the requested JSON object.",
                },
                {"role": "user", "content": prompt},
            ],
            max_completion_tokens=2500,
            temperature=0.3,
            response_format=ANALYSIS_RESPONSE_FORMAT,
        )
        analysis = parse_response_analysis(raw)
        if not analysis["feedback"] or not analysis["improvement_areas"]:
            logger.warning("Analysis missing feedback or suggestions. Raw model output: %r", raw[:1500])
            try:
                retry_raw = complete_chat(
                    [
                        {
                            "role": "system",
                            "content": "You are an expert interviewer. Return only JSON.",
                        },
                        {
                            "role": "user",
                            "content": (
                                f"Question: {question}\nResponse: {response}\n\n"
                                "Give concise, specific feedback on this answer (what worked and what to add) "
                                "and concrete improvement_areas."
                            ),
                        },
                    ],
                    max_completion_tokens=800,
                    temperature=0.3,
                    response_format=FEEDBACK_RETRY_FORMAT,
                )
                retry = parse_response_analysis(retry_raw)
                if not analysis["feedback"]:
                    analysis["feedback"] = retry.get("feedback", "")
                if not analysis["improvement_areas"]:
                    analysis["improvement_areas"] = retry.get("improvement_areas", "")
            except Exception as retry_error:
                logger.error("Feedback retry failed: %s", retry_error)
        return _attach_dimensions(finalize_analysis(analysis), role_family)
    except Exception as exc:
        logger.error("Error analyzing response: %s", exc)
        return _attach_dimensions(
            finalize_analysis(
                {
                    "relevance_score": 5,
                    "clarity_score": 5,
                    "technical_score": 5,
                    "key_points": "",
                    "improvement_areas": "",
                    "feedback": "",
                }
            ),
            role_family,
        )


def _questions_from_payload(payload: dict) -> List[Dict[str, Any]]:
    raw_questions = payload.get("questions") if isinstance(payload, dict) else None
    if not isinstance(raw_questions, list):
        return []
    questions = []
    for item in raw_questions:
        if not isinstance(item, dict):
            continue
        questions.append(
            {
                "question_text": _as_text(item.get("question_text") or item.get("question")),
                "question_type": _as_text(item.get("question_type") or item.get("type")).lower(),
                "assesses": _as_text(item.get("assesses")),
                "key_points": _as_text(item.get("key_points")),
            }
        )
    return [question for question in questions if validate_question(question)]


async def modify_questions(questions: List[Dict[str, Any]], feedback: str) -> List[Dict[str, Any]]:
    if ai_stub_enabled():
        return questions
    try:
        logger.info("Modifying questions based on feedback...")
        questions_text = "\n".join(
            [
                f"Question {i + 1}:\n{q['question_text']}\nType: {q.get('question_type', 'N/A')}\nAssesses: {q.get('assesses', 'N/A')}"
                for i, q in enumerate(questions)
            ]
        )
        prompt = f"""Modify these interview questions based on the feedback.
Return JSON with a questions array of exactly {len(questions)} objects.
Each object has question_text, question_type, assesses, and key_points.

Current Questions:
{questions_text}

Feedback:
{feedback}
"""
        raw = complete_chat(
            [
                {"role": "system", "content": "You refine interview questions. Return JSON only."},
                {"role": "user", "content": prompt},
            ],
            max_completion_tokens=2000,
            response_format=QUESTION_RESPONSE_FORMAT,
        )
        modified = _questions_from_payload(_try_json(raw) or {}) or parse_generated_questions(raw)
        validated = []
        for i, original in enumerate(questions):
            if i < len(modified) and modified[i].get("question_text"):
                validated.append(
                    {
                        "question_text": modified[i]["question_text"].strip(),
                        "question_type": modified[i].get("question_type", original.get("question_type", "general")).lower(),
                        "assesses": modified[i].get("assesses", original.get("assesses", "general skills")),
                        "key_points": modified[i].get("key_points", original.get("key_points", "")),
                    }
                )
            else:
                validated.append(original)
        return validated or questions
    except Exception as exc:
        logger.error("Error modifying questions: %s", exc)
        return questions


def _template_job_description(job_role: str) -> str:
    return (
        f"{job_role} at Mock Company. "
        "Responsibilities include collaborating with the team, shipping reliable work, and communicating clearly. "
        "Requirements: relevant experience, problem solving, and care for the people affected by the work."
    )


async def generate_job_description(job_role: str) -> str:
    if ai_stub_enabled() or not GROQ_API_KEY:
        if not GROQ_API_KEY and not ai_stub_enabled():
            logger.warning("GROQ_API_KEY is not configured. Using a template job description.")
        return _template_job_description(job_role)
    try:
        raw = complete_chat(
            [
                {
                    "role": "system",
                    "content": "You write concise, realistic job descriptions.",
                },
                {
                    "role": "user",
                    "content": (
                        f"Write a concise job description for the role of {job_role}. "
                        "Include key responsibilities, required skills, and qualifications."
                    ),
                },
            ],
            max_completion_tokens=700,
            temperature=0.5,
        )
        return raw.strip() or _template_job_description(job_role)
    except Exception as exc:
        logger.error("Falling back to a template job description: %s", exc)
        return _template_job_description(job_role)


async def generate_interview_questions(jd_content: str, resume_content: str) -> List[Dict[str, Any]]:
    if ai_stub_enabled():
        return get_default_questions()
    try:
        prompt = f"""Given the job description and resume below, generate EXACTLY 5 interview questions.
Cover technical skills, past experience, problem solving, behavior, and cultural fit.
question_type must be one of: technical, experience, problem-solving, behavioral, cultural-fit.
key_points is a short string of 3-4 things to listen for.

Job Description:
{jd_content}

Resume:
{resume_content}
"""
        logger.info("Requesting questions from %s...", GROQ_MODEL)
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                raw = complete_chat(
                    [
                        {
                            "role": "system",
                            "content": (
                                "You are an expert recruiter. Generate specific interview questions "
                                "from the job description and resume. Return JSON only."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    max_completion_tokens=2500,
                    response_format=QUESTION_RESPONSE_FORMAT,
                )
                payload = _try_json(raw)
                questions = _questions_from_payload(payload) if payload else []
                if len(questions) != 5:
                    questions = parse_generated_questions(raw)
                if len(questions) == 5 and all(validate_question(q) for q in questions):
                    logger.info("Successfully generated 5 valid questions")
                    return questions
                logger.warning("Attempt %s: generated %s questions, retrying...", attempt + 1, len(questions))
            except Exception as exc:
                logger.error("Attempt %s failed: %s", attempt + 1, exc)
                if attempt == max_attempts - 1:
                    raise
        logger.warning("Could not generate valid questions, using defaults")
        return get_default_questions()
    except Exception as exc:
        logger.error("Error in question generation: %s", exc)
        return get_default_questions()


def validate_question(question: Dict[str, Any]) -> bool:
    required_fields = ["question_text", "question_type", "assesses", "key_points"]
    if not all(field in question and question[field] for field in required_fields):
        return False
    if len(question["question_text"]) < 10:
        return False
    valid_types = {"technical", "experience", "problem-solving", "behavioral", "cultural-fit"}
    if question["question_type"].lower() not in valid_types:
        return False
    return True


def get_default_questions() -> List[Dict[str, Any]]:
    logger.info("Using default question set")
    return [
        {
            "question_text": "Could you walk me through your most technically challenging project?",
            "question_type": "technical",
            "assesses": "Technical expertise and problem-solving",
            "key_points": "Technical depth, problem approach, solution implementation, results achieved",
        },
        {
            "question_text": "Describe a situation where you had to learn a new technology quickly. How did you approach it?",
            "question_type": "experience",
            "assesses": "Learning ability and adaptability",
            "key_points": "Learning strategy, time management, practical application, outcome",
        },
        {
            "question_text": "Tell me about a time when you had to resolve a complex technical issue under tight deadlines.",
            "question_type": "problem-solving",
            "assesses": "Critical thinking and pressure handling",
            "key_points": "Problem analysis, solution approach, time management, result",
        },
        {
            "question_text": "How do you handle disagreements with team members about technical decisions?",
            "question_type": "behavioral",
            "assesses": "Conflict resolution and teamwork",
            "key_points": "Communication style, conflict resolution approach, team collaboration, outcome",
        },
        {
            "question_text": "What aspects of our company's tech stack and culture interest you the most?",
            "question_type": "cultural-fit",
            "assesses": "Company culture alignment and technical interest",
            "key_points": "Company research, technical knowledge, cultural values, motivation",
        },
    ]


def _fallback_follow_up(reason: str) -> str:
    if reason == "thin":
        return "Could you give one specific example, including what you personally did and what resulted?"
    return "What tradeoff did you weigh there, and how did you choose?"


async def maybe_follow_up_question(question: str, answer: str, analysis: Dict[str, Any]) -> Optional[str]:
    """Return one follow-up, or None. Callers allow at most one per main question."""
    reason = follow_up_reason(answer, analysis)
    if not reason:
        return None
    if ai_stub_enabled() or not GROQ_API_KEY:
        return _fallback_follow_up(reason)
    try:
        raw = complete_chat(
            [
                {
                    "role": "system",
                    "content": "You ask one short follow-up interview question. Return only the question.",
                },
                {
                    "role": "user",
                    "content": (
                        f"The answer was {reason}. Ask one follow-up that stays on the same topic.\n"
                        f"Question: {question}\nAnswer: {answer}"
                    ),
                },
            ],
            max_completion_tokens=200,
            temperature=0.4,
        )
        text = (raw or "").strip().strip('"')
        return text if text.endswith("?") else _fallback_follow_up(reason)
    except Exception as exc:
        logger.error("Follow-up generation failed: %s", exc)
        return _fallback_follow_up(reason)


async def generate_next_main_question(
    jd_content: str,
    resume_content: str,
    history: List[Dict[str, str]],
    main_index: int,
    role_family: str,
    covered: List[str],
) -> Dict[str, Any]:
    """One main question, chosen from the job, the resume, and answers so far."""
    dimension = next_dimension(role_family, covered, main_index)
    plan = rubric_for(role_family)
    if ai_stub_enabled() or not GROQ_API_KEY:
        base = get_default_questions()[(main_index - 1) % 5]
        return {
            **base,
            "dimension": dimension,
            "question_type": dimension,
            "main_index": main_index,
        }
    prior = "\n".join(
        f"Q: {item.get('question', '')}\nA: {item.get('answer', '')}" for item in history
    ) or "No answers yet."
    try:
        raw = complete_chat(
            [
                {
                    "role": "system",
                    "content": (
                        "You write one interview question. Return JSON with question_text, "
                        "question_type, assesses, and key_points."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Role family: {plan['role_label']}.\n"
                        f"This question should probe {dimension}: {plan['descriptors'][dimension]}\n"
                        f"Do not repeat a question already asked.\n\n"
                        f"Job description:\n{jd_content[:4000]}\n\n"
                        f"Resume:\n{resume_content[:4000]}\n\n"
                        f"So far:\n{prior}"
                    ),
                },
            ],
            max_completion_tokens=700,
            temperature=0.5,
            response_format=QUESTION_RESPONSE_FORMAT,
        )
        payload = _try_json(raw) or {}
        questions = _questions_from_payload(payload) or parse_generated_questions(raw)
        chosen = questions[0] if questions else get_default_questions()[(main_index - 1) % 5]
    except Exception as exc:
        logger.error("Next question generation failed: %s", exc)
        chosen = get_default_questions()[(main_index - 1) % 5]
    chosen = dict(chosen)
    chosen["dimension"] = dimension
    chosen["question_type"] = dimension
    chosen["main_index"] = main_index
    return chosen


def parse_generated_questions(text: str) -> List[Dict[str, Any]]:
    payload = _try_json(text)
    if payload:
        from_json = _questions_from_payload(payload)
        if from_json:
            return from_json

    questions = []
    current_question: Dict[str, Any] = {}
    try:
        for line in text.split("\n"):
            line = line.strip().replace("**", "")
            if not line:
                continue
            if line.lower().startswith("question:") or (line[0].isdigit() and ". " in line[:4] and "question" in line.lower()):
                if current_question and "question_text" in current_question:
                    questions.append(current_question)
                current_question = {
                    "question_text": line.split(":", 1)[1].strip() if ":" in line else line.split(".", 1)[1].strip()
                }
            elif line.lower().startswith("type:"):
                current_question["question_type"] = line.split(":", 1)[1].strip().lower()
            elif line.lower().startswith("assesses:"):
                current_question["assesses"] = line.split(":", 1)[1].strip()
            elif line.lower().startswith("key points:"):
                current_question["key_points"] = line.split(":", 1)[1].strip()
        if current_question and "question_text" in current_question:
            questions.append(current_question)
        return [question for question in questions if validate_question(question)]
    except Exception as exc:
        logger.error("Error parsing questions: %s", exc)
        return []
