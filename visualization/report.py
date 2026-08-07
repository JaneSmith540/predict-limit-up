"""Report orchestration for market and single-symbol backtests."""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .analysis import (
    calculate_metrics,
    normalize_trade_records,
    pair_round_trips,
    prepare_daily_results,
    reconstruct_positions,
    vt_symbol_to_ts_code,
)
from .benchmark import benchmark_metadata, load_benchmarks
from .plotting import render_report_figures


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_ROOT = PROJECT_ROOT / "reports"
CACHE_ROOT = PROJECT_ROOT / "data_cache" / "daily"
BENCHMARK_CACHE_ROOT = PROJECT_ROOT / "data_cache" / "benchmarks"


def _safe_name(value: str) -> str:
    value = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", str(value))
    return value.strip("._") or "report"


def _json_safe(value):
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    if pd.isna(value) if not isinstance(value, (dict, list, tuple)) else False:
        return None
    return value


def _write_frame(frame: pd.DataFrame, path: Path) -> None:
    output = frame.reset_index() if frame.index.name == "date" else frame.copy()
    for column in output.columns:
        if pd.api.types.is_datetime64_any_dtype(output[column]):
            output[column] = output[column].dt.strftime("%Y-%m-%d %H:%M:%S")
    output.to_csv(path, index=False, encoding="utf-8-sig")


def _engine_trade_records(engine) -> list[dict]:
    records = []
    for trade in engine.get_all_trades():
        records.append(
            {
                "vt_symbol": trade.vt_symbol,
                "direction": trade.direction.value,
                "offset": trade.offset.value,
                "price": trade.price,
                "volume": trade.volume,
                "datetime": trade.datetime,
            }
        )
    return records


def _single_trade_events(ts_code: str, trades: list[dict]) -> list[dict]:
    suffix = ts_code.split(".")[-1].upper() if "." in ts_code else "SZ"
    exchange = {"SZ": "SZSE", "SH": "SSE", "BJ": "BSE"}.get(suffix, suffix)
    vt_symbol = f"{ts_code.split('.')[0]}.{exchange}"
    events = []
    for trade in trades:
        events.append(
            {
                "vt_symbol": vt_symbol,
                "direction": "Long",
                "offset": "Open",
                "price": trade["buy_price"],
                "volume": trade["shares"],
                "datetime": trade["buy_date"],
            }
        )
        events.append(
            {
                "vt_symbol": vt_symbol,
                "direction": "Short",
                "offset": "Close",
                "price": trade["sell_price"],
                "volume": trade["shares"],
                "datetime": trade["sell_date"],
                "reason": trade.get("reason"),
            }
        )
    return events


def _price_loader_factory(daily_index: pd.DatetimeIndex):
    cache: dict[str, pd.DataFrame] = {}

    def load(symbol: str) -> pd.DataFrame:
        ts_code = vt_symbol_to_ts_code(symbol)
        rows = []
        for day in daily_index:
            path = CACHE_ROOT / day.strftime("%Y") / f"{day.strftime('%Y%m%d')}.parquet"
            if not path.exists():
                continue
            key = str(path)
            if key not in cache:
                cache[key] = pd.read_parquet(path, columns=["ts_code", "close"])
            selected = cache[key]
            selected = selected[selected["ts_code"] == ts_code]
            if not selected.empty:
                rows.append({"date": day, "close": float(selected["close"].iloc[0])})
        return pd.DataFrame(rows, columns=["date", "close"])

    return load


