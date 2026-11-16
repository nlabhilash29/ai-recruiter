import asyncio
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("AI_STUB", "1")
os.environ.setdefault("GROQ_API_KEY", "")
os.environ.setdefault("OPENAI_API_KEY", "")
os.environ.setdefault("ELEVENLABS_API_KEY", "")

from question_generation import PROMPT_VERSION, analyze_response, generate_next_main_question
from rubric import DIMENSIONS

ANSWER = (
    "I led the checkout rewrite, cut failed payments by twelve percent, "
    "and paired with design on the rollout plan for the new flow."
)


class ScoringFallbackTests(unittest.TestCase):
    def test_scoring_failure_is_not_assessed(self):
        previous_stub = os.environ.get("AI_STUB")
        previous_traces = os.environ.get("AI_RECRUITER_TRACES")
        folder = tempfile.mkdtemp(prefix="airec-score-")
        os.environ["AI_STUB"] = "0"
        os.environ["AI_RECRUITER_TRACES"] = "1"
        os.environ["TRACES_DIR"] = folder
        try:
            with patch("question_generation.complete_chat", side_effect=RuntimeError("groq down")):
                analysis = asyncio.run(
                    analyze_response(
                        "What did you decide?",
                        ANSWER,
                        role_family="product_manager",
                    )
                )
        finally:
            if previous_stub is None:
                os.environ.pop("AI_STUB", None)
            else:
                os.environ["AI_STUB"] = previous_stub
            if previous_traces is None:
                os.environ.pop("AI_RECRUITER_TRACES", None)
            else:
                os.environ["AI_RECRUITER_TRACES"] = previous_traces
            os.environ.pop("TRACES_DIR", None)
            shutil.rmtree(folder, ignore_errors=True)
        self.assertTrue(analysis["not_assessed"])
        self.assertEqual(analysis["fallback_used"], "scoring_unavailable")
        self.assertEqual(analysis["prompt_version"], PROMPT_VERSION)
        self.assertIn("not assessed", analysis["feedback"].lower())
        self.assertIn("scoring unavailable", analysis["feedback"].lower())
        for key in ("relevance_score", "clarity_score", "technical_score"):
            self.assertIsNone(analysis[key])
            self.assertNotEqual(analysis[key], 5)
        for key in DIMENSIONS:
            self.assertIsNone(analysis["dimension_scores"][key])

    def test_next_question_failure_records_default_questions(self):
        previous_stub = os.environ.get("AI_STUB")
        previous_traces = os.environ.get("AI_RECRUITER_TRACES")
        folder = tempfile.mkdtemp(prefix="airec-question-")
        os.environ["AI_STUB"] = "0"
        os.environ["AI_RECRUITER_TRACES"] = "1"
        os.environ["TRACES_DIR"] = folder
        try:
            with patch("question_generation.GROQ_API_KEY", "test-key"), patch(
                "question_generation.complete_chat", side_effect=RuntimeError("groq down")
            ):
                question = asyncio.run(
                    generate_next_main_question(
                        "Product manager for checkout.",
                        "I shipped a checkout rewrite.",
                        [],
                        1,
                        "product_manager",
                        [],
                    )
                )
            from observability import load, trace_id_for
            import observability

            with observability.interview("12345678-1234-1234-1234-1234567890ab"):
                with patch("question_generation.GROQ_API_KEY", "test-key"), patch(
                    "question_generation.complete_chat", side_effect=RuntimeError("groq down")
                ):
                    asyncio.run(
                        generate_next_main_question(
                            "Product manager for checkout.",
                            "I shipped a checkout rewrite.",
                            [],
                            1,
                            "product_manager",
                            [],
                        )
                    )
            spans = load(trace_id_for("12345678-1234-1234-1234-1234567890ab"), folder)
        finally:
            if previous_stub is None:
                os.environ.pop("AI_STUB", None)
            else:
                os.environ["AI_STUB"] = previous_stub
            if previous_traces is None:
                os.environ.pop("AI_RECRUITER_TRACES", None)
            else:
                os.environ["AI_RECRUITER_TRACES"] = previous_traces
            os.environ.pop("TRACES_DIR", None)
            shutil.rmtree(folder, ignore_errors=True)
        self.assertTrue(question["question_text"].endswith("?"))
        kinds = [
            event["attributes"].get("kind")
            for span in spans
            for event in span["events"]
            if event["name"] == "error"
        ]
        self.assertIn("default_questions", kinds)


if __name__ == "__main__":
    unittest.main()
