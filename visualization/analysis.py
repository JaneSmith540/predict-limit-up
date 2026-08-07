"""Normalize backtest outputs and calculate visualization-layer diagnostics."""

from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


DAILY_COLUMNS = [
    "trade_count",
    "turnover",
    "commission",
    "slippage",
    "trading_pnl",
    "holding_pnl",
    "total_pnl",
    "net_pnl",
]


def vt_symbol_to_ts_code(vt_symbol: str) -> str:
    """Convert vn.py symbols to the Tushare symbol convention."""
    if "." not in vt_symbol:
        return vt_symbol
    code, suffix = vt_symbol.rsplit(".", 1)
    mapping = {"SZSE": "SZ", "SSE": "SH", "BSE": "BJ"}
    return f"{code}.{mapping.get(suffix.upper(), suffix.upper())}"


def prepare_daily_results(df: pd.DataFrame, capital: float) -> pd.DataFrame:
    """Return a stable daily-result schema for charts and exported artifacts."""
    if df is None or len(df) == 0:
        raise ValueError("daily results are empty")
    if not np.isfinite(float(capital)) or float(capital) <= 0:
        raise ValueError("initial capital must be a positive finite number")

    daily = df.copy()
    if "date" in daily.columns:
        daily["date"] = pd.to_datetime(daily["date"])
        daily = daily.set_index("date")
    else:
        daily.index = pd.to_datetime(daily.index)
    daily.index.name = "date"
    daily = daily.sort_index()
    if daily.index.has_duplicates:
        raise ValueError("daily results contain duplicate dates")

    for column in DAILY_COLUMNS:
        if column not in daily:
            daily[column] = 0.0
        daily[column] = pd.to_numeric(daily[column], errors="coerce").fillna(0.0)

    if "balance" not in daily:
        daily["balance"] = daily["net_pnl"].cumsum() + float(capital)
    daily["balance"] = pd.to_numeric(daily["balance"], errors="coerce")
    if not np.isfinite(daily["balance"]).all():
        raise ValueError("daily balance contains non-finite values")

    # Measure the first observation against initial capital so daily returns
    # compound back to the ending balance even when day one has PnL.
    daily["daily_return"] = daily["balance"].pct_change()
    daily.iloc[0, daily.columns.get_loc("daily_return")] = (
        daily["balance"].iloc[0] / float(capital) - 1.0
    )
    daily["daily_return"] = daily["daily_return"].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    daily["log_return"] = np.log(
        daily["balance"] / daily["balance"].shift(1)
    ).replace([np.inf, -np.inf], np.nan)
    daily.iloc[0, daily.columns.get_loc("log_return")] = (
        np.log(daily["balance"].iloc[0] / float(capital))
        if daily["balance"].iloc[0] > 0
        else np.nan
    )
    daily["log_return"] = daily["log_return"].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    # Initial capital is the pre-period high-water mark for drawdown purposes.
    daily["high_watermark"] = daily["balance"].cummax().clip(lower=float(capital))
    daily["drawdown_amount"] = daily["balance"] - daily["high_watermark"]
    daily["drawdown"] = daily["balance"] / daily["high_watermark"] - 1.0
    return daily[
        DAILY_COLUMNS
        + [
            "balance",
            "daily_return",
            "log_return",
            "high_watermark",
            "drawdown_amount",
            "drawdown",
        ]
    ]


def normalize_trade_records(records: Iterable[dict]) -> pd.DataFrame:
    """Normalize raw fill records while preserving their original values."""
    trades = pd.DataFrame(list(records))
    columns = [
        "vt_symbol",
        "direction",
        "offset",
        "price",
        "volume",
        "datetime",
        "reason",
    ]
    for column in columns:
        if column not in trades:
            trades[column] = pd.NA
    if trades.empty:
        return trades[columns]

    trades["datetime"] = pd.to_datetime(trades["datetime"])
    trades["price"] = pd.to_numeric(trades["price"], errors="coerce")
    trades["volume"] = pd.to_numeric(trades["volume"], errors="coerce")
    return trades[columns].sort_values("datetime").reset_index(drop=True)


def _is_open_trade(row: pd.Series) -> bool:
    direction = str(row["direction"]).strip().lower()
    offset = str(row["offset"]).strip().lower()
    return direction in {"long", "多", "buy"} and offset in {"open", "开", "开仓"}


def _is_close_trade(row: pd.Series) -> bool:
    direction = str(row["direction"]).strip().lower()
    offset = str(row["offset"]).strip().lower()
    return direction in {"short", "空", "sell"} and offset in {
        "close",
        "平",
        "平仓",
        "closetoday",
        "closeyesterday",
    }


