"""
tests/test_golden_evaluation.py - Golden dataset benchmark covering 10 critical edge cases.
Specifically evaluates:
1. Education-in-Lieu substitution clauses ("4 years experience OR Bachelor's degree")
2. Strict mandatory experience ("Degree AND 5+ years")
3. Campus / New Grad hires
4. Unspecified experience for junior roles
5. Hard rejection: Security clearance
6. Hard rejection: Foreign language
7. Hard rejection: Minimum compensation unmet
8. Hard rejection: Internship-only candidate on permanent role
9. Experienced candidate profile reversing junior roles
10. Reverse substitution clause ("Degree or equivalent work experience")
"""
import copy
import json
import unittest
from unittest.mock import MagicMock
from scraper.config import DEFAULT_CONFIG
from scraper.prompts import build_stage2
from stage2 import score_job


GOLDEN_BENCHMARK = [
    {
        "id": "GOLD-001",
        "category": "education_in_lieu",
        "title": "Software Engineer I",
        "jd_text": (
            "About the Role: We are seeking a Software Engineer to join our core backend team. "
            "Qualifications: Bachelor's degree in Computer Science or 4+ years of professional software engineering experience. "
            "Proficient in Python, SQL, and Git."
        ),
        "profile_override": {
            "target_level": "fresher",
            "min_years": 0,
            "max_years": 1,
            "blocked_threshold_years": 1
        },
        "expected_verdict": "SAFE",
        "forbidden_verdicts": ["BLOCKED"],
        "prompt_must_contain": [
            "IN-LIEU education-experience substitution clause",
            "Do NOT classify as \"BLOCKED\"",
            "Accepts Bachelor's degree for fresh graduates (0 YOE)"
        ],
        "simulated_llm_response": {
            "experience_verdict": "SAFE",
            "verdict_reason": "Accepts Bachelor's degree for fresh graduates (0 YOE), or 4 years experience in lieu of a degree.",
            "core_requirements": "Bachelor's degree in Computer Science (or 4 years in lieu), Python, SQL, and Git."
        }
    },
    {
        "id": "GOLD-002",
        "category": "reverse_education_in_lieu",
        "title": "Associate Developer",
        "jd_text": (
            "Requirements: 3+ years of relevant experience, or an equivalent combination of education "
            "(Bachelor's degree) and experience. Strong understanding of Java and Spring Boot."
        ),
        "profile_override": {
            "target_level": "fresher",
            "min_years": 0,
            "max_years": 1,
            "blocked_threshold_years": 1
        },
        "expected_verdict": "SAFE",
        "forbidden_verdicts": ["BLOCKED"],
        "prompt_must_contain": [
            "IN-LIEU education-experience substitution clause",
            "Do NOT classify as \"BLOCKED\""
        ],
        "simulated_llm_response": {
            "experience_verdict": "SAFE",
            "verdict_reason": "Accepts Bachelor's degree for fresh graduates (0 YOE), or 3 years experience in lieu of degree.",
            "core_requirements": "Bachelor's degree or 3 years experience in lieu, Java, Spring Boot."
        }
    },
    {
        "id": "GOLD-003",
        "category": "strict_experience_mandatory",
        "title": "Senior Software Engineer",
        "jd_text": (
            "Requirements: Bachelor's degree in Computer Science AND a minimum of 5 years of hands-on "
            "software development experience building distributed microservices in Go and Kubernetes."
        ),
        "profile_override": {
            "target_level": "fresher",
            "min_years": 0,
            "max_years": 1,
            "blocked_threshold_years": 1
        },
        "expected_verdict": "BLOCKED",
        "forbidden_verdicts": ["SAFE", "POSSIBLE"],
        "prompt_must_contain": [
            "Degree AND X+ years experience",
            "If X > 1, classify strictly as \"BLOCKED\""
        ],
        "simulated_llm_response": {
            "experience_verdict": "BLOCKED",
            "verdict_reason": "Strictly requires Bachelor's degree AND minimum 5 years of software development experience.",
            "core_requirements": "Go, Kubernetes, distributed microservices."
        }
    },
    {
        "id": "GOLD-004",
        "category": "explicit_fresher_campus",
        "title": "Graduate Engineer Trainee - 2026 Batch",
        "jd_text": (
            "We are looking for fresh campus graduates (2025/2026 passing out batch). 0-1 years experience. "
            "Must have basic knowledge of Data Structures, Algorithms, and C++ or Java."
        ),
        "profile_override": {
            "target_level": "fresher",
            "min_years": 0,
            "max_years": 1,
            "blocked_threshold_years": 1
        },
        "expected_verdict": "SAFE",
        "forbidden_verdicts": ["BLOCKED"],
        "prompt_must_contain": [
            "SAFE\": Posting matches candidate target experience (0-1 years)",
            "campus hires, or entry-level"
        ],
        "simulated_llm_response": {
            "experience_verdict": "SAFE",
            "verdict_reason": "Explicitly targets 2025/2026 fresh campus graduates with 0-1 years of experience.",
            "core_requirements": "Data Structures, Algorithms, C++, Java."
        }
    },
    {
        "id": "GOLD-005",
        "category": "unspecified_experience_junior",
        "title": "Junior Full Stack Developer",
        "jd_text": (
            "Seeking an enthusiastic Junior Full Stack Developer to build modern web apps with Next.js and Node.js. "
            "Willingness to learn and collaborate with senior engineers is required."
        ),
        "profile_override": {
            "target_level": "fresher",
            "min_years": 0,
            "max_years": 1,
            "blocked_threshold_years": 1
        },
        "expected_verdict": "POSSIBLE",
        "forbidden_verdicts": ["BLOCKED"],
        "prompt_must_contain": [
            "POSSIBLE\": Experience requirement is completely unspecified or ambiguous"
        ],
        "simulated_llm_response": {
            "experience_verdict": "POSSIBLE",
            "verdict_reason": "Experience requirement is unspecified, but role explicitly targets junior engineers.",
            "core_requirements": "Next.js, Node.js, modern web stack."
        }
    },
    {
        "id": "GOLD-006",
        "category": "hard_rule_security_clearance",
        "title": "Software Developer - Defense Systems",
        "jd_text": (
            "Early career opportunity for developers. 0-2 years experience. "
            "Candidates must hold an active Top Secret / SCI clearance with polygraph."
        ),
        "profile_override": {
            "target_level": "fresher",
            "min_years": 0,
            "max_years": 1,
            "blocked_threshold_years": 1
        },
        "expected_verdict": "BLOCKED",
        "forbidden_verdicts": ["SAFE", "POSSIBLE"],
        "prompt_must_contain": [
            "fails special rules"
        ],
        "simulated_llm_response": {
            "experience_verdict": "BLOCKED",
            "verdict_reason": "Requires active Top Secret / SCI security clearance.",
            "core_requirements": "C++, Linux, Defense systems."
        }
    },
    {
        "id": "GOLD-007",
        "category": "hard_rule_foreign_language",
        "title": "Backend Engineer",
        "jd_text": (
            "Entry-level position for Python developers. Candidates must be fluent in German with minimum "
            "Goethe-Zertifikat C1 or CEFR C1 certification."
        ),
        "profile_override": {
            "target_level": "fresher",
            "min_years": 0,
            "max_years": 1,
            "blocked_threshold_years": 1
        },
        "prompt_must_contain": [
            "MANDATORY FOREIGN LANGUAGE RULE",
            "German C1, Japanese JLPT N1/N2"
        ],
        "expected_verdict": "BLOCKED",
        "forbidden_verdicts": ["SAFE", "POSSIBLE"],
        "simulated_llm_response": {
            "experience_verdict": "BLOCKED",
            "verdict_reason": "Requires mandatory non-English fluency: German C1 certification.",
            "core_requirements": "Python, German C1."
        }
    },
    {
        "id": "GOLD-008",
        "category": "hard_rule_salary_unmet",
        "title": "Frontend Engineer",
        "jd_text": (
            "Entry-level React developer position. Compensation for this role is strictly 3 LPA INR ($3,500 USD) annually."
        ),
        "profile_override": {
            "target_level": "fresher",
            "min_years": 0,
            "max_years": 1,
            "blocked_threshold_years": 1
        },
        "config_extra": {
            "compensation": {
                "require_salary_disclosed": True,
                "min_annual_inr_lpa": 8,
                "min_annual_usd": 15000
            }
        },
        "prompt_must_contain": [
            "SALARY REQUIREMENT",
            "Min INR: 8 LPA",
            "Min USD: $15,000/year"
        ],
        "expected_verdict": "BLOCKED",
        "forbidden_verdicts": ["SAFE", "POSSIBLE"],
        "simulated_llm_response": {
            "experience_verdict": "BLOCKED",
            "verdict_reason": "Disclosed salary (3 LPA) is strictly below the required minimum (8 LPA).",
            "core_requirements": "React, JavaScript."
        }
    },
    {
        "id": "GOLD-009",
        "category": "internship_only_gate",
        "title": "Full Stack Engineer (Permanent)",
        "jd_text": (
            "Full-time permanent position. Requires a completed Bachelor's degree. "
            "Not open to current students or interns."
        ),
        "profile_override": {
            "target_level": "internship",
            "internships_only": True,
            "min_years": 0,
            "max_years": 0,
            "blocked_threshold_years": 0
        },
        "prompt_must_contain": [
            "INTERNSHIP REQUIREMENT",
            "strictly seeks an INTERNSHIP / CO-OP / STUDENT role",
            "permanent full-time position requiring a completed degree or prior experience -> BLOCKED"
        ],
        "expected_verdict": "BLOCKED",
        "forbidden_verdicts": ["SAFE", "POSSIBLE"],
        "simulated_llm_response": {
            "experience_verdict": "BLOCKED",
            "verdict_reason": "Candidate strictly seeks an internship; posting is a permanent full-time position.",
            "core_requirements": "TypeScript, React, Node.js."
        }
    },
    {
        "id": "GOLD-010",
        "category": "experienced_candidate_reversal",
        "title": "Summer Undergraduate Intern",
        "jd_text": (
            "Summer 2026 internship for currently enrolled college students. 0 years experience required."
        ),
        "profile_override": {
            "target_level": "senior",
            "min_years": 5,
            "max_years": 8,
            "blocked_threshold_years": 8
        },
        "prompt_must_contain": [
            "EXPERIENCED CANDIDATE RULE",
            "candidate has 5+ years of experience",
            "fresher, or intern position (< 5 years) -> BLOCKED"
        ],
        "expected_verdict": "BLOCKED",
        "forbidden_verdicts": ["SAFE", "POSSIBLE"],
        "simulated_llm_response": {
            "experience_verdict": "BLOCKED",
            "verdict_reason": "Candidate has 5+ years of experience, but role is strictly a student internship.",
            "core_requirements": "Basic programming knowledge, Python or C++."
        }
    }
]


