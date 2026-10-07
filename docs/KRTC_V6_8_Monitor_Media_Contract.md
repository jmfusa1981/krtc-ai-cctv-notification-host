# KRTC V6.8 Monitor Media Contract

本文件定義KRTC AI CCTV PAO Notification Host V6.8的正式Monitor媒體責任邊界、串流選擇政策、資源穩定性基準與Media Track Freeze條件。除明確標示為compatibility fallback的路徑外，本文的「必須」、「不得」及「應」均視為V6.8整合契約。

## 1. System Responsibility

### Camera / NVR

Camera與NVR負責：

- 原始影像品質與錄影品質。
- Camera-side codec、resolution、FPS、bitrate及GOP profile。
- 提供主串流或原生substream供授權系統取用。

PAO/AIO不以修改Camera主串流設定作為系統必要條件。NVR錄影、其他CCTV系統與錄影平台可以同時使用相同Camera，PAO不得假設自己獨占Camera設定。

### PAO / AIO

PAO/AIO只負責即時監看與瀏覽器播放生命週期，不負責NVR錄影。其媒體政策依序優先考量：

1. 長時間穩定性。
2. 最小CPU與記憶體負擔。
3. 最少程序、thread及session churn。
4. 平順且不中斷的視覺監看。
5. 在前述條件成立後取得足夠影像品質。

PAO/AIO必須優先使用Camera Native H264，不得執行不必要的software transcode。

## 2. Primary Media Path

V6.8正式主路徑為：

```text
Camera Native H264
→ FFmpeg stream copy
→ MediaMTX
→ WebRTC
→ Browser
```

FFmpeg在此路徑只選取video stream並執行`-c:v copy`，不解碼、不縮放、不轉換FPS，也不重新編碼。

下列流程不得作為正常主路徑：

```text
Camera
→ decode
→ resize
→ FPS conversion
→ re-encode
→ MediaMTX
```

只有在Camera沒有瀏覽器相容的Native H264來源，且存在明確compatibility requirement時，才允許使用轉碼fallback。

## 3. Codec Policy

串流選擇優先順序為：

1. 適合目前監看需求的Native H264 stream。
2. Native H264 substream。
3. Native H264 main stream。
4. Hardware H265→H264 compatibility fallback。
5. Software H265→H264 compatibility fallback。

V6.8 Phase 1以Native H264 copy為primary path。H265 software transcode保留為compatibility fallback，不是一般layout切換或降低顯示尺寸的預設方法。

## 4. Display Canvas Policy

AIO正式顯示器為1920×1080 Landscape。1920×1080代表Monitor display canvas maximum，不代表每個Camera stream都必須輸出1920×1080。

Browser顯示必須：

- 保持source aspect ratio。
- 不stretch。
- 不為填滿tile而強制crop。
- 優先保留完整FOV。

來源比例與tile比例不同時允許letterbox或pillarbox黑邊。

## 5. Layout Policy

Monitor支援：

- 1-grid
- 4-grid
- 9-grid
- 16-grid

Layout切換不得因H264 copy stream而重啟bridge，不得建立不必要的transcode，也不應造成黑屏或loading flash。可見Camera的WebRTC session lifecycle應盡可能持續；隱藏slot仍依既有15秒grace與release政策處理。

## 6. Adaptive Profile Semantic Change

現有profile保留以下名稱與數值：

| Layout | Requested Monitor Profile | Requested Policy Target |
|---:|---|---:|
| 1 | `single` | 1920×1080 @ 30 fps |
| 4 | `grid4` | 1280×720 @ 15 fps |
| 9 | `grid9` | 640×360 @ 12 fps |
| 16 | `grid16` | 480×270 @ 10 fps |

這些值正式定義為Requested Monitor Profile / Stream Selection Policy，並非Mandatory Software Transcode Output。

對H264 copy：

- requested profile可以存在，用來描述layout需求及未來native stream selection意圖。
- 實際媒體仍維持source bitstream copy。
- Diagnostics必須回報`actual_bridge_mode=copy`及`actual_output=source-copy`。
- 不得為符合requested width、height或FPS而強制software transcode。

對compatibility transcode，只有實際套用scale/FPS filter時，diagnostics才可將對應尺寸與FPS標示為actual output。

## 7. Stream Selection Policy

Phase 2預定的native stream selection順序為：

- `single`：優先Camera native main H264。
- `grid4`：優先Camera native monitor/substream H264。
- `grid9`：優先較低負載的native H264 substream。
- `grid16`：優先最低但足以辨識的native H264 substream。

如果Camera沒有適合的substream，系統必須繼續使用現有H264 copy，不得自動切回software transcode；只有明確的codec compatibility requirement可以啟用轉碼fallback。

V6.8 Phase 1不包含substream auto-discovery、Camera API控制或自動修改Camera設定。

## 8. Camera Configuration Boundary

PAO不得自動修改Camera後台的：

- codec
- resolution
- FPS
- bitrate
- GOP

Camera主串流可能同時由NVR、其他CCTV系統或錄影平台使用。PAO Monitor的最佳化必須優先透過native stream selection、MediaMTX relay及WebRTC lifecycle完成。

目前Lab bridge來源路徑仍在`start_camera_bridge_lab.ps1`使用`/cam1/h264`。此路徑已通過目前四台Camera實機驗證，本次Media Freeze不改動。Phase 2若需要支援不同Camera stream endpoint，應將`SourcePath`加入受控profile/config欄位；不得同時引入自動探索、Camera API控制或Camera設定寫入。

## 9. Resource Stability Policy

AIO為長時間監看設備，資源政策優先順序為：

1. Long-running stability。
2. Low CPU。
3. Low memory。
4. Low process/thread churn。
5. Smooth visual monitoring。
6. Maximum image quality。

不得為追求超出顯示需求的畫質，增加不必要的decode、resize或encode負擔，進而提高長時間運行crash風險。

V6.8 Media Freeze實測baseline：

| Component | Baseline |
|---|---|
| Camera path | 4 × Native H264 copy |
| FFmpeg CPU | 約0–0.3% each |
| FFmpeg RAM | 約21–23 MB each |
| MediaMTX CPU | 約0.8% |
| MediaMTX RAM | 約67 MB |
| `transcoding_count` | `0` |

## 10. Fallback Policy

Browser播放fallback順序：

```text
WebRTC failure
→ existing MJPEG fallback

WebRTC recovery
→ automatic promotion back to WebRTC
```

H265-only Camera可使用compatibility bridge轉為瀏覽器相容H264。Fallback不得破壞：

- bridge supervisor與既有2/4/8秒crash backoff。
- 15秒stream grace。
- session security、Authentication與CSRF。
- Monitor navigation及layout lifecycle。

## 11. Media Freeze Acceptance

V6.8 Media Track Freeze接受條件與目前結果：

- Native H264四Camera播放：PASS。
- 1/4/9/16 layout：PASS。
- 4→9→16→4 seamless switching：PASS。
- `ready_path_count=4`：PASS。
- `webrtc_session_count=4`：PASS。
- `active_reader_count=4`：PASS。
- `active_visible_camera_count=4`：PASS。
- `transcoding_count=0`：PASS。
- 5-minute quick stability：PASS。
- FFmpeg與MediaMTX CPU/RAM baseline：PASS。

30–60分鐘soak test移入Full Integration Stress，不再阻塞OCC階段。完成本契約及自動回歸後，Media Track應進入Feature Freeze；除整合測試發現的缺陷或明確compatibility需求外，不再新增媒體runtime功能。
