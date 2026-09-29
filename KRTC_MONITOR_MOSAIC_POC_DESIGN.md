# KRTC PAO V6 Monitor Mosaic PoC Design

> 日期：2026-09-04  
> Worktree：`C:\KRTC_DEV\PAO_V6_MONITOR_MOSAIC`  
> Branch：`poc/monitor-wall-mosaic`  
> Baseline：`software-field-baseline-20260904` / `527119b`  
> 本文件只定義下一輪PoC；本輪未建立或修改production source

## 1. PoC Goal

驗證9與16格能在不新增RTSP ownership的前提下，以單一server-side composite MJPEG連線完整顯示，避開Edge/Chromium HTTP/1.1六連線上限，並將同步Waitress長佔worker降為1。

PoC只驗證：

- 9/16 Camera latest-frame composite；
- shared RTSP reuse；
- one encode loop per canonical layout，而非per browser；
- one browser media connection；
- dead/stale/opening Camera不阻塞整張mosaic；
- disconnect、reload、group switch與retention cleanup；
- CPU、RAM、threads、handles、bandwidth與HTTP responsiveness。

1/4格可維持現有per-camera MJPEG作為compatibility control。PoC不是完整UI重寫，也不是Field release。

## 2. Architecture Diagram

```text
RTSP CAM01 ─► SharedCameraStream 01 ─┐
RTSP CAM02 ─► SharedCameraStream 02 ─┤ latest snapshots, never blocking peers
...                                  ├─► SharedMosaicStream(layout key)
RTSP CAM16 ─► SharedCameraStream 16 ─┘      │
                                              ├─ resize/paste or placeholder
                                              ├─ one JPEG encode per tick
                                              ├─ latest JPEG + version
                                              ▼
                                      MosaicRegistry
                                      subscriber_count=N browsers
                                              │
                             one StreamingHttpResponse per browser
                                              │
                                              ▼
                                one <img id="monitor-mosaic">
                                              │
                                  future M2 tile DOM overlays
```

關鍵不變量：

```text
Mosaic module contains no cv2.VideoCapture()
RTSP owners per Django process <= unique active camera count
Composite encode loops per canonical layout = 1
Browser media connections per displayed mosaic = 1
```

## 3. 9-grid Design

固定server profile：

```text
name: grid9
rows × columns: 3 × 3
max cameras: 9
canvas: 1600 × 900
tile widths: 534, 533, 533
tile height: 300
fps: 8
jpeg quality: initial 70 (server-controlled)
```

1600不能整除3；使用預先計算邊界 `[0, 534, 1067, 1600]`，避免最後一欄缺pixel。Camera frame先依16:9 center-crop或letterbox至tile；PoC建議letterbox以避免裁掉月台邊緣，背景黑色。

每125 ms compositor tick讀取9個latest snapshots；任何Camera失敗只替換該tile。不得等待9台同步到同一frame timestamp。

## 4. 16-grid Design

固定server profile：

```text
name: grid16
rows × columns: 4 × 4
max cameras: 16
canvas: 1600 × 900
tile: 400 × 225
fps: 5（A/B上限6）
jpeg quality: initial 65 (server-controlled)
```

200 ms tick可降低AIO CPU與memory bandwidth，同時足以供多格監看。若CPU或RSS不穩，A/B profile降為1280×720、320×180 tile、4 fps；不得由browser任意傳入fps/resolution/quality。

## 5. Resolution, CPU and Bandwidth Trade-off

| Canvas | Pixels/frame | grid9 @ 8 fps | grid16 @ 5 fps | 預期用途 |
|---|---:|---:|---:|---|
| 1920×1080 | 2.07 MP | 16.59 MP/s encode | 10.37 MP/s encode | 品質上限測試；初始CPU/頻寬最高 |
| 1600×900 | 1.44 MP | 11.52 MP/s encode | 7.20 MP/s encode | 建議主PoC，與1920×1080實際grid接近 |
| 1280×720 | 0.92 MP | 7.37 MP/s encode | 4.61 MP/s encode | 降載fallback與A/B基準 |

實際JPEG bytes依內容、quality與noise而變，不能只以raw pixels推算。telemetry必須記錄rolling `jpeg_bytes_avg/p95` 與實際egress Mbps。

