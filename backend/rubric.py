"""Role-agnostic interview rubric.

HackerRank does not publish Chakra weights for Sales, Forward-Deployed
Engineer, Product Manager, or Software Developer. The dimensions below take
the competencies Chakra's public pages do name (problem solving, communication
clarity, technical accuracy / depth, and evidence of ownership) and add
collaboration so customer-facing and product roles can be scored. Weights and
the 1–10 anchors are ours. Unassessed dimensions are left empty rather than
guessed, which is the public Chakra rule.
"""

from __future__ import annotations

DIMENSIONS = (
    "problem_solving",
    "communication",
    "role_knowledge",
    "ownership",
    "collaboration",
)

DIMENSION_LABELS = {
    "problem_solving": "Problem solving",
    "communication": "Communication",
    "role_knowledge": "Role knowledge",
    "ownership": "Ownership and impact",
    "collaboration": "Collaboration",
}

# Percent weights. Each row sums to 100.
ROLE_WEIGHTS = {
    "software_developer": {
        "problem_solving": 25,
        "communication": 15,
        "role_knowledge": 30,
        "ownership": 20,
        "collaboration": 10,
    },
    "forward_deployed_engineer": {
        "problem_solving": 25,
        "communication": 20,
        "role_knowledge": 20,
        "ownership": 20,
        "collaboration": 15,
    },
    "product_manager": {
        "problem_solving": 25,
        "communication": 20,
        "role_knowledge": 20,
        "ownership": 25,
        "collaboration": 10,
    },
    "sales": {
        "problem_solving": 15,
        "communication": 25,
        "role_knowledge": 20,
        "ownership": 25,
        "collaboration": 15,
    },
    "general": {
        "problem_solving": 20,
        "communication": 20,
        "role_knowledge": 25,
        "ownership": 20,
        "collaboration": 15,
    },
}

ROLE_LABELS = {
    "software_developer": "Software Developer",
    "forward_deployed_engineer": "Forward-Deployed Engineer",
    "product_manager": "Product Manager",
    "sales": "Sales",
    "general": "General",
}

# One description per dimension, for every role. The job description says what the work is.
GENERIC_DESCRIPTORS = {
    "problem_solving": "Turns an unclear situation into options, chooses one, and says how they would know it worked.",
    "communication": "Makes the point easy to follow and backs it with a concrete example.",
    "role_knowledge": "Shows sound judgment about the work this role actually does.",
    "ownership": "Names what they personally decided or did, and the result that followed.",
    "collaboration": "Works with the other people the role depends on and handles disagreement without losing the goal.",
}
ROLE_DESCRIPTORS = {family: GENERIC_DESCRIPTORS for family in ROLE_WEIGHTS}

# Shared 1–10 anchors. The role descriptor says what "the work" means.
ANCHORS = {
    "problem_solving": {
        2: "Jumps to a fix, or the approach would not survive contact with the problem.",
        4: "Names a reasonable idea but skips constraints, checks, or why this option.",
        6: "Lays out a workable approach with at least one constraint or check.",
        8: "Compares options, names a tradeoff, and says how they would know it worked.",
        10: "Structures the problem, the options, the tradeoff, and a concrete check or result.",
    },
    "communication": {
        2: "Hard to follow, or mostly labels without an explanation.",
        4: "The point is findable, but the order or the terms are muddy.",
        6: "A listener can retell the main point and one supporting detail.",
        8: "Sequenced, concrete, and matched to the question that was asked.",
        10: "Crisp from the first sentence, with examples placed where they earn the claim.",
    },
    "role_knowledge": {
        2: "The skill the role needs is missing or described incorrectly.",
        4: "Surface familiarity, without enough accuracy to trust on the job.",
        6: "Correct on the core of the topic the question asked.",
        8: "Accurate and specific, including a limit or edge of that knowledge.",
        10: "Depth a peer in this role would rely on, tied to the work in the job description.",
    },
    "ownership": {
        2: "No personal action, or the result is only a slogan.",
        4: "They were nearby, but what they did or what changed is vague.",
        6: "A clear personal action, with a result that is plausible but light on measurement.",
        8: "They owned the decision or the work, and they name a result.",
        10: "Personal ownership, a tradeoff, and a measured outcome.",
    },
    "collaboration": {
        2: "Other people are absent, or conflict is blamed without a response.",
        4: "Mentions a team or customer, without what they did together.",
        6: "Describes a real interaction and their part in it.",
        8: "Handles disagreement or a customer need and says how it was resolved.",
        10: "Brings the right people in, keeps the disagreement specific, and lands a result.",
    },
}


