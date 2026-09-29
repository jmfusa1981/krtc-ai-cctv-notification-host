# KRTC PAO V6 Monitor Mosaic Architecture Audit

> 日期：2026-09-04  
> Worktree：`C:\KRTC_DEV\PAO_V6_MONITOR_MOSAIC`  
> Branch：`poc/monitor-wall-mosaic`  
> Baseline：`software-field-baseline-20260904` / `527119b`  
> 範圍：純 Source Audit；未修改 production source

## 1. Current Monitor Wall Execution Path

目前每一台 visible Camera 都有獨立的 browser media lifecycle：

```text
templates/dashboard/monitor.html
  one <img data-camera-stream> per Camera
        │ src=/api/cameras/<id>/stream/?profile=gridN
        ▼
apps/cameras/urls.py
        ▼
camera_mjpeg_stream()
        ▼
StreamingHttpResponse(generate_mjpeg_frames())
        ▼
acquire_camera_stream(camera.id, authenticated_rtsp_url)
        ▼
process-local SharedCameraStream
        ▼
one cv2.VideoCapture per active Camera per Django process
        ▼
RTSP Camera
```

`generate_mjpeg_frames()` 對每一個 browser subscriber執行自己的 frame wait、resize、JPEG encode與multipart yield。`SharedCameraStream` 只共享 RTSP decode/latest frame，不共享 resize或JPEG encode。

## 2. Browser Connection Problem

`static/js/monitor.js::syncVisibleCameraStreams()` 為每個 visible card呼叫 `activateCameraStream()`，後者對每個 `<img>` 設定獨立 `/stream/` URL。因此：

- grid1：1條長連線。
- grid4：4條長連線。
- grid9：9條長連線。
- grid16：16條長連線。

Edge/Chromium Lab在HTTP/1.1同一 origin只建立6條 media connections；其餘 `<img>` 排隊，造成第7至9格永久顯示 `Still loading stream...`。觀察到 `HTTP_Clients=6`、`RTSP_Total=6` 與 source行為一致：未取得 browser socket的 request根本沒有進入 Django，因此也沒有 acquire後端 RTSP。

Mosaic若將9/16格改為一個 `<img>`，可把該頁的media HTTP connection降為約1，普通 `/check/`、event polling與navigation request不再與9或16條MJPEG競爭browser per-origin sockets。

## 3. Waitress Worker Problem

`StreamingHttpResponse` 在同步WSGI/Waitress下會由一個worker thread持續迭代generator，直到client disconnect或generator結束。現況每台Camera各占一個worker：

| Grid | Long-lived media requests | Nominal occupied Waitress workers |
|---|---:|---:|
| 1 | 1 | 1 |
| 4 | 4 | 4 |
| 9 | 9 | 9 |
| 16 | 16 | 16 |

這解釋 threads=4時4路stream正常但普通HTTP 12/12 timeout，而threads=8時4路stream之外仍有4個worker headroom，普通HTTP回到13–26 ms。

Mosaic的9/16格各只保留一條 `StreamingHttpResponse`，理論上只長佔1個Waitress worker。若threads=8，名義上剩7個worker可處理control/API，但不能直接宣稱正式容量足夠：baseline health endpoint本身會同步開RTSP且可能占用worker，event burst、慢DB及多browser也會改變容量，必須以Lab壓測判定。

## 4. RTSP Ownership

`apps/cameras/stream_pool.py` 的 `_streams` 以camera id為key，透過 `_streams_lock` 建立process-local `SharedCameraStream`。每個stream有一個capture thread與latest full-resolution frame；`subscribe()`/`unsubscribe()`管理client count。

可重用點：

- Mosaic不得呼叫 `cv2.VideoCapture()`。
- Mosaic compositor應對每個Camera只取得一次 `SharedCameraStream` subscription，所有browser clients再共享同一個compositor/JPEG。
- Mosaic停止時必須逐一unsubscribe，讓既有Camera retention開始計時。

Baseline限制：

- `wait_for_frame()`會copy frame，但沒有non-blocking latest-frame snapshot、frame timestamp、stale age或capture health。
- capture open/read沒有bounded timeout與reconnect backoff。
- registry只在單一Django process內共享；多process仍可能重複RTSP。
- `camera_stream_check()`不讀shared owner，而是每次另開 `cv2.VideoCapture()`，會造成health probe duplication。

因此PoC可以在baseline上設計，但production實作不應複製另一套RTSP owner，且應先整合Camera R3能力。

## 5. Current Grid Implementation

`monitor.html` server-render所有active Camera cards。`monitor.js::prepareMonitorSlots()`補足至16個slot；slot的 `data-slot-index`、CSS `order`與DOM card位置構成client-side layout。

