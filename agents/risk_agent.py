"""
⚖️ RISK AGENT — 風控分析
針對妖股計算：
- ATR 波動率計算（停損基準）
- 板數動態倉位（板越多風險越高）
- 流動性評估
- 風報比計算
- 上櫃（TPEX）特有風險評估（流動性折扣、籌碼集中、資訊透明度）
輸出：風險等級 L1-L5 + 倉位建議 + 停損/目標價 + 上櫃風險警示
"""
import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

from config.settings import (
    MAX_STOP_LOSS_PCT,
    MIN_RISK_REWARD,
    LIQUIDITY_MIN_VOL,
    BOARD_POSITION_PCT,
    EXIT_TARGET_BOARDS,
    LIMIT_UP_PCT,
)

logger = logging.getLogger(__name__)

RISK_LABELS = {
    1: "極低風險",
    2: "低風險",
    3: "中等風險",
    4: "高風險",
    5: "極高風險",
}

# 上櫃股票相較上市的倉位縮減比例
OTC_POSITION_RATIO = 0.67
# 上櫃流動性門檻更嚴格（縮至上市的 60%）
OTC_LIQUIDITY_RATIO = 0.60


@dataclass
class RiskResult:
    symbol: str
    risk_level: int           # 1-5
    risk_label: str
    atr: float                # ATR 值
    atr_pct: float            # ATR / 收盤價 %
    stop_loss_price: float    # 建議停損價
    stop_loss_pct: float      # 停損幅度 %
    target_price: float       # 目標價（依再漲幾板估算）
    risk_reward_ratio: float  # 風報比
    suggested_position_pct: float  # 建議倉位 %
    liquidity_ok: bool        # 流動性是否達標
    risk_score: float         # 0-100，越高越安全
    max_drawdown: float       # 近期最大回撤 %
    is_otc: bool = False                          # 是否為上櫃股票
    otc_risk_warnings: list = field(default_factory=list)  # 上櫃特有風險警示


