"""策略模块

涨停预测策略:
  - LimitUpStrategy: vn.py StrategyTemplate 子类 (全市场回测)
  - Strategy: 单股回测用策略类
"""
from strategies.limit_up_strategy import LimitUpStrategy


class Strategy:
    """单股回测用交易策略"""

    def __init__(self):
        from utils import get_config, log
        self.position_size = get_config("trading.position_size", 0.1)
        self.max_holding_days = get_config("trading.max_holding_days", 5)
        self.stop_loss = get_config("trading.stop_loss", -0.05)
        self.take_profit = get_config("trading.take_profit", 0.10)
        self.initial_capital = get_config("trading.initial_capital", 1000000)
        log.info(f"策略初始化 | 仓位: {self.position_size} | 最大持仓: {self.max_holding_days}天")

    def should_buy(self, prob: float, threshold: float) -> bool:
        """是否买入"""
        return prob >= threshold

    def should_sell(self, position: dict, current_price: float) -> tuple:
        """
        是否卖出

        返回: (是否卖出: bool, 原因: str)
        """
        cost_price = position["cost_price"]
        holding_days = position["holding_days"]

        # 计算收益率
        pnl = (current_price - cost_price) / cost_price

        # 止损
        if pnl <= self.stop_loss:
            return True, f"止损({pnl:.1%})"

        # 止盈
        if pnl >= self.take_profit:
            return True, f"止盈({pnl:.1%})"

        # 最大持仓天数
        if holding_days >= self.max_holding_days:
            return True, f"持仓到期({holding_days}天)"

        return False, ""


__all__ = ["LimitUpStrategy", "Strategy"]
