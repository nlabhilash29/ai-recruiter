"""Deterministic confidence for one scored answer.

No model call. The checks are the ones a recruiter can verify by reading the
transcript: the evidence quote is actually in the answer, a dimension was
scored without a quote, the answer is too thin, or a fallback produced the score.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from rubric import clean_dimension_scores

BASE = 90
FLOOR = 10
_STOP = frozenset(
    {
        "a", "an", "the", "and", "or", "to", "of", "for", "in", "on", "at", "as", "by", "with",
        "from", "you", "your", "that", "this", "was", "were", "are", "have", "has", "had", "but",
        "not", "what", "when", "where", "which", "who", "how", "about", "into", "over", "they",
        "their", "them", "just", "because", "would", "could", "should", "there", "been",
    }
)
_LABELS = {
    "high": "High confidence",
    "medium": "Medium confidence",
    "low": "Low confidence",
    "not_assessed": "Not assessed",
}


def _norm(text: str) -> str:
    cleaned = (text or "").replace("\u2019", "'").replace("\u2018", "'").lower()
    cleaned = re.sub(r"[^a-z0-9'\s]", " ", cleaned)
    return " ".join(cleaned.split())


def quote_in_transcript(quote: str, transcript: str) -> bool:
    """True when the quote is present, allowing light wording differences."""
    normalized_quote = _norm(quote)
    normalized_transcript = _norm(transcript)
    if not normalized_quote or not normalized_transcript:
        return False
    if normalized_quote in normalized_transcript:
        return True
    quote_tokens = [word for word in normalized_quote.split() if len(word) > 3 and word not in _STOP]
    transcript_tokens = set(normalized_transcript.split())
    if len(quote_tokens) >= 3:
        found = sum(1 for word in quote_tokens if word in transcript_tokens)
        if found / len(quote_tokens) >= 0.75:
            return True
    quote_length = len(normalized_quote)
    if quote_length < 12 or len(normalized_transcript) < quote_length:
        return SequenceMatcher(None, normalized_quote, normalized_transcript).ratio() >= 0.86
    best = 0.0
    step = max(1, quote_length // 6)
    limit = min(len(normalized_transcript) - quote_length + 1, 4000)
    for index in range(0, limit, step):
        ratio = SequenceMatcher(None, normalized_quote, normalized_transcript[index : index + quote_length]).ratio()
        if ratio > best:
            best = ratio
        if best >= 0.82:
            return True
    return best >= 0.82


def _level(percent: int, scored: bool) -> str:
    if not scored:
        return "not_assessed"
    if percent >= 75:
        return "high"
    if percent >= 50:
        return "medium"
    return "low"


def assess_confidence(
    transcript: str | None,
    evidence: str | None,
    dimension_scores: dict | None,
    fallback_used: str | None = None,
) -> dict:
    from question_generation import lacks_substance

    text = transcript or ""
    quote = (evidence or "").strip()
    scores = clean_dimension_scores(dimension_scores)
    scored_keys = [key for key, value in scores.items() if value is not None]
    scored = bool(scored_keys)
    silent = text.strip().lower().startswith("the candidate did not speak")
    thin = bool(text.strip()) and not silent and lacks_substance(text)
    in_transcript = bool(quote) and quote_in_transcript(quote, text)
    scored_without_evidence = scored and not quote
    reasons = []
    off = 0

    if silent:
        reasons.append("No speech was detected, so this question was not scored.")
    elif fallback_used == "scoring_unavailable":
        reasons.append("Scoring was unavailable, so this answer was not assessed.")
    elif not scored and thin:
        reasons.append("The answer is too thin to assess.")
    elif not scored:
        reasons.append("No dimension was scored for this answer.")

    if quote and in_transcript:
        reasons.append("The evidence quote appears in the transcript.")
    elif quote and not in_transcript:
        reasons.append("The evidence quote is not in the transcript.")
        off += 40
    elif scored_without_evidence:
        reasons.append("Dimensions were scored without an evidence quote.")
        off += 35

    if thin and scored:
        reasons.append("The answer is too thin to support a firm score.")
        off += 25
    if fallback_used and fallback_used != "scoring_unavailable":
        reasons.append("A fallback was used for this answer.")
        off += 30
    elif fallback_used == "scoring_unavailable":
        off += 30

    percent = max(FLOOR, BASE - off) if scored else max(FLOOR, BASE - off)
    level = _level(percent, scored)
    if not reasons:
        reasons.append("The score is backed by an evidence quote in the transcript.")
    return {
        "level": level,
        "percent": percent,
        "label": _LABELS[level],
        "reasons": reasons,
        "evidence_in_transcript": in_transcript if quote else None,
        "checks": {
            "evidence_in_transcript": bool(in_transcript) if quote else False,
            "scored_without_evidence": scored_without_evidence,
            "thin_answer": thin,
            "fallback_used": bool(fallback_used),
        },
    }
