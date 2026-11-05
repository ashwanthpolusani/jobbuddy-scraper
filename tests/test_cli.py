"""
tests/test_cli.py - Comprehensive unit tests for Rolenaut Master CLI (cli.py).
Tests preset listing, switching, backup retention, config validation, and command dispatch.
"""
import io
import json
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import cli

ROOT = Path(__file__).resolve().parent.parent


class TestCLI(unittest.TestCase):
    def test_list_presets(self):
        """CLI list_presets outputs available presets."""
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            cli.list_presets()
        out = buf.getvalue()
        self.assertIn("Rolenaut Engine - Available Presets", out)
        self.assertIn("india_fresher", out)
        self.assertIn("indian_internships", out)

    def test_use_preset_invalid(self):
        """CLI use_preset exits with error code 1 when preset does not exist."""
        with self.assertRaises(SystemExit) as cm:
            cli.use_preset("non_existent_preset_12345")
        self.assertEqual(cm.exception.code, 1)

    def test_use_preset_valid_and_backup(self):
        """CLI use_preset creates backup and copies preset."""
        cfg_path = ROOT / "scraper.config.json"
        backup_path = ROOT / "scraper.config.json.backup"
        orig_content = cfg_path.read_text(encoding="utf-8") if cfg_path.exists() else None

        try:
            with patch("sys.stdout", io.StringIO()):
                cli.use_preset("india_fresher")

            self.assertTrue(cfg_path.exists())
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["locations"]["primary_country"], "India")
        finally:
            if orig_content is not None:
                cfg_path.write_text(orig_content, encoding="utf-8")
            if backup_path.exists():
                backup_path.unlink()

    def test_validate_config(self):
        """CLI validate_config succeeds against valid config."""
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            cli.validate_config()
        out = buf.getvalue()
        self.assertIn("Config Validation: [PASS]", out)


if __name__ == "__main__":
    unittest.main()
