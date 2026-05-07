#!/usr/bin/env python3
"""
🌐 Stock AI Agent 簡易 WebUI

功能：
- 顯示最新妖股分析報告摘要
- 顯示最新回測摘要
- 一鍵執行分析（main.py）
- 一鍵執行回測（backtest.py）
"""
import html
import json
import os
import subprocess
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from config.settings import REPORT_DIR


HOST = "127.0.0.1"
PORT = 8080


def _list_files(pattern: str) -> list[Path]:
    report_dir = Path(REPORT_DIR)
    if not report_dir.exists():
        return []
    return sorted(report_dir.glob(pattern), reverse=True)


def _read_json(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _latest_analysis_report() -> dict:
    files = _list_files("yaogu_*.json")
    return _read_json(files[0]) if files else {}


def _latest_backtest_report() -> dict:
    files = _list_files("backtest_*.json")
    return _read_json(files[0]) if files else {}


def _render_stocks_table(stocks: list[dict]) -> str:
    if not stocks:
        return "<p>目前無推薦股票。</p>"
    rows = []
    for s in stocks:
        score = s.get("scores", {})
        rows.append(
            "<tr>"
            f"<td>{html.escape(s.get('symbol', ''))}</td>"
            f"<td>{html.escape(s.get('name', ''))}</td>"
            f"<td>{float(score.get('recommendation', 0)):.1f}</td>"
            f"<td>{float(score.get('confidence', 0)):.1f}%</td>"
            f"<td>{float(s.get('volume_ratio', 0)):.1f}x</td>"
            "</tr>"
        )
    return (
        "<table border='1' cellpadding='6' cellspacing='0'>"
        "<tr><th>代號</th><th>名稱</th><th>推薦分數</th><th>信心</th><th>量比</th></tr>"
        + "".join(rows)
        + "</table>"
    )


def _render_page(message: str = "", command_output: str = "") -> str:
    analysis = _latest_analysis_report()
    backtest = _latest_backtest_report()
    stocks = analysis.get("stocks", [])
    op = analysis.get("operation_advice", {})

    analysis_title = (
        f"{analysis.get('analysis_date', '-')}"
        f"｜掃描 {analysis.get('total_scanned', 0)} 檔"
        f"｜推薦 {analysis.get('total_candidates', 0)} 檔"
    ) if analysis else "尚無分析報告"

    backtest_title = (
        f"有效交易 {backtest.get('total_trades', 0)} 筆"
        f"｜勝率 {backtest.get('win_rate_pct', 0)}%"
        f"｜平均報酬 {backtest.get('avg_final_return_pct', 0)}%"
    ) if backtest else "尚無回測報告"

    safe_message = html.escape(message)
    safe_output = html.escape(command_output)
    ai_summary = html.escape(analysis.get("ai_summary", ""))
    action = html.escape(op.get("action", ""))
    position = html.escape(op.get("position_guidance", ""))
    risk_alert = html.escape(op.get("risk_alert", ""))

    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <title>Stock AI Agent WebUI</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 20px; line-height: 1.5; }}
    .card {{ border: 1px solid #ddd; border-radius: 8px; padding: 16px; margin-bottom: 16px; }}
    .actions form {{ display: inline-block; margin-right: 8px; }}
    button {{ padding: 8px 14px; cursor: pointer; }}
    pre {{ background: #f6f8fa; padding: 12px; border-radius: 6px; overflow-x: auto; }}
  </style>
</head>
<body>
  <h1>📈 Stock AI Agent - 簡易 WebUI</h1>
  <p>時間：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>

  <div class="card actions">
    <h2>操作</h2>
    <form method="post" action="/run-analysis">
      <input type="hidden" name="no_line" value="1">
      <button type="submit">執行今日分析（不推播）</button>
    </form>
    <form method="post" action="/run-backtest">
      <input type="hidden" name="horizon" value="3">
      <button type="submit">執行回測（3天）</button>
    </form>
    <p>{safe_message}</p>
  </div>

  <div class="card">
    <h2>最新分析摘要</h2>
    <p>{html.escape(analysis_title)}</p>
    <p><b>AI 總結：</b>{ai_summary or "—"}</p>
    <p><b>操作建議：</b>{action or "—"}</p>
    <p><b>倉位：</b>{position or "—"}</p>
    <p><b>風險提醒：</b>{risk_alert or "—"}</p>
    {_render_stocks_table(stocks)}
  </div>

  <div class="card">
    <h2>最新回測摘要</h2>
    <p>{html.escape(backtest_title)}</p>
  </div>

  <div class="card">
    <h2>最近執行輸出</h2>
    <pre>{safe_output}</pre>
  </div>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    last_message = ""
    last_output = ""

    def _send_html(self, content: str, status: int = 200) -> None:
        body = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path != "/":
            self._send_html("<h1>404 Not Found</h1>", status=404)
            return
        self._send_html(_render_page(self.last_message, self.last_output))

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        data = self.rfile.read(length).decode("utf-8")
        form = parse_qs(data)

        if self.path == "/run-analysis":
            cmd = [sys.executable, "main.py", "--json"]
            if form.get("no_line", [""])[0] == "1":
                cmd.append("--no-line")
            self._run_command(cmd, "分析完成")
        elif self.path == "/run-backtest":
            horizon = form.get("horizon", ["3"])[0]
            cmd = [sys.executable, "backtest.py", "--horizon", horizon]
            self._run_command(cmd, "回測完成")
        else:
            self._send_html("<h1>404 Not Found</h1>", status=404)
            return

        self._send_html(_render_page(self.last_message, self.last_output))

    def _run_command(self, cmd: list[str], done_message: str) -> None:
        try:
            proc = subprocess.run(
                cmd,
                cwd=os.getcwd(),
                capture_output=True,
                text=True,
                timeout=300,
            )
            output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
            self.last_output = output[-8000:] if output else "(無輸出)"
            if proc.returncode == 0:
                self.last_message = f"✅ {done_message}"
            else:
                self.last_message = f"❌ 執行失敗（exit={proc.returncode}）"
        except Exception as e:
            self.last_message = "❌ 執行失敗（例外）"
            self.last_output = str(e)


def main() -> None:
    server = HTTPServer((HOST, PORT), Handler)
    print(f"✅ WebUI 啟動：http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
