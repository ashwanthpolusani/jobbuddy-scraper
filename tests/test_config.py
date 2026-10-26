"""Tests for configuration loader, presets, and schema conformity."""
import json
import unittest
from pathlib import Path
from scraper.config import load_config, DEFAULT_CONFIG

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
                # Verify key sections exist
                self.assertTrue("locations" in data or "experience" in data or "skills" in data)


if __name__ == "__main__":
    unittest.main()
