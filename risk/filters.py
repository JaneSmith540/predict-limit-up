"""
一票否决过滤器 (14项)
逐项检查一票否决清单，任意一项命中即淘汰该标的

TODO: 协作者需要实现以下 14 项检查逻辑
每个检查方法返回 None（通过）或 str（否决原因）
"""

from typing import Optional

from config.settings import config
from models.nfrm import NFRMResult
from utils.logger import get_logger

logger = get_logger(__name__)


class VetoFilter:
    """
    一票否决过滤器

    TODO: 以下所有方法目前返回 None（不否决）
          协作者需要逐个实现真实检查逻辑
    """

    def __init__(self):
        self.veto_list = config.get("veto_list", [])

    def check(self, ts_code: str, nfrm_result: NFRMResult) -> Optional[str]:
        """
        执行全部 14 项否决检查
        返回: None=通过, str=否决原因
        """
        checks = [
            self.check_nfrm(nfrm_result.total_score),
            self.check_ahs(nfrm_result.dimension_scores),
            self.check_auction_gain(),
            self.check_float_market_cap(ts_code),
            self.check_share_unlock(ts_code),
            self.check_financial_irregularity(ts_code),
            self.check_shareholder_reducing(ts_code),
            self.check_tail_seal(),
            self.check_cumulative_gain(ts_code),
            self.check_sector_retreat(),
            self.check_market_risk(),
            self.check_auction_trap(),
            self.check_zhuanggu(),
            self.check_sector_effect(),
        ]

        for result in checks:
            if result is not None:
                return result
        return None

    # TODO: 以下 14 个方法全部需要协作者实现 ----------------

    def check_nfrm(self, score: int) -> Optional[str]:
        """1. NFRM < 45"""
        if score < 45:
            return "NFRM得分低于45"
        return None

    def check_ahs(self, scores: dict) -> Optional[str]:
        """2. AHS < 50"""
        # TODO: 需要 AHS 结果传入
        return None

    def check_auction_gain(self) -> Optional[str]:
        """3. 竞价涨幅 >9%（一字板）或 <2%"""
        # TODO: 需要竞价数据
        return None

    def check_float_market_cap(self, ts_code: str) -> Optional[str]:
        """4. 流通市值 > 300亿"""
        # TODO: 从 Tushare daily_basic 获取
        return None

    def check_share_unlock(self, ts_code: str) -> Optional[str]:
        """5. 近30日有大额解禁（>流通盘5%）"""
        # TODO: 从 Tushare share_float 获取
        return None

    def check_financial_irregularity(self, ts_code: str) -> Optional[str]:
        """6. 近90日有财务非标/监管函/立案调查"""
        # TODO: 需要公告/监管数据
        return None

    def check_shareholder_reducing(self, ts_code: str) -> Optional[str]:
        """7. 大股东正在减持（公告后6个月内）"""
        # TODO: 需要公告数据
        return None

    def check_tail_seal(self) -> Optional[str]:
        """8. 尾盘偷袭板（14:30后封板且封单弱）"""
        # TODO: 需要实时盘口数据
        return None

    def check_cumulative_gain(self, ts_code: str) -> Optional[str]:
        """9. 连续上涨 > 50%后出利好"""
        # TODO: 需要历史涨幅数据
        return None

    def check_sector_retreat(self) -> Optional[str]:
        """10. 板块退潮（昨日涨停今日低开率 > 60%）"""
        # TODO: 需要板块涨停历史数据
        return None

    def check_market_risk(self) -> Optional[str]:
        """11. 大盘系统性风险（沪深300周跌幅 > 5%）"""
        # TODO: 需要沪深300周线数据
        return None

    def check_auction_trap(self) -> Optional[str]:
        """12. 竞价诱多（9:20后价格持续回落）"""
        # TODO: 需要竞价阶段 Tick 数据
        return None

    def check_zhuanggu(self) -> Optional[str]:
        """13. 庄股特征（分时钓鱼线、对倒出货）"""
        # TODO: 需要分时数据 + 模式识别
        return None

    def check_sector_effect(self) -> Optional[str]:
        """14. 无板块效应（同板块无竞价高开股）"""
        # TODO: 需要板块成分股竞价数据
        return None
