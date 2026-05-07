"""
🧪 WebUI 基本測試
"""
import unittest
from unittest.mock import patch

import webui


class TestWebUI(unittest.TestCase):
    @patch("webui._latest_backtest_report", return_value={})
    @patch("webui._latest_analysis_report", return_value={})
    def test_render_page_basic(self, _mock_analysis, _mock_backtest):
        html = webui._render_page("ok", "done")
        self.assertIn("Stock AI Agent - 簡易 WebUI", html)
        self.assertIn("ok", html)
        self.assertIn("done", html)

    @patch(
        "webui._latest_analysis_report",
        return_value={
            "analysis_date": "20260508",
            "total_scanned": 50,
            "total_candidates": 1,
            "ai_summary": "測試摘要",
            "operation_advice": {
                "action": "測試操作",
                "position_guidance": "測試倉位",
                "risk_alert": "測試風險",
            },
            "stocks": [
                {
                    "symbol": "1234.TW",
                    "name": "測試股",
                    "volume_ratio": 5.2,
                    "scores": {"recommendation": 88.0, "confidence": 75.0},
                }
            ],
        },
    )
    @patch("webui._latest_backtest_report", return_value={"total_trades": 3, "win_rate_pct": 66.7, "avg_final_return_pct": 4.2})
    def test_render_page_with_data(self, _mock_backtest, _mock_analysis):
        html = webui._render_page()
        self.assertIn("1234.TW", html)
        self.assertIn("測試股", html)
        self.assertIn("66.7%", html)


if __name__ == "__main__":
    unittest.main()