相較16條separate MJPEG：

- 仍存在：16路RTSP network input、16路decode、latest full-frame storage。
- 增加：每tick 16次tile selection/resize/paste、placeholder與一次canvas compose。
- 降低：每browser由16次JPEG encode變成每canonical layout一次encode；輸出multipart與browser decode/render也由16份變1份。
- 若兩個browser共用layout：共享Mosaic後仍只encode一次，但會有兩條mosaic HTTP delivery connections；這是正確的共享層級。

1280×720 BGR frame約2.64 MiB，16份latest約42.2 MiB。compositor應逐Camera snapshot→resize→paste後立即釋放full copy，避免同時保存另一組42 MiB copies。1600×900 canvas約4.12 MiB，encoded JPEG通常遠小於raw canvas。

## 6. Frame Pipeline

每個tick：

1. 以canonical ordered camera slots迭代。
2. 對每個SharedCameraStream取得立即返回的latest snapshot；不得呼叫HTTP health endpoint。
3. 比較frame version與monotonic frame age。
4. 新鮮frame：copy、保持aspect ratio resize、paste到預先配置canvas region。
5. 無frame/opening/stale/offline：畫server-side placeholder tile。
6. 所有tile完成後只呼叫一次 `cv2.imencode('.jpg', canvas, quality)`。
7. encode成功才publish `(jpeg_version, jpeg_bytes, composed_at)`；失敗保留上一張或publish安全placeholder mosaic，不終止thread。
8. subscriber generator只等待新的jpeg version並yield multipart boundary，不做resize/compose/encode。

不要每tick配置16個長期numpy buffers。Canvas可重用，但publish前的encoded bytes必須immutable；所有shared state以Condition保護並縮短lock範圍。

## 7. SharedMosaicStream Design

建議新增 `apps/cameras/mosaic.py`，不要把compositor塞入`views.py`。

### `MosaicProfile`

不可由client自由修改的immutable profile：

```text
name, rows, columns, camera_limit
canvas_width, canvas_height
fps, jpeg_quality
stale_after_ms
```

只允許server registry中的 `grid9`、`grid16`。1/4在PoC沿用原path。

### `SharedMosaicStream`

狀態：

```text
layout_key = (profile_name, ordered_camera_ids)
camera_streams
latest_jpeg
jpeg_version
last_composed_at_monotonic
subscriber_count
compose_count / encode_failures / dropped_ticks
per_tile_frame_age_ms / tile_state
stopped / stop_requested / idle_since
thread
condition
```

行為：

- 第1個mosaic subscriber啟動一個compositor並對每個unique Camera各subscribe一次。
- 第2個相同layout browser只增加mosaic subscriber，不新增Camera subscriptions或encode loop。
- subscriber等待latest JPEG，不在Waitress worker內做composition。
- layout中重複camera id在validation階段拒絕；不允許以同一Camera填兩格來規避計數。
- compositor thread `finally`逐一unsubscribe所有Camera stream並從registry移除自己。

### `MosaicRegistry`

以process-local lock原子取得canonical `layout_key`，避免兩個同時request各自建立compositor。必須限制active layout數、每session建立速率與idle entries；多process限制與Camera registry相同，需在production deployment note揭露。

### Retention Policy

不建議對Mosaic再套15秒camera-style retention。最後mosaic client離開時應立即或至多1–2秒內停止compose並unsubscribe underlying Camera；之後由既有SharedCameraStream保留15秒RTSP。若Mosaic也保留15秒，RTSP釋放可能變成約30秒，會破壞已驗證行為。

短暫reload仍可建立新Mosaic但取得retention中的原Camera owners，不重開RTSP。是否保留最後JPEG 1–2秒可在PoC A/B，不能延後Camera unsubscribe。

## 8. Latest-frame Semantics

每台Camera獨立：

```text
latest frame exists AND age <= stale threshold -> FRAME
no frame AND capture starting                 -> CONNECTING
frame exists BUT age > threshold              -> STALE / NO SIGNAL
capture error or stopped                       -> NO SIGNAL
slot has no Camera                             -> EMPTY SLOT
```

