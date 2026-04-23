#!/usr/bin/env python3
"""
🧪 快速測試運行器
快速執行所有測試並顯示結果
"""
import sys
import subprocess
import time

def run_command(cmd, description):
    """執行命令並顯示結果"""
    print(f"\n{'='*60}")
    print(f"🔍 {description}")
    print(f"{'='*60}")
    
    start = time.time()
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    elapsed = time.time() - start
    
    print(result.stdout)
    if result.stderr:
        print(result.stderr)
    
    status = "✅ 通過" if result.returncode == 0 else "❌ 失敗"
    print(f"\n{status} (耗時: {elapsed:.2f}秒)")
    
    return result.returncode == 0

def main():
    print("""
╔══════════════════════════════════════════════════════════════╗
║           🧪 Stock AI Agent 完整測試套件                     ║
╚══════════════════════════════════════════════════════════════╝
    """)
    
    results = []
    
    # 1. 語法檢查
    results.append(run_command(
        "python -m py_compile main.py agents/*.py config/*.py",
        "1️⃣ Python 語法檢查"
    ))
    
    # 2. 模組導入測試
    results.append(run_command(
        """python -c "
from agents.orchestrator import OrchestratorAgent
from agents.scanner_agent import ScannerAgent
from config.settings import ANTHROPIC_API_KEY
print('✅ 所有模組導入成功')
" """,
        "2️⃣ 模組導入測試"
    ))
    
    # 3. 單元測試
    results.append(run_command(
        "python -m unittest tests.test_agents -v",
        "3️⃣ Agent 單元測試"
    ))
    
    # 4. 整合測試
    results.append(run_command(
        "python -m unittest tests.test_integration -v",
        "4️⃣ 整合測試"
    ))
    
    # 5. 命令行測試
    results.append(run_command(
        "python main.py --help > /dev/null",
        "5️⃣ 命令行介面測試"
    ))
    
    # 總結
    print(f"\n{'='*60}")
    print("📊 測試總結")
    print(f"{'='*60}")
    
    passed = sum(results)
    total = len(results)
    
    print(f"通過: {passed}/{total}")
    print(f"失敗: {total - passed}/{total}")
    
    if all(results):
        print("\n🎉 所有測試通過！系統狀態: 🟢 健康")
        return 0
    else:
        print("\n⚠️ 部分測試失敗，請檢查錯誤訊息")
        return 1

if __name__ == "__main__":
    sys.exit(main())
