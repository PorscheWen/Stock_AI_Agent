"""
📲 LINE NOTIFIER — 妖股報告推播
將妖股選股報告推播至 LINE Bot（Flex Message 卡片式）
"""
import json
import logging
import os

from dotenv import load_dotenv
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    FlexContainer,
    FlexMessage,
    MessagingApi,
    MulticastRequest,
    PushMessageRequest,
    TextMessage,
)

load_dotenv()
logger = logging.getLogger(__name__)

_RISK_COLORS = {1: "#27AE60", 2: "#2ECC71", 3: "#F39C12", 4: "#E74C3C", 5: "#8E44AD"}
_BOARD_COLORS = {1: "#3498DB", 2: "#27AE60", 3: "#E67E22", 4: "#E74C3C"}


def _get_api() -> MessagingApi:
    """建立 MessagingApi，使用 CHANNEL_STOCK_ACCESS_TOKEN（對齊 ETF repo）"""
    token = os.environ.get("CHANNEL_STOCK_ACCESS_TOKEN", "")
    if not token:
        raise RuntimeError("CHANNEL_STOCK_ACCESS_TOKEN 未設定")
    return MessagingApi(ApiClient(Configuration(access_token=token)))


def _get_user_ids() -> list[str]:
    """
    訂閱者清單讀取順序（對齊 ETF repo line_push.py）：
    1. CHANNEL_STOCK_USER_IDS 環境變數（逗號分隔，支援多人）
    2. CHANNEL_STOCK_USER_ID 環境變數（單人向下相容）
    """
    ids_env = os.environ.get("CHANNEL_STOCK_USER_IDS", "")
    if ids_env:
        ids = [uid.strip() for uid in ids_env.split(",") if uid.strip()]
        if ids:
            logger.info("[LINE] 從 CHANNEL_STOCK_USER_IDS 讀取 %d 人", len(ids))
            return ids

    single = os.environ.get("CHANNEL_STOCK_USER_ID", "").strip()
    if single:
        return [single]

    raise RuntimeError(
        "推播目標未設定：請設定 CHANNEL_STOCK_USER_IDS 或 CHANNEL_STOCK_USER_ID"
    )


def _send(api: MessagingApi, user_ids: list[str], messages: list) -> None:
    """單人用 push_message，多人用 multicast（每批 ≤500）。"""
    if len(user_ids) == 1:
        api.push_message(PushMessageRequest(to=user_ids[0], messages=messages))
    else:
        for i in range(0, len(user_ids), 500):
            api.multicast(MulticastRequest(to=user_ids[i:i + 500], messages=messages))


def _star_bar(score: float) -> str:
    filled = round(score / 20)
    return "★" * filled + "☆" * (5 - filled)


def _board_label(boards: int) -> str:
    labels = {1: "1⃣ 第一板", 2: "2⃣ 第二板", 3: "3⃣ 第三板", 4: "4⃣ 第四板"}
    return labels.get(boards, f"{boards}板")


def _market_badge(is_otc: bool) -> dict:
    """上市/上櫃市場標籤元件"""
    if is_otc:
        return {
            "type": "box", "layout": "horizontal",
            "backgroundColor": "#7D3C98", "paddingAll": "4px",
            "cornerRadius": "4px", "width": "40px",
            "contents": [
                {"type": "text", "text": "上櫃", "size": "xxs",
                 "color": "#FFFFFF", "align": "center", "weight": "bold"},
            ],
        }
    return {
        "type": "box", "layout": "horizontal",
        "backgroundColor": "#1A5276", "paddingAll": "4px",
        "cornerRadius": "4px", "width": "40px",
        "contents": [
            {"type": "text", "text": "上市", "size": "xxs",
             "color": "#FFFFFF", "align": "center", "weight": "bold"},
        ],
    }