Compositor不設global barrier，不要求所有version增加，也不因單台 `wait_for_frame()`阻塞。Camera有新frame時使用最新frame；沒有新frame時可在stale threshold內重用上一個tile cache。Camera R3的monotonic `last_frame_age_ms`應是production source of truth；PoC若在baseline執行，可由compositor在version變動時自行記錄monotonic receive time，但必須標為temporary adapter。

## 9. Placeholder Behavior

Placeholder固定使用本地canvas繪製，不讀filesystem path、不打health endpoint：

```text
CAM-007
CONNECTING
```

```text
CAM-007
NO SIGNAL
```

```text
SLOT 12
EMPTY
```

顏色：CONNECTING用amber、NO SIGNAL用red、EMPTY用slate；Camera code須來自已驗證DB object並限制長度。不要在placeholder或log顯示RTSP URL、username、password或exception原文。

## 10. Endpoint Design

### PoC minimum endpoint

```text
GET /api/cameras/mosaic-stream/?layout=grid9&group=0
GET /api/cameras/mosaic-stream/?layout=grid16&group=0
```

PoC不接受camera IDs。Server以active Camera固定排序及validated non-negative bounded group index推導該組9/16台，消除任意ID注入，代價是暫不反映client drag layout。

Endpoint必須：

- `login_required`；
- layout只接受grid9/grid16，其他回400；
- group轉整數、限制在實際group範圍；
- queryset只取active且有stream設定、使用者有權查看的Camera；
- 不接受RTSP URL、credential、filesystem path、fps、resolution或quality；
- response設 `Cache-Control: no-store/no-cache` 與 `X-Accel-Buffering: no`；
- 使用canonical ordered IDs取得SharedMosaicStream；
- generator `finally`一定unsubscribe mosaic；
- invalid/empty layout不啟動thread。

### Production layout endpoint

```text
POST /api/cameras/mosaic-layouts/
Content-Type: application/json
CSRF required
{"layout":"grid16","camera_ids":[7,2,...]}

201 {"stream_url":"/api/cameras/mosaic-stream/<signed_token>/"}
GET /api/cameras/mosaic-stream/<signed_token>/
```

POST驗證：最多16、數量不超profile、unique positive integers、Camera存在/active/authorized；再建立短時效Django signed token，token內容只含profile、ordered IDs、issued-at與user/session binding，不含URL或credential。GET重新驗證signature、expiry、user binding及Camera active狀態。

防DoS：每session同時active mosaic最多1個、短時間layout create rate limit、global process registry cap、canonical key reuse、server固定profile。若沒有現成rate-limit infrastructure，PoC至少做hard caps與舊layout release，production前再決定middleware/部署層限流；不得為此引入Redis/Celery/Channels。

## 11. Frontend M1 Design

9/16切換時顯示：

```html
<div class="mosaic-container" data-mosaic-container>
    <img id="monitor-mosaic" class="mosaic-stream" alt="9 camera monitor mosaic">
    <div class="mosaic-loading">...</div>
</div>
```

M1行為：

- grid1/grid4仍使用既有card/per-camera MJPEG。
- grid9/grid16先release目前per-camera `<img>` requests，再設一條mosaic `src`。
- group navigation/carousel只更新validated `group` URL，且先清除舊`src`。
- pagehide/beforeunload/logout/navigation都清除mosaic `src`。
- Camera tree、search、event alert可保留；tile click/drag/drop可在M1明確停用或只更新下一輪group，不宣稱功能完整。
- load/error/15秒warning改為mosaic-level，不以9/16張image load事件判斷。
- tile status由JPEG placeholder表達；不啟動9/16個blocking baseline health requests。

M1是最小transport PoC。它可確認9/16全部represented、connections、workers與resource stability，但Camera label的獨立DOM、keyboard focus、tooltip及per-tile interaction不足。

## 12. Future M2 Overlay Design

```html
<div class="mosaic-container" data-layout="grid16">
    <img class="mosaic-stream">
    <div class="mosaic-overlay-grid">
        <button class="mosaic-tile-overlay" data-slot="0" data-camera-id="7">
            <span>CAM-007</span><span class="status">ONLINE</span>
        </button>
        <!-- up to 16 overlays -->
    </div>
</div>
```

