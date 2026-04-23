"""
🚪 EXIT AGENT — 出場策略
針對持倉妖股制定出場計劃：
- 分批出場點位（+1 板減半，+2 板清倉）
- 移動停損觸發條件
- 緊急出場條件（漲停打開 / 落板 / 大盤急跌）
- 最大持倉天數控制
輸出：ExitResult（出場策略）
"""
import logging
from dataclasses import dataclass, field

from config.settings import (
    EXIT_TARGET_BOARDS,
    EXIT_PARTIAL_PCT,
    EXIT_TRAILING_PCT,
    EXIT_MAX_HOLD_DAYS,
    EXIT_PROFIT_TARGET,
    LIMIT_UP_PCT,
    MAX_STOP_LOSS_PCT,
)

logger = logging.getLogger(__name__)


@dataclass
class ExitResult:
    symbol: str
    stop_loss_price: float       # 硬停損價（跌破立即出場）
    stop_loss_pct: float         # 停損幅度 %
    target_price_1: float        # 第一目標（+1板，減半倉）
    target_price_2: float        # 第二目標（+2板，清倉）
    trailing_stop_pct: float     # 移動停損幅度 %
    max_hold_days: int           # 最大持倉天數
    emergency_rules: list = field(default_factory=list)  # 緊急出場觸發條件
    partial_exit_plan: list = field(default_factory=list)  # 分批出場計劃
    summary: str = ""            # 出場策略摘要


class ExitAgent:
    """出場策略 Agent"""

    def __init__(self):
        self.name = "ExitAgent"

    # ── 公開介面 ─────────────────────────────────────────
    def run(self, candidates: list[dict]) -> dict[str, ExitResult]:
        """
        candidates: 每個 dict 包含
          symbol, close, consecutive_days, risk_stop_loss_pct
        """
        results = {}
        for c in candidates:
            symbol = c["symbol"]
            try:
                result = self._plan(c)
                results[symbol] = result
                logger.info(
                    f"[Exit] {symbol} 停損={result.stop_loss_pct:.1f}% "
                    f"目標1={result.target_price_1:.2f} "
                    f"目標2={result.target_price_2:.2f}"
                )
            except Exception as e:
                logger.warning(f"[Exit] {symbol} 策略失敗：{e}")
        return results

    # ── 內部方法 ─────────────────────────────────────────
    def _plan(self, c: dict) -> ExitResult:
        symbol    = c["symbol"]
        close     = c["close"]
        boards    = c.get("consecutive_days", 1)
        stop_pct  = c.get("risk_stop_loss_pct", MAX_STOP_LOSS_PCT * 100)

        # 確保停損不超過最大限制
        stop_pct  = min(stop_pct, MAX_STOP_LOSS_PCT * 100)
        stop_price = round(close * (1 - stop_pct / 100), 2)

        # 目標價：每板 +10%
        limit_up_mult = 1 + LIMIT_UP_PCT / 100
        target_1 = round(close * limit_up_mult, 2)        # +1 板
        target_2 = round(close * (limit_up_mult ** 2), 2) # +2 板

        # 緊急出場規則
        emergency_rules = [
            "漲停板被打開（封單消失）→ 立即出場，不等收盤",
            "次日跌停（落板）→ 開盤即出，不作任何等待",
            f"大盤當日跌幅超過 -2% → 減至半倉保護獲利",
            f"持倉超過 {EXIT_MAX_HOLD_DAYS} 天仍未再創高 → 清倉觀望",
            f"達到最高獲利目標 +{EXIT_PROFIT_TARGET*100:.0f}% → 全部出場，不戀戰",
        ]

        # 分批出場計劃
        partial_exit_plan = [
            {
                "trigger": f"股價達到 {target_1:.2f}（+1 板 +{LIMIT_UP_PCT:.0f}%）",
                "action":  f"出場 {EXIT_PARTIAL_PCT*100:.0f}%，剩餘部位轉移動停損",
            },
            {
                "trigger": f"股價達到 {target_2:.2f}（+2 板 +{LIMIT_UP_PCT*2:.0f}%以上）",
                "action":  "全部出場，本波結束",
            },
            {
                "trigger": f"移動停損觸發（最高點回落 {EXIT_TRAILING_PCT*100:.0f}%）",
                "action":  "剩餘倉位出場",
            },
        ]

        # 高板數調整策略
        if boards >= 3:
            summary = (
                f"第 {boards} 板高風險：目標更保守，"
                f"到達 {target_1:.2f} 即出場 70%，"
                f"剩餘設 {EXIT_TRAILING_PCT*100:.0f}% 移動停損"
            )
            # 高板數提前出場更多
            partial_exit_plan[0]["action"] = "出場 70%，剩餘部位移動停損"
        else:
            summary = (
                f"分批出場：到 {target_1:.2f} 出一半，"
                f"到 {target_2:.2f} 全清；"
                f"跌破 {stop_price:.2f} 硬停損"
            )

        return ExitResult(
            symbol=symbol,
            stop_loss_price=stop_price,
            stop_loss_pct=round(stop_pct, 2),
            target_price_1=target_1,
            target_price_2=target_2,
            trailing_stop_pct=EXIT_TRAILING_PCT * 100,
            max_hold_days=EXIT_MAX_HOLD_DAYS,
            emergency_rules=emergency_rules,
            partial_exit_plan=partial_exit_plan,
            summary=summary,
        )