def _build_stock_bubble(s: dict, rank: int = 0) -> dict:
    """每檔妖股一個 Flex Bubble"""
    sc    = s["scores"]
    risk  = s["risk"]
    entry = s["entry"]
    exit_ = s["exit"]
    val   = s["validation"]
    conf  = sc["confidence"]
    boards = s.get("consecutive_days", 1)
    is_otc = risk.get("is_otc", False)
    otc_warnings = risk.get("otc_risk_warnings", [])

    header_color = _BOARD_COLORS.get(min(boards, 4), "#E74C3C")
    risk_color   = _RISK_COLORS.get(risk["level"], "#95A5A6")
    rank_prefix  = f"#{rank} " if rank else ""

    # 股票代號顯示（去除 .TW / .TWO suffix）
    display_code = s["symbol"].replace(".TWO", "").replace(".TW", "")

    body_contents = [
        # 評分列
        {
            "type": "box", "layout": "horizontal", "spacing": "sm",
            "contents": [
                {"type": "text", "text": "動能", "size": "xs", "color": "#888", "flex": 1},
                {"type": "text", "text": "催化劑", "size": "xs", "color": "#888", "flex": 1},
                {"type": "text", "text": "信心", "size": "xs", "color": "#888", "flex": 1},
            ],
        },
        {
            "type": "box", "layout": "horizontal", "spacing": "sm",
            "contents": [
                {"type": "text", "text": f"{sc['momentum']:.0f}", "size": "md", "weight": "bold", "flex": 1},
                {"type": "text", "text": f"{sc['catalyst']:.0f}", "size": "md", "weight": "bold", "flex": 1},
                {"type": "text", "text": f"{conf:.0f}%", "size": "md", "weight": "bold",
                 "color": "#27AE60" if conf >= 65 else "#E74C3C", "flex": 1},
            ],
        },
        {"type": "separator", "margin": "sm"},
        # 量比 + 風報比
        {
            "type": "box", "layout": "horizontal",
            "contents": [
                {"type": "text", "text": "量比", "size": "xs", "color": "#888", "flex": 1},
                {"type": "text", "text": f"{s['volume_ratio']:.1f}x",
                 "size": "sm", "weight": "bold", "flex": 2},
                {"type": "text", "text": "風報比", "size": "xs", "color": "#888", "flex": 1},
                {"type": "text", "text": f"{risk['risk_reward_ratio']:.1f}:1",
                 "size": "sm", "weight": "bold", "flex": 2},
            ],
        },
        # 進場建議
        {
            "type": "box", "layout": "vertical",
            "backgroundColor": "#E8F5E9", "paddingAll": "10px",
            "cornerRadius": "8px", "margin": "sm",
            "contents": [
                {"type": "text", "text": "🎯 進場建議", "size": "xs", "weight": "bold", "color": "#2E7D32"},
                {"type": "text", "text": entry["method"],
                 "size": "xs", "color": "#333", "wrap": True, "margin": "xs"},
                {"type": "text", "text": entry["timing"],
                 "size": "xs", "color": "#555", "wrap": True, "margin": "xs"},
            ],
        },
        # 出場計劃
        {
            "type": "box", "layout": "vertical",
            "backgroundColor": "#FFF3E0", "paddingAll": "10px",
            "cornerRadius": "8px",
            "contents": [
                {"type": "text", "text": "🚪 出場計劃", "size": "xs", "weight": "bold", "color": "#E65100"},
                {"type": "text", "text": exit_["summary"],
                 "size": "xs", "color": "#333", "wrap": True, "margin": "xs"},
                {"type": "text",
                 "text": f"停損 ${risk['stop_loss_price']:,.2f}（-{risk['stop_loss_pct']:.1f}%）",
                 "size": "xs", "color": "#E74C3C", "margin": "xs"},
            ],
        },
        # 驗證結果
        {
            "type": "box", "layout": "horizontal", "margin": "sm",
            "contents": [
                {"type": "text",
                 "text": f"{'✅' if val['check1'] else '❌'} 動能  "
                         f"{'✅' if val['check2'] else '❌'} 風控  "
                         f"{'✅' if val['check3'] else '❌'} 空方",
                 "size": "xs", "color": "#555", "wrap": True},
            ],
        },
    ]

    # 上櫃特有風險警示區塊（最多顯示前 3 條）
    if is_otc and otc_warnings:
        warning_items = [
            {"type": "text", "text": "⚠️ 上櫃特有風險", "size": "xs",
             "weight": "bold", "color": "#6C3483"},
        ]
        for w in otc_warnings[:3]:
            # 截取前 40 字，避免 LINE 卡片過長
            short = w[:60] + "…" if len(w) > 60 else w
            warning_items.append({
                "type": "text", "text": f"• {short}",
                "size": "xxs", "color": "#5D4037", "wrap": True, "margin": "xs",
            })
        body_contents.append({
            "type": "box", "layout": "vertical",
            "backgroundColor": "#F3E5F5", "paddingAll": "10px",
            "cornerRadius": "8px", "margin": "sm",
            "contents": warning_items,
        })

    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": header_color,
            "paddingAll": "16px",
            "contents": [
                {
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {
                            "type": "box", "layout": "vertical", "flex": 1,
                            "contents": [
                                {
                                    "type": "box", "layout": "horizontal",
                                    "spacing": "sm", "margin": "none",
                                    "contents": [
                                        _market_badge(is_otc),
                                        {"type": "text",
                                         "text": f"{rank_prefix}{display_code} {s['name']}",
                                         "size": "lg", "weight": "bold",
                                         "color": "#FFFFFF", "flex": 1},
                                    ],
                                },
                                {"type": "text", "text": _board_label(boards),
                                 "size": "sm", "color": "#FFFFFF", "margin": "xs"},
                            ],
                        },
                        {
                            "type": "box", "layout": "vertical", "flex": 0,
                            "contents": [
                                {"type": "text", "text": f"${s['close']:,.1f}",
                                 "size": "xl", "weight": "bold", "color": "#FFFFFF", "align": "end"},
                                {"type": "text", "text": f"+{s['pct_change']:.1f}%",
                                 "size": "md", "color": "#FFD700", "align": "end"},
                            ],
                        },
                    ],
                },
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "paddingAll": "14px",
            "contents": body_contents,
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": risk_color,
            "paddingAll": "10px",
            "contents": [
                {"type": "text",
                 "text": (
                     f"{'[上櫃] ' if is_otc else ''}"
                     f"{risk['risk_label']} — 建議倉位 {risk['position_pct']:.0%}"
                 ),
                 "size": "xs", "color": "#FFFFFF", "align": "center"},
            ],
        },
    }


