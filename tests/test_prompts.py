"""
tests/test_prompts.py - Unit tests for dynamic Stage 1 and Stage 2 prompt generation.
Verifies config interpolation, candidate profile tiers (fresher, mid-level, senior),
education-in-lieu clauses, internships, foreign language, and salary disclosure rules.
"""
import copy
import unittest
from scraper.prompts import build_stage1, build_stage2, stage1_prompt, stage2_prompt
from scraper.config import DEFAULT_CONFIG


class TestPromptBuilders(unittest.TestCase):
    def setUp(self):
        self.cfg = copy.deepcopy(DEFAULT_CONFIG)

    def test_stage1_prompt_fresher_tier(self):
        """Stage 1 prompt for fresher profile must include entry-level target instructions."""
        prompt = build_stage1(self.cfg, "Raw career page text")
        self.assertIn("TARGET CANDIDATE: Fresh Graduate / Entry-level (0-1 years experience)", prompt)
        self.assertIn("ACCEPT: 'fresher', 'entry-level', 'new grad'", prompt)
        self.assertIn("REJECT: Any role requiring 2+ years", prompt)
        self.assertIn("India", prompt)
        self.assertIn("software_engineering", prompt)
        self.assertIn("experience_verdict", prompt)
        self.assertIn("Raw career page text", prompt)

    def test_stage1_prompt_mid_level_tier(self):
        """Stage 1 prompt for 2-4 years candidate profile."""
        mid_cfg = copy.deepcopy(self.cfg)
        mid_cfg["experience"]["min_years"] = 2
        mid_cfg["experience"]["max_years"] = 4
        prompt = build_stage1(mid_cfg, "Raw career page text")
        self.assertIn("TARGET CANDIDATE: Experienced Professional (2 to 4 years experience)", prompt)
        self.assertIn("Mid-level roles, SDE-2", prompt)
        self.assertIn("REJECT: Intern/trainee/0-year roles", prompt)

    def test_stage1_prompt_senior_tier(self):
        """Stage 1 prompt for senior profile (5+ years)."""
        sr_cfg = copy.deepcopy(self.cfg)
        sr_cfg["experience"]["min_years"] = 5
        sr_cfg["experience"]["max_years"] = 10
        prompt = build_stage1(sr_cfg, "Raw career page text")
        self.assertIn("TARGET CANDIDATE: Senior / Lead / Staff (5+ years of experience)", prompt)
        self.assertIn("Senior, Staff, Lead", prompt)
        self.assertIn("REJECT: Entry-level, intern, trainee", prompt)

    def test_stage2_fresher_prompt_has_education_in_lieu_clause(self):
        """Stage 2 fresher prompt must explicitly instruct on Education-in-Lieu substitution."""
        prompt = build_stage2(self.cfg, "Sample JD text")
        self.assertIn("EXPERIENCE CLAUSE DISAMBIGUATION RULES", prompt)
        self.assertIn("IN-LIEU education-experience substitution clause", prompt)
        self.assertIn("Bachelor's degree in Computer Science", prompt)
        self.assertIn("Do NOT classify as \"BLOCKED\"", prompt)
        self.assertIn("Sample JD text", prompt)

    def test_stage2_internship_only_rule_injected(self):
        """Stage 2 prompt must inject internship restriction when configured."""
        intern_cfg = copy.deepcopy(self.cfg)
        intern_cfg["experience"]["internships_only"] = True
        intern_cfg["experience"]["target_level"] = "internship"
        prompt = build_stage2(intern_cfg, "Sample JD text")
        self.assertIn("INTERNSHIP REQUIREMENT", prompt)
        self.assertIn("strictly seeks an INTERNSHIP / CO-OP / STUDENT role", prompt)

    def test_stage2_senior_rules_injected_when_min_years_ge_3(self):
        """When candidate has min_years >= 3, prompt must inject senior candidate rejection rule."""
        sr_cfg = copy.deepcopy(self.cfg)
        sr_cfg["experience"]["min_years"] = 5
        sr_cfg["experience"]["max_years"] = 8
        sr_cfg["experience"]["target_level"] = "senior"

        prompt = build_stage2(sr_cfg, "Sample JD text")
        self.assertIn("EXPERIENCED CANDIDATE RULE", prompt)
        self.assertIn("5+ years of experience", prompt)
        self.assertIn("entry-level, fresher, or intern position (< 5 years) -> BLOCKED", prompt)

    def test_stage2_foreign_language_rule_injected(self):
        """Mandatory foreign language rule must be injected when enabled in config."""
        prompt = build_stage2(self.cfg, "Sample JD text")
        self.assertIn("MANDATORY FOREIGN LANGUAGE RULE", prompt)
        self.assertIn("German C1, Japanese JLPT N1/N2", prompt)

    def test_stage2_salary_rule_injected_when_configured(self):
        """Salary requirement rule must be injected when require_salary_disclosed is true."""
        comp_cfg = copy.deepcopy(self.cfg)
        comp_cfg["compensation"] = {
            "require_salary_disclosed": True,
            "min_annual_usd": 75000,
            "min_annual_inr_lpa": 15
        }
        prompt = build_stage2(comp_cfg, "Sample JD text")
        self.assertIn("SALARY REQUIREMENT", prompt)
        self.assertIn("$75,000/year", prompt)
        self.assertIn("15 LPA", prompt)

    def test_backward_compatibility_prompt_handlers(self):
        """stage1_prompt.build() and stage2_prompt.build() must produce identical output to functions."""
        jd_text = "Software Engineer at Google. Python and distributed systems."
        p1 = stage1_prompt.build(self.cfg, jd_text)
        p2 = build_stage1(self.cfg, jd_text)
        self.assertEqual(p1, p2)

        p3 = stage2_prompt.build(self.cfg, jd_text)
        p4 = build_stage2(self.cfg, jd_text)
        self.assertEqual(p3, p4)


if __name__ == "__main__":
    unittest.main()
