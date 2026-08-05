"""
NFRM 多因子共振涨停预测模型 (N-factor Resonance Model)

五维加权: 信息面25% + 资金面25% + 技术面20% + 筹码面15% + 市场面15%
非线性放大: 五维均≥70分时，涨停概率非线性跃升
"""

from dataclasses import dataclass
from typing import Dict, Tuple

from config.settings import config
from models.factors.information import InformationFactor, InfoInput
from models.factors.capital import CapitalFactor, CapitalInput
from models.factors.technical import TechnicalFactor, TechnicalInput
from models.factors.chip import ChipFactor, ChipInput
from models.factors.market import MarketFactor, MarketInput


@dataclass
class NFRMInput:
    """NFRM 模型输入（聚合五维因子输入）"""
    info: InfoInput = None
    capital: CapitalInput = None
    technical: TechnicalInput = None
    chip: ChipInput = None
    market: MarketInput = None


@dataclass
class NFRMResult:
    """NFRM 模型输出"""
    total_score: int               # 总分 (0-100)
    dimension_scores: Dict[str, int]  # 各维度得分
    signal_level: str             # 信号等级: S+/S/A+/A/B/C
    win_probability: float        # 涨停概率
    nonlinear_boost: bool          # 是否触发非线性放大


class NFRMModel:
    """
    NFRM 多因子共振涨停预测模型

    用法:
        model = NFRMModel()
        result = model.calculate(nfrm_input)
        print(result.signal_level, result.win_probability)
    """

    def __init__(self):
        self.weights = config.get("nfrm.weights", {})
        self.score_mapping = config.get("nfrm.score_mapping", {})
        self.nonlinear = config.get("nfrm.nonlinear_amplify", {})

        # 初始化五维因子引擎
        self._info_factor = InformationFactor()
        self._capital_factor = CapitalFactor()
        self._technical_factor = TechnicalFactor()
        self._chip_factor = ChipFactor()
        self._market_factor = MarketFactor()

    def calculate(self, data: NFRMInput) -> NFRMResult:
        """计算 NFRM 综合得分"""
        # 1. 计算各维度得分
        scores = {}
        scores["information"] = self._info_factor.calculate(data.info) if data.info else 50
        scores["capital"] = self._capital_factor.calculate(data.capital) if data.capital else 50
        scores["technical"] = self._technical_factor.calculate(data.technical) if data.technical else 50
        scores["chip"] = self._chip_factor.calculate(data.chip) if data.chip else 50
        scores["market"] = self._market_factor.calculate(data.market) if data.market else 50

        # 2. 加权计算总分
        total = 0
        for dim, score in scores.items():
            weight = self.weights.get(dim, 0)
            total += score * weight
        total_score = int(round(total))

        # 3. 非线性放大效应检测
        nonlinear_boost = False
        if self.nonlinear.get("enabled", False):
            threshold = self.nonlinear.get("all_dims_threshold", 70)
            if all(s >= threshold for s in scores.values()):
                nonlinear_boost = True

        # 4. 映射信号等级与涨停概率
        signal_level, win_prob = self._map_score(total_score, nonlinear_boost)

        return NFRMResult(
            total_score=total_score,
            dimension_scores=scores,
            signal_level=signal_level,
            win_probability=win_prob,
            nonlinear_boost=nonlinear_boost,
        )

    def _map_score(self, score: int, nonlinear: bool) -> Tuple[str, float]:
        """总分映射为信号等级与涨停概率"""
        # 按分数从高到低匹配
        level_order = ["S_plus", "S", "A_plus", "A", "B", "C"]
        for level_key in level_order:
            mapping = self.score_mapping.get(level_key, {})
            min_score = mapping.get("min_score", 0)
            if score >= min_score:
                prob = mapping.get("probability", 0)
                label = mapping.get("label", level_key)
                # 非线性放大: 概率额外提升
                if nonlinear:
                    prob += self.nonlinear.get("probability_boost", 0.15)
                    prob = min(prob, 0.95)  # 概率上限95%
                return label, prob

        return "C", 0.0
