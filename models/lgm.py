"""
LGM 涨停基因模型 (Limit-up Gene Model)

五个子项: 涨停次数30% + 连板率25% + 封板成功率20% + 股性活跃度15% + 振幅10%
评估个股的"涨停基因"——是否具有持续涨停的历史特征
"""

from dataclasses import dataclass

import pandas as pd

from config.settings import config


@dataclass
class LGMInput:
    """LGM 模型输入数据"""
    limit_up_count_180d: int = 0       # 近180日涨停次数
    consecutive_rate: float = 0.0      # 连板率 (0-1)
    seal_success_rate: float = 0.0     # 封板成功率 (0-1)
    avg_turnover_20d: float = 0.0      # 20日平均换手率 (0-1)
    avg_amplitude_20d: float = 0.0     # 20日平均振幅 (0-1)


@dataclass
class LGMResult:
    """LGM 模型输出"""
    total_score: int                    # 总分 (0-100)
    sub_scores: dict                    # 各子项得分
    has_gene: bool                      # 是否具备涨停基因 (>=60分)


class LGMModel:
    """
    LGM 涨停基因模型

    用法:
        model = LGMModel()
        result = model.calculate(lgm_input)
    """

    def __init__(self):
        self.weights = config.get("lgm.weights", {})
        self.scoring = config.get("lgm.scoring", {})

    def calculate(self, data: LGMInput) -> LGMResult:
        """计算 LGM 综合得分"""
        scores = {}

        scores["limit_up_count"] = self._score_limit_up_count(data.limit_up_count_180d)
        scores["consecutive_rate"] = self._score_consecutive_rate(data.consecutive_rate)
        scores["seal_success_rate"] = self._score_seal_rate(data.seal_success_rate)
        scores["activity"] = self._score_activity(data.avg_turnover_20d)
        scores["amplitude"] = self._score_amplitude(data.avg_amplitude_20d)

        # 加权计算总分
        total = 0
        for key, score in scores.items():
            weight = self.weights.get(key, 0)
            total += score * weight
        total_score = int(round(total))

        return LGMResult(
            total_score=total_score,
            sub_scores=scores,
            has_gene=total_score >= 60,
        )

    def _score_limit_up_count(self, count: int) -> int:
        """涨停次数得分: 近180日>=5次为满分"""
        params = self.scoring.get("limit_up_count", {})
        threshold = params.get("full_score_threshold", 5)
        per_score = params.get("per_count_score", 20)
        return min(count * per_score, 100)

    def _score_consecutive_rate(self, rate: float) -> int:
        """连板率得分: >60%为满分"""
        params = self.scoring.get("consecutive_rate", {})
        threshold = params.get("full_score_threshold", 0.60)
        if rate >= threshold:
            return 100
        return int(rate / threshold * 100)

    def _score_seal_rate(self, rate: float) -> int:
        """封板成功率得分: >80%为满分"""
        params = self.scoring.get("seal_success_rate", {})
        threshold = params.get("full_score_threshold", 0.80)
        if rate >= threshold:
            return 100
        return int(rate / threshold * 100)

    def _score_activity(self, turnover: float) -> int:
        """股性活跃度得分: 换手率5%-15%为满分"""
        params = self.scoring.get("activity", {})
        min_t = params.get("turnover_rate_min", 0.05)
        max_t = params.get("turnover_rate_max", 0.15)
        if min_t <= turnover <= max_t:
            return 100
        elif turnover < min_t:
            return int(turnover / min_t * 100)
        else:  # > max
            excess = turnover - max_t
            return max(100 - int(excess * 200), 40)

    def _score_amplitude(self, amp: float) -> int:
        """振幅得分: 4%-8%为满分"""
        params = self.scoring.get("amplitude", {})
        min_a = params.get("amp_min", 0.04)
        max_a = params.get("amp_max", 0.08)
        if min_a <= amp <= max_a:
            return 100
        elif amp < min_a:
            return int(amp / min_a * 100)
        else:  # > max
            excess = amp - max_a
            return max(100 - int(excess * 200), 40)
