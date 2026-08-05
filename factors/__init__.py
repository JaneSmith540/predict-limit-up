"""
因子模块

  1. 在 config.yaml 的 factors 列表里加上你的因子名
  2. 在下面 compute_factors() 里加上你的因子计算
  3. 因子值加入返回的 DataFrame 即可，模型会自动读取

因子要求: 每个因子是一列数值，和日线数据行对齐
"""
import pandas as pd
import numpy as np


def compute_factors(df: pd.DataFrame) -> pd.DataFrame:
    """
    计算所有因子

    输入: 日线数据（含 close 列）
    输出: 在原 DataFrame 上添加因子列后返回

    ============================================================
    ★ 在这里加新因子 ★
    ------------------------------------------------------------
    示例: 加一个 RSI 因子
      1. config.yaml factors 列表加 rsi
      2. 这里加: df['rsi'] = compute_rsi(df['close'], 14)
    ============================================================
    """
    # --- MA5: 5日均线 ---
    df["ma5"] = df["close"].rolling(window=5).mean()

    # --- MA10: 10日均线 ---
    df["ma10"] = df["close"].rolling(window=10).mean()

    # ★ 在这里加新因子 ★

    return df


def get_factor_columns() -> list:
    """返回当前所有因子列名（模型用这个来选择特征）"""
    return ["ma5", "ma10"]
