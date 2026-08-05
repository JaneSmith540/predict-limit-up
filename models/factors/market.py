"""
市场面因子 (Market Factor)
评分维度: 板块共振 / 大盘环境 / 市场情绪
权重占 NFRM 总分 15%
"""

from dataclasses import dataclass

from config.settings import config


@dataclass
class MarketInput:
    """市场面因子输入数据"""
    sector_gain: float = 0.0            # 板块涨幅
    sector_limit_up_count: int = 0      # 板块内涨停股数量
    hs300_above_ma60: bool = True       # 沪深300是否在60日均线上方
    hs300_daily_gain: float = 0.0        # 沪深300当日涨跌幅
    market_limit_up_count: int = 0       # 全市场涨停家数
    market_limit_down_count: int = 0     # 全市场跌停家数


class MarketFactor:
    """市场面因子计算引擎，输出 0-100 分"""

    def __init__(self):
        self.params = config.get("nfrm.market_factors", {})

    def calculate(self, data: MarketInput) -> int:
        scores = []

        scores.append(self._score_sector(data.sector_gain, data.sector_limit_up_count))
        scores.append(self._score_market_env(data.hs300_above_ma60, data.hs300_daily_gain))
        scores.append(self._score_sentiment(data.market_limit_up_count, data.market_limit_down_count))

        return int(sum(scores) / len(scores)) if scores else 50

    def _score_sector(self, gain: float, count: int) -> int:
        mapping = self.params.get("sector_resonance", {})
        if gain >= 0.03 and count >= 3:
            return mapping.get("strong", 100)
        elif gain >= 0.01:
            return mapping.get("medium", 70)
        else:
            return mapping.get("weak", 30)

    def _score_market_env(self, above_ma60: bool, gain: float) -> int:
        mapping = self.params.get("market_env", {})
        if above_ma60 and gain > 0:
            return mapping.get("bull", 100)
        elif above_ma60:
            return mapping.get("shock", 60)
        else:
            return mapping.get("bear", 20)

    def _score_sentiment(self, up_count: int, down_count: int) -> int:
        mapping = self.params.get("sentiment", {})
        if up_count >= 50 and down_count < 10:
            return mapping.get("high", 100)
        elif up_count >= down_count:
            return mapping.get("medium", 60)
        else:
            return mapping.get("low", 20)
