"""
gemini.py - Dual-model Gemini pool with round-robin load balancing and instant failover.
Only sleeps when BOTH models are rate-limited. Config-driven limits.
"""
import time

from google import genai


class ModelPool:
    """
    Manages two Gemini models with:
    - Round-robin load balancing
    - Instant failover on 429/503
    - Per-model RPM and RPD tracking
    - Sleep only when both are exhausted
    """

    def __init__(self, cfg: dict):
        gcfg = cfg.get("ai_models", cfg.get("gemini", {}))
        self._client  = genai.Client(api_key=cfg["_gemini_api_key"])
        self._models  = gcfg.get("models", ["gemini-2.5-flash", "gemini-2.0-flash"])
        self._rpm     = gcfg.get("rpm_limit", 15)
        self._rpd     = gcfg.get("rpd_limit", 1500)
        self._current = 0
        self._stats   = {
            m: {"minute_count": 0, "day_count": 0, "minute_start": time.time()}
            for m in self._models
        }

    # -- Internal helpers -------------------------------------------------------

    def _refresh_minute(self, model: str):
        s = self._stats[model]
        if time.time() - s["minute_start"] >= 60:
            s["minute_count"] = 0
            s["minute_start"] = time.time()

    def _is_available(self, model: str) -> bool:
        self._refresh_minute(model)
        s = self._stats[model]
        return s["minute_count"] < self._rpm and s["day_count"] < self._rpd

    def _record_use(self, model: str):
        self._stats[model]["minute_count"] += 1
        self._stats[model]["day_count"]    += 1

    def _mark_limited(self, model: str):
        self._stats[model]["minute_count"] = self._rpm

    def usage_summary(self) -> dict:
        return {m: self._stats[m]["day_count"] for m in self._models}

    # -- Public API -------------------------------------------------------------

    def generate(self, prompt: str) -> str:
        """
        Try models in round-robin order.
        Instant failover on 429/503.
        Sleeps only when both models are exhausted.
        Returns response text or raises RuntimeError.
        """
        ordered = [
            self._models[(self._current + i) % len(self._models)]
            for i in range(len(self._models))
        ]
        self._current = (self._current + 1) % len(self._models)

        max_global_retries = 3
        for attempt in range(max_global_retries):
            for model in ordered:
                if not self._is_available(model):
                    print(f"  [~] {model} quota reached - skipping to next model")
                    continue
                try:
                    response = self._client.models.generate_content(
                        model=model,
                        contents=prompt,
                        config={"response_mime_type": "application/json"},
                    )
                    self._record_use(model)
                    print(f"  [OK] [{model}] responded")
                    return response.text
                except Exception as e:
                    err = str(e)
                    if "429" in err or "Quota" in err or "503" in err:
                        print(f"  [!] [{model}] rate limited - trying next model instantly")
                        self._mark_limited(model)
                        continue
                    raise

            # Both models exhausted - wait for RPM window to reset
            print(f"  [...] Both models rate limited. Sleeping 65s... (attempt {attempt + 1}/{max_global_retries})")
            time.sleep(65)
            for m in self._models:
                self._stats[m]["minute_count"] = 0
                self._stats[m]["minute_start"] = time.time()

        raise RuntimeError("All Gemini models exhausted after max retries.")
