"""
信息面因子 (Information Factor)
评分维度: 公告利好评级 / 政策催化 / 舆情热度 / 美股映射
权重占 NFRM 总分 25%
"""

from dataclasses import dataclass
from typing import Dict

from config.settings import config


@dataclass
class InfoInput:
    """信息面因子输入数据"""
    announcement_title: str = ""          # 最新公告标题
    announcement_level: str = "neutral"  # 公告评级
    policy_level: str = ""                # 政策级别
    news_heat_score: int = 50             # 舆情热度分 (0-100)
    us_market_mapping_gain: float = 0.0  # 美股映射标的涨幅


class InformationFactor:
    """
    信息面因子计算引擎

    输出: 0-100 分
    """

    def __init__(self):
        self.params = config.get("nfrm.information_factors", {})

    def calculate(self, data: InfoInput) -> int:
        """计算信息面综合得分"""
        scores = []

        # 1. 公告利好评级
        ann_score = self._score_announcement(data.announcement_level)
        scores.append(ann_score)

        # 2. 政策催化
        policy_score = self._score_policy(data.policy_level)
        scores.append(policy_score)

        # 3. 舆情热度
        heat_score = self._score_news_heat(data.news_heat_score)
        scores.append(heat_score)

        # 4. 美股映射
        us_score = self._score_us_mapping(data.us_market_mapping_gain)
        scores.append(us_score)

        # 取最高分作为该维度得分（信息面只要有一条重磅利好即可）
        return max(scores) if scores else 50

    def _score_announcement(self, level: str) -> int:
        """公告评级得分"""
        mapping = self.params.get("announcement_level", {})
        return mapping.get(level, 50)

    def _score_policy(self, level: str) -> int:
        """政策催化得分"""
        mapping = self.params.get("policy_catalyst", {})
        return mapping.get(level, 50) if level else 50

    def _score_news_heat(self, heat_score: int) -> int:
        """舆情热度得分"""
        mapping = self.params.get("news_heat", {})
        if heat_score >= 80:
            return mapping.get("high", 100)
        elif heat_score >= 50:
            return mapping.get("medium", 70)
        else:
            return mapping.get("low", 40)

    def _score_us_mapping(self, gain: float) -> int:
        """美股映射得分"""
        mapping = self.params.get("us_market_mapping", {})
        if gain >= 0.05:
            return mapping.get("strong_mapping", 90)
        elif gain >= 0.02:
            return mapping.get("medium_mapping", 60)
        elif gain > 0:
            return mapping.get("weak_mapping", 30)
        return 50
