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


def _build_stock_bubble(s: dict, rank: int = 0) -> dict:
    """每檔妖股一個 Flex Bubble"""
    sc    = s["scores"]
    risk  = s["risk"]
    entry = s["entry"]
    exit_ = s["exit"]
    val   = s["validation"]
    conf  = sc["confidence"]
    boards = s.get("consecutive_days", 1)

    header_color = _BOARD_COLORS.get(min(boards, 4), "#E74C3C")
    risk_color   = _RISK_COLORS.get(risk["level"], "#95A5A6")
    rank_prefix  = f"#{rank} " if rank else ""

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
                                {"type": "text", "text": f"{rank_prefix}{s['symbol'].replace('.TW','')} {s['name']}",
                                 "size": "lg", "weight": "bold", "color": "#FFFFFF"},
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
            "contents": [
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
                # 量比
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
            ],
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": risk_color,
            "paddingAll": "10px",
            "contents": [
                {"type": "text",
                 "text": f"{risk['risk_label']} — 建議倉位 {risk['position_pct']:.0%}",
                 "size": "xs", "color": "#FFFFFF", "align": "center"},
            ],
        },
    }


def _build_summary_bubble(report: dict) -> dict:
    """總覽摘要 Bubble"""
    date  = report["generated_at"][:10]
    total = report["total_candidates"]
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
                    "type": "box", "layout": "horizontal",
                    "contents": [
                        {
                            "type": "box", "layout": "vertical", "flex": 1,
                            "backgroundColor": "#EBF5FB", "paddingAll": "12px",
                            "cornerRadius": "8px",
                            "contents": [
                                {"type": "text", "text": "通過驗證", "size": "xs", "color": "#888", "align": "center"},
                                {"type": "text", "text": f"{total} 檔", "size": "xxl",
                                 "weight": "bold", "color": "#2980B9", "align": "center"},
                            ],
                        },
                        {"type": "box", "layout": "vertical", "flex": 0, "width": "12px", "contents": []},
                        {
                            "type": "box", "layout": "vertical", "flex": 1,
                            "backgroundColor": "#EAFAF1", "paddingAll": "12px",
                            "cornerRadius": "8px",
                            "contents": [
                                {"type": "text", "text": "耗時", "size": "xs", "color": "#888", "align": "center"},
                                {"type": "text", "text": f"{report['elapsed_seconds']}s", "size": "xxl",
                                 "weight": "bold", "color": "#27AE60", "align": "center"},
                            ],
                        },
                    ],
                },
                {
                    "type": "text", "text": summary_short or "今日掃描完成，請查看個股報告",
                    "size": "xs", "color": "#555", "wrap": True, "margin": "md",
                },
            ],
        },
    }


def push_report(report: dict) -> bool:
    """推播妖股報告至 LINE Bot（支援單人/多人）"""
    try:
        api      = _get_api()
        user_ids = _get_user_ids()
    except RuntimeError as e:
        logger.warning("[LINE] %s，跳過推播", e)
        return False

    try:
        stocks = sorted(
            report["stocks"],
            key=lambda x: x["scores"]["confidence"],
            reverse=True,
        )

        bubbles = [_build_summary_bubble(report)]
        for rank, s in enumerate(stocks, 1):
            bubbles.append(_build_stock_bubble(s, rank))

        carousel = {"type": "carousel", "contents": bubbles[:12]}
        messages = [
            FlexMessage(
                alt_text=f"🚀 妖股報告 {report['generated_at'][:10]} — {report['total_candidates']} 檔通過驗證",
                contents=FlexContainer.from_dict(carousel),
            )
        ]
        _send(api, user_ids, messages)
        logger.info("[LINE] 推播成功，共 %d 檔（%d 人）", len(stocks), len(user_ids))
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
