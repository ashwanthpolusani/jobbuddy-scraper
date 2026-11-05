"""Tests for configuration loader, presets, schema conformity, and safety defaults."""
import json
import os
import unittest
from pathlib import Path
from scraper.config import load_config, DEFAULT_CONFIG, deep_merge, _normalize_config

ROOT = Path(__file__).resolve().parent.parent


class TestConfig(unittest.TestCase):
    def test_default_config_sections(self):
        """Verify all 9 canonical sections are present in DEFAULT_CONFIG."""
        expected_sections = [
            "locations", "experience", "skills", "categories", "compensation",
            "hard_rejection_rules", "ai_models", "database", "runner"
        ]
        for sec in expected_sections:
            self.assertIn(sec, DEFAULT_CONFIG)

    def test_all_presets_valid(self):
        """Ensure all presets in presets/ can be loaded and have valid keys."""
        presets_dir = ROOT / "presets"
        self.assertTrue(presets_dir.exists())
        for p in presets_dir.glob("*.json"):
            with self.subTest(preset=p.stem):
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.assertIsInstance(data, dict)
                self.assertTrue("locations" in data or "experience" in data or "skills" in data)

    def test_load_preset_by_name(self):
        """Verify loading preset directly via load_config(preset=...)."""
        cfg = load_config(preset="india_fresher", require_gemini=False, require_db=False)
        self.assertEqual(cfg["locations"]["primary_country"], "India")

    def test_invalid_preset_raises_filenotfound(self):
        """Verify requesting a non-existent preset raises FileNotFoundError with helpful list."""
        with self.assertRaises(FileNotFoundError):
            load_config(preset="non_existent_preset_xyz")

    def test_deep_merge_immutability(self):
        """Verify deep_merge creates new merged dict without mutating the base."""
        base = {"a": 1, "sub": {"x": 10, "y": 20}}
        override = {"sub": {"y": 99, "z": 30}, "b": 2}
        merged = deep_merge(base, override)

        self.assertEqual(merged["sub"]["x"], 10)
        self.assertEqual(merged["sub"]["y"], 99)
        self.assertEqual(merged["sub"]["z"], 30)
        self.assertEqual(merged["b"], 2)
        # Ensure base was not modified
        self.assertEqual(base["sub"]["y"], 20)
        self.assertNotIn("z", base["sub"])

    def test_require_gemini_flag(self):
        """Verify require_gemini=False allows loading when GEMINI_API_KEY is unset."""
        orig_key = os.environ.get("GEMINI_API_KEY")
        try:
            os.environ["GEMINI_API_KEY"] = ""
            # Should NOT raise with require_gemini=False
            cfg = load_config(require_gemini=False, require_db=False)
            self.assertEqual(cfg["_gemini_api_key"], "")

            # MUST raise with require_gemini=True
            with self.assertRaises(EnvironmentError):
                load_config(require_gemini=True, require_db=False)
        finally:
            if orig_key is not None:
                os.environ["GEMINI_API_KEY"] = orig_key

    def test_legacy_normalization(self):
        """Verify legacy candidate block is properly normalized to 9-section structure."""
        legacy = {
            "candidate": {
                "locations": {
                    "primary_country": "Germany",
                    "cities": ["Berlin", "Munich"],
                    "allow_remote": True,
                },
                "experience": {
                    "min_years": 1,
                    "max_years": 3,
                }
            }
        }
        normalized = _normalize_config(legacy)
        self.assertEqual(normalized["locations"]["primary_country"], "Germany")
        self.assertEqual(normalized["locations"]["allowed_cities"], ["Berlin", "Munich"])
        self.assertEqual(normalized["experience"]["min_years"], 1)
        self.assertEqual(normalized["experience"]["max_years"], 3)


if __name__ == "__main__":
    unittest.main()
