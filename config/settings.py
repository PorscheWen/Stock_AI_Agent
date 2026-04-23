"""
⚙️ 所有策略參數集中管理
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── API 金鑰 ─────────────────────────────────────────────
ANTHROPIC_API_KEY              = os.getenv("ANTHROPIC_API_KEY", "")
# LINE Bot（對齊 Stock_AI_Agent_ETF 命名慣例）
CHANNEL_STOCK_SECRET       = os.getenv("CHANNEL_STOCK_SECRET", "")
CHANNEL_STOCK_ACCESS_TOKEN = os.getenv("CHANNEL_STOCK_ACCESS_TOKEN", "")
CHANNEL_STOCK_USER_ID      = os.getenv("CHANNEL_STOCK_USER_ID", "")    # 單人
CHANNEL_STOCK_USER_IDS     = os.getenv("CHANNEL_STOCK_USER_IDS", "")   # 多人（逗號分隔）

# ── Claude 模型 ───────────────────────────────────────────
CLAUDE_MODEL = "claude-opus-4-5"    # 用於驗證/空方分析/最終摘要
CLAUDE_HAIKU = "claude-haiku-4-5"   # 用於快速催化劑評估

# ── 妖股掃描門檻 ──────────────────────────────────────────
LIMIT_UP_PCT          = 9.5    # 台股漲停門檻（%），觸及視為漲停
VOLUME_SURGE_MIN      = 5.0    # 最低量比（當日量 / 20日均量）
MIN_CONSECUTIVE_DAYS  = 1      # 最少連板數（1 = 今日漲停即可入選）
MAX_BOARD_ENTRY       = 3      # 最多追到第幾板（第4板以後不追）
MAX_MARKET_CAP_B      = 300    # 最大市值（億元），排除大型股

# ── 動能分析 ──────────────────────────────────────────────
MOMENTUM_OPEN_BREAK_LIMIT = 2  # 漲停打開次數超過此值動能減弱
MOMENTUM_MIN_SCORE        = 55 # 動能最低分數

# ── 催化劑分析 ────────────────────────────────────────────
CATALYST_MIN_SCORE  = 60   # 催化劑最低分數
CATALYST_CATEGORIES = {
    "policy":      "政策/法規受益",
    "earnings":    "業績驚喜/獲利大增",
    "supply_chain":"供應鏈/重大得標",
    "concept":     "概念/炒作題材",
    "turnaround":  "轉機股",
    "unknown":     "不明原因",
}

# ── 風控設定 ──────────────────────────────────────────────
MAX_STOP_LOSS_PCT   = 0.05   # 妖股最大停損 5%（嚴格執行）
MIN_RISK_REWARD     = 2.0    # 最低風報比 2:1
LIQUIDITY_MIN_VOL   = 1_000_000  # 日均量最低 100 萬股

# 板數對應建議倉位（占總資金比例）
BOARD_POSITION_PCT = {
    1: 0.10,   # 第 1 板：10%
    2: 0.15,   # 第 2 板：15%（最佳進場）
    3: 0.10,   # 第 3 板：10%
    4: 0.00,   # 第 4 板以後：不追
}

# ── 進場策略 ──────────────────────────────────────────────
ENTRY_MA_PERIOD     = 5     # 回踩支撐用 MA5
ENTRY_GAP_MIN_PCT   = 3.0   # 最小跳空缺口（%），跳空不追

# ── 出場策略 ──────────────────────────────────────────────
EXIT_TARGET_BOARDS   = 2     # 目標再漲幾板後開始出場
EXIT_PARTIAL_PCT     = 0.50  # 到目標後先出 50%
EXIT_TRAILING_PCT    = 0.05  # 移動停損幅度 5%
EXIT_MAX_HOLD_DAYS   = 4     # 最大持倉天數（不超過4天）
EXIT_PROFIT_TARGET   = 0.30  # 最高目標報酬 +30%

# ── 驗證門檻 ──────────────────────────────────────────────
CONFIDENCE_THRESHOLD   = 0.65  # 信心分數低於此值否決
MIN_BOARD_COUNT        = 2     # 最少連板數（驗證層）

# ── 輸出設定 ──────────────────────────────────────────────
REPORT_DIR = "reports"

# ── 股票名稱對照（常見妖股標的） ─────────────────────────
STOCK_NAMES: dict[str, str] = {}