Overlay grid與backend使用相同ordered slot mapping。可保留：

- label、status badge、tooltip與ARIA文字；
- click selection與keyboard focus；
- drag/drop後POST新layout並原子切換token；
- double-click切到既有single-camera view；
- event camera依ID加highlight class；
- per-tile CONNECTING/OFFLINE遮罩，不影響mosaic media connection。

M2 health資料應來自R3 shared diagnostics或一個批次non-blocking status API，不應每30秒同時呼叫16個會開capture的baseline `/check/`。

## 13. Lifecycle and Cleanup

```text
HTTP request arrives
  -> validate/authenticate layout
  -> MosaicRegistry.acquire(key)
  -> mosaic.subscribe()
  -> generator waits latest JPEG and yields

client changes group/grid/reloads/leaves/logs out
  -> browser clears old img src / TCP closes
  -> generator receives GeneratorExit/disconnect
  -> finally mosaic.unsubscribe()
  -> subscriber_count reaches 0
  -> stop compositor promptly
  -> finally unsubscribe all SharedCameraStreams
  -> each Camera enters existing 15-second retention
  -> registry removes current mosaic owner
```

需防護：double unsubscribe、constructor中途失敗、部分Camera acquire失敗、encode exception、browser rapid reload、same-key concurrent acquire及thread startup race。Compositor wait應使用Condition/event，可在stop時喚醒，禁止長 `sleep()`拖延cleanup。

## 14. Security Limits

| Control | PoC/Production requirement |
|---|---|
| Authentication | 所有stream與layout endpoint必須登入 |
| Authorization | 只允許使用者可看的active Camera |
| Layouts | server allowlist grid9/grid16（production可擴1/4） |
| Camera count | hard max 16 |
| Duplicates | reject |
| Missing/inactive | reject或server-derived EMPTY；規則需一致 |
| FPS | server fixed 8/5，client不可覆寫 |
| Canvas | server fixed 1600×900，client不可覆寫 |
| Quality | server fixed，client不可覆寫 |
| Layout churn | canonical key、per-session active cap與rate limit |
| Secrets | response/log/token均不含RTSP URL/credential |
| Paths | endpoint不接受任何filesystem path |
| Anonymous access | deny |

## 15. Telemetry

三組baseline必須用同一採樣方法：現有9-grid六格、mosaic grid9、mosaic grid16。至少記錄：

| Metric | 建議來源/方法 |
|---|---|
| RTSP sessions | MediaMTX/API或TCP 8554 established count，按Camera去重 |
| Browser media HTTP connections | Edge DevTools Network與server active stream counter |
| Waitress active/queued threads | Waitress log/queue depth與process thread sampling |
| Process threads | OS process counter，每秒採樣 |
| Handles | Windows process handle count |
| CPU | process CPU avg/p95/max |
| RAM | working set與private bytes/RSS，觀察斜率 |
| Ordinary HTTP latency | `/dashboard/`或read-only API固定12次，成功率及p50/p95/max |
| Mosaic FPS | compositor publish count/time與browser received estimate |
| JPEG output size | bytes avg/p95/max與egress Mbps |
| Frame age | 每tile age avg/p95/max與stale tile count |
| Dropped frames/ticks | source version skips、late ticks、encode failures |
| Registry lifecycle | active mosaic keys/subscribers、Camera subscribers、create/destroy count |

日志只能用camera id/code、layout hash與數值；不得記RTSP URL或credential。每次測試至少穩定運行15分鐘，另做30次grid/group切換與20次reload/leave-return循環。

## 16. Acceptance Criteria

### 9-grid PASS

- 9台Camera全部represented；dead Camera只顯示自身placeholder。
- browser media HTTP connections約1。
- underlying RTSP約9，health週期不應規律增加第10條。
- 無永久loading tile；opening最終轉frame或placeholder。
- 固定普通HTTP probe全部成功，無3秒timeout；記錄p95而非只看單次。
- CPU/RAM在15分鐘內穩定，無持續上升趨勢。
- thread/handle count在切換與reload後回到穩定區間。

### 16-grid PASS

