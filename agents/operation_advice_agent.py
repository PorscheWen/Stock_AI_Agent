"""
🧭 OPERATION ADVICE AGENT — 整體操作建議
根據今日推薦妖股清單做整體評估，輸出：
- 市場節奏（積極/中性/保守）
- 建議操作（進攻/分批/觀望）
- 倉位建議與風險提醒
"""
from dataclasses import dataclass


@dataclass
class OperationAdviceResult:
    market_mode: str
    action: str
    position_guidance: str
    risk_alert: str
    rationale: str


class OperationAdviceAgent:
    """整體操作建議 Agent（規則式，避免額外外部依賴）"""

    def __init__(self):
        self.name = "OperationAdviceAgent"

    def run(self, stocks: list[dict]) -> OperationAdviceResult:
        if not stocks:
            return OperationAdviceResult(
                market_mode="保守",
                action="今日無通過標的，建議觀望等待下一個確認訊號。",
                position_guidance="總倉位 0%~10%，保留現金。",
                risk_alert="避免為了交易而交易，優先等待量價與題材共振。",
                rationale="缺乏通過驗證的強勢標的，勝率不足。",
            )

        top_n = min(len(stocks), 4)
        selected = stocks[:top_n]

        avg_conf = sum(s["scores"]["confidence"] for s in selected) / top_n
        avg_mom = sum(s["scores"]["momentum"] for s in selected) / top_n
        avg_cat = sum(s["scores"]["catalyst"] for s in selected) / top_n
        avg_rr = sum(s["risk"]["risk_reward_ratio"] for s in selected) / top_n
        high_risk_count = sum(1 for s in selected if s["risk"]["level"] >= 4)

        if avg_conf >= 75 and avg_mom >= 70 and avg_cat >= 65 and high_risk_count <= 1:
            market_mode = "積極"
            action = "可主動布局前 1~2 強勢股，採分批進場與移動停利。"
            position_guidance = "總倉位 50%~70%，單檔不超過 25%。"
        elif avg_conf >= 60 and avg_rr >= 2.0:
            market_mode = "中性"
            action = "以試單為主，優先做最強股的回檔承接，控制節奏。"
            position_guidance = "總倉位 30%~50%，單檔不超過 20%。"
        else:
            market_mode = "保守"
            action = "僅觀察或極小倉位試單，避免追高。"
            position_guidance = "總倉位 10%~30%，單檔不超過 10%。"

        risk_alert = (
            "若任一持股跌破停損，應立即執行風控；連續 2 筆停損後當日停止加碼。"
            if high_risk_count >= 1
            else "留意隔日開盤量能是否延續，量縮不漲時避免加碼。"
        )
        rationale = (
            f"前{top_n}檔平均信心 {avg_conf:.0f}%，"
            f"動能 {avg_mom:.0f}，催化劑 {avg_cat:.0f}，風報比 {avg_rr:.1f}。"
        )

        return OperationAdviceResult(
            market_mode=market_mode,
            action=action,
            position_guidance=position_guidance,
            risk_alert=risk_alert,
            rationale=rationale,
        )
