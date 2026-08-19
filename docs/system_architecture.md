# KRTC AI CCTV 通報主機 Django 系統架構說明

## 1. 專案背景

本專案為 KRTC AI CCTV 通報主機系統之 Django 版本。前期已完成 PoC 與 MVP 測試，包含 Dashboard UI、Flask + OpenCV 後端串流，以及 IP Camera RTSP 影像接入測試。

經小組討論後，後續系統將由 Flask MVP 轉換為 Django 架構，以利建立較完整的資料庫、API、AI 模型管理、事件紀錄、通報流程、權限控管與部署維護。

本文件主要說明目前 Django 專案架構、各 App 模組用途、AI 模型放入資料庫後的取用方式，以及後續 API 串接方向。

---

## 2. 系統目標

本系統主要目標如下：

1. 建立通報主機 Dashboard UI。
2. 串接多台 IP Camera 並顯示即時影像。
3. 接收 AI 模型偵測結果。
4. 將 AI 事件寫入資料庫。
5. 提供事件確認、誤報、通報與結案流程。
6. 提供事件紀錄查詢與後續報表功能。
7. 建立 AI 模型資料庫管理機制，使前端與後端 API 可依設定取用模型資訊。
8. 建立可部署於 AIO 通報主機或工作電腦的系統架構。

---

## 3. 技術架構

| 類別 | 技術 |
|---|---|
| Backend Framework | Django |
| API Framework | Django REST Framework |
| Frontend | HTML / CSS / JavaScript |
| Camera Stream | RTSP / OpenCV / MJPEG Streaming |
| Database | SQLite for development, PostgreSQL for deployment |
| AI Integration | AI API / Model Service Bridge |
| Event Management | Django App + Database |
| Deployment Target | AIO 通報主機 / 工作電腦 |

---

## 4. 系統架構圖

```text
IP Cameras
   |
   | RTSP Stream
   v
Camera Stream Service
OpenCV / FFmpeg / Snapshot Capture
   |
   |--------------------------
   |                         |
   v                         v
Dashboard Live View       AI Model / AI API
   |                         |
   |                         v
   |                   AI Detection Result
   |                         |
   v                         v
Django Backend  <------  AI Bridge API
   |
   |-- accounts
   |-- dashboard
   |-- cameras
   |-- events
   |-- ai_bridge
   |-- notifications
   |-- records
   |-- settings_app
   |
   v
Database
   |
   v
Event Query / Notification / System Management
```

---

## 5. 專案資料夾結構

目前 Django 專案規劃結構如下：

```text
krtc_notification_host/
├─ manage.py
├─ requirements.txt
├─ README.md
├─ .env
├─ .gitignore
│
├─ config/
│  ├─ __init__.py
│  ├─ settings.py
│  ├─ urls.py
│  ├─ asgi.py
│  └─ wsgi.py
│
├─ apps/
│  ├─ accounts/
│  │  ├─ models.py
│  │  ├─ views.py
│  │  ├─ urls.py
│  │  ├─ serializers.py
│  │  └─ permissions.py
│  │
│  ├─ dashboard/
│  │  ├─ views.py
│  │  ├─ urls.py
│  │  └─ templates/
│  │     └─ dashboard/
│  │        └─ index.html
│  │
│  ├─ cameras/
│  │  ├─ models.py
│  │  ├─ views.py
│  │  ├─ urls.py
│  │  ├─ serializers.py
│  │  ├─ permissions.py
│  │  └─ stream.py
│  │
│  ├─ events/
│  │  ├─ models.py
│  │  ├─ views.py
│  │  ├─ urls.py
│  │  ├─ serializers.py
│  │  └─ permissions.py
│  │
│  ├─ ai_bridge/
│  │  ├─ models.py
│  │  ├─ views.py
│  │  ├─ urls.py
│  │  └─ services.py
│  │
│  ├─ notifications/
│  │  ├─ models.py
│  │  ├─ views.py
│  │  ├─ urls.py
│  │  └─ services.py
│  │
│  ├─ records/
│  │  ├─ views.py
│  │  ├─ urls.py
│  │  └─ export.py
│  │
│  └─ settings_app/
│     ├─ models.py
│     ├─ views.py
│     ├─ urls.py
│     └─ serializers.py
│
├─ static/
│  ├─ css/
│  │  └─ style.css
│  ├─ js/
│  │  ├─ app.js
│  │  ├─ dashboard.js
│  │  ├─ events.js
│  │  ├─ records.js
│  │  └─ settings.js
│  └─ images/
│
├─ templates/
│  ├─ base.html
│  ├─ login.html
│  └─ layout/
│     ├─ navbar.html
│     └─ sidebar.html
│
├─ media/
│  ├─ snapshots/
│  └─ event_clips/
│
├─ logs/
│
└─ docs/
   ├─ system_architecture.md
   ├─ api_spec.md
   ├─ deployment_guide.md
   └─ development_log.md
```

