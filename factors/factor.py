import numpy as np


def calculate_factors(closes):

    factors = {}

    # 均线
    ma5 = np.mean(closes[-5:])
    ma10 = np.mean(closes[-10:])

    factors["ma5"] = ma5
    factors["ma10"] = ma10


    # 动量
    factors["momentum_5"] = (
        closes[-1] / closes[-6] - 1
    )

    factors["momentum_10"] = (
        closes[-1] / closes[-11] - 1
    )


    # 均线偏离
    factors["ma5_bias"] = (
        closes[-1] / ma5 - 1
    )

    factors["ma10_bias"] = (
        closes[-1] / ma10 - 1
    )


    # 波动
    factors["volatility_5"] = np.std(
        closes[-5:]
    )


    # 突破
    factors["break_high_10"] = (
        closes[-1] / max(closes[-10:]) - 1
    )


    return factors