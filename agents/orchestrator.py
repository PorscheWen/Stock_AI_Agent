"""
🎯 ORCHESTRATOR AGENT — 主控協調中心
統籌所有子 Agent，採並行+順序混合執行：
Step 1 → ScannerAgent（序列，基礎資料）
Step 2 → MomentumAgent + CatalystAgent + RiskAgent（ThreadPool 並行）
Step 3 → EntryAgent + ExitAgent（序列，依賴 Step 2 結果）
Step 4 → ValidationAgent（序列，最終把關）
Step 5 → Claude Opus 口語總結 + LINE 推播
"""
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime

import anthropic
from dotenv import load_dotenv

from agents.scanner_agent import ScannerAgent
from agents.momentum_agent import MomentumAgent
from agents.catalyst_agent import CatalystAgent
from agents.risk_agent import RiskAgent
from agents.entry_agent import EntryAgent
from agents.exit_agent import ExitAgent
from agents.validation_agent import ValidationAgent
from agents import line_notifier
from config.settings import (
    ANTHROPIC_API_KEY,
    CLAUDE_MODEL,
    REPORT_DIR,
)

load_dotenv()
logger = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


class OrchestratorAgent:
    """多 Agent 協調中心"""

    def __init__(self):
        self.scanner   = ScannerAgent()
        self.momentum  = MomentumAgent()
        self.catalyst  = CatalystAgent()
        self.risk      = RiskAgent()
        self.entry     = EntryAgent()
        self.exit      = ExitAgent()
        self.validator = ValidationAgent()

    # ── 主流程 ────────────────────────────────────────────
    def run(self, *, date_str: str | None = None, enable_line: bool = True) -> dict:
        start = time.time()
        today = date_str or datetime.now().strftime("%Y%m%d")
        logger.info("=" * 60)
        logger.info(f"[Orchestrator] 妖股分析開始 {today}")

        # Step 1 — 掃描
        logger.info("[Step 1] 掃描妖股候選")
        scan_results = self.scanner.run(date_str=today)
        if not scan_results:
            logger.warning("[Step 1] 今日無妖股候選，提早結束")
            return self._empty_report(today, time.time() - start)

        symbols    = [s.symbol for s in scan_results]
        scan_map   = {s.symbol: s for s in scan_results}
        board_map  = {s.symbol: s.consecutive_days for s in scan_results}
        name_map   = {s.symbol: s.name for s in scan_results}  # 公司名稱對照

        logger.info(f"[Step 1] 發現 {len(symbols)} 檔候選：{symbols}")

        # Step 2 — 並行分析（Momentum + Catalyst + Risk）
        logger.info("[Step 2] 並行：動能 / 催化劑 / 風控")
        momentum_map, catalyst_map, risk_map = self._parallel_analysis(
            symbols, board_map, name_map
        )

        # Step 3 — 整合候選資料
        candidates = self._merge_candidates(
            scan_results, momentum_map, catalyst_map, risk_map
        )

        # Step 4 — Entry + Exit（依候選清單）
        logger.info("[Step 4] 進場 / 出場策略")
        entry_map = self.entry.run(candidates)
        exit_map  = self.exit.run(candidates)

        # Step 5 — 最終驗證
        logger.info("[Step 5] 三重驗證")
        val_results = self.validator.run(candidates)
        passed      = [v for v in val_results if v.passed]
        passed_set  = {v.symbol for v in passed}
        logger.info(f"[Step 5] 通過 {len(passed)}/{len(candidates)} 檔")

        # Step 6 — 建構報告
        approved_stocks = [
            self._build_stock_dict(c, momentum_map, catalyst_map, risk_map,
                                   entry_map, exit_map, val_results)
            for c in candidates if c["symbol"] in passed_set
        ]

        # Step 7 — Claude Opus 口語總結
        logger.info("[Step 7] Claude Opus 生成總結")
        ai_summary = self._generate_summary(approved_stocks, today)

        elapsed = round(time.time() - start)
        report  = {
            "generated_at"    : datetime.now().isoformat(),
            "analysis_date"   : today,
            "total_scanned"   : len(symbols),
            "total_candidates": len(approved_stocks),
            "elapsed_seconds" : elapsed,
            "stocks"          : approved_stocks,
            "ai_summary"      : ai_summary,
        }

        # Step 8 — 儲存 + 推播
        report_path = self._save_report(report, today)
        logger.info(f"[Step 8] 報告儲存至 {report_path}")

        if enable_line:
            line_notifier.push_report(report)

        logger.info(f"[Orchestrator] 完成，耗時 {elapsed}s")
        return report

    # ── 並行分析 ─────────────────────────────────────────
    def _parallel_analysis(
        self,
        symbols: list[str],
        board_map: dict[str, int],
        name_map: dict[str, str] | None = None,
    ) -> tuple[dict, dict, dict]:
        momentum_map: dict = {}
        catalyst_map: dict = {}
        risk_map: dict     = {}

        def run_momentum():
            return self.momentum.run(symbols)  # 已回傳 dict[str, MomentumResult]

        def run_catalyst():
            return self.catalyst.run(symbols, name_map)  # 已回傳 dict[str, CatalystResult]

        def run_risk():
            return self.risk.run(symbols, board_map)  # 已回傳 dict[str, RiskResult]

        tasks = {
            "momentum": run_momentum,
            "catalyst": run_catalyst,
            "risk"    : run_risk,
        }

        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {pool.submit(fn): name for name, fn in tasks.items()}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    result = future.result()
                    if name == "momentum":
                        momentum_map = result
                    elif name == "catalyst":
                        catalyst_map = result
                    elif name == "risk":
                        risk_map = result
                except Exception as e:
                    logger.error(f"[Step 2] {name} 失敗：{e}")

        return momentum_map, catalyst_map, risk_map

    # ── 整合 ─────────────────────────────────────────────
    def _merge_candidates(
        self,
        scan_results,
        momentum_map: dict,
        catalyst_map: dict,
        risk_map: dict,
    ) -> list[dict]:
        candidates = []
        for sr in scan_results:
            sym = sr.symbol
            mm  = momentum_map.get(sym)
            cm  = catalyst_map.get(sym)
            rm  = risk_map.get(sym)

            c = {
                "symbol"         : sym,
                "name"           : sr.name,
                "close"          : sr.close,
                "pct_change"     : sr.pct_change,
                "volume_ratio"   : sr.volume_ratio,
                "consecutive_days": sr.consecutive_days,
                # Momentum
                "momentum_score" : mm.momentum_score if mm else 50.0,
                "open_break_count": mm.open_break_count if mm else 0,
                "avg_turnover_rate": mm.avg_turnover_rate if mm else 0.0,
                # Catalyst
                "catalyst_score"    : cm.catalyst_score if cm else 50.0,
                "catalyst_category" : cm.category if cm else "unknown",
                "catalyst_durability": cm.durability if cm else "unknown",
                "catalyst_summary"  : cm.summary if cm else "",
                "catalyst_warning"  : cm.warning if cm else "",
                # Risk
                "stop_loss_price"  : rm.stop_loss_price if rm else sr.close * 0.95,
                "stop_loss_pct"    : rm.stop_loss_pct if rm else 5.0,
                "target_price"     : rm.target_price if rm else sr.close * 1.20,
                "risk_reward_ratio": rm.risk_reward_ratio if rm else 2.0,
                "position_pct"     : rm.suggested_position_pct if rm else 0.10,
                "liquidity_ok"     : rm.liquidity_ok if rm else True,
                "risk_level"       : rm.risk_level if rm else 3,
            }
            candidates.append(c)
        return candidates

    def _build_stock_dict(
        self, c: dict, momentum_map, catalyst_map, risk_map, entry_map, exit_map, val_results
    ) -> dict:
        sym = c["symbol"]
        rm  = risk_map.get(sym)
        em  = entry_map.get(sym)
        xm  = exit_map.get(sym)
        vm  = next((v for v in val_results if v.symbol == sym), None)

        return {
            "symbol"         : sym,
            "name"           : c["name"],
            "close"          : c["close"],
            "pct_change"     : c["pct_change"],
            "volume_ratio"   : c["volume_ratio"],
            "consecutive_days": c["consecutive_days"],
            "scores": {
                "momentum"  : c["momentum_score"],
                "catalyst"  : c["catalyst_score"],
                "confidence": round(vm.confidence_score * 100, 1) if vm else 0,
            },
            "risk": {
                "level"            : rm.risk_level if rm else 3,
                "risk_label"       : rm.risk_label if rm else "中等風險",
                "stop_loss_price"  : c["stop_loss_price"],
                "stop_loss_pct"    : c["stop_loss_pct"],
                "target_price"     : c["target_price"],
                "risk_reward_ratio": c["risk_reward_ratio"],
                "position_pct"     : c["position_pct"],
            },
            "entry": {
                "method": em.entry_method if em else "",
                "timing": em.timing if em else "",
                "condition": em.entry_condition if em else "",
            },
            "exit": {
                "summary"        : xm.summary if xm else "",
                "partial_plan"   : xm.partial_exit_plan if xm else [],
                "emergency_rules": xm.emergency_rules if xm else [],
            },
            "catalyst": {
                "score"     : c["catalyst_score"],
                "category"  : c["catalyst_category"],
                "durability": c["catalyst_durability"],
                "summary"   : c["catalyst_summary"],
                "warning"   : c["catalyst_warning"],
            },
            "validation": {
                "passed": vm.passed if vm else False,
                "check1": vm.check1_momentum_consistent if vm else False,
                "check2": vm.check2_risk_compliant if vm else False,
                "check3": vm.check3_bear_cleared if vm else False,
                "bear_args": vm.bear_arguments if vm else [],
                "verdict": vm.final_verdict if vm else "",
            },
        }

    # ── Claude 口語總結 ───────────────────────────────────
    def _generate_summary(self, stocks: list[dict], date_str: str) -> str:
        if not stocks:
            return "今日無妖股通過三重驗證，建議觀望。"

        top = [
            f"{s['symbol']} {s['name']} 第{s['consecutive_days']}板 "
            f"信心{s['scores']['confidence']:.0f}% 題材:{s['catalyst']['category']}"
            for s in stocks[:5]
        ]
        prompt = f"""今日 {date_str} 共 {len(stocks)} 檔妖股通過驗證：
{chr(10).join(top)}

用80字（繁體中文）說明：市場氛圍、最強標的、操作要點。"""

        try:
            resp = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=200,
                system=[{
                    "type": "text",
                    "text": "台股操盤手，精簡專業。",
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.content[0].text.strip()
        except Exception as e:
            logger.warning(f"[Orchestrator] 總結生成失敗：{e}")
            return f"今日 {len(stocks)} 檔妖股通過驗證，請留意止損紀律。"

    # ── 工具 ─────────────────────────────────────────────
    def _save_report(self, report: dict, today: str) -> str:
        os.makedirs(REPORT_DIR, exist_ok=True)
        path = os.path.join(REPORT_DIR, f"yaogu_{today}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        return path

    def _empty_report(self, today: str, elapsed: float) -> dict:
        return {
            "generated_at"    : datetime.now().isoformat(),
            "analysis_date"   : today,
            "total_scanned"   : 0,
            "total_candidates": 0,
            "elapsed_seconds" : round(elapsed),
            "stocks"          : [],
            "ai_summary"      : "今日無妖股候選",
        }
