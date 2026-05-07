#!/usr/bin/env python3
"""
📈 Backtest - 妖股建議回測

讀取 reports/yaogu_*.json，針對每次推薦股票進行 N 日回測，
輸出整體命中率、停損觸發率、平均報酬與回測明細。
"""
import argparse
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

from config.settings import REPORT_DIR, DEFAULT_BACKTEST_HORIZON_DAYS


@dataclass
class TradeBacktestResult:
    analysis_date: str
    symbol: str
    name: str
    entry_price: float
    confidence: float
    recommendation: float
    target_price: float
    stop_loss_price: float
    horizon_days: int
    final_return_pct: float
    max_return_pct: float
    min_return_pct: float
    hit_target: bool
    hit_stop: bool
    valid: bool


def _safe_pct(base: float, value: float) -> float:
    if base <= 0:
        return 0.0
    return (value - base) / base * 100


def _evaluate_trade(
    entry_price: float,
    target_price: float,
    stop_loss_price: float,
    bars: pd.DataFrame,
) -> tuple[float, float, float, bool, bool]:
    max_high = float(bars["High"].max())
    min_low = float(bars["Low"].min())
    last_close = float(bars["Close"].iloc[-1])

    final_return_pct = _safe_pct(entry_price, last_close)
    max_return_pct = _safe_pct(entry_price, max_high)
    min_return_pct = _safe_pct(entry_price, min_low)
    hit_target = target_price > 0 and max_high >= target_price
    hit_stop = stop_loss_price > 0 and min_low <= stop_loss_price
    return (
        round(final_return_pct, 2),
        round(max_return_pct, 2),
        round(min_return_pct, 2),
        hit_target,
        hit_stop,
    )


def _fetch_bars(symbol: str, analysis_date: str, horizon_days: int) -> pd.DataFrame:
    start_date = datetime.strptime(analysis_date, "%Y%m%d") + timedelta(days=1)
    end_date = start_date + timedelta(days=horizon_days + 14)
    ticker = yf.Ticker(symbol)
    bars = ticker.history(start=start_date.strftime("%Y-%m-%d"), end=end_date.strftime("%Y-%m-%d"))
    if bars is None or bars.empty:
        return pd.DataFrame()
    return bars.head(horizon_days).copy()


