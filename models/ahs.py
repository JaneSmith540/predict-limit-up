"""
AHS 竞价健康度评分 (Auction Health Score)

四个子项: 竞价涨幅30% + 竞价量能比30% + 委托比20% + 价格漂移20%
在集合竞价阶段 (9:15-9:25) 实时计算
"""

from dataclasses import dataclass
from typing import List

from config.settings import config


@dataclass
class AHSInput:
    """AHS 模型输入数据"""
    auction_gain: float = 0.0          # 竞价涨幅 (0-1, 相对昨收)
    volume_ratio: float = 0.0           # 竞价量能比 (竞价成交量/昨日全天成交量)
    order_ratio: float = 1.0             # 委托比 (买盘委托量/卖盘委托量)
    price_drift: str = "sideways"       # 价格漂移: upward/sideways/downward


@dataclass
class AHSResult:
    """AHS 模型输出"""
    total_score: int              # 总分 (0-100)
    sub_scores: dict              # 各子项得分
    is_healthy: bool              # 是否健康 (>=60分)


class AHSModel:
    """
    AHS 竞价健康度评分模型

    用法:
        model = AHSModel()
        result = model.calculate(ahs_input)
    """

    def __init__(self):
        self.weights = config.get("ahs.weights", {})
        self.gain_scoring = config.get("ahs.auction_gain_scoring", {})
        self.vol_scoring = config.get("ahs.volume_ratio_scoring", {})
        self.order_scoring = config.get("ahs.order_ratio_scoring", {})
        self.drift_scoring = config.get("ahs.price_drift_scoring", {})

    def calculate(self, data: AHSInput) -> AHSResult:
        """计算 AHS 综合得分"""
        scores = {}

        scores["auction_gain"] = self._score_auction_gain(data.auction_gain)
        scores["volume_ratio"] = self._score_volume_ratio(data.volume_ratio)
        scores["order_ratio"] = self._score_order_ratio(data.order_ratio)
        scores["price_drift"] = self._score_price_drift(data.price_drift)

        # 加权计算总分
        total = 0
        for key, score in scores.items():
            weight = self.weights.get(key, 0)
            total += score * weight
        total_score = int(round(total))

        return AHSResult(
            total_score=total_score,
            sub_scores=scores,
            is_healthy=total_score >= 60,
        )

    def _score_auction_gain(self, gain: float) -> int:
        """竞价涨幅评分: 3%-5%为满分"""
        for _, rule in self.gain_scoring.items():
            min_v, max_v, score = rule["min"], rule["max"], rule["score"]
            if min_v <= gain < max_v:
                return score
        return 40  # 默认

    def _score_volume_ratio(self, ratio: float) -> int:
        """竞价量能比评分: 8%-15%为满分"""
        for _, rule in self.vol_scoring.items():
            min_v, max_v, score = rule["min"], rule["max"], rule["score"]
            if min_v <= ratio < max_v:
                return score
        return 40

    def _score_order_ratio(self, ratio: float) -> int:
        """委托比评分: >5为满分"""
        for _, rule in self.order_scoring.items():
            min_v, max_v, score = rule["min"], rule["max"], rule["score"]
            if min_v <= ratio < max_v:
                return score
        return 20

    def _score_price_drift(self, drift: str) -> int:
        """价格漂移评分"""
        return self.drift_scoring.get(drift, 70)
