# 安裝與 MCP 連線

## 安裝來源

從 [GitHub 專案](https://github.com/kdazero/MotionForge) 下載原始碼 ZIP，解壓縮後在含 `pyproject.toml` 的資料夾開啟終端機。以下安裝的是本地原始碼；目前不要直接執行 `pip install motionforge`，PyPI 上同名套件不一定屬於本專案。

需要 Python 3.12+ 與首次安裝時的網路連線。Windows 建議使用本次驗證的 Python 3.13：

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m motionforge --help
.\.venv\Scripts\python.exe examples/run_demo.py --workspace ./workspace
```

macOS／Linux 使用 `python3 -m venv .venv`，並將以上執行檔替換為 `.venv/bin/python`。Python 與 OpenCV／NumPy 必須支援本機平台；並非所有 CPU 架構均已驗證。

如取得 `.whl` 發布檔，可在虛擬環境內使用 `python -m pip install 完整路徑/motionforge-0.2.0-py3-none-any.whl`。教學腳本與範例在原始碼／使用者 ZIP 中，不在 wheel 中。

## 建立 MCP 設定

```powershell
.\.venv\Scripts\python.exe scripts/mcp_config.py --workspace ./workspace --output mcp-config.local.json
```

此指令會使用當前虛擬環境 Python 的絕對路徑與工作區絕對路徑，產生以下形狀的設定。輸出檔只供自己使用，已在 `.gitignore` 排除；現有檔案不會被覆蓋。

```json
{
  "mcpServers": {
    "motionforge": {
      "command": "/absolute/path/to/.venv/bin/python",
      "args": ["-m", "motionforge", "--workspace", "/absolute/path/to/workspace"],
      "env": {"PYTHONUTF8": "1"}
    }
  }
}
```

將 `motionforge` 項目合併到你的客戶端設定。不同客戶端設定畫面可能不同，使用其提供的本機 stdio MCP 功能；若不接受 `mcpServers` 包裝，分別填入 command、args 與 env。

重啟連線，讓 AI 呼叫 `get_capabilities`。應看到名稱 MotionForge、版本 0.2.0 與 `requires_spine: false`。再讀取 `motionforge://workflow`。客戶端必須能查看工具回傳圖片，才能進行視覺審查。

## HTTP（進階）

```text
python -m motionforge --workspace ./workspace --transport http --port 8776
```

端點為 `http://127.0.0.1:8776/mcp`，使用 Streamable HTTP。首頁與 `/studio` 回傳 404 是預期行為。此版本只綁本機，沒有帳號驗證或雲端代管；本機 stdio 是預設使用方式。不要直接改成對外公開服務。遠端連線需要另外設計認證與部署。

## 常見問題

| 情況 | 處理方式 |
| --- | --- |
| 找不到 Python | 安裝 Python 3.12+；Windows 可先用 `py --list` 確認版本 |
| `No module named motionforge` | 使用安裝時同一個虛擬環境的 Python，並在原始碼根目錄執行 `python -m pip install .` |
| AI 找不到圖片 | 附件 ID 不是檔案路徑；讓客戶端傳送實際 bytes，或放到 `workspace/inbox/` |
| 開啟網頁只有 404 | 本版本沒有操作網頁；使用 MCP 客戶端 |
| 草稿無法正式匯出 | 完整檢查所有影格並記錄；預覽用途可明確使用 `require_reviewed: false` |
| 渲染一直未完成 | 保持 MCP 程序存活；程序結束不會自動續跑，需重新開始渲染 |
| 重跑範例 | 範例每次使用新角色 ID，保留之前成果 |

移除工具可以刪除自己的虛擬環境；角色與成果保存在指定 workspace，請另行備份。
