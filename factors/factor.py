"""
因子计算（策略端）

所有因子均为无量纲/归一化指标，跨股票可比。
输入: 收盘价序列（不含当日，即 t-1 及更早）
"""
import numpy as np


def calculate_rsi(closes: np.ndarray, period: int = 14) -> float:
    """计算 RSI 指标

    输入收盘价序列（最近 period+1 根），返回 RSI(0~100)。
    """
    if len(closes) < period + 1:
        return np.nan

    deltas = np.diff(closes[-(period + 1):])
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = np.mean(gains)
    avg_loss = np.mean(losses)

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def calculate_factors(closes):
    """从收盘价序列计算全部因子

    参数:
        closes: list/np.array，t-1 及更早的收盘价（不含当日）

    返回:
        dict，因子名 -> 因子值（均为无量纲，跨股票可比）

    因子清单:
        momentum_5     5日动量收益率
        momentum_10    10日动量收益率
        ma5_bias       收盘价相对MA5偏离度
        ma10_bias      收盘价相对MA10偏离度
        volatility_5   5日变异系数（波动率/均值）
        break_high_10  相对10日新高突破比率（≤0）
        rsi_14         14日RSI
    """
    closes = np.array(closes, dtype=float)
    n = len(closes)
    factors = {}

    if n < 5:
        return factors

    last_close = closes[-1]

    # --- 动量 ---
    if n >= 6:
        factors["momentum_5"] = float(last_close / closes[-6] - 1.0)
    if n >= 11:
        factors["momentum_10"] = float(last_close / closes[-11] - 1.0)

    # --- 均线偏离 ---
    ma5 = float(np.mean(closes[-5:]))
    factors["ma5_bias"] = float(last_close / ma5 - 1.0)

    if n >= 10:
        ma10 = float(np.mean(closes[-10:]))
        factors["ma10_bias"] = float(last_close / ma10 - 1.0)

    # --- 波动率（变异系数，无量纲）---
    window5 = closes[-5:]
    mean5 = float(np.mean(window5))
    if mean5 > 0:
        factors["volatility_5"] = float(np.std(window5) / mean5)

    # --- 突破比率 ---
    if n >= 10:
        high10 = float(np.max(closes[-10:]))
        if high10 > 0:
            factors["break_high_10"] = float(last_close / high10 - 1.0)

    # --- RSI ---
    factors["rsi_14"] = float(calculate_rsi(closes, 14))

    return factors