- 16台Camera全部represented。
- browser media HTTP connections約1，underlying RTSP約16。
- 普通HTTP保持可回應，Waitress queue無永久starvation。
- 實際mosaic FPS達server profile可接受範圍，late ticks受控。
- CPU不長時間飽和；RSS/thread/handle沒有持續成長。

### Retention PASS

- 離開Monitor Wall後Mosaic subscriber與compositor promptly cleanup。
- underlying Camera立即進入既有retention，約15秒加disconnect margin後RTSP歸零。
- 15秒內返回可reuse underlying SharedCameraStream，不重建RTSP session。
- 兩個browser看同一canonical layout只存在一個encode loop。

## 17. Failure Criteria

任一項即判PoC失敗或必須回設計修正：

- 一台dead/stale Camera令整張mosaic停止更新。
- 16 Camera令CPU長時間飽和或ordinary HTTP timeout。
- RSS持續成長，不能在停止後回落至合理區間。
- mosaic/compositor thread或handle隨reload/grid switch持續增加。
- RTSP session超過unique expected Camera count，或health造成規律duplication。
- 同layout多browser建立多個encode loops。
- browser reload產生orphan compositor。
- logout/page exit後stream與subscriber無法cleanup。
- Mosaic retention疊加導致underlying RTSP明顯超過既有15秒政策。
- endpoint接受任意RTSP URL、超過16 Camera、任意FPS/8K/quality或未登入存取。
- Camera label/slot mapping與實際tile影像錯位。

## 18. Estimated Source Changes for Next Round

理想最小邊界：

| File | PoC change |
|---|---|
| `apps/cameras/mosaic.py`（新增） | profiles、placeholder、compose、SharedMosaicStream、registry與metrics |
| `apps/cameras/views.py` | 小型validated endpoint adapter與multipart generator；不放compose loop |
| `apps/cameras/urls.py` | 一條mosaic route |
| `templates/dashboard/monitor.html` | M1 mosaic container；保留既有cards供1/4 |
| `static/js/monitor.js` | 9/16 transport switch、group URL、cleanup；1/4 regression |
| `static/css/monitor.css` | M1 canvas sizing/loading；未來M2 overlay grid |
| `apps/cameras/tests/test_mosaic.py`（新增） | unit/concurrency/security/lifecycle tests |

`apps/dashboard/views.py` 原則上不需修改，因PoC endpoint可server-side依active Camera排序；若要簽發initial layout token才考慮極小context addition。不得修改model、migration、requirements或Camera R3 source副本。

下一輪至少應有mock tests：no `VideoCapture` in mosaic、non-blocking dead Camera、one encode owner for concurrent clients、unique Camera subscriptions、finally cleanup、profile/input/auth limits、credential-free errors、placeholder state、group derivation與1/4 existing path不變。

## 19. AIO Test Matrix

| Case | Layout | Cameras | Clients | Fault injection | Duration/loops |
|---|---|---:|---:|---|---|
| B0 | existing grid9 | 9 | 1 | none | reproduce 6-tile ceiling |
| M9-1 | mosaic grid9 | 9 | 1 | none | 15 min |
| M9-2 | mosaic grid9 | 9 | 2 same layout | none | 15 min; verify one encoder |
| M9-D | mosaic grid9 | 9 | 1 | one Camera offline | 10 min |
| M16-1 | mosaic grid16 | 16 | 1 | none | 15 min |
| M16-2 | mosaic grid16 | 16 | 2 same layout | none | 15 min |
| M16-D | mosaic grid16 | 16 | 1 | 1 then 4 Cameras offline | recovery test |
| SWITCH | 4↔9↔16↔1 | 16 | 1 | none | 30 cycles |
| RELOAD | grid16 | 16 | 1 | none | 20 reloads |
| RET-FAST | grid16 | 16 | 1 | leave/return <15s | 10 cycles |
| RET-FULL | grid16 | 16 | 1 | leave >15s | verify RTSP 16→0 |
| LOGOUT | grid16 | 16 | 1 | logout while streaming | verify cleanup/auth |
| LOAD | grid16 | 16 | 1 | ordinary HTTP 12+ requests | success/p95/queue |

每個case都記錄第15節全部metrics。測試順序先1280×720 safety profile，再1600×900主profile；1920×1080只在資源有headroom時測。

