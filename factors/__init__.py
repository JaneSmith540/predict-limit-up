"""
因子模块

  1. 在 config.yaml 的 factors 列表里加上你的因子名
  2. 在下面 compute_factors() 里加上你的因子计算
  3. 因子值加入返回的 DataFrame 即可，模型会自动读取

因子要求: 每个因子是一列数值，和日线数据行对齐
"""
import pandas as pd
import numpy as np
from .factor import calculate_factors

def compute_factors(df: pd.DataFrame) -> pd.DataFrame:
    """
    计算所有因子

    输入: 日线数据（含 close, ts_code, trade_date 列）
    输出: 在原 DataFrame 上添加因子列后返回

    所有 rolling 因子后接 .shift(1)，确保因子只使用 t-1 及更早数据，
    不偷看当日收盘。多股票时按 ts_code 分组 rolling。

    ============================================================
    ★ 在这里加新因子 ★
    ------------------------------------------------------------
    示例: 加一个 RSI 因子
      1. config.yaml factors 列表加 rsi
      2. 这里加: df['rsi'] = df.groupby('ts_code')['close'].transform(lambda s: compute_rsi(s, 14).shift(1))
    ============================================================
    """
    if "ts_code" in df.columns:
        df = df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
        grp = df.groupby("ts_code")["close"]
        df["ma5"] = grp.transform(lambda s: s.rolling(window=5).mean().shift(1))
        df["ma10"] = grp.transform(lambda s: s.rolling(window=10).mean().shift(1))
    else:
        df["ma5"] = df["close"].rolling(window=5).mean().shift(1)
        df["ma10"] = df["close"].rolling(window=10).mean().shift(1)

    # ★ 在这里加新因子 ★

    return df


def get_factor_columns() -> list:
    """返回当前所有因子列名（模型用这个来选择特征）"""
    return ["ma5", "ma10"]