---

## 6. Django Apps 模組說明

### 6.1 accounts

`accounts` app 負責使用者登入、角色、權限與操作紀錄。

預計角色包含：

| 角色 | 說明 |
|---|---|
| Admin | 系統管理者，可管理帳號、攝影機、AI 模型與系統設定 |
| Operator | 操作員，可查看 Dashboard、確認事件與執行通報 |
| Viewer | 僅可查看 Dashboard 與事件紀錄 |
| AI Engineer | 可管理 AI 模型設定與測試 AI API |

初期可先使用 Django 內建 `User`、`Group` 與 `Permission`。若後續有進階需求，再擴充自訂 User model。

---

### 6.2 dashboard

`dashboard` app 負責通報主機主畫面。

主要功能：

1. 顯示 1 / 4 / 9 / 16 分割攝影機畫面。
2. 顯示 Camera online / offline 狀態。
3. 顯示最新 AI 偵測事件。
4. 提供事件詳情彈窗。
5. 提供通報操作入口。
6. 支援區域篩選與攝影機群組切換。
7. 接收後端事件資料並更新前端畫面。

前期 Dashboard 可使用 Django Template 搭配原生 JavaScript。後續若系統規模增加，可再評估 Vue 或 React。

---

### 6.3 cameras

`cameras` app 負責 IP Camera 管理與串流。

主要功能：

1. 新增、修改、停用 Camera。
2. 儲存 Camera 名稱、代碼、區域、RTSP URL。
3. 提供即時影像串流 endpoint。
4. 提供 Camera snapshot 擷取功能。
5. 提供 Camera online / offline 健康檢查。
6. 提供 Dashboard 查詢 Camera 清單。

建議資料表：

```python
class Camera(models.Model):
    name = models.CharField(max_length=100)
    camera_code = models.CharField(max_length=50, unique=True)
    area = models.CharField(max_length=100)
    rtsp_url = models.TextField()
    username = models.CharField(max_length=100, blank=True)
    password = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    is_online = models.BooleanField(default=False)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
```

欄位說明：

| 欄位 | 說明 |
|---|---|
| name | Camera 顯示名稱 |
| camera_code | Camera 代碼，例如 CAM-001 |
| area | Camera 所屬區域 |
| rtsp_url | RTSP 串流位置 |
| username | Camera 帳號 |
| password | Camera 密碼 |
| is_active | 是否啟用 |
| is_online | 是否在線 |
| last_checked_at | 最後檢查時間 |
| created_at | 建立時間 |

---

### 6.4 events

`events` app 負責 AI 偵測事件與事件處理流程。

主要功能：

1. 儲存 AI 偵測事件。
2. 儲存事件類型、信心分數、來源 Camera、發生時間。
3. 儲存事件快照。
4. 提供事件確認、誤報、通報與結案流程。
5. 提供事件查詢 API。
6. 提供 Dashboard 最新事件資料。

建議事件狀態：

| 狀態 | 說明 |
|---|---|
| new | 新事件 |
| reviewing | 操作員確認中 |
| confirmed | 已確認 |
| false_alarm | 誤報 |
| notified | 已通報 |
| closed | 已結案 |

建議資料表：

```python
class Event(models.Model):
    EVENT_TYPES = [
        ("intrusion", "入侵"),
        ("fall", "跌倒"),
        ("fight", "鬥毆"),
        ("fire", "火煙"),
        ("abnormal", "異常行為"),
    ]

    STATUS_CHOICES = [
        ("new", "新事件"),
        ("reviewing", "確認中"),
        ("confirmed", "已確認"),
        ("false_alarm", "誤報"),
        ("notified", "已通報"),
        ("closed", "已結案"),
    ]

    camera = models.ForeignKey("cameras.Camera", on_delete=models.CASCADE)
    event_type = models.CharField(max_length=50, choices=EVENT_TYPES)
    confidence = models.FloatField(default=0.0)
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default="new")
    snapshot = models.ImageField(upload_to="snapshots/", null=True, blank=True)
    description = models.TextField(blank=True)
    detected_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
```

