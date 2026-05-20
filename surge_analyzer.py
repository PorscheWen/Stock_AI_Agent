#!/usr/bin/env python3
"""
📊 surge_analyzer.py — 台股暴漲潛力分析

分析 TWSE + TPEX（上市+上櫃）前百大成交量個股，評估隔日暴漲潛力並輸出報告。

用法：
  python surge_analyzer.py                   # 分析今日（或最新交易日）
  python surge_analyzer.py --date 20260423   # 分析指定日期
  python surge_analyzer.py --no-line         # 不推播 LINE
"""
import argparse
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

TW = timezone(timedelta(hours=8))

REPORT_DIR   = Path("daily_run")
TOP_VOLUME_N = 100
TOP_RESULT_N = 4

TWSE_MARKET_URL = (
    "https://www.twse.com.tw/rwd/zh/afterTrading/"
    "STOCK_DAY_ALL?response=json&date={date}"
)
TWSE_INST_URL = (
    "https://www.twse.com.tw/rwd/zh/fund/"
    "T86?response=json&date={date}&selectType=ALL"
)
# TPEX（上櫃）使用民國年格式 {roc_date} = "115/05/19"
TPEX_MARKET_URL = (
    "https://www.tpex.org.tw/web/stock/aftertrading/"
    "otc_quotes_no1430/stk_wn1430_result.php"
    "?l=zh-tw&d={roc_date}&se=EW"
)
TPEX_INST_URL = (
    "https://www.tpex.org.tw/web/stock/3insti/daily_trade/"
    "3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&d={roc_date}"
)


# ── 工具函式 ─────────────────────────────────────────

def _parse_float(val) -> float:
    try:
        return float(str(val).replace(",", "").replace("--", "0").strip())
    except (ValueError, AttributeError):
        return 0.0


def _parse_int(val) -> int:
    try:
        return int(str(val).replace(",", "").replace("--", "0").strip())
    except (ValueError, AttributeError):
        return 0


def _ad_to_roc(date_str: str) -> str:
    """將 YYYYMMDD 轉為 TPEX 民國年格式 YYY/MM/DD"""
    dt = datetime.strptime(date_str, "%Y%m%d")
    return f"{dt.year - 1911}/{dt.month:02d}/{dt.day:02d}"


def _last_trading_date() -> str:
    """取得最近一個台股交易日（YYYYMMDD）"""
    now = datetime.now(tz=TW)
    d = now.date()
    # 若尚未收盤（15:00 前）往前推一日
    if now.hour < 15:
        d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.strftime("%Y%m%d")


def _next_trading_day(date_str: str) -> str:
    d = datetime.strptime(date_str, "%Y%m%d").date() + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def _iter_trading_dates(date_str: str, max_back: int = 3):
    """從 date_str 往前產生最多 max_back+1 個交易日（含當日）"""
    d = datetime.strptime(date_str, "%Y%m%d").date()
    count = 0
    while count <= max_back:
        if d.weekday() < 5:  # 非週末
            yield d.strftime("%Y%m%d")
            count += 1
        d -= timedelta(days=1)


# ── TWSE 資料抓取 ─────────────────────────────────────

def _fetch_twse_market(date_str: str) -> pd.DataFrame:
    """抓取 TWSE 當日全市場收盤資料"""
    url = TWSE_MARKET_URL.format(date=date_str)
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error(f"[TWSE] 無法取得市場資料: {e}")
        return pd.DataFrame()

    if data.get("stat") not in ("OK", "ok"):
        logger.warning(f"[TWSE] 資料狀態異常: {data.get('stat')}")
        return pd.DataFrame()

    rows = data.get("data", [])
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=[
        "code", "name", "volume_shares", "value",
        "open", "high", "low", "close",
        "change", "volume_lots",
    ])
    # 只保留 4 碼純數字個股（排除 ETF/ETN）
    df = df[df["code"].str.match(r"^\d{4}$", na=False)].copy()
    df["_vol_int"] = df["volume_lots"].apply(_parse_int)
    return df


