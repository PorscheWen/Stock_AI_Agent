"""
auto_update_keywords.py
每週自動分析近 7 天未命中新聞 → 呼叫 Claude API → 更新 keywords.json
排程：每週日 22:00（由 Windows 工作排程器執行）
"""

import sys, io, os, json, re, feedparser, urllib.parse
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
import anthropic

# ── 設定 ──────────────────────────────────────────
BASE_DIR      = Path(__file__).parent
KEYWORDS_FILE = BASE_DIR / "keywords.json"
LOG_FILE      = BASE_DIR / "keyword_update_log.txt"
ENV_FILE      = Path("C:/Users/BaoGo/Documents/ClaudeCode/.env")

load_dotenv(ENV_FILE)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

GOOGLE_RSS_EN = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en&num=20"
GOOGLE_RSS_ZH = "https://news.google.com/rss/search?q={q}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant&num=20"

NEWS_QUERIES_EN = {
    "trump_policy":   "Trump+tariff+trade+Taiwan",
    "taiwan_strait":  "Taiwan+Strait+China+military+PLA",
    "tsmc_semi":      "TSMC+semiconductor+chip+AI+revenue",
    "fed_rate":       "Federal+Reserve+interest+rate+inflation",
    "taiwan_economy": "Taiwan+economy+export+GDP",
    "us_china":       "US+China+trade+war+sanction+technology",
}
NEWS_QUERIES_ZH = {
    "cna_economy":  "site:cna.com.tw (台積電 OR 半導體 OR 關稅 OR 出口 OR 股市 OR AI晶片)",
    "cna_politics": "site:cna.com.tw (台海 OR 兩岸 OR 解放軍 OR 美台 OR 涉台 OR 統戰)",
    "pts_economy":  "site:news.pts.org.tw (台積電 OR 半導體 OR 股市 OR 台股 OR 關稅)",
    "pts_politics": "site:news.pts.org.tw (台海 OR 兩岸 OR 解放軍 OR 美台 OR 軍演)",
}

CATEGORY_ZH = {
    "trump":    "川普/關稅政策",
    "strait":   "台海/兩岸局勢",
    "semi":     "半導體/TSMC",
    "fed":      "Fed/利率",
    "tw_macro": "台灣總體經濟",
    "us_china": "美中關係",
    "other":    "其他",
}


# ── Step 1: 抓近 7 天新聞 ─────────────────────────
def fetch_all_news(days: int = 7) -> list[dict]:
    cutoff = datetime.utcnow() - timedelta(days=days)
    entries = []

    for cat, q in NEWS_QUERIES_EN.items():
        url = GOOGLE_RSS_EN.format(q=q)
        try:
            feed = feedparser.parse(url)
            for e in feed.get("entries", [])[:20]:
                ps = e.get("published_parsed")
                if ps and datetime(*ps[:6]) < cutoff:
                    continue
                pub_dt = datetime(*ps[:6]) if ps else datetime.utcnow()
                entries.append({
                    "title_raw": e.get("title", ""),
                    "title":     e.get("title", "").lower(),
                    "source":    e.get("source", {}).get("title", ""),
                    "pub":       pub_dt.strftime("%m/%d %H:%M"),
                    "cat":       cat, "lang": "en",
                })
        except Exception:
            pass

    for cat, q in NEWS_QUERIES_ZH.items():
        url = GOOGLE_RSS_ZH.format(q=urllib.parse.quote(q))
        try:
            feed = feedparser.parse(url)
            for e in feed.get("entries", [])[:20]:
                ps = e.get("published_parsed")
                if ps and datetime(*ps[:6]) < cutoff:
                    continue
                pub_dt = datetime(*ps[:6]) if ps else datetime.utcnow()
                raw = e.get("title", "")
                clean = re.sub(
                    r"\s*[|｜]\s*(政治|財經|兩岸|社會|國際|科技|生活|產經|證券|地方|影劇|運動|教育).*$",
                    "", raw).strip()
                clean = re.sub(r"\s*[-–]\s*(中央社|CNA|公視|PTS|PNN).*$", "", clean).strip()
                src = e.get("source", {}).get("title", "")
                if not src:
                    src = "中央社 CNA" if "cna.com.tw" in e.get("link","") else \
                          "公視新聞" if "pts.org.tw" in e.get("link","") else ""
                entries.append({
                    "title_raw": raw, "title": clean.lower(), "title_zh": clean,
                    "source": src, "pub": pub_dt.strftime("%m/%d %H:%M"),
                    "cat": cat, "lang": "zh",
                })
        except Exception:
            pass

    # 去重
    seen, unique = set(), []
    for e in entries:
        k = e["title"][:50]
        if k not in seen:
            seen.add(k)
            unique.append(e)

    return unique