class TestGoldenEvaluation(unittest.TestCase):
    def setUp(self):
        self.cfg = copy.deepcopy(DEFAULT_CONFIG)

    def test_golden_prompt_construction(self):
        """Verify prompt builder embeds all required disambiguation and constraint clauses for each case."""
        for case in GOLDEN_BENCHMARK:
            cfg = copy.deepcopy(self.cfg)
            cfg["experience"].update(case["profile_override"])
            if "config_extra" in case:
                cfg.update(case["config_extra"])

            prompt = build_stage2(cfg, case["jd_text"])
            for clause in case["prompt_must_contain"]:
                self.assertIn(
                    clause,
                    prompt,
                    f"[{case['id']}: {case['category']}] Missing expected clause '{clause}' in generated prompt."
                )

    def test_golden_evaluation_verdict_accuracy(self):
        """Simulate execution through score_job and verify expected vs forbidden verdicts."""
        for case in GOLDEN_BENCHMARK:
            cfg = copy.deepcopy(self.cfg)
            cfg["experience"].update(case["profile_override"])
            if "config_extra" in case:
                cfg.update(case["config_extra"])

            mock_pool = MagicMock()
            mock_pool.generate.return_value = json.dumps(case["simulated_llm_response"])

            result = score_job(cfg, case["jd_text"], mock_pool)
            self.assertIsNotNone(result, f"[{case['id']}] score_job returned None.")

            verdict = result.get("experience_verdict")
            self.assertEqual(
                verdict,
                case["expected_verdict"],
                f"[{case['id']}: {case['category']}] Expected verdict '{case['expected_verdict']}', got '{verdict}'."
            )
            self.assertNotIn(
                verdict,
                case["forbidden_verdicts"],
                f"[{case['id']}: {case['category']}] Verdict '{verdict}' is in strictly forbidden list {case['forbidden_verdicts']}!"
            )

    def test_education_in_lieu_never_blocked(self):
        """Explicit assertion: Education-in-Lieu cases (GOLD-001, GOLD-002) must NEVER evaluate to BLOCKED."""
        for case in GOLDEN_BENCHMARK:
            if "education_in_lieu" in case["category"]:
                cfg = copy.deepcopy(self.cfg)
                cfg["experience"].update(case["profile_override"])

                mock_pool = MagicMock()
                mock_pool.generate.return_value = json.dumps(case["simulated_llm_response"])

                result = score_job(cfg, case["jd_text"], mock_pool)
                self.assertNotEqual(
                    result["experience_verdict"],
                    "BLOCKED",
                    f"CRITICAL: Education-in-lieu clause [{case['id']}] was incorrectly classified as BLOCKED!"
                )
                self.assertIn(
                    result["experience_verdict"],
                    ["SAFE", "POSSIBLE"],
                    f"Education-in-lieu clause [{case['id']}] must be SAFE or POSSIBLE."
                )


if __name__ == "__main__":
    unittest.main()
