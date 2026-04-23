# 🧪 測試指南

## 快速開始

### 運行所有測試（推薦）
```bash
python run_tests.py
```

### 運行特定測試

#### 1. Agent 單元測試
```bash
python -m unittest tests.test_agents -v
```

#### 2. 整合測試
```bash
python -m unittest tests.test_integration -v
```

#### 3. 運行所有測試
```bash
python -m unittest discover tests -v
```

---

## 測試文件說明

| 文件 | 說明 |
|------|------|
| `tests/test_agents.py` | Agent 單元測試 - 測試各個 Agent 的初始化和基本功能 |
| `tests/test_integration.py` | 整合測試 - 測試端到端工作流程 |
| `run_tests.py` | 測試運行器 - 一鍵執行所有測試 |
| `TEST_REPORT.md` | 測試報告 - 詳細的測試結果文檔 |

---

## 測試覆蓋範圍

### ✅ Agent 測試
- ScannerAgent - 市場掃描
- MomentumAgent - 動能分析
- CatalystAgent - 催化劑評估
- RiskAgent - 風險管理
- EntryAgent - 進場策略
- ExitAgent - 出場策略
- ValidationAgent - 最終驗證
- OrchestratorAgent - 主控協調

### ✅ 功能測試
- 命令行參數 (`--help`, `--date`, `--no-line`, `--json`)
- 日期格式驗證
- 配置文件載入
- 錯誤處理機制

### ✅ 整合測試
- 端到端工作流程
- 報告生成
- JSON 輸出格式

---

## 測試前準備

確保已安裝所有依賴：
```bash
pip install -r requirements.txt
```

確保 `.env` 文件已配置：
```bash
ANTHROPIC_API_KEY=your_api_key_here
CHANNEL_STOCK_SECRET=your_line_secret
CHANNEL_STOCK_ACCESS_TOKEN=your_line_token
CHANNEL_STOCK_USER_ID=your_line_user_id
```

---

## 手動測試命令

### 測試主程式
```bash
# 顯示幫助
python main.py --help

# 分析今日（不推播 LINE）
python main.py --no-line

# 分析指定日期
python main.py --date 20260423 --no-line

# JSON 輸出模式
python main.py --date 20260423 --no-line --json
```

### 測試模組導入
```bash
python -c "from agents.orchestrator import OrchestratorAgent; print('✅ 導入成功')"
```

### 語法檢查
```bash
python -m py_compile main.py agents/*.py config/*.py
```

---

## 常見問題

### Q: 測試超時怎麼辦？
A: 某些測試需要連接外部 API，可能需要較長時間。確保網路連接正常。

### Q: API 相關測試失敗？
A: 檢查 `.env` 文件中的 API 金鑰是否正確配置。

### Q: 如何只測試特定的測試類別？
A: 使用 unittest 的路徑語法：
```bash
python -m unittest tests.test_agents.TestAgentInitialization -v
```

---

## 持續整合 (CI)

建議在 GitHub Actions 或其他 CI/CD 平台上設定自動測試：

```yaml
# .github/workflows/test.yml 範例
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: python run_tests.py
```

---

## 測試結果

最新測試結果請參考 [TEST_REPORT.md](TEST_REPORT.md)

**最後更新**: 2026-04-23  
**測試狀態**: ✅ 所有測試通過 (22/22)