# ── Step 2: 找未命中新聞 ──────────────────────────
def find_unmatched(entries: list[dict], rules: list[dict]) -> list[dict]:
    unmatched = []
    for entry in entries:
        title = entry["title"]
        hit = any(r["keyword"].lower() in title for r in rules)
        if not hit:
            unmatched.append(entry)
    return unmatched


# ── Step 3: 用 Claude API 分類候選關鍵字 ─────────
CLASSIFY_PROMPT = """\
你是台股投資新聞分析專家。
以下是近期未被關鍵字系統命中的新聞標題（共 {n} 則）。

請你：
1. 判斷每則新聞對「台灣股市短期走勢」的影響（正面/負面/中性）
2. 若有明確影響，提取一個 2~6 字的核心關鍵詞（中文）或 2~4 字的英文片語
3. 給予 -20 到 +20 的影響分數（正=利多，負=利空，0=無影響）
4. 歸類：trump（川普/關稅）/ strait（台海/兩岸）/ semi（半導體/TSMC）/ fed（Fed/利率）/ tw_macro（台灣總體）/ us_china（美中）/ other（略過）
5. 標記 skip=true 表示不需要新增規則（中性、無關或已有類似規則）

---
新聞標題：
{titles}
---

請以 JSON 陣列回傳，格式如下（只回傳 JSON，不要多餘說明）：
[
  {{
    "title": "原始標題（前30字）",
    "keyword": "核心關鍵詞",
    "score": 數字,
    "label": "中文說明（10字內）",
    "category": "分類",
    "skip": false
  }},
  ...
]

注意：
- 只有 |分數| >= 8 且 skip=false 才值得新增
- 若分數絕對值 < 8 或影響不明確，設 skip=true
- 每個 keyword 需足夠通用，未來其他類似標題也能命中
- 避免過度具體的人名、日期、數字
"""


