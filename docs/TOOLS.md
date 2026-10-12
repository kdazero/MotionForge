# 工具與資料格式

實際參數與驗證規則以 MCP `list_tools` 回傳的 JSON Schema 為準。

| 工作 | 工具 |
| --- | --- |
| 能力／流程 | `get_capabilities`、`motionforge://workflow`、`animate_character` prompt |
| 動作配方 | `list_motion_recipes`、`get_motion_recipe`、`instantiate_motion_recipe`、`verify_motion_recipe`、`apply_motion_recipe`、`motionforge://recipes/female_gestures_v1` |
| 輸入素材 | `upload_asset`、`list_assets`、`inspect_image`、`extract_part` |
| 角色 | `list_characters`、`create_character`、`import_character`、`inspect_character`、`update_character` |
| 附件／綁定 | `bind_mesh`、`register_attachment`、`register_joint_attachment`、`bind_joint_strip`、`set_layer_constraints`、`map_roles`、`lock_identity` |
| 動作 | `add_motion_preset`、`set_animation`、`retime_animation`、`analyze_motion` |
| 渲染／檢查 | `start_render`、`render_status`、`inspect_frames`、`record_frame_checks` |
| 匯出 | `export_animations`、`read_artifact_bytes` |

## 座標

- 圖片與裁切：原始像素、左上原點、X 向右、Y 向下。
- 骨架／附件：父骨局部座標、Y 向上，旋轉單位為度。父骨必須先宣告。
- Layer x/y 是附件中心相對骨頭的位置，layers 由後往前繪製。
- 動作 translate/rotate 是相對 setup pose 的偏移，scale 是乘數，時間單位為秒。
- `retime_animation` 的 speed=1.5 表示速度變快 1.5 倍。

例如將既有 `head` 骨頭點頭，再回原位：

```json
{
  "project_id": "your-character",
  "name": "nod",
  "animation": {
    "bones": {
      "head": {
        "rotate": [
          {"time": 0, "angle": 0},
          {"time": 0.5, "angle": -8},
          {"time": 1, "angle": 0}
        ]
      }
    }
  }
}
```

這是 `set_animation` 的參數。名稱必須先透過 `inspect_character` 確認。

## 支援範圍

支援父子骨架、region、加權／非加權網格、線性及 rigid skinning、deform、附件切換、drawOrder、slot 色彩與透明度，以及 linear／stepped／貝茲曲線。JSON 使用 3.8 結構；版本欄位不是安裝 Spine 的要求，也不是遊戲端相容保證。

IK、transform/path constraints、linked mesh、clipping、特殊繼承與非 normal 混色模式會拒絕。events 可以保存在資料中，但點陣動畫不會執行遊戲事件。不輸出原生 `.spine` 工程。

## 資源與審查限制

- PNG/JPEG/WebP/JSON 上傳最大 16 MB；圖片最大 1,600 萬像素、單邊 8,192。
- 角色 ID 為 1–64 字元的英數字、`-` 或 `_`，不能是 Windows 保留檔名。
- `create_character` 支援 1–64 圖層、1–128 骨頭；`import_character`／`update_character` 的資料最多 512 骨頭。
- 圖層名稱與動作名稱使用與角色 ID 相同的規則；圖層名稱不分大小寫也不得重複（Windows／macOS 檔名不分大小寫）。匯入的圖片路徑同樣不得只差大小寫或使用 Windows 保留名稱。
- 手動放進 `inbox/` 的檔案只接受 PNG 與 JSON；JPEG／WebP 請透過 `upload_asset`，它會轉成 PNG。
- 最長 20 秒、1–60 FPS、128–2048 正方形畫布；每次最多 1.6 億影格像素。
- 每個伺服器程序同時一項渲染；程序結束不會續跑未完成工作。
- PNG 序列保留最後姿勢，動畫及 spritesheet 排除重複端點，避免循環多停一格。
- WebP/APNG 以毫秒計時；GIF 為 10ms 單位，僅二值透明度。
- 需先查看完整影格再提交檢查；局部裁切不代替完整影格。草稿不得宣稱已通過審查。
- 多動作合併匯出需來自同一角色與同一修訂。

`lock_identity` 可記錄素材、比例與攝影範圍限制。鎖定後，任何工具（包括 `update_character`、`register_attachment`、`bind_mesh`、`set_layer_constraints`）若會移除鎖、改動骨架／附件／圖層規則或原圖，都會在建立新修訂前被拒絕；確定要改，請先改完再明確呼叫一次 `lock_identity` 重新鎖定。它是動畫工作流程的檢查機制，不是不可繞過的權限或 DRM。
