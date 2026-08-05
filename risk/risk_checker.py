"""
风控检查器
独立于策略类的风控模块，每次下单前强制执行

TODO: 协作者需要实现以下检查
- 单票仓位上限
- 单日建仓上限
- 板块集中度
- 大盘熔断（沪深300跌超3%清仓）
- T+1约束检查
- 黑名单管理（连续2次止损暂停5日）
- 撤单频率（单日不超过50次）
"""

from datetime import datetime, timedelta
from typing import List, Optional
from pathlib import Path
import json

from config.settings import config, PROJECT_ROOT
from strategy.position_manager import Position
from utils.logger import get_logger

logger = get_logger(__name__)


class RiskChecker:
    """
    风控检查器

    TODO: 所有方法目前返回 True（通过），协作者需要实现真实检查逻辑
    """

    def __init__(self):
        self.risk_config = config.get("risk_control", {})
        self._daily_build_amount = 0.0
        self._daily_cancel_count = 0
        self._blacklist = self._load_blacklist()

    def check_before_order(
        self,
        ts_code: str,
        amount: float,
        total_capital: float,
        positions: List[Position],
    ) -> tuple:
        """
        下单前风控检查
        返回: (通过与否: bool, 原因: str)
        """
        # TODO: 实现以下检查
        checks = [
            self.check_single_stock_limit(ts_code, amount, total_capital),
            self.check_daily_build_limit(amount, total_capital),
            self.check_sector_concentration(ts_code, amount, total_capital, positions),
            self.check_blacklist(ts_code),
            self.check_cancel_frequency(),
        ]
        for passed, reason in checks:
            if not passed:
                return False, reason
        return True, "通过"

    # --- 具体检查方法（全部待实现）---

    def check_single_stock_limit(self, ts_code, amount, total_capital) -> tuple:
        """单票仓位上限 15%"""
        # TODO
        return True, "通过"

    def check_daily_build_limit(self, amount, total_capital) -> tuple:
        """单日建仓上限 25%"""
        # TODO
        return True, "通过"

    def check_sector_concentration(self, ts_code, amount, total_capital, positions) -> tuple:
        """单一板块 ≤ 30%"""
        # TODO
        return True, "通过"

    def check_market_circuit_breaker(self, hs300_drop: float) -> Optional[str]:
        """大盘熔断: 沪深300跌超3% → 清仓所有"""
        # TODO
        return None

    def check_t_plus_1(self, entry_date: str) -> bool:
        """T+1约束: 当日买入次日才可卖出"""
        # TODO
        return True

    def check_blacklist(self, ts_code: str) -> tuple:
        """黑名单检查"""
        if ts_code in self._blacklist:
            return False, f"黑名单标的({ts_code})"
        return True, "通过"

    def check_cancel_frequency(self) -> tuple:
        """撤单频率: 单日不超过50次"""
        # TODO
        return True, "通过"

    def add_to_blacklist(self, ts_code: str, reason: str):
        """加入黑名单"""
        suspend_days = self.risk_config.get("blacklist", {}).get("suspend_days", 5)
        self._blacklist[ts_code] = {
            "reason": reason,
            "added_date": datetime.now().strftime("%Y-%m-%d"),
            "expire_date": (datetime.now() + timedelta(days=suspend_days)).strftime("%Y-%m-%d"),
        }
        self._save_blacklist()
        logger.warning(f"加入黑名单: {ts_code} 原因: {reason}")

    # --- 黑名单持久化 ---

    def _load_blacklist(self) -> dict:
        """加载黑名单"""
        # TODO: 从 SQLite/JSON 加载
        return {}

    def _save_blacklist(self):
        """保存黑名单"""
        # TODO: 写入 SQLite/JSON
        pass
