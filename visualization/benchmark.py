"""Cached benchmark retrieval for static reports."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pandas as pd
import tushare as ts
from dotenv import load_dotenv


BENCHMARKS = {"沪深300": "000300.SH", "中证500": "000905.SH"}


def load_benchmarks(
    start_date: str,
    end_date: str,
    cache_root: Path,
    retries: int = 3,
    sleep_seconds: float = 0.2,
) -> tuple[pd.DataFrame, dict]:
    """Load benchmarks from cache, refreshing missing ranges through Tushare."""
    cache_root.mkdir(parents=True, exist_ok=True)
    start = pd.Timestamp(start_date).strftime("%Y%m%d")
    end = pd.Timestamp(end_date).strftime("%Y%m%d")
    status = {"requested": BENCHMARKS.copy(), "available": {}, "missing": [], "errors": {}}
    frames = []

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    token = os.getenv("TUSHARE_TOKEN", "")
    api = None
    if token and token != "your_token_here":
        try:
            ts.set_token(token)
            api = ts.pro_api()
        except Exception as exc:
            status["errors"]["initialization"] = str(exc)

    for label, code in BENCHMARKS.items():
        path = cache_root / f"{code}_{start}_{end}.parquet"
        frame = None
        if path.exists():
            try:
                frame = pd.read_parquet(path)
            except Exception as exc:
                status["errors"][label] = f"cache read failed: {exc}"

        if frame is None and api is not None:
            last_error = None
            for attempt in range(1, retries + 1):
                try:
                    frame = api.index_daily(ts_code=code, start_date=start, end_date=end)
                    if frame is not None and not frame.empty:
                        frame = frame.sort_values("trade_date")
                        frame.to_parquet(path, index=False, engine="pyarrow")
                    break
                except Exception as exc:
                    last_error = exc
                    if attempt < retries:
                        time.sleep(min(2**attempt, 8) + sleep_seconds)
            if frame is None or frame.empty:
                status["errors"][label] = f"download failed: {last_error}"

        if frame is None or frame.empty:
            status["missing"].append(label)
            continue

        frame = frame.copy()
        frame["date"] = pd.to_datetime(frame["trade_date"])
        frame["return"] = pd.to_numeric(frame["close"], errors="coerce").pct_change()
        frame = frame.dropna(subset=["date", "close"])[["date", "close", "return"]]
        frame["benchmark"] = label
        frames.append(frame)
        status["available"][label] = {"code": code, "rows": int(len(frame)), "path": str(path)}

    if not frames:
        return pd.DataFrame(columns=["date", "close", "return", "benchmark"]), status
    return pd.concat(frames, ignore_index=True), status


def benchmark_metadata(status: dict) -> dict:
    """Return JSON-safe benchmark status."""
    return json.loads(json.dumps(status, ensure_ascii=False, default=str))
