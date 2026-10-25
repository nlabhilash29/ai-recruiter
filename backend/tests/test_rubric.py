import os
import unittest

os.environ.setdefault("AI_STUB", "1")

from question_generation import fallback_question
from rubric import (
    DIMENSIONS,
    GENERIC_DESCRIPTORS,
    ROLE_WEIGHTS,
    aggregate,
    follow_up_reason,
    infer_role_from_documents,
    recommend,
    rubric_for,
    weighted_overall,
)


class RubricTests(unittest.TestCase):
    def test_every_role_weights_to_one_hundred(self):
        for role, weights in ROLE_WEIGHTS.items():
            self.assertEqual(set(weights), set(DIMENSIONS))
            self.assertEqual(sum(weights.values()), 100, role)

    def test_explicit_role_beats_a_title_guess(self):
        plan = rubric_for("sales")
        self.assertEqual(plan["role_family"], "sales")
        self.assertEqual(plan["weights"]["communication"], 25)
        inferred = rubric_for("Forward Deployed Engineer, payments")
        self.assertEqual(inferred["role_family"], "forward_deployed_engineer")
        self.assertEqual(
            infer_role_from_documents("Opening", "We need a product manager for growth.", "Engineer who codes."),
            "product_manager",
        )
        self.assertEqual(infer_role_from_documents("Hello", "No title words here."), "general")

    def test_unassessed_dimensions_do_not_change_the_overall(self):
        full = {"problem_solving": 8, "communication": 8, "role_knowledge": 8, "ownership": 8, "collaboration": 8}
        partial = dict(full)
        partial["collaboration"] = None
        self.assertEqual(weighted_overall(full, "general"), 8)
        self.assertEqual(weighted_overall(partial, "general"), 8)
        rolled = aggregate([partial, {"problem_solving": None}], "general")
        self.assertIsNone(rolled["dimensions"]["collaboration"])
        self.assertEqual(rolled["dimensions"]["communication"], 8)
        self.assertEqual(rolled["dimensions"]["problem_solving"], 8)

    def test_recommendation_needs_evidence(self):
        thin = {"problem_solving": 9, "communication": None, "role_knowledge": None, "ownership": None, "collaboration": None}
        self.assertEqual(recommend(9, thin), "Not enough evidence to recommend yet")
        strong = {key: 8 for key in DIMENSIONS}
        self.assertEqual(recommend(8, strong), "Strong yes — advance")
        mixed = {key: 5 for key in DIMENSIONS}
        self.assertIn("Mixed", recommend(5, mixed))
        weak = {key: 3 for key in DIMENSIONS}
        self.assertIn("do not advance", recommend(3, weak))

    def test_follow_up_is_one_reason_or_none(self):
        long_answer = " ".join(["example"] * 40)
        self.assertIsNone(follow_up_reason(long_answer, {"relevance_score": 7.2, "not_assessed": False}))
        self.assertEqual(follow_up_reason("too short", {"relevance_score": 7, "not_assessed": False}), "thin")
        self.assertEqual(
            follow_up_reason(long_answer, {"relevance_score": 9, "not_assessed": False}),
            "interesting",
        )
        self.assertIsNone(follow_up_reason("", {"not_assessed": True, "relevance_score": 1}))

    def test_dimension_descriptions_are_role_generic(self):
        banned = ("coding", "code", "algorithm", "engineer", "technical", "debug")
        for role in ROLE_WEIGHTS:
            descriptors = rubric_for(role)["descriptors"]
            self.assertEqual(descriptors, GENERIC_DESCRIPTORS)
            for text in descriptors.values():
                lowered = text.lower()
                for word in banned:
                    self.assertNotIn(word, lowered)

    def test_fallback_questions_follow_the_role_not_a_coding_script(self):
        question = fallback_question(
            "Product Manager",
            "role_knowledge",
            1,
            "I shipped a checkout rewrite with design and engineering.",
        )
        text = question["question_text"].lower()
        self.assertIn("product manager", text)
        self.assertIn("checkout", text)
        for word in ("algorithm", "coding", "tech stack", "technically challenging"):
            self.assertNotIn(word, text)


if __name__ == "__main__":
    unittest.main()