def pair_round_trips(
    trades: pd.DataFrame,
    trading_dates: Iterable,
    size_map: dict[str, float] | None = None,
) -> tuple[pd.DataFrame, dict]:
    """FIFO-match long opens and closes, including partial fills."""
    columns = [
        "vt_symbol",
        "entry_datetime",
        "exit_datetime",
        "entry_price",
        "exit_price",
        "volume",
        "holding_calendar_days",
        "holding_trading_days",
        "gross_return",
        "gross_pnl",
        "reason",
        "status",
    ]
    if trades.empty:
        return pd.DataFrame(columns=columns), {
            "unmatched_open_lots": 0,
            "unmatched_close_volume": 0.0,
        }

    dates = pd.DatetimeIndex(pd.to_datetime(list(trading_dates))).normalize().unique().sort_values()
    sizes = size_map or {}
    queues: dict[str, deque] = defaultdict(deque)
    rows: list[dict] = []
    unmatched_close_volume = 0.0

    for _, trade in trades.sort_values("datetime").iterrows():
        symbol = str(trade["vt_symbol"])
        volume = float(trade["volume"])
        if not np.isfinite(volume) or volume <= 0:
            continue
        if _is_open_trade(trade):
            queues[symbol].append(
                {
                    "datetime": pd.Timestamp(trade["datetime"]),
                    "price": float(trade["price"]),
                    "remaining": volume,
                }
            )
            continue
        if not _is_close_trade(trade):
            continue

        remaining = volume
        while remaining > 0 and queues[symbol]:
            lot = queues[symbol][0]
            matched = min(remaining, lot["remaining"])
            entry_dt = pd.Timestamp(lot["datetime"])
            exit_dt = pd.Timestamp(trade["datetime"])
            entry_day = entry_dt.normalize()
            exit_day = exit_dt.normalize()
            entry_pos = int(dates.searchsorted(entry_day, side="left"))
            exit_pos = int(dates.searchsorted(exit_day, side="left"))
            holding_trading_days = max(exit_pos - entry_pos, 0)
            size = float(sizes.get(symbol, 1.0))
            entry_price = float(lot["price"])
            exit_price = float(trade["price"])
            rows.append(
                {
                    "vt_symbol": symbol,
                    "entry_datetime": entry_dt,
                    "exit_datetime": exit_dt,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "volume": matched,
                    "holding_calendar_days": max((exit_day - entry_day).days, 0),
                    "holding_trading_days": holding_trading_days,
                    "gross_return": exit_price / entry_price - 1.0,
                    "gross_pnl": (exit_price - entry_price) * matched * size,
                    "reason": trade.get("reason", pd.NA),
                    "status": "closed",
                }
            )
            remaining -= matched
            lot["remaining"] -= matched
            if lot["remaining"] <= 1e-12:
                queues[symbol].popleft()
        unmatched_close_volume += remaining

    for symbol, queue in queues.items():
        for lot in queue:
            rows.append(
                {
                    "vt_symbol": symbol,
                    "entry_datetime": lot["datetime"],
                    "exit_datetime": pd.NaT,
                    "entry_price": lot["price"],
                    "exit_price": np.nan,
                    "volume": lot["remaining"],
                    "holding_calendar_days": np.nan,
                    "holding_trading_days": np.nan,
                    "gross_return": np.nan,
                    "gross_pnl": np.nan,
                    "reason": pd.NA,
                    "status": "open_at_end",
                }
            )

    result = pd.DataFrame(rows, columns=columns)
    metadata = {
        "unmatched_open_lots": int((result["status"] == "open_at_end").sum()),
        "unmatched_close_volume": float(unmatched_close_volume),
    }
    return result, metadata


