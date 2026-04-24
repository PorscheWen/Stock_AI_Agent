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
    token = os.environ.get("CHANNEL_STOCK_ACCESS_TOKEN", "")
    if not token:
        raise RuntimeError(
            "CHANNEL_STOCK_ACCESS_TOKEN 未設定，"
            "請至 GitHub Settings > Secrets and variables > Actions 新增"
        )
    from linebot.v3.messaging import MessagingApi, ApiClient, Configuration
    return MessagingApi(ApiClient(Configuration(access_token=token)))


def _get_user_ids() -> list[str]:
    """支援多人（CHANNEL_STOCK_USER_IDS 逗號分隔）與單人（CHANNEL_STOCK_USER_ID）"""
    multi = os.environ.get("CHANNEL_STOCK_USER_IDS", "")
    if multi:
        ids = [u.strip() for u in multi.split(",") if u.strip()]
        if ids:
            return ids
    single = os.environ.get("CHANNEL_STOCK_USER_ID", "")
    if single:
        return [single]
    raise RuntimeError(
        "CHANNEL_STOCK_USER_ID 未設定，"
        "請至 GitHub Settings > Secrets and variables > Actions 新增"
    )


def _get_user_id() -> str:
    """向下相容：回傳第一個 user id"""
    return _get_user_ids()[0]


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


def _build_score_bar(score: float, max_score: float = 110.0) -> dict:
    """ETF repo 風格橫向評分條"""
    pct = int(min(score / max_score * 100, 100))
    if score >= 90:
        color = "#00695C"
    elif score >= 75:
        color = "#2E7D32"
    elif score >= 60:
        color = "#F57F17"
    else:
        color = "#C62828"
    return {
        "type": "box",
        "layout": "horizontal",
        "height": "8px",
        "backgroundColor": "#EEEEEE",
        "cornerRadius": "4px",
        "contents": [
            {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": color,
                "height": "8px",
                "cornerRadius": "4px",
                "flex": pct,
                "contents": [],
            },
            {
                "type": "box",
                "layout": "vertical",
                "flex": max(1, 100 - pct),
                "contents": [],
            },
        ],
    }


def _section_title(text: str) -> dict:
    return {
        "type": "text",
        "text": text,
        "size": "sm",
        "weight": "bold",
        "color": "#333333",
    }


def _entry_strategy(row: dict) -> str:
    """依漲幅與量比產生進場建議文字"""
    chg = row["change_pct"]
    vol = row["vol_ratio"]
    ma5  = row.get("ma5", 0)
    close = row["close"]
    ma5_str = f"MA5 {ma5:.1f}" if ma5 > 0 else "MA5"
    if chg >= 9.5:
        extra = "（爆量強勢優先）" if vol >= 5 else ""
        return f"今日漲停，明日集合競價追漲停{extra}；若開低可觀察 {ma5_str} 支撐"
    elif chg >= 5.0:
        return f"強勢上漲，可逢回踩 {ma5_str} 支撐進場，追漲需設嚴格停損"
    else:
        return f"溫和漲勢，等量縮回測 {ma5_str} 支撐確認後再進場"


def _exit_strategy(tgt_pct: float, stop_pct: float) -> str:
    return (
        f"達停利 +{tgt_pct:.1f}% 先減倉 50%，"
        f"剩餘移動停損 -5%；"
        f"最長持有 4 天，跌破停損 {stop_pct:.1f}% 強制出場"
    )


# ── 摘要 Bubble ───────────────────────────────────────
def _summary_bubble(date_str: str, count: int) -> dict:
    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#00695C",
            "paddingAll": "16px",
            "contents": [
                {"type": "text", "text": "🇹🇼 台股暴漲潛力報告", "size": "lg", "weight": "bold", "color": "#FFFFFF"},
                {"type": "text", "text": date_str, "size": "sm", "color": "#B2DFDB", "margin": "xs"},
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
                    "backgroundColor": "#E8F5E9",
                    "paddingAll": "16px",
                    "cornerRadius": "8px",
                    "contents": [
                        {"type": "text", "text": "今日精選（評分 ≥ 90）", "size": "xs", "color": "#555555", "align": "center"},
                        {
                            "type": "text",
                            "text": f"{count} 檔" if count > 0 else "今日無符合",
                            "size": "xxl",
                            "weight": "bold",
                            "color": "#00695C" if count > 0 else "#C62828",
                            "align": "center",
                        },
                    ],
                },
                {
                    "type": "text",
                    "text": "依評分由高至低排列，僅呈現評分 ≥ 90 分之個股",
                    "size": "xs",
                    "color": "#777777",
                    "wrap": True,
                    "margin": "md",
                    "align": "center",
                },
                {
                    "type": "text",
                    "text": "⚠️ 僅供參考，非投資建議",
                    "size": "xxs",
                    "color": "#AAAAAA",
                    "align": "center",
                    "margin": "sm",
                },
            ],
        },
    }


