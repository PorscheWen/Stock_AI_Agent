"""直接測試關鍵字規則命中情況"""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(__file__))

# 手動載入規則（不觸發 surge_analyzer 的 stdout 重定向）
exec(open(__file__.replace("check_rules.py","surge_analyzer.py"), encoding="utf-8").read().split("def fetch_news_sentiment")[0].replace(
    "import sys\nimport io\n# Force UTF-8 output on Windows\nsys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')\n", ""
))

test_titles = [
    "AI超旺 台灣3月出口飆801.8億美元創高",
    "中共25機艦船台海周邊活動國軍嚴密監控應處",
    "降低依賴台積電 日本追加6315億日圓補貼Rapidus",
    "美關稅恐致新藥引進延遲專家籲減老藥促成長",
    "鄭習會後中共祭統戰工具推動上海福建赴台自由行等10項涉台措施",
    "中國10項涉台措施政院批交流工具化經貿武器化統戰作法",
    "TSMC Reports Record Quarterly Revenue as AI Chip Demand Persists",
    "Bond Traders Cling to Bets on a Fed Rate Cut This Year After CPI",
    "3月出口達801.8億美元 年增率61.8%創歷年單月新高",
    "We might need to raise rates: Fed official put a rate hike back on the table",
    "Could Trump Ignite a Stock Market Rally by Suspending Tariffs?",
    "Taiwan Strait: China should abandon threats against Taiwan, US diplomat says",
    "TSMC在台美擴先進封裝 從CoWoS到CoPoS鋪天蓋地",
    "外資買超台積電 連七日淨買入",
    "台股大漲500點 三大法人齊買",
]

print(f"{'分數':>5}  {'類別':12}  {'命中規則':18}  標題")
print("-" * 90)
for title in test_titles:
    t = title.lower()
    best_score, best_label, best_cat = 0, "─ 未命中 ─", ""
    for keyword, score, label, cat in NEWS_SENTIMENT_RULES:
        if keyword.lower() in t and abs(score) > abs(best_score):
            best_score, best_label, best_cat = score, label, cat
    mark = "[+]" if best_score > 0 else "[-]" if best_score < 0 else "[ ]"
    print(f"{mark} {best_score:+4d}  {best_cat:12}  {best_label:18}  {title[:52]}")
