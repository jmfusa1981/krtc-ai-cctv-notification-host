# MediaMTX 多攝影機整合 Phase 1

V6.8正式責任邊界、stream selection policy與Media Freeze條件，以[`KRTC_V6_8_Monitor_Media_Contract.md`](KRTC_V6_8_Monitor_Media_Contract.md)為準；本文件保留Phase 1實作與Lab操作細節。

## 架構與範圍

CAM-004 的廠商 SDP 含有非標準 `m=event`、`m=IVA-event` 與 `m=application` media section；MediaMTX v1.21.1 直接拉取時會以 `invalid SDP: sdp: invalid value 'event'` 拒絕來源。因此 Phase 1 改用 video-only bridge：

`Camera RTSP/TCP -> FFmpeg video-only stream copy -> MediaMTX publisher -> WebRTC -> Browser`

Django 僅負責登入、授權、攝影機清單及產生不含憑證的播放描述，不解碼或重新編碼 WebRTC 影像。FFmpeg 只選擇第一路 Video；H.264 執行 stream copy，H.265 則在獨立 bridge 程序中轉為瀏覽器相容的 H.264。兩種 profile 都不轉送 Audio、Data 或廠商 Event streams。

MediaMTX 不會轉碼。轉碼只發生在 Camera 與 MediaMTX 之間的獨立 FFmpeg bridge，不會放入 Django request 或 Monitor lifecycle。

## 檔案與設定

- 執行檔預期位置：`tools/runtime/mediamtx/mediamtx.exe`
- Lab 設定：`config/mediamtx.lab.yml`
- MediaMTX 啟動腳本：`tools/mediamtx/start_mediamtx_lab.ps1`
- Camera bridge 啟動腳本：`tools/mediamtx/start_camera_bridge_lab.ps1`
- Codec resolver：`tools/mediamtx/camera_bridge_codec.ps1`
- Lab codec profile：`tools/mediamtx/camera_bridge_profiles.lab.psd1`
- MediaMTX API：僅監聽 `127.0.0.1:9997`
- MediaMTX RTSP relay：僅監聽 `127.0.0.1:8554`
- WebRTC HTTP：`0.0.0.0:8889`
- WebRTC ICE UDP：`0.0.0.0:8189`

本專案未附帶或下載 `mediamtx.exe`。正式環境建議把已核准版本放在持久化 runtime 目錄，使用獨立 Windows Service 帳號、固定版本與受控設定檔；不要把攝影機密碼寫入 Git、HTML、JavaScript 或命令列記錄。

## Lab 啟動

第一個 PowerShell 啟動 MediaMTX；四個路徑只接受 publisher，不直接連線攝影機：

```powershell
.\tools\mediamtx\start_mediamtx_lab.ps1
```

第二個 PowerShell 將憑證放在程序環境，並啟動指定的 video-only bridge：

```powershell
$env:KRTC_LAB_CAMERA_USERNAME = "<camera-user>"
$env:KRTC_LAB_CAMERA_PASSWORD = "<camera-password>"
.\tools\mediamtx\start_camera_bridge_lab.ps1 -CameraCode CAM-004
```

目前四台Lab Camera均使用已完成實機驗證的Native H.264 stream copy。正式整合可由受控Camera metadata或ffprobe preflight取得codec，再透過`-SourceCodec H264|H265`覆寫；codec resolver只依codec決定profile，不以Camera code分支。H.265 software transcode僅保留為compatibility fallback。

第三個 PowerShell 啟動 Django：

```powershell
$env:KRTC_MEDIAMTX_ENABLED = "True"
$env:KRTC_MEDIAMTX_WEBRTC_BASE_URL = "http://192.168.6.25:8889"
$env:KRTC_MEDIAMTX_PHASE1_CAMERA_CODES = "CAM-001,CAM-002,CAM-003,CAM-004"
python manage.py runserver 0.0.0.0:8000
```

如瀏覽器不在 PAO 主機上，`KRTC_MEDIAMTX_WEBRTC_BASE_URL` 必須使用瀏覽器可達的 PAO 位址，不能使用 `127.0.0.1`。CAM-001 至 CAM-004 使用 `cam001` 至 `cam004` publisher 路徑；Camera來源只由各自獨立的FFmpeg bridge存取，MediaMTX不會主動拉取Vendor RTSP。

若 Django Dashboard 以 HTTPS 提供，MediaMTX 播放網址也必須是 HTTPS，否則瀏覽器會封鎖 mixed content。Phase 1 不變更既有 Caddy/HTTPS；正式部署應在核准的反向代理與憑證設計完成後才開啟此功能。

## 診斷順序

以下命令僅供人工 Lab 驗證，不應放進自動測試：