# ── 個股 Bubble（ETF repo 風格） ──────────────────────
def _stock_bubble(row: dict, rank: int) -> dict:
    score   = row["surge_score"]
    label   = _score_label(score)
    color   = _score_color(score)
    chg     = row["change_pct"]
    chg_str = f"{chg:+.2f}%"
    now_str = datetime.now().strftime("%H:%M")

    macd_str = _macd_status(row["dif"], row["dea"])
    ma_trend = "多頭排列" if row["ma5"] > row["ma20"] else "空頭排列"

    # 停利（紅）/ 停損（綠）— 以 ATR 2% 估算
    atr_est  = row["close"] * 0.02
    target   = round(row["close"] + atr_est * 3.0, 2)
    stop     = round(row["close"] - atr_est * 1.5, 2)
    tgt_pct  = round((target - row["close"]) / row["close"] * 100, 1)
    stop_pct = round((stop   - row["close"]) / row["close"] * 100, 1)

    # 法人
    foreign_str = _inst_fmt(row.get("foreign"))
    trust_str   = _inst_fmt(row.get("trust"))
    dealer_str  = _inst_fmt(row.get("dealer"))
    foreign_color = "#2E7D32" if isinstance(row.get("foreign"), (int, float)) and row["foreign"] > 0 else "#C62828"
    trust_color   = "#2E7D32" if isinstance(row.get("trust"),   (int, float)) and row["trust"]   > 0 else "#C62828"
    dealer_color  = "#2E7D32" if isinstance(row.get("dealer"),  (int, float)) and row["dealer"]  > 0 else "#C62828"

    # 操作建議文字
    entry_txt = _entry_strategy(row)
    exit_txt  = _exit_strategy(tgt_pct, stop_pct)

    # ── Header ────────────────────────────────────────
    header = {
        "type": "box",
        "layout": "horizontal",
        "backgroundColor": color,
        "paddingAll": "14px",
        "contents": [
            {
                "type": "box",
                "layout": "vertical",
                "flex": 5,
                "contents": [
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "contents": [
                            {
                                "type": "text",
                                "text": f"#{rank} {row.get('name', row['code'])}",
                                "color": "#FFFFFF",
                                "size": "md",
                                "weight": "bold",
                                "flex": 0,
                                "wrap": True,
                            },
                            {
                                "type": "text",
                                "text": f"  ({row['code']})",
                                "color": "#FFFFFFAA",
                                "size": "sm",
                                "flex": 0,
                            },
                        ],
                    },
                    {
                        "type": "text",
                        "text": f"今日漲幅 {chg_str}　成交 {row['volume_lots']:,} 張",
                        "color": "#FFFFFFAA",
                        "size": "xxs",
                        "margin": "xs",
                        "wrap": True,
                    },
                ],
            },
            {
                "type": "box",
                "layout": "vertical",
                "flex": 3,
                "alignItems": "flex-end",
                "contents": [
                    {
                        "type": "text",
                        "text": f"{score:.0f} 分",
                        "color": "#FFFFFF",
                        "size": "xl",
                        "weight": "bold",
                        "align": "end",
                    },
                    {
                        "type": "text",
                        "text": label,
                        "color": "#FFFFFFCC",
                        "size": "xs",
                        "align": "end",
                        "margin": "xs",
                    },
                ],
            },
        ],
    }

    # ── 現價 + 停利(紅)/停損(綠) ─────────────────────
    price_row = {
        "type": "box",
        "layout": "horizontal",
        "margin": "md",
        "contents": [
            {
                "type": "box",
                "layout": "vertical",
                "flex": 5,
                "contents": [
                    {"type": "text", "text": "現價", "size": "xxs", "color": "#888888"},
                    {
                        "type": "text",
                        "text": f"NT${row['close']:.2f}",
                        "size": "xl",
                        "weight": "bold",
                        "color": "#212121",
                        "adjustMode": "shrink-to-fit",
                    },
                    {"type": "text", "text": now_str, "size": "xxs", "color": "#BBBBBB"},
                ],
            },
            {"type": "separator", "margin": "sm"},
            {
                "type": "box",
                "layout": "vertical",
                "flex": 5,
                "alignItems": "flex-end",
                "contents": [
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "contents": [
                            {"type": "text", "text": "停利", "size": "xxs", "color": "#888888", "flex": 0},
                            {
                                "type": "text",
                                "text": f"  NT${target:.2f}",
                                "size": "sm",
                                "weight": "bold",
                                "color": "#C62828",   # 停利 → 紅色
                                "flex": 0,
                            },
                            {
                                "type": "text",
                                "text": f"  +{tgt_pct:.1f}%",
                                "size": "xs",
                                "color": "#C62828",
                                "flex": 0,
                            },
                        ],
                    },
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "margin": "sm",
                        "contents": [
                            {"type": "text", "text": "停損", "size": "xxs", "color": "#888888", "flex": 0},
                            {
                                "type": "text",
                                "text": f"  NT${stop:.2f}",
                                "size": "sm",
                                "weight": "bold",
                                "color": "#2E7D32",   # 停損 → 綠色
                                "flex": 0,
                            },
                            {
                                "type": "text",
                                "text": f"  {stop_pct:.1f}%",
                                "size": "xs",
                                "color": "#2E7D32",
                                "flex": 0,
                            },
                        ],
                    },
                ],
            },
        ],
    }

    # ── 評分橫條 ──────────────────────────────────────
    score_row = {
        "type": "box",
        "layout": "horizontal",
        "margin": "md",
        "contents": [
            {
                "type": "text",
                "text": f"評分 {score:.0f} / 110",
                "size": "xxs",
                "color": "#666666",
                "flex": 0,
            },
            {
                "type": "box",
                "layout": "vertical",
                "flex": 1,
                "margin": "sm",
                "justifyContent": "center",
                "contents": [_build_score_bar(score)],
            },
        ],
    }

    # ── 技術指標 2×2 ─────────────────────────────────
    def _cell(title: str, value: str, val_color: str) -> dict:
        return {
            "type": "box",
            "layout": "vertical",
            "flex": 1,
            "backgroundColor": "#F8F8F8",
            "cornerRadius": "6px",
            "paddingAll": "8px",
            "contents": [
                {"type": "text", "text": title, "size": "xxs", "color": "#666666"},
                {"type": "text", "text": value, "size": "xs", "weight": "bold", "color": val_color, "margin": "xs"},
            ],
        }

    rsi_color  = "#2E7D32" if 45 <= row["rsi"] <= 70 else "#C62828"
    macd_color = "#2E7D32" if "金叉" in macd_str else "#C62828"
    ma_color   = "#2E7D32" if "多頭" in ma_trend else "#C62828"
    vol_color  = "#E65100" if row["vol_ratio"] >= 3.0 else "#2C3E50"

    indicator_grid = {
        "type": "box",
        "layout": "vertical",
        "margin": "sm",
        "spacing": "sm",
        "contents": [
            {
                "type": "box",
                "layout": "horizontal",
                "spacing": "sm",
                "contents": [
                    _cell("RSI(14)", f"{row['rsi']:.1f}", rsi_color),
                    _cell("MACD", macd_str, macd_color),
                ],
            },
            {
                "type": "box",
                "layout": "horizontal",
                "spacing": "sm",
                "contents": [
                    _cell("均線", "多頭" if "多頭" in ma_trend else "空頭", ma_color),
                    _cell("量比", f"{row['vol_ratio']:.1f}x", vol_color),
                ],
            },
        ],
    }

    # ── 法人籌碼一行 ──────────────────────────────────
    inst_row = {
        "type": "box",
        "layout": "horizontal",
        "margin": "sm",
        "contents": [
            {"type": "text", "text": "外資", "size": "xxs", "color": "#888888", "flex": 1},
            {"type": "text", "text": foreign_str, "size": "xxs", "color": foreign_color, "flex": 2},
            {"type": "text", "text": "投信", "size": "xxs", "color": "#888888", "flex": 1},
            {"type": "text", "text": trust_str, "size": "xxs", "color": trust_color, "flex": 2},
            {"type": "text", "text": "自營", "size": "xxs", "color": "#888888", "flex": 1},
            {"type": "text", "text": dealer_str, "size": "xxs", "color": dealer_color, "flex": 2},
        ],
    }

    # ── 操作建議（綠色背景） ───────────────────────────
    strategy_section = {
        "type": "box",
        "layout": "vertical",
        "margin": "md",
        "backgroundColor": "#E8F5E9",
        "paddingAll": "10px",
        "cornerRadius": "8px",
        "contents": [
            _section_title("📋 操作建議"),
            {"type": "separator", "margin": "xs"},
            {
                "type": "text",
                "text": f"🎯 進場：{entry_txt}",
                "size": "xs",
                "color": "#333333",
                "wrap": True,
                "margin": "sm",
            },
            {
                "type": "text",
                "text": f"🚪 出場：{exit_txt}",
                "size": "xs",
                "color": "#555555",
                "wrap": True,
                "margin": "xs",
            },
            {
                "type": "text",
                "text": "⚠️ 漲停打開或次日跌停請立即出場",
                "size": "xs",
                "color": "#C62828",
                "wrap": True,
                "margin": "sm",
                "weight": "bold",
            },
        ],
    }

    # ── Body ─────────────────────────────────────────
    body = {
        "type": "box",
        "layout": "vertical",
        "paddingAll": "14px",
        "contents": [
            price_row,
            {"type": "separator", "margin": "md"},
            score_row,
            {"type": "separator", "margin": "md"},
            _section_title("📊 技術指標"),
            indicator_grid,
            {"type": "separator", "margin": "md"},
            _section_title("💼 法人籌碼（張）"),
            inst_row,
            strategy_section,
        ],
    }

    # ── Footer ────────────────────────────────────────
    footer = {
        "type": "box",
        "layout": "vertical",
        "backgroundColor": "#F5F5F5",
        "paddingAll": "10px",
        "contents": [
            {
                "type": "text",
                "text": f"⏱ {datetime.now().strftime('%Y-%m-%d %H:%M')}　⚠️ 僅供參考，非投資建議",
                "size": "xxs",
                "color": "#AAAAAA",
                "align": "center",
                "wrap": True,
            },
        ],
    }

    return {
        "type": "bubble",
        "size": "mega",
        "header": header,
        "body": body,
        "footer": footer,
        "styles": {
            "header": {"separator": False},
            "footer": {"separator": True},
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
    """df_top10: surge_analyzer.main() 回傳的 DataFrame（已按 surge_score 降序，僅含 ≥90 分）"""
    try:
        api      = _get_api()
        user_ids = _get_user_ids()
    except RuntimeError as e:
        logger.error("[LINE] 設定錯誤 → %s", e)
        return False

    from linebot.v3.messaging import PushMessageRequest, FlexMessage, FlexContainer

    date_str = datetime.now().strftime("%Y-%m-%d")
    rows = df_top10.to_dict(orient="records")

    bubbles = [_summary_bubble(date_str, len(rows))]
    for rank, row in enumerate(rows, 1):
        bubbles.append(_stock_bubble(row, rank))

    carousel = {"type": "carousel", "contents": bubbles[:12]}
    msg = FlexMessage(
        alt_text=f"🇹🇼 台股暴漲潛力 TOP{len(rows)} — {date_str}",
        contents=FlexContainer.from_dict(carousel),
    )

    success_count = 0
    for uid in user_ids:
        try:
            api.push_message(
                PushMessageRequest(to=uid, messages=[msg])
            )
            logger.info("[LINE] 推播成功 → %s  TOP %d", uid, len(rows))
            success_count += 1
        except Exception as e:
            logger.error("[LINE] 推播失敗 → %s : %s", uid, e)

    return success_count > 0


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
