"""
Stock Backtest Agent
支援台股與美股，針對指定時間段執行多策略回測
輸出：預估收益、最大回撤、夏普比率、風險評估、操作建議

用法：
    python backtest_agent.py 2330 2023-01-01 2024-12-31
    python backtest_agent.py AAPL 2022-01-01 2024-12-31 --capital 500000
    python backtest_agent.py 2330 2023-01-01 2024-12-31 --output my_report.md
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import argparse
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime

warnings.filterwarnings('ignore')


# ─────────────────────────────────────────────
# 1. 資料抓取
# ─────────────────────────────────────────────
def fetch_data(symbol: str, start: str, end: str) -> pd.DataFrame:
    """
    下載歷史 OHLCV 資料
      - 台股 4碼數字 → 自動補 .TW (e.g. 2330 → 2330.TW)
      - 台股 ETF 含非純數字 → 補 .TW (e.g. 00631L → 00631L.TW)
      - 美股英文字母 → 直接使用 (e.g. AAPL)
    """
    if symbol.replace('L', '').replace('R', '').isdigit() or \
       (len(symbol) <= 7 and symbol[:4].isdigit()):
        ticker_sym = f"{symbol}.TW"
    else:
        ticker_sym = symbol.upper()

    print(f"► 下載 [{ticker_sym}] 歷史資料 ({start} ~ {end})...")
    df = yf.download(ticker_sym, start=start, end=end,
                     auto_adjust=True, progress=False)

    if df.empty:
        raise ValueError(
            f"無法取得 {ticker_sym} 的資料，請確認代號或日期範圍。"
            f"（台股代號格式：2330 / 00631L；美股：AAPL）"
        )

    # 攤平 MultiIndex columns（yfinance >= 0.2 可能出現）
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]

    df.index = pd.to_datetime(df.index).tz_localize(None)
    print(f"  取得 {len(df)} 筆交易日資料\n")
    return df


# ─────────────────────────────────────────────
# 2. 技術指標
# ─────────────────────────────────────────────
def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c = df['Close']

    # 移動平均
    df['MA5']  = c.rolling(5).mean()
    df['MA10'] = c.rolling(10).mean()
    df['MA20'] = c.rolling(20).mean()
    df['MA60'] = c.rolling(60).mean()

    # RSI(14)
    delta = c.diff()
    gain  = delta.where(delta > 0, 0.0).rolling(14).mean()
    loss  = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
    rs    = gain / (loss + 1e-9)
    df['RSI'] = 100 - 100 / (1 + rs)

    # MACD (12, 26, 9)
    ema12     = c.ewm(span=12, adjust=False).mean()
    ema26     = c.ewm(span=26, adjust=False).mean()
    df['DIF'] = ema12 - ema26
    df['DEA'] = df['DIF'].ewm(span=9, adjust=False).mean()
    df['MACD_bar'] = (df['DIF'] - df['DEA']) * 2

    # 布林通道 (20, 2σ)
    df['BB_mid']   = c.rolling(20).mean()
    bb_std         = c.rolling(20).std()
    df['BB_upper'] = df['BB_mid'] + 2 * bb_std
    df['BB_lower'] = df['BB_mid'] - 2 * bb_std

    # ATR(14)
    tr = pd.concat([
        df['High'] - df['Low'],
        (df['High'] - c.shift(1)).abs(),
        (df['Low']  - c.shift(1)).abs(),
    ], axis=1).max(axis=1)
    df['ATR'] = tr.rolling(14).mean()

    # 成交量比
    df['Vol_MA20']  = df['Volume'].rolling(20).mean()
    df['Vol_ratio'] = df['Volume'] / (df['Vol_MA20'] + 1e-9)

    return df


# ─────────────────────────────────────────────
# 3. 回測引擎
# ─────────────────────────────────────────────
class BacktestEngine:
    """
    單股、全資金投入、無槓桿回測引擎
    台股預設：手續費 0.1425%、交易稅（賣）0.3%
    美股預設：手續費 0%（多數零佣金），無交易稅
    """

    def __init__(self, df: pd.DataFrame,
                 initial_capital: float = 1_000_000,
                 is_tw: bool = True):
        self.df = df.dropna(subset=['MA20', 'RSI', 'DIF', 'DEA']).copy()
        self.initial_capital = initial_capital
        self.commission = 0.001425 if is_tw else 0.0
        self.sell_tax   = 0.003    if is_tw else 0.0
        self.lot_size   = 1000     if is_tw else 1   # 台股 1張=1000股

    # ── 訊號執行器 ────────────────────────────
    def _execute(self, signals: pd.Series) -> tuple:
        capital  = self.initial_capital
        position = 0
        buy_price, buy_date = 0.0, None
        trades, equity_list = [], []

        df = self.df.copy()
        df['sig'] = signals.reindex(df.index).fillna(0)

        for date, row in df.iterrows():
            price = float(row['Close'])
            sig   = row['sig']

            # 買入
            if sig == 1 and position == 0:
                cost_per_unit = price * self.lot_size * (1 + self.commission)
                units = int(capital / cost_per_unit)     # 幾張/股
                if units > 0:
                    shares = units * self.lot_size
                    capital -= shares * price * (1 + self.commission)
                    position = shares
                    buy_price = price
                    buy_date  = date

            # 賣出
            elif sig == -1 and position > 0:
                revenue = position * price * (1 - self.commission - self.sell_tax)
                cost    = position * buy_price * (1 + self.commission)
                profit  = revenue - cost
                pct     = profit / cost * 100
                capital += revenue
                trades.append({
                    'buy_date':   buy_date,
                    'sell_date':  date,
                    'buy_price':  buy_price,
                    'sell_price': price,
                    'shares':     position,
                    'profit':     profit,
                    'pct':        pct,
                    'hold_days':  (date - buy_date).days,
                })
                position = 0

            equity_list.append(capital + (position * price if position else 0))

        equity_curve = pd.Series(equity_list, index=df.index)
        return trades, equity_curve

    # ── 策略定義 ─────────────────────────────
    def _buy_hold(self):
        s = pd.Series(0, index=self.df.index)
        s.iloc[0]  = 1
        s.iloc[-1] = -1
        return self._execute(s)

    def _ma_cross(self):
        df = self.df
        p5, p20 = df['MA5'].shift(1), df['MA20'].shift(1)
        s = pd.Series(0, index=df.index)
        s[(df['MA5'] > df['MA20']) & (p5 <= p20)] = 1   # 金叉
        s[(df['MA5'] < df['MA20']) & (p5 >= p20)] = -1  # 死叉
        return self._execute(s)

    def _rsi_strategy(self):
        df = self.df
        prev = df['RSI'].shift(1)
        s = pd.Series(0, index=df.index)
        s[(df['RSI'] > 30) & (prev <= 30)] = 1   # 超賣回升
        s[(df['RSI'] < 70) & (prev >= 70)] = -1  # 超買回落
        return self._execute(s)

    def _macd_strategy(self):
        df = self.df
        pd_dif, pd_dea = df['DIF'].shift(1), df['DEA'].shift(1)
        s = pd.Series(0, index=df.index)
        s[(df['DIF'] > df['DEA']) & (pd_dif <= pd_dea)] = 1   # MACD 金叉
        s[(df['DIF'] < df['DEA']) & (pd_dif >= pd_dea)] = -1  # MACD 死叉
        return self._execute(s)

    def _combined(self):
        """綜合策略：均線 + MACD + 量能三重確認"""
        df = self.df
        p_ma5, p_ma20 = df['MA5'].shift(1), df['MA20'].shift(1)
        p_dif, p_dea  = df['DIF'].shift(1), df['DEA'].shift(1)

        # 買入：均線金叉 且 MACD 多頭 且 量比 > 1.3
        buy = (
            (df['MA5'] > df['MA20']) & (p_ma5 <= p_ma20) &
            (df['DIF'] > df['DEA']) &
            (df['Vol_ratio'] > 1.3)
        ) | (
            (df['DIF'] > df['DEA']) & (p_dif <= p_dea) &
            (df['MA5'] > df['MA20']) &
            (df['RSI'].between(35, 65))
        )

        # 賣出：均線死叉 或 RSI 超買且 MACD 轉空
        sell = (
            (df['MA5'] < df['MA20']) & (p_ma5 >= p_ma20)
        ) | (
            (df['RSI'] > 75) & (df['DIF'] < df['DEA'])
        )

        s = pd.Series(0, index=df.index)
        s[buy]  = 1
        s[sell] = -1
        return self._execute(s)

    # ── 績效指標計算 ──────────────────────────
    def _metrics(self, trades: list, equity: pd.Series, name: str) -> dict:
        if equity.empty:
            return {}

        final   = float(equity.iloc[-1])
        n_days  = (equity.index[-1] - equity.index[0]).days
        n_years = max(n_days / 365.0, 1 / 365)

        total_ret = (final - self.initial_capital) / self.initial_capital * 100
        cagr      = ((final / self.initial_capital) ** (1 / n_years) - 1) * 100

        # 最大回撤
        rolling_max = equity.cummax()
        drawdown    = (equity - rolling_max) / rolling_max * 100
        max_dd      = float(drawdown.min())

        # 夏普比率（無風險利率 1.5%/年）
        daily_ret  = equity.pct_change().dropna()
        rf_daily   = 0.015 / 252
        excess     = daily_ret - rf_daily
        sharpe     = float(excess.mean() / (excess.std() + 1e-9) * (252 ** 0.5))

        # 年化波動率
        volatility = float(daily_ret.std() * (252 ** 0.5) * 100)

        # 勝率與盈虧比
        if trades:
            wins  = [t for t in trades if t['profit'] > 0]
            loses = [t for t in trades if t['profit'] <= 0]
            win_rate  = len(wins) / len(trades) * 100
            avg_win   = float(np.mean([t['pct'] for t in wins]))  if wins  else 0.0
            avg_loss  = float(np.mean([t['pct'] for t in loses])) if loses else 0.0
            pl_ratio  = abs(avg_win / avg_loss) if avg_loss else float('inf')
            avg_hold  = float(np.mean([t['hold_days'] for t in trades]))
        else:
            win_rate = avg_win = avg_loss = avg_hold = 0.0
            pl_ratio = 0.0

        calmar = cagr / abs(max_dd) if max_dd else 0.0

        return {
            'strategy':        name,
            'initial_capital': self.initial_capital,
            'final_equity':    final,
            'total_return':    total_ret,
            'cagr':            cagr,
            'max_drawdown':    max_dd,
            'sharpe_ratio':    sharpe,
            'volatility':      volatility,
            'calmar_ratio':    calmar,
            'win_rate':        win_rate,
            'total_trades':    len(trades),
            'avg_profit_pct':  avg_win,
            'avg_loss_pct':    avg_loss,
            'profit_loss_ratio': pl_ratio,
            'avg_hold_days':   avg_hold,
            'trades':          trades,
            'equity_curve':    equity,
            'n_days':          n_days,
        }

    # ── 公開介面 ──────────────────────────────
    def run(self, strategy: str) -> dict:
        strategy_fn = {
            'buy_hold': self._buy_hold,
            'ma_cross': self._ma_cross,
            'rsi':      self._rsi_strategy,
            'macd':     self._macd_strategy,
            'combined': self._combined,
        }
        if strategy not in strategy_fn:
            raise ValueError(f"未知策略：{strategy}")
        trades, equity = strategy_fn[strategy]()
        return self._metrics(trades, equity, strategy)


# ─────────────────────────────────────────────
# 4. 風險評估模組
# ─────────────────────────────────────────────
def assess_risk(m: dict) -> dict:
    score = 0
    factors = []

    # 最大回撤
    mdd = abs(m.get('max_drawdown', 0))
    if mdd > 30:
        score += 3
        factors.append(f"最大回撤 {mdd:.1f}%，高風險 — 每 100 元投入最壞曾虧損約 {mdd:.0f} 元")
    elif mdd > 20:
        score += 2
        factors.append(f"最大回撤 {mdd:.1f}%，中等風險")
    elif mdd > 10:
        score += 1
        factors.append(f"最大回撤 {mdd:.1f}%，風險可接受")
    else:
        factors.append(f"最大回撤 {mdd:.1f}%，風險控制良好")

    # 波動率
    vol = m.get('volatility', 0)
    if vol > 40:
        score += 3
        factors.append(f"年化波動率 {vol:.1f}%，極度震盪，不適合保守投資人")
    elif vol > 25:
        score += 2
        factors.append(f"年化波動率 {vol:.1f}%，波動偏高，需強化停損紀律")
    elif vol > 15:
        score += 1
        factors.append(f"年化波動率 {vol:.1f}%，中等波動")
    else:
        factors.append(f"年化波動率 {vol:.1f}%，波動穩定")

    # 夏普比率
    sharpe = m.get('sharpe_ratio', 0)
    if sharpe < 0:
        score += 3
        factors.append(f"夏普比率 {sharpe:.2f}，風險調整後報酬為負，策略劣於持有現金")
    elif sharpe < 0.5:
        score += 2
        factors.append(f"夏普比率 {sharpe:.2f}，風險報酬效率偏低")
    elif sharpe < 1.0:
        score += 1
        factors.append(f"夏普比率 {sharpe:.2f}，尚可接受（> 1.0 為優秀）")
    else:
        factors.append(f"夏普比率 {sharpe:.2f}，風險報酬效率良好")

    # 勝率
    wr = m.get('win_rate', 0)
    if wr < 40:
        score += 2
        factors.append(f"勝率 {wr:.1f}%，超過半數交易虧損，需依賴大盈虧比維持正期望")
    elif wr < 50:
        score += 1
        factors.append(f"勝率 {wr:.1f}%，略低於 50%，需搭配好的盈虧比")
    else:
        factors.append(f"勝率 {wr:.1f}%，過半交易獲利，穩健")

    # 綜合等級
    if score >= 8:
        level = "極高風險"
    elif score >= 6:
        level = "高風險"
    elif score >= 4:
        level = "中高風險"
    elif score >= 2:
        level = "中等風險"
    else:
        level = "低風險"

    return {'risk_level': level, 'risk_score': score, 'risk_factors': factors}


# ─────────────────────────────────────────────
# 5. 操作建議
# ─────────────────────────────────────────────
def generate_recommendation(symbol: str, all_metrics: dict,
                             df: pd.DataFrame) -> dict:
    # 最佳策略 = 年化報酬最高（排除 buy_hold 做對比）
    active = {k: v for k, v in all_metrics.items()
              if v and k != 'buy_hold'}
    if active:
        best_strat, best_m = max(active.items(),
                                 key=lambda x: x[1].get('cagr', -999))
    else:
        best_strat = 'buy_hold'
        best_m = all_metrics.get('buy_hold', {})

    last = df.iloc[-1]

    def safe_float(val):
        return float(val) if not pd.isna(val) else 0.0

    price  = safe_float(last['Close'])
    rsi    = safe_float(last['RSI'])
    ma5    = safe_float(last['MA5'])
    ma20   = safe_float(last['MA20'])
    dif    = safe_float(last['DIF'])
    dea    = safe_float(last['DEA'])
    atr    = safe_float(last['ATR']) or price * 0.02
    vr     = safe_float(last['Vol_ratio'])

    signals = []

    # 均線
    if ma5 > ma20:
        signals.append(('多', f'均線多頭排列（MA5={ma5:.2f} > MA20={ma20:.2f}）'))
    else:
        signals.append(('空', f'均線空頭排列（MA5={ma5:.2f} < MA20={ma20:.2f}）'))

    # MACD
    if dif > dea:
        signals.append(('多', f'MACD 多頭（DIF={dif:.3f} > DEA={dea:.3f}）'))
    else:
        signals.append(('空', f'MACD 空頭（DIF={dif:.3f} < DEA={dea:.3f}）'))

    # RSI
    if rsi < 30:
        signals.append(('多', f'RSI={rsi:.1f}，超賣反彈訊號'))
    elif rsi > 70:
        signals.append(('空', f'RSI={rsi:.1f}，超買壓回訊號'))
    else:
        signals.append(('中', f'RSI={rsi:.1f}，中性區間'))

    # 量能
    if vr >= 2.0:
        signals.append(('多', f'量比={vr:.1f}x，爆量放大，資金積極介入'))
    elif vr < 0.7:
        signals.append(('空', f'量比={vr:.1f}x，縮量，動能不足'))

    bull = sum(1 for s, _ in signals if s == '多')
    bear = sum(1 for s, _ in signals if s == '空')

    if bull >= 3:
        action = '積極買進'
    elif bull >= 2 and bear <= 1:
        action = '買進'
    elif bear >= 3:
        action = '賣出 / 空手觀望'
    elif bear >= 2:
        action = '減碼 / 觀望'
    else:
        action = '觀望'

    target = round(price + 2.0 * atr, 2)
    stop   = round(price - 1.5 * atr, 2)

    return {
        'action':        action,
        'latest_price':  price,
        'target_price':  target,
        'stop_loss':     stop,
        'signals':       signals,
        'best_strategy': best_strat,
        'best_cagr':     best_m.get('cagr', 0) if best_m else 0,
        'best_sharpe':   best_m.get('sharpe_ratio', 0) if best_m else 0,
    }


# ─────────────────────────────────────────────
# 6. 報告產生
# ─────────────────────────────────────────────
STRATEGY_NAMES = {
    'buy_hold': '買入持有（基準）',
    'ma_cross': '均線交叉策略',
    'rsi':      'RSI 超賣超買策略',
    'macd':     'MACD 金叉死叉策略',
    'combined': '綜合策略（均線+MACD+量能）',
}


def generate_report(symbol: str, start: str, end: str,
                    all_metrics: dict, risk_results: dict,
                    rec: dict, df: pd.DataFrame) -> str:
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    lines = []

    # ── 標題 ──
    lines += [
        f"# {symbol} 股票回測分析報告",
        f"**回測區間**：{start} ~ {end}　｜　**報告產生**：{now}",
        "",
        "> ⚠️ 本報告為歷史回測結果，不構成投資建議，請自行評估風險。",
        "",
        "---",
        "",
    ]

    # ── 基本資訊 ──
    first_close = float(df['Close'].iloc[0])
    last_close  = float(df['Close'].iloc[-1])
    period_pct  = (last_close / first_close - 1) * 100

    lines += [
        "## 一、基本資訊",
        "",
        f"| 項目 | 數值 |",
        f"|------|------|",
        f"| 股票代號 | {symbol} |",
        f"| 回測期間 | {start} ~ {end} |",
        f"| 交易日數 | {len(df)} 天 |",
        f"| 期初收盤 | {first_close:.2f} |",
        f"| 期末收盤 | {last_close:.2f} |",
        f"| 期間漲跌 | **{period_pct:+.2f}%** |",
        "",
        "---",
        "",
    ]

    # ── 策略績效比較 ──
    lines += [
        "## 二、各策略績效比較",
        "",
        "| 策略 | 總報酬 | 年化報酬 | 最大回撤 | 夏普比率 | 波動率 | 勝率 | 交易次數 |",
        "|------|:------:|:-------:|:-------:|:-------:|:-----:|:----:|:-------:|",
    ]

    for strat, m in all_metrics.items():
        if not m:
            lines.append(f"| {STRATEGY_NAMES.get(strat, strat)} | — | — | — | — | — | — | — |")
            continue
        name = STRATEGY_NAMES.get(strat, strat)
        lines.append(
            f"| {name} "
            f"| {m['total_return']:+.2f}% "
            f"| {m['cagr']:+.2f}% "
            f"| {m['max_drawdown']:.2f}% "
            f"| {m['sharpe_ratio']:.2f} "
            f"| {m['volatility']:.1f}% "
            f"| {m['win_rate']:.1f}% "
            f"| {m['total_trades']} |"
        )

    lines += ["", "---", ""]

    # ── 最佳策略詳情 ──
    best_strat = rec['best_strategy']
    best_m = all_metrics.get(best_strat, {})

    if best_m:
        lines += [
            f"## 三、最佳策略詳情：{STRATEGY_NAMES.get(best_strat, best_strat)}",
            "",
            f"### 資金績效",
            "",
            f"- **初始資金**：{best_m['initial_capital']:>12,.0f} 元",
            f"- **期末資金**：{best_m['final_equity']:>12,.0f} 元",
            f"- **獲利金額**：{best_m['final_equity'] - best_m['initial_capital']:>+12,.0f} 元",
            f"- **總報酬率**：**{best_m['total_return']:+.2f}%**",
            f"- **年化報酬率（CAGR）**：**{best_m['cagr']:+.2f}%**",
            "",
            f"### 風險指標",
            "",
            f"- **最大回撤**：{best_m['max_drawdown']:.2f}%",
            f"- **年化波動率**：{best_m['volatility']:.2f}%",
            f"- **夏普比率**：{best_m['sharpe_ratio']:.2f}",
            f"- **Calmar 比率**：{best_m['calmar_ratio']:.2f}",
            "",
            f"### 交易統計",
            "",
            f"- **總交易次數**：{best_m['total_trades']} 次",
            f"- **勝率**：{best_m['win_rate']:.1f}%",
            f"- **平均獲利幅度**：{best_m['avg_profit_pct']:+.2f}%",
            f"- **平均虧損幅度**：{best_m['avg_loss_pct']:+.2f}%",
            f"- **盈虧比**：{best_m['profit_loss_ratio']:.2f}",
            f"- **平均持倉天數**：{best_m['avg_hold_days']:.1f} 天",
            "",
        ]

        # 近5筆交易
        trades = best_m.get('trades', [])
        if trades:
            recent = trades[-5:]
            lines += [
                "### 近 5 筆交易記錄",
                "",
                "| 買入日 | 賣出日 | 買入價 | 賣出價 | 損益(元) | 報酬率 | 持有天數 |",
                "|--------|--------|:------:|:------:|--------:|:------:|:-------:|",
            ]
            for t in recent:
                lines.append(
                    f"| {str(t['buy_date'])[:10]} "
                    f"| {str(t['sell_date'])[:10]} "
                    f"| {t['buy_price']:.2f} "
                    f"| {t['sell_price']:.2f} "
                    f"| {t['profit']:>+,.0f} "
                    f"| {t['pct']:+.2f}% "
                    f"| {t['hold_days']} |"
                )
            lines += [""]

    lines += ["---", ""]

    # ── 風險評估 ──
    lines += ["## 四、各策略風險評估", ""]

    for strat, risk in risk_results.items():
        name = STRATEGY_NAMES.get(strat, strat)
        level = risk['risk_level']
        score = risk['risk_score']

        # 風險等級顏色標示
        level_mark = {
            '低風險': '✅',
            '中等風險': '🟡',
            '中高風險': '🟠',
            '高風險': '🔴',
            '極高風險': '🚨',
        }.get(level, '⚪')

        lines += [
            f"### {name}",
            f"**風險等級**：{level_mark} {level}（分數 {score}/12）",
            "",
        ]
        for f in risk['risk_factors']:
            lines.append(f"- {f}")
        lines += [""]

    lines += ["---", ""]

    # ── 最新技術面 ──
    lines += [
        "## 五、目前技術面（最新一個交易日）",
        "",
        f"- **最新收盤**：{rec['latest_price']:.2f}",
        "",
        "**技術訊號分析：**",
        "",
    ]

    for sig_type, desc in rec['signals']:
        icon = {'多': '🟢', '空': '🔴', '中': '🟡'}.get(sig_type, '⚪')
        lines.append(f"- {icon} {desc}")

    lines += ["", "---", ""]

    # ── 操作建議 ──
    action = rec['action']
    action_marks = {
        '積極買進': '**[積極買進]** 🚀',
        '買進':     '**[建議買進]**',
        '觀望':     '**[建議觀望]**',
        '減碼 / 觀望': '**[減碼 / 觀望]** ⚠️',
        '賣出 / 空手觀望': '**[賣出 / 空手觀望]** 🔻',
    }
    action_display = action_marks.get(action, f'**[{action}]**')

    lines += [
        f"## 六、操作建議：{action_display}",
        "",
        f"| 項目 | 數值 |",
        f"|------|------|",
        f"| 最新收盤 | {rec['latest_price']:.2f} |",
        f"| 目標價（+2 ATR） | **{rec['target_price']:.2f}** |",
        f"| 停損價（-1.5 ATR） | **{rec['stop_loss']:.2f}** |",
        f"| 最佳回測策略 | {STRATEGY_NAMES.get(rec['best_strategy'], rec['best_strategy'])} |",
        f"| 策略年化報酬 | {rec['best_cagr']:+.2f}% |",
        f"| 策略夏普比率 | {rec['best_sharpe']:.2f} |",
        "",
        "### 投資注意事項",
        "",
        "1. **歷史不代表未來**：回測報酬基於歷史資料，未來實際表現可能有重大差異",
        "2. **交易成本**：實際交易含手續費、稅、滑點，小頻率策略成本影響更顯著",
        "3. **停損紀律**：跌破停損價應嚴格執行出場，避免虧損擴大",
        "4. **部位管理**：單一股票建議不超過總資金 20%，分散風險",
        "5. **大盤環境**：個股訊號須搭配大盤趨勢與總體經濟環境綜合判斷",
        "",
        "---",
        "",
        f"*本報告由 `Stock_AI_agent/backtest_agent.py` 自動生成*",
        f"*生成時間：{now}*",
    ]

    return "\n".join(lines)


# ─────────────────────────────────────────────
# 7. 主程式 (CLI)
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description='股票回測 Agent — 多策略回測 + 風險評估 + 操作建議',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
範例：
  python backtest_agent.py 2330 2023-01-01 2024-12-31
  python backtest_agent.py AAPL 2022-01-01 2024-12-31 --capital 500000
  python backtest_agent.py 00631L 2021-01-01 2024-12-31 --output etf_report.md
        """
    )
    parser.add_argument('symbol',   help='股票代號（台股: 2330 / 00631L；美股: AAPL）')
    parser.add_argument('start',    help='回測開始日 YYYY-MM-DD')
    parser.add_argument('end',      help='回測結束日 YYYY-MM-DD')
    parser.add_argument('--capital', type=float, default=1_000_000,
                        help='初始資金（預設 1,000,000）')
    parser.add_argument('--output', type=str, default='',
                        help='報告輸出路徑（.md），預設自動命名')
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"  股票回測 Agent")
    print(f"  股票：{args.symbol}  |  區間：{args.start} ~ {args.end}")
    print(f"  初始資金：{args.capital:,.0f}")
    print(f"{'='*60}\n")

    # 1. 下載資料
    df_raw = fetch_data(args.symbol, args.start, args.end)

    # 2. 計算技術指標
    print("► 計算技術指標...")
    df = add_indicators(df_raw)
    df_clean = df.dropna(subset=['MA20', 'RSI', 'DIF', 'DEA'])
    print(f"  有效資料 {len(df_clean)} 筆（已排除指標暖機期）\n")

    if len(df_clean) < 30:
        print("⚠️  有效資料不足 30 筆，回測結果可能不具參考價值")

    # 3. 判斷台股 / 美股（決定手續費）
    is_tw = (args.symbol.replace('L', '').replace('R', '').isdigit() or
             (len(args.symbol) <= 7 and args.symbol[:4].isdigit()))

    engine = BacktestEngine(df_clean, initial_capital=args.capital, is_tw=is_tw)

    # 4. 執行回測
    print("► 執行多策略回測...")
    strategies = ['buy_hold', 'ma_cross', 'rsi', 'macd', 'combined']
    all_metrics = {}

    for strat in strategies:
        try:
            m = engine.run(strat)
            all_metrics[strat] = m
            print(
                f"  [{STRATEGY_NAMES[strat][:12].ljust(12)}]  "
                f"年化 {m['cagr']:+6.2f}%  "
                f"最大回撤 {m['max_drawdown']:6.2f}%  "
                f"夏普 {m['sharpe_ratio']:+5.2f}  "
                f"勝率 {m['win_rate']:5.1f}%  "
                f"交易 {m['total_trades']:3d}次"
            )
        except Exception as e:
            print(f"  [{strat}] 執行失敗：{e}")
            all_metrics[strat] = {}

    print()

    # 5. 風險評估
    print("► 風險評估...")
    risk_results = {k: assess_risk(v) for k, v in all_metrics.items() if v}
    for strat, risk in risk_results.items():
        print(f"  [{STRATEGY_NAMES[strat][:12].ljust(12)}]  {risk['risk_level']}")
    print()

    # 6. 操作建議
    print("► 生成操作建議...")
    rec = generate_recommendation(args.symbol, all_metrics, df_clean)
    print(f"  建議操作：{rec['action']}")
    print(f"  目標價：  {rec['target_price']:.2f}")
    print(f"  停損價：  {rec['stop_loss']:.2f}")
    print()

    # 7. 產生報告
    report = generate_report(
        args.symbol, args.start, args.end,
        all_metrics, risk_results, rec, df_clean
    )

    # 8. 儲存報告
    if args.output:
        out_path = args.output
    else:
        safe_sym = args.symbol.replace('/', '_')
        out_path = (
            f"C:/Users/BaoGo/Documents/ClaudeCode/Stock_AI_agent/"
            f"backtest_{safe_sym}_{args.start}_{args.end}.md"
        )

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(report)

    print(f"✓ 報告已儲存：{out_path}")
    print(f"{'='*60}\n")

    return report


if __name__ == '__main__':
    main()
