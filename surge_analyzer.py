"""
Taiwan Stock Top-100 Volume - Next-Day Surge Potential Analysis
Analysis date: 2026-04-10
"""

import sys
import io
# Force UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import os
import requests
import pandas as pd
import yfinance as yf
import json
import re
from datetime import datetime, timedelta, timezone

def _get_last_trading_date() -> str:
    """自動計算最近一個台股交易日（YYYYMMDD），跳過週末。以台灣時區（UTC+8）為基準。"""
    TW = timezone(timedelta(hours=8))
    candidate = datetime.now(TW).replace(hour=0, minute=0, second=0, microsecond=0)
    # 若是週末則往前找最近的週五
    while candidate.weekday() >= 5:  # 5=Saturday, 6=Sunday
        candidate -= timedelta(days=1)
    return candidate.strftime("%Y%m%d")

TRADE_DATE = _get_last_trading_date()
TRADE_DATE_FMT = f"{TRADE_DATE[:4]}-{TRADE_DATE[4:6]}-{TRADE_DATE[6:]}"


# ─────────────────────────────────────────
# Step 1: 抓取 TWSE 當日全部成交資料
# ─────────────────────────────────────────
def fetch_top100_by_volume(date_str: str) -> pd.DataFrame:
    url = f"https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY_ALL?response=json&date={date_str}"
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    data = resp.json()

    rows = data.get("data", [])
    if not rows:
        raise ValueError("TWSE 資料為空，請確認日期是否為交易日")

    df = pd.DataFrame(rows, columns=[
        "code", "name", "shares", "value",
        "open", "high", "low", "close",
        "change", "volume_lots"
    ])

    # 只保留純數字代號的個股（排除 ETF / ETN 等 6 碼）
    df = df[df["code"].str.match(r"^\d{4}$")]

    def parse_num(x):
        try:
            return float(str(x).replace(",", ""))
        except:
            return 0.0

    df["shares"] = df["shares"].apply(parse_num)
    df["volume_lots"] = df["volume_lots"].apply(parse_num)
    df["close"] = df["close"].apply(parse_num)
    df["open"] = df["open"].apply(parse_num)
    df["high"] = df["high"].apply(parse_num)
    df["low"] = df["low"].apply(parse_num)

    # 解析漲跌幅
    def parse_change(x):
        x = str(x).strip()
        m = re.search(r"([+-]?\d+\.?\d*)", x)
        return float(m.group(1)) if m else 0.0

    df["change_val"] = df["change"].apply(parse_change)
    df["change_pct"] = df.apply(
        lambda r: (r["change_val"] / (r["close"] - r["change_val"]) * 100)
        if (r["close"] - r["change_val"]) > 0 else 0.0,
        axis=1
    )

    # 依成交量(張)排序，取前 100
    df = df.sort_values("volume_lots", ascending=False).head(100).reset_index(drop=True)
    return df


# ─────────────────────────────────────────
# Step 2: 用 yfinance 抓取近 60 日歷史
# ─────────────────────────────────────────
def fetch_history(code: str) -> pd.DataFrame | None:
    ticker_sym = f"{code}.TW"
    try:
        ticker = yf.Ticker(ticker_sym)
        hist = ticker.history(period="3mo")
        if hist.empty or len(hist) < 20:
            return None
        hist.index = hist.index.tz_localize(None)
        return hist
    except Exception:
        return None


# ─────────────────────────────────────────
# Step 3: 計算技術指標
# ─────────────────────────────────────────
def calc_indicators(hist: pd.DataFrame) -> dict:
    close = hist["Close"]
    volume = hist["Volume"]

    # 均線
    ma5  = close.rolling(5).mean().iloc[-1]
    ma20 = close.rolling(20).mean().iloc[-1]
    ma60 = close.rolling(60).mean().iloc[-1] if len(close) >= 60 else None
    last_close = close.iloc[-1]
    prev_close = close.iloc[-2] if len(close) >= 2 else last_close

    # RSI(14)
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    rsi = (100 - 100 / (1 + rs)).iloc[-1]

    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    macd_bar = (dif - dea) * 2
    dif_val = dif.iloc[-1]
    dea_val = dea.iloc[-1]
    macd_val = macd_bar.iloc[-1]
    prev_macd = macd_bar.iloc[-2] if len(macd_bar) >= 2 else macd_val

    # 布林通道
    ma20_s = close.rolling(20).mean()
    std20  = close.rolling(20).std()
    upper  = (ma20_s + 2 * std20).iloc[-1]
    lower  = (ma20_s - 2 * std20).iloc[-1]

    # 成交量比
    vol_now  = volume.iloc[-1]
    vol_ma20 = volume.rolling(20).mean().iloc[-1]
    vol_ratio = vol_now / (vol_ma20 + 1e-9)

    # 近 5 日漲幅
    ret5 = (last_close / close.iloc[-6] - 1) * 100 if len(close) >= 6 else 0

    return {
        "last_close": last_close,
        "prev_close": prev_close,
        "change_pct_yf": (last_close / prev_close - 1) * 100,
        "ma5": ma5,
        "ma20": ma20,
        "ma60": ma60,
        "rsi": rsi,
        "dif": dif_val,
        "dea": dea_val,
        "macd_bar": macd_val,
        "prev_macd_bar": prev_macd,
        "upper_band": upper,
        "lower_band": lower,
        "mid_band": (ma20_s).iloc[-1],
        "vol_ratio": vol_ratio,
        "ret5": ret5,
    }


# ─────────────────────────────────────────
# Step 4: 法人籌碼
# ─────────────────────────────────────────
def fetch_institutional(date_str: str) -> dict:
    """回傳 {code: {foreign, trust, dealer}} 的字典"""
    url = f"https://www.twse.com.tw/rwd/zh/fund/T86?response=json&date={date_str}&selectType=ALL"
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        data = resp.json()
        if data.get("stat") != "OK":
            return {}
        result = {}
        for row in data.get("data", []):
            code = str(row[0]).strip()
            def to_int(x):
                try:
                    return int(str(x).replace(",", ""))
                except:
                    return 0
            result[code] = {
                "foreign": to_int(row[4]),   # 外資買賣超
                "trust":   to_int(row[10]),  # 投信買賣超
                "dealer":  to_int(row[14]),  # 自營商買賣超
            }
        return result
    except Exception:
        return {}


# ─────────────────────────────────────────
# Step 5: 評分模型（暴漲潛力）
# ─────────────────────────────────────────
def score_surge_potential(ind: dict, inst: dict, today_info: dict) -> float:
    score = 0.0

    # === 技術面 (最高 60 分) ===

    # 1. 均線多頭排列
    if ind["ma5"] > ind["ma20"]:
        score += 8
    if ind["ma20"] > (ind["ma60"] or 0):
        score += 5

    # 2. RSI 超賣回彈（30-50 金叉潛力區）
    rsi = ind["rsi"]
    if 30 < rsi < 50:
        score += 10
    elif 50 <= rsi < 65:
        score += 5
    elif rsi < 30:
        score += 7  # 極度超賣，反彈機率高

    # 3. MACD 金叉或剛金叉
    if ind["dif"] > ind["dea"] and ind["prev_macd_bar"] < 0 and ind["macd_bar"] >= 0:
        score += 15  # 剛形成金叉，強烈訊號
    elif ind["dif"] > ind["dea"] and ind["macd_bar"] > 0:
        score += 8
    elif ind["macd_bar"] > ind["prev_macd_bar"]:
        score += 3   # MACD 柱體擴大

    # 4. 布林通道下軌反彈
    last = ind["last_close"]
    lower = ind["lower_band"]
    upper = ind["upper_band"]
    mid   = ind["mid_band"]
    band_width = upper - lower
    if band_width > 0:
        pos = (last - lower) / band_width
        if pos < 0.2:
            score += 10  # 接近下軌，反彈概率高
        elif 0.2 <= pos < 0.4:
            score += 5

    # 5. 爆量（相對均量）
    vr = ind["vol_ratio"]
    if vr >= 3.0:
        score += 12  # 爆量突破，強訊號
    elif vr >= 2.0:
        score += 8
    elif vr >= 1.5:
        score += 4

    # 6. 近5日漲幅（不能太高，避免追高）
    ret5 = ind["ret5"]
    if -5 <= ret5 < 0:
        score += 5  # 略微回調，即將反彈
    elif 0 <= ret5 < 5:
        score += 3

    # === 法人面 (最高 30 分) ===
    if inst:
        foreign = inst.get("foreign", 0)
        trust   = inst.get("trust", 0)
        dealer  = inst.get("dealer", 0)

        if foreign > 1000:
            score += 10
        elif foreign > 500:
            score += 6
        elif foreign > 0:
            score += 3

        if trust > 200:
            score += 10
        elif trust > 50:
            score += 6
        elif trust > 0:
            score += 3

        if dealer > 0:
            score += 3

        # 三大法人同步買超
        if foreign > 0 and trust > 0 and dealer > 0:
            score += 7

    # === 當日量能與漲幅 (最高 20 分) ===
    day_vol = today_info.get("volume_lots", 0)
    day_chg = today_info.get("change_pct", 0)

    # 漲幅不太大但量大，隔日繼續強
    if 2 < day_chg <= 6:
        score += 5
    elif 0 < day_chg <= 2:
        score += 3
    elif day_chg > 6:
        score += 2  # 已漲太多，回調風險

    if day_vol > 50000:
        score += 8
    elif day_vol > 20000:
        score += 5
    elif day_vol > 10000:
        score += 3

    return round(score, 1)


# ─────────────────────────────────────────
# Step 6: 新聞情緒分析
# ─────────────────────────────────────────
import feedparser

