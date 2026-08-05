"""
信号生成引擎
整合 NFRM + LGM + AHS 三大模型，生成最终交易信号
"""

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from config.settings import config
from models.nfrm import NFRMModel, NFRMInput, NFRMResult
from models.lgm import LGMModel, LGMInput, LGMResult
from models.ahs import AHSModel, AHSInput, AHSResult
from risk.filters import VetoFilter
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class StockSignal:
    """单只股票的交易信号"""
    ts_code: str                     # 股票代码
    name: str = ""                   # 股票名称
    nfrm_result: Optional[NFRMResult] = None
    lgm_result: Optional[LGMResult] = None
    ahs_result: Optional[AHSResult] = None
    signal_level: str = "C"         # 信号等级 S+/S/A+/A/B/C
    max_position_pct: float = 0.0    # 建议最大仓位
    win_probability: float = 0.0    # 涨停概率
    veto_reason: str = ""            # 一票否决原因（如有）
    timestamp: str = ""             # 生成时间


class SignalGenerator:
    """
    信号生成引擎

    流程: NFRM 初筛 → 一票否决检查 → AHS 确认 → LGM 加成 → 信号分级

    用法:
        generator = SignalGenerator()
        signal = generator.generate(ts_code, nfrm_input, ahs_input, lgm_input)
    """

    def __init__(self):
        self.nfrm = NFRMModel()
        self.lgm = LGMModel()
        self.ahs = AHSModel()
        self.veto = VetoFilter()
        self.signal_levels = config.get("signal_levels", {})

    def generate(
        self,
        ts_code: str,
        nfrm_input: NFRMInput,
        ahs_input: AHSInput,
        lgm_input: LGMInput,
        name: str = "",
    ) -> StockSignal:
        """生成完整交易信号"""
        signal = StockSignal(ts_code=ts_code, name=name)

        # 1. NFRM 多因子共振评分
        signal.nfrm_result = self.nfrm.calculate(nfrm_input)
        logger.info(f"{ts_code} NFRM得分: {signal.nfrm_result.total_score} ({signal.nfrm_result.signal_level})")

        # NFRM < 45 直接淘汰
        if signal.nfrm_result.total_score < 45:
            signal.signal_level = "C"
            signal.veto_reason = "NFRM得分低于45"
            return signal

        # 2. 一票否决检查
        veto_reason = self.veto.check(ts_code, signal.nfrm_result)
        if veto_reason:
            signal.signal_level = "C"
            signal.veto_reason = veto_reason
            logger.info(f"{ts_code} 一票否决: {veto_reason}")
            return signal

        # 3. AHS 竞价健康度确认
        signal.ahs_result = self.ahs.calculate(ahs_input)
        logger.info(f"{ts_code} AHS得分: {signal.ahs_result.total_score}")

        # AHS < 50 淘汰
        if signal.ahs_result.total_score < 50:
            signal.signal_level = "C"
            signal.veto_reason = "AHS得分低于50"
            return signal

        # 4. LGM 涨停基因加成
        signal.lgm_result = self.lgm.calculate(lgm_input)
        logger.info(f"{ts_code} LGM得分: {signal.lgm_result.total_score}")

        # 5. 信号分级与仓位确定
        level, position_pct, prob = self._determine_level(signal)
        signal.signal_level = level
        signal.max_position_pct = position_pct
        signal.win_probability = prob
        signal.timestamp = datetime.now().isoformat()

        logger.info(
            f"{ts_code} 最终信号: {level} 仓位:{position_pct:.1%} 概率:{prob:.1%}"
        )
        return signal

    def _determine_level(self, signal: StockSignal) -> tuple:
        """根据 NFRM/AHS/LGM 综合确定信号等级"""
        nfrm_score = signal.nfrm_result.total_score
        ahs_score = signal.ahs_result.total_score if signal.ahs_result else 0
        lgm_score = signal.lgm_result.total_score if signal.lgm_result else 0
        all_dims = signal.nfrm_result.dimension_scores
        all_dims_above_70 = all(v >= 70 for v in all_dims.values())

        # S+ 级
        s_plus = self.signal_levels.get("S_plus", {}).get("conditions", {})
        if (nfrm_score >= s_plus.get("nfrm_min", 85)
                and ahs_score >= s_plus.get("ahs_min", 80)
                and lgm_score >= s_plus.get("lgm_min", 70)
                and all_dims_above_70):
            return "S+", 0.15, 0.70

        # S 级
        s_cond = self.signal_levels.get("S", {}).get("conditions", {})
        if (nfrm_score >= s_cond.get("nfrm_min", 75)
                and ahs_score >= s_cond.get("ahs_min", 70)
                and lgm_score >= s_cond.get("lgm_min", 60)):
            return "S", 0.12, 0.55

        # A+ 级
        a_plus = self.signal_levels.get("A_plus", {}).get("conditions", {})
        if nfrm_score >= a_plus.get("nfrm_min", 65) and ahs_score >= a_plus.get("ahs_min", 60):
            return "A+", 0.08, 0.45

        # A 级
        a_cond = self.signal_levels.get("A", {}).get("conditions", {})
        if nfrm_score >= a_cond.get("nfrm_min", 55) and ahs_score >= a_cond.get("ahs_min", 50):
            return "A", 0.05, 0.35

        # B 级
        b_cond = self.signal_levels.get("B", {}).get("conditions", {})
        if nfrm_score >= b_cond.get("nfrm_min", 45):
            return "B", 0.03, 0.25

        return "C", 0.0, 0.0
