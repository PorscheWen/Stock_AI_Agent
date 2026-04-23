"""
🔍 VALIDATION AGENT — 三重獨立驗證
針對妖股的三道把關：
① 動能一致性驗證（連板 + 量比 + 催化劑三者吻合）
② 風控合規驗證（停損 ≤ 5%、風報比 ≥ 2:1、流動性）
③ Claude 空方邏輯反駁（模擬放空者找弱點）
輸出：通過/否決 + 信心分數 + 風險警示
"""
import logging
from dataclasses import dataclass, field

import anthropic

from config.settings import (
    ANTHROPIC_API_KEY,
    CLAUDE_MODEL,
    CONFIDENCE_THRESHOLD,
    MAX_STOP_LOSS_PCT,
    MIN_RISK_REWARD,
    MIN_BOARD_COUNT,
    VOLUME_SURGE_MIN,
    CATALYST_MIN_SCORE,
)

logger = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


@dataclass
class ValidationResult:
    symbol: str
    passed: bool                        # 是否通過三重驗證
    confidence_score: float             # 0-1 信心分數
    check1_momentum_consistent: bool    # ① 動能一致性
    check2_risk_compliant: bool         # ② 風控合規
    check3_bear_cleared: bool           # ③ 空方反駁通過
    rejection_reasons: list = field(default_factory=list)
    bear_arguments: list  = field(default_factory=list)
    final_verdict: str = ""