---

### 6.5 ai_bridge

`ai_bridge` app 負責 Django 系統與 AI 模型之間的銜接。

本模組不直接負責 AI 模型訓練，而是負責：

1. 讀取資料庫中的 AI 模型設定。
2. 判斷目前啟用的 AI 模型。
3. 將 Camera snapshot 或 stream frame 傳給 AI API。
4. 接收 AI API 回傳結果。
5. 將 AI 偵測結果轉換成 Event。
6. 提供 AI API 測試 endpoint。
7. 提供 AI model status 查詢。

設計原則：

```text
AI 模型與 Django 主系統分離。
Django 負責管理模型設定、事件建立與資料流。
AI 模型可以由外部 API 或本機模型服務提供。
```

---

### 6.6 notifications

`notifications` app 負責事件通報流程。

主要功能：

1. 記錄操作員執行的通報動作。
2. 儲存通報對象、通報訊息、通報結果。
3. 關聯事件資料與操作員資料。
4. 後續可串接 Email、LINE、簡訊或內部通報 API。

建議資料表：

```python
class NotificationLog(models.Model):
    event = models.ForeignKey("events.Event", on_delete=models.CASCADE)
    operator = models.ForeignKey("auth.User", on_delete=models.SET_NULL, null=True)
    target = models.CharField(max_length=100)
    message = models.TextField()
    result = models.CharField(max_length=50, default="success")
    sent_at = models.DateTimeField(auto_now_add=True)
```

---

### 6.7 records

`records` app 負責歷史紀錄查詢與匯出。

查詢條件包含：

1. 日期區間。
2. Camera。
3. 區域。
4. 事件類型。
5. 事件狀態。
6. 信心分數。
7. 操作員。

後續可加入：

1. CSV 匯出。
2. Excel 匯出。
3. PDF 報表。
4. 事件統計圖表。

---

### 6.8 settings_app

`settings_app` app 負責系統參數設定。

主要功能：

1. AI 模型啟用或停用。
2. 各事件類型 confidence threshold 設定。
3. Dashboard 預設分割畫面。
4. Camera 輪巡時間。
5. 通報對象設定。
6. 系統模式設定，例如 Demo、Test、Production。

此 app 命名為 `settings_app`，避免與 Django 專案中的 `config/settings.py` 混淆。

---

## 7. AI 模型資料庫設計

為了讓 AI 模型可以由資料庫管理，建議建立 `AIModel` 資料表。此資料表主要負責記錄目前系統中可用的 AI 模型、模型版本、模型用途、API 位置、模型路徑、信心分數門檻與啟用狀態。

建議資料表：

```python
class AIModel(models.Model):
    name = models.CharField(max_length=100)
    model_code = models.CharField(max_length=50, unique=True)
    version = models.CharField(max_length=50)
    event_type = models.CharField(max_length=50)
    api_url = models.URLField(blank=True)
    model_path = models.TextField(blank=True)
    confidence_threshold = models.FloatField(default=0.8)
    is_active = models.BooleanField(default=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

欄位說明：

| 欄位 | 說明 |
|---|---|
| name | AI 模型名稱 |
| model_code | 模型代碼，例如 FALL_DETECTION_V1 |
| version | 模型版本 |
| event_type | 模型負責辨識的事件類型 |
| api_url | 若模型以 API 形式提供，則儲存 API URL |
| model_path | 若模型放在本機，則儲存模型路徑 |
| confidence_threshold | 事件成立門檻 |
| is_active | 是否啟用 |
| description | 模型說明 |
| created_at | 建立時間 |
| updated_at | 更新時間 |

---

## 8. Camera 與 AI 模型關聯設計

若不同 Camera 需要啟用不同 AI 模型，建議建立 Camera 與 AIModel 的關聯資料表。

建議資料表：

```python
class CameraAIModel(models.Model):
    camera = models.ForeignKey("cameras.Camera", on_delete=models.CASCADE)
    ai_model = models.ForeignKey("ai_bridge.AIModel", on_delete=models.CASCADE)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
