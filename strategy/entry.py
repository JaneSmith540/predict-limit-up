"""
入场逻辑模块
管理五阶段建仓节奏: 研究观察 → 竞价挂单 → 开盘加仓 → 回封加仓 → 预留现金
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from config.settings import config
from strategy.signal_generator import StockSignal
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class OrderRequest:
    """下单请求"""
    ts_code: str
    direction: str          # buy / sell
    price: float
    volume: int
    order_type: str         # limit / market
    reason: str
    timestamp: str = ""


class EntryManager:
    """
    入场管理器 — 控制五阶段建仓节奏

    用法:
        entry = EntryManager()
        orders = entry.execute_auction_order(signal, open_price, limit_price)
    """

    def __init__(self):
        self.phases = config.get("entry_phases", {})
        self.seal_signals = config.get("seal_confirm_signals", {})

    def execute_auction_order(
        self,
        signal: StockSignal,
        open_price: float,
        limit_up_price: float,
        total_capital: float,
    ) -> Optional[OrderRequest]:
        """
        阶段2: 竞价挂单 (T日9:25后)

        挂单价 = min(开盘价 * 1.02, 涨停价 * 0.99)
        预计秒板标的直接挂涨停价排队
        """
        if signal.signal_level == "C":
            return None

        phase = self.phases.get("auction_order", {})
        position_pct = min(signal.max_position_pct, phase.get("position_pct_max", 0.08))

        # 计算挂单价
        price_mult_open = phase.get("order_price_open_multiplier", 1.02)
        price_mult_limit = phase.get("order_price_limit_multiplier", 0.99)
        order_price = min(open_price * price_mult_open, limit_up_price * price_mult_limit)

        # 计算下单数量（A股100股整手）
        order_amount = total_capital * position_pct
        volume = int(order_amount / order_price / 100) * 100

        if volume < 100:
            logger.warning(f"{signal.ts_code} 仓位过小，跳过挂单")
            return None

        order = OrderRequest(
            ts_code=signal.ts_code,
            direction="buy",
            price=round(order_price, 2),
            volume=volume,
            order_type="limit",
            reason=f"竞价挂单 信号等级:{signal.signal_level}",
            timestamp=datetime.now().isoformat(),
        )
        logger.info(f"竞价挂单: {order.ts_code} {order.volume}股 @ {order.price}")
        return order

    def execute_open_add(
        self,
        signal: StockSignal,
        current_price: float,
        total_capital: float,
        seal_signals_met: list,
    ) -> Optional[OrderRequest]:
        """
        阶段3: 开盘加仓 (9:30-9:35)
        需满足秒板确认信号（至少4项）
        """
        required = self.seal_signals.get("required_count", 4)
        if len(seal_signals_met) < required:
            logger.info(f"{signal.ts_code} 秒板确认信号不足({len(seal_signals_met)}/{required})，放弃加仓")
            return None

        # 检查弱势信号
        weak_signals = self.seal_signals.get("weak_signals", {})
        if weak_signals.get("low_open") and "low_open" in seal_signals_met:
            return None

        phase = self.phases.get("open_add", {})
        position_pct = phase.get("position_pct_max", 0.07)
        order_amount = total_capital * position_pct
        volume = int(order_amount / current_price / 100) * 100

        if volume < 100:
            return None

        order = OrderRequest(
            ts_code=signal.ts_code,
            direction="buy",
            price=round(current_price, 2),
            volume=volume,
            order_type="limit",
            reason=f"开盘加仓 秒板确认({len(seal_signals_met)}/{required})",
            timestamp=datetime.now().isoformat(),
        )
        logger.info(f"开盘加仓: {order.ts_code} {order.volume}股 @ {order.price}")
        return order

    def check_cancel(
        self,
        order: OrderRequest,
        current_price: float,
        open_price: float,
        minutes_since_open: int,
    ) -> bool:
        """检查是否需要撤单（开盘后1分钟内未成交且价格回落）"""
        cancel_min = self.phases.get("auction_order", {}).get("cancel_minutes", 1)
        if minutes_since_open >= cancel_min and current_price < open_price:
            logger.info(f"{order.ts_code} 未成交且价格回落，执行撤单")
            return True
        return False
