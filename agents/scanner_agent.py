"""
📡 SCANNER AGENT — 妖股掃描
從 TWSE / TPEX API 抓取全市場當日資料（上市 + 上櫃），篩選：
- 觸及漲停（漲幅 ≥ 9.5%）
- 量比 ≥ 5x（成交量 / 20 日均量）
- 計算連板天數
輸出：妖股候選清單 list[ScanResult]
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd
import requests
import yfinance as yf

from config.settings import (
    LIMIT_UP_PCT,
    VOLUME_SURGE_MIN,
    MIN_CONSECUTIVE_DAYS,
    MAX_BOARD_ENTRY,
)

logger = logging.getLogger(__name__)

TW = timezone(timedelta(hours=8))


@dataclass
class ScanResult:
    symbol: str           # 股票代號（上市 .TW / 上櫃 .TWO）
    name: str             # 股票名稱
    close: float          # 收盤價
    pct_change: float     # 當日漲幅 %
    volume: float         # 當日成交量（張）
    avg_volume: float     # 20 日均量（張）
    volume_ratio: float   # 量比
    consecutive_days: int # 連板天數
    is_limit_up: bool     # 今日是否漲停
    signals: list = field(default_factory=list)


class ScannerAgent:
    """妖股掃描 Agent（涵蓋 TWSE 上市 + TPEX 上櫃）"""

    TWSE_URL = (
        "https://www.twse.com.tw/rwd/zh/afterTrading/"
        "STOCK_DAY_ALL?response=json&date={date}"
    )
    # TPEX 使用民國年格式：{roc_date} = "115/05/19"
    TPEX_URL = (
        "https://www.tpex.org.tw/web/stock/aftertrading/"
        "otc_quotes_no1430/stk_wn1430_result.php"
        "?l=zh-tw&d={roc_date}&se=EW"
    )

    def __init__(self):
        self.name = "ScannerAgent"

    # ── 公開介面 ─────────────────────────────────────────
    def run(self, date_str: str | None = None) -> list[ScanResult]:
        """掃描全市場（上市+上櫃），回傳妖股候選清單；date_str 省略時自動取最新交易日"""
        date_str = date_str or self._last_trading_date()
        logger.info(f"[Scanner] 掃描日期：{date_str}")

        df_twse = self._fetch_twse(date_str)
        df_tpex = self._fetch_tpex(date_str)

        if not df_twse.empty:
            df_twse["_market"] = "TW"
        if not df_tpex.empty:
            df_tpex["_market"] = "TWO"

        df_today = pd.concat([df_twse, df_tpex], ignore_index=True)
        if df_today.empty:
            logger.warning("[Scanner] TWSE + TPEX 資料均為空")
            return []

        logger.info(
            f"[Scanner] TWSE {len(df_twse)} 檔 + TPEX {len(df_tpex)} 檔 = 共 {len(df_today)} 檔"
        )

        # ── Step 1: 粗篩疑似漲停（不呼叫 yfinance）────────────
        pre_candidates = []
        for _, row in df_today.iterrows():
            close  = self._parse_float(row["close"])
            change = self._parse_float(row["change"])
            if close <= 0:
                continue
            prev_close = close - change
            pct = (change / prev_close * 100) if prev_close > 0 else 0.0
            if pct >= LIMIT_UP_PCT - 0.5:
                pre_candidates.append((row, pct))

        logger.info(f"[Scanner] 粗篩後 {len(pre_candidates)} 檔疑似漲停，開始 yfinance 精篩")

        # ── Step 2: 只對粗篩結果呼叫 yfinance ────────────────────
        candidates = []
        for row, pct in pre_candidates:
            market = str(row.get("_market", "TW"))
            result = self._analyze_row(row, market=market)
            if result:
                candidates.append(result)

        candidates.sort(key=lambda x: (x.consecutive_days, x.volume_ratio), reverse=True)
        logger.info(f"[Scanner] 找到 {len(candidates)} 檔妖股候選")
        return candidates

    # ── 內部方法 ─────────────────────────────────────────
    def _last_trading_date(self) -> str:
        """取得最近一個台股交易日（YYYYMMDD）"""
        now = datetime.now(TW)
        while now.weekday() >= 5:
            now -= timedelta(days=1)
        return now.strftime("%Y%m%d")

    @staticmethod
    def _to_roc_date(date_str: str) -> str:
        """將 YYYYMMDD 轉為 TPEX 民國年格式 YYY/MM/DD"""
        dt = datetime.strptime(date_str, "%Y%m%d")
        return f"{dt.year - 1911}/{dt.month:02d}/{dt.day:02d}"

    def _fetch_twse(self, date_str: str) -> pd.DataFrame:
        """從 TWSE API 抓取上市股票當日收盤資料"""
        try:
            url = self.TWSE_URL.format(date=date_str)
            resp = requests.get(
                url,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=20,
            )
            data = resp.json()
            rows = data.get("data", [])
            if not rows:
                return pd.DataFrame()

            df = pd.DataFrame(rows, columns=[
                "code", "name", "volume_shares", "value",
                "open", "high", "low", "close",
                "change", "volume_lots",
            ])
            df = df[df["code"].str.match(r"^\d{4}$")]
            return df
        except Exception as e:
            logger.error(f"[Scanner] TWSE 抓取失敗：{e}")
            return pd.DataFrame()

    def _fetch_tpex(self, date_str: str) -> pd.DataFrame:
        """從 TPEX API 抓取上櫃股票當日收盤資料

        TPEX 回傳結構：{"tables":[{"data":[...], ...}], "stat":"ok"}
        欄位順序：代號,名稱,收盤,漲跌,開盤,最高,最低,成交股數,成交金額,成交筆數,...
        """
        try:
            roc_date = self._to_roc_date(date_str)
            url = self.TPEX_URL.format(roc_date=roc_date)
            resp = requests.get(
                url,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=20,
            )
            data = resp.json()
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
                    "volume_lots":   r[9],  # 成交筆數（與 TWSE 同語意）
                })

            df = pd.DataFrame(records)
            if df.empty:
                return pd.DataFrame()
            df = df[df["code"].str.match(r"^\d{4}$")]
            return df
        except Exception as e:
            logger.error(f"[Scanner] TPEX 抓取失敗：{e}")
            return pd.DataFrame()

    def _parse_float(self, val) -> float:
        """解析數字欄位（含逗號）"""
        try:
            return float(str(val).replace(",", "").replace("--", "0"))
        except (ValueError, TypeError):
            return 0.0

    def _analyze_row(self, row: pd.Series, market: str = "TW") -> Optional[ScanResult]:
        """分析單支股票，判斷是否為妖股候選"""
        code = str(row["code"]).strip()
        name = str(row["name"]).strip()

        close  = self._parse_float(row["close"])
        change = self._parse_float(row["change"])
        volume = self._parse_float(row["volume_shares"]) / 1000  # 股 → 張

        if close <= 0 or volume <= 0:
            return None

        prev_close = close - change
        pct = (change / prev_close * 100) if prev_close > 0 else 0.0

        is_limit_up = pct >= LIMIT_UP_PCT

        # 上市用 .TW，上櫃用 .TWO
        symbol_yf = f"{code}.{market}"
        consecutive, avg_vol = self._calc_consecutive_and_avgvol(symbol_yf, close, pct)

        vol_ratio = (volume / avg_vol) if avg_vol > 0 else 0.0

        if not is_limit_up and consecutive < MIN_CONSECUTIVE_DAYS:
            return None
        if vol_ratio < VOLUME_SURGE_MIN:
            return None
        if consecutive > MAX_BOARD_ENTRY:
            pass  # 超過最大追板數，保留但標記高風險

        signals = []
        if is_limit_up:
            signals.append(f"漲停 +{pct:.1f}%")
        if consecutive >= 2:
            signals.append(f"連板 {consecutive} 天")
        if vol_ratio >= 10:
            signals.append(f"超級爆量 {vol_ratio:.1f}x")
        elif vol_ratio >= 5:
            signals.append(f"爆量 {vol_ratio:.1f}x")

        return ScanResult(
            symbol=symbol_yf,
            name=name,
            close=close,
            pct_change=round(pct, 2),
            volume=volume,
            avg_volume=round(avg_vol, 1),
            volume_ratio=round(vol_ratio, 2),
            consecutive_days=consecutive,
            is_limit_up=is_limit_up,
            signals=signals,
        )

    def _calc_consecutive_and_avgvol(
        self, symbol: str, today_close: float, today_pct: float
    ) -> tuple[int, float]:
        """計算連板天數與 20 日均量（使用 yfinance）"""
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="30d")
            if df.empty or len(df) < 5:
                return (1 if today_pct >= LIMIT_UP_PCT else 0), 0.0

            avg_vol = float(df["Volume"].iloc[:-1].tail(20).mean()) / 1000  # 股 → 張

            consecutive = 1 if today_pct >= LIMIT_UP_PCT else 0
            closes = df["Close"].iloc[:-1]  # 不含今日
            for i in range(len(closes) - 1, 0, -1):
                prev = closes.iloc[i - 1]
                curr = closes.iloc[i]
                if prev > 0 and (curr - prev) / prev * 100 >= LIMIT_UP_PCT:
                    consecutive += 1
                else:
                    break

            return consecutive, avg_vol
        except Exception:
            return (1 if today_pct >= LIMIT_UP_PCT else 0), 0.0