def _create_output_dir(mode: str, name: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    root = REPORT_ROOT / f"{stamp}_{mode}_{_safe_name(name)}"
    sequence = 1
    while root.exists():
        root = REPORT_ROOT / f"{stamp}_{mode}_{_safe_name(name)}_{sequence}"
        sequence += 1
    (root / "figures").mkdir(parents=True, exist_ok=False)
    (root / "data").mkdir(parents=True, exist_ok=False)
    return root


def _attach_position_metrics(metrics: dict, positions: pd.DataFrame) -> None:
    """Add exposure and price-imputation summaries to the report metrics."""
    if positions.empty:
        metrics["position_statistics"] = {}
        return
    metrics["position_statistics"] = {
        "average_position_count": float(positions["position_count"].mean()),
        "maximum_position_count": int(positions["position_count"].max()),
        "average_gross_exposure": float(positions["gross_exposure"].mean()),
        "maximum_gross_exposure": float(positions["gross_exposure"].max()),
        "average_net_exposure": float(positions["net_exposure"].mean()),
        "maximum_net_exposure": float(positions["net_exposure"].max()),
        "missing_price_observations": int(positions["missing_price_count"].sum()),
        "forward_filled_price_observations": int(
            positions.get("forward_filled_price_count", pd.Series(dtype=float)).sum()
        ),
        "fill_price_fallback_observations": int(
            positions.get("fill_price_fallback_count", pd.Series(dtype=float)).sum()
        ),
    }


def _truncate_to_backtest_start(
    daily: pd.DataFrame,
    trades: pd.DataFrame,
    parameters: dict | None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Exclude engine warm-up observations before the configured backtest start."""
    daily = daily.copy()
    if "date" in daily.columns:
        daily["date"] = pd.to_datetime(daily["date"])
        daily = daily.set_index("date")
    else:
        daily.index = pd.to_datetime(daily.index)
    daily.index.name = "date"
    daily = daily.sort_index()

    requested_start = (parameters or {}).get("backtest_start")
    if requested_start is None:
        return daily, trades, {
            "requested_start": None,
            "excluded_pre_start_days": 0,
            "excluded_pre_start_trades": 0,
        }

    start = pd.Timestamp(requested_start).normalize()
    daily_mask = daily.index.normalize() >= start
    filtered_daily = daily.loc[daily_mask].copy()
    if filtered_daily.empty:
        raise ValueError("backtest_start is after all daily results")
    excluded_days = int((~daily_mask).sum())
    if excluded_days and "balance" in filtered_daily:
        filtered_daily = filtered_daily.drop(columns="balance")

    filtered_trades = trades
    excluded_trades = 0
    if not trades.empty:
        trade_mask = trades["datetime"].dt.normalize() >= start
        filtered_trades = trades.loc[trade_mask].copy()
        excluded_trades = int((~trade_mask).sum())

    return filtered_daily, filtered_trades, {
        "requested_start": start.date().isoformat(),
        "excluded_pre_start_days": excluded_days,
        "excluded_pre_start_trades": excluded_trades,
    }


def _run_report(
    mode: str,
    name: str,
    daily: pd.DataFrame,
    trades: pd.DataFrame,
    capital: float,
    annual_days: int,
    engine_statistics: dict | None = None,
    parameters: dict | None = None,
) -> Path:
    report_dir = _create_output_dir(mode, name)
    daily, trades, boundary_meta = _truncate_to_backtest_start(daily, trades, parameters)
    daily = prepare_daily_results(daily, capital)
    trading_dates = daily.index
    round_trips, roundtrip_meta = pair_round_trips(trades, trading_dates)
    positions, position_meta = reconstruct_positions(daily, trades, CACHE_ROOT)
    benchmarks, benchmark_status = load_benchmarks(
        daily.index[0], daily.index[-1], BENCHMARK_CACHE_ROOT
    )
    metrics = calculate_metrics(daily, round_trips, annual_days, engine_statistics, initial_capital=capital)
    _attach_position_metrics(metrics, positions)
    metrics["benchmark_status"] = benchmark_metadata(benchmark_status)

    data_dir = report_dir / "data"
    _write_frame(daily, data_dir / "daily_results.csv")
    _write_frame(trades, data_dir / "trades.csv")
    _write_frame(round_trips, data_dir / "round_trips.csv")
    _write_frame(positions, data_dir / "positions_daily.csv")

    metadata = {
        "mode": mode,
        "name": name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "annual_days": annual_days,
        "parameters": parameters or {},
        "cache_root": str(CACHE_ROOT),
        "round_trip": roundtrip_meta,
        "positions": position_meta,
        "boundary": boundary_meta,
        "benchmarks": benchmark_metadata(benchmark_status),
        "data_range": {
            "start": str(daily.index[0].date()),
            "end": str(daily.index[-1].date()),
        },
        "trades": trades,
    }
    json_metadata = {key: value for key, value in metadata.items() if key != "trades"}
    (report_dir / "metrics.json").write_text(
        json.dumps(_json_safe(metrics), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (report_dir / "metadata.json").write_text(
        json.dumps(_json_safe(json_metadata), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    render_report_figures(
        daily=daily,
        benchmarks=benchmarks,
        round_trips=round_trips,
        positions=positions,
        metrics=metrics,
        annual_days=annual_days,
        output_dir=report_dir / "figures",
        metadata={"trades": trades},
        price_loader=_price_loader_factory(daily.index),
    )
    return report_dir


def generate_market_report(
    engine,
    statistics: dict | None = None,
    name: str = "全市场",
    parameters: dict | None = None,
) -> Path:
    """Generate a complete report from a finished vn.py market backtest."""
    if engine.daily_df is None or engine.daily_df.empty:
        raise ValueError("market engine has no daily results")
    trades = normalize_trade_records(_engine_trade_records(engine))
    size_map = getattr(engine, "sizes", {})
    daily, trades, boundary_meta = _truncate_to_backtest_start(
        engine.daily_df, trades, parameters
    )
    daily = prepare_daily_results(daily, engine.capital)
    round_trips, roundtrip_meta = pair_round_trips(trades, daily.index, size_map=size_map)
    report_dir = _create_output_dir("market", name)
    positions, position_meta = reconstruct_positions(daily, trades, CACHE_ROOT, size_map=size_map)
    benchmarks, benchmark_status = load_benchmarks(daily.index[0], daily.index[-1], BENCHMARK_CACHE_ROOT)
    metrics = calculate_metrics(
        daily,
        round_trips,
        getattr(engine, "annual_days", 240),
        statistics,
        initial_capital=engine.capital,
    )
    _attach_position_metrics(metrics, positions)
    metrics["benchmark_status"] = benchmark_metadata(benchmark_status)
    _write_frame(daily, report_dir / "data" / "daily_results.csv")
    _write_frame(trades, report_dir / "data" / "trades.csv")
    _write_frame(round_trips, report_dir / "data" / "round_trips.csv")
    _write_frame(positions, report_dir / "data" / "positions_daily.csv")
    metadata = {
        "mode": "market",
        "name": name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "annual_days": getattr(engine, "annual_days", 240),
        "parameters": parameters or {},
        "cache_root": str(CACHE_ROOT),
        "round_trip": roundtrip_meta,
        "positions": position_meta,
        "boundary": boundary_meta,
        "benchmarks": benchmark_metadata(benchmark_status),
        "data_range": {
            "start": str(daily.index[0].date()),
            "end": str(daily.index[-1].date()),
        },
    }
    (report_dir / "metrics.json").write_text(json.dumps(_json_safe(metrics), ensure_ascii=False, indent=2), encoding="utf-8")
    (report_dir / "metadata.json").write_text(json.dumps(_json_safe(metadata), ensure_ascii=False, indent=2), encoding="utf-8")
    render_report_figures(
        daily, benchmarks, round_trips, positions, metrics,
        getattr(engine, "annual_days", 240), report_dir / "figures", metadata={"trades": trades},
        price_loader=_price_loader_factory(daily.index),
    )
    return report_dir


def generate_single_report(
    ts_code: str,
    trades: list[dict],
    equity_curve: list[dict],
    initial_capital: float,
    parameters: dict | None = None,
) -> Path:
    """Generate a report from the legacy single-symbol backtest outputs."""
    if not equity_curve:
        raise ValueError("single-symbol equity curve is empty")
    equity = pd.DataFrame(equity_curve)
    equity["date"] = pd.to_datetime(equity["date"])
    equity = equity.sort_values("date").set_index("date")
    daily = pd.DataFrame(index=equity.index)
    daily["net_pnl"] = equity["equity"].diff().fillna(equity["equity"].iloc[0] - initial_capital)
    daily["total_pnl"] = daily["net_pnl"]
    daily["trade_count"] = 0
    daily["turnover"] = 0.0
    daily["commission"] = 0.0
    daily["slippage"] = 0.0
    daily["trading_pnl"] = daily["net_pnl"]
    daily["holding_pnl"] = 0.0
    daily["balance"] = equity["equity"]
    events = normalize_trade_records(_single_trade_events(ts_code, trades))
    if not events.empty:
        counts = events.groupby(events["datetime"].dt.normalize()).size()
        daily.loc[daily.index.intersection(counts.index), "trade_count"] = counts
        daily.loc[daily.index.intersection(counts.index), "turnover"] = (
            events.assign(turnover=events["price"] * events["volume"])
            .groupby(events["datetime"].dt.normalize())["turnover"]
            .sum()
        )
    return _run_report(
        mode="single",
        name=ts_code,
        daily=daily,
        trades=events,
        capital=initial_capital,
        annual_days=240,
        parameters=parameters,
    )
