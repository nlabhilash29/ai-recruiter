import unittest

from confidence import assess_confidence, quote_in_transcript
from rubric import DIMENSIONS


TRANSCRIPT = (
    "I led the checkout rewrite and cut failed payments by twelve percent. "
    "I paired with design on the rollout."
)


def _scores(**overrides):
    scores = {key: None for key in DIMENSIONS}
    scores.update(overrides)
    return scores


class ConfidenceTests(unittest.TestCase):
    def test_exact_and_fuzzy_quote_matches_the_transcript(self):
        self.assertTrue(quote_in_transcript("I led the checkout rewrite", TRANSCRIPT))
        self.assertTrue(quote_in_transcript("I led the checkout rewrite and reduced failed payments.", TRANSCRIPT))
        self.assertFalse(quote_in_transcript("I launched a satellite from the roof on Tuesday.", TRANSCRIPT))

    def test_grounded_score_is_high_confidence(self):
        result = assess_confidence(
            TRANSCRIPT,
            "I led the checkout rewrite and cut failed payments by twelve percent.",
            _scores(ownership=8, communication=7),
        )
        self.assertEqual(result["level"], "high")
        self.assertTrue(result["checks"]["evidence_in_transcript"])
        self.assertFalse(result["checks"]["scored_without_evidence"])
        self.assertIn("appears in the transcript", " ".join(result["reasons"]))

    def test_score_without_evidence_and_invented_quote(self):
        missing = assess_confidence(TRANSCRIPT, "", _scores(ownership=8))
        self.assertTrue(missing["checks"]["scored_without_evidence"])
        self.assertEqual(missing["level"], "medium")
        invented = assess_confidence(
            TRANSCRIPT,
            "I launched a satellite from the roof on Tuesday.",
            _scores(ownership=9),
        )
        self.assertFalse(invented["checks"]["evidence_in_transcript"])
        self.assertIn("not in the transcript", " ".join(invented["reasons"]))
        self.assertEqual(invented["level"], "medium")

    def test_thin_answer_fallback_and_scoring_failure(self):
        thin = assess_confidence("Too short.", "", _scores(communication=6), fallback_used="thin_analysis")
        self.assertTrue(thin["checks"]["thin_answer"])
        self.assertTrue(thin["checks"]["fallback_used"])
        self.assertEqual(thin["level"], "low")
        failed = assess_confidence(TRANSCRIPT, "", _scores(), fallback_used="scoring_unavailable")
        self.assertEqual(failed["level"], "not_assessed")
        self.assertEqual(failed["label"], "Not assessed")
        self.assertIn("not assessed", " ".join(failed["reasons"]).lower())


if __name__ == "__main__":
    unittest.main()