```

使用情境：

```text
CAM-001 可啟用 Fall Detection。
CAM-002 可啟用 Intrusion Detection。
CAM-003 可同時啟用 Fall Detection 與 Fire Detection。
```

此設計可支援多 Camera、多模型、多事件類型的擴充。

---

## 9. AI 模型取用流程

AI 模型不建議直接寫死在 Django 程式碼中，而是由資料庫管理。Django 系統透過 `ai_bridge` app 讀取目前啟用的 AI 模型設定，再呼叫對應的 AI API 或模型服務。

流程如下：

```text
1. cameras app 擷取指定 Camera 的 snapshot。
2. ai_bridge app 查詢該 Camera 目前啟用的 AIModel。
3. ai_bridge 根據 AIModel.api_url 或 AIModel.model_path 呼叫模型。
4. AI 模型回傳偵測結果。
5. ai_bridge 判斷 confidence 是否大於 confidence_threshold。
6. 若事件成立，建立 Event。
7. events app 儲存事件資料。
8. dashboard app 顯示新事件。
9. operator 執行確認、誤報、通報或結案。
```

---

## 10. AI API 回傳格式建議

AI 模型服務建議回傳以下 JSON 格式：

```json
{
  "camera_code": "CAM-001",
  "model_code": "FALL_DETECTION_V1",
  "event_type": "fall",
  "confidence": 0.92,
  "bbox": [
    {
      "x": 120,
      "y": 80,
      "w": 60,
      "h": 120
    }
  ],
  "timestamp": "2026-06-30T14:30:00+08:00",
  "message": "Fall detected"
}
```

欄位說明：

| 欄位 | 說明 |
|---|---|
| camera_code | 事件來源 Camera |
| model_code | 使用的 AI 模型 |
| event_type | 事件類型 |
| confidence | 信心分數 |
| bbox | 偵測框座標 |
| timestamp | 偵測時間 |
| message | 模型回傳訊息 |

---

## 11. Django 接收 AI 結果的 API

建議 endpoint：

```text
POST /api/ai/events/
```

Request body：

```json
{
  "camera_code": "CAM-001",
  "model_code": "FALL_DETECTION_V1",
  "event_type": "fall",
  "confidence": 0.92,
  "bbox": [
    {
      "x": 120,
      "y": 80,
      "w": 60,
      "h": 120
    }
  ],
  "timestamp": "2026-06-30T14:30:00+08:00"
}
```

Django 後端處理邏輯如下：

```text
1. 根據 camera_code 找到 Camera。
2. 根據 model_code 找到 AIModel。
3. 檢查 AIModel 是否啟用。
4. 檢查 confidence 是否大於 AIModel.confidence_threshold。
5. 建立 Event。
6. 儲存 bbox 與 snapshot 資訊。
7. 回傳建立成功訊息。
```

Response 範例：

```json
{
  "success": true,
  "event_id": 101,
  "status": "new",
  "message": "AI event created successfully"
}
```

---

## 12. API 規劃

### 12.1 Camera API

```text
GET    /api/cameras/
POST   /api/cameras/
GET    /api/cameras/{id}/
PATCH  /api/cameras/{id}/
DELETE /api/cameras/{id}/
GET    /api/cameras/{id}/stream/
GET    /api/cameras/{id}/snapshot/
POST   /api/cameras/{id}/check/
```

---

### 12.2 Event API

```text
GET    /api/events/
POST   /api/events/
GET    /api/events/{id}/
PATCH  /api/events/{id}/
POST   /api/events/{id}/confirm/
POST   /api/events/{id}/false-alarm/
POST   /api/events/{id}/notify/
POST   /api/events/{id}/close/
```

---

### 12.3 AI Bridge API

```text
GET    /api/ai/models/
POST   /api/ai/models/
GET    /api/ai/models/{id}/
PATCH  /api/ai/models/{id}/
POST   /api/ai/events/
POST   /api/ai/test/
GET    /api/ai/status/
```

---

### 12.4 Dashboard API

```text
GET    /dashboard/
GET    /api/dashboard/summary/
GET    /api/dashboard/recent-events/
GET    /api/dashboard/camera-status/
```

---

## 13. 資料流說明

### 13.1 Camera 即時顯示流程

```text
IP Camera
   |
   | RTSP
   v
cameras/stream.py
   |
   | OpenCV VideoCapture
   v
Django StreamingHttpResponse
   |
   v
