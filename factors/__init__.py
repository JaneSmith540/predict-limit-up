"""
因子模块

  1. 在 config.yaml 的 factors 列表里加上你的因子名
  2. 在下面 compute_factors() 里加上你的因子计算
  3. 因子值加入返回的 DataFrame 即可，模型会自动读取

因子要求: 每个因子是一列数值，和日线数据行对齐
所有因子均为无量纲指标，跨股票可比。
"""
import pandas as pd
import numpy as np
from .factor import calculate_factors

# 全部因子列名（与 calculate_factors 返回的 key 保持一致）
FACTOR_COLUMNS = [
    "momentum_5",
    "momentum_10",
    "ma5_bias",
    "ma10_bias",
    "volatility_5",
    "break_high_10",
    "rsi_14",
]


def compute_factors(df: pd.DataFrame) -> pd.DataFrame:
    """
    计算所有因子（训练端）

    输入: 日线数据（含 close, ts_code, trade_date 列）
    输出: 在原 DataFrame 上添加因子列后返回

    所有因子基于 close_prev = close.shift(1) 计算，
    即只用 t-1 及更早数据，无未来信息泄漏。
    """
    if "ts_code" in df.columns:
        df = df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
        grp = df.groupby("ts_code")["close"]
    else:
        grp = df["close"]

    # 用 t-1 收盘价作为基准，确保因子不含当日信息
    close_prev = grp.transform(lambda s: s.shift(1))

    # --- 动量 ---
    df["momentum_5"] = close_prev / close_prev.shift(5) - 1.0
    df["momentum_10"] = close_prev / close_prev.shift(10) - 1.0

    # --- 均线偏离 ---
    ma5 = close_prev.rolling(window=5).mean()
    ma10 = close_prev.rolling(window=10).mean()
    df["ma5_bias"] = close_prev / ma5 - 1.0
    df["ma10_bias"] = close_prev / ma10 - 1.0

    # --- 波动率（变异系数）---
    vol5_mean = close_prev.rolling(window=5).mean()
    vol5_std = close_prev.rolling(window=5).std()
    df["volatility_5"] = vol5_std / vol5_mean

    # --- 突破比率 ---
    high10 = close_prev.rolling(window=10).max()
    df["break_high_10"] = close_prev / high10 - 1.0

    # --- RSI 14 ---
    delta = close_prev.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.rolling(window=14).mean()
    avg_loss = loss.rolling(window=14).mean()
    rs = avg_gain / avg_loss
    df["rsi_14"] = 100.0 - 100.0 / (1.0 + rs)

    return df


def get_factor_columns() -> list:
    """返回当前所有因子列名（模型用这个来选择特征）"""
    return FACTOR_COLUMNS.copy()
