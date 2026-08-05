"""
仓位管理模块
基于凯利公式的仓位计算 + 组合层面风险预算
"""

from dataclasses import dataclass
from typing import Dict, List

from config.settings import config
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class Position:
    """持仓信息"""
    ts_code: str
    name: str = ""
    volume: int = 0               # 持仓数量
    avg_cost: float = 0.0         # 持仓均价
    entry_date: str = ""          # 建仓日期
    holding_days: int = 0          # 持有天数
    signal_level: str = ""         # 入场信号等级
    sector: str = ""               # 所属板块


class PositionManager:
    """
    仓位管理器

    - 凯利公式计算最优仓位
    - 组合层面风险预算（单票上限、日建仓上限、板块集中度）
    - 最大同时持仓数控制
    """

    def __init__(self):
        self.risk = config.get("risk_control", {})
        self.portfolio = self.risk.get("portfolio", {})

    def kelly_fraction(self, win_prob: float, win_loss_ratio: float = 2.0) -> float:
        """
        凯利公式计算最优仓位比例
        f* = (bp - q) / b
        b = 盈亏比, p = 胜率, q = 1 - p
        """
        b = win_loss_ratio
        p = win_prob
        q = 1 - p
        if b * p - q <= 0:
            return 0.0
        kelly = (b * p - q) / b
        # 凯利公式通常取半凯利（更保守）
        return min(kelly * 0.5, self.risk.get("single_stock_max_pct", 0.15))

    def check_position_limits(
        self,
        current_positions: List[Position],
        total_capital: float,
        new_ts_code: str,
        new_sector: str,
        intended_pct: float,
    ) -> float:
        """
        检查组合层面风控限制，返回实际允许的仓位比例

        检查项:
        1. 单票仓位上限
        2. 单日建仓上限
        3. 板块集中度
        4. 最大同时持仓数
        """
        actual_pct = intended_pct

        # 1. 单票仓位上限
        single_max = self.risk.get("single_stock_max_pct", 0.15)
        actual_pct = min(actual_pct, single_max)

        # 2. 最大同时持仓数
        max_positions = self.portfolio.get("max_concurrent_positions", 3)
        if len(current_positions) >= max_positions:
            logger.info(f"已达最大持仓数({max_positions})，拒绝新仓位")
            return 0.0

        # 3. 板块集中度
        sector_max = self.risk.get("sector_concentration_max", 0.30)
        sector_exposure = sum(
            p.volume * p.avg_cost
            for p in current_positions
            if p.sector == new_sector
        ) / total_capital if total_capital > 0 else 0
        remaining_sector = sector_max - sector_exposure
        actual_pct = min(actual_pct, remaining_sector)

        # 4. 现金保留
        cash_min = config.get("entry_phases.cash_reserve.min_pct", 0.10)
        total_exposure = sum(p.volume * p.avg_cost for p in current_positions) / total_capital
        remaining_capital = 1.0 - total_exposure - cash_min
        actual_pct = min(actual_pct, max(remaining_capital, 0.0))

        return round(actual_pct, 4)

    def update_holding_days(self, positions: List[Position]):
        """更新持仓天数，检查是否超过最大持有天数"""
        max_days = self.portfolio.get("max_holding_days", 5)
        expired = []
        for pos in positions:
            pos.holding_days += 1
            if pos.holding_days >= max_days:
                logger.info(f"{pos.ts_code} 持有{pos.holding_days}天，达到最大持有天数，触发出场")
                expired.append(pos)
        return expired
