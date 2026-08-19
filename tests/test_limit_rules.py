import unittest

from utils import is_one_word_limit_up, limit_up_price, is_limit_up


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


class TestLimitUpPrice(unittest.TestCase):
    def test_limit_up_price_boards(self):
        # 前收 10.00：ST 10.50 / 主板 11.00 / 创业板·科创板 12.00
        self.assertEqual(limit_up_price(10.0, "st"), 10.5)
        self.assertEqual(limit_up_price(10.0, "main"), 11.0)
        self.assertEqual(limit_up_price(10.0, "chinext"), 12.0)
        self.assertEqual(limit_up_price(10.0, "star"), 12.0)
        self.assertEqual(limit_up_price(10.0), 11.0)  # 默认主板

    def test_limit_up_price_unknown_board_defaults_main(self):
        # 未知板块名回退到主板 +10%
        self.assertEqual(limit_up_price(10.0, "unknown"), 11.0)


class TestIsLimitUp(unittest.TestCase):
    def test_is_limit_up_main(self):
        # 前收 10.00，主板封板于 11.00
        self.assertTrue(is_limit_up(11.0, 10.0))

    def test_is_limit_up_star(self):
        # 创业板/科创板封板于 12.00
        self.assertTrue(is_limit_up(12.0, 10.0))

    def test_is_limit_up_not_reached(self):
        # 涨 3%（未封任何板块涨停价）不算涨停
        self.assertFalse(is_limit_up(10.3, 10.0))

    def test_is_limit_up_invalid_preclose(self):
        self.assertFalse(is_limit_up(11.0, 0))


if __name__ == "__main__":
    unittest.main()
