"""
🧪 回測模組測試
"""
import unittest

import pandas as pd

from backtest import _evaluate_trade


class TestBacktestCalculation(unittest.TestCase):
    def test_evaluate_trade_target_hit(self):
        bars = pd.DataFrame(
            [
                {"High": 110, "Low": 98, "Close": 105},
                {"High": 118, "Low": 103, "Close": 115},
                {"High": 112, "Low": 101, "Close": 108},
            ]
        )
        final_ret, max_ret, min_ret, hit_target, hit_stop = _evaluate_trade(
            entry_price=100, target_price=115, stop_loss_price=95, bars=bars
        )
        self.assertEqual(final_ret, 8.0)
        self.assertEqual(max_ret, 18.0)
        self.assertEqual(min_ret, -2.0)
        self.assertTrue(hit_target)
        self.assertFalse(hit_stop)

    def test_evaluate_trade_stop_hit(self):
        bars = pd.DataFrame(
            [
                {"High": 101, "Low": 92, "Close": 94},
                {"High": 99, "Low": 91, "Close": 93},
            ]
        )
        final_ret, max_ret, min_ret, hit_target, hit_stop = _evaluate_trade(
            entry_price=100, target_price=120, stop_loss_price=95, bars=bars
        )
        self.assertEqual(final_ret, -7.0)
        self.assertEqual(max_ret, 1.0)
        self.assertEqual(min_ret, -9.0)
        self.assertFalse(hit_target)
        self.assertTrue(hit_stop)


if __name__ == "__main__":
    unittest.main()
