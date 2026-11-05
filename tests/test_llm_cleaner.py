"""
tests/test_llm_cleaner.py - Comprehensive tests for clean_llm_json and LLM response sanitization.
Validates extraction of pure JSON from markdown fences, conversational wrappers,
and corrupted or edge-case LLM strings.
"""
import json
import unittest
from scraper.gemini import clean_llm_json


class TestLLMCleaner(unittest.TestCase):
    def test_pure_json_object(self):
        raw = '{"experience_verdict": "SAFE", "verdict_reason": "0 years experience required"}'
        cleaned = clean_llm_json(raw)
        data = json.loads(cleaned)
        self.assertEqual(data["experience_verdict"], "SAFE")

    def test_pure_json_array(self):
        raw = '[{"title": "Junior Developer"}, {"title": "Intern"}]'
        cleaned = clean_llm_json(raw)
        data = json.loads(cleaned)
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["title"], "Junior Developer")

    def test_markdown_code_fence_json(self):
        raw = """```json
{
  "experience_verdict": "SAFE",
  "verdict_reason": "No prior experience needed",
  "core_requirements": "Python, React"
}
```"""
        cleaned = clean_llm_json(raw)
        data = json.loads(cleaned)
        self.assertEqual(data["experience_verdict"], "SAFE")

    def test_markdown_code_fence_without_json_tag(self):
        raw = """```
[
  {
    "title": "Graduate Engineer",
    "location": "Bengaluru"
  }
]
```"""
        cleaned = clean_llm_json(raw)
        data = json.loads(cleaned)
        self.assertEqual(data[0]["location"], "Bengaluru")

    def test_conversational_preamble_and_postamble(self):
        raw = """Here is the structured analysis of the job description you requested:

```json
{
  "experience_verdict": "BLOCKED",
  "verdict_reason": "Requires 5+ years of production experience",
  "core_requirements": "Kubernetes, Go, Distributed Systems"
}
```

Let me know if you need any further verification!"""
        cleaned = clean_llm_json(raw)
        data = json.loads(cleaned)
        self.assertEqual(data["experience_verdict"], "BLOCKED")

    def test_unfenced_conversational_wrapping(self):
        raw = 'Sure, here is your result: {"experience_verdict": "POSSIBLE", "verdict_reason": "Experience not specified"} Hope this helps!'
        cleaned = clean_llm_json(raw)
        data = json.loads(cleaned)
        self.assertEqual(data["experience_verdict"], "POSSIBLE")

    def test_array_with_conversational_text(self):
        raw = 'I extracted the following jobs: [{"title": "Software Intern", "company_name": "Acme"}] and that is all.'
        cleaned = clean_llm_json(raw)
        data = json.loads(cleaned)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["title"], "Software Intern")

    def test_empty_and_none_input(self):
        self.assertEqual(clean_llm_json(""), "")
        self.assertEqual(clean_llm_json(None), "")
        self.assertEqual(clean_llm_json("   "), "")

    def test_nested_brackets_in_string(self):
        raw = '{"experience_verdict": "SAFE", "verdict_reason": "Array notation [0-1 yrs] in description"}'
        cleaned = clean_llm_json(raw)
        data = json.loads(cleaned)
        self.assertIn("[0-1 yrs]", data["verdict_reason"])

    def test_unicode_and_special_chars(self):
        raw = '```json\n{"verdict_reason": "Experience in C++, C# & ₹ Indian Rupee compensation"}\n```'
        cleaned = clean_llm_json(raw)
        data = json.loads(cleaned)
        self.assertIn("C++", data["verdict_reason"])
        self.assertIn("₹", data["verdict_reason"])


if __name__ == "__main__":
    unittest.main()