class RiskAgent:
    """風控分析 Agent"""

    def __init__(self):
        self.name = "RiskAgent"

    # ── 公開介面 ─────────────────────────────────────────
    def run(
        self, symbols: list[str], board_map: dict[str, int]
    ) -> dict[str, RiskResult]:
        """
        board_map: {symbol: consecutive_days}，依板數調整倉位
        """
        results = {}
        for symbol in symbols:
            try:
                boards = board_map.get(symbol, 1)
                result = self._analyze(symbol, boards)
                if result:
                    results[symbol] = result
                    logger.info(
                        f"[Risk] {symbol} 等級=L{result.risk_level} "
                        f"停損={result.stop_loss_pct:.1f}% "
                        f"倉位={result.suggested_position_pct:.0%}"
                    )
            except Exception as e:
                logger.warning(f"[Risk] {symbol} 分析失敗：{e}")
        return results

    # ── 內部方法 ─────────────────────────────────────────
    def _fetch(self, symbol: str) -> Optional[pd.DataFrame]:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="60d")
        if df.empty or len(df) < 10:
            return None
        return df

    def _calc_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        high  = df["High"]
        low   = df["Low"]
        close = df["Close"]
        prev_c = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_c).abs(),
            (low  - prev_c).abs(),
        ], axis=1).max(axis=1)
        atr = float(tr.rolling(period).mean().iloc[-1])
        return atr if not np.isnan(atr) else float(tr.mean())

    def _calc_max_drawdown(self, close: pd.Series) -> float:
        roll_max = close.cummax()
        dd = (close - roll_max) / roll_max
        return float(dd.min())  # 負值，例如 -0.15 = 15% 回撤

    def _analyze(self, symbol: str, consecutive_days: int) -> Optional[RiskResult]:
        df = self._fetch(symbol)
        if df is None:
            return None

        is_otc = symbol.endswith(".TWO")

        close  = df["Close"]
        volume = df["Volume"]

        c_last   = float(close.iloc[-1])
        avg_vol  = float(volume.rolling(20).mean().iloc[-1])

        atr      = self._calc_atr(df)
        atr_pct  = atr / c_last if c_last > 0 else 0
        max_dd   = self._calc_max_drawdown(close)

        # 上櫃流動性門檻更嚴格
        liq_threshold = LIQUIDITY_MIN_VOL / 1000
        if is_otc:
            liq_threshold *= OTC_LIQUIDITY_RATIO
        liquidity = (avg_vol / 1000) >= liq_threshold

        # ── 停損計算（ATR 1.5 倍，但不超過最大停損） ──────
        stop_dist  = min(atr * 1.5, c_last * MAX_STOP_LOSS_PCT)
        stop_price = round(c_last - stop_dist, 2)
        stop_pct   = stop_dist / c_last * 100

        # ── 目標價（妖股：再漲 EXIT_TARGET_BOARDS 板） ────
        target_gain  = (1 + LIMIT_UP_PCT / 100) ** EXIT_TARGET_BOARDS - 1
        target_price = round(c_last * (1 + target_gain), 2)
        rr_ratio     = target_gain / (stop_pct / 100) if stop_pct > 0 else 0

        # ── 建議倉位（依板數動態調整） ────────────────────
        pos_pct = BOARD_POSITION_PCT.get(
            min(consecutive_days, max(BOARD_POSITION_PCT.keys())), 0.0
        )
        if not liquidity:
            pos_pct *= 0.5
        if is_otc:
            pos_pct *= OTC_POSITION_RATIO  # 上櫃股票倉位縮減至 2/3

        # ── 風控評分（越高越安全） ─────────────────────────
        score = 100.0
        score -= min(atr_pct * 100 * 3, 30)        # 波動懲罰
        score -= min(abs(max_dd) * 100 * 1.5, 25)  # 回撤懲罰
        if not liquidity:
            score -= 25
        if consecutive_days >= 4:
            score -= 20
        elif consecutive_days == 3:
            score -= 10
        if stop_pct > MAX_STOP_LOSS_PCT * 100:
            score -= 15
        if is_otc:
            score -= 10  # 上櫃固定扣分（資訊不對稱 + 市場深度）
        score = max(0.0, min(100.0, score))

        if score >= 80:
            level = 1
        elif score >= 65:
            level = 2
        elif score >= 50:
            level = 3
        elif score >= 35:
            level = 4
        else:
            level = 5

        # 上櫃風險等級再升一級（最高 L5）
        if is_otc:
            level = min(level + 1, 5)

        otc_warnings = self._build_otc_warnings(
            is_otc, consecutive_days, avg_vol, atr_pct, max_dd
        ) if is_otc else []

        return RiskResult(
            symbol=symbol,
            risk_level=level,
            risk_label=RISK_LABELS[level],
            atr=round(atr, 4),
            atr_pct=round(atr_pct * 100, 2),
            stop_loss_price=stop_price,
            stop_loss_pct=round(stop_pct, 2),
            target_price=target_price,
            risk_reward_ratio=round(rr_ratio, 2),
            suggested_position_pct=round(pos_pct, 2),
            liquidity_ok=liquidity,
            risk_score=round(score, 1),
            max_drawdown=round(abs(max_dd) * 100, 2),
            is_otc=is_otc,
            otc_risk_warnings=otc_warnings,
        )

    @staticmethod
    def _build_otc_warnings(
        is_otc: bool,
        consecutive_days: int,
        avg_vol_shares: float,
        atr_pct: float,
        max_dd: float,
    ) -> list[str]:
        """產生上櫃股票特有風險警示清單"""
        if not is_otc:
            return []

        warnings: list[str] = []

        # ① 流動性風險（所有上櫃股票）
        warnings.append(
            "【上櫃流動性】成交量通常低於上市，急跌時買賣價差擴大，"
            "停損單需掛市價或提前出場"
        )

        # ② 籌碼集中風險（所有上櫃股票）
        warnings.append(
            "【籌碼集中】上櫃小型股大股東持股比例高，"
            "主力一旦出貨跌速遠快於上市股，嚴守 -5% 停損"
        )

        # ③ 資訊透明度（所有上櫃股票）
        warnings.append(
            "【資訊透明度】上櫃公司財報揭露頻率低於上市，"
            "題材真實性需自行交叉驗證，勿單靠新聞追漲"
        )

        # ④ 連板回落風險（連板 ≥ 2）
        if consecutive_days >= 2:
            warnings.append(
                f"【連板回落】上櫃連板股（目前第 {consecutive_days} 板）"
                "落板後平均跌幅 15-25%，建議設移動停損且持倉不超過 3 天"
            )

        # ⑤ 高波動警告（ATR% > 8%）
        if atr_pct > 8.0:
            warnings.append(
                f"【高波動】ATR 達 {atr_pct:.1f}%，上櫃高波動股票"
                "隔日開盤跳空風險大，避免隔夜持有大倉位"
            )

        # ⑥ 近期回撤深（max_dd < -15%）
        if abs(max_dd) > 15.0:
            warnings.append(
                f"【歷史回撤】近 60 日最大回撤達 {abs(max_dd):.1f}%，"
                "股價波動劇烈，上漲後快速回測機率高"
            )

        return warnings
