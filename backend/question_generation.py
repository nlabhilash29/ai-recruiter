import json
import logging
import re
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from rubric import (
    DIMENSIONS,
    clean_dimension_scores,
    follow_up_reason,
    infer_role_from_documents,
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
                        "problem_solving": {"type": ["number", "null"]},
                        "communication": {"type": ["number", "null"]},
                        "role_knowledge": {"type": ["number", "null"]},
                        "ownership": {"type": ["number", "null"]},
                        "collaboration": {"type": ["number", "null"]},
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


def lacks_substance(text: str) -> bool:
    """True when the answer is too short or off-topic to score."""
    raw = " ".join((text or "").replace("\u2019", "'").split()).strip()
    if not raw:
        return True
    lowered = raw.lower()
    words = re.findall(r"[a-z0-9']+", lowered)
    if len(words) < 8:
        return True
    off_topic = (
        "test response",
        "this is a test",
        "just a test",
        "let's move on",
        "lets move on",
        "let us move on",
        "skip this",
        "skip the question",
        "no comment",
        "i don't know",
        "i dont know",
        "nothing to add",
        "next question",
    )
    return len(words) <= 24 and any(phrase in lowered for phrase in off_topic)


def _thin_analysis() -> Dict[str, Any]:
    analysis = finalize_analysis(
        {
            "relevance_score": None,
            "clarity_score": None,
            "technical_score": None,
            "key_points": "",
            "improvement_areas": "Give one specific example from the work, including what you did and the result.",
            "feedback": "There wasn't enough content in this answer to assess it.",
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
    raw = analysis.get("dimension_scores") if isinstance(analysis.get("dimension_scores"), dict) else {}
    scores = clean_dimension_scores(raw)
    # A dimension the model left null stays unassessed. Do not copy a filler score onto it.
    legacy = {
        "communication": analysis.get("clarity_score"),
        "role_knowledge": analysis.get("technical_score"),
        "problem_solving": analysis.get("relevance_score"),
    }
    for key, value in legacy.items():
        if key in raw or scores.get(key) is not None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if 1 <= float(value) <= 10:
            scores[key] = round(float(value), 1)
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
    job_text: str = "",
) -> Dict[str, Any]:
    """Score an answer and always return feedback plus improvement text."""
    if no_speech or not (response or "").strip() or response.strip().lower().startswith("the candidate did not speak"):
        return _unscored_analysis()
    if lacks_substance(response):
        return _thin_analysis()
    if ai_stub_enabled():
        return _stub_analysis(role_family)
    plan = rubric_for(role_family)
    focus = dimension or "the dimension this question was meant to test"
    try:
        prompt = f"""Score this interview answer against the rubric. Use only the transcript.
Judge it against the expectations of the role in the job description.
Do not require coding, algorithms, system design, or implementation depth unless that job description is for a technical role such as a software engineer or developer.
A product manager, salesperson, or other non-engineering candidate is not marked down for lacking code.
If a dimension has no evidence in the answer, set it to null. Do not guess, and do not use 5 as a placeholder.
If the answer is only a few words, off-topic, or has no real example (for example "This is a test response. Let's move on."), set every dimension_scores value to null and say in feedback that there was not enough content to assess. Do not assign numeric scores.
Scores are 1 to 10 only when the transcript supports them. Anchors live at 2, 4, 6, 8, and 10.
evidence is a short quote or close paraphrase from the answer that justifies the scores.
feedback is 2-3 sentences on what worked and what to add, and must be non-empty.
improvement_areas is concrete advice, and must be non-empty.
relevance_score is the weighted overall of the dimensions you could score.
clarity_score copies communication. technical_score copies role_knowledge.

Role: {plan["role_label"]}
Primary dimension for this question: {focus}
Descriptors: {plan["descriptors"]}

Job description:
{(job_text or "")[:3000]}

Question: {question}
Response: {response}
"""
        raw = complete_chat(
            [
                {
                    "role": "system",
                    "content": (
                        "You score an interview answer for the role in the job description. "
                        "Do not assume the role is a software engineer. Return only the requested JSON object."
                    ),
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
    plan = _plan_from_documents(jd_content, resume_content)
    if ai_stub_enabled():
        return get_default_questions(plan["role_label"], resume_content)
    try:
        prompt = f"""Given the job description and resume below, generate EXACTLY 5 interview questions.
First plan 5 distinct focus areas, each mapped to a different requirement in the job description: strategy, execution, stakeholders, metrics, and a domain skill.
Then write one question per area, in that order.
Each resume project, result, or phrase may be used at most once across the 5.
Each question is one sentence, at most 25 words, and asks only one thing.
No long preamble that restates the resume. A brief anchor clause is fine, such as "At HackerRank you built the AI Fluency Score."
No multi-part questions, and no second ask such as "and how", "and what", or "and why".
Do not ask generic questions. Do not ask coding, algorithm, debugging, or implementation questions unless the job is a technical role such as a software engineer or developer.
question_type must be one of: problem_solving, communication, role_knowledge, ownership, collaboration.
Use problem_solving for strategy, ownership for execution, collaboration for stakeholders, role_knowledge for metrics, and communication for the domain skill.
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
                                "You write interview questions for the role in the job description. "
                                "Use one unused matching detail from the resume in each question. "
                                "Do not default to software-engineering questions. "
                                "Each question is one sentence of at most 25 words. "
                                "Return JSON only."
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
                    return _polish_question_set(questions, jd_content, resume_content)
                logger.warning("Attempt %s: generated %s questions, retrying...", attempt + 1, len(questions))
            except Exception as exc:
                logger.error("Attempt %s failed: %s", attempt + 1, exc)
                if attempt == max_attempts - 1:
                    raise
        logger.warning("Could not generate valid questions, using defaults")
        return get_default_questions(plan["role_label"], resume_content)
    except Exception as exc:
        logger.error("Error in question generation: %s", exc)
        return get_default_questions(plan["role_label"], resume_content)


def validate_question(question: Dict[str, Any]) -> bool:
    required_fields = ["question_text", "question_type", "assesses", "key_points"]
    if not all(field in question and question[field] for field in required_fields):
        return False
    if len(question["question_text"]) < 10:
        return False
    valid_types = {
        "technical",
        "experience",
        "problem-solving",
        "behavioral",
        "cultural-fit",
        "problem_solving",
        "communication",
        "role_knowledge",
        "ownership",
        "collaboration",
    }
    if question["question_type"].lower() not in valid_types:
        return False
    return True


QUESTION_WORD_LIMIT = 25
QUESTION_OVERLAP_THRESHOLD = 0.45
_LENGTH_RETRIES = 2
_UNIQUENESS_RETRIES = 2
_FOCUS_BY_DIMENSION = {
    "problem_solving": ("strategy", "a strategic choice or unclear problem this role has to resolve"),
    "ownership": ("execution", "a result this person personally delivered"),
    "collaboration": ("stakeholders", "working with the other people this role depends on"),
    "role_knowledge": ("metrics", "how they knew the work met the bar for this role"),
    "communication": ("domain skill", "explaining a point that matters in this role"),
}
_STOP_WORDS = frozenset(
    {
        "a", "an", "the", "and", "or", "to", "of", "for", "in", "on", "at", "as", "by", "with",
        "from", "you", "your", "we", "our", "they", "their", "it", "this", "that", "was", "were",
        "is", "are", "be", "did", "do", "how", "what", "when", "where", "why", "which", "who",
        "about", "into", "over", "after", "before", "than", "then", "just", "me", "my", "have",
        "has", "had", "but", "if", "so", "not", "can", "could", "would", "should", "your",
    }
)
_GENERIC_PHRASES = frozenset(
    {
        "product manager",
        "project manager",
        "software engineer",
        "this role",
    }
)


def _content_tokens(text: str) -> List[str]:
    return [
        word
        for word in re.findall(r"[a-z0-9]+", (text or "").lower())
        if len(word) > 2 and word not in _STOP_WORDS
    ]


def _phrases(tokens: List[str], size: int) -> set:
    return {" ".join(tokens[index : index + size]) for index in range(len(tokens) - size + 1)}


def questions_overlap(left: str, right: str, resume: str = "", threshold: float = QUESTION_OVERLAP_THRESHOLD) -> bool:
    """True when two questions are near-duplicates or reuse the same resume anchor."""
    left_tokens = _content_tokens(left)
    right_tokens = _content_tokens(right)
    if not left_tokens or not right_tokens:
        return False
    shared = set(left_tokens) & set(right_tokens)
    union = set(left_tokens) | set(right_tokens)
    if union and len(shared) / len(union) >= threshold:
        return True
    if not resume:
        return False
    resume_phrases = _phrases(_content_tokens(resume), 2) | _phrases(_content_tokens(resume), 3)
    left_phrases = (_phrases(left_tokens, 2) | _phrases(left_tokens, 3)) & resume_phrases
    right_phrases = (_phrases(right_tokens, 2) | _phrases(right_tokens, 3)) & resume_phrases
    return bool((left_phrases & right_phrases) - _GENERIC_PHRASES)


def question_word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9']+", text or ""))


def is_multi_part(text: str) -> bool:
    if (text or "").count("?") > 1:
        return True
    return bool(re.search(r"\b(?:and|then)\s+(?:how|what|why|which|when|where)\b", text or "", re.IGNORECASE))


def is_short_question(text: str) -> bool:
    cleaned = (text or "").strip()
    parts = [part for part in re.split(r"[.!?]+", cleaned) if part.strip()]
    return (
        bool(cleaned)
        and cleaned.endswith("?")
        and 6 <= question_word_count(cleaned) <= QUESTION_WORD_LIMIT
        and len(parts) == 1
        and not is_multi_part(cleaned)
    )


def _clip_question(text: str) -> str:
    """Keep one ask. Prefer the question itself over a resume preamble."""
    raw = re.split(
        r"\b(?:and|then)\s+(?:how|what|why|which|when|where)\b",
        (text or "").strip(),
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    pieces = [part.strip() for part in re.split(r"(?<=[.!?])\s+", raw) if part.strip()]
    question_pieces = [part for part in pieces if "?" in part]
    chosen = question_pieces[0] if question_pieces else (pieces[-1] if pieces else raw)
    chosen = re.split(r"[.!?]", chosen, maxsplit=1)[0]
    words = chosen.split()[:QUESTION_WORD_LIMIT]
    sentence = " ".join(words).strip(" ,;:-")
    if not sentence:
        return ""
    if not sentence.endswith("?"):
        sentence += "?"
    return sentence


def resume_anchors(text: str) -> List[str]:
    """Short distinctive phrases from a resume, in order, at most one per line or sentence."""
    chunks = []
    seen = set()
    pieces = re.split(r"[\n;]+|(?<=[.!?])\s+", (text or "").replace("\r", "\n"))
    for piece in pieces:
        if "@" in piece and " " not in piece.strip():
            continue
        tokens = _content_tokens(piece)
        if len(tokens) < 2:
            continue
        phrase = " ".join(tokens[:3])
        if phrase in seen:
            continue
        seen.add(phrase)
        chunks.append(phrase)
        if len(chunks) == 5:
            break
    return chunks


def _anchor_for(resume_content: str, main_index: int, priors: List[str]) -> str:
    anchors = resume_anchors(resume_content)
    if not anchors:
        return ""
    start = max(main_index, 1) - 1
    ordered = anchors[start:] + anchors[:start]
    for phrase in ordered:
        if phrase and not any(questions_overlap(phrase, prior, resume_content) for prior in priors if prior):
            return phrase
    return ""


def coerce_short_question(text: str, shorten, fallback: str, attempts: int = _LENGTH_RETRIES) -> str:
    """Ask `shorten` up to `attempts` times, then use a safe short fallback."""
    current = (text or "").strip()
    for _ in range(attempts):
        if is_short_question(current):
            return current
        current = (shorten(current) or "").strip()
    if is_short_question(current):
        return current
    clipped = _clip_question(text)
    if is_short_question(clipped):
        return clipped
    return fallback


def coerce_unique_question(
    text: str,
    priors: List[str],
    resume: str,
    regenerate,
    fallback: str,
    attempts: int = _UNIQUENESS_RETRIES,
) -> str:
    """Regenerate overlapping questions a bounded number of times, then fall back."""
    current = (text or "").strip()
    previous = [item for item in priors if item]

    def clashes(candidate: str) -> bool:
        return any(questions_overlap(candidate, prior, resume) for prior in previous)

    for _ in range(attempts):
        if current and not clashes(current):
            return current
        current = (regenerate(current) or "").strip()
    if current and not clashes(current):
        return current
    return fallback


def fallback_question(
    role_label: str,
    dimension: str,
    main_index: int,
    resume_content: str = "",
    priors: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """One short role-shaped question. Never a coding prompt, and not a second ask."""
    role = (role_label or "this role").strip() or "this role"
    anchor = _anchor_for(resume_content, main_index, priors or [])
    where = f" in {anchor}" if anchor else ""
    prompts = {
        "problem_solving": f"What unclear problem did you choose to solve{where} as a {role}?",
        "communication": f"How did you explain a difficult point outside your team{where} as a {role}?",
        "role_knowledge": f"What result{where} best matches your work as a {role}?",
        "ownership": f"What did you personally decide{where} as a {role}?",
        "collaboration": f"Where did you disagree with someone you depended on{where} as a {role}?",
    }
    text = prompts.get(dimension) or f"What choice from your background{where} fits this {role} work?"
    if not is_short_question(text):
        text = _clip_question(text)
    return {
        "question_text": text,
        "question_type": dimension,
        "assesses": dimension,
        "key_points": "A specific example, the candidate's own actions, and a result",
        "dimension": dimension,
        "main_index": main_index,
    }


def get_default_questions(role_label: str = "this role", resume_content: str = "") -> List[Dict[str, Any]]:
    logger.info("Using role-shaped fallback questions")
    dimensions = ["problem_solving", "communication", "role_knowledge", "ownership", "collaboration"]
    questions = []
    priors: List[str] = []
    for index, dimension in enumerate(dimensions, 1):
        question = fallback_question(role_label, dimension, index, resume_content, priors)
        questions.append(question)
        priors.append(question["question_text"])
    return questions


def _plan_from_documents(jd_content: str, resume_content: str) -> Dict[str, Any]:
    family = infer_role_from_documents("", jd_content or "", resume_content or "")
    return rubric_for(family)


def _technical_rule(role_family: str) -> str:
    if role_family in {"software_developer", "forward_deployed_engineer"}:
        return (
            "This role is technical. You may ask about implementation only when both the job description "
            "and the resume show that work."
        )
    return (
        "This role is not a coding role. Do not ask coding, algorithm, debugging, system-design, "
        "or technical-implementation questions."
    )


def _question_from_model_text(raw: str) -> str:
    text = (raw or "").strip().strip('"')
    payload = _try_json(text)
    if isinstance(payload, dict):
        questions = _questions_from_payload(payload)
        if questions and questions[0].get("question_text"):
            return str(questions[0]["question_text"]).strip()
        if payload.get("question_text"):
            return str(payload["question_text"]).strip()
    return text


def _llm_shorten(text: str, role: str) -> str:
    try:
        raw = complete_chat(
            [
                {
                    "role": "system",
                    "content": "You shorten an interview question. Return only the question.",
                },
                {
                    "role": "user",
                    "content": (
                        "Rewrite this as one question. One sentence, at most 25 words, one ask, one question mark. "
                        f"Keep the role ({role}) and at most one short resume anchor. "
                        "Do not add a second ask.\n"
                        f"Question: {text}"
                    ),
                },
            ],
            max_completion_tokens=200,
            temperature=0.2,
        )
        return _question_from_model_text(raw)
    except Exception as exc:
        logger.error("Question shorten failed: %s", exc)
        return ""


def _llm_regenerate(
    text: str,
    *,
    role: str,
    dimension: str,
    technical_rule: str,
    priors: List[str],
    resume: str,
) -> str:
    focus, blurb = _FOCUS_BY_DIMENSION.get(dimension, ("this area", "one requirement of the role"))
    asked = "\n".join(f"- {item}" for item in priors if item) or "None yet."
    try:
        raw = complete_chat(
            [
                {
                    "role": "system",
                    "content": "You write one short interview question. Return only the question.",
                },
                {
                    "role": "user",
                    "content": (
                        "The previous question overlapped an earlier one or reused a resume anchor. "
                        f"Write a different question for this focus: {focus} ({blurb}). "
                        "One sentence, at most 25 words, one ask, one question mark. "
                        "Do not use a resume project, result, or phrase already used.\n"
                        f"Role: {role}.\n{technical_rule}\n"
                        f"Already asked:\n{asked}\n\n"
                        f"Resume:\n{(resume or '')[:2000]}\n\n"
                        f"Overlapping question: {text}"
                    ),
                },
            ],
            max_completion_tokens=200,
            temperature=0.4,
        )
        return _question_from_model_text(raw)
    except Exception as exc:
        logger.error("Question rewrite failed: %s", exc)
        return ""


def shape_question_text(
    text: str,
    *,
    role: str,
    dimension: str,
    main_index: int,
    resume: str,
    priors: List[str],
    technical_rule: str,
    use_model: bool,
) -> str:
    """Shorten, then drop a repeated anchor. Both steps are bounded, then a short fallback."""
    fallback = fallback_question(role, dimension, main_index, resume, priors)["question_text"]
    if not use_model or not (text or "").strip():
        return fallback

    def shorten(current: str) -> str:
        return _llm_shorten(current, role)

    short = coerce_short_question(text, shorten, fallback)

    def regenerate(current: str) -> str:
        return _llm_regenerate(
            current,
            role=role,
            dimension=dimension,
            technical_rule=technical_rule,
            priors=priors,
            resume=resume,
        )

    unique = coerce_unique_question(short, priors, resume, regenerate, fallback)
    if not is_short_question(unique):
        return fallback
    return unique


def _polish_question_set(
    questions: List[Dict[str, Any]],
    jd_content: str,
    resume_content: str,
) -> List[Dict[str, Any]]:
    plan = _plan_from_documents(jd_content, resume_content)
    rule = _technical_rule(plan["role_family"])
    polished = []
    priors: List[str] = []
    for index, question in enumerate(questions, 1):
        raw_type = (question.get("question_type") or "").lower().replace("-", "_").replace(" ", "_")
        dimension = raw_type if raw_type in _FOCUS_BY_DIMENSION else DIMENSIONS[(index - 1) % len(DIMENSIONS)]
        text = shape_question_text(
            question.get("question_text") or "",
            role=plan["role_label"],
            dimension=dimension,
            main_index=index,
            resume=resume_content or "",
            priors=priors,
            technical_rule=rule,
            use_model=True,
        )
        item = dict(question)
        item["question_text"] = text
        item["question_type"] = dimension
        item["dimension"] = dimension
        item["main_index"] = index
        polished.append(item)
        priors.append(text)
    return polished


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
    priors = [str(item.get("question") or "").strip() for item in history if str(item.get("question") or "").strip()]
    shaped = fallback_question(plan["role_label"], dimension, main_index, resume_content, priors)
    if ai_stub_enabled() or not GROQ_API_KEY:
        return shaped
    prior = "\n".join(
        f"Q: {item.get('question', '')}\nA: {item.get('answer', '')}" for item in history
    ) or "No answers yet."
    technical_rule = _technical_rule(plan["role_family"])
    focus, blurb = _FOCUS_BY_DIMENSION.get(dimension, ("this area", "one requirement of the role"))
    asked = "\n".join(f"- {item}" for item in priors) or "None yet."
    try:
        raw = complete_chat(
            [
                {
                    "role": "system",
                    "content": (
                        "You write one short interview question for the role in the job description. "
                        "Use one unused matching detail from the resume. "
                        "Do not default to a software-engineering question. "
                        "Return JSON with question_text, question_type, assesses, and key_points."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "First, keep this plan of 5 distinct focus areas, each mapped to a different "
                        "requirement in the job description: strategy, execution, stakeholders, metrics, "
                        "and a domain skill.\n"
                        f"Write only question {main_index} of 5. Its focus is {focus}: {blurb}.\n"
                        "One sentence, at most 25 words, one ask, one question mark.\n"
                        "No second ask, and no \"and how\", \"and what\", or \"and why\".\n"
                        "A brief resume anchor is fine (\"At HackerRank you built the AI Fluency Score.\"). "
                        "Do not restate the resume in a preamble.\n"
                        "Each resume project, result, or phrase may be used at most once across the 5 questions.\n"
                        "Do not reuse an anchor or closely paraphrase any question already asked.\n"
                        "Do not ask a generic question such as 'tell me about yourself' or 'what is your greatest weakness'.\n"
                        f"Role: {plan['role_label']}.\n"
                        f"{technical_rule}\n"
                        f"question_type must be {dimension}.\n"
                        f"Already asked:\n{asked}\n\n"
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
        chosen = questions[0] if questions else dict(shaped)
    except Exception as exc:
        logger.error("Next question generation failed: %s", exc)
        chosen = dict(shaped)
    chosen = dict(chosen)
    chosen["question_text"] = shape_question_text(
        chosen.get("question_text") or "",
        role=plan["role_label"],
        dimension=dimension,
        main_index=main_index,
        resume=resume_content or "",
        priors=priors,
        technical_rule=technical_rule,
        use_model=True,
    )
    chosen["dimension"] = dimension
    chosen["question_type"] = dimension
    chosen["assesses"] = chosen.get("assesses") or dimension
    chosen["key_points"] = chosen.get("key_points") or shaped["key_points"]
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
