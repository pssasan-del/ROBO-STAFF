"""Append V4.3 estimated transaction-cost metrics to Telegram performance text."""
from __future__ import annotations


def install_performance_display_overlay(telegram_bot_class):
    original = telegram_bot_class._perf_text

    def _perf_text(title, r):
        base = original(title, r)
        n = int(float(r.get('edge_samples') or 0))
        if n <= 0:
            return base
        extra = (
            f"\nCost-aware samples: {n} | Avg est gross: {float(r.get('avg_est_gross_r') or 0):.2f}R"
            f" | Avg est net: {float(r.get('avg_est_net_r') or 0):.2f}R"
            f"\nAvg option break-even: {float(r.get('avg_est_break_even_pct') or 0):.2f}%"
            f" | Gross/Cost: {float(r.get('avg_gross_cost_multiple') or 0):.2f}x"
        )
        return base + extra

    telegram_bot_class._perf_text = staticmethod(_perf_text)
    return telegram_bot_class