def _fetch_twse_institutional(date_str: str) -> dict:
    """抓取 TWSE 三大法人買賣超，回傳 {code: {foreign, trust, dealer}}

    T86 欄位（19欄）：
      [0]代號 [1]名稱
      [2]外資買進 [3]外資賣出 [4]外資淨買超
      [5]外資自營買進 [6]外資自營賣出 [7]外資自營淨買超
      [8]投信買進 [9]投信賣出 [10]投信淨買超
      [11]自營商淨買超 [12..14]自行買賣 [15..17]避險
      [18]三大法人合計
    """
    # 若當日資料尚未公布，自動退回前一交易日
    for attempt_date in _iter_trading_dates(date_str, max_back=3):
        url = TWSE_INST_URL.format(date=attempt_date)
        result: dict = {}
        try:
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if data.get("stat") not in ("OK", "ok"):
                logger.debug(f"[TWSE] T86 {attempt_date} 無資料 ({data.get('stat')})，嘗試前一日")
                continue
            for row in data.get("data", []):
                if len(row) < 19:
                    continue
                code = str(row[0]).strip()
                result[code] = {
                    "foreign": _parse_int(row[4]),   # 外資淨買超
                    "trust":   _parse_int(row[10]),  # 投信淨買超
                    "dealer":  _parse_int(row[11]),  # 自營商淨買超
                }
            if result:
                if attempt_date != date_str:
                    logger.info(f"[TWSE] 法人資料使用 {attempt_date}（{date_str} 尚未公布）")
                return result
        except Exception as e:
            logger.warning(f"[TWSE] 無法取得法人資料 ({attempt_date}): {e}")
    return {}


# ── TPEX 資料抓取 ─────────────────────────────────────

def _fetch_tpex_market(date_str: str) -> pd.DataFrame:
    """抓取 TPEX 上櫃股票當日收盤資料（欄位對齊 TWSE schema）

    TPEX 回傳結構：{"tables":[{"data":[...]}], "stat":"ok"}
    欄位順序：代號,名稱,收盤,漲跌,開盤,最高,最低,成交股數,成交金額,成交筆數,...
    """
    roc_date = _ad_to_roc(date_str)
    url = TPEX_MARKET_URL.format(roc_date=roc_date)
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"[TPEX] 無法取得市場資料: {e}")
        return pd.DataFrame()

    tables = data.get("tables", [])
    rows = tables[0].get("data", []) if tables else []
    if not rows:
        return pd.DataFrame()

    records = []
    for r in rows:
        if len(r) < 10:
            continue
        records.append({
            "code":          str(r[0]).strip(),
            "name":          str(r[1]).strip(),
            "close":         r[2],
            "change":        r[3],
            "open":          r[4],
            "high":          r[5],
            "low":           r[6],
            "volume_shares": r[7],
            "value":         r[8],
            "volume_lots":   r[9],
            "_market":       "TWO",
        })

    df = pd.DataFrame(records)
    if df.empty:
        return pd.DataFrame()
    df = df[df["code"].str.match(r"^\d{4}$", na=False)].copy()
    df["_vol_int"] = df["volume_lots"].apply(_parse_int)
    return df


def _fetch_tpex_institutional(date_str: str) -> dict:
    """抓取 TPEX 三大法人買賣超，回傳 {code: {foreign, trust, dealer}}

    TPEX 回傳結構：{"tables":[{"data":[...]}], "stat":"ok"}
    欄位：[0]代號 [1]名稱 [4]外資淨買超 [10]投信淨買超 [19]自營商淨買超合計
    """
    for attempt_date in _iter_trading_dates(date_str, max_back=3):
        roc_date = _ad_to_roc(attempt_date)
        url = TPEX_INST_URL.format(roc_date=roc_date)
        result: dict = {}
        try:
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            tables = data.get("tables", [])
            rows = tables[0].get("data", []) if tables else []
            if not rows:
                logger.debug(f"[TPEX] 法人 {attempt_date} 無資料，嘗試前一日")
                continue
            for row in rows:
                if len(row) < 20:
                    continue
                code = str(row[0]).strip()
                result[code] = {
                    "foreign": _parse_int(row[4]),
                    "trust":   _parse_int(row[10]),
                    "dealer":  _parse_int(row[19]),
                }
            if result:
                if attempt_date != date_str:
                    logger.info(f"[TPEX] 法人資料使用 {attempt_date}（{date_str} 尚未公布）")
                return result
        except Exception as e:
            logger.warning(f"[TPEX] 無法取得法人資料 ({attempt_date}): {e}")
    return {}


# ── 上櫃風險評估 ──────────────────────────────────────

