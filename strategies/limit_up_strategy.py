"""涨停预测策略 — vn.py StrategyTemplate 子类
支持滚动重训：多模型按日期段切换
交易时序: t日收盘信号 -> t+1日开盘成交
"""
import numpy as np
import pandas as pd
from collections import defaultdict

from vnpy.trader.constant import Interval, Direction
from vnpy.trader.object import BarData
from vnpy_portfoliostrategy import StrategyTemplate

from factors import get_factor_columns
from factors.factor import calculate_factors


class LimitUpStrategy(StrategyTemplate):
    """涨停预测策略（滚动重训）"""

    author = "predict-limit-up"

    daily_pick: int = 2
    max_positions: int = 2
    stop_loss: float = -0.04
    take_profit: float = 0.10
    max_holding_days: int = 3
    position_size: float = 0.50
    initial_capital: float = 1_000_000
    min_prob: float = 0.40

    parameters = [
        "daily_pick", "max_positions", "stop_loss", "take_profit",
        "max_holding_days", "position_size", "initial_capital", "min_prob",
    ]
    variables = ["pos_count", "signal_count"]

    def __init__(self, strategy_engine, strategy_name, vt_symbols, setting):
        super().__init__(strategy_engine, strategy_name, vt_symbols, setting)

        self.close_history = defaultdict(list)
        self.cost_prices = {}
        self.holding_days = defaultdict(int)
        self.entry_probs = {}

        self.model = None
        self.models_with_dates = None
        self.exit_model = None

        self.factor_cols = get_factor_columns()
        self.pos_count = 0
        self.signal_count = 0
        self.market_trade_days = None

    def on_init(self) -> None:
        self.load_bars(30, Interval.DAILY)
        self.write_log("策略初始化")

    def on_start(self) -> None:
        self.write_log("策略启动")

    def on_stop(self) -> None:
        self.write_log("策略停止")

    def calculate_price(self, vt_symbol, direction, reference):
        if direction == Direction.LONG:
            return reference * 1.1
        else:
            return reference * 0.9

    def _get_active_model(self, current_date):
        """根据当前日期选择对应的模型"""
        if not self.models_with_dates:
            return self.model
        for item in self.models_with_dates:
            if item["start"] <= current_date < item["end"]:
                return item["model"]
        return self.models_with_dates[-1]["model"]

    def on_bars(self, bars):
        """核心回调: 每日 K 线切片"""

        # --- 0. 重置全部 target ---
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

            should_sell = False
            sell_reason = ""

            if pnl <= self.stop_loss:
                should_sell = True
                sell_reason = "止损 pnl=" + format(pnl, ".1%")
            elif pnl >= self.take_profit:
                should_sell = True
                sell_reason = "止盈 pnl=" + format(pnl, ".1%")
            elif self.holding_days[vt_symbol] >= self.max_holding_days:
                should_sell = True
                sell_reason = "到期 " + str(self.holding_days[vt_symbol]) + "天"

            if should_sell:
                self.set_target(vt_symbol, 0)
                self.write_log(sell_reason + " " + vt_symbol)
                if vt_symbol in self.cost_prices:
                    del self.cost_prices[vt_symbol]
                if vt_symbol in self.entry_probs:
                    del self.entry_probs[vt_symbol]

        # --- 2. 获取当前日期并选择模型 ---
        current_dt = next(iter(bars.values())).datetime
        current_date = current_dt.strftime("%Y%m%d")
        active_model = self._get_active_model(current_date)

        if not active_model:
            self.rebalance_portfolio(bars)
            self._update_close_history(bars)
            return

        # --- 2.5 市场趋势过滤（可选）---
        if self.market_trade_days is not None:
            if current_date not in self.market_trade_days:
                self.rebalance_portfolio(bars)
                self._update_close_history(bars)
                return

        # --- 3. 计算因子 ---
        factor_rows = []
        factor_symbols = []

        for vt_symbol, bar in bars.items():
            closes = self.close_history.get(vt_symbol, [])
            if len(closes) < 15:
                continue
            factor_dict = calculate_factors(closes)
            if not factor_dict:
                continue
            factor_rows.append(factor_dict)
            factor_symbols.append(vt_symbol)

        if not factor_rows:
            self.rebalance_portfolio(bars)
            self._update_close_history(bars)
            return

        # --- 4. 模型预测 ---
        df = pd.DataFrame(factor_rows)
        probs = active_model.predict(df)
        df["prob"] = probs
        df["vt_symbol"] = factor_symbols

        # --- 5. 选股: 始终选Top N，设最低概率下限 ---
        min_floor = 0.30
        qualified = df[df["prob"] >= min_floor]
        if len(qualified) < self.daily_pick:
            qualified = df.nlargest(self.daily_pick, "prob")
        top_n = qualified.nlargest(self.daily_pick, "prob")

        current_hold = sum(1 for v in self.pos_data.values() if v > 0)
        available_slots = self.max_positions - current_hold

        bought = 0
        for _, row in top_n.iterrows():
            if bought >= available_slots:
                break
            vt_symbol = row["vt_symbol"]
            if self.get_pos(vt_symbol) > 0:
                continue
            bar = bars.get(vt_symbol)
            if not bar:
                continue
            buy_amount = self.initial_capital * self.position_size
            shares = int(buy_amount / bar.close_price / 100) * 100
            if shares < 100:
                continue
            self.set_target(vt_symbol, shares)
            self.cost_prices[vt_symbol] = bar.close_price
            self.holding_days[vt_symbol] = 0
            self.entry_probs[vt_symbol] = row["prob"]
            bought += 1
            self.signal_count += 1

        # --- 6. 执行调仓 ---
        self.rebalance_portfolio(bars)
        self._update_close_history(bars)
        self.pos_count = sum(1 for v in self.pos_data.values() if v > 0)

    def _update_close_history(self, bars):
        for vt_symbol, bar in bars.items():
            self.close_history[vt_symbol].append(bar.close_price)
            if len(self.close_history[vt_symbol]) > 40:
                self.close_history[vt_symbol] = self.close_history[vt_symbol][-40:]
