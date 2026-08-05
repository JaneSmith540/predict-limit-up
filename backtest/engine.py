"""
回测引擎
基于历史数据模拟策略运行，评估策略表现

TODO: 协作者实现完整回测框架
- 支持指定时间范围回测（2020年至今）
- 逐日模拟: 尾盘扫描 → 隔夜 → 竞价 → 开盘 → 出场
- 输出: 胜率、盈亏比、最大回撤、收益曲线
- 验收标准: NFRM≥65标的次日涨停率>55%，盈亏比>2.0
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

import pandas as pd

from config.settings import config
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class BacktestTrade:
    """单笔回测交易记录"""
    ts_code: str
    entry_date: str
    entry_price: float
    exit_date: str = ""
    exit_price: float = 0.0
    signal_level: str = ""
    holding_days: int = 0
    pnl_pct: float = 0.0       # 单笔收益率
    exit_reason: str = ""


@dataclass
class BacktestResult:
    """回测结果汇总"""
    total_trades: int = 0
    win_count: int = 0
    loss_count: int = 0
    win_rate: float = 0.0          # 胜率
    avg_win_pct: float = 0.0       # 平均盈利
    avg_loss_pct: float = 0.0     # 平均亏损
    profit_factor: float = 0.0    # 盈亏比
    max_drawdown: float = 0.0     # 最大回撤
    total_return: float = 0.0     # 总收益率
    trades: List[BacktestTrade] = field(default_factory=list)


class BacktestEngine:
    """
    回测引擎

    TODO: 协作者实现完整回测逻辑
    流程:
    1. 加载历史数据（Tushare 日线 + 涨停数据）
    2. 逐日模拟策略运行
    3. 记录交易、计算绩效
    """

    def __init__(self, start_date: str = "", end_date: str = ""):
        self.start_date = start_date or config.get("data_source.backtest.start_date", "20200101")
        self.end_date = end_date or config.get("data_source.backtest.end_date", "20260804")
        self.trades: List[BacktestTrade] = []
        logger.info(f"回测引擎初始化: {self.start_date} ~ {self.end_date}")

    def run(self) -> BacktestResult:
        """
        执行完整回测
        TODO: 协作者实现
        """
        logger.info("回测开始...")
        # TODO: 逐日模拟策略
        # for trade_date in trading_days:
        #     1. tail_scan(trade_date) → 初选池
        #     2. overnight_scan(trade_date) → 信息面更新
        #     3. auction_monitor(trade_date+1) → AHS 评分
        #     4. generate_signal() → 信号池
        #     5. entry() → 模拟建仓
        #     6. exit() → 模拟出场
        result = BacktestResult()
        logger.info("回测结束")
        return result

    def _get_trading_days(self) -> List[str]:
        """获取交易日历"""
        # TODO: 从 Tushare 获取
        return []

    def _simulate_day(self, trade_date: str):
        """模拟单日交易"""
        # TODO
        pass

    def _calculate_metrics(self) -> BacktestResult:
        """计算回测指标"""
        # TODO: 胜率、盈亏比、最大回撤等
        return BacktestResult()

    def plot_equity_curve(self, result: BacktestResult, save_path: str = ""):
        """绘制收益曲线"""
        # TODO: matplotlib / plotly
        pass
