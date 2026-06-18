"""Unit tests for FinOps Gemini cost estimation (Decimal, cache-aware + tiered).

``estimate_gemini_cost_usd`` must return an exact ``Decimal``, never raise, and reflect the three
billing realities: context-cache discounts, the long-context (short/long) tier split, and an
unknown-model fallback.
"""
import os
import unittest
from decimal import Decimal
from types import SimpleNamespace

# config imports src.shared.core.config at import time and needs a key present.
os.environ.setdefault("GEMINI_API_KEY", "test-key")

from src.shared.core.config import estimate_gemini_cost_usd, MODEL_PRICING_MATRIX


def _usage(prompt: int, output: int, cached: int = 0, details=None) -> SimpleNamespace:
    return SimpleNamespace(
        prompt_token_count=prompt,
        candidates_token_count=output,
        cached_content_token_count=cached,
        prompt_tokens_details=details,
    )


class EstimateGeminiCostTests(unittest.TestCase):
    FLASH = "gemini-3.1-flash-lite"      # short/long flat: (0.25, 1.50, 0.025) /1M
    PRO = "gemini-3.1-pro-preview"       # tiered: short (2,12,0.2) -> long (4,18,0.4) at 200k
    PRO_25 = "gemini-2.5-pro"            # tiered: short (1.25,10,0.125) -> long (2.5,15,0.25) at 200k

    def test_returns_decimal_type(self) -> None:
        self.assertIsInstance(estimate_gemini_cost_usd(self.FLASH, _usage(1000, 100)), Decimal)

    def test_uncached_input_and_output_exact(self) -> None:
        # 1M uncached input @0.25 + 1M output @1.50 = exactly 1.75.
        cost = estimate_gemini_cost_usd(self.FLASH, _usage(prompt=1_000_000, output=1_000_000))
        self.assertEqual(cost, Decimal("1.75"))

    def test_cached_tokens_are_cheaper_than_flat(self) -> None:
        # 100k prompt of which 60k cached, 10k output.
        usage = _usage(prompt=100_000, output=10_000, cached=60_000)
        cost = estimate_gemini_cost_usd(self.FLASH, usage)
        # 40k*0.25 + 60k*0.025 + 10k*1.50, all /1e6 — computed in Decimal.
        expected = (Decimal(40_000) * Decimal("0.25") + Decimal(60_000) * Decimal("0.025")
                    + Decimal(10_000) * Decimal("1.50")) / Decimal(1_000_000)
        self.assertEqual(cost, expected)
        # Strictly cheaper than pricing all input at the uncached rate.
        flat = (Decimal(100_000) * Decimal("0.25") + Decimal(10_000) * Decimal("1.50")) / Decimal(1_000_000)
        self.assertLess(cost, flat)

    def test_long_tier_applies_over_threshold(self) -> None:
        # 300k prompt (> 200k) → long tier input 4.0 / output 18.0.
        cost = estimate_gemini_cost_usd(self.PRO, _usage(prompt=300_000, output=1_000))
        expected = (Decimal(300_000) * Decimal("4.00") + Decimal(1_000) * Decimal("18.00")) / Decimal(1_000_000)
        self.assertEqual(cost, expected)

    def test_short_tier_under_threshold(self) -> None:
        # 100k prompt (<= 200k) → short tier input 2.0 / output 12.0.
        cost = estimate_gemini_cost_usd(self.PRO, _usage(prompt=100_000, output=1_000))
        expected = (Decimal(100_000) * Decimal("2.00") + Decimal(1_000) * Decimal("12.00")) / Decimal(1_000_000)
        self.assertEqual(cost, expected)

    def test_gemini_2_5_pro_long_tier_doubles_over_threshold(self) -> None:
        # 300k prompt (> 200k) → corrected long tier input 2.50 / output 15.00 (was wrongly == short).
        cost = estimate_gemini_cost_usd(self.PRO_25, _usage(prompt=300_000, output=1_000))
        expected = (Decimal(300_000) * Decimal("2.50") + Decimal(1_000) * Decimal("15.00")) / Decimal(1_000_000)
        self.assertEqual(cost, expected)

    def test_gemini_2_5_flash_cached_read_rate(self) -> None:
        # Corrected cached_read rate 0.03/1M: 100k cached-only prompt = 100k * 0.03 / 1e6.
        cost = estimate_gemini_cost_usd("gemini-2.5-flash", _usage(prompt=100_000, output=0, cached=100_000))
        self.assertEqual(cost, Decimal(100_000) * Decimal("0.03") / Decimal(1_000_000))

    def test_unknown_model_uses_default_rates(self) -> None:
        # Falls back to gemini-2.5-flash-lite (short input 0.10).
        self.assertNotIn("gemini-imaginary", MODEL_PRICING_MATRIX)
        cost = estimate_gemini_cost_usd("gemini-imaginary", _usage(prompt=1_000_000, output=0))
        self.assertEqual(cost, Decimal("0.10"))

    def test_missing_fields_do_not_crash(self) -> None:
        # A bare object with no usage attributes → Decimal("0"), no exception.
        self.assertEqual(estimate_gemini_cost_usd(self.FLASH, object()), Decimal("0"))

    def test_cached_exceeding_prompt_never_negative(self) -> None:
        # Defensive: cached > prompt must not produce a negative cost.
        cost = estimate_gemini_cost_usd(self.FLASH, _usage(prompt=10, output=0, cached=1000))
        self.assertGreaterEqual(cost, Decimal("0"))


if __name__ == "__main__":
    unittest.main()