def _build_otc_risk_warnings(
    is_otc: bool,
    consecutive_days: int,
    vol_ratio: float,
    ret5: float,
) -> list[str]:
    """產生上櫃股票特有風險警示清單（surge_analyzer 版，不依賴 ATR）"""
    if not is_otc:
        return []

    warnings: list[str] = [
        "【流動性】上櫃成交量通常低於上市，急跌時出場困難，停損單建議掛市價",
        "【籌碼集中】上櫃小型股大股東比例高，主力出貨跌速快，嚴守停損",
        "【資訊透明度】上櫃財報揭露頻率低，題材真實性需自行交叉驗證",
    ]

    if consecutive_days >= 2:
        warnings.append(
            f"【連板回落風險】目前第 {consecutive_days} 板，"
            "上櫃連板股落板平均回撤 15-25%，建議移動停損"
        )

    if vol_ratio > 10.0:
        warnings.append(
            f"【爆量警示】量比達 {vol_ratio:.1f}x，"
            "上櫃爆量後次日開盤可能出現大幅回落或跳空跌停"
        )

    if ret5 > 40.0:
        warnings.append(
            f"【短期超漲】5日漲幅 {ret5:.1f}%，"
            "上櫃短期超漲後的均值回歸風險高，注意追高風險"
        )

    return warnings


# ── 技術指標計算 ──────────────────────────────────────

def _calc_rsi(close: pd.Series, period: int = 14) -> float:
    delta = close.diff()
    gain  = delta.where(delta > 0, 0.0)
    loss  = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs  = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1]) if not rsi.empty else 50.0


def _calc_macd(close: pd.Series) -> tuple[float, float]:
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    dif   = ema12 - ema26
    dea   = dif.ewm(span=9, adjust=False).mean()
    return float(dif.iloc[-1]), float(dea.iloc[-1])


def _fetch_yf(code: str, suffix: str = "TW") -> pd.DataFrame | None:
    """抓取 Yahoo Finance 歷史資料；上市用 .TW，上櫃用 .TWO"""
    try:
        ticker = yf.Ticker(f"{code}.{suffix}")
        df = ticker.history(period="60d")
        if df is None or df.empty or len(df) < 20:
            return None
        return df
    except Exception as e:
        logger.debug(f"[yf] {code}.{suffix} 取得失敗: {e}")
        return None


# ── 個股分析與評分 ─────────────────────────────────────

def _analyze_stock(
    code: str,
    name: str,
    twse_row: pd.Series,
    inst: dict,
    suffix: str = "TW",
) -> dict | None:
    """分析單一股票，回傳評分字典；資料不足時回傳 None。
    suffix: 'TW' 表上市，'TWO' 表上櫃（影響 yfinance 查詢）。
    """
    close_price = _parse_float(twse_row.get("close", 0))
    change_val  = _parse_float(twse_row.get("change", 0))
    volume_lots = _parse_int(twse_row.get("volume_lots", 0))

    if close_price <= 0:
        return None

    prev_close = close_price - change_val
    change_pct = (change_val / prev_close * 100) if prev_close > 0 else 0.0

    df = _fetch_yf(code, suffix=suffix)
    if df is None:
        return None

    close_s = df["Close"]
    vol_s   = df["Volume"]

    rsi       = _calc_rsi(close_s)
    dif, dea  = _calc_macd(close_s)
    ma5       = float(close_s.tail(5).mean())
    ma20      = float(close_s.tail(20).mean())
    avg_vol   = float(vol_s.tail(20).mean())
    today_vol = float(vol_s.iloc[-1]) if len(vol_s) >= 1 else 0.0
    vol_ratio = (today_vol / avg_vol) if avg_vol > 0 else 1.0
    ret5      = float((close_s.iloc[-1] / close_s.iloc[-6] - 1) * 100) if len(close_s) >= 6 else 0.0

    # ── 評分（滿分 110）────────────────────────────────
    score = 0.0

    # 技術面（60 分）
    # RSI：45–75 最佳 +20，40–80 可接受 +10
    if 45 <= rsi <= 75:
        score += 20
    elif 40 <= rsi <= 80:
        score += 10
    # MACD 金叉
    if dif > dea:
        score += 15
    # 均線多頭排列
    if ma5 > ma20:
        score += 15
    # 量比
    if vol_ratio >= 3.0:
        score += 10
    elif vol_ratio >= 2.0:
        score += 7
    elif vol_ratio >= 1.2:
        score += 4

    # 法人籌碼（30 分）
    inst_data = inst.get(code, {})
    foreign = inst_data.get("foreign", 0)
    trust   = inst_data.get("trust",   0)
    dealer  = inst_data.get("dealer",  0)
    if isinstance(foreign, (int, float)) and foreign > 0:
        score += 10
    if isinstance(trust, (int, float)) and trust > 0:
        score += 10
    elif isinstance(trust, (int, float)) and trust < 0:
        score -= 5
    if isinstance(dealer, (int, float)) and dealer > 0:
        score += 10

    # 當日量能（20 分）
    if volume_lots >= 50_000:
        score += 20
    elif volume_lots >= 20_000:
        score += 15
    elif volume_lots >= 5_000:
        score += 10
    elif volume_lots >= 1_000:
        score += 5

    is_otc = suffix == "TWO"
    otc_warnings = _build_otc_risk_warnings(
        is_otc=is_otc,
        consecutive_days=0,        # surge_analyzer 不追蹤連板，傳 0
        vol_ratio=vol_ratio,
        ret5=ret5,
    )

    return {
        "code":             code,
        "name":             name,
        "market":           "上櫃" if is_otc else "上市",
        "is_otc":           is_otc,
        "close":            close_price,
        "change_pct":       round(change_pct, 2),
        "volume_lots":      volume_lots,
        "rsi":              round(rsi, 1),
        "dif":              round(dif, 4),
        "dea":              round(dea, 4),
        "ma5":              round(ma5, 2),
        "ma20":             round(ma20, 2),
        "vol_ratio":        round(vol_ratio, 2),
        "ret5":             round(ret5, 2),
        "foreign":          foreign,
        "trust":            trust,
        "dealer":           dealer,
        "surge_score":      round(score, 1),
        "otc_risk_warnings": otc_warnings,
    }


