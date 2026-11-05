"""
tests/test_model_pool.py - Complete deterministic unit test suite for ModelPool.
Verifies round-robin load balancing, instant 429/503 failover, sliding 60s window resets,
dual-exhaustion sleeping (mocked), and max-retry termination without live API costs.
"""
import unittest
from unittest.mock import MagicMock, patch
from scraper.gemini import ModelPool


class TestModelPool(unittest.TestCase):
    def setUp(self):
        self.cfg = {
            "_gemini_api_key": "test-mock-key-12345",
            "ai_models": {
                "models": ["gemini-mock-primary", "gemini-mock-secondary"],
                "rpm_limit": 2,
                "rpd_limit": 10,
            }
        }

    @patch("scraper.gemini.genai.Client")
    def test_initialization_defaults_and_stats(self, mock_client_cls):
        """Verify initialization configures models, limits, and stats structures."""
        pool = ModelPool(self.cfg)
        mock_client_cls.assert_called_once_with(api_key="test-mock-key-12345")
        self.assertEqual(pool._models, ["gemini-mock-primary", "gemini-mock-secondary"])
        self.assertEqual(pool._rpm, 2)
        self.assertEqual(pool._rpd, 10)
        self.assertIn("gemini-mock-primary", pool._stats)
        self.assertIn("gemini-mock-secondary", pool._stats)
        self.assertEqual(pool._stats["gemini-mock-primary"]["minute_count"], 0)
        self.assertEqual(pool._stats["gemini-mock-primary"]["day_count"], 0)

    @patch("scraper.gemini.genai.Client")
    def test_initialization_legacy_gemini_key(self, mock_client_cls):
        """Verify initialization supports legacy 'gemini' key in config."""
        legacy_cfg = {
            "_gemini_api_key": "legacy-key",
            "gemini": {
                "models": ["gemini-legacy-1", "gemini-legacy-2"],
                "rpm_limit": 5,
                "rpd_limit": 100,
            }
        }
        pool = ModelPool(legacy_cfg)
        self.assertEqual(pool._models, ["gemini-legacy-1", "gemini-legacy-2"])
        self.assertEqual(pool._rpm, 5)
        self.assertEqual(pool._rpd, 100)

    @patch("scraper.gemini.genai.Client")
    def test_round_robin_load_balancing(self, mock_client_cls):
        """Verify sequential successful calls alternate models in round-robin fashion."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_resp = MagicMock()
        mock_resp.text = '{"verdict": "SAFE"}'
        mock_client.models.generate_content.return_value = mock_resp

        pool = ModelPool(self.cfg)

        # Call 1 -> Model 0
        r1 = pool.generate("Prompt 1")
        self.assertEqual(r1, '{"verdict": "SAFE"}')
        first_call_model = mock_client.models.generate_content.call_args_list[0].kwargs["model"]
        self.assertEqual(first_call_model, "gemini-mock-primary")

        # Call 2 -> Model 1
        r2 = pool.generate("Prompt 2")
        self.assertEqual(r2, '{"verdict": "SAFE"}')
        second_call_model = mock_client.models.generate_content.call_args_list[1].kwargs["model"]
        self.assertEqual(second_call_model, "gemini-mock-secondary")

        # Call 3 -> Back to Model 0
        r3 = pool.generate("Prompt 3")
        self.assertEqual(r3, '{"verdict": "SAFE"}')
        third_call_model = mock_client.models.generate_content.call_args_list[2].kwargs["model"]
        self.assertEqual(third_call_model, "gemini-mock-primary")

        # Check usage summary tracking
        summary = pool.usage_summary()
        self.assertEqual(summary["gemini-mock-primary"], 2)
        self.assertEqual(summary["gemini-mock-secondary"], 1)

    @patch("scraper.gemini.time.sleep")
    @patch("scraper.gemini.genai.Client")
    def test_instant_failover_on_429_quota_exceeded(self, mock_client_cls, mock_sleep):
        """When Model 0 hits 429, pool must instantly failover to Model 1 without sleep."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        rate_limit_err = Exception("429 ResourceExhausted: Quota exceeded for model")
        success_resp = MagicMock()
        success_resp.text = '{"verdict": "SAFE"}'

        # First call fails on Model 0, succeeds on Model 1
        mock_client.models.generate_content.side_effect = [rate_limit_err, success_resp]

        pool = ModelPool(self.cfg)
        result = pool.generate("Test prompt")

        self.assertEqual(result, '{"verdict": "SAFE"}')
        self.assertEqual(mock_client.models.generate_content.call_count, 2)
        # Instant failover must NOT call sleep!
        mock_sleep.assert_not_called()
        # Model 0 must be marked limited (minute_count set to rpm)
        self.assertEqual(pool._stats["gemini-mock-primary"]["minute_count"], 2)
        # Model 1 must have recorded use
        self.assertEqual(pool._stats["gemini-mock-secondary"]["minute_count"], 1)

    @patch("scraper.gemini.time.sleep")
    @patch("scraper.gemini.genai.Client")
    def test_instant_failover_on_503_service_unavailable(self, mock_client_cls, mock_sleep):
        """When Model 0 hits 503, pool must instantly failover to Model 1 without sleep."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        err_503 = Exception("503 Service Unavailable: Overloaded")
        success_resp = MagicMock(text='{"status": "ok"}')
        mock_client.models.generate_content.side_effect = [err_503, success_resp]

        pool = ModelPool(self.cfg)
        result = pool.generate("Test prompt")
        self.assertEqual(result, '{"status": "ok"}')
        mock_sleep.assert_not_called()
        self.assertEqual(pool._stats["gemini-mock-primary"]["minute_count"], 2)

    @patch("scraper.gemini.genai.Client")
    def test_non_retryable_error_raises_immediately(self, mock_client_cls):
        """Non-quota errors (e.g. 400 Bad Request, Auth) must bubble up immediately."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.models.generate_content.side_effect = ValueError("400 Bad Request: Invalid syntax")

        pool = ModelPool(self.cfg)
        with self.assertRaises(ValueError) as ctx:
            pool.generate("Test prompt")
        self.assertIn("400 Bad Request", str(ctx.exception))
        # Should NOT attempt model 2
        self.assertEqual(mock_client.models.generate_content.call_count, 1)

    @patch("scraper.gemini.time.time")
    @patch("scraper.gemini.genai.Client")
    def test_sliding_window_minute_refresh(self, mock_client_cls, mock_time):
        """Minute count must reset to 0 after 60 seconds have elapsed."""
        mock_time.return_value = 1000.0
        pool = ModelPool(self.cfg)

        # Artificially exhaust model
        pool._stats["gemini-mock-primary"]["minute_count"] = 2
        self.assertFalse(pool._is_available("gemini-mock-primary"))

        # Advance time by 30s -> Still exhausted
        mock_time.return_value = 1030.0
        self.assertFalse(pool._is_available("gemini-mock-primary"))

        # Advance time by 61s -> Reset to 0 and available
        mock_time.return_value = 1061.0
        self.assertTrue(pool._is_available("gemini-mock-primary"))
        self.assertEqual(pool._stats["gemini-mock-primary"]["minute_count"], 0)

    @patch("scraper.gemini.time.sleep")
    @patch("scraper.gemini.genai.Client")
    def test_dual_exhaustion_sleeps_and_recovers(self, mock_client_cls, mock_sleep):
        """When both models are rate-limited, pool sleeps 65s, resets stats, and retries."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        err_429 = Exception("429 Quota Exceeded")
        success_resp = MagicMock(text='{"verdict": "RECOVERED"}')

        # Model 0 fails (429), Model 1 fails (429) -> Sleep 65s -> Model 0 succeeds
        mock_client.models.generate_content.side_effect = [err_429, err_429, success_resp]

        pool = ModelPool(self.cfg)
        result = pool.generate("Prompt")

        self.assertEqual(result, '{"verdict": "RECOVERED"}')
        mock_sleep.assert_called_once_with(65)
        self.assertEqual(mock_client.models.generate_content.call_count, 3)

    @patch("scraper.gemini.time.sleep")
    @patch("scraper.gemini.genai.Client")
    def test_max_retries_exhaustion_raises_runtime_error(self, mock_client_cls, mock_sleep):
        """If both models fail across all 3 retry loops, RuntimeError must be raised."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.models.generate_content.side_effect = Exception("429 ResourceExhausted")

        pool = ModelPool(self.cfg)
        with self.assertRaises(RuntimeError) as ctx:
            pool.generate("Prompt")

        self.assertIn("All Gemini models exhausted after max retries", str(ctx.exception))
        # 3 global attempts * 1 sleep per dual-failure = 3 sleeps
        self.assertEqual(mock_sleep.call_count, 3)

    @patch("scraper.gemini.genai.Client")
    def test_daily_rpd_limit_blocks_availability(self, mock_client_cls):
        """Reaching the RPD daily limit marks the model unavailable even after minute resets."""
        pool = ModelPool(self.cfg)
        pool._stats["gemini-mock-primary"]["day_count"] = 10  # rpd_limit is 10
        self.assertFalse(pool._is_available("gemini-mock-primary"))


if __name__ == "__main__":
    unittest.main()
