# MotionForge

| 原圖 | 揮手 | 思考 |
| :---: | :---: | :---: |
| ![角色原圖](examples/showcase/original.png) | ![MotionForge 0.3.1 揮手動畫](examples/showcase/wave.webp) | ![MotionForge 0.3.1 思考動畫](examples/showcase/think.webp) |

使用 **MotionForge 0.3.1** 製作；展示版本已由專案作者確認。[展示素材說明](examples/showcase/README.md) · [下載 0.3.1](https://github.com/kdazero/MotionForge/releases/tag/v0.3.1)

**讓 AI 使用角色分件、骨架與動作參考，製作可下載的 2D 動畫。**

MotionForge 是本機執行的 MCP 工具，提供動畫編寫、CPU 渲染、逐幀檢查與素材匯出。接上支援本機 MCP 與圖片檢視的 AI 客戶端後，可以用對話操作。**目前是開發者預覽版，沒有圖形操作介面，也沒有影片自動動作捕捉或內建補圖模型。**

不需要 Spine、GPU 或 MotionForge 帳號。AI 客戶端／模型由使用者自行準備，其費用與資料傳送方式依該服務而定。

**0.3.1 更新**：手掌依腕根與腕寬對齊、取樣校正膚色；連續關節網格保留袖口輪廓；分件檢查可攔截衣服缺失與其他部位的殘片；固定遮擋規則讓思考時的手指顯示在臉前。新角色的組裝方式見 [關節、膚色與遮擋](docs/JOINT_ASSEMBLY.md)。

**內附固定動作配方（自 0.3.0 起）**：包含配方角色的最終版揮手（V3.9，約 3.67 秒）與思考（V3.6，4.8 秒），以及 31 張共用分件、轉掌／屈指手型、網格與完整時間軌。AI 可透過 `instantiate_motion_recipe` 直接建立可復刻專案，不需要原作者電腦或 Spine。配方角色與頁首展示角色不同；手指改模、腕袖遮擋、肩腕跟隨與新角色對位方法見 [動作配方](docs/GESTURE_RECIPES.md)。

安裝後可執行 `python examples/replay_gestures.py --workspace ./workspace`，透過真正 MCP 產生兩段透明動圖與草稿包。AI 接入後先讀 `get_motion_recipe` 或 `motionforge://recipes/female_gestures_v1`；骨架／素材不相容時不會直接套用固定角度。原生資料可精確復刻，新角色仍需自己的手型與關節對位，渲染結果須另行逐幀檢查。

## 可以做什麼？

- 從圖片的明確輪廓切出透明部件，建立父子骨架與網格權重。
- 編寫待機、揮手等動作，調整速度、切換表情與手型。
- 鎖定原始素材、比例與攝影範圍，保存角色的修改版本。
- 輸出透明 WebP、APNG、PNG 序列、GIF 和分頁 spritesheet。
- 逐幀檢視與記錄；未完成驗收的輸出會保留草稿標記。

GIF 只有二值透明度，半透明邊缘請使用 WebP／APNG／PNG。動畫是否自然仍需要實際查看與調整。

## 先安裝，再跑範例

需要 **Python 3.12 以上**。下載此專案 ZIP 並解壓縮，或：

```text
git clone https://github.com/kdazero/MotionForge.git
cd MotionForge
```

Windows PowerShell：

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe examples/run_demo.py --workspace ./workspace
```

若安裝的是 Python 3.12，第一行改用 `py -3.12`。不必啟用虛擬環境，也不必修改 PowerShell 執行原則。

macOS／Linux：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python examples/run_demo.py --workspace ./workspace
```

範例會透過真正的 MCP 連線匯入內附的幾何機器人、渲染揮手並輸出草稿 ZIP；完成後會列出檔案位置。這一步不需要 AI 帳號，可先確認安裝正常。示範是簡單關節動畫，並非人體動作精度展示。

目前本機實測為 Windows／Python 3.13；其他系統的指令與 CI 設定已提供，驗證狀態見 [版本驗證](docs/VALIDATION.md)。

## 接到你的 AI 客戶端

先產生適合這台電腦的 MCP 設定：

```powershell
.\.venv\Scripts\python.exe scripts/mcp_config.py --workspace ./workspace
```

macOS／Linux 將執行檔換成 `.venv/bin/python`。將輸出的 `motionforge` 項目合併到客戶端的 MCP 設定，重新連線，再請 AI 讀取 `get_capabilities` 與 `motionforge://workflow`。**不要覆蓋原有的其他 MCP 設定。**

第一次可以直接說：

> 使用 MotionForge。先查看現有角色，找出範例機器人與 wave 動作，檢視預覽並向我說明結果。接著複製一個較慢的揮手動作，輸出草稿 WebP，供我比較。

本機 MCP 需要客戶端能啟動本機程序；雲端客戶端不能直接連你的 localhost。完整說明見 [安裝與連線](docs/INSTALL.md)。

## 使用自己的角色與動作參考

1. 將角色圖或透明 PNG 分件交給 AI；本機檔案放進設定的 `workspace/inbox/`。
2. 提供影片／GIF／關鍵姿勢圖，指定時間段與「要模仿的部位」。
3. AI 先確認能讀取參考，整理起手、主要動作與收尾，再確認是否缺少手型或被遮住的部件。
4. AI 透過工具建立角色、編寫動畫並提供草稿。
5. 提出修改，完成逐幀檢查後匯出。

**影片由 AI 客戶端查看與理解；MotionForge 不接收 MP4 上傳，也不會從影片自動抽取動作。** 外部影片看不到時，改提供檔案或帶時間的截圖。只有一張角色圖時，遮擋處需要使用者或客戶端的圖像工具補繪。

- [使用教學](docs/USAGE.md)
- [如何提供動作參考](docs/REFERENCES.md)
- [可複製的需求表](examples/motion-request.md)
- [工具、座標與資料限制](docs/TOOLS.md)

## 開發、授權與回報

```text
python -m pip install -e ".[dev]"
python -m pytest -q
python -m ruff check src tests scripts examples
python -m build
python scripts/package_release.py
```

程式碼、文件與內附程式繪製的機器人範例採用 [MIT](LICENSE)。第三方依賴保留各自授權，見 [第三方聲明](THIRD_PARTY_NOTICES.md)。使用者自行提供的角色與參考素材不會因此變成 MIT 授權。

本專案不附帶 Spine Editor 或官方 Spine Runtime；僅支援部分 3.8 結構資料，不代表完整 runtime 相容或官方認證。

問題請附作業系統、Python／MotionForge 版本、重現步驟與已移除私人資料的錯誤訊息，提交至 [Issues](https://github.com/kdazero/MotionForge/issues)。詳見 [貢獻指南](CONTRIBUTING.md)。