# 各新聞類別的 Google News RSS 查詢關鍵字
# 英文版：廣泛國際財經新聞
NEWS_QUERIES_EN = {
    "trump_policy":    "Trump+tariff+trade+Taiwan",
    "taiwan_strait":   "Taiwan+Strait+China+military+PLA",
    "tsmc_semi":       "TSMC+semiconductor+chip+AI+revenue",
    "fed_rate":        "Federal+Reserve+interest+rate+inflation",
    "taiwan_economy":  "Taiwan+economy+export+GDP",
    "us_china":        "US+China+trade+war+sanction+technology",
}

# 繁中版：中央社(site:cna.com.tw) + 公視(site:news.pts.org.tw) 專屬查詢
# 使用 urllib 編碼，Google News 繁中版回傳較精準的台灣在地新聞
NEWS_QUERIES_ZH = {
    "cna_economy":  "site:cna.com.tw (台積電 OR 半導體 OR 關稅 OR 出口 OR 股市 OR AI晶片)",
    "cna_politics": "site:cna.com.tw (台海 OR 兩岸 OR 解放軍 OR 美台 OR 涉台 OR 統戰)",
    "pts_economy":  "site:news.pts.org.tw (台積電 OR 半導體 OR 股市 OR 台股 OR 關稅)",
    "pts_politics": "site:news.pts.org.tw (台海 OR 兩岸 OR 解放軍 OR 美台 OR 軍演)",
}

GOOGLE_RSS_EN = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en&num=15"
GOOGLE_RSS_ZH = "https://news.google.com/rss/search?q={q}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant&num=15"

_KEYWORDS_FILE = os.path.join(os.path.dirname(__file__), "keywords.json")


