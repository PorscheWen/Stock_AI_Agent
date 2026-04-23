#!/usr/bin/env python3
"""
🚀 Stock AI Agent — 妖股多 Agent 交易系統
用法：
  python main.py                  # 分析今日妖股
  python main.py --date 20241220  # 分析指定日期
  python main.py --no-line        # 不推播 LINE
  python main.py --json           # 只輸出 JSON 結果
"""
import argparse
import json
import logging
import sys
from datetime import datetime

from agents.orchestrator import OrchestratorAgent

# ── 日誌設定 ────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="妖股 Multi-Agent 分析系統",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
範例：
  python main.py                   分析今日妖股
  python main.py --date 20241218   分析 2024-12-18 資料
  python main.py --no-line         不推播 LINE 通知
  python main.py --json            僅輸出 JSON，無彩色 log
""",
    )
    p.add_argument(
        "--date",
        help="指定日期（YYYYMMDD），未提供則使用今日",
        default=None,
    )
    p.add_argument(
        "--no-line",
        action="store_true",
        help="不推播 LINE 通知",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="只輸出 JSON 結果（適合程式串接）",
    )
    return p.parse_args()


def _print_report(report: dict) -> None:
    """終端機友善輸出"""
    divider = "─" * 60
    print(f"\n{divider}")
    print(f"  🚀 妖股報告  {report['generated_at'][:10]}")
    print(f"  掃描 {report['total_scanned']} 檔 → 通過 {report['total_candidates']} 檔  耗時 {report['elapsed_seconds']}s")
    print(divider)

    stocks = sorted(
        report["stocks"],
        key=lambda x: x["scores"]["confidence"],
        reverse=True,
    )

    if not stocks:
        print("  ⚠️  今日無妖股通過三重驗證，建議空倉觀望\n")
        print(f"  {report['ai_summary']}\n")
        return

    for rank, s in enumerate(stocks, 1):
        sc = s["scores"]
        ri = s["risk"]
        en = s["entry"]
        ex = s["exit"]
        vl = s["validation"]

        # 顏色符號
        board_emoji = ["", "🔵", "🟢", "🟡", "🔴"].get(
            min(s["consecutive_days"], 4), "⚫"
        )
        passed_icon = "✅" if vl["passed"] else "❌"

        print(f"\n  #{rank} {board_emoji} {s['symbol']} {s['name']}")
        print(f"     收盤 ${s['close']:,.1f}  漲幅 +{s['pct_change']:.1f}%  量比 {s['volume_ratio']:.1f}x")
        print(f"     第 {s['consecutive_days']} 板 | 動能 {sc['momentum']:.0f} | 催化劑 {sc['catalyst']:.0f} | 信心 {sc['confidence']:.0f}%")
        print(f"     題材：{s['catalyst']['category'].upper()} ({s['catalyst']['durability']})")
        print(f"     {passed_icon} {vl['verdict']}")
        print()
        print(f"     🎯 進場：{en['method']}")
        print(f"        時機：{en['timing']}")
        print()
        print(f"     🚪 出場：{ex['summary']}")
        print(f"        停損：${ri['stop_loss_price']:,.2f}（-{ri['stop_loss_pct']:.1f}%）")
        print(f"        目標：${ri['target_price']:,.2f}  風報比 {ri['risk_reward_ratio']:.1f}:1")
        print()
        print(f"     💰 建議倉位：{ri['position_pct']:.0%}  風險等級：{ri['risk_label']}")

        if en.get("condition"):
            print(f"     ⚠️  進場條件：{en['condition']}")

        if ex.get("emergency_rules"):
            print(f"     🚨 緊急規則：{ex['emergency_rules'][0]}")

        print(f"  {divider}")

    print(f"\n  📝 AI 總結：")
    print(f"  {report['ai_summary']}\n")


def main() -> None:
    args = parse_args()

    if args.json:
        # JSON-only 模式：關閉 log
        logging.disable(logging.CRITICAL)

    date_str = args.date
    if date_str:
        try:
            datetime.strptime(date_str, "%Y%m%d")
        except ValueError:
            print(f"錯誤：日期格式錯誤，請使用 YYYYMMDD，例如 20241218", file=sys.stderr)
            sys.exit(1)

    orchestrator = OrchestratorAgent()

    try:
        report = orchestrator.run(
            date_str=date_str,
            enable_line=not args.no_line,
        )
    except KeyboardInterrupt:
        print("\n[中斷] 使用者手動停止", file=sys.stderr)
        sys.exit(0)
    except Exception as e:
        logger.error(f"分析失敗：{e}")
        sys.exit(1)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_report(report)


if __name__ == "__main__":
    main()