def reconstruct_positions(
    daily: pd.DataFrame,
    trades: pd.DataFrame,
    cache_root: Path,
    size_map: dict[str, float] | None = None,
) -> tuple[pd.DataFrame, dict]:
    """Rebuild end-of-day positions and exposure from fills and cached closes."""
    sizes = size_map or {}
    positions: dict[str, float] = defaultdict(float)
    last_prices: dict[str, float] = {}
    fill_prices: dict[str, float] = {}
    rows: list[dict] = []
    missing_price_observations = 0
    forward_filled_price_observations = 0
    fill_price_fallback_observations = 0
    missing_cache_days = 0

    fills = trades.copy()
    if not fills.empty:
        fills["date"] = fills["datetime"].dt.normalize()
    for date, daily_row in daily.iterrows():
        day = pd.Timestamp(date).normalize()
        if not fills.empty:
            day_fills = fills[fills["date"] == day]
            for _, trade in day_fills.iterrows():
                symbol = str(trade["vt_symbol"])
                volume = float(trade["volume"])
                if _is_open_trade(trade):
                    positions[symbol] += volume
                elif _is_close_trade(trade):
                    positions[symbol] -= volume
                    if abs(positions[symbol]) <= 1e-12:
                        positions.pop(symbol, None)
                fill_prices[symbol] = float(trade["price"])

        active = [symbol for symbol, volume in positions.items() if abs(volume) > 1e-12]
        cache_path = cache_root / day.strftime("%Y") / f"{day.strftime('%Y%m%d')}.parquet"
        close_map: dict[str, float] = {}
        if active and cache_path.exists():
            price_df = pd.read_parquet(cache_path, columns=["ts_code", "close"])
            wanted = {vt_symbol_to_ts_code(symbol) for symbol in active}
            selected = price_df[price_df["ts_code"].isin(wanted)]
            close_map = dict(zip(selected["ts_code"], selected["close"]))
        elif active:
            missing_cache_days += 1

        gross_value = 0.0
        net_value = 0.0
        imputed_today = 0
        forward_filled_today = 0
        fill_price_fallback_today = 0
        for symbol in active:
            ts_code = vt_symbol_to_ts_code(symbol)
            price = close_map.get(ts_code)
            if price is not None and np.isfinite(price):
                last_prices[symbol] = float(price)
            else:
                if symbol in last_prices:
                    price = last_prices[symbol]
                    forward_filled_today += 1
                else:
                    price = fill_prices.get(symbol)
                    if price is not None:
                        fill_price_fallback_today += 1
                imputed_today += 1
            if price is None or not np.isfinite(price):
                continue
            value = positions[symbol] * float(price) * float(sizes.get(symbol, 1.0))
            gross_value += abs(value)
            net_value += value

        missing_price_observations += imputed_today
        forward_filled_price_observations += forward_filled_today
        fill_price_fallback_observations += fill_price_fallback_today
        balance = float(daily_row["balance"])
        rows.append(
            {
                "date": day,
                "position_count": len(active),
                "gross_market_value": gross_value,
                "net_market_value": net_value,
                "gross_exposure": gross_value / balance if balance else np.nan,
                "net_exposure": net_value / balance if balance else np.nan,
                "cash_proxy": balance - net_value,
                "turnover": float(daily_row.get("turnover", 0.0)),
                "turnover_rate": (
                    float(daily_row.get("turnover", 0.0)) / abs(balance)
                    if balance
                    else np.nan
                ),
                "missing_price_count": imputed_today,
                "forward_filled_price_count": forward_filled_today,
                "fill_price_fallback_count": fill_price_fallback_today,
            }
        )

    result = pd.DataFrame(rows).set_index("date")
    metadata = {
        "missing_price_observations": int(missing_price_observations),
        "forward_filled_price_observations": int(forward_filled_price_observations),
        "fill_price_fallback_observations": int(fill_price_fallback_observations),
        "missing_cache_days": int(missing_cache_days),
    }
    return result, metadata


def monthly_returns(daily: pd.DataFrame) -> pd.DataFrame:
    """Compound daily returns into a year-by-month table with annual returns."""
    version_parts = tuple(int(part) for part in pd.__version__.split(".")[:2])
    month_frequency = "ME" if version_parts >= (2, 2) else "M"
    monthly = (1.0 + daily["daily_return"]).resample(month_frequency).prod() - 1.0
    frame = monthly.to_frame("return")
    frame["year"] = frame.index.year
    frame["month"] = frame.index.month
    pivot = frame.pivot(index="year", columns="month", values="return")
    pivot = pivot.reindex(columns=range(1, 13))
    annual = (1.0 + frame["return"]).groupby(frame["year"]).prod() - 1.0
    pivot["annual"] = annual
    return pivot


def rolling_metrics(daily: pd.DataFrame, annual_days: int) -> pd.DataFrame:
    """Calculate the fixed-window rolling risk series used by the report."""
    returns = daily["daily_return"]
    result = pd.DataFrame(index=daily.index)
    result["volatility_20d"] = returns.rolling(20, min_periods=10).std() * np.sqrt(annual_days)
    mean_60 = returns.rolling(60, min_periods=30).mean()
    std_60 = returns.rolling(60, min_periods=30).std()
    result["sharpe_60d"] = mean_60 / std_60.replace(0, np.nan) * np.sqrt(annual_days)
    result["return_60d"] = (1.0 + returns).rolling(60, min_periods=30).apply(np.prod, raw=True) - 1.0
    return result