def classify_with_claude(unmatched: list[dict]) -> list[dict]:
    if not ANTHROPIC_API_KEY:
        print("  [WARN] 未設定 ANTHROPIC_API_KEY，跳過 Claude 分類")
        return []

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    results = []

    # 每批 20 則，避免 token 超限
    batch_size = 20
    for i in range(0, len(unmatched), batch_size):
        batch = unmatched[i:i + batch_size]
        titles_text = "\n".join(
            f"{j+1}. [{e.get('source','')[:10]}] {e.get('title_zh') or e['title_raw']}"
            for j, e in enumerate(batch)
        )

        prompt = CLASSIFY_PROMPT.format(n=len(batch), titles=titles_text)

        try:
            msg = client.messages.create(
                model="claude-haiku-4-5-20251001",   # 快速省 token
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = msg.content[0].text.strip()

            # 清除 markdown code block
            raw = re.sub(r"^```(?:json)?\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)

            classified = json.loads(raw)
            results.extend(classified)
            print(f"  批次 {i//batch_size + 1}：分類 {len(classified)} 則")
        except Exception as e:
            print(f"  [ERROR] Claude 分類失敗：{e}")

    return results


# ── Step 4: 更新 keywords.json ────────────────────
def update_keywords(new_candidates: list[dict]) -> tuple[int, list[dict]]:
    """將新候選加入 keywords.json，回傳 (新增數, 新增規則列表)"""
    with open(KEYWORDS_FILE, encoding="utf-8") as f:
        data = json.load(f)

    existing_keywords = {r["keyword"].lower() for r in data["rules"]}
    added = []

    for c in new_candidates:
        if c.get("skip"):
            continue
        kw = c.get("keyword", "").strip()
        score = c.get("score", 0)
        label = c.get("label", "")
        cat   = c.get("category", "other")

        if not kw or cat == "other":
            continue
        if abs(score) < 8:
            continue
        if kw.lower() in existing_keywords:
            continue

        rule = {"keyword": kw, "score": score, "label": label, "category": cat}
        data["rules"].append(rule)
        existing_keywords.add(kw.lower())
        added.append(rule)

    if added:
        data["updated_at"] = datetime.now().strftime("%Y-%m-%d")
        data["version"] = str(round(float(data.get("version", "1.0")) + 0.1, 1))
        with open(KEYWORDS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    return len(added), added


# ── Step 5: 寫 Log ────────────────────────────────
def write_log(stats: dict, added: list[dict]):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"\n{'='*60}\n")
        f.write(f"[{timestamp}] 每週關鍵字自動更新\n")
        f.write(f"  掃描新聞：{stats['total']} 則（近7天）\n")
        f.write(f"  未命中：{stats['unmatched']} 則\n")
        f.write(f"  送 Claude 分類：{stats['classified']} 則\n")
        f.write(f"  新增關鍵字：{stats['added']} 條\n")
        if added:
            f.write(f"\n  新增詳細：\n")
            for r in added:
                f.write(f"    [{r['score']:+3d}][{r['category']:8s}] {r['keyword']:20s} → {r['label']}\n")
        f.write(f"{'='*60}\n")


# ── 傳送 LINE 通知 ────────────────────────────────
def notify_line(stats: dict, added: list[dict]):
    channel_id     = "2009776475"
    channel_secret = "256e8e8c2dfc910a03bdf156cbe3f50d"
    user_id        = "Uc4b6168aaeef9ffdf18e4ab0273ff9b9"

    import requests as req

    token_resp = req.post(
        "https://api.line.me/oauth2/v3/token",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "client_credentials",
              "client_id": channel_id, "client_secret": channel_secret},
        timeout=10,
    )
    if token_resp.status_code != 200:
        return
    token = token_resp.json()["access_token"]

    if added:
        added_lines = "\n".join(
            f"  [{r['score']:+3d}][{r['category']}] {r['keyword']} → {r['label']}"
            for r in added[:10]
        )
        text = (
            f"🔄 每週關鍵字自動更新完成\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"掃描：{stats['total']} 則新聞（近7天）\n"
            f"未命中：{stats['unmatched']} 則\n"
            f"新增關鍵字：{stats['added']} 條\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"新增清單：\n{added_lines}"
        )
    else:
        text = (
            f"✅ 每週關鍵字更新：無新增\n"
            f"掃描 {stats['total']} 則，未命中 {stats['unmatched']} 則\n"
            f"現有規則已能完整覆蓋本週新聞"
        )

    req.post(
        "https://api.line.me/v2/bot/message/push",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {token}"},
        data=json.dumps({"to": user_id, "messages": [{"type": "text", "text": text}]},
                        ensure_ascii=False).encode("utf-8"),
        timeout=10,
    )


# ── 主程式 ────────────────────────────────────────
def main():
    print(f"\n{'='*55}")
    print(f" 每週關鍵字自動更新")
    print(f" 執行時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*55}\n")

    # 載入現有規則
    with open(KEYWORDS_FILE, encoding="utf-8") as f:
        kw_data = json.load(f)
    rules = kw_data["rules"]
    print(f"► 現有規則：{len(rules)} 條（版本 {kw_data.get('version','?')}）\n")

    # 抓近 7 天新聞
    print("► 抓取近 7 天新聞...")
    all_news = fetch_all_news(days=7)
    print(f"  取得 {len(all_news)} 則（去重後）\n")

    # 找未命中
    unmatched = find_unmatched(all_news, rules)
    print(f"► 未命中新聞：{len(unmatched)} 則")
    for e in unmatched[:5]:
        display = e.get("title_zh") or e["title_raw"]
        print(f"  [{e.get('source','')[:10]:10s}] {display[:60]}")
    if len(unmatched) > 5:
        print(f"  ...（還有 {len(unmatched)-5} 則）")
    print()

    # Claude 分類
    print(f"► 呼叫 Claude API 分類 {len(unmatched)} 則未命中新聞...")
    classified = classify_with_claude(unmatched)
    actionable = [c for c in classified if not c.get("skip") and abs(c.get("score",0)) >= 8]
    print(f"  分類完成，有效候選：{len(actionable)} 條\n")

    # 更新規則
    n_added, added_rules = update_keywords(classified)
    print(f"► 新增關鍵字：{n_added} 條")
    for r in added_rules:
        print(f"  [{r['score']:+3d}][{r['category']:8s}] {r['keyword']:20s} → {r['label']}")

    stats = {
        "total":      len(all_news),
        "unmatched":  len(unmatched),
        "classified": len(classified),
        "added":      n_added,
    }

    write_log(stats, added_rules)
    notify_line(stats, added_rules)

    print(f"\n✓ 完成。關鍵字總數：{len(rules) + n_added} 條")
    print(f"✓ Log 已寫入：{LOG_FILE}")


if __name__ == "__main__":
    main()