# ── 報告生成 ──────────────────────────────────────────

def _fmt_inst(v) -> str:
    if not isinstance(v, (int, float)):
        return "N/A"
    v = int(v)
    return f"+{v:,}" if v > 0 else f"{v:,}"


def _build_stock_detail_lines(rows: list[dict], start_rank: int = 1) -> list[str]:
    """產生個股詳細分析 Markdown 段落（可供上市/上櫃共用）"""
    lines: list[str] = []
    for i, row in enumerate(rows, start_rank):
        macd_status  = "金叉 ▲" if row["dif"] > row["dea"] else "死叉 ▼"
        ma_trend     = "多頭排列" if row["ma5"] > row["ma20"] else "空頭排列"
        market_tag   = row.get("market", "上市")
        is_otc       = row.get("is_otc", False)
        otc_warnings = row.get("otc_risk_warnings", [])

        stock_lines = [
            f"### #{i} {row['name']} ({row['code']}) [{market_tag}]",
            "",
            f"- **收盤價**：{row['close']:.2f}　**當日漲幅**：{row['change_pct']:+.2f}%　**成交筆數**：{row['volume_lots']:,}",
            f"- **綜合評分**：{row['surge_score']:.0f} 分　**量比**：{row['vol_ratio']:.1f}x　**5日漲幅**：{row['ret5']:+.1f}%",
            f"- **RSI(14)**：{row['rsi']:.1f}　**MACD**：{macd_status}　**均線**：{ma_trend}",
            f"- **外資**：{_fmt_inst(row['foreign'])} 張　**投信**：{_fmt_inst(row['trust'])} 張　**自營商**：{_fmt_inst(row['dealer'])} 張",
        ]
        if is_otc and otc_warnings:
            stock_lines += ["", "> ⚠️ **上櫃特有風險警示**"]
            for w in otc_warnings:
                stock_lines.append(f"> - {w}")
        stock_lines.append("")
        lines += stock_lines
    return lines


