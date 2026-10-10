# 從角色到動畫

## 先試內附角色

執行 README 的 `examples/run_demo.py` 後，工作區會有 `robot-…` 角色及揮手草稿。讓 AI 使用 `list_characters` 找到 ID，再以 `inspect_character` 讀取骨架、附件、動作與修訂。

範例使用 MCP 真實連線完成匯入、角色映射、渲染、草稿匯出。不需要影片或 AI 帳號；腳本不會代替人類完成美術驗收。

## 使用自己的素材

最容易使用的是已拆好的透明 PNG：頭、身體、上臂、前臂、手與表情。圖片可以由本機 AI 讀取並呼叫 `upload_asset`，或手動放到指定工作區的 `inbox/`。所有工具路徑都相對於該工作區。

只有完整角色圖時，AI 先用 `inspect_image` 查看原始尺寸，再用 `extract_part` 指定輪廓與排除孔洞。工具只保留看得到的像素；遮住的手臂、頭髮或關節需要另行補圖。圖像生成由使用者或 AI 客戶端提供。

## 提出需求

使用 [需求表](../examples/motion-request.md)，附上 [動作參考](REFERENCES.md)。AI 先讀參考並安排起手、主要姿勢與收尾。需要翻掌卻只有手背素材時，先補手心附件，再用附件切換完成動作。

## AI 操作流程

1. 讀取 `get_capabilities` 和 `motionforge://workflow`。
2. 透過 `create_character` 建立骨架與圖層，或 `import_character` 匯入 3.8 結構 JSON 與未打包 PNG。
3. 透過 `inspect_character` 讀取真實名稱。需要網格時用 `bind_mesh`，新增表情用 `register_attachment`。
4. 用 `set_animation` 編寫動作。`add_motion_preset` 只是起點；不同角色需重新調整。
5. `analyze_motion` 分析整段範圍。需要多動作同畫布時，共用 bounds。
6. `start_render` 回傳 run_id；保持伺服器存活，使用 `render_status` 查詢。
7. `inspect_frames` 每次查看 1–12 格；檢查完整影格及腕袖、臉部等局部，依實際所見填寫 `record_frame_checks`。
8. `export_animations` 匯出。正式匯出預設要求所有影格通過；預覽階段明確設 `require_reviewed: false`。

檔案輸出包含角色 JSON、PNG 部件、動圖、spritesheet、來源參考、雜湊與檢查紀錄。分享前查看其中的參考連結與文字是否適合公開。

## 修改與驗收

明確指出時間與部位，例如「0.8 秒手腕翻得太快」。`retime_animation` 可以等比例調速，`set_animation` 修改軌道，`update_character` 修改角色結構；更新時需帶入最新修訂以避免覆蓋別人的修改。

角色修改會保留之前的修訂；已渲染工作保存來源快照。修改產物檔案會使舊檢查失效。數值檢查不代表符合參考、沒有接縫或動作自然；驗收紀錄只是已提交的觀察，也不等於使用者最終接受。

## 取得成果

本機客戶端可以開啟回傳的工作區路徑。客戶端若只支援工具傳輸，可透過 `read_artifact_bytes` 分塊取得 bytes；是否顯示可下載附件取決於該客戶端。APNG 的輸出檔名為 `animation.png`，透明 WebP 為 `animation.webp`。