Dashboard <img> or video container
```

初期可採用 MJPEG Streaming，以降低前端整合難度。

---

### 13.2 AI 事件建立流程

```text
IP Camera
   |
   v
Snapshot / Frame Capture
   |
   v
AI Model / AI API
   |
   v
AI Detection Result
   |
   v
POST /api/ai/events/
   |
   v
ai_bridge app
   |
   v
events app
   |
   v
Database
   |
   v
Dashboard Event List
```

---

### 13.3 操作員通報流程

```text
Dashboard New Event
   |
   v
Operator Review
   |
   |-- Confirmed
   |-- False Alarm
   |-- Notify
   |-- Close
   v
events app 更新事件狀態
   |
   v
notifications app 紀錄通報行為
   |
   v
records app 提供歷史查詢
```

---

## 14. 資料庫核心資料表

目前建議的核心資料表如下：

```text
User
Camera
AIModel
CameraAIModel
Event
NotificationLog
SystemConfig
AuditLog
```

簡化關聯：

```text
User
 └── NotificationLog

Camera
 ├── Event
 └── CameraAIModel
        └── AIModel

Event
 └── NotificationLog

SystemConfig
AuditLog
```

---

## 15. 開發階段規劃

### Phase 1：Django 基礎架構

目標：將既有 MVP 專案轉為 Django 專案結構。

工作項目：

1. 建立 Django project。
2. 建立 apps 目錄。
3. 建立 dashboard、cameras、events、ai_bridge 等 app。
4. 移植原本 MVP UI 到 Django templates/static。
5. 確認 `/dashboard/` 可正常顯示。

---

### Phase 2：Camera 串流與資料庫

目標：建立 Camera 資料庫與串流 endpoint。

工作項目：

1. 建立 Camera model。
2. 建立 Camera API。
3. 將 CAM-001、CAM-002 寫入資料庫。
4. 建立 RTSP stream endpoint。
5. Dashboard 從 API 取得 Camera 資料。

---

### Phase 3：AI 模型資料庫

目標：讓 AI 模型資訊可由資料庫管理。

工作項目：

1. 建立 AIModel model。
2. 建立 AIModel API。
3. 建立 CameraAIModel 關聯表。
4. 可透過資料庫啟用或停用模型。
5. 可由 API 查詢目前啟用模型。

---

### Phase 4：AI 事件接收

目標：建立 Django 接收 AI 偵測結果的標準流程。

工作項目：

1. 建立 `/api/ai/events/`。
2. 接收 AI API 回傳結果。
3. 根據 camera_code 與 model_code 建立 Event。
4. Dashboard 顯示事件。
5. 操作員可確認、誤報、通報或結案。

---

### Phase 5：正式部署與測試

目標：部署到通報主機並測試系統穩定性。

工作項目：

1. 部署到 AIO 通報主機或工作電腦。
2. 測試多台 IP Camera 同時顯示。
3. 測試 AI 模型事件回傳。
4. 測試事件紀錄查詢。
5. 測試系統穩定性與效能。

---

## 16. 目前優先工作

目前建議優先完成以下項目：

1. 確認 Django 專案可以正常啟動。
2. 修正 `manage.py`、`settings.py`、`urls.py` 等基礎設定。
3. 建立 Camera model。
4. 建立 AIModel model。
5. 建立 Event model。
6. 建立基本 API 路由。
7. 移植現有 Dashboard UI。
8. 串接 CAM-001 與 CAM-002。
9. 建立 AI event receiver API。
10. 將階段性成果同步至 GitHub。

---

## 17. 設計原則

本階段目標不是一次完成正式系統，而是建立可擴充的 Django 架構，使 UI、Camera、AI 模型、事件通報與資料庫可以逐步整合。

目前系統應優先保持以下原則：

1. UI 與後端 API 分離。
2. AI 模型與 Django 主系統分離。
3. 模型設定放入資料庫管理。
4. Camera 設定放入資料庫管理。
5. Event 作為系統核心資料。
6. 先完成可展示版本，再逐步優化效能與部署。
7. 不將 Camera 帳密、RTSP URL、`.env` 等敏感資訊上傳至 GitHub。

---

## 18. 備註

目前本專案處於 Django 架構建立與系統整合前期階段。已先建立專案目錄、README、系統架構文件與 GitHub 版本控管。

後續工作將依序完成 Django 可執行環境、Camera 串流、AIModel 資料庫、Event API 與 Dashboard 整合。
