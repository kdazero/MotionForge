# 工具與資料格式

實際參數與驗證規則以 MCP `list_tools` 回傳的 JSON Schema 為準。

| 工作 | 工具 |
| --- | --- |
| 能力／流程 | `get_capabilities`、`motionforge://workflow`、`animate_character` prompt |
| 輸入素材 | `upload_asset`、`list_assets`、`inspect_image`、`extract_part` |
| 角色 | `list_characters`、`create_character`、`import_character`、`inspect_character`、`update_character` |
| 附件／綁定 | `bind_mesh`、`register_attachment`、`map_roles`、`lock_identity` |
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
- 角色建立支援 1–64 圖層、1–128 骨頭。
- 最长 20 秒、1–60 FPS、128–2048 正方形畫布；每次最多 1.6 億影格像素。
- 每個伺服器程序同時一項渲染；程序結束不會續跑未完成工作。
- PNG 序列保留最後姿勢，動畫及 spritesheet 排除重複端點，避免循環多停一格。
- WebP/APNG 以毫秒計時；GIF 為 10ms 單位，僅二值透明度。
- 需先查看完整影格再提交檢查；局部裁切不代替完整影格。草稿不得宣称已通過審查。
- 多動作合併匯出需來自同一角色與同一修訂。

`lock_identity` 可記錄素材、比例與攝影範圍限制；它是動畫工作流程的檢查機制，不是不可繞過的權限或 DRM。
