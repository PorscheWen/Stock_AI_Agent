# Stock_AI_Agent

台股爆量飆股分析系統，每日收盤後透過 GitHub Actions 自動掃描 TWSE 前百大成交量個股，篩選次日爆發潛力股並推播 LINE 操作建議。

## 架構

```
surge_analyzer.py          # 主分析程式
    ├── 抓取 TWSE 前百大成交量個股
    ├── 技術指標篩選（量能、價格突破）
    ├── backtest_agent.py  # 回測驗證
    ├── check_rules.py     # 規則檢查
    └── line_push.py       # LINE 推播
```

## 功能

| 功能 | 說明 |
|------|------|
| 成交量掃描 | 抓取 TWSE 當日全部成交資料，篩選前 100 大量個股 |
| 爆發潛力評分 | 量能、價格突破、技術指標綜合評分 |
| 回測驗證 | 歷史勝率驗證（backtest_agent.py） |
| LINE 推播 | 每日自動推播操作建議 |
| 報告存檔 | 分析報告 commit 至 `daily_run/`，保留最新 10 筆 |
| 關鍵字自動更新 | `auto_update_keywords.py` 定期更新 `keywords.json` |

## GitHub Actions 自動排程

每週一至週五台灣時間 **13:50**（台股收盤後）自動執行，無需本機常駐。

支援手動觸發：GitHub repo → Actions → Daily Stock Analysis → Run workflow

### 必要 Secrets（GitHub repo → Settings → Secrets and variables → Actions）

| Secret | 說明 |
|--------|------|
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Bot Token |
| `LINE_USER_ID` | 推播目標用戶 ID |

## 快速啟動（本機執行）

```bash
# 1. 安裝套件
pip install -r requirements.txt

# 2. 設定環境變數
cp .env.example .env
# 填入 LINE_CHANNEL_ACCESS_TOKEN 與 LINE_USER_ID

# 3. 立即執行一次
python surge_analyzer.py
```

## 檔案結構

```
├── .github/workflows/         # GitHub Actions 排程
├── surge_analyzer.py          # 主分析程式（TWSE 資料抓取與評分）
├── backtest_agent.py          # 歷史回測驗證
├── line_push.py               # LINE Push 推播
├── check_rules.py             # 規則篩選
├── auto_update_keywords.py    # 關鍵字自動更新
├── keywords.json              # 關鍵字設定
├── daily_run/                 # 每日分析報告存檔
├── requirements.txt
└── run_daily.bat              # Windows 本機手動執行腳本
```

> ⚠️ 本專案資訊僅供參考，不構成任何投資建議。
