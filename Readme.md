# 🚀 Stock AI Agent — 妖股獵手多智能體系統

台股妖股自動偵測與買賣策略系統。**Multi-Agent 架構**，每日台股收盤後透過 GitHub Actions 自動掃描全市場，識別妖股並輸出完整的進出場操作建議，推播至 LINE Bot。

> ⚠️ 本專案資訊僅供學習參考，不構成任何投資建議。投資有風險，請自行判斷。

---

## 什麼是妖股？

妖股（Monster Stock）是**短期內出現極端異常漲幅**、且漲幅無法完全由基本面解釋的股票。

**本系統的妖股判斷條件（需同時符合）：**

| 維度 | 條件 |
|------|------|
| 價格 | 5 日漲幅 ≥ 25%，或出現連續漲停 ≥ 2 板 |
| 成交量 | 量比 ≥ 5x（當日量 / 20 日均量） |
| 市值 | 市值 ≤ 300 億（小型股易被控盤） |
| 催化劑 | 有明確題材驅動（政策/業績/供應鏈/概念） |

---

## 系統架構

```
Stock_AI_Agent/
├── .github/workflows/
│   └── daily_analysis.yml     ⏰ 每日收盤後自動執行（14:35）
├── agents/
│   ├── orchestrator.py        🧠 主控 Agent（並行協調）
│   ├── scanner_agent.py       📡 妖股掃描（TWSE 漲停偵測）
│   ├── momentum_agent.py      ⚡ 動能分析（連板強度/籌碼）
│   ├── catalyst_agent.py      🔬 催化劑分析（Claude 題材評估）
│   ├── risk_agent.py          ⚖️  風控計算（ATR/停損/倉位）
│   ├── entry_agent.py         🎯 進場策略（第幾板/追漲停）
│   ├── exit_agent.py          🚪 出場策略（目標價/移動停損）
│   ├── validation_agent.py    🔍 三重獨立驗證
│   └── line_notifier.py       📲 LINE Flex Message 推播
├── config/
│   └── settings.py            ⚙️  所有策略參數
├── main.py                    CLI 進入點
├── requirements.txt
└── .env.example
```

```
ORCHESTRATOR（主控）
    │
    ├─ [Step 1] ScannerAgent ──────► 全市場掃描（TWSE API）
    │           找出：漲停股 + 量比≥5x + 連板數
    │                         │
    ├─ [Step 2] 並行執行 ──────┤
    │   ├─ MomentumAgent      │  連板強度 / 籌碼集中度
    │   ├─ CatalystAgent      │  Claude 題材真實性評估
    │   └─ RiskAgent          │  ATR / 停損 / 建議倉位
    │                         │
    ├─ [Step 3] EntryAgent ───► 進場策略（第幾板 / 時機）
    ├─ [Step 4] ExitAgent ────► 出場策略（目標 / 停損）
    │                         │
    ├─ [Step 5] ValidationAgent ► 三重把關
    │   ├─ ① 動能一致性驗證
    │   ├─ ② 風控合規驗證
    │   └─ ③ Claude 空方邏輯反駁
    │                         │
    └─ [Step 6] 輸出報告 + LINE 推播
```

---

## 妖股買賣策略

### 進場策略（EntryAgent）

| 板數 | 風險等級 | 進場方式 | 建議倉位 |
|------|---------|---------|---------|
| 第 1 板 | 🟡 中高 | 收盤前漲停掛單（需有明確催化劑） | 10% |
| 第 2 板 | 🟢 最佳 | 開盤集合競價追漲停 / 回踩 MA5 支撐 | 15% |
| 第 3 板 | 🟠 高 | 僅限強勢市場，缺口不破才追 | 10% |
| 第 4 板以後 | 🔴 極高 | 不追，等回踩確認 | 0% |

**進場條件（需全部符合）：**
- 量比 ≥ 5x
- 有催化劑題材（新聞驗證）
- 當日大盤不跌超過 -1%
- 非進入第 5 板以後

### 出場策略（ExitAgent）

| 情境 | 操作 |
|------|------|
| 第 +2 板目標到達 | 減倉 50%，剩餘追蹤移動停損 |
| 漲停被打開 | 立即出場（主力出貨信號） |
| 次日跌停（落板） | 立即出場，不作任何等待 |
| 大盤急跌 -2% | 減倉至半倉保護利潤 |
| 達到目標利潤 +30% | 全部出場，不戀戰 |

**停損規則（嚴格執行）：**
- 進場後跌破 -5%：強制停損，不猶豫
- 漲停打開後未能再封板：出場
- 持倉超過 3 天未再創高：減倉觀望

### 驗證門檻（ValidationAgent）

| 項目 | 門檻 |
|------|------|
| 信心分數 | ≥ 65% |
| 連板數 | ≥ 2 板 |
| 量比 | ≥ 5x |
| 停損距離 | ≤ 5% |
| 催化劑評分 | ≥ 60 分 |
| 風報比 | ≥ 2:1 |

---

## 快速開始

```bash
# 1. 安裝依賴
pip install -r requirements.txt

# 2. 設定 API 金鑰
cp .env.example .env

# 3. 執行掃描
python main.py

# 4. 只輸出 JSON 報告
python main.py --json

# 5. 執行測試
python -m pytest tests/ -v
```

---

## 環境變數

| 變數 | 用途 | 必填 |
|------|------|------|
| `ANTHROPIC_API_KEY` | Claude AI（催化劑分析 + 空方驗證） | ✅ |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Bot 推播 | 選用 |
| `LINE_USER_ID` | 推播目標 ID | 選用 |

---

## GitHub Actions 自動排程

每週一至週五台灣時間 **14:35**（台股收盤後）自動執行。

支援手動觸發：GitHub repo → Actions → 妖股每日分析 → Run workflow

### Secrets 設定

| Secret | 說明 |
|--------|------|
| `ANTHROPIC_API_KEY` | Claude API 金鑰（必要） |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Bot Token（選用） |
| `LINE_USER_ID` | 推播目標用戶 ID（選用） |

---

## Agent 說明

| Agent | 職責 | 輸出 |
|-------|------|------|
| **ScannerAgent** | TWSE 全市場掃描，找漲停 + 量比 ≥ 5x + 計算連板數 | 妖股候選清單 |
| **MomentumAgent** | 連板強度、漲停打開次數、換手率、籌碼集中度 | 動能評分 0-100 |
| **CatalystAgent** | Claude 評估題材真實性、持續性、市場共識 | 催化劑評分 0-100 |
| **RiskAgent** | ATR 停損計算、板數動態倉位調整、風險等級 L1-L5 | 風控參數 |
| **EntryAgent** | 最佳進場方式（漲停追進/集合競價/回踩 MA5）與價格區間 | 進場建議 |
| **ExitAgent** | 分批出場計劃、移動停損條件、緊急出場觸發 | 出場策略 |
| **ValidationAgent** | 三重把關：動能一致性 + 風控合規 + Claude 空方反駁 | 通過/否決 + 信心分數 |
| **OrchestratorAgent** | 並行協調所有 Agent，生成報告 + LINE 推播 | JSON 報告 |