`setGridMode()`設定1/4/9/16與group index；`renderCurrentCameraGroup()`只顯示目前group範圍；`getMonitorStreamProfile()`映射為 `single/grid4/grid9/grid16`。Backend profiles為：

| Profile | Per-camera FPS | Per-camera max width | JPEG quality |
|---|---:|---:|---:|
| single | 15 | 1280 | 80 |
| grid4 | 12 | 960 | 78 |
| grid9 | 8 | 640 | 65 |
| grid16 | 6 | 480 | 60 |

這些是每路stream的encode profile，不是mosaic canvas尺寸。直接把grid9的640或grid16的480當作整張mosaic寬度會導致嚴重畫質不足。

## 6. Current Frontend Lifecycle

1. Django render所有active Camera cards與per-camera stream/check URLs。
2. `prepareMonitorSlots()`補空slot，initial grid固定4。
3. `syncVisibleCameraStreams()`每200 ms啟動一張visible `<img>`。
4. group/grid切換時hidden Camera先保留browser connection 15秒；若仍hidden才移除`src`。
5. browser `<img>` load/error事件驅動card/overlay狀態。
6. 15秒尚未load時顯示slow-loading warning。
7. health每30秒對全部visible cards同時fetch；baseline沒有client timeout/concurrency cap。
8. `pagehide`、`beforeunload`或Dashboard navigation呼叫cleanup並移除所有stream `src`。
9. browser斷線後generator `finally` unsubscribe；底層SharedCameraStream再保留15秒。

注意：group切換存在frontend 15秒延遲釋放，再加backend 15秒retention；但整頁離開會立即移除`src`，Lab觀察約17秒後RTSP 4→0與此相符。

## 7. Existing UI Functions and Mosaic Impact

| 功能 | 現況 | M1第一階段 | M2正式候選 | 主要風險 |
|---|---|---|---|---|
| 1-grid | per-camera MJPEG | 保留既有path | 保留 | 不必為PoC擴大範圍 |
| 4-grid | 4條per-camera MJPEG | 保留既有path | 可後續評估 | 目前threads=8已有Lab可用證據 |
| 9-grid | 9張card/9條MJPEG | 改單一mosaic image | mosaic+9 DOM overlays | 必須切換transport而非只改CSS |
| 16-grid | 16張card/16條MJPEG | 改單一mosaic image | mosaic+16 DOM overlays | CPU、memory bandwidth需量測 |
| Camera selection | slot click | 可只保留group級選擇或暫停 | overlay click映射slot | M1沒有獨立tile DOM |
| Camera name | card footer | 可畫入JPEG或暫時簡化 | overlay DOM保留 | JPEG文字無法無障礙/獨立更新 |
| Status badge | per-card DOM | 可暫時用placeholder文字 | 每tile overlay badge | 不應讓health endpoint阻塞compositor |
| Loading overlay | per-card DOM | 一個mosaic-level overlay；tile狀態由placeholder | 每tile overlay | M1無法遮單一tile DOM |
| Online/offline | health+image events | placeholder顯示CONNECTING/NO SIGNAL | overlay結合shared snapshot | baseline health會複製RTSP |
| 拖拉/排列 | client交換slot index | PoC可暫停或固定server order | POST layout後更新token | backend必須取得validated slot mapping |
| Carousel | client group timer | 可保留，切換server-derived group | 可完整保留 | 切換時避免產生orphan compositor |
| Group navigation | client group index | 可保留，重建單一mosaic URL | 可完整保留 | canonical layout key必須含ordered IDs |
| 頁面離開release | 清除所有img src | 清除mosaic src | 相同 | server需可靠處理GeneratorExit/disconnect |
| 15秒retention | per-camera shared owner | 必須保留 | 必須保留 | Mosaic retention不可再疊15秒造成30秒以上 |
| Single-camera viewing | grid1/profile single | 保留既有per-camera stream | overlay double-click進grid1 | return時需重建mosaic subscriber |
| Health polling | visible cards每30秒 | PoC可顯示compositor內部狀態 | R3 shared health更新overlay | baseline會另開VideoCapture |
| Event highlight | card/slot/tree DOM class | Camera tree可保留；canvas內highlight可暫緩 | overlay依camera id加class | M1 canvas無tile DOM |

分類結論：M1適合驗證transport、worker與compositor，不適合作為功能完整的正式UI；M2才適合保留selection、drag/drop、badge、tooltip、double-click與event highlight。

## 8. Existing Performance Profiles and Display Geometry

1920×1080 viewport下：toolbar最小64 px，`.monitor-content`左右padding共28 px、sidebar 260 px、gap 10 px，sidebar開啟時grid可用寬約1622 px；`.monitor-grid`高度固定 `1080-92=988` px。

扣除grid gap後，現有card外框約為：

- 3×3：每格約534×323 px；再扣46 px footer，影像區約534×277 px。
- 4×4：每格約398×240 px；再扣46 px footer，影像區約398×194 px。

