import asyncio
import os
import unittest

os.environ["AI_STUB"] = "1"
os.environ["GROQ_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
os.environ["ELEVENLABS_API_KEY"] = ""

from question_generation import (
    analyze_response,
    coerce_short_question,
    coerce_unique_question,
    fallback_question,
    get_default_questions,
    is_multi_part,
    is_short_question,
    lacks_substance,
    question_word_count,
    questions_overlap,
    shape_question_text,
)
from rubric import DIMENSIONS, recommend


RESUME = (
    "Built the HackerRank evaluation charter and the AI Fluency Score. "
    "Ran a hill-climbing loop across those modules."
)
LEFT = (
    "How did the hill-climbing loop change the AI Fluency Score "
    "inside the evaluation charter?"
)
RIGHT = (
    "What did the hill climbing loop change in the AI Fluency Score "
    "on that evaluation charter?"
)


class QuestionShapeTests(unittest.TestCase):
    def test_shared_resume_anchor_counts_as_overlap(self):
        self.assertTrue(questions_overlap(LEFT, RIGHT, RESUME))
        checkout = "What checkout metric showed the rewrite was ready to ship?"
        roadmap = "Where did the roadmap disagreement with design start?"
        other = "I shipped a checkout rewrite. I reset the roadmap with design."
        self.assertFalse(questions_overlap(checkout, roadmap, other))

    def test_short_question_is_one_ask(self):
        long = (
            "At HackerRank you owned the evaluation charter and the AI Fluency Score, "
            "and how did the hill-climbing loop change those modules over the following quarter?"
        )
        self.assertFalse(is_short_question(long))
        self.assertTrue(is_multi_part(long))
        self.assertGreater(question_word_count(long), 25)
        short = "What result in the checkout rewrite best matches your work as a product manager?"
        self.assertTrue(is_short_question(short))
        self.assertLessEqual(question_word_count(short), 25)

    def test_coerce_short_stops_after_two_long_rewrites(self):
        long = "Tell me and how did you handle the rest of this extremely long preamble that keeps going past the limit?"
        calls = []

        def shorten(_text):
            calls.append(1)
            return long

        fallback = "What did you personally decide as a product manager?"
        result = coerce_short_question(long, shorten, fallback)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result, fallback)
        self.assertTrue(is_short_question(result))

    def test_coerce_unique_falls_back_when_the_rewrite_still_overlaps(self):
        calls = []

        def regenerate(_text):
            calls.append(1)
            return RIGHT

        fallback = "What did you personally decide as a product manager?"
        result = coerce_unique_question(RIGHT, [LEFT], RESUME, regenerate, fallback)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result, fallback)
        self.assertFalse(questions_overlap(result, LEFT, RESUME))

    def test_fallback_questions_stay_short_and_use_each_anchor_once(self):
        question = fallback_question(
            "Product Manager",
            "role_knowledge",
            1,
            "I shipped a checkout rewrite with design and engineering.",
        )
        text = question["question_text"].lower()
        self.assertIn("product manager", text)
        self.assertIn("checkout", text)
        self.assertTrue(is_short_question(question["question_text"]))

        resume = "\n".join(
            [
                "Built the AI Fluency Score for the evaluation charter.",
                "Shipped a checkout rewrite with design and engineering.",
                "Reset the roadmap priority with sales and support.",
                "Led a pricing experiment on the team plan.",
                "Wrote the onboarding guide for new managers.",
            ]
        )
        questions = get_default_questions("Product Manager", resume)
        texts = [item["question_text"] for item in questions]
        self.assertEqual(len(texts), 5)
        for item in texts:
            self.assertTrue(is_short_question(item), item)
        for index, left in enumerate(texts):
            for right in texts[index + 1 :]:
                self.assertFalse(questions_overlap(left, right, resume), (left, right))

    def test_shape_without_a_model_uses_the_short_fallback(self):
        text = shape_question_text(
            "A very long overlapping question " * 12,
            role="Product Manager",
            dimension="role_knowledge",
            main_index=1,
            resume="I shipped a checkout rewrite with design and engineering.",
            priors=[],
            technical_rule="",
            use_model=False,
        )
        self.assertIn("checkout", text.lower())
        self.assertIn("product manager", text.lower())
        self.assertTrue(is_short_question(text))

    def test_contentless_answer_is_not_scored(self):
        sample = "This is a test response. Let's move on."
        self.assertTrue(lacks_substance(sample))
        analysis = asyncio.run(
            analyze_response(
                "What did you decide?",
                sample,
                role_family="product_manager",
            )
        )
        for key in DIMENSIONS:
            self.assertIsNone(analysis["dimension_scores"][key])
        self.assertIsNone(analysis["relevance_score"])
        self.assertIsNone(analysis["clarity_score"])
        self.assertIsNone(analysis["technical_score"])
        self.assertIn("enough content", analysis["feedback"].lower())
        self.assertEqual(
            recommend(None, analysis["dimension_scores"]),
            "Not enough evidence to recommend yet",
        )
        substantive = "I shipped the checkout rewrite and cut failed payments by twelve percent."
        self.assertFalse(lacks_substance(substantive))


if __name__ == "__main__":
    unittest.main()
