import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from visualization.analysis import (
    calculate_metrics,
    monthly_returns,
    normalize_benchmark_returns,
    normalize_trade_records,
    pair_round_trips,
    prepare_daily_results,
    reconstruct_positions,
    vt_symbol_to_ts_code,
)


class VisualizationAnalysisTests(unittest.TestCase):
    def test_first_day_return_and_drawdown_use_initial_capital(self):
        dates = pd.to_datetime(["2026-01-02", "2026-01-05"])
        daily = prepare_daily_results(
            pd.DataFrame({"net_pnl": [100.0, -50.0]}, index=dates), 1_000.0
        )

        self.assertAlmostEqual(daily.loc[dates[0], "daily_return"], 0.10)
        self.assertAlmostEqual(daily.loc[dates[1], "daily_return"], 1050 / 1100 - 1)
        self.assertEqual(daily.loc[dates[0], "high_watermark"], 1100.0)
        self.assertAlmostEqual(daily.loc[dates[1], "drawdown"], 1050 / 1100 - 1)
        self.assertAlmostEqual(
            (1 + daily["daily_return"]).prod(), daily["balance"].iloc[-1] / 1000
        )

    def test_drawdown_start_is_period_start_when_balance_never_reaches_initial_capital(self):
        dates = pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"])
        daily = prepare_daily_results(
            pd.DataFrame({"net_pnl": [-100.0, 50.0, -200.0]}, index=dates), 1_000.0
        )
        metrics = calculate_metrics(
            daily,
            pd.DataFrame(
                columns=[
                    "vt_symbol",
                    "status",
                    "gross_pnl",
                    "gross_return",
                    "holding_trading_days",
                ]
            ),
            240,
            initial_capital=1_000.0,
        )

        self.assertEqual(metrics["max_drawdown_start"], "2026-01-02")
        self.assertEqual(metrics["max_drawdown_end"], "2026-01-06")

    def test_prepare_daily_results_and_monthly_compounding(self):
        dates = pd.to_datetime(["2026-01-02", "2026-01-05", "2026-02-02"])
        source = pd.DataFrame({"net_pnl": [0.0, 100.0, -50.0]}, index=dates)
        daily = prepare_daily_results(source, 1_000.0)

        self.assertEqual(list(daily["balance"]), [1000.0, 1100.0, 1050.0])
        self.assertAlmostEqual(daily["drawdown"].iloc[-1], 1050 / 1100 - 1)
        monthly = monthly_returns(daily)
        self.assertAlmostEqual(monthly.loc[2026, 1], 0.1)
        self.assertAlmostEqual(monthly.loc[2026, 2], 1050 / 1100 - 1)
        self.assertAlmostEqual(monthly.loc[2026, "annual"], 0.05)

    def test_fifo_pairing_supports_partial_fills_and_open_lots(self):
        trades = normalize_trade_records(
            [
                {"vt_symbol": "000001.SZSE", "direction": "Long", "offset": "Open", "price": 10, "volume": 100, "datetime": "2026-01-02"},
                {"vt_symbol": "000001.SZSE", "direction": "Long", "offset": "Open", "price": 12, "volume": 100, "datetime": "2026-01-05"},
                {"vt_symbol": "000001.SZSE", "direction": "Short", "offset": "Close", "price": 15, "volume": 150, "datetime": "2026-01-07"},
            ]
        )
        dates = pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"])
        result, metadata = pair_round_trips(trades, dates)
        closed = result[result["status"] == "closed"]

        self.assertEqual(list(closed["volume"]), [100.0, 50.0])
        self.assertAlmostEqual(closed["gross_pnl"].sum(), 650.0)
        self.assertEqual(metadata["unmatched_open_lots"], 1)
        self.assertEqual(result.iloc[-1]["status"], "open_at_end")

    def test_benchmark_normalization_uses_common_first_date(self):
        dates = pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"])
        benchmarks = pd.DataFrame(
            {
                "date": list(dates) + list(dates[1:]),
                "benchmark": ["沪深300"] * 3 + ["中证500"] * 2,
                "close": [100, 101, 102, 200, 198],
            }
        )
        normalized = normalize_benchmark_returns(benchmarks, dates)
        self.assertTrue(np.isnan(normalized.loc[dates[0], "沪深300"]))
        self.assertAlmostEqual(normalized.loc[dates[1], "沪深300"], 0.0)
        self.assertAlmostEqual(normalized.loc[dates[2], "中证500"], -0.01)

    def test_reconstruct_positions_forward_fills_missing_close(self):
        dates = pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"])
        daily = prepare_daily_results(pd.DataFrame({"net_pnl": [0, 10, 0]}, index=dates), 10_000)
        trades = normalize_trade_records(
            [
                {"vt_symbol": "000001.SZSE", "direction": "Long", "offset": "Open", "price": 10, "volume": 100, "datetime": dates[0]},
                {"vt_symbol": "000001.SZSE", "direction": "Short", "offset": "Close", "price": 11, "volume": 100, "datetime": dates[2]},
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            year = root / "2026"
            year.mkdir()
            pd.DataFrame({"ts_code": ["000001.SZ"], "close": [10.5]}).to_parquet(year / "20260102.parquet", index=False)
            positions, metadata = reconstruct_positions(daily, trades, root)

        self.assertEqual(positions.loc[dates[0], "position_count"], 1)
        self.assertEqual(positions.loc[dates[1], "missing_price_count"], 1)
        self.assertEqual(positions.loc[dates[2], "position_count"], 0)
        self.assertEqual(metadata["missing_cache_days"], 1)
        self.assertEqual(metadata["forward_filled_price_observations"], 1)

    def test_metrics_include_trading_day_drawdown_and_cost_summaries(self):
        dates = pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"])
        daily = prepare_daily_results(
            pd.DataFrame(
                {
                    "net_pnl": [100.0, -50.0, 0.0],
                    "turnover": [1000.0, 0.0, 500.0],
                    "commission": [1.0, 0.0, 0.5],
                    "slippage": [0.2, 0.0, 0.1],
                    "trade_count": [2, 0, 1],
                },
                index=dates,
            ),
            1_000.0,
        )
        round_trips = pd.DataFrame(
            [
                {
                    "vt_symbol": "000001.SZSE",
                    "gross_pnl": 10.0,
                    "gross_return": 0.1,
                    "holding_trading_days": 1,
                    "status": "closed",
                }
            ]
        )
        metrics = calculate_metrics(daily, round_trips, 240, initial_capital=1000.0)

        self.assertEqual(metrics["max_drawdown_trading_days"], 1)
        self.assertAlmostEqual(metrics["total_cost"], 1.8)
        self.assertEqual(metrics["trading_days_with_activity"], 2)
        self.assertIn("2026", metrics["monthly_returns"])

    def test_symbol_conversion(self):
        self.assertEqual(vt_symbol_to_ts_code("000001.SZSE"), "000001.SZ")
        self.assertEqual(vt_symbol_to_ts_code("600000.SSE"), "600000.SH")
        self.assertEqual(vt_symbol_to_ts_code("920001.BSE"), "920001.BJ")


if __name__ == "__main__":
    unittest.main()
