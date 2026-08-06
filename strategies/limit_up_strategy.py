"""
涨停预测策略 — vn.py StrategyTemplate 子类

交易逻辑:
  1. on_bars 收到全市场当日 K 线切片
  2. 用 t-1 及更早收盘价计算 MA5/MA10 因子（无未来函数）
  3. 模型预测涨停概率 -> 选概率最高的 N 只
  4. 持仓检查: 止损/止盈/持仓到期 -> 设置目标仓位为 0
  5. rebalance_portfolio 自动下单（t 日收盘信号 -> t+1 日开盘成交）

关键设计:
  - close_history 在因子计算之后才更新，确保因子只使用 t-1 数据
  - calculate_price 设限价至涨跌停附近，确保以 t+1 开盘价成交
  - 每次 on_bars 先重置全部 target 为当前持仓，避免隔日残留信号
"""
import numpy as np
import pandas as pd
from collections import defaultdict

from vnpy.trader.constant import Interval, Direction
from vnpy.trader.object import BarData
from vnpy_portfoliostrategy import StrategyTemplate


class LimitUpStrategy(StrategyTemplate):
    """涨停预测策略"""

    author = "predict-limit-up"

    # 策略参数
    daily_pick: int = 3            # 每日选股数量
    max_positions: int = 3         # 最大持仓数
    stop_loss: float = -0.05       # 止损比例
    take_profit: float = 0.10      # 止盈比例
    max_holding_days: int = 5      # 最大持仓天数
    position_size: float = 0.1     # 单只股票仓位比例
    initial_capital: float = 1_000_000  # 初始资金

    parameters = [
        "daily_pick", "max_positions", "stop_loss", "take_profit",
        "max_holding_days", "position_size", "initial_capital",
    ]
    variables = ["pos_count", "signal_count"]

    def __init__(self, strategy_engine, strategy_name, vt_symbols, setting):
        super().__init__(strategy_engine, strategy_name, vt_symbols, setting)

        # 收盘价历史 (用于计算 MA 因子)
        self.close_history: dict[str, list] = defaultdict(list)

        # 持仓成本价
        self.cost_prices: dict[str, float] = {}

        # 持仓天数
        self.holding_days: dict[str, int] = defaultdict(int)

        # 训练好的模型 (由回测入口注入)
        self.model = None

        # 因子列名 (与 factors 模块保持一致)
        self.factor_cols = ["ma5", "ma10"]

        # 状态变量
        self.pos_count = 0
        self.signal_count = 0

    def on_init(self) -> None:
        """策略初始化"""
        self.load_bars(20, Interval.DAILY)
        self.write_log("策略初始化")

    def on_start(self) -> None:
        """策略启动"""
        self.write_log("策略启动")

    def on_stop(self) -> None:
        """策略停止"""
        self.write_log("策略停止")

    def calculate_price(
        self,
        vt_symbol: str,
        direction: Direction,
        reference: float,
    ) -> float:
        """重写委托价格计算: 设限价至涨跌停附近，确保以 t+1 开盘价成交

        vn.py BacktestingEngine 的 cross_limit_order 逻辑:
          - LONG: order.price >= bar.low_price 才能成交
                  成交价 = min(order.price, bar.open_price)
          - SHORT: order.price <= bar.high_price 才能成交
                   成交价 = max(order.price, bar.open_price)

        设限价 = close * 1.1 (买入) / close * 0.9 (卖出):
          - 几乎一定能成交 (因为在涨跌停范围内)
          - 成交价 = open_price (实现 t+1 开盘价成交)
        """
        if direction == Direction.LONG:
            return reference * 1.1
        else:
            return reference * 0.9

    def on_bars(self, bars: dict[str, BarData]) -> None:
        """核心回调: 每日 K 线切片

        vn.py BacktestingEngine 在每个交易日调用此方法:
          - 预热期: trading=False, on_bars 被调用用于积累历史数据
          - 回测期: trading=True, 信号和交易生效

        交易时序:
          - t 日 on_bars: 用 close_history (t-1 及更早) 算因子 -> 模型预测 -> set_target
          - rebalance_portfolio 在 t 日发出限价单 (价格=收盘价*1.1/0.9)
          - t+1 日 cross_limit_order 撮合成交 (成交价=t+1开盘价)
        """

        # --- 0. 重置全部 target 为当前持仓, 清除隔日残留信号 ---
        for vt_symbol in list(self.target_data.keys()):
            self.set_target(vt_symbol, self.get_pos(vt_symbol))

        # --- 1. 检查持仓: 止损/止盈/到期 ---
        for vt_symbol in list(self.pos_data.keys()):
            pos = self.get_pos(vt_symbol)
            if pos <= 0:
                continue

            bar = bars.get(vt_symbol)
            if not bar:
                continue

            self.holding_days[vt_symbol] += 1
            cost = self.cost_prices.get(vt_symbol, bar.close_price)
            pnl = (bar.close_price - cost) / cost

            if pnl <= self.stop_loss:
                self.set_target(vt_symbol, 0)
                self.write_log(f"止损 {vt_symbol} | pnl={pnl:.1%}")
            elif pnl >= self.take_profit:
                self.set_target(vt_symbol, 0)
                self.write_log(f"止盈 {vt_symbol} | pnl={pnl:.1%}")
            elif self.holding_days[vt_symbol] >= self.max_holding_days:
                self.set_target(vt_symbol, 0)
                self.write_log(f"持仓到期 {vt_symbol} | {self.holding_days[vt_symbol]}天")

        # --- 2. 检查模型是否就绪 ---
        if not self.model:
            self.rebalance_portfolio(bars)
            self._update_close_history(bars)
            return

        # --- 3. 计算因子 (用 t-1 及更早数据, 不含当日) ---
        factor_rows = []
        factor_symbols = []

        for vt_symbol, bar in bars.items():
            closes = self.close_history.get(vt_symbol, [])
            if len(closes) < 10:
                continue

            # MA 因子: 用 close_history 的最近 5/10 天均值
            # close_history 在 _update_close_history 中更新 (在因子计算之后)
            # 所以这里的 closes 不含当日收盘价 -> 无未来函数
            ma5 = float(np.mean(closes[-5:]))
            ma10 = float(np.mean(closes[-10:]))

            factor_rows.append({"ma5": ma5, "ma10": ma10})
            factor_symbols.append(vt_symbol)

        if not factor_rows:
            self.rebalance_portfolio(bars)
            self._update_close_history(bars)
            return

        # --- 4. 模型预测 ---
        df = pd.DataFrame(factor_rows)
        probs = self.model.predict(df)
        df["prob"] = probs
        df["vt_symbol"] = factor_symbols

        # --- 5. 选股: 取概率最高的 N 只 ---
        top_n = df.nlargest(self.daily_pick, "prob")

        current_hold = sum(1 for v in self.pos_data.values() if v > 0)
        available_slots = self.max_positions - current_hold

        bought = 0
        for _, row in top_n.iterrows():
            if bought >= available_slots:
                break

            vt_symbol = row["vt_symbol"]

            # 已持仓的不再重复买入
            if self.get_pos(vt_symbol) > 0:
                continue

            bar = bars.get(vt_symbol)
            if not bar:
                continue

            # 计算买入股数 (按 100 股取整)
            buy_amount = self.initial_capital * self.position_size
            shares = int(buy_amount / bar.close_price / 100) * 100
            if shares < 100:
                continue

            # 设置目标仓位 (rebalance_portfolio 会在下一根 bar 成交)
            self.set_target(vt_symbol, shares)
            self.cost_prices[vt_symbol] = bar.close_price
            self.holding_days[vt_symbol] = 0
            bought += 1
            self.signal_count += 1

        # --- 6. 执行调仓 (t日信号 -> t+1日开盘成交) ---
        self.rebalance_portfolio(bars)

        # --- 7. 更新历史收盘价 (在因子计算之后, 确保不偷看当日) ---
        self._update_close_history(bars)

        # 更新状态变量
        self.pos_count = sum(1 for v in self.pos_data.values() if v > 0)

    def _update_close_history(self, bars: dict[str, BarData]) -> None:
        """更新收盘价缓存，只保留最近 30 天

        在因子计算之后调用，确保因子不包含当日收盘价。
        """
        for vt_symbol, bar in bars.items():
            self.close_history[vt_symbol].append(bar.close_price)
            if len(self.close_history[vt_symbol]) > 30:
                self.close_history[vt_symbol] = self.close_history[vt_symbol][-30:]
