"""
资金面因子 (Capital Factor)
评分维度: 主力净流入 / 北向资金 / 大单占比 / 封单强度
权重占 NFRM 总分 25%
"""

from dataclasses import dataclass

from config.settings import config


@dataclass
class CapitalInput:
    """资金面因子输入数据"""
    main_net_inflow_rank: str = "medium"    # 主力净流入排名等级
    north_fund_net: float = 0.0            # 北向资金净买入额（亿元）
    large_order_ratio: float = 0.0          # 大单成交占比
    seal_fund_amount: float = 0.0           # 封单金额（元）


class CapitalFactor:
    """资金面因子计算引擎，输出 0-100 分"""

    def __init__(self):
        self.params = config.get("nfrm.capital_factors", {})

    def calculate(self, data: CapitalInput) -> int:
        scores = []

        scores.append(self._score_main_inflow(data.main_net_inflow_rank))
        scores.append(self._score_north_fund(data.north_fund_net))
        scores.append(self._score_large_order(data.large_order_ratio))
        scores.append(self._score_seal_fund(data.seal_fund_amount))

        # 加权平均（资金面各子项权重均等）
        return int(sum(scores) / len(scores)) if scores else 50

    def _score_main_inflow(self, rank: str) -> int:
        mapping = self.params.get("main_net_inflow", {})
        return mapping.get(rank, 50)

    def _score_north_fund(self, net: float) -> int:
        mapping = self.params.get("north_fund", {})
        if net >= 1.0:
            return mapping.get("strong_buy", 100)
        elif net > 0:
            return mapping.get("medium_buy", 70)
        else:
            return mapping.get("sell", 20)

    def _score_large_order(self, ratio: float) -> int:
        mapping = self.params.get("large_order_ratio", {})
        if ratio >= 0.15:
            return mapping.get("high", 100)
        elif ratio >= 0.08:
            return mapping.get("medium", 70)
        else:
            return mapping.get("low", 40)

    def _score_seal_fund(self, amount: float) -> int:
        mapping = self.params.get("limit_up_fund", {})
        if amount >= 100000000:
            return mapping.get("strong", 100)
        elif amount >= 30000000:
            return mapping.get("medium", 70)
        else:
            return mapping.get("weak", 30)
