"""
技术面因子 (Technical Factor)
评分维度: 量价配合 / 均线系统 / MACD信号 / K线形态
权重占 NFRM 总分 20%
"""

from dataclasses import dataclass

from config.settings import config


@dataclass
class TechnicalInput:
    """技术面因子输入数据"""
    volume_ratio: float = 1.0           # 量比
    daily_gain: float = 0.0             # 当日涨幅
    ma_alignment: str = "partial"       # 均线排列: 多头/partial/bearish
    macd_signal: str = "above_zero"    # MACD: golden_cross/above_zero/below_zero
    pattern: str = "none"              # K线形态: breakout/flag/none


class TechnicalFactor:
    """技术面因子计算引擎，输出 0-100 分"""

    def __init__(self):
        self.params = config.get("nfrm.technical_factors", {})

    def calculate(self, data: TechnicalInput) -> int:
        scores = []

        scores.append(self._score_volume_price(data.volume_ratio, data.daily_gain))
        scores.append(self._score_ma(data.ma_alignment))
        scores.append(self._score_macd(data.macd_signal))
        scores.append(self._score_pattern(data.pattern))

        return int(sum(scores) / len(scores)) if scores else 50

    def _score_volume_price(self, vol_ratio: float, gain: float) -> int:
        mapping = self.params.get("volume_price", {})
        if vol_ratio >= 2.0 and gain >= 0.09:
            return mapping.get("perfect_resonance", 100)
        elif vol_ratio >= 1.5 and gain >= 0.05:
            return mapping.get("strong", 80)
        elif vol_ratio >= 1.0:
            return mapping.get("medium", 60)
        else:
            return mapping.get("weak", 30)

    def _score_ma(self, alignment: str) -> int:
        mapping = self.params.get("ma_system", {})
        # 处理中文键名 "多头排列"
        if alignment in ("多头", "bull", "perfect"):
            return mapping.get("多头排列", 100)
        return mapping.get(alignment, 50)

    def _score_macd(self, signal: str) -> int:
        mapping = self.params.get("macd_signal", {})
        return mapping.get(signal, 50)

    def _score_pattern(self, pattern: str) -> int:
        mapping = self.params.get("pattern", {})
        return mapping.get(pattern, 50)
