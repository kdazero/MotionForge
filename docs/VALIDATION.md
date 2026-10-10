# 0.3.1 驗證與先前發布紀錄

## 0.3.1 本地驗證與展示確認（2026-10-10）

- Windows／Python 3.13：46 項測試通過，Ruff 檢查與格式檢查通過。包含實際 MCP stdio／HTTP、腕根對位與膚色取樣、手／臉遮擋、連續彎肘、斜向袖口輪廓，以及相連袖片的禁止區域檢查。
- 獨立安裝環境中的 wheel 與原始碼逐檔一致；`pip check` 通過。新網格重建結果一致，抽驗揮手第 0／18／30 格及思考第 60 格與已安裝套件的渲染像素一致。內附固定配方的骨架、素材與兩個時間軌驗證通過。
- 頁首展示重新輸出為 768 × 768、30 FPS。揮手含結束格 111 格，思考 145 格；所有動作時間軌與修正前一致。WebP／APNG／GIF 完整解碼、時長與 ZIP 完整性檢查通過。
- 查看揮手全部 111 格的袖口／腋下局部、思考全部 145 格的上半身、六張揮手全身縮圖與放大前後對照。播放器完整循環以 1 倍與 0.25 倍速自動檢查通過；自動播放檢查不代表人工觀看完整影片。
- 專案作者已在本次對話中確認這版展示，並授權放入 README 與發布 GitHub。展示核准與引擎逐格審查旗標分開：未完成全解析度逐格審查的工作區仍保留原有草稿紀錄，不因發布展示而改成全部通過。

舊工程的網格需要從原始 region 分件重新綁定，才會套用輪廓修正。自訂角色仍需正確分件與關節標記。跨平台狀態以 [GitHub Actions](https://github.com/kdazero/MotionForge/actions) 的實際結果為準。

## 0.3.0 本地配方驗證（2026-10-10）

- 29 項測試通過，包含真正的 MCP stdio／HTTP 新配方工具、原生四位小數末幀、手型時間表、舊修訂保留、過期修訂及不相容骨架／素材拒絕；修改後六項配方與連線測試再通過。Ruff 檢查與格式檢查通過。
- 配方的 wave／think 時間軌、骨架、槽與網格逐項等同本輪固定來源；31 張 PNG 按 SHA-256 核對。既有本機 `spinemotion.ai_server` 入口亦可建立相同配方。
- 八個轉掌／屈指及接點時間，從配方複製前後分別用相同 MotionForge 渲染器繪製，結果像素一致。這不代表 MotionForge 與 Spine 的光柵化像素一致。
- 在原始碼目錄之外，從新的驗證環境載入 0.3.0 wheel。確認 `motionforge` 位於該環境的 site-packages，且沒有安裝 `spinemotion`；Spine 路徑指定為不存在的執行檔。
- 執行 `examples/replay_gestures.py`，從空白工作區透過 MCP 建立角色並輸出 wave 111 格、think 145 格，使用同一角色修訂、固定取景、30 FPS 與 512 像素畫布。附參考來源、透明 WebP 及 PNG 草稿包。
- 256 張影格全部通過檔案雜湊核對，素材包通過 CRC；各抽看 12 張抬手、換型、停留與放下代表姿勢。抽查没有代替逐幀美術驗收，報告仍為未核准。

自動檢查不會核准美術。此輪渲染仍標示草稿，呼叫端須透過 `inspect_frames`／`record_frame_checks` 完成實際逐幀檢查；不能沿用原生 Spine 的舊通過狀態。新角色的手型與關節對位也不在精確復刻保證範圍內。GitHub Actions 新增同一 MCP 重播流程，尚未把本地結果當作跨平台 CI 已通過。

下列為 0.2.0 先前驗證紀錄，保留原範圍與日期。

本地驗證日期：2026-10-10（Asia/Taipei）。

## 已完成

- Windows／Python 3.13，全新虛擬環境安裝獨立 `motionforge` 套件成功。
- 25 項自動測試通過，包含真正的 MCP stdio／Streamable HTTP、角色與動作、網格、透明度、素材鎖定、快照與審查狀態。
- Ruff 程式檢查與格式檢查通過。
- 修正 Windows 原子更新進度檔期間偶發的讀取分享違規，測試短暫重試與持續拒絕存取的上限。
- source distribution 與 wheel 建置成功；wheel 不含舊 `spinemotion` 套件、Spine CLI 或桌面操作程式。
- 第二個乾淨環境只安裝 wheel，從原始碼目錄之外確認載入已安裝套件；環境中沒有 `spinemotion`。
- 透過 wheel 的 MCP 入口完成內附機器人範例：25 張完整 PNG 影格，透明 WebP／APNG、GIF、spritesheet 與草稿 ZIP。
- `pip check` 通過，命令列入口與 MCP 設定產生器可以執行。
- 保存 33 個 Windows 執行期依賴的版本與授權文字；不包含開發工具清單。

## 範例驗收範圍

查看過揮手的七個代表姿勢，確認簡單幾何機器人可見且完成抬手、揮動與放下。範例仍是草稿，沒有把抽樣觀看記為逐幀美術驗收；`visual_review_passed` 保持 false。

## 平台狀態

本地實測僅涵蓋 Windows／Python 3.13。GitHub Actions 設定涵蓋 Windows、Linux、macOS 的 Python 3.12／3.13；**設定檔存在不等於測試已通過**，請查看 [Actions 的實際結果](https://github.com/kdazero/MotionForge/actions)。

沒有宣稱已驗證任意 AI 客戶端帳號連線、影片動作捕捉、全自動補圖、任意人體動作、原生 Spine 工程或遊戲 runtime 相容性。

## 重現

依 README 安裝 `.[dev]`，執行測試、Ruff、`examples/run_demo.py` 與 `python -m build`。再於另一個虛擬環境安裝 `dist/` 中的 wheel 並跑一次範例。`scripts/package_release.py` 產生使用者 ZIP 與 SHA-256 清單。

依賴清單與授權資料是套件 metadata 的整理，不取代對新增程式／素材來源的確認。公開包不含使用者工作區、研究影片、私人設定或正式角色素材。
