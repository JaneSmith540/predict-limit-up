"""
筹码面因子 (Chip Factor)
评分维度: 筹码集中度 / 上方套牢盘比例 / 股东户数变化
权重占 NFRM 总分 15%
"""

from dataclasses import dataclass

from config.settings import config


@dataclass
class ChipInput:
    """筹码面因子输入数据"""
    concentration_90: float = 0.0       # 90%集中度 (0-1)
    trapped_ratio: float = 0.0          # 上方套牢盘比例 (0-1)
    holder_change_pct: float = 0.0     # 股东户数环比变化 (负数=集中)


class ChipFactor:
    """筹码面因子计算引擎，输出 0-100 分"""

    def __init__(self):
        self.params = config.get("nfrm.chip_factors", {})

    def calculate(self, data: ChipInput) -> int:
        scores = []

        scores.append(self._score_concentration(data.concentration_90))
        scores.append(self._score_trapped(data.trapped_ratio))
        scores.append(self._score_holder_change(data.holder_change_pct))

        return int(sum(scores) / len(scores)) if scores else 50

    def _score_concentration(self, conc: float) -> int:
        """90%集中度: >0.8 为满分"""
        mapping = self.params.get("concentration", {})
        if conc >= 0.80:
            return mapping.get("high", 100)
        elif conc >= 0.60:
            return mapping.get("medium", 70)
        else:
            return mapping.get("low", 40)

    def _score_trapped(self, ratio: float) -> int:
        """套牢盘比例: <10% 为满分"""
        mapping = self.params.get("trapped_ratio", {})
        if ratio < 0.10:
            return mapping.get("low", 100)
        elif ratio < 0.30:
            return mapping.get("medium", 60)
        else:
            return mapping.get("high", 20)

    def _score_holder_change(self, change_pct: float) -> int:
        """股东户数变化: 下降(集中)为好"""
        mapping = self.params.get("holder_change", {})
        if change_pct <= -0.05:
            return mapping.get("decreasing", 100)
        elif abs(change_pct) < 0.05:
            return mapping.get("stable", 60)
        else:
            return mapping.get("increasing", 30)