def normalize_role(value: str | None) -> str:
    key = (value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "swe": "software_developer",
        "software": "software_developer",
        "software_engineer": "software_developer",
        "engineer": "software_developer",
        "developer": "software_developer",
        "fde": "forward_deployed_engineer",
        "forward_deployed": "forward_deployed_engineer",
        "pm": "product_manager",
        "product": "product_manager",
        "account_executive": "sales",
    }
    key = aliases.get(key, key)
    if key in ROLE_WEIGHTS:
        return key
    return "general"


def infer_role(title: str | None) -> str:
    text = (title or "").lower()
    if "forward" in text and "deploy" in text:
        return "forward_deployed_engineer"
    if "fde" in text.split() or "solutions engineer" in text or "customer engineer" in text:
        return "forward_deployed_engineer"
    if "product manager" in text or text.strip() in {"pm", "product"}:
        return "product_manager"
    if "sales" in text or "account executive" in text or "account manager" in text:
        return "sales"
    if any(word in text for word in ("engineer", "developer", "software", "sre", "programmer")):
        return "software_developer"
    return "general"


def infer_role_from_documents(*parts: str | None) -> str:
    """First specific match wins: title, then job description, then resume. Otherwise general."""
    for part in parts:
        family = infer_role(part)
        if family != "general":
            return family
    return "general"


def rubric_for(role: str | None) -> dict:
    raw = (role or "").strip().lower().replace("-", "_").replace(" ", "_")
    known = set(ROLE_WEIGHTS) | {
        "swe",
        "software",
        "software_engineer",
        "engineer",
        "developer",
        "fde",
        "forward_deployed",
        "pm",
        "product",
        "account_executive",
    }
    family = normalize_role(role) if raw in known else infer_role(role)
    weights = ROLE_WEIGHTS[family]
    return {
        "role_family": family,
        "role_label": ROLE_LABELS[family],
        "weights": weights,
        "descriptors": ROLE_DESCRIPTORS[family],
        "anchors": ANCHORS,
        "dimensions": [
            {
                "id": key,
                "label": DIMENSION_LABELS[key],
                "weight": weights[key],
                "descriptor": ROLE_DESCRIPTORS[family][key],
                "anchors": ANCHORS[key],
            }
            for key in DIMENSIONS
        ],
    }


def next_dimension(role: str | None, covered: list[str], main_index: int) -> str:
    weights = rubric_for(role)["weights"]
    remaining = [key for key in sorted(DIMENSIONS, key=lambda item: -weights[item]) if key not in set(covered)]
    if remaining:
        return remaining[0]
    return DIMENSIONS[(main_index - 1) % len(DIMENSIONS)]


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 1 or number > 10:
        return None
    return round(number, 1)


def clean_dimension_scores(raw) -> dict:
    source = raw or {}
    if not isinstance(source, dict):
        return {key: None for key in DIMENSIONS}
    return {key: _number(source.get(key)) for key in DIMENSIONS}


def weighted_overall(scores: dict, role: str | None):
    weights = rubric_for(role)["weights"]
    total_weight = 0
    total = 0.0
    for key, weight in weights.items():
        value = _number((scores or {}).get(key))
        if value is None:
            continue
        total += value * weight
        total_weight += weight
    if total_weight == 0:
        return None
    return round(total / total_weight, 1)


def follow_up_reason(answer: str, analysis: dict) -> str | None:
    """At most one follow-up. Thin answers and unusually strong ones earn it."""
    if (analysis or {}).get("not_assessed"):
        return None
    words = [word for word in (answer or "").split() if word]
    score = _number((analysis or {}).get("relevance_score"))
    if len(words) < 18 or (score is not None and score < 5):
        return "thin"
    if score is not None and score >= 8.5 and len(words) >= 35:
        return "interesting"
    return None


def recommend(overall, scores: dict) -> str:
    assessed = [value for value in clean_dimension_scores(scores).values() if value is not None]
    if len(assessed) < 3 or overall is None:
        return "Not enough evidence to recommend yet"
    lowest = min(assessed)
    if overall >= 8 and lowest >= 6:
        return "Strong yes — advance"
    if overall >= 6.5 and lowest >= 4:
        return "Yes — advance"
    if overall >= 5:
        return "Mixed — another conversation before deciding"
    return "No — do not advance on this interview"


def aggregate(per_answer: list[dict], role: str | None) -> dict:
    """Average each dimension across answers that actually assessed it."""
    buckets = {key: [] for key in DIMENSIONS}
    for scores in per_answer:
        cleaned = clean_dimension_scores(scores)
        for key, value in cleaned.items():
            if value is not None:
                buckets[key].append(value)
    averaged = {
        key: round(sum(values) / len(values), 1) if values else None
        for key, values in buckets.items()
    }
    overall = weighted_overall(averaged, role)
    return {
        "dimensions": averaged,
        "overall": overall,
        "recommendation": recommend(overall, averaged),
    }