def run_backtest(report_dir: str, horizon_days: int, min_confidence: float) -> dict:
    report_path = Path(report_dir)
    files = sorted(report_path.glob("yaogu_*.json"))
    results: list[TradeBacktestResult] = []

    for file in files:
        with file.open("r", encoding="utf-8") as f:
            report = json.load(f)
        analysis_date = str(report.get("analysis_date", ""))
        for s in report.get("stocks", []):
            confidence = float(s.get("scores", {}).get("confidence", 0.0))
            if confidence < min_confidence:
                continue

            symbol = str(s.get("symbol", "")).strip()
            entry_price = float(s.get("close", 0.0))
            target_price = float(s.get("risk", {}).get("target_price", 0.0))
            stop_loss_price = float(s.get("risk", {}).get("stop_loss_price", 0.0))
            if not symbol or entry_price <= 0 or not analysis_date:
                continue

            bars = _fetch_bars(symbol, analysis_date, horizon_days)
            if bars.empty:
                results.append(
                    TradeBacktestResult(
                        analysis_date=analysis_date,
                        symbol=symbol,
                        name=str(s.get("name", "")),
                        entry_price=entry_price,
                        confidence=confidence,
                        recommendation=float(s.get("scores", {}).get("recommendation", 0.0)),
                        target_price=target_price,
                        stop_loss_price=stop_loss_price,
                        horizon_days=horizon_days,
                        final_return_pct=0.0,
                        max_return_pct=0.0,
                        min_return_pct=0.0,
                        hit_target=False,
                        hit_stop=False,
                        valid=False,
                    )
                )
                continue

            final_ret, max_ret, min_ret, hit_target, hit_stop = _evaluate_trade(
                entry_price, target_price, stop_loss_price, bars
            )
            results.append(
                TradeBacktestResult(
                    analysis_date=analysis_date,
                    symbol=symbol,
                    name=str(s.get("name", "")),
                    entry_price=entry_price,
                    confidence=confidence,
                    recommendation=float(s.get("scores", {}).get("recommendation", 0.0)),
                    target_price=target_price,
                    stop_loss_price=stop_loss_price,
                    horizon_days=horizon_days,
                    final_return_pct=final_ret,
                    max_return_pct=max_ret,
                    min_return_pct=min_ret,
                    hit_target=hit_target,
                    hit_stop=hit_stop,
                    valid=True,
                )
            )

    valid_rows = [r for r in results if r.valid]
    total = len(valid_rows)
    summary = {
        "generated_at": datetime.now().isoformat(),
        "report_dir": str(report_path),
        "horizon_days": horizon_days,
        "min_confidence": min_confidence,
        "total_reports": len(files),
        "total_trades": total,
        "win_rate_pct": round(sum(1 for r in valid_rows if r.final_return_pct > 0) / total * 100, 2) if total else 0.0,
        "avg_final_return_pct": round(sum(r.final_return_pct for r in valid_rows) / total, 2) if total else 0.0,
        "avg_max_return_pct": round(sum(r.max_return_pct for r in valid_rows) / total, 2) if total else 0.0,
        "avg_min_return_pct": round(sum(r.min_return_pct for r in valid_rows) / total, 2) if total else 0.0,
        "target_hit_rate_pct": round(sum(1 for r in valid_rows if r.hit_target) / total * 100, 2) if total else 0.0,
        "stop_hit_rate_pct": round(sum(1 for r in valid_rows if r.hit_stop) / total * 100, 2) if total else 0.0,
        "trades": [asdict(r) for r in results],
    }
    return summary


def _save_backtest_result(summary: dict, report_dir: str) -> tuple[str, str]:
    report_path = Path(report_dir)
    report_path.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = report_path / f"backtest_{ts}.json"
    md_path = report_path / f"backtest_{ts}.md"

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    lines = [
        "# 妖股策略回測報告",
        "",
        f"- 生成時間：{summary['generated_at']}",
        f"- 回測天數：{summary['horizon_days']} 天",
        f"- 最低信心門檻：{summary['min_confidence']}%",
        f"- 報告數量：{summary['total_reports']}",
        f"- 有效交易筆數：{summary['total_trades']}",
        "",
        "## 核心指標",
        f"- 勝率：{summary['win_rate_pct']}%",
        f"- 平均最終報酬：{summary['avg_final_return_pct']}%",
        f"- 平均最大報酬：{summary['avg_max_return_pct']}%",
        f"- 平均最大回撤：{summary['avg_min_return_pct']}%",
        f"- 目標價命中率：{summary['target_hit_rate_pct']}%",
        f"- 停損觸發率：{summary['stop_hit_rate_pct']}%",
        "",
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return str(json_path), str(md_path)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="妖股策略回測")
    p.add_argument("--report-dir", default=REPORT_DIR, help="報告目錄（預設 reports）")
    p.add_argument("--horizon", type=int, default=DEFAULT_BACKTEST_HORIZON_DAYS, help="回測天數")
    p.add_argument("--min-confidence", type=float, default=0.0, help="最低信心門檻（0~100）")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    summary = run_backtest(args.report_dir, args.horizon, args.min_confidence)
    json_path, md_path = _save_backtest_result(summary, args.report_dir)
    print(f"回測完成：{summary['total_trades']} 筆有效交易")
    print(f"   勝率：{summary['win_rate_pct']}%")
    print(f"   平均最終報酬：{summary['avg_final_return_pct']}%")
    print(f"   JSON：{json_path}")
    print(f"   Markdown：{md_path}")


if __name__ == "__main__":
    main()
