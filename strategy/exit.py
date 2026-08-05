"""
出场逻辑模块
事件驱动止盈 + 技术性止盈 + 7层止损体系
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from config.settings import config
from utils.logger import get_logger

logger = get_logger(__name__)


class ExitReason(Enum):
    """出场原因枚举"""
    # 事件驱动止盈
    HOLD_NEXT_DAY = "封板至收盘，持有至次日"
    NEXT_DAY_HIGH_OPEN = "次日竞价高开>3%，持有观察"
    AUCTION_SELL_ALL = "次日竞价低开>2%，集合竞价清仓"
    UNSEAL_30MIN = "炸板后30分钟未回封，清仓"
    SECTOR_LEADER_BREAK = "板块龙头断板，减仓50%"
    EXCHANGE_MONITOR = "交易所监控/特停，清仓"
    # 技术性止盈
    TAKE_PROFIT_50PCT = "次日竞价涨幅>7%，卖出50%"
    PROFIT_15PCT = "浮盈达15%，卖出50%"
    SEAL_FUND_DROP = "封单量骤降>50%，清仓"
    SECTOR_FOLLOWER_DOWN = "板块跟风股跌停，清仓龙头"
    # 止损
    STOP_LOSS_L1_AUCTION = "L1竞价止损: 次日竞价低开>2%"
    STOP_LOSS_L2_OPEN = "L2开盘止损: 5分钟内跌破昨收"
    STOP_LOSS_L3_TECHNICAL = "L3技术止损: 跌破涨停价/5日均线"
    STOP_LOSS_L4_UNSEAL = "L4炸板止损: 炸板后直线下杀"
    STOP_LOSS_L5_DRAWDOWN = "L5回撤止损: 浮亏达5%"
    STOP_LOSS_L6_MARKET = "L6大盘止损: 沪深300跌破60日均线且跌>3%"


@dataclass
class ExitSignal:
    """出场信号"""
    ts_code: str
    action: str            # sell_all / sell_half / hold / reduce_50pct
    volume: int = 0        # 卖出数量（0表示全部）
    price: float = 0.0     # 建议卖出价格
    reason: ExitReason = None
    stop_loss_level: str = ""  # L1-L6
    timestamp: str = ""


class ExitManager:
    """
    出场管理器

    用法:
        exit_mgr = ExitManager()
        signal = exit_mgr.check_holding(position, market_data)
    """

    def __init__(self):
        self.event_rules = config.get("exit_rules.event_driven", {})
        self.tech_rules = config.get("exit_rules.technical", {})
        self.stop_rules = config.get("exit_rules.stop_loss", {})

    def check_next_day_auction(
        self, ts_code: str, auction_gain: float
    ) -> Optional[ExitSignal]:
        """次日集合竞价出场检查"""
        # L1 竞价止损: 低开>2%
        l1 = self.stop_rules.get("L1_auction", {})
        l1_threshold = l1.get("trigger", {}).get("next_day_low_open", -0.02)
        if auction_gain <= l1_threshold:
            return ExitSignal(
                ts_code=ts_code, action="sell_all",
                reason=ExitReason.STOP_LOSS_L1_AUCTION,
                stop_loss_level="L1",
                timestamp=datetime.now().isoformat(),
            )

        # 次日竞价高开>3%，持有观察
        if auction_gain > 0.03:
            return ExitSignal(
                ts_code=ts_code, action="hold",
                reason=ExitReason.NEXT_DAY_HIGH_OPEN,
                timestamp=datetime.now().isoformat(),
            )

        # 次日竞价涨幅>7%，卖出50%
        if auction_gain > 0.07:
            return ExitSignal(
                ts_code=ts_code, action="sell_half",
                reason=ExitReason.TAKE_PROFIT_50PCT,
                timestamp=datetime.now().isoformat(),
            )

        return None

    def check_intraday(
        self,
        ts_code: str,
        position: dict,
        market_data: dict,
    ) -> Optional[ExitSignal]:
        """盘中出场检查"""
        # L2 开盘止损: 5分钟内跌破昨收
        if market_data.get("minutes_since_open", 0) <= 5:
            if market_data.get("current_price", 0) < market_data.get("prev_close", 0):
                return ExitSignal(
                    ts_code=ts_code, action="sell_all",
                    reason=ExitReason.STOP_LOSS_L2_OPEN,
                    stop_loss_level="L2",
                    timestamp=datetime.now().isoformat(),
                )

        # L5 回撤止损: 浮亏达5%
        cost_price = position.get("avg_cost", 0)
        current_price = market_data.get("current_price", 0)
        if cost_price > 0:
            loss_pct = (current_price - cost_price) / cost_price
            if loss_pct <= -0.05:
                return ExitSignal(
                    ts_code=ts_code, action="sell_all",
                    reason=ExitReason.STOP_LOSS_L5_DRAWDOWN,
                    stop_loss_level="L5",
                    timestamp=datetime.now().isoformat(),
                )

        # 炸板后30分钟未回封
        if market_data.get("unsealed", False):
            if market_data.get("minutes_since_unseal", 0) >= 30:
                return ExitSignal(
                    ts_code=ts_code, action="sell_all",
                    reason=ExitReason.UNSEAL_30MIN,
                    timestamp=datetime.now().isoformat(),
                )

        # 浮盈达15%，卖出50%
        if cost_price > 0:
            profit_pct = (current_price - cost_price) / cost_price
            if profit_pct >= 0.15:
                return ExitSignal(
                    ts_code=ts_code, action="sell_half",
                    reason=ExitReason.PROFIT_15PCT,
                    timestamp=datetime.now().isoformat(),
                )

        return None

    def check_market_risk(
        self, positions: list, hs300_data: dict
    ) -> Optional[list]:
        """L6 大盘止损: 沪深300跌破60日均线且跌幅>3%"""
        l6 = self.stop_rules.get("L6_market", {})
        trigger = l6.get("trigger", {})

        if (hs300_data.get("below_ma60", False)
                and hs300_data.get("daily_gain", 0) <= trigger.get("drop_pct", -0.03)):
            logger.warning("触发L6大盘止损，清仓所有持仓")
            return [
                ExitSignal(
                    ts_code=pos["ts_code"], action="sell_all",
                    reason=ExitReason.STOP_LOSS_L6_MARKET,
                    stop_loss_level="L6",
                    timestamp=datetime.now().isoformat(),
                )
                for pos in positions
            ]
        return None