## 20. Rollback Boundary

PoC應以feature switch或9/16 frontend branch選擇控制。rollback只需：

- 關閉Mosaic 9/16 activation，回到原per-camera URL；
- 移除mosaic route/module與M1 markup/JS/CSS；
- 不改DB、不做migration rollback；
- SharedCameraStream、1/4與其他Django功能不受影響。

在本branch未commit階段可只restore上述PoC檔案；不得reset、clean或操作其他worktree。正式整合應用non-destructive revert。

## 21. Mosaic vs HTTP/2 Reverse Proxy

| 面向 | Mosaic PoC | HTTP/2 proxy + existing MJPEG |
|---|---|---|
| Browser media connections | 9/16畫面約1 | 可multiplex browser transport，但仍有9/16 logical streams |
| Waitress workers | 約1個長worker/client mosaic | proxy不會自動消除backend 9/16個同步StreamingHttpResponse workers |
| Server CPU | 9/16 decode + tile resize + 1 encode/layout | 9/16 decode + 9/16 encode/client仍大致保留 |
| Deployment | Django/OpenCV內局部PoC | 新proxy、HTTP/2/TLS/cert與service管理 |
| Windows AIO維護 | 沿用現有process，需監控compositor | 增加proxy設定、patch、log與故障面 |
| Rollback | 關閉feature、恢復per-camera frontend | 涉及network/TLS/proxy routing rollback |
| Field risk | CPU/compose品質與功能整合 | TLS、proxy buffering、WSGI worker仍不足等風險 |

因此目前先選Mosaic：它同時處理browser connection ceiling與Waitress logical stream數，而HTTP/2主要處理browser transport multiplexing，未直接解決同步backend worker與多次JPEG encode。HTTP/2仍可作長期transport hardening，但不是本PoC最小修復。

## 22. Production Integration Notes

1. 先整合並AIO驗證Camera R3，再讓Mosaic依賴其atomic owner、shared frame age、bounded timeout與backoff。
2. PoC M1通過後才做M2 overlays與production layout POST/signed token。
3. 保留1/4現況作rollback及A/B control，不一次改寫全部Monitor Wall。
4. 確認正式部署只有預期Django process數；process-local registry不跨process共享。
5. Waitress threads=8只是假設測試點，必須以queue/latency/多client實測決定。
6. 使用server metrics與bounded registry，避免layout churn、orphan thread與silent encode failure。
7. 針對logout/session invalidation與既有長連線語意做專門安全回歸。

## 23. Explicit Non-Claims

- 本輪沒有實作Mosaic，也沒有修改production source。
- 不宣稱目前9/16 Monitor Wall已可完整顯示。
- 不宣稱Waitress threads=8足以正式部署。
- 不宣稱Mosaic降低RTSP decode數；9/16仍預期有9/16條underlying RTSP。
- 不宣稱baseline health duplication已解決；該項屬Camera R3工作線。
- 不宣稱多Django process可共享Camera或Mosaic registry。
- 不宣稱M1保留drag/drop、per-tile status、tooltip、double-click與完整無障礙功能。
- 不宣稱Field AIO CPU、RAM、FPS、bandwidth、retention或cleanup已驗證。
- 不包含HTTP/2、WebRTC、MediaMTX轉發、DB schema、migration或dependency變更。
- 不修改Camera R3或Security/UI worktree。

## 24. Review Decision

六項review判斷：

1. 可完全禁止Mosaic建立 `VideoCapture`，改由SharedCameraStream提供frames。
2. 單一mosaic `<img>`可避開9/16條browser long-connection ceiling。
3. 單一StreamingHttpResponse可把9/16格長佔Waitress workers降為1。
4. Prompt cleanup後交回既有SharedCameraStream 15-second retention，可保留Camera lifecycle。
5. 新增獨立`mosaic.py`加小型endpoint與9/16 frontend switch即可做PoC，不需重寫整個Django架構。
6. Source、feature activation與rollback boundary明確，1/4既有path可維持。

最終結論：`READY_FOR_MOSAIC_POC_IMPLEMENTATION`。

此結論只授權下一輪受限PoC規劃的技術可行性，不等同production merge或Field deployment核准。
