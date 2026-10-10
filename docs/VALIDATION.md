# 0.2.0 發布驗證

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