def _build_report(
    df_twse: pd.DataFrame,
    df_tpex: pd.DataFrame,
    date_str: str,
    sample_n_twse: int,
    sample_n_tpex: int,
) -> str:
    """上市 TOP N 和上櫃 TOP N 分開呈現的 Markdown 報告"""
    analysis_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    next_day      = _next_trading_day(date_str)
    now_str       = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    twse_rows = df_twse.to_dict(orient="records") if not df_twse.empty else []
    tpex_rows = df_tpex.to_dict(orient="records") if not df_tpex.empty else []

    def _table_rows(rows: list[dict]) -> list[str]:
        out = []
        for i, row in enumerate(rows, 1):
            out.append(
                f"| {i} | {row['code']} | {row['name']} | "
                f"{row['close']:.2f} | {row['change_pct']:+.2f}% | "
                f"{row['volume_lots']:,} | {row['surge_score']:.0f} |"
            )
        return out

    table_header = [
        "| 排名 | 代碼 | 名稱 | 收盤 | 當日漲幅 | 成交筆數 | 評分 |",
        "|------|------|------|------|---------|---------|------|",
    ]

    lines = [
        f"# 台股暴漲潛力 — 上市 TOP {TOP_RESULT_N} ＋ 上櫃 TOP {TOP_RESULT_N}",
        f"**分析基準日**：{analysis_date}　｜　**預測目標日**：{next_day}（下一交易日）",
        "",
        "> ⚠️ 本報告僅供參考，不構成投資建議，最終決策請自行判斷。",
        "",
        "---",
        "",
        "## 分析說明",
        f"- **上市（TWSE）**：{sample_n_twse} 支，依成交量取前 {TOP_VOLUME_N} 支分析",
        f"- **上櫃（TPEX）**：{sample_n_tpex} 支，依成交量取前 {TOP_VOLUME_N} 支獨立分析",
        "",
        "---",
        "",
        f"## 🏦 上市（TWSE）TOP {TOP_RESULT_N}",
        "",
        *table_header,
        *_table_rows(twse_rows),
        "",
        "---",
        "",
        f"## 🏪 上櫃（TPEX）TOP {TOP_RESULT_N}",
        "",
        *table_header,
        *_table_rows(tpex_rows),
        "",
        "---",
        "",
        "## 個股詳細分析",
        "",
        f"### 🏦 上市個股",
        "",
        *_build_stock_detail_lines(twse_rows),
        f"### 🏪 上櫃個股",
        "",
        *_build_stock_detail_lines(tpex_rows),
        "---",
        "",
        "## 分析方法說明",
        "",
        "| 評分維度 | 權重 | 主要指標 |",
        "|---------|------|---------|",
        "| 技術面 | 60分 | 均線排列、RSI、MACD金叉、量比 |",
        "| 法人籌碼 | 30分 | 外資/投信/自營商買賣超 |",
        "| 當日量能 | 20分 | 成交筆數規模 |",
        "| 上櫃折扣 | — | 上櫃股票風險評估附加警示 |",
        "",
        "*本報告由 Stock_AI_agent 自動生成，資料來源：TWSE（上市）、TPEX（上櫃）、Yahoo Finance*",
        f"*生成時間：{now_str}*",
    ]

    return "\n".join(lines)


# ── 主程式 ────────────────────────────────────────────

def _analyze_market_stocks(
    df_vol: pd.DataFrame,
    inst_data: dict,
    market_suffix: str,
    label: str,
) -> pd.DataFrame:
    """分析指定市場的前百大成交量個股，回傳評分 DataFrame（已按 surge_score 降序）"""
    results = []
    total = len(df_vol)
    for i, (_, row) in enumerate(df_vol.iterrows(), 1):
        code = str(row.get("code", "")).strip()
        name = str(row.get("name", code)).strip()
        if not code:
            continue
        logger.info(f"  [{label} {i:3d}/{total}] {code} {name}")
        result = _analyze_stock(code, name, row, inst_data, suffix=market_suffix)
        if result:
            results.append(result)
        time.sleep(0.3)
    if not results:
        return pd.DataFrame()
    return (
        pd.DataFrame(results)
        .sort_values("surge_score", ascending=False)
        .reset_index(drop=True)
    )


