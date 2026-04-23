"""
🧪 整合測試 - 測試端到端工作流程
"""
import unittest
import sys
import json
from datetime import datetime
from io import StringIO


class TestMainScript(unittest.TestCase):
    """測試主程式腳本"""

    def test_help_command(self):
        """測試 --help 參數"""
        import subprocess
        result = subprocess.run(
            ["python", "main.py", "--help"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("妖股 Multi-Agent 分析系統", result.stdout)
        self.assertIn("--date", result.stdout)
        self.assertIn("--no-line", result.stdout)
        self.assertIn("--json", result.stdout)

    def test_invalid_date_format(self):
        """測試無效的日期格式"""
        import subprocess
        result = subprocess.run(
            ["python", "main.py", "--date", "2026-04-23"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("日期格式錯誤", result.stderr)

    def test_import_all_agents(self):
        """測試所有 Agent 可正常導入"""
        try:
            from agents.scanner_agent import ScannerAgent
            from agents.momentum_agent import MomentumAgent
            from agents.catalyst_agent import CatalystAgent
            from agents.risk_agent import RiskAgent
            from agents.entry_agent import EntryAgent
            from agents.exit_agent import ExitAgent
            from agents.validation_agent import ValidationAgent
            from agents.orchestrator import OrchestratorAgent
            
            # 成功導入
            self.assertTrue(True)
        except ImportError as e:
            self.fail(f"導入 Agent 失敗: {e}")


class TestReportGeneration(unittest.TestCase):
    """測試報告生成"""

    def test_daily_reports_exist(self):
        """測試 daily_run 目錄有報告"""
        import os
        import glob
        
        reports = glob.glob("daily_run/surge_report_*.md")
        self.assertGreater(len(reports), 0, "應該至少有一份報告")

    def test_report_format(self):
        """測試報告格式"""
        import os
        import glob
        
        reports = sorted(glob.glob("daily_run/surge_report_*.md"))
        if reports:
            with open(reports[-1], 'r', encoding='utf-8') as f:
                content = f.read()
                # 檢查關鍵區塊（適應實際報告格式）
                self.assertTrue(
                    "妖股報告" in content or "台股" in content or "分析" in content,
                    "報告應包含分析內容"
                )


class TestConfigValidation(unittest.TestCase):
    """測試配置驗證"""

    def test_env_file_exists(self):
        """測試 .env 文件存在"""
        import os
        self.assertTrue(os.path.exists(".env"), ".env 文件應該存在")

    def test_required_settings(self):
        """測試必要的設定參數"""
        from config.settings import (
            LIMIT_UP_PCT,
            VOLUME_SURGE_MIN,
            MIN_CONSECUTIVE_DAYS,
            MAX_BOARD_ENTRY,
            MAX_MARKET_CAP_B,
        )
        
        # 驗證數值合理性
        self.assertGreater(LIMIT_UP_PCT, 0)
        self.assertGreater(VOLUME_SURGE_MIN, 0)
        self.assertGreaterEqual(MIN_CONSECUTIVE_DAYS, 1)
        self.assertGreaterEqual(MAX_BOARD_ENTRY, 1)
        self.assertGreater(MAX_MARKET_CAP_B, 0)

    def test_api_key_configured(self):
        """測試 API 金鑰已配置（不檢查有效性）"""
        from config.settings import ANTHROPIC_API_KEY
        # 只檢查是否已設定，不檢查有效性
        self.assertIsInstance(ANTHROPIC_API_KEY, str)


class TestErrorHandling(unittest.TestCase):
    """測試錯誤處理"""

    def test_keyboard_interrupt_handling(self):
        """測試 Ctrl+C 中斷處理"""
        # 這個測試只驗證程式碼結構
        with open("main.py", "r", encoding="utf-8") as f:
            content = f.read()
            self.assertIn("KeyboardInterrupt", content)
            self.assertIn("except Exception", content)

    def test_graceful_error_exit(self):
        """測試程式會優雅地處理錯誤"""
        with open("main.py", "r", encoding="utf-8") as f:
            content = f.read()
            self.assertIn("sys.exit(1)", content)


if __name__ == "__main__":
    # 設定詳細輸出
    unittest.main(verbosity=2)
