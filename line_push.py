"""
📲 LINE PUSH — Stock_AI_agent
將暴漲潛力 TOP 10 以 Flex Carousel 推播至 LINE
Carousel 順序：評分由高到低（左→右）
"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import os
import logging
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")


def _get_api():
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    if not token:
        raise RuntimeError("LINE_CHANNEL_ACCESS_TOKEN 未設定")
    from linebot.v3.messaging import MessagingApi, ApiClient, Configuration
    return MessagingApi(ApiClient(Configuration(access_token=token)))


def _get_user_id() -> str:
    uid = os.environ.get("LINE_USER_ID", "")
    if not uid:
        raise RuntimeError("LINE_USER_ID 未設定")
    return uid


# ── 配色：依評分高低 ───────────────────────────────────
def _score_color(score: float) -> str:
    if score >= 75:
        return "#1A5276"   # 深藍 — 強力推薦
    elif score >= 60:
        return "#1E8449"   # 深綠 — 推薦
    elif score >= 45:
        return "#B7950B"   # 深黃 — 觀察
    else:
        return "#7B7D7D"   # 灰   — 低分


def _score_label(score: float) -> str:
    if score >= 75:
        return "強力推薦"
    elif score >= 60:
        return "推薦"
    elif score >= 45:
        return "觀察"
    else:
        return "低分"


def _macd_status(dif: float, dea: float) -> str:
    return "金叉 ▲" if dif > dea else "死叉 ▼"


def _inst_fmt(val) -> str:
    if not isinstance(val, (int, float)):
        return "N/A"
    v = int(val)
    if v > 0:
        return f"+{v:,}"
    return f"{v:,}"


# ── 摘要 Bubble ───────────────────────────────────────
def _summary_bubble(date_str: str, count: int) -> dict:
    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#2C3E50",
            "paddingAll": "16px",
            "contents": [
                {"type": "text", "text": "🇹🇼 台股暴漲潛力報告", "size": "lg", "weight": "bold", "color": "#FFFFFF"},
                {"type": "text", "text": date_str, "size": "sm", "color": "#BDC3C7", "margin": "xs"},
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "paddingAll": "14px",
            "contents": [
                {
                    "type": "box",
                    "layout": "vertical",
                    "backgroundColor": "#EBF5FB",
                    "paddingAll": "16px",
                    "cornerRadius": "8px",
                    "contents": [
                        {"type": "text", "text": "今日精選（評分 ≥ 70）", "size": "xs", "color": "#888", "align": "center"},
                        {
                            "type": "text",
                            "text": f"{count} 檔" if count > 0 else "今日無符合",
                            "size": "xxl",
                            "weight": "bold",
                            "color": "#1E8449" if count > 0 else "#E74C3C",
                            "align": "center",
                        },
                    ],
                },
                {
                    "type": "text",
                    "text": "依評分由高至低排列，僅呈現評分 ≥ 70 分之個股",
                    "size": "xs",
                    "color": "#888",
                    "wrap": True,
                    "margin": "md",
                    "align": "center",
                },
            ],
        },
    }


# ── 個股 Bubble ────────────────────────────────────────
def _stock_bubble(row: dict, rank: int) -> dict:
    score    = row["surge_score"]
    color    = _score_color(score)
    label    = _score_label(score)
    chg      = row["change_pct"]
    chg_color = "#27AE60" if chg >= 0 else "#E74C3C"
    chg_str   = f"{chg:+.2f}%"

    macd_str  = _macd_status(row["dif"], row["dea"])
    ma_trend  = "多頭排列" if row["ma5"] > row["ma20"] else "空頭排列"

    # 停損 / 目標（ATR 估算：以近5日波動 2% 為基準）
    atr_est   = row["close"] * 0.02
    stop      = round(row["close"] - atr_est * 1.5, 2)
    target    = round(row["close"] + atr_est * 3.0, 2)
    stop_pct  = round((stop  - row["close"]) / row["close"] * 100, 1)
    tgt_pct   = round((target - row["close"]) / row["close"] * 100, 1)

    # 法人
    foreign_str = _inst_fmt(row.get("foreign"))
    trust_str   = _inst_fmt(row.get("trust"))
    dealer_str  = _inst_fmt(row.get("dealer"))

    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": color,
            "paddingAll": "14px",
            "contents": [
                {
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {
                            "type": "text",
                            "text": f"#{rank} {row['code']} {row.get('name', '')}",
                            "size": "md",
                            "weight": "bold",
                            "color": "#FFFFFF",
                            "flex": 1,
                            "wrap": True,
                        },
                        {
                            "type": "text",
                            "text": f"{score} 分",
                            "size": "lg",
                            "weight": "bold",
                            "color": "#FFFFFF",
                            "align": "end",
                            "gravity": "center",
                        },
                    ],
                },
                {
                    "type": "box",
                    "layout": "horizontal",
                    "margin": "xs",
                    "contents": [
                        {"type": "text", "text": f"${row['close']:.2f}", "size": "sm", "color": "#FFFFFF", "flex": 1},
                        {"type": "text", "text": chg_str, "size": "sm", "color": "#FFFFFF", "align": "end"},
                    ],
                },
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "xs",
            "paddingAll": "14px",
            "contents": [
                # 技術指標列
                {
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {
                            "type": "box",
                            "layout": "vertical",
                            "flex": 1,
                            "contents": [
                                {"type": "text", "text": "RSI", "size": "xs", "color": "#888"},
                                {"type": "text", "text": f"{row['rsi']:.1f}", "size": "md", "weight": "bold"},
                            ],
                        },
                        {
                            "type": "box",
                            "layout": "vertical",
                            "flex": 1,
                            "contents": [
                                {"type": "text", "text": "MACD", "size": "xs", "color": "#888"},
                                {
                                    "type": "text",
                                    "text": macd_str,
                                    "size": "sm",
                                    "weight": "bold",
                                    "color": "#27AE60" if "金叉" in macd_str else "#E74C3C",
                                },
                            ],
                        },
                        {
                            "type": "box",
                            "layout": "vertical",
                            "flex": 1,
                            "contents": [
                                {"type": "text", "text": "量比", "size": "xs", "color": "#888"},
                                {
                                    "type": "text",
                                    "text": f"{row['vol_ratio']:.1f}x",
                                    "size": "md",
                                    "weight": "bold",
                                    "color": "#E67E22" if row["vol_ratio"] >= 2.5 else "#2C3E50",
                                },
                            ],
                        },
                        {
                            "type": "box",
                            "layout": "vertical",
                            "flex": 1,
                            "contents": [
                                {"type": "text", "text": "均線", "size": "xs", "color": "#888"},
                                {
                                    "type": "text",
                                    "text": "多頭" if "多頭" in ma_trend else "空頭",
                                    "size": "sm",
                                    "weight": "bold",
                                    "color": "#27AE60" if "多頭" in ma_trend else "#E74C3C",
                                },
                            ],
                        },
                    ],
                },
                {"type": "separator", "margin": "sm"},
                # 法人籌碼
                {
                    "type": "box",
                    "layout": "horizontal",
                    "margin": "xs",
                    "contents": [
                        {"type": "text", "text": "外資", "size": "xs", "color": "#888", "flex": 1},
                        {
                            "type": "text",
                            "text": foreign_str,
                            "size": "xs",
                            "flex": 2,
                            "color": "#27AE60" if isinstance(row.get("foreign"), (int, float)) and row["foreign"] > 0 else "#E74C3C",
                        },
                        {"type": "text", "text": "投信", "size": "xs", "color": "#888", "flex": 1},
                        {
                            "type": "text",
                            "text": trust_str,
                            "size": "xs",
                            "flex": 2,
                            "color": "#27AE60" if isinstance(row.get("trust"), (int, float)) and row["trust"] > 0 else "#E74C3C",
                        },
                    ],
                },
                {"type": "separator", "margin": "sm"},
                # 停損 / 目標
                {
                    "type": "box",
                    "layout": "horizontal",
                    "margin": "xs",
                    "contents": [
                        {
                            "type": "box",
                            "layout": "vertical",
                            "flex": 1,
                            "contents": [
                                {"type": "text", "text": "停損", "size": "xs", "color": "#E74C3C"},
                                {"type": "text", "text": f"{stop}", "size": "sm", "weight": "bold", "color": "#E74C3C"},
                                {"type": "text", "text": f"{stop_pct:.1f}%", "size": "xs", "color": "#E74C3C"},
                            ],
                        },
                        {
                            "type": "box",
                            "layout": "vertical",
                            "flex": 1,
                            "contents": [
                                {"type": "text", "text": "目標", "size": "xs", "color": "#27AE60"},
                                {"type": "text", "text": f"{target}", "size": "sm", "weight": "bold", "color": "#27AE60"},
                                {"type": "text", "text": f"+{tgt_pct:.1f}%", "size": "xs", "color": "#27AE60"},
                            ],
                        },
                        {
                            "type": "box",
                            "layout": "vertical",
                            "flex": 1,
                            "contents": [
                                {"type": "text", "text": "5日漲幅", "size": "xs", "color": "#888"},
                                {
                                    "type": "text",
                                    "text": f"{row['ret5']:+.1f}%",
                                    "size": "sm",
                                    "weight": "bold",
                                    "color": "#27AE60" if row["ret5"] >= 0 else "#E74C3C",
                                },
                            ],
                        },
                    ],
                },
            ],
        },
        "footer": {
            "type": "box",
            "layout": "horizontal",
            "paddingAll": "10px",
            "backgroundColor": "#F2F3F4",
            "contents": [
                {"type": "text", "text": label, "size": "sm", "weight": "bold", "color": color, "flex": 1},
                {"type": "text", "text": f"成交 {row['volume_lots']:,} 張", "size": "xs", "color": "#888", "align": "end"},
            ],
        },
    }


# ── 主推播函式 ─────────────────────────────────────────
def push_text(message: str) -> None:
    """推播純文字（適合錯誤通知）。"""
    from linebot.v3.messaging import PushMessageRequest, TextMessage
    _get_api().push_message(PushMessageRequest(
        to=_get_user_id(),
        messages=[TextMessage(text=message)],
    ))


def push_surge_report(df_top10) -> bool:
    """df_top10: surge_analyzer.main() 回傳的 DataFrame（已按 surge_score 降序，僅含 ≥70 分）"""
    try:
        api     = _get_api()
        user_id = _get_user_id()
    except RuntimeError as e:
        logger.warning("[LINE] %s，跳過推播", e)
        return False

    from linebot.v3.messaging import PushMessageRequest, FlexMessage, FlexContainer

    date_str = datetime.now().strftime("%Y-%m-%d")
    rows = df_top10.to_dict(orient="records")

    bubbles = [_summary_bubble(date_str, len(rows))]
    for rank, row in enumerate(rows, 1):
        bubbles.append(_stock_bubble(row, rank))

    carousel = {"type": "carousel", "contents": bubbles[:12]}

    try:
        api.push_message(
            PushMessageRequest(
                to=user_id,
                messages=[
                    FlexMessage(
                        alt_text=f"🇹🇼 台股暴漲潛力 TOP{len(rows)} — {date_str}",
                        contents=FlexContainer.from_dict(carousel),
                    )
                ],
            )
        )
        logger.info("[LINE] 推播成功：TOP %d 暴漲潛力股", len(rows))
        return True
    except Exception as e:
        logger.error("[LINE] 推播失敗: %s", e)
        return False


# ── 直接執行：分析 + 推播 ──────────────────────────────
if __name__ == "__main__":
    from surge_analyzer import main as surge_main

    logger.info("► 執行 surge_analyzer...")
    df_top10, _ = surge_main()

    logger.info("► 推播至 LINE Bot...")
    ok = push_surge_report(df_top10)

    print()
    print("推播結果:", "✅ 成功" if ok else "❌ 失敗")
    print()
    print("Carousel 順序（左→右）：")
    for i, row in df_top10.iterrows():
        print(f"  #{i+1:2d} {row['code']} {row.get('name',''):6s}  評分={row['surge_score']:.0f}")
