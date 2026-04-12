import sys, io, urllib.parse, feedparser, re
from datetime import datetime, timedelta

# 直接複製必要部分，不 import surge_analyzer（避免 stdout 衝突）
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

GOOGLE_RSS_EN = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en&num=15"
GOOGLE_RSS_ZH = "https://news.google.com/rss/search?q={q}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant&num=15"

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

cutoff = datetime.utcnow() - timedelta(hours=48)
all_entries = []

for cat, q in NEWS_QUERIES_EN.items():
    url = GOOGLE_RSS_EN.format(q=q)
    try:
        feed = feedparser.parse(url)
        for e in feed.get("entries", [])[:15]:
            ps = e.get("published_parsed")
            if ps:
                pub_dt = datetime(*ps[:6])
                if pub_dt < cutoff: continue
            else:
                pub_dt = datetime.utcnow()
            all_entries.append({
                "title_raw": e.get("title",""),
                "title": e.get("title","").lower(),
                "source": e.get("source",{}).get("title",""),
                "pub": pub_dt.strftime("%m/%d %H:%M"),
                "cat": cat, "lang": "en",
            })
    except: pass

for cat, q in NEWS_QUERIES_ZH.items():
    url = GOOGLE_RSS_ZH.format(q=urllib.parse.quote(q))
    try:
        feed = feedparser.parse(url)
        for e in feed.get("entries", [])[:15]:
            ps = e.get("published_parsed")
            if ps:
                pub_dt = datetime(*ps[:6])
                if pub_dt < cutoff: continue
            else:
                pub_dt = datetime.utcnow()
            raw = e.get("title","")
            clean = re.sub(r'\s*[|\-–]\s*(中央社|CNA|公視|PTS).*$', '', raw).strip()
            src = e.get("source",{}).get("title","")
            if not src:
                src = "中央社 CNA" if "cna.com.tw" in e.get("link","") else "公視新聞" if "pts.org.tw" in e.get("link","") else ""
            all_entries.append({
                "title_raw": raw, "title": clean.lower(), "title_zh": clean,
                "source": src, "pub": pub_dt.strftime("%m/%d %H:%M"),
                "cat": cat, "lang": "zh",
            })
    except: pass

# 去重
seen, unique = set(), []
for e in all_entries:
    k = e["title"][:50]
    if k not in seen:
        seen.add(k); unique.append(e)

print(f"總抓取（去重後）：{len(unique)} 則\n")

# 直接列出所有新聞，讓使用者看哪些有問題
cats = {}
for e in unique:
    cats.setdefault(e["cat"], []).append(e)

for cat, items in cats.items():
    print(f"═══ [{cat}] {len(items)} 則 ═══")
    for it in items:
        lang = it.get("lang","?")
        display = it.get("title_zh") or it["title_raw"]
        src = it.get("source","")[:12]
        print(f"  [{lang}][{src:12s}] {display[:72]}")
    print()
