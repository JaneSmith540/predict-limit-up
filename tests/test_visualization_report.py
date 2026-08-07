import json
import tempfile
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from matplotlib.image import imread

from visualization.report import generate_market_report, generate_single_report
from visualization.benchmark import load_benchmarks


class VisualizationReportTests(unittest.TestCase):
    def _benchmark_frame(self):
        dates = pd.date_range("2026-01-02", periods=40, freq="B")
        rows = []
        for label, start in [("沪深300", 4000), ("中证500", 6000)]:
            for index, date in enumerate(dates):
                rows.append({"date": date, "close": start + index, "return": 0.0, "benchmark": label})
        return pd.DataFrame(rows)

    def test_single_report_generates_static_bundle_with_exit_reason(self):
        dates = pd.date_range("2026-01-02", periods=40, freq="B")
        equity_curve = [
            {"date": date.strftime("%Y%m%d"), "equity": 1_000_000 + index * 500}
            for index, date in enumerate(dates)
        ]
        trades = [
            {
                "buy_date": dates[3].strftime("%Y%m%d"),
                "sell_date": dates[8].strftime("%Y%m%d"),
                "buy_price": 10.0,
                "sell_price": 11.0,
                "shares": 1000,
                "pnl": 0.1,
                "reason": "持仓到期(5天)",
            }
        ]
        benchmark_status = {"requested": {}, "available": {}, "missing": [], "errors": {}}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reports = root / "reports"
            cache = root / "daily"
            for date in dates:
                year = cache / date.strftime("%Y")
                year.mkdir(parents=True, exist_ok=True)
                pd.DataFrame({"ts_code": ["000025.SZ"], "close": [10.0]}).to_parquet(
                    year / f"{date.strftime('%Y%m%d')}.parquet", index=False
                )

            with (
                patch("visualization.report.REPORT_ROOT", reports),
                patch("visualization.report.CACHE_ROOT", cache),
                patch("visualization.report.load_benchmarks", return_value=(self._benchmark_frame(), benchmark_status)),
            ):
                report_dir = generate_single_report("000025.SZ", trades, equity_curve, 1_000_000)

            self.assertTrue((report_dir / "backtest_report.pdf").exists())
            self.assertTrue((report_dir / "figures" / "01_overview.png").exists())
            self.assertTrue((report_dir / "figures" / "05b_exit_reasons.png").exists())
            self.assertTrue((report_dir / "data" / "daily_results.csv").exists())
            self.assertTrue((report_dir / "data" / "trades.csv").exists())
            self.assertTrue((report_dir / "data" / "round_trips.csv").exists())
            self.assertTrue((report_dir / "data" / "positions_daily.csv").exists())
            for figure_path in (report_dir / "figures").glob("*.png"):
                image = imread(figure_path)
                self.assertEqual(image.shape[1], 2160)
                self.assertEqual(image.shape[0], 1260)
            metrics = json.loads((report_dir / "metrics.json").read_text(encoding="utf-8"))
            self.assertEqual(metrics["closed_round_trips"], 1)
            self.assertEqual(metrics["win_rate"], 1.0)

    def test_no_trade_report_still_renders(self):
        dates = pd.date_range("2026-01-02", periods=10, freq="B")
        equity_curve = [{"date": d.strftime("%Y%m%d"), "equity": 1_000_000} for d in dates]
        benchmark_status = {"requested": {}, "available": {}, "missing": ["沪深300", "中证500"], "errors": {}}
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch("visualization.report.REPORT_ROOT", Path(tmp) / "reports"),
                patch("visualization.report.CACHE_ROOT", Path(tmp) / "daily"),
                patch("visualization.report.load_benchmarks", return_value=(pd.DataFrame(), benchmark_status)),
            ):
                report_dir = generate_single_report("000001.SZ", [], equity_curve, 1_000_000)
            self.assertTrue((report_dir / "backtest_report.pdf").exists())
            self.assertGreaterEqual(len(list((report_dir / "figures").glob("*.png"))), 7)

    def test_benchmark_cache_survives_api_initialization_failure(self):
        dates = pd.date_range("2026-01-02", periods=3, freq="B")
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            for code, start in [("000300.SH", 4000), ("000905.SH", 6000)]:
                pd.DataFrame(
                    {
                        "trade_date": dates.strftime("%Y%m%d"),
                        "close": [start, start + 1, start + 2],
                    }
                ).to_parquet(cache / f"{code}_20260102_20260106.parquet", index=False)
            with patch("visualization.benchmark.ts.pro_api", side_effect=RuntimeError("offline")):
                frame, status = load_benchmarks(dates[0], dates[-1], cache)
            self.assertEqual(set(status["available"]), {"沪深300", "中证500"})
            self.assertEqual(len(frame), 6)

    def test_benchmark_missing_is_explicit_when_cache_and_api_are_unavailable(self):
        dates = pd.date_range("2026-01-02", periods=3, freq="B")
        with tempfile.TemporaryDirectory() as tmp:
            with patch("visualization.benchmark.ts.pro_api", side_effect=RuntimeError("offline")):
                frame, status = load_benchmarks(dates[0], dates[-1], Path(tmp))
            self.assertTrue(frame.empty)
            self.assertEqual(set(status["missing"]), {"沪深300", "中证500"})
            self.assertIn("initialization", status["errors"])

    def test_market_engine_report_without_exit_reasons(self):
        dates = pd.date_range("2026-01-02", periods=40, freq="B")
        daily = pd.DataFrame(
            {
                "net_pnl": [0.0] * 40,
                "trade_count": [0, 0, 2, 0, 0, 2] + [0] * 34,
                "turnover": [0.0, 0.0, 20_000.0, 0.0, 0.0, 20_000.0] + [0.0] * 34,
            },
            index=dates,
        )
        class _Trade:
            def __init__(self, symbol, direction, offset, price, volume, when):
                self.vt_symbol = symbol
                self.direction = SimpleNamespace(value=direction)
                self.offset = SimpleNamespace(value=offset)
                self.price = price
                self.volume = volume
                self.datetime = when

        engine = SimpleNamespace(
            daily_df=daily,
            capital=1_000_000.0,
            annual_days=240,
            sizes={"000025.SZSE": 1.0},
            get_all_trades=lambda: [
                _Trade("000025.SZSE", "Long", "Open", 10.0, 1000, dates[2]),
                _Trade("000025.SZSE", "Short", "Close", 10.5, 1000, dates[5]),
            ],
        )
        status = {"requested": {}, "available": {}, "missing": [], "errors": {}}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "daily"
            for date in dates:
                year = cache / date.strftime("%Y")
                year.mkdir(parents=True, exist_ok=True)
                pd.DataFrame({"ts_code": ["000025.SZ"], "close": [10.2]}).to_parquet(
                    year / f"{date.strftime('%Y%m%d')}.parquet", index=False
                )
            with (
                patch("visualization.report.REPORT_ROOT", root / "reports"),
                patch("visualization.report.CACHE_ROOT", cache),
                patch("visualization.report.load_benchmarks", return_value=(self._benchmark_frame(), status)),
            ):
                report_dir = generate_market_report(
                    engine,
                    statistics={"start_date": dates[0].date()},
                    name="夹具市场",
                )
            self.assertTrue((report_dir / "backtest_report.pdf").exists())
            self.assertTrue((report_dir / "figures" / "08_timeline_01_000025.SZSE.png").exists())
            self.assertFalse((report_dir / "figures" / "05b_exit_reasons.png").exists())
            metrics = json.loads((report_dir / "metrics.json").read_text(encoding="utf-8"))
            self.assertEqual(metrics["closed_round_trips"], 1)
            self.assertEqual(metrics["engine_statistics"]["start_date"], "2026-01-02")

    def test_market_report_excludes_warmup_days_before_backtest_start(self):
        dates = pd.to_datetime(["2025-07-31", "2025-08-01", "2025-08-04"])
        daily = pd.DataFrame(
            {
                "net_pnl": [999.0, 10.0, -5.0],
                "trade_count": [2, 2, 0],
                "turnover": [1000.0, 2000.0, 0.0],
                "balance": [1_000_999.0, 1_001_009.0, 1_001_004.0],
            },
            index=dates,
        )

        class _Trade:
            def __init__(self, when):
                self.vt_symbol = "000025.SZSE"
                self.direction = SimpleNamespace(value="Long")
                self.offset = SimpleNamespace(value="Open")
                self.price = 10.0
                self.volume = 100
                self.datetime = when

        engine = SimpleNamespace(
            daily_df=daily,
            capital=1_000_000.0,
            annual_days=240,
            sizes={"000025.SZSE": 1.0},
            get_all_trades=lambda: [_Trade(dates[0]), _Trade(dates[1])],
        )
        status = {"requested": {}, "available": {}, "missing": ["沪深300", "中证500"], "errors": {}}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                patch("visualization.report.REPORT_ROOT", root / "reports"),
                patch("visualization.report.CACHE_ROOT", root / "daily"),
                patch("visualization.report.load_benchmarks", return_value=(pd.DataFrame(), status)),
            ):
                report_dir = generate_market_report(
                    engine,
                    name="边界市场",
                    parameters={"backtest_start": "20250801"},
                )

            daily_output = pd.read_csv(report_dir / "data" / "daily_results.csv")
            trades_output = pd.read_csv(report_dir / "data" / "trades.csv")
            metadata = json.loads((report_dir / "metadata.json").read_text(encoding="utf-8"))
            metrics = json.loads((report_dir / "metrics.json").read_text(encoding="utf-8"))

        self.assertEqual(daily_output["date"].iloc[0][:10], "2025-08-01")
        self.assertEqual(len(daily_output), 2)
        self.assertEqual(len(trades_output), 1)
        self.assertEqual(metrics["end_balance"], 1_000_005.0)
        self.assertEqual(metadata["boundary"]["excluded_pre_start_days"], 1)
        self.assertEqual(metadata["boundary"]["excluded_pre_start_trades"], 1)


if __name__ == "__main__":
    unittest.main()