def load_sentiment_rules() -> list[tuple]:
    """從 keywords.json 載入情緒規則，若檔案不存在則 fallback 至內建規則。"""
    if os.path.exists(_KEYWORDS_FILE):
        with open(_KEYWORDS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return [(r["keyword"], r["score"], r["label"], r["category"])
                for r in data.get("rules", [])]
    return NEWS_SENTIMENT_RULES   # fallback

# 關鍵字情緒字典：{keyword: (score, label, category)}
# score: 正=對台股利多，負=利空；|score|越大影響越大
NEWS_SENTIMENT_RULES = [
    # ── Trump / 關稅 ──
    ("tariff exemption",         +20, "川普關稅豁免",      "trump"),
    ("tariff suspension",        +20, "川普暫停關稅",      "trump"),
    ("suspending tariff",        +18, "川普暫停關稅",      "trump"),
    ("tariff pause",             +18, "川普暫停關稅",      "trump"),
    ("tariff reduction",         +15, "關稅減免",          "trump"),
    ("trade deal",               +12, "貿易協議",          "trump"),
    ("tariff hike",              -20, "關稅加徵",          "trump"),
    ("new tariffs",              -18, "新增關稅",          "trump"),
    ("tariff increase",          -18, "關稅提高",          "trump"),
    ("trade war escalat",        -20, "貿易戰升級",        "trump"),
    ("tech ban",                 -15, "科技禁令",          "trump"),
    ("chip export ban",          -20, "晶片出口禁令",      "trump"),
    ("chip restriction",         -15, "晶片限制",          "trump"),
    ("export control",           -12, "出口管制",          "trump"),
    ("reciprocal tariff",        -15, "對等關稅",          "trump"),

    # ── 台海關係 ──
    ("taiwan invasion",          -40, "台海軍事入侵",      "strait"),
    ("military exercise taiwan", -30, "台海軍演",          "strait"),
    ("pla drill",                -25, "解放軍演習",        "strait"),
    ("taiwan blockade",          -35, "台海封鎖",          "strait"),
    ("cross-strait tension",     -20, "兩岸緊張",          "strait"),
    ("china military threat",    -18, "中國軍事威脅",      "strait"),
    ("taiwan strait conflict",   -30, "台海衝突",          "strait"),
    ("us arms sale taiwan",      +15, "美售台武器",        "strait"),
    ("us taiwan defense",        +12, "美台防衛合作",      "strait"),
    ("china abandon threat",     +10, "中國放棄威脅",      "strait"),
    ("abandon threat",           +10, "中國放棄威脅",      "strait"),
    ("taiwan independence",      -15, "台獨衝突風險",      "strait"),

    # ── TSMC / 半導體 ──
    ("tsmc record revenue",      +20, "台積電創新高",      "semi"),
    ("tsmc beat estimate",       +15, "台積電獲利超預期",  "semi"),
    ("ai chip demand",           +12, "AI 晶片需求強",     "semi"),
    ("tsmc expansion",           +10, "台積電擴產",        "semi"),
    ("semiconductor shortage",   +10, "晶片短缺利多",      "semi"),
    ("nvidia order",             +10, "輝達大單",          "semi"),
    ("tsmc cut forecast",        -15, "台積電下修",        "semi"),
    ("chip oversupply",          -12, "晶片供過於求",      "semi"),
    ("semiconductor downturn",   -15, "半導體下行",        "semi"),
    ("memory price drop",        -10, "記憶體跌價",        "semi"),

    # ── Fed / 利率 ──
    ("rate cut",                 +15, "Fed 降息",          "fed"),
    ("interest rate cut",        +15, "降息",              "fed"),
    ("dovish fed",               +12, "Fed 鴿派",          "fed"),
    ("fed pivot",                +12, "Fed 政策轉向",      "fed"),
    ("rate hike",                -15, "Fed 升息",          "fed"),
    ("interest rate hike",       -15, "升息壓力",          "fed"),
    ("hawkish fed",              -12, "Fed 鷹派",          "fed"),
    ("inflation surge",          -10, "通膨升溫",          "fed"),
    ("recession risk",           -15, "經濟衰退風險",      "fed"),

    # ── 台灣總體 ──
    ("taiwan gdp",               +10, "台灣 GDP 利多",     "tw_macro"),
    ("taiwan export growth",     +12, "台灣出口成長",      "tw_macro"),
    ("taiwan trade growth",      +12, "台灣貿易成長",      "tw_macro"),
    ("foreign investment taiwan",+10, "外資流入台灣",      "tw_macro"),
    ("taiwan downgrade",         -12, "台灣評等下調",      "tw_macro"),

    # ══════════════════════════════════════════
    # 繁中規則（中央社 / 公視 新聞用）
    # ══════════════════════════════════════════

    # ── 川普/關稅（繁中）──
    ("豁免關稅",     +20, "川普關稅豁免",      "trump"),
    ("暫停關稅",     +20, "川普暫停關稅",      "trump"),
    ("關稅豁免",     +20, "關稅豁免",          "trump"),
    ("關稅暫緩",     +18, "關稅暫緩",          "trump"),
    ("關稅減免",     +15, "關稅減免",          "trump"),
    ("貿易協議",     +12, "貿易協議",          "trump"),
    ("加徵關稅",     -20, "加徵關稅",          "trump"),
    ("關稅升",       -18, "關稅上升",          "trump"),
    ("對等關稅",     -15, "對等關稅",          "trump"),
    ("貿易戰升溫",   -20, "貿易戰升溫",        "trump"),
    ("晶片禁令",     -20, "晶片出口禁令",      "trump"),
    ("出口管制",     -12, "出口管制",          "trump"),
    ("科技制裁",     -15, "科技制裁",          "trump"),
    ("川普警告",     -10, "川普警告台灣",      "trump"),
    ("封鎖荷莫茲",   -12, "地緣衝突擴大",      "trump"),

    # ── 台海/兩岸（繁中）──
    ("解放軍入侵",   -40, "台海入侵",          "strait"),
    ("武力犯台",     -40, "武力犯台",          "strait"),
    ("台海封鎖",     -35, "台海封鎖",          "strait"),
    ("解放軍軍演",   -30, "解放軍演習",        "strait"),
    ("軍事演習",     -20, "軍事演習",          "strait"),
    ("台海緊張",     -20, "台海緊張",          "strait"),
    ("武裝衝突",     -25, "武裝衝突",          "strait"),
    ("涉台措施",     -10, "中國涉台統戰",      "strait"),
    ("統戰工具",     -12, "中國統戰措施",      "strait"),
    ("鄭習會",        -8, "兩岸政治角力",      "strait"),
    ("兩岸緊張",     -18, "兩岸緊張",          "strait"),
    ("美台軍售",     +15, "美台軍售",          "strait"),
    ("美台防衛",     +12, "美台防衛合作",      "strait"),
    ("友台",         +10, "友台訊號",          "strait"),
    ("反制中國",     +8,  "美國反制中國",      "strait"),
    ("美退將",        +5, "美方支持台灣",      "strait"),

    # ── TSMC/半導體（繁中）──
    ("台積電創新高",  +20, "台積電創新高",      "semi"),
    ("台積電強勁",    +15, "台積電業績強勁",    "semi"),
    ("台積電超預期",  +15, "台積電獲利超標",    "semi"),
    ("台積電擴產",    +10, "台積電擴產",        "semi"),
    ("ai晶片需求",    +12, "AI晶片需求旺",      "semi"),
    ("先進封裝",      +10, "先進封裝需求強",    "semi"),
    ("cowos",         +10, "CoWoS 需求旺",      "semi"),
    ("台積電下修",    -15, "台積電下修預期",    "semi"),
    ("晶片庫存",      -10, "晶片庫存過高",      "semi"),
    ("半導體下行",    -15, "半導體下行",        "semi"),

    # ── 台股/總經（繁中）──
    ("台股大漲",      +15, "台股大漲",          "tw_macro"),
    ("台股創新高",    +18, "台股創新高",        "tw_macro"),
    ("外資買超",      +12, "外資買超",          "tw_macro"),
    ("外資回流",      +12, "外資回流台股",      "tw_macro"),
    ("出口大增",      +12, "台灣出口大增",      "tw_macro"),
    ("gdp上修",       +10, "台灣GDP上修",       "tw_macro"),
    ("台股重挫",      -15, "台股重挫",          "tw_macro"),
    ("外資賣超",      -12, "外資賣超",          "tw_macro"),
    ("出口衰退",      -12, "台灣出口衰退",      "tw_macro"),

    # ── Fed/利率（繁中）──
    ("降息",          +15, "降息",              "fed"),
    ("暫停升息",      +12, "暫停升息",          "fed"),
    ("鴿派",          +10, "Fed鴿派",           "fed"),
    ("升息",          -15, "升息",              "fed"),
    ("鷹派",          -12, "Fed鷹派",           "fed"),
    ("通膨升溫",      -10, "通膨升溫",          "fed"),
    ("衰退風險",      -15, "衰退風險",          "fed"),

    # ── 台海/軍事（補充，繁中常見用語）──
    ("機艦",          -20, "中國軍機艦船繞台",  "strait"),
    ("台海周邊",      -20, "中國軍機艦船繞台",  "strait"),
    ("繞台",          -22, "中國軍機繞台",      "strait"),
    ("共機",          -22, "共機擾台",          "strait"),
    ("共艦",          -18, "共艦繞台",          "strait"),
    ("實彈演習",      -30, "中國實彈演習",      "strait"),
    ("封台",          -35, "封鎖台灣",          "strait"),
    ("兩岸統一",      -15, "兩岸統一政治壓力",  "strait"),
    ("武統",          -35, "武力統一",          "strait"),
    ("飛彈威脅",      -30, "飛彈威脅",          "strait"),

    # ── 台灣出口/總經（補充）──
    ("出口飆",        +18, "台灣出口大幅成長",  "tw_macro"),
    ("出口創高",      +18, "台灣出口創新高",    "tw_macro"),
    ("出口創新高",    +20, "台灣出口創歷史新高","tw_macro"),
    ("創歷年單月新高",+20, "台灣出口創歷史新高","tw_macro"),
    ("出口年增率",    +12, "台灣出口年增",      "tw_macro"),
    ("出口年增",      +10, "台灣出口年增",      "tw_macro"),
    ("出口衰退",      -12, "台灣出口衰退",      "tw_macro"),
    ("美關稅",        -12, "美國關稅衝擊台灣",  "trump"),

    # ── TSMC/科技（補充）──
    ("降低依賴台積電",  -8, "去台積電化風險",   "semi"),
    ("替代台積電",      -8, "競爭壓力",         "semi"),
    ("rapidus",         -5, "日本替代方案",      "semi"),
    ("台積電赴美",     +10, "台積電美國布局",    "semi"),
    ("台積電日本",      +8, "台積電海外布局",    "semi"),
    ("台積電德國",      +8, "台積電歐洲布局",    "semi"),
    ("ai超旺",         +15, "AI需求超旺",        "semi"),
    ("ai需求旺",       +12, "AI需求強勁",        "semi"),
]


def fetch_news_sentiment(hours_back: int = 48) -> dict:
    """
    抓取近 N 小時新聞（英文國際媒體 + 中央社 + 公視），進行情緒評分。

    回傳:
      score       : -100 ~ +100（正=利多，負=利空）
      items       : list of {"title", "source", "pub", "score", "label", "category", "url", "lang"}
      category_scores : 各類別小計
      summary     : 簡短文字說明
    """
    import urllib.parse
    _now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = _now_utc - timedelta(hours=hours_back)
    all_entries = []

    # ── 英文來源 ──
    for cat, q in NEWS_QUERIES_EN.items():
        url = GOOGLE_RSS_EN.format(q=q)
        try:
            feed = feedparser.parse(url)
            for entry in feed.get("entries", [])[:15]:
                pub_struct = entry.get("published_parsed")
                if pub_struct:
                    pub_dt = datetime(*pub_struct[:6])
                    if pub_dt < cutoff:
                        continue
                else:
                    pub_dt = _now_utc

                all_entries.append({
                    "title_raw": entry.get("title", ""),
                    "title":     entry.get("title", "").lower(),
                    "source":    entry.get("source", {}).get("title", ""),
                    "pub":       pub_dt.strftime("%m/%d %H:%M"),
                    "url":       entry.get("link", ""),
                    "cat":       cat,
                    "lang":      "en",
                })
        except Exception:
            pass

    # ── 繁中來源（中央社 + 公視）──
    for cat, q in NEWS_QUERIES_ZH.items():
        encoded_q = urllib.parse.quote(q)
        url = GOOGLE_RSS_ZH.format(q=encoded_q)
        try:
            feed = feedparser.parse(url)
            for entry in feed.get("entries", [])[:15]:
                pub_struct = entry.get("published_parsed")
                if pub_struct:
                    pub_dt = datetime(*pub_struct[:6])
                    if pub_dt < cutoff:
                        continue
                else:
                    pub_dt = _now_utc

                # 移除標題末尾的分類標籤與來源
                # e.g. "標題| 政治 - 中央社 CNA" → "標題"
                # e.g. "標題| 兩岸"               → "標題"
                raw_title = entry.get("title", "")
                clean_title = re.sub(
                    r"\s*[|｜]\s*(政治|財經|兩岸|社會|國際|科技|生活|產經|證券|地方|影劇|運動|教育).*$",
                    "", raw_title
                ).strip()
                clean_title = re.sub(r"\s*[-–]\s*(中央社|CNA|公視|PTS|PNN).*$", "", clean_title).strip()

                # 取來源標籤
                src = entry.get("source", {}).get("title", "")
                if not src:
                    if "cna.com.tw" in entry.get("link", ""):
                        src = "中央社 CNA"
                    elif "pts.org.tw" in entry.get("link", ""):
                        src = "公視新聞"

                all_entries.append({
                    "title_raw":   raw_title,
                    "title":       clean_title.lower(),
                    "title_zh":    clean_title,   # 繁中原文（供顯示）
                    "source":      src,
                    "pub":         pub_dt.strftime("%m/%d %H:%M"),
                    "url":         entry.get("link", ""),
                    "cat":         cat,
                    "lang":        "zh",
                })
        except Exception:
            pass

    # 去重（同標題不同 RSS 可能重複）
    seen = set()
    unique_entries = []
    for e in all_entries:
        key = e["title"][:50]
        if key not in seen:
            seen.add(key)
            unique_entries.append(e)

    # 載入最新規則（keywords.json 可能已被 auto_update_keywords.py 更新）
    active_rules = load_sentiment_rules()

    # 情緒評分（先做，供後續同事件去重使用）
    def score_entry(entry):
        title = entry["title"]
        best_score, best_label, best_cat = 0, "", ""
        for keyword, score, label, cat in active_rules:
            if keyword.lower() in title:
                if abs(score) > abs(best_score):
                    best_score, best_label, best_cat = score, label, cat
        return best_score, best_label, best_cat

    for e in unique_entries:
        s, l, c = score_entry(e)
        e["score"], e["label"], e["category"] = s, l, c

    # 同事件去重：同一類別 (category) + 同日 + 相似主題只保留最高分那則
    # 防止「涉台措施」14 篇全部計分，實際上是同一事件
    event_seen: dict = {}   # key = (category, date, keyword命中) → 最高分
    deduped = []
    for e in unique_entries:
        if e["score"] == 0:
            deduped.append(e)
            continue
        date_str = e["pub"][:5]   # "MM/DD"
        # 用命中的關鍵字前 4 字 + 日期 + 類別 作為事件 key
        event_key = (e["category"], date_str, e["label"][:6])
        if event_key not in event_seen:
            event_seen[event_key] = e
            deduped.append(e)
        else:
            # 已有同事件，若本則分數更大則替換
            existing = event_seen[event_key]
            if abs(e["score"]) > abs(existing["score"]):
                deduped.remove(existing)
                event_seen[event_key] = e
                deduped.append(e)
            # 否則直接丟棄（同事件不重複計分）

    unique_entries = deduped

    # 情緒評分（已在去重前評過分，直接彙總）
    scored = []
    category_scores = {}

    for entry in unique_entries:
        if entry["score"] != 0:
            scored.append(entry)
            category_scores[entry["category"]] = (
                category_scores.get(entry["category"], 0) + entry["score"]
            )

    # 加權總分（避免單類堆疊，各類別設上下限）
    total_score = 0
    for cat, s in category_scores.items():
        capped = max(-40, min(40, s))  # 每個類別最多 ±40
        total_score += capped

    total_score = max(-100, min(100, total_score))

    # 排序：分數絕對值大的優先，同分取最新
    scored_sorted = sorted(scored, key=lambda x: (-abs(x["score"]), x["pub"]), reverse=False)
    scored_sorted = sorted(scored_sorted, key=lambda x: abs(x["score"]), reverse=True)

    # 摘要說明
    if total_score >= 30:
        summary = "新聞面整體偏多，多項利多訊號共振"
    elif total_score >= 10:
        summary = "新聞面溫和偏多，有正面催化劑"
    elif total_score <= -30:
        summary = "新聞面整體偏空，多項利空訊號出現"
    elif total_score <= -10:
        summary = "新聞面溫和偏空，存在不確定風險"
    else:
        summary = "新聞面中性，無明顯方向性訊號"

    return {
        "score":            total_score,
        "items":            scored_sorted[:12],   # 最多顯示 12 則
        "all_count":        len(unique_entries),
        "scored_count":     len(scored),
        "category_scores":  category_scores,
        "summary":          summary,
    }


# ─────────────────────────────────────────
# Step 7: 大盤趨勢預測
# ─────────────────────────────────────────
ETF_BULL = "00631L"   # 元大台灣50正2（2x 多方槓桿）
ETF_BEAR = "0050"     # 元大台灣50（避險/保守操作）


# ─────────────────────────────────────────
# 外部訊號 A：Polymarket + VIX 恐慌指數
# ─────────────────────────────────────────
# Polymarket：批量抓取後以關鍵字過濾，找台股相關地緣/政治市場
POLY_KEYWORDS = {
    "strait": {
        # 用完整詞組避免 "pla" 匹配到 "playboi" 等無關詞
        "terms":     ["taiwan", "china invades", "china invade taiwan", "invasion of taiwan",
                      "chinese military", "strait of taiwan"],
        "direction": -1,   # 台海衝突 → 台股極度利空
        "weight":    2.5,
        "label":     "台海衝突概率",
    },
    "trump": {
        "terms":     ["trump tariff", "tariff on", "trade war", "trade tariff",
                      "import tariff", "reciprocal tariff"],
        "direction": -1,   # 川普關稅 → 台股利空
        "weight":    1.2,
        "label":     "川普/關稅風險",
    },
    "fed": {
        "terms":     ["federal reserve rate", "fed rate cut", "fed rate hike",
                      "fomc rate", "rate cut in 20"],
        "direction": +1,   # 降息 → 台股利多（若搜到降息市場）
        "weight":    1.2,
        "label":     "Fed 利率方向",
    },
    "recession": {
        "terms":     ["us recession", "american recession", "gdp recession",
                      "economic recession"],
        "direction": -1,
        "weight":    1.5,
        "label":     "美國衰退概率",
    },
}


def fetch_polymarket_signals() -> dict:
    """
    查詢 Polymarket 公開預測市場 + VIX 恐慌指數，轉換為宏觀情緒分數。

    Polymarket：
      - 批量抓取 100 個活躍市場，以關鍵字過濾台股相關市場
      - Yes 機率偏離 50% 越多，分數越高（方向依利多/利空設定）

    VIX（CBOE Volatility Index，透過 yfinance）：
      - VIX > 30：市場極度恐慌 → -10
      - VIX 20-30：市場警戒 → -5
      - VIX < 15：市場平靜 → +8

    回傳 {"score": int, "items": list, "vix": float|None, "available": bool}
    """
    result = {"score": 0, "items": [], "vix": None, "available": False}

    # ── A1. Polymarket ──
    try:
        resp = requests.get(
            "https://gamma-api.polymarket.com/markets",
            params={"limit": 100, "active": "true"},
            timeout=8,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if resp.status_code == 200:
            markets = resp.json() if isinstance(resp.json(), list) else []
            seen = set()
            for m in markets:
                question = (m.get("question") or "").lower()
                cid = m.get("conditionId", "")
                if cid in seen:
                    continue

                for cat, cfg in POLY_KEYWORDS.items():
                    if not any(kw in question for kw in cfg["terms"]):
                        continue
                    try:
                        raw = m.get("outcomePrices", "[]")
                        prices = json.loads(raw) if isinstance(raw, str) else raw
                        yes_prob = float(prices[0]) if prices else 0.5
                    except Exception:
                        yes_prob = 0.5

                    deviation = yes_prob - 0.5
                    signal = round(deviation * cfg["direction"] * cfg["weight"] * 20)
                    result["items"].append({
                        "question":     m.get("question", "")[:70],
                        "yes_prob":     round(yes_prob * 100, 1),
                        "signal_score": signal,
                        "category":     cat,
                        "label":        cfg["label"],
                    })
                    result["score"] += signal
                    result["available"] = True
                    seen.add(cid)
                    break   # 每市場只歸類一個類別
    except Exception as e:
        result["poly_error"] = str(e)

    # ── A2. VIX 恐慌指數（yfinance，已有套件）──
    try:
        vix_hist = yf.Ticker("^VIX").history(period="5d")
        if not vix_hist.empty:
            vix_val = vix_hist["Close"].iloc[-1]
            result["vix"] = round(float(vix_val), 1)
            result["available"] = True

            if vix_val > 35:
                result["score"] -= 12
                result["items"].append({
                    "label": "VIX 恐慌指數", "question": f"VIX = {vix_val:.1f}（極度恐慌，>35）",
                    "yes_prob": None, "signal_score": -12, "category": "tw_macro",
                })
            elif vix_val > 25:
                result["score"] -= 6
                result["items"].append({
                    "label": "VIX 恐慌指數", "question": f"VIX = {vix_val:.1f}（警戒區，>25）",
                    "yes_prob": None, "signal_score": -6, "category": "tw_macro",
                })
            elif vix_val < 15:
                result["score"] += 8
                result["items"].append({
                    "label": "VIX 恐慌指數", "question": f"VIX = {vix_val:.1f}（市場平靜，<15）",
                    "yes_prob": None, "signal_score": +8, "category": "tw_macro",
                })
            else:
                result["items"].append({
                    "label": "VIX 恐慌指數", "question": f"VIX = {vix_val:.1f}（正常區間）",
                    "yes_prob": None, "signal_score": 0, "category": "tw_macro",
                })
    except Exception as e:
        result["vix_error"] = str(e)

    result["score"] = max(-25, min(25, result["score"]))
    return result


# ─────────────────────────────────────────
# 外部訊號 B：AI-Trader Market-Intel
# ─────────────────────────────────────────
def fetch_market_intel_signals() -> dict:
    """
    查詢 AI-Trader market-intel API 取得宏觀訊號快照。
    回傳 {"score": int, "bullish_ratio": float, "items": list, "available": bool}
    """
    result = {"score": 0, "bullish_ratio": 0.5, "items": [], "available": False}
    try:
        headers = {"User-Agent": "Mozilla/5.0"}

        # 1. 宏觀訊號比率 + 逐條訊號說明
        resp = requests.get(
            "https://ai4trade.ai/api/market-intel/macro-signals",
            timeout=8, headers=headers,
        )
        if resp.status_code == 200:
            data = resp.json()
            bullish = data.get("bullish_count") or 0
            total   = data.get("total_count")   or 0
            verdict = (data.get("verdict") or "").lower()   # "bullish"/"bearish"/"neutral"

            if total > 0:
                ratio = bullish / total
                result["bullish_ratio"] = round(ratio, 2)
                result["verdict"] = verdict

                if ratio >= 0.65:
                    result["score"] += 10
                elif ratio <= 0.35:
                    result["score"] -= 10

                result["items"].append(
                    f"整體判斷：{verdict.upper()} — {bullish}/{total} 個多頭訊號（{ratio:.0%}）"
                )

                # 加入逐條訊號說明（優先顯示中文）
                for sig in data.get("signals", [])[:5]:
                    status = sig.get("status", "")
                    label  = sig.get("label_zh") or sig.get("label", "")
                    expl   = sig.get("explanation_zh") or sig.get("explanation", "")
                    icon   = "+" if status == "bullish" else "-" if status == "bearish" else "~"
                    result["items"].append(f"  [{icon}] {label}：{expl[:60]}")

                result["available"] = True

        # 2. 新聞快照（macro 類別，若有內容則顯示）
        resp2 = requests.get(
            "https://ai4trade.ai/api/market-intel/news",
            params={"category": "macro", "limit": 5},
            timeout=8, headers=headers,
        )
        if resp2.status_code == 200:
            news_data = resp2.json()
            items = news_data if isinstance(news_data, list) else news_data.get("items", [])
            for item in items[:5]:
                sentiment = (item.get("sentiment") or "").lower()
                headline  = item.get("headline") or item.get("title") or ""
                if sentiment == "bullish":
                    result["score"] += 2
                elif sentiment == "bearish":
                    result["score"] -= 2
                if headline:
                    result["items"].append(f"  [新聞/{sentiment}] {headline[:65]}")
            if items:
                result["available"] = True

    except Exception as e:
        result["error"] = str(e)

    result["score"] = max(-15, min(15, result["score"]))
    return result


def predict_market_trend() -> dict:
    """
    分析台股加權指數 (^TWII) + 美股三大指數，
    預測隔日是否有 5%+ 漲幅，或一週內持續上漲趨勢。

    回傳 dict:
      direction  : "strong_bull" | "bull" | "neutral" | "bear" | "strong_bear"
      score      : -100 ~ +100（正=偏多，負=偏空）
      next_day_5pct_prob : 隔日 5%+ 漲幅概率描述
      weekly_trend       : 一週趨勢描述
      etf_action         : {"code", "name", "action", "reason"}
      signals            : list of signal strings
      twii               : TWII 最新技術數據
      us_markets         : US 指數摘要
    """
    signals = []
    score = 0

    # ── 1. 台股加權指數 ──
    twii_hist = None
    twii_data = {}
    try:
        twii = yf.Ticker("^TWII")
        twii_hist = twii.history(period="3mo")
        twii_hist.index = twii_hist.index.tz_localize(None)

        close = twii_hist["Close"]
        volume = twii_hist["Volume"]

        last  = close.iloc[-1]
        prev  = close.iloc[-2]
        day_chg_pct = (last / prev - 1) * 100

        ma5  = close.rolling(5).mean().iloc[-1]
        ma20 = close.rolling(20).mean().iloc[-1]
        ma60 = close.rolling(60).mean().iloc[-1] if len(close) >= 60 else None

        # RSI
        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = (100 - 100 / (1 + gain / (loss + 1e-9))).iloc[-1]

        # MACD
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        dif = ema12 - ema26
        dea = dif.ewm(span=9, adjust=False).mean()
        dif_val  = dif.iloc[-1]
        dea_val  = dea.iloc[-1]
        dif_prev = dif.iloc[-2]
        dea_prev = dea.iloc[-2]

        # 布林通道
        ma20_s = close.rolling(20).mean()
        std20  = close.rolling(20).std()
        upper  = (ma20_s + 2 * std20).iloc[-1]
        lower  = (ma20_s - 2 * std20).iloc[-1]
        bb_pos = (last - lower) / (upper - lower + 1e-9)

        # 近 5 日 / 10 日動量
        ret5  = (last / close.iloc[-6]  - 1) * 100 if len(close) >= 6  else 0
        ret10 = (last / close.iloc[-11] - 1) * 100 if len(close) >= 11 else 0

        # 成交量比
        vol_ratio = volume.iloc[-1] / (volume.rolling(20).mean().iloc[-1] + 1e-9)

        twii_data = {
            "last": round(last, 1),
            "day_chg_pct": round(day_chg_pct, 2),
            "ma5": round(ma5, 1),
            "ma20": round(ma20, 1),
            "ma60": round(ma60, 1) if ma60 else None,
            "rsi": round(rsi, 1),
            "dif": round(dif_val, 2),
            "dea": round(dea_val, 2),
            "upper": round(upper, 1),
            "lower": round(lower, 1),
            "bb_pos": round(bb_pos, 2),
            "ret5": round(ret5, 2),
            "ret10": round(ret10, 2),
            "vol_ratio": round(vol_ratio, 2),
        }

        # ── 評分：均線 ──
        if ma5 > ma20:
            score += 15
            signals.append("TWII MA5 > MA20（短線多頭排列）")
        else:
            score -= 15
            signals.append("TWII MA5 < MA20（短線空頭排列）")

        if ma60 and ma20 > ma60:
            score += 10
            signals.append("TWII MA20 > MA60（中長線偏多）")
        elif ma60 and ma20 < ma60:
            score -= 10
            signals.append("TWII MA20 < MA60（中長線偏空）")

        # ── 評分：RSI ──
        if 50 <= rsi <= 70:
            score += 12
            signals.append(f"TWII RSI={rsi:.1f}（健康多頭區）")
        elif rsi > 70:
            score += 3
            signals.append(f"TWII RSI={rsi:.1f}（超買，短線注意回調）")
        elif 30 <= rsi < 50:
            score -= 8
            signals.append(f"TWII RSI={rsi:.1f}（弱勢區，偏空）")
        else:
            score += 8  # 極度超賣，反彈機率升高
            signals.append(f"TWII RSI={rsi:.1f}（極度超賣，反彈訊號）")

        # ── 評分：MACD ──
        golden_cross = (dif_prev < dea_prev) and (dif_val >= dea_val)
        death_cross  = (dif_prev > dea_prev) and (dif_val <= dea_val)

        if golden_cross:
            score += 20
            signals.append("TWII MACD 剛形成金叉（強力買進訊號）")
        elif dif_val > dea_val:
            score += 10
            signals.append(f"TWII MACD 多頭（DIF={dif_val:.1f} > DEA={dea_val:.1f}）")
        elif death_cross:
            score -= 20
            signals.append("TWII MACD 剛形成死叉（強力賣出訊號）")
        else:
            score -= 10
            signals.append(f"TWII MACD 空頭（DIF={dif_val:.1f} < DEA={dea_val:.1f}）")

        # ── 評分：布林通道位置 ──
        if bb_pos < 0.2:
            score += 15
            signals.append(f"TWII 接近布林下軌（位置 {bb_pos:.0%}），反彈空間大")
        elif bb_pos > 0.85:
            score -= 8
            signals.append(f"TWII 接近布林上軌（位置 {bb_pos:.0%}），短線壓力")
        else:
            score += 5

        # ── 評分：動量 ──
        if ret5 > 5:
            score += 10
            signals.append(f"TWII 近5日強勢上漲 +{ret5:.1f}%，動能延續中")
        elif ret5 > 0:
            score += 5
        elif ret5 < -5:
            score -= 10
            signals.append(f"TWII 近5日下跌 {ret5:.1f}%，空頭壓力")

        # ── 評分：當日漲幅（動能延續判斷）──
        if day_chg_pct > 3:
            score += 8
            signals.append(f"TWII 當日大漲 +{day_chg_pct:.1f}%，隔日動能可期")
        elif day_chg_pct > 0:
            score += 3
        elif day_chg_pct < -3:
            score -= 8
            signals.append(f"TWII 當日大跌 {day_chg_pct:.1f}%，注意恐慌蔓延")

        # ── 評分：爆量 ──
        if vol_ratio > 1.8:
            score += 8
            signals.append(f"TWII 爆量（量比 {vol_ratio:.1f}x），主力介入明顯")

    except Exception as e:
        signals.append(f"TWII 資料抓取失敗：{e}")

    # ── 2. 美股三大指數（前收盤，台股重要參考）──
    us_data = {}
    us_tickers = {"S&P500": "^GSPC", "NASDAQ": "^IXIC", "Dow Jones": "^DJI"}
    us_total_chg = 0
    us_count = 0

    for name, sym in us_tickers.items():
        try:
            t = yf.Ticker(sym)
            h = t.history(period="5d")
            h.index = h.index.tz_localize(None)
            if len(h) >= 2:
                last_us  = h["Close"].iloc[-1]
                prev_us  = h["Close"].iloc[-2]
                chg_pct  = (last_us / prev_us - 1) * 100
                us_data[name] = {"close": round(last_us, 1), "chg_pct": round(chg_pct, 2)}
                us_total_chg += chg_pct
                us_count += 1
        except Exception:
            us_data[name] = {"close": None, "chg_pct": None}

    if us_count > 0:
        us_avg_chg = us_total_chg / us_count
        if us_avg_chg > 2:
            score += 15
            signals.append(f"美股三大指數平均漲 +{us_avg_chg:.1f}%（台股跟漲動能強）")
        elif us_avg_chg > 0.5:
            score += 7
            signals.append(f"美股小幅收紅 +{us_avg_chg:.1f}%（台股溫和正面）")
        elif us_avg_chg < -2:
            score -= 15
            signals.append(f"美股三大指數平均跌 {us_avg_chg:.1f}%（台股開低壓力大）")
        elif us_avg_chg < -0.5:
            score -= 7
            signals.append(f"美股小幅收黑 {us_avg_chg:.1f}%（台股偏保守）")

    # ── 3. 新聞情緒分析 ──
    news = fetch_news_sentiment(hours_back=48)
    news_score = news["score"]

    # 新聞分數以 30% 權重加入大盤評分（技術面 70% + 新聞面 30%）
    news_contribution = round(news_score * 0.30)
    score += news_contribution

    if news_contribution >= 6:
        signals.append(f"新聞面偏多（{news['summary']}，貢獻 +{news_contribution}）")
    elif news_contribution <= -6:
        signals.append(f"新聞面偏空（{news['summary']}，貢獻 {news_contribution}）")
    else:
        signals.append(f"新聞面中性（{news['summary']}）")

    # 台海緊張特別處理（直接強制覆蓋）
    strait_score = news["category_scores"].get("strait", 0)
    if strait_score <= -30:
        score -= 20
        signals.append("⚠️ 台海局勢高度緊張，市場恐慌風險大幅上升")
    elif strait_score <= -15:
        score -= 10
        signals.append("⚠️ 台海關係出現緊張訊號，注意地緣政治風險")

    # ── 4. 外部訊號：Polymarket + AI-Trader Market-Intel ──
    ext_signals = {"polymarket": {}, "market_intel": {}, "combined_score": 0}
    try:
        poly  = fetch_polymarket_signals()
        intel = fetch_market_intel_signals()

        # 合併：Polymarket 60%、Market-Intel 40%
        combined = round(poly["score"] * 0.6 + intel["score"] * 0.4)
        combined = max(-20, min(20, combined))
        score += combined

        ext_signals = {
            "polymarket":    poly,
            "market_intel":  intel,
            "combined_score": combined,
        }

        if combined >= 5:
            signals.append(
                f"外部市場共識偏多（Polymarket+MarketIntel 貢獻 +{combined}）"
            )
        elif combined <= -5:
            signals.append(
                f"外部市場共識偏空（Polymarket+MarketIntel 貢獻 {combined}）"
            )
        else:
            signals.append(f"外部市場訊號中性（貢獻 {combined:+d}）")

        # Polymarket 台海市場特別處理（高概率觸發額外懲罰）
        for item in poly.get("items", []):
            if item.get("category") == "strait" and item.get("yes_prob", 0) > 40:
                score -= 15
                signals.append(
                    f"⚠️ Polymarket 台海衝突市場概率 {item['yes_prob']}%，地緣風險顯著"
                )
                break

    except Exception as e:
        signals.append(f"外部訊號載入失敗（{e}），僅使用技術面+新聞面")

    # ── 5. 綜合判斷 ──
    score = max(-100, min(100, score))

    # 隔日漲/跌 5% 概率（雙向）
    if score >= 60:
        rise_5pct = "高（多重強訊號共振，跳空大漲可能性明顯）"
    elif score >= 40:
        rise_5pct = "中（偏多，需配合外資持續回補）"
    elif score >= 15:
        rise_5pct = "低（小幅上漲較可能，難達 5%）"
    else:
        rise_5pct = "極低"

    if score <= -60:
        fall_5pct = "高（多重空頭訊號，重挫風險大）"
    elif score <= -40:
        fall_5pct = "中（偏空，下跌風險明顯）"
    elif score <= -15:
        fall_5pct = "低（輕微偏空，小跌為主）"
    else:
        fall_5pct = "極低"

    # 一週趨勢
    if score >= 50:
        weekly = "一週偏多：均線多頭排列 + MACD 動能向上，持續上漲趨勢明確"
    elif score >= 20:
        weekly = "一週溫和偏多：指數處於整理後醞釀上攻階段"
    elif score >= -20:
        weekly = "一週方向不明：觀望等待訊號更明確"
    elif score >= -50:
        weekly = "一週偏空：短線弱勢，注意支撐是否守住"
    else:
        weekly = "一週空頭明確：建議減碼避險"

    # 方向判定
    if score >= 50:
        direction = "strong_bull"
    elif score >= 20:
        direction = "bull"
    elif score <= -50:
        direction = "strong_bear"
    elif score <= -20:
        direction = "bear"
    else:
        direction = "neutral"

    # ETF 建議
    if direction in ("strong_bull", "bull"):
        etf_action = {
            "code":   ETF_BULL,
            "name":   "元大台灣50正2（2x槓桿多方）",
            "action": "買進" if direction == "bull" else "強力買進",
            "reason": f"大盤多頭訊號明確（評分 {score:+d}），{ETF_BULL} 可放大漲幅收益",
        }
    elif direction in ("strong_bear", "bear"):
        etf_action = {
            "code":   ETF_BEAR,
            "name":   "0050 元大台灣50（保守避險）",
            "action": "買進" if direction == "bear" else "強力買進",
            "reason": f"大盤空頭訊號出現（評分 {score:+d}），轉持 {ETF_BEAR} 元大台灣50 降低風險敞口",
        }
    else:
        etf_action = {
            "code":   None,
            "name":   None,
            "action": "觀望",
            "reason": f"大盤方向不明（評分 {score:+d}），建議等待更清晰訊號後再進場",
        }

    return {
        "direction":        direction,
        "score":            score,
        "rise_5pct_prob":   rise_5pct,
        "fall_5pct_prob":   fall_5pct,
        "weekly_trend":     weekly,
        "etf_action":         etf_action,
        "signals":            signals,
        "twii":               twii_data,
        "us_markets":         us_data,
        "news":               news,
        "external_signals":   ext_signals,
    }


# ─────────────────────────────────────────
# Step 6: 主程式
# ─────────────────────────────────────────
def main():
    print(f"\n{'='*60}")
    print(f" 台股前百大交易量 — 隔日暴漲潛力分析")
    print(f" 分析基準日：{TRADE_DATE_FMT}")
    print(f"{'='*60}\n")

    print("► 抓取 TWSE 前百大交易量股票...")
    top100 = fetch_top100_by_volume(TRADE_DATE)
    print(f"  取得 {len(top100)} 支個股\n")

    print("► 大盤趨勢預測（TWII + 美股）...")
    market = predict_market_trend()
    direction_label = {
        "strong_bull": "強力多頭",
        "bull":        "偏多",
        "neutral":     "盤整觀望",
        "bear":        "偏空",
        "strong_bear": "強力空頭",
    }.get(market["direction"], "不明")
    etf = market["etf_action"]
    print(f"  大盤評分：{market['score']:+d} ｜ 方向：{direction_label}")
    if etf["code"]:
        print(f"  ETF 建議：{etf['action']} {etf['code']} ({etf['name']})")
    else:
        print(f"  ETF 建議：{etf['action']}")
    print()

    print("► 抓取三大法人籌碼...")
    inst_all = fetch_institutional(TRADE_DATE)
    print(f"  取得 {len(inst_all)} 支法人資料\n")

    results = []
    print("► 計算技術指標與評分 (共100支)...")

    for idx, row in top100.iterrows():
        code = row["code"]
        hist = fetch_history(code)
        if hist is None:
            continue

        try:
            ind = calc_indicators(hist)
        except Exception:
            continue

        inst = inst_all.get(code, {})
        today_info = {
            "volume_lots": row["volume_lots"],
            "change_pct": row["change_pct"],
        }

        surge_score = score_surge_potential(ind, inst, today_info)

        results.append({
            "rank_vol": idx + 1,
            "code": code,
            "name": row.get("name", ""),
            "close": ind["last_close"],
            "change_pct": row["change_pct"],
            "volume_lots": int(row["volume_lots"]),
            "vol_ratio": round(ind["vol_ratio"], 2),
            "rsi": round(ind["rsi"], 1),
            "ma5": round(ind["ma5"], 2),
            "ma20": round(ind["ma20"], 2),
            "dif": round(ind["dif"], 3),
            "dea": round(ind["dea"], 3),
            "macd_bar": round(ind["macd_bar"], 3),
            "upper": round(ind["upper_band"], 2),
            "lower": round(ind["lower_band"], 2),
            "ret5": round(ind["ret5"], 2),
            "foreign": inst.get("foreign", "N/A"),
            "trust": inst.get("trust", "N/A"),
            "dealer": inst.get("dealer", "N/A"),
            "surge_score": surge_score,
        })

        if (idx + 1) % 20 == 0:
            print(f"  已分析 {idx + 1}/100...")

    print(f"\n  分析完成，有效股票數：{len(results)}")

    # 排序取前 10
    df_result = pd.DataFrame(results).sort_values("surge_score", ascending=False).head(10).reset_index(drop=True)
    return df_result, results, market


def generate_report(df_top10: pd.DataFrame, all_results: list, market: dict = None) -> str:
    lines = []
    lines.append(f"# 台股前百大交易量 — 隔日暴漲潛力 TOP 10")
    lines.append(f"**分析基準日**：{TRADE_DATE_FMT}　｜　**預測目標日**：2026-04-11（下一交易日）")
    lines.append("")
    lines.append("> ⚠️ 本報告僅供參考，不構成投資建議，最終決策請自行判斷。")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 大盤趨勢預測區塊
    if market:
        twii = market.get("twii", {})
        us   = market.get("us_markets", {})
        etf  = market.get("etf_action", {})
        direction_zh = {
            "strong_bull": "強力多頭",
            "bull":        "偏多",
            "neutral":     "盤整觀望",
            "bear":        "偏空",
            "strong_bear": "強力空頭",
        }.get(market["direction"], "不明")
        score = market["score"]
        score_bar = "█" * (abs(score) // 10) + "░" * (10 - abs(score) // 10)
        score_sign = "+" if score >= 0 else ""

        lines.append("## 大盤趨勢預測")
        lines.append("")
        lines.append(f"| 項目 | 數值 |")
        lines.append(f"|------|------|")
        lines.append(f"| 大盤方向 | **{direction_zh}** |")
        lines.append(f"| 綜合評分 | `{score_sign}{score}` （{score_bar}）|")
        lines.append(f"| 隔日漲 5%+ 概率 | {market['rise_5pct_prob']} |")
        lines.append(f"| 隔日跌 5%+ 概率 | {market['fall_5pct_prob']} |")
        lines.append(f"| 一週趨勢預測 | {market['weekly_trend']} |")
        lines.append("")

        if twii:
            lines.append("### 台股加權指數（TWII）")
            lines.append(f"- 最新收盤：**{twii.get('last', 'N/A')}**（當日 {twii.get('day_chg_pct', 0):+.2f}%）")
            lines.append(f"- MA5/MA20/MA60：{twii.get('ma5')} / {twii.get('ma20')} / {twii.get('ma60', 'N/A')}")
            lines.append(f"- RSI(14)：{twii.get('rsi')}　｜　MACD DIF/DEA：{twii.get('dif')} / {twii.get('dea')}")
            lines.append(f"- 布林通道位置：{twii.get('bb_pos', 0):.0%}（0%=下軌，100%=上軌）")
            lines.append(f"- 近5日漲幅：{twii.get('ret5', 0):+.2f}%　｜　近10日：{twii.get('ret10', 0):+.2f}%")
            lines.append(f"- 成交量比：{twii.get('vol_ratio', 0):.1f}x")
            lines.append("")

        if us:
            lines.append("### 美股三大指數（前收盤）")
            for name, d in us.items():
                if d.get("close"):
                    lines.append(f"- **{name}**：{d['close']:,}（{d['chg_pct']:+.2f}%）")
            lines.append("")

        lines.append("### 訊號清單")
        for sig in market.get("signals", []):
            icon = "🟢" if any(k in sig for k in ["多頭", "金叉", "強勢", "漲", "偏多", "超賣", "反彈"]) else "🔴"
            lines.append(f"- {icon} {sig}")
        lines.append("")

        # 新聞情緒分析區塊
        news = market.get("news", {})
        if news:
            cat_zh = {
                "trump":     "川普/關稅",
                "strait":    "台海局勢",
                "semi":      "半導體/TSMC",
                "fed":       "Fed/利率",
                "tw_macro":  "台灣總體",
                "us_china":  "美中關係",
            }
            lines.append("### 新聞情緒分析")
            lines.append(f"- **新聞評分**：{news['score']:+d}　｜　{news['summary']}")
            lines.append(f"- 掃描新聞：{news['all_count']} 則，有情緒影響：{news['scored_count']} 則")
            lines.append("")

            if news.get("category_scores"):
                lines.append("**各類別評分：**")
                for cat, s in sorted(news["category_scores"].items(), key=lambda x: abs(x[1]), reverse=True):
                    bar = "+" * max(0, s // 5) if s > 0 else "-" * max(0, abs(s) // 5)
                    lines.append(f"- {cat_zh.get(cat, cat)}：{s:+d}　`{bar}`")
                lines.append("")

            if news.get("items"):
                lines.append("**重要新聞（按影響力排序）：**")
                lines.append("")
                lines.append("| 影響 | 時間 | 來源 | 標題 |")
                lines.append("|------|------|------|------|")
                for item in news["items"][:10]:
                    icon = "🟢" if item["score"] > 0 else "🔴"
                    score_str = f"{icon} {item['score']:+d}"
                    # 繁中新聞優先顯示中文標題
                    display_title = item.get("title_zh") or item["title_raw"]
                    title_short = display_title[:58] + ("…" if len(display_title) > 58 else "")
                    src_label = item["source"][:18]
                    lines.append(f"| {score_str} | {item['pub']} | {src_label} | {title_short} |")
                lines.append("")

        # 外部訊號區塊（Polymarket + Market-Intel）
        ext = market.get("external_signals", {})
        poly_data  = ext.get("polymarket", {})
        intel_data = ext.get("market_intel", {})
        ext_score  = ext.get("combined_score", 0)

        if poly_data.get("available") or intel_data.get("available"):
            lines.append("### 外部市場共識訊號")
            lines.append(
                f"- **綜合貢獻分數**：{ext_score:+d}"
                f"（Polymarket {poly_data.get('score', 0):+d} × 60%"
                f" + MarketIntel {intel_data.get('score', 0):+d} × 40%）"
            )
            lines.append("")

            # Polymarket + VIX 表格
            if poly_data.get("items"):
                vix_val = poly_data.get("vix")
                vix_str = f"VIX {vix_val}" if vix_val else ""
                lines.append(
                    f"**Polymarket 預測市場 + VIX 恐慌指數**"
                    + (f"（{vix_str}）" if vix_str else "") + "："
                )
                lines.append("")
                lines.append("| 類別 | 指標/問題 | Yes 概率 | 訊號分 |")
                lines.append("|------|-----------|----------|--------|")
                for item in poly_data["items"]:
                    prob = f"{item['yes_prob']}%" if item.get("yes_prob") is not None else "N/A"
                    icon = "🟢" if item["signal_score"] > 0 else "🔴" if item["signal_score"] < 0 else "⚪"
                    lines.append(
                        f"| {item['label']} | {item['question'][:52]} "
                        f"| {prob} | {icon} {item['signal_score']:+d} |"
                    )
                lines.append("")

            # Market-Intel 清單
            if intel_data.get("items"):
                ratio   = intel_data.get("bullish_ratio", 0.5)
                verdict = (intel_data.get("verdict") or "").upper()
                lines.append(
                    f"**AI-Trader Market-Intel**"
                    f"（{verdict}，多頭比率 {ratio:.0%}，評分 {intel_data.get('score', 0):+d}）："
                )
                for it in intel_data["items"]:
                    lines.append(f"- {it}")
                lines.append("")

        lines.append("### ETF 操作建議")
        if etf.get("code"):
            lines.append(f"**建議：{etf['action']} [{etf['code']}] {etf['name']}**")
        else:
            lines.append(f"**建議：{etf['action']}**")
        lines.append(f"> {etf['reason']}")
        lines.append("")
        lines.append("---")
        lines.append("")

    # 個股分析樣本說明
    lines.append("## 大盤環境摘要")
    lines.append("- **分析樣本**：TWSE 全市場 1350 支個股，依成交量(張)取前 100 支個股進行篩選")
    lines.append("")
    lines.append("---")
    lines.append("")

    # TOP 10 表格
    lines.append("## TOP 10 暴漲潛力股一覽")
    lines.append("")
    lines.append("| 排名 | 代碼 | 名稱 | 收盤 | 當日漲幅 | 成交量(張) | 評分 |")
    lines.append("|------|------|------|------|---------|-----------|------|")

    for i, row in df_top10.iterrows():
        lines.append(
            f"| {i+1} | {row['code']} | {row.get('name','')} | {row['close']:.2f} | {row['change_pct']:+.2f}% "
            f"| {row['volume_lots']:,} | **{row['surge_score']}** |"
        )

    lines.append("")
    lines.append("---")
    lines.append("")

    # 個股詳細分析
    lines.append("## 個股詳細分析")
    lines.append("")

    reason_templates = {
        "vol_explosion": "爆量突破（量比 {vr:.1f}x），顯示主力積極介入，短線動能強烈。",
        "macd_golden": "MACD 剛形成金叉（DIF={dif:.3f} > DEA={dea:.3f}），買盤力道確認。",
        "rsi_rebound": "RSI({rsi:.1f}) 處於超賣後回彈區間，短線有強勁反彈動能。",
        "bb_lower": "股價接近布林通道下軌（下軌={lower:.2f}），技術面反彈訊號明確。",
        "ma_bullish": "均線多頭排列（MA5={ma5:.2f} > MA20={ma20:.2f}），趨勢向上。",
        "inst_buy": "三大法人同步買超（外資 {foreign:,}張 / 投信 {trust:,}張），籌碼集中。",
        "foreign_buy": "外資大舉買超 {foreign:,} 張，法人看好後市。",
        "trust_buy": "投信買超 {trust:,} 張，資金持續流入。",
        "moderate_gain": "當日溫和上漲 {chg:.2f}%，未過熱，隔日有機會繼續強攻。",
    }

    for i, row in df_top10.iterrows():
        name_str = row.get("name", "")
        lines.append(f"### {i+1}. 【{row['code']}】{name_str}｜ 評分：{row['surge_score']} 分")
        lines.append("")
        lines.append("#### 前一日收盤")
        lines.append(f"- 收盤價：**{row['close']:.2f}** 元（漲跌 {row['change_pct']:+.2f}%）")
        lines.append(f"- 成交量：**{row['volume_lots']:,}** 張")
        lines.append("")
        lines.append("#### 技術面")

        ma_trend = "多頭排列" if row["ma5"] > row["ma20"] else "空頭排列"
        lines.append(f"- MA5/MA20：{row['ma5']:.2f} / {row['ma20']:.2f}（{ma_trend}）")

        macd_signal = "金叉" if row["dif"] > row["dea"] else "死叉"
        lines.append(f"- MACD：DIF {row['dif']:.3f} / DEA {row['dea']:.3f}（{macd_signal}）")
        lines.append(f"- 布林通道：下軌 {row['lower']:.2f} ｜ 上軌 {row['upper']:.2f}")
        lines.append(f"- 近5日漲幅：{row['ret5']:+.2f}%")
        lines.append("")
        lines.append("#### 法人籌碼")

        if isinstance(row["foreign"], (int, float)):
            lines.append(f"- 外資：{int(row['foreign']):+,} 張")
            lines.append(f"- 投信：{int(row['trust']):+,} 張")
            lines.append(f"- 自營商：{int(row['dealer']):+,} 張")
        else:
            lines.append("- 法人資料暫不可用")

        lines.append("")
        lines.append("#### 暴漲理由分析")

        reasons = []

        # 爆量（保留邏輯，改用成交量絕對值呈現）
        if row["vol_ratio"] >= 3.0:
            reasons.append(f"📈 **爆量突破**：成交量 {row['volume_lots']:,} 張（均量 3 倍以上），主力積極進場，動能強烈。")
        elif row["vol_ratio"] >= 2.0:
            reasons.append(f"📊 **放量上攻**：成交量 {row['volume_lots']:,} 張（均量 2 倍以上），買盤動能充足。")

        # MACD
        if row["dif"] > row["dea"] and row["macd_bar"] > 0:
            reasons.append(f"✅ **MACD 多頭**：DIF({row['dif']:.3f}) > DEA({row['dea']:.3f})，動能向上確認。")

        # 布林通道
        band_width = row["upper"] - row["lower"]
        if band_width > 0:
            pos = (row["close"] - row["lower"]) / band_width
            if pos < 0.25:
                reasons.append(f"📉 **布林下軌支撐**：股價貼近下軌（{row['lower']:.2f}），技術面反彈訊號強烈。")

        # 法人
        if isinstance(row["foreign"], (int, float)):
            f_val = int(row["foreign"])
            t_val = int(row["trust"])
            d_val = int(row["dealer"])
            if f_val > 0 and t_val > 0:
                reasons.append(f"🏦 **外資+投信同步買超**：外資 {f_val:,}張，投信 {t_val:,}張，籌碼面極佳。")
            elif f_val > 500:
                reasons.append(f"🌐 **外資大買**：外資淨買超 {f_val:,} 張，法人看多明顯。")
            elif t_val > 100:
                reasons.append(f"💼 **投信積極布局**：投信買超 {t_val:,} 張，短線拉抬意圖明顯。")

        # 當日漲幅
        if 1 < row["change_pct"] <= 5:
            reasons.append(f"🟢 **溫和上漲未過熱**：當日漲幅 {row['change_pct']:+.2f}%，尚有上攻空間。")

        if not reasons:
            reasons.append("綜合技術指標偏多，短線具備上漲動能。")

        for r in reasons:
            lines.append(f"{r}")

        lines.append("")

        # 操作建議
        score = row["surge_score"]
        if score >= 70:
            suggest = "**[強力買進]**"
            target = round(row["close"] * 1.07, 1)
            stop   = round(row["close"] * 0.95, 1)
        elif score >= 55:
            suggest = "**[買進]**"
            target = round(row["close"] * 1.05, 1)
            stop   = round(row["close"] * 0.96, 1)
        elif score >= 40:
            suggest = "**[小量布局]**"
            target = round(row["close"] * 1.04, 1)
            stop   = round(row["close"] * 0.97, 1)
        else:
            suggest = "**[觀望]**"
            target = None
            stop = None

        lines.append(f"#### 操作建議：{suggest}")
        if target:
            lines.append(f"- 短線目標價：**{target}** 元")
            lines.append(f"- 停損參考：**{stop}** 元（跌破停損出場）")
        lines.append("")
        lines.append("---")
        lines.append("")

    lines.append("## 分析方法說明")
    lines.append("")
    lines.append("| 評分維度 | 權重 | 主要指標 |")
    lines.append("|---------|------|---------|")
    lines.append("| 技術面 | 60分 | 均線排列、RSI、MACD金叉、布林通道、量比 |")
    lines.append("| 法人籌碼 | 30分 | 外資/投信/自營商買賣超，三方同向加分 |")
    lines.append("| 當日量能 | 20分 | 成交量(張)規模、當日漲幅是否溫和 |")
    lines.append("")
    lines.append(f"*本報告由 Stock_AI_agent 自動生成，資料來源：TWSE、Yahoo Finance*")
    lines.append(f"*生成時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")

    return "\n".join(lines)


# ─────────────────────────────────────────
# Step 7: LINE 推播
# ─────────────────────────────────────────
LINE_CHANNEL_ID     = "2009776475"
LINE_CHANNEL_SECRET = "256e8e8c2dfc910a03bdf156cbe3f50d"
LINE_USER_ID        = "Uc4b6168aaeef9ffdf18e4ab0273ff9b9"


def get_line_token() -> str | None:
    resp = requests.post(
        "https://api.line.me/oauth2/v3/token",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "client_credentials",
            "client_id": LINE_CHANNEL_ID,
            "client_secret": LINE_CHANNEL_SECRET,
        },
        timeout=10,
    )
    if resp.status_code == 200:
        return resp.json()["access_token"]
    print(f"[LINE] Token 取得失敗：{resp.status_code} {resp.text}")
    return None


def build_market_line_message(market: dict) -> dict:
    """組合大盤趨勢預測 LINE 訊息"""
    twii = market.get("twii", {})
    us   = market.get("us_markets", {})
    etf  = market.get("etf_action", {})
    direction_zh = {
        "strong_bull": "強力多頭",
        "bull":        "偏多",
        "neutral":     "盤整觀望",
        "bear":        "偏空",
        "strong_bear": "強力空頭",
    }.get(market["direction"], "不明")

    score = market["score"]
    score_icon = "🚀" if score >= 50 else "📈" if score >= 20 else "⚖️" if score >= -20 else "📉" if score >= -50 else "🔻"

    us_lines = []
    for name, d in us.items():
        if d.get("chg_pct") is not None:
            arrow = "▲" if d["chg_pct"] >= 0 else "▼"
            us_lines.append(f"  {name}: {arrow}{abs(d['chg_pct']):.2f}%")

    signal_summary = []
    for sig in market.get("signals", [])[:4]:
        signal_summary.append(f"• {sig}")

    etf_line = ""
    if etf.get("code"):
        etf_line = f"\n\n💡 ETF 建議：{etf['action']} [{etf['code']}]\n{etf['reason']}"
    else:
        etf_line = f"\n\n💡 ETF 建議：{etf['action']}\n{etf['reason']}"

    twii_line = ""
    if twii:
        twii_line = (
            f"\n\n📊 TWII：{twii.get('last', 'N/A')}（{twii.get('day_chg_pct', 0):+.2f}%）"
            f"\nRSI={twii.get('rsi')}  DIF={twii.get('dif')}  量比={twii.get('vol_ratio')}x"
            f"\n近5日：{twii.get('ret5', 0):+.2f}%｜近10日：{twii.get('ret10', 0):+.2f}%"
        )

    # 新聞摘要
    news = market.get("news", {})
    news_lines = []
    if news:
        cat_zh = {
            "trump": "川普/關稅", "strait": "台海局勢",
            "semi": "半導體", "fed": "Fed利率",
            "tw_macro": "台灣總體", "us_china": "美中關係",
        }
        news_lines.append(f"\n📰 新聞情緒：{news['score']:+d}（{news['summary'][:18]}）")
        # 最高影響前3則（繁中優先顯示中文標題）
        top_news = news.get("items", [])[:3]
        for item in top_news:
            arrow = "▲" if item["score"] > 0 else "▼"
            display = item.get("title_zh") or item["title_raw"]
            src = item.get("source", "")
            src_tag = f"[{src[:5]}]" if src else ""
            news_lines.append(f"  {arrow}[{item['score']:+d}]{src_tag} {display[:42]}")
        # 台海特別警示
        strait_s = news.get("category_scores", {}).get("strait", 0)
        if strait_s <= -15:
            news_lines.append(f"\n⚠️ 台海警示：台海情緒分 {strait_s}，高度關注！")

    text = (
        f"{score_icon} 大盤趨勢預測\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"方向：{direction_zh}（評分 {score:+d}）\n"
        f"漲5%+概率：{market['rise_5pct_prob'][:18]}\n"
        f"跌5%+概率：{market['fall_5pct_prob'][:18]}\n"
        f"一週趨勢：{market['weekly_trend'][:30]}"
        f"{twii_line}\n\n"
        f"🌍 美股前收\n" + "\n".join(us_lines) +
        "\n".join(news_lines) +
        "\n\n主要訊號：\n" + "\n".join(signal_summary) +
        etf_line
    )

    return {"type": "text", "text": text}


def build_line_messages(df: pd.DataFrame, trade_date: str) -> list[dict]:
    """組合 LINE 推播訊息（3 則）"""

    # ── 訊息 1：TOP10 排行表 ──
    rows = []
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    for i, row in df.iterrows():
        chg = f"{row['change_pct']:+.2f}%"
        name_short = row.get("name", "")[:4]
        rows.append(
            f"{medals[i]} {row['code']} {name_short}  {row['close']:.1f}  {chg}  {int(row['surge_score'])}"
        )

    msg1 = (
        f"📊 台股前百大交易量 — 隔日暴漲潛力 TOP 10\n"
        f"基準日：{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}｜預測：隔一交易日\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "   代碼 名稱　收盤　漲幅　評分\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        + "\n".join(rows) +
        "\n━━━━━━━━━━━━━━━━━━━━"
    )

    # ── 訊息 2：前5名重點分析 ──
    detail_lines = ["🔍 重點分析\n━━━━━━━━━━━━━━━━━━━━"]
    score_labels = {72: "強力買進", 70: "強力買進", 69: "買進", 68: "買進",
                    66: "買進", 65: "買進", 64: "買進/注意"}

    for i, row in df.head(5).iterrows():
        score = int(row["surge_score"])
        action = "強力買進" if score >= 70 else "買進" if score >= 55 else "觀望"
        target = round(row["close"] * (1.07 if score >= 70 else 1.05), 1)
        stop   = round(row["close"] * (0.95 if score >= 70 else 0.96), 1)

        # 主要理由
        reasons = []
        if row["vol_ratio"] >= 3.0:
            reasons.append(f"爆量({row['volume_lots']:,}張)")
        elif row["vol_ratio"] >= 2.0:
            reasons.append(f"放量({row['volume_lots']:,}張)")
        if row["dif"] > row["dea"]:
            reasons.append("MACD金叉")
        if isinstance(row["foreign"], (int, float)) and row["foreign"] > 0 and isinstance(row["trust"], (int, float)) and row["trust"] > 0:
            reasons.append("三法人買超")
        elif isinstance(row["foreign"], (int, float)) and row["foreign"] > 500:
            reasons.append(f"外資+{int(row['foreign'])//1000}千張")

        reason_str = "、".join(reasons) if reasons else "技術偏多"
        name_str = row.get("name", "")
        detail_lines.append(
            f"\n【{row['code']}】{name_str} {score}分｜{action}\n"
            f"{reason_str}\n"
            f"目標：{target}｜停損：{stop}"
        )

    msg2 = "\n".join(detail_lines)

    # ── 訊息 3：評分說明 + 免責 ──
    msg3 = (
        "📐 評分模型\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "技術面(60)：均線/RSI/MACD/布林/量比\n"
        "法人籌碼(30)：外資/投信/自營商買超\n"
        "當日量能(20)：成交量規模＋漲幅溫和度\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⚠️ 本報告僅供參考，不構成投資建議\n"
        "最終決策請自行判斷\n"
        f"📁 完整報告：surge_report_{trade_date}.md"
    )

    return [
        {"type": "text", "text": msg1},
        {"type": "text", "text": msg2},
        {"type": "text", "text": msg3},
    ]


def send_line_messages(messages: list[dict]) -> bool:
    token = get_line_token()
    if not token:
        return False

    payload = {"to": LINE_USER_ID, "messages": messages}
    resp = requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        timeout=10,
    )
    if resp.status_code == 200:
        print("✓ LINE 推播成功")
        return True
    print(f"[LINE] 推播失敗：{resp.status_code} {resp.text}")
    return False


# ─────────────────────────────────────────
# 主程式入口
# ─────────────────────────────────────────
if __name__ == "__main__":
    import argparse, json

    parser = argparse.ArgumentParser(description="台股前百大交易量暴漲潛力分析")
    parser.add_argument("--date", default=TRADE_DATE, help="分析日期 YYYYMMDD（預設最近交易日）")
    parser.add_argument("--no-line", action="store_true", help="跳過 LINE 推播")
    args = parser.parse_args()

    df_top10, all_results, market = main()

    print("\n" + "="*60)
    print(" TOP 10 暴漲潛力股（評分排名）")
    print("="*60)
    print(df_top10[["code", "name", "close", "change_pct", "volume_lots",
                     "surge_score"]].to_string(index=False))

    # 儲存 Markdown 報告
    report_md = generate_report(df_top10, all_results, market)
    report_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "daily_run")
    os.makedirs(report_dir, exist_ok=True)
    output_path = os.path.join(report_dir, f"surge_report_{TRADE_DATE}.md")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report_md)
    print(f"\n✓ 報告已儲存：{output_path}")

    # LINE 推播
    if not args.no_line:
        print("\n► 發送 LINE 推播...")
        market_msg = build_market_line_message(market)
        stock_msgs = build_line_messages(df_top10, TRADE_DATE)
        # 大盤預測放第一則，接著個股排行與分析
        send_line_messages([market_msg] + stock_msgs)
