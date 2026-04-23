"""
⚡ MOMENTUM AGENT — 動能分析
針對妖股候選深入分析連板強度：
- 漲停打開次數（越少越強）
- 封板時間（越早越強）
- 換手率分析（籌碼集中度）
- 板塊/題材同步強度
輸出：動能評分 0-100 + 詳細說明
"""
import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

from config.settings import (
    LIMIT_UP_PCT,
    MOMENTUM_OPEN_BREAK_LIMIT,
    MOMENTUM_MIN_SCORE,
)

logger = logging.getLogger(__name__)


@dataclass
class MomentumResult:
    symbol: str
    consecutive_days: int      # 連板天數
    open_break_count: int      # 漲停打開次數（0 = 從未被打開）
    avg_turnover_rate: float   # 平均換手率 %（近 3 日）
    momentum_score: float      # 動能評分 0-100
    board_strength: str        # "強勢" / "中等" / "弱勢"
    signals: list = field(default_factory=list)
    warning: str = ""          # 風險警示


class MomentumAgent:
    """動能分析 Agent"""

    def __init__(self):
        self.name = "MomentumAgent"

    # ── 公開介面 ─────────────────────────────────────────
    def run(self, symbols: list[str]) -> dict[str, MomentumResult]:
        results = {}
        for symbol in symbols:
            try:
                result = self._analyze(symbol)
                if result:
                    results[symbol] = result
                    logger.info(
                        f"[Momentum] {symbol} 連板={result.consecutive_days} "
                        f"打開={result.open_break_count} 評分={result.momentum_score:.1f}"
                    )
            except Exception as e:
                logger.warning(f"[Momentum] {symbol} 分析失敗：{e}")
        return results

    # ── 內部方法 ─────────────────────────────────────────
    def _fetch(self, symbol: str) -> Optional[pd.DataFrame]:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="30d")
        if df.empty or len(df) < 5:
            return None
        return df

    def _analyze(self, symbol: str) -> Optional[MomentumResult]:
        df = self._fetch(symbol)
        if df is None:
            return None

        close  = df["Close"]
        high   = df["High"]
        low    = df["Low"]
        volume = df["Volume"]

        # ── 計算連板天數 ──────────────────────────────────
        consecutive = 0
        for i in range(len(close) - 1, 0, -1):
            prev = float(close.iloc[i - 1])
            curr = float(close.iloc[i])
            if prev > 0 and (curr - prev) / prev * 100 >= LIMIT_UP_PCT:
                consecutive += 1
            else:
                break

        # ── 計算漲停打開次數 ──────────────────────────────
        # 漲停日：收盤漲幅 ≥ 9.5%；若當日最高 > 漲停價但收盤 = 漲停 → 封板
        # 漲停被打開：當日開高但收盤未達漲停
        open_break_count = 0
        limit_up_days = []
        n = min(len(close), 20)
        for i in range(len(close) - n, len(close)):
            prev_c = float(close.iloc[i - 1]) if i > 0 else float(close.iloc[i])
            curr_c = float(close.iloc[i])
            curr_h = float(high.iloc[i])
            if prev_c > 0:
                pct = (curr_c - prev_c) / prev_c * 100
                limit_price = round(prev_c * 1.10, 2)
                if pct >= LIMIT_UP_PCT:
                    limit_up_days.append(i)
                    # 盤中打開過但最終收漲停
                    if curr_h > limit_price * 1.001:
                        open_break_count += 1  # 曾被打開但最終收回

        # ── 換手率（近 3 日均值） ─────────────────────────
        # 換手率 ≈ 成交量（股）/ 流通股數，簡化：用成交量 / 市值代理
        recent_vols = volume.iloc[-3:].values
        avg_vol_20  = float(volume.tail(20).mean())
        turnover_proxy = float(np.mean(recent_vols)) / avg_vol_20 if avg_vol_20 > 0 else 1.0
        avg_turnover_rate = round(turnover_proxy * 100, 1)  # 相對換手率指數

        # ── 動能評分 ──────────────────────────────────────
        score = 50.0
        signals = []
        warning = ""

        # 連板加分
        if consecutive >= 3:
            score += 25
            signals.append(f"強勢連板 {consecutive} 天")
        elif consecutive == 2:
            score += 15
            signals.append(f"連板 {consecutive} 天")
        elif consecutive == 1:
            score += 5
            signals.append("今日漲停")
        else:
            score -= 15

        # 漲停打開次數
        if open_break_count == 0 and consecutive >= 2:
            score += 20
            signals.append("從未被打開（一字板）")
        elif open_break_count <= 1:
            score += 10
        else:
            score -= open_break_count * 8
            warning = f"漲停已被打開 {open_break_count} 次，動能轉弱"

        # 換手率：換手率高 = 籌碼活躍
        if avg_turnover_rate >= 300:
            score += 10
            signals.append("超高換手率（主力活躍）")
        elif avg_turnover_rate >= 150:
            score += 5
        elif avg_turnover_rate < 50:
            score -= 10
            warning = warning or "換手率偏低，缺乏市場關注"

        score = max(0.0, min(100.0, score))

        if score >= 75:
            strength = "強勢"
        elif score >= 55:
            strength = "中等"
        else:
            strength = "弱勢"

        return MomentumResult(
            symbol=symbol,
            consecutive_days=consecutive,
            open_break_count=open_break_count,
            avg_turnover_rate=avg_turnover_rate,
            momentum_score=round(score, 1),
            board_strength=strength,
            signals=signals,
            warning=warning,
        )