sidebar收合後寬度增加，畫面比例也會變。Camera source為1280×720（16:9），所以mosaic應維持16:9 canvas並由CSS `object-fit: contain`或明確letterbox處理，不應為填滿不同比例容器而任意拉伸。

候選canvas比較：

| Canvas | 3×3 nominal tile | 4×4 tile | 每frame pixels | 評估 |
|---|---:|---:|---:|---|
| 1920×1080 | 640×360 | 480×270 | 2.07 MP | 最佳細節；encode、copy與頻寬最高 |
| 1600×900 | 533/534×300 | 400×225 | 1.44 MP | 與實際open-sidebar顯示接近，建議PoC主profile |
| 1280×720 | 426/427×240 | 320×180 | 0.92 MP | CPU/頻寬最低；16格仍可辨識但細節較少 |

建議PoC先固定1600×900、grid9 8 fps、grid16 5 fps；再以1280×720作降載A/B。1920×1080保留品質上限測試，不作初始預設。

## 9. SharedCameraStream Reuse Points

Mosaic可重用的最小介面是 `acquire_camera_stream()`、`wait_for_frame()`、`unsubscribe()`。但不能在一個tick依序用2秒timeout等待9/16台，否則一台dead Camera就可拖住整張mosaic。

PoC可對各stream使用timeout=0的non-blocking version check，並由compositor保存每tile最後成功frame與取得時間。Production較佳介面是Camera R3提供的thread-safe latest-frame/health snapshot：短鎖內copy引用或frame、立即返回、附frame version與monotonic age，不依賴HTTP health endpoint。

## 10. Integration Risks

1. 16條RTSP decode仍存在；Mosaic只消除16次browser JPEG encode/transport，不消除Camera decode成本。
2. 若每tick同時copy 16張1280×720 BGR，瞬間額外資料約42 MiB；應逐tile snapshot→resize→paste，避免保留16份full-frame copies。
3. OpenCV operation在Python thread中通常進入native code，但CPU、memory bandwidth與GIL周邊排程仍需實測。
4. 多browser若各自建立compositor，JPEG encode成本會倍增；必須有canonical shared mosaic registry。
5. layout churn可造成大量短命thread/registry key，需限流、key canonicalization與idle cleanup。
6. WSGI client disconnect偵測並非瞬間；generator `finally`與orphan watchdog都需測試。
7. baseline health仍可額外開RTSP，可能令 `RTSP_Total`高於camera count。
8. process-local registries在多Waitress process/多service instance下不共享。
9. mosaic單一JPEG損壞或endpoint中斷會影響整個grid，故需mosaic-level reconnect UI。
10. M1將文字畫入JPEG會降低可操作性與無障礙；正式整合需M2 overlays。

## 11. Camera R3 Dependency

Production integration應先整合 `fix/camera-r3-shared-health` 已review的能力：

- health與Monitor atomic shared ownership；
- shared health/frame age snapshot；
- bounded RTSP open/read timeout；
- bounded reconnect backoff；
-正確subscriber/15-second retention lifecycle；
- credential-free diagnostics。

本branch只從baseline做設計，不複製Camera R3 source。PoC實作若尚未rebase/merge R3，只能視為isolated feasibility code，不能直接判定Field-ready。

## 12. Security Considerations

- Mosaic endpoint必須 `login_required`，並沿用現有Camera/Monitor授權政策。
- client只能提供受控layout/token；不得提供RTSP URL、credential或filesystem path。
- layout只允許1/4/9/16，最多16個unique、active、存在且有權查看的Camera。
- FPS、canvas、JPEG quality均由server profile固定，禁止client要求100 fps、8K或quality=100。
- canonical layout keys與per-user/per-session建立速率限制可降低layout-explosion DoS。
- response與log不得輸出authenticated RTSP URL或credential。
- logout後browser必須取消stream；server需驗證disconnect cleanup。長連線建立後不會自動逐frame重新驗證session，這是必須明列的測試與風險。

## 13. Mosaic Suitability Conclusion

Mosaic與現有Django架構相容：它可以位於新的 `apps/cameras/mosaic.py`，重用SharedCameraStream，views只做驗證與StreamingHttpResponse adapter；9/16 frontend只需切換到單一mosaic `<img>`。不需要migration、DB schema或新dependency，rollback可限定在camera mosaic module/route與Monitor Wall template/JS/CSS。

Mosaic能直接避開HTTP/1.1同origin六條長連線上限，並把9/16格Waitress長佔worker由9/16降為1。主要design risk是baseline缺少R3級shared health/timeout與M1功能退化；兩者都有清楚的PoC/production邊界。

Audit結論：架構適合進入受限的Mosaic PoC，但PoC結果不得取代Camera R3整合與AIO telemetry驗證。
