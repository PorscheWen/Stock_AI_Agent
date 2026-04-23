"""
🎯 ENTRY AGENT — 進場策略
結合板數、動能、催化劑，給出具體進場建議：
- 第幾板最佳進場
- 進場方式（漲停追進 / 集合競價 / 回踩 MA5）
- 具體進場價格區間
- 是否值得進場的綜合判斷
輸出：EntryResult（進場建議）
"""
import logging
from dataclasses import dataclass
from typing import Optional

import pandas as pd
import yfinance as yf

from config.settings import (
    MAX_BOARD_ENTRY,
    ENTRY_MA_PERIOD,
    BOARD_POSITION_PCT,
)

logger = logging.getLogger(__name__)


@dataclass
class EntryResult:
    symbol: str
    should_enter: bool         # 是否建議進場
    entry_method: str          # 進場方式說明
    entry_price_low: float     # 建議進場價下限
    entry_price_high: float    # 建議進場價上限
    board_number: int          # 當前板數
    timing: str                # 進場時機說明
    position_pct: float        # 建議倉位 %
    reason: str = ""           # 推薦/不推薦原因


class EntryAgent:
    """進場策略 Agent"""

    def __init__(self):
        self.name = "EntryAgent"

    # ── 公開介面 ─────────────────────────────────────────
    def run(self, candidates: list[dict]) -> dict[str, EntryResult]:
        """
        candidates: 每個 dict 包含
          symbol, close, consecutive_days, momentum_score,
          catalyst_score, volume_ratio, is_limit_up
        """
        results = {}
        for c in candidates:
            symbol = c["symbol"]
            try:
                result = self._decide(c)
                results[symbol] = result
                action = "✅ 建議進場" if result.should_enter else "⏸️  觀望"
                logger.info(
                    f"[Entry] {symbol} {action} "
                    f"方式={result.entry_method[:20]} "
                    f"倉位={result.position_pct:.0%}"
                )
            except Exception as e:
                logger.warning(f"[Entry] {symbol} 策略失敗：{e}")
        return results

    # ── 內部方法 ─────────────────────────────────────────
    def _fetch_ma5(self, symbol: str) -> Optional[float]:
        """取得 MA5 支撐價位"""
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="15d")
            if df.empty or len(df) < 5:
                return None
            return float(df["Close"].tail(5).mean())
        except Exception:
            return None

    def _decide(self, c: dict) -> EntryResult:
        symbol     = c["symbol"]
        close      = c["close"]
        boards     = c.get("consecutive_days", 1)
        momentum   = c.get("momentum_score", 50.0)
        catalyst   = c.get("catalyst_score", 50.0)
        vol_ratio  = c.get("volume_ratio", 1.0)
        is_limit_up = c.get("is_limit_up", False)

        # ── 基本篩選：超過追板上限或動能弱 ───────────────
        if boards > MAX_BOARD_ENTRY:
            return EntryResult(
                symbol=symbol,
                should_enter=False,
                entry_method="不追",
                entry_price_low=0,
                entry_price_high=0,
                board_number=boards,
                timing="第 4 板以後不追，等回踩確認",
                position_pct=0.0,
                reason=f"已達第 {boards} 板，超過追板上限 {MAX_BOARD_ENTRY} 板",
            )

        if momentum < 40 or catalyst < 30:
            return EntryResult(
                symbol=symbol,
                should_enter=False,
                entry_method="觀望",
                entry_price_low=0,
                entry_price_high=0,
                board_number=boards,
                timing="動能或題材評分不足",
                position_pct=0.0,
                reason=f"動能={momentum:.0f} 催化劑={catalyst:.0f}，條件不足",
            )

        pos_pct = BOARD_POSITION_PCT.get(boards, 0.10)

        # ── 第 1 板進場策略 ───────────────────────────────
        if boards == 1:
            if catalyst >= 70 and vol_ratio >= 8:
                method = "今日收盤前漲停板掛買"
                timing = "14:25 前掛漲停價委買，若成交即持有"
                low    = round(close * 1.095, 2)
                high   = round(close * 1.10, 2)
                enter  = True
                reason = f"強題材（{catalyst:.0f}分）+ 超級爆量（{vol_ratio:.1f}x），第一板值得卡位"
            else:
                # 等次日開盤確認
                ma5 = self._fetch_ma5(symbol) or close * 0.97
                method = "等次日開盤集合競價或回踩 MA5"
                timing = "次日開盤若高開 ≥ 3%，集合競價追；若平開回踩 MA5 不破再買"
                low    = round(ma5 * 0.99, 2)
                high   = round(close * 1.05, 2)
                enter  = True
                reason = "第 1 板，建議等次日開盤確認強度再進"

        # ── 第 2 板進場策略（最佳進場）────────────────────
        elif boards == 2:
            if is_limit_up:
                method = "次日開盤集合競價追漲停"
                timing = "集合競價 9:00 前掛漲停價委買，確保排隊在前段"
            else:
                ma5 = self._fetch_ma5(symbol) or close * 0.95
                method = f"回踩 MA5（{ma5:.2f}）附近買進"
                timing = f"等待股價回踩至 {ma5:.2f} 附近，不破即進場"
            low    = round(close * 0.97, 2)
            high   = round(close * 1.10, 2)
            enter  = True
            reason = "第 2 板為妖股最佳進場時機，動能確認、風報比最優"

        # ── 第 3 板進場策略（謹慎） ────────────────────────
        else:  # boards == 3
            if momentum >= 75 and catalyst >= 70:
                method = "缺口不破隔日再追"
                timing = "次日開盤若不回補缺口，可小倉追；若跌破昨日低點立即出場"
                low    = round(close * 1.00, 2)
                high   = round(close * 1.05, 2)
                enter  = True
                reason = f"第 3 板高風險，動能={momentum:.0f}+題材={catalyst:.0f}仍強，小倉參與"
                pos_pct = min(pos_pct, 0.08)  # 第 3 板最多 8%
            else:
                method = "觀望不追"
                timing = "第 3 板且動能/題材不夠強，風報比不佳"
                low    = 0
                high   = 0
                enter  = False
                reason = f"第 3 板動能={momentum:.0f} 催化劑={catalyst:.0f}，不符合追板條件"

        return EntryResult(
            symbol=symbol,
            should_enter=enter,
            entry_method=method,
            entry_price_low=low,
            entry_price_high=high,
            board_number=boards,
            timing=timing,
            position_pct=pos_pct if enter else 0.0,
            reason=reason,
        )
