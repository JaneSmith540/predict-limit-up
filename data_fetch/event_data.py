"""
事件数据获取模块
公告、龙虎榜、解禁、融资融券等事件类数据
"""

from typing import Optional

import pandas as pd

from data_fetch.tushare_client import TushareClient


class EventDataFetcher:
    """事件驱动数据获取器"""

    def __init__(self):
        self.client = TushareClient()

    def get_announcements(
        self, ts_code: str = "", start_date: str = "", end_date: str = ""
    ) -> pd.DataFrame:
        """获取上市公司公告列表"""
        return self.client.anns_d(
            ts_code=ts_code, start_date=start_date, end_date=end_date
        )

    def get_top_list(self, trade_date: str) -> pd.DataFrame:
        """获取龙虎榜明细"""
        return self.client.top_list(trade_date=trade_date)

    def get_top_inst(self, trade_date: str) -> pd.DataFrame:
        """获取龙虎榜机构席位明细"""
        return self.client.top_inst(trade_date=trade_date)

    def get_share_float(
        self, ts_code: str = "", start_date: str = "", end_date: str = ""
    ) -> pd.DataFrame:
        """获取限售股解禁数据"""
        return self.client.share_float(
            ts_code=ts_code, start_date=start_date, end_date=end_date
        )

    def get_margin_detail(self, trade_date: str) -> pd.DataFrame:
        """获取融资融券明细"""
        return self.client.margin_detail(trade_date=trade_date)

    def classify_announcement(self, title: str) -> str:
        """
        公告利好评级分类
        TODO: 接入 NLP 模型或规则引擎进行公告分类
        """
        # 临时规则引擎（后续可替换为 NLP）
        major_keywords = ["业绩预增", "并购重组", "重大合同", "增持", "回购"]
        moderate_keywords = ["产品涨价", "中标", "获批", "补助"]
        minor_keywords = ["例行", "董事会决议", "股东大会"]

        for kw in major_keywords:
            if kw in title:
                return "major_positive"
        for kw in moderate_keywords:
            if kw in title:
                return "moderate_positive"
        for kw in minor_keywords:
            if kw in title:
                return "minor_positive"
        return "neutral"