def _build_summary_bubble(report: dict) -> dict:
    """總覽摘要 Bubble（含上市/上櫃分別計數）"""
    date       = report["generated_at"][:10]
    cnt_twse   = report.get("total_candidates_twse", 0)
    cnt_tpex   = report.get("total_candidates_tpex", 0)
    ai_summary = report.get("ai_summary", "")
    summary_short = ai_summary[:180] + "..." if len(ai_summary) > 180 else ai_summary

    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box", "layout": "vertical",
            "backgroundColor": "#2C3E50", "paddingAll": "16px",
            "contents": [
                {"type": "text", "text": "🚀 妖股每日報告", "size": "lg",
                 "weight": "bold", "color": "#FFFFFF"},
                {"type": "text", "text": date, "size": "sm", "color": "#BDC3C7", "margin": "xs"},
            ],
        },
        "body": {
            "type": "box", "layout": "vertical", "spacing": "md", "paddingAll": "16px",
            "contents": [
                {
                    "type": "box", "layout": "horizontal", "spacing": "sm",
                    "contents": [
                        {
                            "type": "box", "layout": "vertical", "flex": 1,
                            "backgroundColor": "#E3F2FD", "paddingAll": "12px",
                            "cornerRadius": "8px",
                            "contents": [
                                {"type": "text", "text": "🏦 上市",
                                 "size": "xs", "color": "#1A5276", "align": "center", "weight": "bold"},
                                {"type": "text", "text": f"{cnt_twse} 檔",
                                 "size": "xxl", "weight": "bold",
                                 "color": "#1565C0" if cnt_twse > 0 else "#9E9E9E",
                                 "align": "center"},
                            ],
                        },
                        {
                            "type": "box", "layout": "vertical", "flex": 1,
                            "backgroundColor": "#F3E5F5", "paddingAll": "12px",
                            "cornerRadius": "8px",
                            "contents": [
                                {"type": "text", "text": "🏪 上櫃",
                                 "size": "xs", "color": "#6C3483", "align": "center", "weight": "bold"},
                                {"type": "text", "text": f"{cnt_tpex} 檔",
                                 "size": "xxl", "weight": "bold",
                                 "color": "#7B1FA2" if cnt_tpex > 0 else "#9E9E9E",
                                 "align": "center"},
                            ],
                        },
                        {
                            "type": "box", "layout": "vertical", "flex": 1,
                            "backgroundColor": "#EAFAF1", "paddingAll": "12px",
                            "cornerRadius": "8px",
                            "contents": [
                                {"type": "text", "text": "耗時",
                                 "size": "xs", "color": "#888", "align": "center"},
                                {"type": "text", "text": f"{report['elapsed_seconds']}s",
                                 "size": "xxl", "weight": "bold",
                                 "color": "#27AE60", "align": "center"},
                            ],
                        },
                    ],
                },
                {
                    "type": "text",
                    "text": summary_short or "今日掃描完成，請查看個股報告",
                    "size": "xs", "color": "#555", "wrap": True, "margin": "md",
                },
            ],
        },
    }