```powershell
# 1. 直接來源（手動代入，注意不要把含密碼輸出貼入紀錄）
ffprobe -rtsp_transport tcp -v error -show_streams "rtsp://<user>:<password>@192.168.6.92/cam1/h264"

# 2. MediaMTX與FFmpeg bridge程序
Get-Process mediamtx
Get-Process ffmpeg

# 3. 本機控制面與reader狀態
Invoke-RestMethod http://127.0.0.1:9997/v3/paths/list
Invoke-RestMethod http://127.0.0.1:9997/v3/rtsp/conns/list
Invoke-RestMethod http://127.0.0.1:9997/v3/webrtc/sessions/list

# 4. 不含攝影機憑證的本機relay
ffprobe -rtsp_transport tcp -v error -show_streams "rtsp://127.0.0.1:8554/cam004"

# 5. 瀏覽器播放頁
Start-Process "http://192.168.6.25:8889/cam004"
```

Phase 1 Lab 的 FFmpeg bridge 可在操作監看頁期間持續運行。多個瀏覽器 reader 共用同一個 MediaMTX publisher，不會各自開啟 Camera RTSP。切回 Django Dashboard 時，監看頁會移除 iframe，使瀏覽器端 WHEP/RTCPeerConnection 得以釋放；Camera bridge 只有在操作者按下 Ctrl+C 時停止。

正式環境的後續政策應由獨立服務管理每台 Camera 的 `Camera -> FFmpeg bridge -> MediaMTX publisher` 生命週期、重啟節流與健康檢查。本階段不依 reader 數量自動產生或終止 FFmpeg 程序。

若取得核准的 MediaMTX 執行檔，可在啟動前先驗證設定語法（實際參數須以該核准版本的 `mediamtx --help` 為準）：

```powershell
.\tools\runtime\mediamtx\mediamtx.exe --validate-conf .\config\mediamtx.lab.yml
```

CAM-004 先前 FFmpeg 測試曾出現起始輸出時間戳為負值，但 30 fps 連續拉流穩定。本階段不改寫時間戳；實機驗證時應保留 MediaMTX 的 timestamp correction 或 warning 訊息，作為後續判讀依據。

## 故障判讀

- `disabled`：Django 的 MediaMTX 功能開關未啟用。
- `not_enabled_for_camera`：攝影機不在 Phase 1 白名單。
- `inactive` / `offline`：攝影機狀態不允許建立播放頁。
- `invalid_configuration`：WebRTC base URL 缺漏、格式錯誤或含有使用者資訊。
- MediaMTX API 無 path：確認MediaMTX程序與設定檔。
- `cam004` path 沒有 publisher：確認FFmpeg bridge程序與其stderr；不得把未遮罩的來源網址貼入紀錄。
- path 存在但無影像：依序檢查bridge的RTSP/TCP拉流、codec resolver所選profile、輸出H.264瀏覽器相容性、TCP 8889及UDP 8189防火牆。

## Unified Monitor Phase 2

Phase 2 以功能開關漸進切換資料平面：

```text
KRTC_MONITOR_MEDIA_MODE=mediamtx
KRTC_MONITOR_MOSAIC_FALLBACK=True
KRTC_MEDIAMTX_PHASE1_CAMERA_CODES=CAM-001,CAM-002,CAM-003,CAM-004
```

`mediamtx` 模式下，1/4/9/16 都在瀏覽器建立獨立 WebRTC tile；`legacy` 模式下，1/4 使用既有 MJPEG，9/16 使用既有 server-side Mosaic。WebRTC HTTP 載入失敗會使用 2、4、8 秒退避重試，超過上限後只讓該 tile 切換到 MJPEG fallback，不影響其他 Camera。

一次啟動四個獨立 Lab bridge：

```powershell
.\tools\mediamtx\start_camera_bridges_lab.ps1 -CameraCode all
```

或只啟動指定 Camera：

```powershell
.\tools\mediamtx\start_camera_bridges_lab.ps1 -CameraCode CAM-001,CAM-004
```

每個 bridge 使用獨立子程序；manager 會顯示 CameraCode、MediaMTX path 與 PID。單一程序結束只回報該 Camera，不會終止其他 bridge；按 Ctrl+C 時會清理其建立的子程序樹。

只讀診斷：

```powershell
python manage.py diagnose_monitor_media
python manage.py diagnose_monitor_media --json
```

輸出包含 monitor media mode、fallback、MediaMTX可達性、四個path的ready/readers/bytes、WebRTC session數、FFmpeg程序數、每台bridge的source codec/mode/state及transcoding count，以及目前Django診斷程序的CPU時間與記憶體。`active_visible_camera_count` 由具有WebRTC reader的path數量推算，不會向Camera建立新連線。Bridge狀態快照只保存CameraCode、codec、mode、本機destination、PID與狀態，不保存來源URL或憑證。

## Codec profile與效能

H.264 profile 保持 `-map 0:v:0 -c:v copy -an -dn`；H.265 profile 使用 `-map 0:v:0 -c:v libx264 -preset veryfast -tune zerolatency -pix_fmt yuv420p -an -dn`。兩者都保留RTSP/TCP、`+genpts`及wallclock timestamp。

