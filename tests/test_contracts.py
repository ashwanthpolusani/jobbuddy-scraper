"""
tests/test_contracts.py - API Contract testing for Stage 1 and Stage 2 LLM JSON outputs.
Tests schema validity, required key presence, enum restrictions, markdown code fence cleaning,
and robust fallback handling for malformed or corrupted LLM payloads.
"""
import json
import re
import unittest
import jsonschema


# Formal JSON Schema Contracts for Gemini Outputs

STAGE1_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "required": [
            "title", "company_name", "location", "link",
            "link_type", "category", "experience_verdict"
        ],
        "properties": {
            "title": {"type": "string", "minLength": 1},
            "company_name": {"type": "string"},
            "location": {"type": "string"},
            "core_requirements": {"type": "string"},
            "link": {"type": "string"},
            "link_type": {"type": "string", "enum": ["direct_apply", "filtered_list"]},
            "category": {"type": "string"},
            "experience_verdict": {"type": "string", "enum": ["SAFE", "POSSIBLE", "BLOCKED"]},
            "error_type": {"type": "string"}
        },
        "additionalProperties": True
    }
}

STAGE2_SCHEMA = {
    "type": "object",
    "required": ["experience_verdict", "verdict_reason", "core_requirements"],
    "properties": {
        "experience_verdict": {
            "type": "string",
            "enum": ["SAFE", "POSSIBLE", "BLOCKED"]
        },
        "verdict_reason": {
            "type": "string",
            "minLength": 3
        },
        "core_requirements": {
            "type": "string"
        }
    },
    "additionalProperties": True
}


def sanitize_markdown_fences(text: str) -> str:
    """Strips markdown code fences (```json ... ``` or ``` ... ```) commonly output by LLMs."""
    if not text:
        return ""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*```$", "", t)
    return t.strip()


class TestLLMContracts(unittest.TestCase):
    def test_valid_stage1_contract(self):
        """Valid Stage 1 payload passes JSON schema validation."""
        valid_json = [
            {
                "title": "Junior Python Developer",
                "company_name": "Acme Corp",
                "location": "Bengaluru, India",
                "core_requirements": "Python, Django, PostgreSQL",
                "link": "https://acme.com/jobs/101",
                "link_type": "direct_apply",
                "category": "software_engineering",
                "experience_verdict": "SAFE"
            },
            {
                "title": "Graduate Rotational Program",
                "company_name": "Tech Corp",
                "location": "Worldwide Remote",
                "core_requirements": "Java, Cloud fundamentals",
                "link": "https://techcorp.com/careers/early-talent",
                "link_type": "filtered_list",
                "category": "software_engineering",
                "experience_verdict": "POSSIBLE"
            }
        ]
        # Should not raise
        jsonschema.validate(instance=valid_json, schema=STAGE1_SCHEMA)

    def test_invalid_stage1_missing_required_keys(self):
        """Missing required keys violates Stage 1 contract."""
        invalid_json = [
            {
                "title": "Software Engineer",
                "company_name": "Incomplete Inc"
                # Missing location, link, link_type, category, experience_verdict
            }
        ]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(instance=invalid_json, schema=STAGE1_SCHEMA)

    def test_invalid_stage1_invalid_link_type_enum(self):
        """Invalid link_type violates enum constraint."""
        invalid_json = [
            {
                "title": "Developer",
                "company_name": "Acme",
                "location": "Remote",
                "core_requirements": "Python",
                "link": "https://acme.com",
                "link_type": "unknown_link_type",
                "category": "software_engineering",
                "experience_verdict": "SAFE"
            }
        ]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(instance=invalid_json, schema=STAGE1_SCHEMA)

    def test_valid_stage2_contract(self):
        """Valid Stage 2 payload passes JSON schema validation."""
        valid_obj = {
            "experience_verdict": "SAFE",
            "verdict_reason": "Accepts Bachelor's degree for fresh graduates (0 YOE) or 4 years experience in lieu of degree.",
            "core_requirements": "Bachelor's degree in CS (or 4 years in lieu), Python, Django, SQL."
        }
        jsonschema.validate(instance=valid_obj, schema=STAGE2_SCHEMA)

    def test_invalid_stage2_illegal_verdict_enum(self):
        """Non-standard verdict (e.g. 'MAYBE' or 'ELIGIBLE') violates Stage 2 contract."""
        invalid_obj = {
            "experience_verdict": "MAYBE",
            "verdict_reason": "Ambiguous wording in posting.",
            "core_requirements": "Python, AWS"
        }
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(instance=invalid_obj, schema=STAGE2_SCHEMA)

    def test_invalid_stage2_missing_verdict_reason(self):
        """Missing verdict_reason violates Stage 2 contract."""
        invalid_obj = {
            "experience_verdict": "SAFE",
            "core_requirements": "Python, AWS"
        }
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(instance=invalid_obj, schema=STAGE2_SCHEMA)

    def test_markdown_fence_cleaning_single_and_multi_line(self):
        """LLM output enclosed in ```json ... ``` markdown fences is stripped cleanly."""
        raw_output_json_fence = (
            "```json\n"
            "{\n"
            '  "experience_verdict": "SAFE",\n'
            '  "verdict_reason": "Entry-level new grad position.",\n'
            '  "core_requirements": "Python, SQL"\n'
            "}\n"
            "```"
        )
        clean = sanitize_markdown_fences(raw_output_json_fence)
        parsed = json.loads(clean)
        jsonschema.validate(instance=parsed, schema=STAGE2_SCHEMA)
        self.assertEqual(parsed["experience_verdict"], "SAFE")

        raw_output_generic_fence = (
            "```\n"
            "{\n"
            '  "experience_verdict": "BLOCKED",\n'
            '  "verdict_reason": "Requires 7+ years of experience.",\n'
            '  "core_requirements": "Go, Distributed Systems"\n'
            "}\n"
            "```"
        )
        clean2 = sanitize_markdown_fences(raw_output_generic_fence)
        parsed2 = json.loads(clean2)
        jsonschema.validate(instance=parsed2, schema=STAGE2_SCHEMA)
        self.assertEqual(parsed2["experience_verdict"], "BLOCKED")

    def test_empty_or_malformed_json_fallback(self):
        """Sanitizing empty or non-JSON string handles edge cases gracefully."""
        self.assertEqual(sanitize_markdown_fences(""), "")
        self.assertEqual(sanitize_markdown_fences(None), "")
        with self.assertRaises(json.JSONDecodeError):
            json.loads(sanitize_markdown_fences("This is not valid JSON"))


if __name__ == "__main__":
    unittest.main()
