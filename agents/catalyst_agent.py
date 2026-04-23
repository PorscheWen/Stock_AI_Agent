"""
🔬 CATALYST AGENT — 催化劑分析
抓取 Google RSS 個股新聞，使用 Claude Haiku 評估：
- 題材真實性（業績/政策/供應鏈 vs 純炒作）
- 題材持續性（一次性 / 短期 / 長期）
- 市場共識程度
輸出：催化劑評分 0-100 + 題材分類 + 摘要
"""
import logging
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Optional

import anthropic
import feedparser

from config.settings import (
    ANTHROPIC_API_KEY,
    CLAUDE_HAIKU,
    CATALYST_CATEGORIES,
    CATALYST_MIN_SCORE,
)

logger = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

GOOGLE_RSS_ZH = (
    "https://news.google.com/rss/search?q={q}"
    "&hl=zh-TW&gl=TW&ceid=TW:zh-Hant&num=10"
)
GOOGLE_RSS_EN = (
    "https://news.google.com/rss/search?q={q}"
    "&hl=en-US&gl=US&ceid=US:en&num=10"
)


@dataclass
class CatalystResult:
    symbol: str
    catalyst_score: float      # 0-100，越高越有說服力
    category: str              # 題材類別（見 settings.CATALYST_CATEGORIES）
    durability: str            # "long" / "short" / "one-time"
    headlines: list = field(default_factory=list)   # 相關新聞標題
    summary: str = ""          # Claude 摘要
    warning: str = ""          # 風險警示


class CatalystAgent:
    """催化劑分析 Agent"""

    def __init__(self):
        self.name = "CatalystAgent"

    # ── 公開介面 ─────────────────────────────────────────
    def run(
        self, symbols: list[str], name_map: dict[str, str] | None = None
    ) -> dict[str, CatalystResult]:
        results = {}
        for symbol in symbols:
            try:
                name = (name_map or {}).get(symbol)  # 使用真實公司名稱
                result = self._analyze(symbol, name)
                if result:
                    results[symbol] = result
                    logger.info(
                        f"[Catalyst] {symbol} 題材={result.category} "
                        f"評分={result.catalyst_score:.1f} 持續性={result.durability}"
                    )
            except Exception as e:
                logger.warning(f"[Catalyst] {symbol} 分析失敗：{e}")
        return results

    # ── 內部方法 ─────────────────────────────────────────
    def _fetch_news(self, code: str, name: str) -> list[str]:
        """抓取個股相關新聞標題（中英文 RSS）"""
        headlines = []
        queries = [
            urllib.parse.quote(f"{code} {name} 股票"),
            urllib.parse.quote(f"{name} 漲停 題材"),
        ]
        for q in queries:
            try:
                feed = feedparser.parse(GOOGLE_RSS_ZH.format(q=q))
                for entry in feed.get("entries", [])[:5]:
                    title = entry.get("title", "").strip()
                    if title:
                        headlines.append(title)
            except Exception:
                pass

        # 英文查詢（美股或國際供應鏈關聯）
        en_q = urllib.parse.quote(f"Taiwan {name} stock")
        try:
            feed = feedparser.parse(GOOGLE_RSS_EN.format(q=en_q))
            for entry in feed.get("entries", [])[:3]:
                title = entry.get("title", "").strip()
                if title:
                    headlines.append(title)
        except Exception:
            pass

        return list(dict.fromkeys(headlines))[:10]  # 去重，最多 10 則

    def _claude_evaluate(
        self, symbol: str, name: str, headlines: list[str]
    ) -> tuple[float, str, str, str, str]:
        """用 Claude Haiku 評估題材品質"""
        if not headlines:
            return 20.0, "unknown", "one-time", "無相關新聞，可能為純技術面炒作", "缺乏題材支撐"

        headlines_text = "\n".join(f"- {h}" for h in headlines[:5])
        prompt = f"""台股 {symbol}（{name}）漲停題材分析，新聞：
{headlines_text}

嚴格按此格式輸出5行，不加其他內容：
SCORE: <0-100整數>
CATEGORY: <policy|earnings|supply_chain|concept|turnaround|unknown>
DURATION: <long|short|one-time>
SUMMARY: <20字內>
WARNING: <15字內，無風險填無>"""

        try:
            resp = client.messages.create(
                model=CLAUDE_HAIKU,
                max_tokens=120,
                system=[{
                    "type": "text",
                    "text": "台股題材分析師，判斷漲停驅動力。僅輸出指定格式。",
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text.strip()

            score     = 50.0
            category  = "unknown"
            durability = "one-time"
            summary   = ""
            warning   = ""

            for line in text.split("\n"):
                # 去除 markdown 粗體（**SCORE:**）與前後空白
                line = re.sub(r"\*+", "", line).strip()
                if re.match(r"SCORE:", line, re.IGNORECASE):
                    try:
                        score = float(re.search(r"\d+", line).group())
                    except Exception:
                        pass
                elif re.match(r"CATEGORY:", line, re.IGNORECASE):
                    # 取第一個有效類別（防止 concept|earnings 多值）
                    cat_raw = line.split(":", 1)[1].strip().lower()
                    for cat_token in re.split(r"[|,/\s]+", cat_raw):
                        cat_token = cat_token.strip()
                        if cat_token in CATALYST_CATEGORIES:
                            category = cat_token
                            break
                elif re.match(r"DURAB|DURATION", line, re.IGNORECASE):
                    dur = line.split(":", 1)[1].strip().lower()
                    if dur in ("long", "short", "one-time"):
                        durability = dur
                elif re.match(r"SUMMARY:", line, re.IGNORECASE):
                    summary = line.split(":", 1)[1].strip()
                elif re.match(r"WARNING:", line, re.IGNORECASE):
                    w = line.split(":", 1)[1].strip()
                    warning = "" if w in ("無", "none", "-") else w

            return score, category, durability, summary, warning

        except Exception as e:
            logger.warning(f"[Catalyst] Claude 呼叫失敗：{e}")
            return 40.0, "unknown", "one-time", "題材分析失敗", str(e)

    def _analyze(self, symbol: str, name: str | None = None) -> Optional[CatalystResult]:
        # 從 symbol 拆解代號與名稱
        code = symbol.replace(".TW", "").replace(".TWO", "")
        name = name or code  # 優先使用傳入的公司名稱

        headlines = self._fetch_news(code, name)
        score, category, durability, summary, warning = self._claude_evaluate(
            symbol, name, headlines
        )

        return CatalystResult(
            symbol=symbol,
            catalyst_score=round(score, 1),
            category=category,
            durability=durability,
            headlines=headlines,
            summary=summary,
            warning=warning,
        )