H.264 stream copy幾乎不消耗編碼CPU。H.265→H.264 compatibility fallback會完整解碼及重新編碼，啟用時應監看CPU、幀率、溫度與延遲。若Camera只有H.265，應優先評估Camera既有Native H.264子碼流；其次才考慮Intel QSV、NVIDIA NVENC或其他已核准hardware encoder，最後才使用software libx264。硬體路徑仍須維持H.264、低延遲、`yuv420p`相容輸出，並先確認驅動、FFmpeg build及多session容量。

## Media Runtime Stabilization

部分Vendor H.265來源回報`r_frame_rate=90000/1`及`avg_frame_rate=0/0`，若直接交給libx264會導致錯誤的macroblock rate及level判定。H.265 profile因此在encoder前使用`-vf fps=30`建立固定30 FPS filter timebase，並以`-fps_mode cfr`明確宣告CFR輸出；沒有再疊加`-r 30`，避免同一輸出執行兩次frame rate轉換。`+genpts`及wallclock timestamp仍用於修復Vendor RTSP輸入時間，fps filter則負責在編碼前drop/duplicate成穩定節奏。

Lab預設可透過`-TranscodeFps 30`調整，允許範圍為1至60。此參數只進入H.265 transcode profile，H.264 copy profile不加入filter、`-r`或`-fps_mode`，原始bitstream與timing行為不變。

多bridge manager預設對異常退出執行最多三次restart，間隔為2、4、8秒；各Camera獨立計數，一台失敗不阻塞其他Camera。可用`-MaxRestarts`及`-RestartBaseSeconds`調整，設為`-MaxRestarts 0`可停用restart。

Bridge狀態保存`ExitCode`、不含憑證的`LastError`、PID及程序建立時間。診斷同時比對PID與建立時間；PID不存在或已被其他程序重用時會標示`stale_process_identity`，不會誤報running。

Monitor在MediaMTX模式每5秒重新取得安全path readiness。fallback運行期間若path恢復，iframe會在背景重建；WebRTC player載入成功後才釋放MJPEG fallback並切回WebRTC。hidden slot仍沿用15秒grace period，頁面版型與Mosaic fallback不變。

## Adaptive Monitor Profile Phase 1

所有layout與輸出參數集中在`config/monitor_profiles.json`：

| Layout | Profile | Output | FPS |
|---|---|---:|---:|
| 1 | single | 1920x1080 | 30 |
| 4 | grid4 | 1280x720 | 15 |
| 9 | grid9 | 640x360 | 12 |
| 16 | grid16 | 480x270 | 10 |

Compatibility H.265 transcode filter為`scale=W:H:force_original_aspect_ratio=decrease,pad=W:H:(ow-iw)/2:(oh-ih)/2,fps=FPS`。因此4:3來源會完整縮入16:9 canvas，再以黑邊pillarbox補足，不會stretch或crop。H.264來源在Phase 1維持stream copy；grid profile是stream selection/display policy，不會為符合requested resolution而新增software encoder。

Monitor切換layout後會以CSRF保護的control-plane endpoint送出profile請求，1.5秒debounce會合併快速的1→4→9→16操作。Supervisor監看安全runtime state；profile真正改變時只對H.265 transcode bridge執行A/B make-before-break轉場，H.264 copy bridge不重啟。Intentional profile switch不增加2/4/8秒crash restart計數，並以`Reason=layout_change`獨立記錄。

`diagnose_monitor_media`會顯示整體`active_profile`，以及每台Camera的SourceCodec、actual BridgeMode、profile、requested width/height/fps、state、PID、ExitCode與LastError。狀態及API皆不包含Camera來源URL或憑證。

Phase 2預留的來源優先順序為：Camera native H.264 substream、H.264 main stream copy、hardware H.265→H.264、software libx264。本階段不探測或切換Camera native substream。

## Seamless Adaptive Profile Switching

H.265 Camera以base path作為A槽、`_b` path作為B槽，例如`cam001`與`cam001_b`。切換profile時Supervisor先在非作用中槽啟動新bridge，舊槽持續提供目前畫面；新path ready後，Monitor以隱藏的第二層WebRTC iframe預載。只有全部轉場Camera都完成iframe load，且MediaMTX path已出現WebRTC reader後，前端才一次交換current/next layer並送出CSRF保護的ACK。Supervisor收到相同transition ID與完整Camera集合後，才以`Reason=layout_change_cleanup`停止舊bridge。

轉場預設上限為10秒。新bridge、path readiness或瀏覽器預載任一步驟失敗時，Supervisor只停止next bridge，保留current bridge與既有畫面，並將狀態記為`failed`。新的layout request會以request ID取代進行中的轉場，舊next bridge會以`layout_change_cancelled`清理；這些清理都不進入crash restart counter。

一般MediaMTX狀態仍每5秒更新；profile request或轉場期間暫時以500毫秒輪詢安全control plane。診斷欄位包含`profile_transition_state/from/to/started_at/camera_count`，每台Camera另顯示`active_path`、`next_path`與`transition_state`，不含來源RTSP URL或Camera憑證。
