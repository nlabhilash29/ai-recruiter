"""The model's per-dimension scores, its 'not assessable' verdict, and its evidence quote must survive
parse -> finalize -> _attach_dimensions. Includes replays of real model replies captured from a
synthetic eval run (tests/fixtures/captured_analysis_replies.json)."""
import asyncio
import json
import os
import unittest
from pathlib import Path
from unittest import mock

os.environ["AI_STUB"] = "1"
os.environ["GROQ_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
os.environ["ELEVENLABS_API_KEY"] = ""
os.environ["GROQ_MODEL"] = "openai/gpt-oss-120b"

import question_generation as qg  # noqa: E402

DIMS = ("problem_solving", "communication", "role_knowledge", "ownership", "collaboration")
CAPTURED = {
    item["case"]: item["reply"]
    for item in json.loads((Path(__file__).parent / "fixtures" / "captured_analysis_replies.json").read_text())
}


def _reply(dims, evidence="we cut churn from 18% to 12%", relevance=7.5):
    return json.dumps({
        "relevance_score": relevance, "clarity_score": dims.get("communication"),
        "technical_score": dims.get("role_knowledge"), "key_points": "A summary, not a quote.",
        "improvement_areas": "Add the tradeoff.", "feedback": "Clear example.", "evidence": evidence,
        "dimension_scores": dims,
    })


def _pipeline(raw, role="general"):
    return qg._attach_dimensions(qg.finalize_analysis(qg.parse_response_analysis(raw)), role)


def _analyze(raw, dimension="ownership"):
    with mock.patch.object(qg, "ai_stub_enabled", return_value=False), \
            mock.patch.object(qg, "complete_chat", return_value=raw):
        return asyncio.run(qg.analyze_response(
            "What did you personally deliver?",
            "I owned the onboarding redesign end to end and we cut churn from 18% to 12% in one quarter, "
            "working with sales and support to roll it out.",
            role_family="general", dimension=dimension, job_text="Customer Success Manager"))


class DimensionsSurviveTests(unittest.TestCase):
    def test_all_five_dimensions_are_kept(self):
        dims = {"problem_solving": 8, "communication": 7, "role_knowledge": 6, "ownership": 9, "collaboration": 5}
        result = _pipeline(_reply(dims))
        self.assertEqual(result["dimension_scores"], {k: float(v) for k, v in dims.items()})
        self.assertFalse(result.get("not_assessed"))

    def test_problem_solving_is_the_models_score_not_the_overall(self):
        dims = {"problem_solving": 4, "communication": 8, "role_knowledge": 8, "ownership": None, "collaboration": None}
        result = _pipeline(_reply(dims, relevance=7.5))
        self.assertEqual(result["dimension_scores"]["problem_solving"], 4.0)

    def test_all_null_is_not_assessed_never_five(self):
        dims = {k: None for k in DIMS}
        result = _pipeline(_reply(dims, evidence="", relevance=None))
        self.assertTrue(result["not_assessed"])
        self.assertEqual(result["dimension_scores"], {k: None for k in DIMS})
        self.assertIsNone(result["relevance_score"])
        self.assertIsNone(result["clarity_score"])
        self.assertIsNone(result["technical_score"])
        self.assertTrue(result["feedback"])

    def test_partial_nulls_stay_null_and_are_not_backfilled(self):
        dims = {"problem_solving": None, "communication": 7, "role_knowledge": None, "ownership": 8,
                "collaboration": None}
        result = _pipeline(_reply(dims, relevance=7.5))
        self.assertIsNone(result["dimension_scores"]["problem_solving"])
        self.assertIsNone(result["dimension_scores"]["role_knowledge"])
        self.assertEqual(result["dimension_scores"]["ownership"], 8.0)

    def test_evidence_is_the_quote_not_key_points(self):
        dims = {"problem_solving": 8, "communication": 8, "role_knowledge": 8, "ownership": 8, "collaboration": 8}
        self.assertEqual(_pipeline(_reply(dims))["evidence"], "we cut churn from 18% to 12%")
        self.assertEqual(_pipeline(_reply(dims, evidence=""))["evidence"], "")
        self.assertEqual(_pipeline(_reply(dims, evidence=None))["evidence"], "")

    def test_legacy_text_reply_without_dimensions_still_backfills(self):
        result = _pipeline("Relevance Score: 8\nClarity Score: 7\nTechnical Score: 6\nOverall Feedback: Good.\n"
                           "Improvement Areas: Add a metric.")
        self.assertEqual(result["dimension_scores"]["communication"], 7.0)
        self.assertEqual(result["dimension_scores"]["role_knowledge"], 6.0)
        self.assertIsNone(result["dimension_scores"]["ownership"])

    def test_null_evidence_is_allowed_by_the_schema(self):
        schema = qg.ANALYSIS_RESPONSE_FORMAT["json_schema"]["schema"]
        self.assertIn("null", schema["properties"]["evidence"]["type"])


class CapturedReplyReplayTests(unittest.TestCase):
    """Real gpt-oss-120b replies from the 22 Nov 2026 synthetic run, replayed through analyze_response."""

    def _expected(self, case):
        raw = CAPTURED[case]
        return json.loads(raw[raw.find("{"): raw.rfind("}") + 1])

    def test_replays_keep_every_dimension_the_model_scored(self):
        for case in ("all_five_scored", "ownership_scored_collab_null", "other_partial"):
            with self.subTest(case=case):
                model = self._expected(case)
                result = _analyze(CAPTURED[case])
                for dim in DIMS:
                    want = model["dimension_scores"].get(dim)
                    self.assertEqual(result["dimension_scores"][dim], None if want is None else float(want), dim)
                self.assertEqual(result["evidence"], model["evidence"].strip())
                self.assertFalse(result.get("not_assessed"))

    def test_replayed_all_null_reply_is_not_assessed(self):
        result = _analyze(CAPTURED["all_null_not_assessable"])
        self.assertTrue(result["not_assessed"])
        self.assertEqual(set(result["dimension_scores"].values()), {None})
        self.assertIsNone(result["relevance_score"])

    def test_replay_ownership_question_saves_ownership(self):
        result = _analyze(CAPTURED["ownership_scored_collab_null"], dimension="ownership")
        self.assertEqual(result["dimension_scores"]["ownership"], 7.0)


if __name__ == "__main__":
    unittest.main()
