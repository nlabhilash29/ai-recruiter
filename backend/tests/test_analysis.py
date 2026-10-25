import os
import unittest

os.environ.setdefault("AI_STUB", "1")

from question_generation import finalize_analysis, parse_response_analysis


MULTILINE = """
Relevance Score: 8
Clarity Score: 7
Technical Score: 6.5
Key Points Covered:
- mentioned react
- led the project
Improvement Areas:
Quantify the impact.
Add a testing story.
Overall Feedback:
You covered the architecture well.
The answer needs a measurable outcome.
"""

MARKDOWN = """
**Relevance Score:** 9/10

## Overall Feedback

Strong structure and a relevant example. Add the metric next time.

## Improvement Areas

Include the before-and-after metric.
"""

JSON_BODY = """
```json
{
  "relevance_score": 8.5,
  "clarity_score": 7,
  "technical_score": 6.5,
  "key_points": ["react", "leadership"],
  "improvement_areas": "Add metrics.",
  "feedback": "Clear and specific."
}
```
"""


class ParseAnalysisTests(unittest.TestCase):
    def test_multiline_labels(self):
        analysis = parse_response_analysis(MULTILINE)
        self.assertEqual(analysis["relevance_score"], 8.0)
        self.assertEqual(analysis["clarity_score"], 7.0)
        self.assertEqual(analysis["technical_score"], 6.5)
        self.assertIn("mentioned react", analysis["key_points"])
        self.assertIn("led the project", analysis["key_points"])
        self.assertIn("Quantify the impact.", analysis["improvement_areas"])
        self.assertIn("Add a testing story.", analysis["improvement_areas"])
        self.assertIn("architecture well", analysis["feedback"])
        self.assertIn("measurable outcome", analysis["feedback"])

    def test_markdown_headings_and_score_suffix(self):
        analysis = parse_response_analysis(MARKDOWN)
        self.assertEqual(analysis["relevance_score"], 9.0)
        self.assertIn("Strong structure", analysis["feedback"])
        self.assertIn("metric next time", analysis["feedback"])
        self.assertIn("before-and-after", analysis["improvement_areas"])

    def test_json_object(self):
        analysis = parse_response_analysis(JSON_BODY)
        self.assertEqual(analysis["relevance_score"], 8.5)
        self.assertEqual(analysis["feedback"], "Clear and specific.")
        self.assertEqual(analysis["improvement_areas"], "Add metrics.")
        self.assertIn("react", analysis["key_points"])
        self.assertIn("leadership", analysis["key_points"])

    def test_same_line_labels_still_work(self):
        text = (
            "Relevance Score: 4\n"
            "Clarity Score: 5\n"
            "Technical Score: 6\n"
            "Key Points Covered: APIs\n"
            "Improvement Areas: Be more specific\n"
            "Overall Feedback: Too vague.\n"
        )
        analysis = parse_response_analysis(text)
        self.assertEqual(analysis["feedback"], "Too vague.")
        self.assertEqual(analysis["improvement_areas"], "Be more specific")
        self.assertEqual(analysis["relevance_score"], 4.0)

    def test_finalize_never_leaves_feedback_blank(self):
        result = finalize_analysis(
            {
                "relevance_score": "8/10",
                "clarity_score": None,
                "technical_score": 11,
                "key_points": "[points]",
                "improvement_areas": "",
                "feedback": "  ",
            }
        )
        self.assertTrue(result["feedback"].strip())
        self.assertTrue(result["improvement_areas"].strip())
        self.assertEqual(result["relevance_score"], 8.0)
        self.assertEqual(result["technical_score"], 10.0)
        self.assertEqual(result["key_points"], "")

    def test_finalize_uses_improvement_text_in_feedback_fallback(self):
        result = finalize_analysis({"feedback": "", "improvement_areas": "Mention the outcome."})
        self.assertIn("Mention the outcome.", result["feedback"])
        self.assertEqual(result["improvement_areas"], "Mention the outcome.")


if __name__ == "__main__":
    unittest.main()
