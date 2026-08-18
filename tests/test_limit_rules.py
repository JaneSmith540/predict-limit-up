import unittest

from utils import is_one_word_limit_up


class TestOneWordLimitUp(unittest.TestCase):
    def test_one_word_main_board(self):
        # 前收 10.00，主板 +10% 一字涨停于 11.00
        self.assertTrue(is_one_word_limit_up(11.0, 11.0, 11.0, 11.0, 10.0))

    def test_one_word_star_board(self):
        # 创业板/科创板 +20% 一字涨停于 12.00
        self.assertTrue(is_one_word_limit_up(12.0, 12.0, 12.0, 12.0, 10.0))

    def test_one_word_st_board(self):
        # ST +5% 一字涨停于 5.25
        self.assertTrue(is_one_word_limit_up(5.25, 5.25, 5.25, 5.25, 5.0))

    def test_limit_up_with_intraday_range_is_buyable(self):
        # 开盘 10.50，盘中波动，收盘涨停 11.00 -> 非一字，可买
        self.assertFalse(is_one_word_limit_up(10.5, 11.0, 10.4, 11.0, 10.0))

    def test_normal_up_day(self):
        # 普通上涨日，未触及涨停
        self.assertFalse(is_one_word_limit_up(10.1, 10.3, 10.05, 10.2, 10.0))

    def test_no_pre_close(self):
        # 无前收数据时不误判
        self.assertFalse(is_one_word_limit_up(11.0, 11.0, 11.0, 11.0, None))

    def test_limit_down_not_flagged(self):
        # 跌停一字板不应被当成涨停
        self.assertFalse(is_one_word_limit_up(9.0, 9.0, 9.0, 9.0, 10.0))


if __name__ == "__main__":
    unittest.main()