def push_report(report: dict) -> bool:
    """推播妖股報告至 LINE Bot（上市/上櫃各自一則 Flex Message）"""
    try:
        api      = _get_api()
        user_ids = _get_user_ids()
    except RuntimeError as e:
        logger.warning("[LINE] %s，跳過推播", e)
        return False

    try:
        date_str   = report["generated_at"][:10]
        stocks_tw  = report.get("stocks_twse", [])
        stocks_otc = report.get("stocks_tpex", [])

        # 若新欄位不存在（舊格式相容），退回全部一起處理
        if not stocks_tw and not stocks_otc:
            stocks_tw = report.get("stocks", [])

        messages = []

        # ── 訊息 1：摘要 + 上市股票 ──────────────────────
        twse_bubbles = [_build_summary_bubble(report)]
        for rank, s in enumerate(
            sorted(stocks_tw, key=lambda x: x["scores"]["confidence"], reverse=True), 1
        ):
            twse_bubbles.append(_build_stock_bubble(s, rank))
        messages.append(FlexMessage(
            alt_text=(
                f"🏦 上市妖股 {date_str} — "
                f"{len(stocks_tw)} 檔 | 上櫃 {len(stocks_otc)} 檔通過驗證"
            ),
            contents=FlexContainer.from_dict(
                {"type": "carousel", "contents": twse_bubbles[:12]}
            ),
        ))

        # ── 訊息 2：上櫃股票（有才送）────────────────────
        if stocks_otc:
            otc_bubbles = []
            for rank, s in enumerate(
                sorted(stocks_otc, key=lambda x: x["scores"]["confidence"], reverse=True), 1
            ):
                otc_bubbles.append(_build_stock_bubble(s, rank))
            messages.append(FlexMessage(
                alt_text=f"🏪 上櫃妖股 {date_str} — {len(stocks_otc)} 檔通過驗證",
                contents=FlexContainer.from_dict(
                    {"type": "carousel", "contents": otc_bubbles[:12]}
                ),
            ))

        _send(api, user_ids, messages[:5])  # LINE 每次 push 上限 5 則
        logger.info(
            "[LINE] 推播成功，上市 %d 檔 + 上櫃 %d 檔（%d 人）",
            len(stocks_tw), len(stocks_otc), len(user_ids),
        )
        return True

    except Exception as e:
        logger.error("[LINE] 推播失敗：%s", e)
        return False


def push_text(message: str) -> None:
    """推播純文字訊息給所有訂閱者（用於錯誤通知）"""
    try:
        api      = _get_api()
        user_ids = _get_user_ids()
        _send(api, user_ids, [TextMessage(text=message)])
    except Exception as e:
        logger.error("[LINE] 文字推播失敗：%s", e)