def normalize_benchmark_returns(
    benchmarks: pd.DataFrame, trading_dates: Iterable
) -> pd.DataFrame:
    """Align benchmark closes and normalize all available series at a common date."""
    dates = pd.DatetimeIndex(pd.to_datetime(list(trading_dates))).sort_values()
    if benchmarks.empty:
        return pd.DataFrame(index=dates)
    frame = benchmarks.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    pivot = frame.pivot_table(index="date", columns="benchmark", values="close", aggfunc="last")
    pivot = pivot.reindex(dates).ffill()
    common = pivot.dropna(how="any")
    if common.empty:
        return pd.DataFrame(index=dates, columns=pivot.columns, dtype=float)
    start = common.index[0]
    normalized = pivot.divide(pivot.loc[start]).subtract(1.0)
    normalized.loc[normalized.index < start] = np.nan
    return normalized


def calculate_metrics(
    daily: pd.DataFrame,
    round_trips: pd.DataFrame,
    annual_days: int,
    engine_statistics: dict | None = None,
    initial_capital: float | None = None,
) -> dict:
    """Calculate serializable headline metrics for the static report."""
    returns = daily["daily_return"]
    start_balance = float(initial_capital) if initial_capital is not None else float(daily["balance"].iloc[0])
    total_return = float(daily["balance"].iloc[-1] / start_balance - 1.0)
    periods = max(len(daily), 1)
    annual_return = (
        float((1.0 + total_return) ** (annual_days / periods) - 1.0)
        if total_return > -1.0
        else -1.0
    )
    annual_volatility = float(returns.std() * np.sqrt(annual_days))
    sharpe = (
        float(returns.mean() / returns.std() * np.sqrt(annual_days))
        if returns.std() and np.isfinite(returns.std())
        else 0.0
    )
    dd_end = daily["drawdown"].idxmin()
    balances_to_trough = daily.loc[:dd_end, "balance"]
    dd_start = (
        daily.index[0]
        if float(balances_to_trough.max()) < start_balance
        else balances_to_trough.idxmax()
    )
    dd_window = daily.loc[dd_start:dd_end]

    closed = round_trips[round_trips["status"] == "closed"].copy()
    wins = closed[closed["gross_pnl"] > 0]
    losses = closed[closed["gross_pnl"] <= 0]
    gross_profit = float(wins["gross_pnl"].sum()) if not wins.empty else 0.0
    gross_loss = float(losses["gross_pnl"].sum()) if not losses.empty else 0.0

    monthly = monthly_returns(daily)
    return {
        "start_date": str(daily.index[0].date()),
        "end_date": str(daily.index[-1].date()),
        "trading_days": int(len(daily)),
        "start_balance": start_balance,
        "end_balance": float(daily["balance"].iloc[-1]),
        "total_return": total_return,
        "annual_return": annual_return,
        "annual_volatility": annual_volatility,
        "sharpe_ratio": sharpe,
        "max_drawdown": float(daily["drawdown"].min()),
        "max_drawdown_start": str(dd_start.date()),
        "max_drawdown_end": str(dd_end.date()),
        "max_drawdown_calendar_days": int((dd_end - dd_start).days),
        "max_drawdown_trading_days": int(max(len(dd_window) - 1, 0)),
        "total_trade_events": int(daily["trade_count"].sum()),
        "closed_round_trips": int(len(closed)),
        "win_rate": float((closed["gross_pnl"] > 0).mean()) if len(closed) else None,
        "average_trade_return": float(closed["gross_return"].mean()) if len(closed) else None,
        "median_trade_return": float(closed["gross_return"].median()) if len(closed) else None,
        "profit_factor": gross_profit / abs(gross_loss) if gross_loss else None,
        "average_holding_trading_days": float(closed["holding_trading_days"].mean()) if len(closed) else None,
        "total_turnover": float(daily["turnover"].sum()),
        "total_commission": float(daily["commission"].sum()),
        "total_slippage": float(daily["slippage"].sum()),
        "total_cost": float(daily["commission"].sum() + daily["slippage"].sum()),
        "trading_days_with_activity": int((daily["trade_count"] > 0).sum()),
        "average_daily_turnover_rate": float(
            (daily["turnover"] / daily["balance"].abs().replace(0, np.nan)).mean()
        ),
        "monthly_returns": {
            str(year): {
                ("annual" if column == "annual" else f"{int(column):02d}"): (
                    float(value) if pd.notna(value) else None
                )
                for column, value in row.items()
            }
            for year, row in monthly.iterrows()
        },
        "stock_gross_pnl_contribution": {
            str(symbol): float(value)
            for symbol, value in closed.groupby("vt_symbol")["gross_pnl"]
            .sum()
            .sort_values(ascending=False)
            .items()
        },
        "engine_statistics": engine_statistics or {},
    }