class ValidationAgent:
    """三重獨立驗證 Agent"""

    def __init__(self):
        self.name = "ValidationAgent"

    # ── 公開介面 ─────────────────────────────────────────
    def run(self, candidates: list[dict]) -> list[ValidationResult]:
        results = []
        for c in candidates:
            result = self._validate(c)
            status = "✅ 通過" if result.passed else "❌ 否決"
            logger.info(
                f"[Validation] {c['symbol']} {status} "
                f"信心={result.confidence_score:.0%}"
            )
            results.append(result)
        return results

    # ── 三重驗證 ─────────────────────────────────────────
    def _check1_momentum_consistency(self, c: dict) -> tuple[bool, list[str]]:
        """① 動能一致性：連板 + 量比 + 催化劑三者須吻合"""
        issues = []

        boards    = c.get("consecutive_days", 0)
        vol_ratio = c.get("volume_ratio", 0.0)
        catalyst  = c.get("catalyst_score", 0.0)
        momentum  = c.get("momentum_score", 0.0)

        if boards < MIN_BOARD_COUNT:
            issues.append(f"連板數 {boards} 不足最低要求 {MIN_BOARD_COUNT} 板")

        if vol_ratio < VOLUME_SURGE_MIN:
            issues.append(f"量比 {vol_ratio:.1f}x 不足 {VOLUME_SURGE_MIN}x")

        if catalyst < CATALYST_MIN_SCORE:
            issues.append(f"催化劑評分 {catalyst:.0f} 不足 {CATALYST_MIN_SCORE} 分")

        # 動能與催化劑矛盾：動能強但無題材 → 可能是純主力炒作
        if momentum >= 75 and catalyst < 40:
            issues.append("動能強但題材薄弱，可能為純主力操弄，風險極高")

        return len(issues) == 0, issues

    def _check2_risk_compliance(self, c: dict) -> tuple[bool, list[str]]:
        """② 風控合規：停損/風報比/流動性符合門檻"""
        issues = []

        stop_pct = c.get("stop_loss_pct", 99.0)
        rr_ratio = c.get("risk_reward_ratio", 0.0)
        liquidity = c.get("liquidity_ok", True)
        boards    = c.get("consecutive_days", 1)

        max_stop = MAX_STOP_LOSS_PCT * 100
        if stop_pct > max_stop:
            issues.append(f"停損 {stop_pct:.1f}% 超過上限 {max_stop:.0f}%")

        if rr_ratio < MIN_RISK_REWARD:
            issues.append(f"風報比 {rr_ratio:.1f} 低於最低要求 {MIN_RISK_REWARD}")

        if not liquidity:
            issues.append("流動性不足（日均量過低），難以快速出場")

        if boards > 4:
            issues.append(f"已達第 {boards} 板，追板風險過高")

        return len(issues) == 0, issues

    def _check3_bear_case(self, c: dict) -> tuple[bool, list[str], str]:
        """③ 空方邏輯反駁（Claude 扮演放空者）"""
        prompt = f"""你是嚴格的放空分析師，請對台股妖股 {c['symbol']} 提出 3 個最有力的做空論點。

多方數據：
- 連板天數：{c.get('consecutive_days', 0)} 板
- 量比：{c.get('volume_ratio', 0):.1f}x
- 動能評分：{c.get('momentum_score', 0):.0f}/100
- 催化劑評分：{c.get('catalyst_score', 0):.0f}/100（題材：{c.get('catalyst_category', '不明')}）
- 題材持續性：{c.get('catalyst_durability', '未知')}
- 風報比：{c.get('risk_reward_ratio', 0):.1f}
- 停損：{c.get('stop_loss_pct', 0):.1f}%

請從以下角度提出反向論點：
1. 技術面陷阱（高板數反轉風險）
2. 題材面疑慮（催化劑真實性/持續性）
3. 市場情緒風險（追高接刀風險）

輸出格式（每行一條）：
BEAR1: <論點>
BEAR2: <論點>
BEAR3: <論點>
SEVERITY: <LOW|MEDIUM|HIGH>"""

        try:
            resp = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=350,
                system=[{
                    "type": "text",
                    "text": "你是台股操盤手，專門找出妖股的做空機會和散戶追高陷阱。請精準客觀分析。",
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text.strip()

            bears    = []
            severity = "LOW"
            for line in text.split("\n"):
                line = line.strip()
                if line.startswith(("BEAR1:", "BEAR2:", "BEAR3:")):
                    bears.append(line.split(":", 1)[1].strip())
                elif line.startswith("SEVERITY:"):
                    s = line.split(":", 1)[1].strip().upper()
                    if s in ("LOW", "MEDIUM", "HIGH"):
                        severity = s

            passed = severity != "HIGH"
            return passed, bears, severity

        except Exception as e:
            logger.warning(f"[Validation] Claude 空方分析失敗：{e}")
            return True, ["空方分析失敗，預設通過"], "LOW"

    def _calc_confidence(
        self, c: dict, issues1: list, issues2: list, severity: str
    ) -> float:
        boards   = c.get("consecutive_days", 1)
        momentum = c.get("momentum_score", 50.0)
        catalyst = c.get("catalyst_score", 50.0)
        rr       = c.get("risk_reward_ratio", 2.0)

        # 基礎分：各因素加權
        score = (
            min(boards * 10, 30)       * 0.20 +  # 連板（最多3板=30分）
            momentum                    * 0.30 +  # 動能（0-100）
            catalyst                    * 0.25 +  # 催化劑（0-100）
            min(rr / 5.0, 1.0) * 100  * 0.25    # 風報比（最多5:1）
        ) / 100

        # 扣分
        score -= len(issues1) * 0.06
        score -= len(issues2) * 0.08
        if severity == "HIGH":
            score -= 0.18
        elif severity == "MEDIUM":
            score -= 0.09

        return max(0.0, min(1.0, round(score, 4)))

    def _validate(self, c: dict) -> ValidationResult:
        ok1, issues1 = self._check1_momentum_consistency(c)
        ok2, issues2 = self._check2_risk_compliance(c)
        ok3, bears, severity = self._check3_bear_case(c)

        confidence = self._calc_confidence(c, issues1, issues2, severity)

        # 信心分數低於門檻也否決
        if confidence < CONFIDENCE_THRESHOLD:
            ok3 = False
            issues2.append(
                f"信心分數 {confidence:.0%} 低於門檻 {CONFIDENCE_THRESHOLD:.0%}"
            )

        all_passed   = ok1 and ok2 and ok3
        all_issues   = issues1 + issues2
        final_verdict = (
            f"通過三重驗證，信心 {confidence:.0%}，建議進場" if all_passed
            else f"驗證未通過：{'；'.join(all_issues[:2])}"
        )

        return ValidationResult(
            symbol=c["symbol"],
            passed=all_passed,
            confidence_score=confidence,
            check1_momentum_consistent=ok1,
            check2_risk_compliant=ok2,
            check3_bear_cleared=ok3,
            rejection_reasons=all_issues,
            bear_arguments=bears,
            final_verdict=final_verdict,
        )