def main(
    date_str: str | None = None,
    enable_line: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    """
    主分析流程：上市和上櫃各自取前 TOP_VOLUME_N 分析，分別推薦 TOP_RESULT_N 檔。
    回傳: (df_twse_top: pd.DataFrame, df_tpex_top: pd.DataFrame, report_path: str)
    """
    date_str = date_str or _last_trading_date()
    logger.info(f"[Analyzer] 分析日期：{date_str}")

    # Step 1：分別取得 TWSE / TPEX 市場資料
    logger.info("[Step 1] 取得 TWSE（上市）市場資料...")
    df_twse_mkt = _fetch_twse_market(date_str)
    if not df_twse_mkt.empty:
        df_twse_mkt["_market"] = "TW"

    logger.info("[Step 1] 取得 TPEX（上櫃）市場資料...")
    df_tpex_mkt = _fetch_tpex_market(date_str)
    # _market = "TWO" 已在 _fetch_tpex_market 內設定

    if df_twse_mkt.empty and df_tpex_mkt.empty:
        logger.warning("[Step 1] 無任何市場資料，結束")
        return pd.DataFrame(), pd.DataFrame(), ""

    sample_n_twse = len(df_twse_mkt)
    sample_n_tpex = len(df_tpex_mkt)
    logger.info(f"[Step 1] 上市 {sample_n_twse} 檔，上櫃 {sample_n_tpex} 檔")

    # Step 2：各市場取前 TOP_VOLUME_N 成交量個股
    df_twse_vol = df_twse_mkt.nlargest(TOP_VOLUME_N, "_vol_int").copy() if not df_twse_mkt.empty else pd.DataFrame()
    df_tpex_vol = df_tpex_mkt.nlargest(TOP_VOLUME_N, "_vol_int").copy() if not df_tpex_mkt.empty else pd.DataFrame()
    logger.info(f"[Step 2] 上市取 {len(df_twse_vol)} 檔，上櫃取 {len(df_tpex_vol)} 檔")

    # Step 3：取得三大法人資料
    logger.info("[Step 3] 取得三大法人資料...")
    inst_twse = _fetch_twse_institutional(date_str)
    inst_tpex = _fetch_tpex_institutional(date_str)
    inst_data = {**inst_tpex, **inst_twse}
    logger.info(f"[Step 3] 法人資料 {len(inst_data)} 檔")

    # Step 4：分別分析上市 / 上櫃
    logger.info(f"[Step 4a] 分析上市 {len(df_twse_vol)} 檔...")
    df_twse_all = _analyze_market_stocks(df_twse_vol, inst_data, "TW",  "上市")

    logger.info(f"[Step 4b] 分析上櫃 {len(df_tpex_vol)} 檔...")
    df_tpex_all = _analyze_market_stocks(df_tpex_vol, inst_data, "TWO", "上櫃")

    # Step 5：各取 TOP_RESULT_N
    df_twse_top = df_twse_all.head(TOP_RESULT_N).copy() if not df_twse_all.empty else pd.DataFrame()
    df_tpex_top = df_tpex_all.head(TOP_RESULT_N).copy() if not df_tpex_all.empty else pd.DataFrame()

    if not df_twse_top.empty:
        logger.info(f"[Step 5] 上市 TOP {TOP_RESULT_N}，最高分：{df_twse_top.iloc[0]['surge_score']:.0f}")
    if not df_tpex_top.empty:
        logger.info(f"[Step 5] 上櫃 TOP {TOP_RESULT_N}，最高分：{df_tpex_top.iloc[0]['surge_score']:.0f}")

    # Step 6：生成 Markdown 報告
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f"surge_report_{date_str}.md"
    report_path.write_text(
        _build_report(df_twse_top, df_tpex_top, date_str, sample_n_twse, sample_n_tpex),
        encoding="utf-8",
    )
    logger.info(f"[Step 6] 報告已儲存：{report_path}")

    # Step 7：LINE 推播（上市+上櫃各自推薦清單）
    if enable_line:
        has_push = not df_twse_top.empty or not df_tpex_top.empty
        if has_push:
            logger.info("[Step 7] 推播至 LINE...")
            from line_push import push_surge_report
            ok = push_surge_report(df_twse_top, df_tpex_top)
            if ok:
                logger.info("[Step 7] LINE 推播成功")
            else:
                raise RuntimeError(
                    "LINE 推播失敗！"
                    "請確認 GitHub Secrets：CHANNEL_STOCK_ACCESS_TOKEN、CHANNEL_STOCK_USER_ID"
                )
        else:
            logger.info("[Step 7] 無分析結果，跳過 LINE 推播")

    return df_twse_top, df_tpex_top, str(report_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="台股暴漲潛力分析")
    parser.add_argument("--date",    type=str, default=None, help="分析日期 YYYYMMDD")
    parser.add_argument("--no-line", action="store_true",    help="不推播 LINE")
    args = parser.parse_args()

    df_tw, df_otc, path = main(date_str=args.date, enable_line=not args.no_line)

    if not df_tw.empty or not df_otc.empty:
        print(f"\n✅ 分析完成！報告：{path}")
        if not df_tw.empty:
            print(f"\n🏦 上市 TOP {TOP_RESULT_N}：")
            for i, row in df_tw.iterrows():
                print(
                    f"  #{i+1:2d} {row['code']} {row.get('name',''):8s}"
                    f"  評分={row['surge_score']:.0f}  漲幅={row['change_pct']:+.1f}%"
                )
        if not df_otc.empty:
            print(f"\n🏪 上櫃 TOP {TOP_RESULT_N}：")
            for i, row in df_otc.iterrows():
                print(
                    f"  #{i+1:2d} {row['code']} {row.get('name',''):8s}"
                    f"  評分={row['surge_score']:.0f}  漲幅={row['change_pct']:+.1f}%"
                )
    else:
        print("❌ 分析失敗或無資料")
        sys.exit(1)
