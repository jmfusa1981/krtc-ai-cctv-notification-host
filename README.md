# KRTC AI CCTV Notification Host

高雄捷運（KRTC）AI CCTV 智慧影像辨識系統之 **PAO 通報主機（Notification Host）**。

本系統以 Django 為主要 Web Application Framework，部署於各站區通報主機，負責接收 AI 推論主機事件、顯示即時事件、管理 CCTV / IP Speaker、執行站區廣播、保存事件紀錄與安全稽核資訊，並透過站端 API 與 OCC 中央維護主機進行資料整合。

目前專案已由早期 PoC / MVP 階段進入 **V6 功能收斂、系統安全強化、OCC 整合與工程現場 SIT 測試階段**。

---

## Current Development Status

目前主要開發分支：

```text
feature/v6-ui-security
```

V6 Field Test Ready Checkpoint：

```text
Commit:
98101ed34525d01f3828ca74be2ad86ff43061b0

Backup Tag:
v6-backup-20260825_173012
```

目前系統主要功能已完成基礎收斂，後續工作以：

```text
Inference Host Integration
→ PAO Station Integration
→ OCC Maintenance Host Integration
→ Field Installation
→ SIT
→ Defect Convergence
→ Acceptance
```

為主要方向。

---

## 1. System Architecture

```text
AI Inference Host
        │
        │ REST API / WebSocket
        ▼
PAO Notification Host
        │
        │ REST API / Cursor Pull
        ▼
OCC Maintenance Host
```

### AI Inference Host
- AI 模型推論
- CCTV AI 事件辨識
- Event API / Snapshot
- Camera Status / Health
- Zone Count / 人流資訊
- WebSocket Alert

### PAO Notification Host
- 接收 AI Event
- 即時事件顯示
- Event Snapshot / Event Records
- 即時監視牆
- IP Camera / Inference Host / IP Speaker 管理
- 自動 / 手動廣播
- Zone Count / 區域人流
- Device Health / System Log
- Security Audit
- User / Role Management
- Superuser USB Security
- OCC Read-only API
- Station-side Event Recording 管理

### OCC Maintenance Host
- 各站 PAO 狀態集中監控
- Device Fault / System Log / Security Audit 集中管理
- Station Heartbeat
- Cursor-based Synchronization
- 多站設備與事件整合
- 中央維護與管理

---

## 2. Technology Stack

```text
Backend
├─ Python
├─ Django
├─ SQLite
└─ REST API

Frontend
├─ HTML
├─ CSS
└─ JavaScript

Video / CCTV
├─ RTSP
├─ MJPEG
└─ OpenCV / Stream Service

Integration
├─ HTTP REST API
├─ WebSocket
├─ JSON
└─ Bearer Token

Deployment
├─ Windows
├─ Python Virtual Environment
├─ Waitress
├─ WhiteNoise
└─ Windows Service / WinSW
```

主要開發環境：

```text
Windows
Python 3.12+
Django 5.2.x
SQLite
VS Code
PowerShell
```

---

## 3. Django Apps

```text
apps/
├─ accounts/       Authentication / RBAC / Superuser USB Security
├─ dashboard/      Dashboard / Monitor / Records / Snapshots / System Log
├─ cameras/        IP Camera / RTSP / Stream Pool
├─ events/         AI Event / Event Lifecycle / Zone Count
├─ ai_bridge/      Inference API / Polling / Zone Count Integration
├─ notifications/  IP Speaker / Broadcast Rule / Scheduler / Speaker Health
├─ settings_app/   Station / Camera / Speaker / Host / User / UI Settings
└─ station_api/    OCC API / Device Fault / Audit / Watchdog / Sync
```

---

## 4. Main Event Flow

```text
IP Camera
   │
   ▼
AI Inference Host
   │
   ▼
Inference Event API / WebSocket
   │
   ▼
PAO AI Bridge
   │
   ▼
Event Database
   │
   ├─ Event Snapshot
   ├─ Dashboard Alert
   ├─ Broadcast Rule
   ├─ IP Speaker
   └─ System / Audit Record
             │
             ▼
      OCC Maintenance Host
```

---

## 5. Dashboard & Monitor Wall

Dashboard 主要顯示：

```text
Station Information
Camera Status
Speaker Status
Inference Host Status
Zone Count
Pending AI Events
Event Snapshot
Event Handling
Broadcast Status
System Time
Current User / Role
```

Monitor Wall 支援 `1 / 4 / 9 / 16` 分割畫面，包含 RTSP / MJPEG stream、Camera status、Reconnect、Shared backend stream pool 與短暫 stream retention。

---

## 6. AI Inference Host Integration

主要串接資料：

```text
AI Event
Camera Status
Inference Health
Zone Count
Snapshot
WebSocket Alert
```

Zone Count API：

```text
GET /api/notify/zone_counts
```

主要欄位：

```text
camera_id
station
roi_id
count
threshold
updated_at
```

PAO 以 `station + roi_id` 作為 grouping key；相同 Zone 多 Camera 回報時：

```text
count = SUM(camera count)
threshold = MAX(threshold)
updated_at = newest timestamp
```

---

## 7. Device Management

### IP Camera
Camera Code / Name / IP / RTSP URL / Status / Stream Test / Delete

### Inference Host
Host Code / Name / IP / Base URL / Health / Configuration URL / Host Settings / Delete

### IP Speaker
Speaker Code / Name / IP / SIP URI / Deployment State / Health / Delete

---

## 8. Station Broadcast System

```text
Manual Broadcast
Automatic Broadcast
Broadcast Rule
Multiple Speakers
Audio Mapping
Broadcast Scheduler
Broadcast Log
Speaker Health
```

---

## 9. Event Records & Snapshot

Event Records 主要欄位：

```text
Event ID
Event Time
Event Type
Camera
Zone
Status
Inference Host
Snapshot
Recording
```

支援條件查詢與 CSV / Excel 匯出。

Snapshot 架構：

```text
Inference Snapshot
        │
        ▼
PAO Local Storage
        │
        ├─ Dashboard
        └─ Snapshot Search
```

---

## 10. Event Recording

PAO 為每筆 AI Event 事件錄影之站端正式存放 / 播放主機。

```text
AI Event
   │
   ▼
Immediate Event Handling
   │
   ▼
EventRecordingJob
   │
   ▼
Wait for NVR recording
   │
   ▼
Delayed NVR Retrieval
   │
   ▼
Local MP4
   │
   ├─ PAO Playback
   └─ OCC / External Query
```

事件通知與錄影 Retrieval 採分離式設計。

---

## 11. System Log

```text
DeviceFaultLog
DeviceFaultChange
```

DeviceFaultChange 採 Append-only 設計。

Change Type：

```text
created
refreshed
recovered
```

---

## 12. Security Audit

V6.5 Security Audit Foundation：

```text
LOGIN_SUCCESS
LOGIN_FAILED
LOGOUT
USB_VERIFY_SUCCESS
USB_VERIFY_FAILED
USB_KEY_REGISTERED
USB_KEY_REGISTER_FAILED
USB_KEY_DISABLED
USER_CREATED
USER_UPDATED
USER_ENABLED
USER_DISABLED
STATION_SETTINGS_UPDATED
```

禁止保存：

```text
Password
USB Token
Bearer Token
Authorization Header
Session Secret
```

---

## 13. Role-Based Access Control

| Function | Operator | Maintainer | Administrator | Superuser |
|---|---:|---:|---:|---:|
| Dashboard | ✓ | ✓ | ✓ | ✓ |
| Event Records | ✓ | ✓ | ✓ | ✓ |
| Monitor Wall | ✓ | ✓ | ✓ | ✓ |
| Device Settings | Limited | ✓ | ✓ | ✓ |
| System Log | ✕ | ✓ | ✓ | ✓ |
| Security Audit | ✕ | ✕ | ✓ | ✓ |
| User Management | ✕ | ✕ | ✓ | ✓ |
| Django Admin | ✕ | ✕ | ✕ | ✓ |

Backend 同步執行權限驗證，不只依靠 UI 隱藏。

---

## 14. Superuser USB Security

```text
Username / Password
        +
Trusted USB Key
        │
        ▼
Django Admin
```

USB Key 不保存 Password，以 Token Hash 驗證；USB Key 檔案不得提交 Git。

---

## 15. PAO ↔ OCC Integration

Machine-to-machine Authentication：

```http
Authorization: Bearer <KRTC_OCC_API_TOKEN>
```

Device Fault Change Feed：

```http
GET /api/v1/device-fault-changes/?since_id=0&limit=200
```

Security Audit Change Feed：

```http
GET /api/v1/audit-log-changes/?since_id=0&limit=200
```

OCC 每站保存獨立 Cursor；Station Offline 時不推進 cursor，恢復後從原 cursor 繼續。

---

## 16. PAO Service Watchdog

PAO 可監控自身 Runtime Service；若整台 PAO Host 完全停止，必須由 OCC 透過 `Heartbeat Timeout` 判斷主機離線。

---

## 17. Development Startup

```powershell
cd C:\Users\USER\krtc_notification_host_v6

Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\venv\Scripts\Activate.ps1

python manage.py check
python manage.py migrate
python manage.py runserver 127.0.0.1:8010
```

Dashboard：

```text
http://127.0.0.1:8010/dashboard/
```

Django Admin：

```text
http://127.0.0.1:8010/admin/
```

---

## 18. Validation Commands

```powershell
python manage.py check
python manage.py migrate --check
python manage.py makemigrations --check --dry-run
```

---

## 19. Source Repository Security

禁止提交：

```text
.env
db.sqlite3
*.key
media/
staticfiles/
runtime/
logs/
venv/
_update_backups/
backups/
```

---

## 20. Backup Strategy

```text
1. GitHub Source Repository
2. Portable Source ZIP
3. Complete Git Bundle
```

Git Bundle 保存 Commit History、Branches、Tags 與 Repository History，並搭配 SHA256 驗證完整性。

---

## 21. Field Deployment

目前 V6 已進入工程現場測試準備階段。

進場前確認：

```text
PAO IP / Port
OCC IP / Port
Inference Host IP / Port
Camera RTSP
Speaker IP / SIP
Station Code
Station Name
Firewall Rules
API Endpoint
OCC Machine Token
NTP
VLAN / Gateway
Test Account
SIT Test Case
Expected Result
```

---

## 22. Project Phase

```text
PoC
  ↓
MVP
  ↓
V2 / V3
  ↓
V4
  ↓
V5
  ↓
V6
  ↓
Functional Convergence
  ↓
Security Hardening
  ↓
OCC Integration
  ↓
Field Installation      ← CURRENT
  ↓
SIT
  ↓
Acceptance Convergence
```

---

## Status

**KRTC AI CCTV Notification Host V6**

```text
Core Feature Development     : Substantially Complete
UI / UX Convergence          : Final Stage
RBAC                         : Implemented
Superuser USB Security       : Implemented
Inference Integration        : Implemented / SIT Pending
Zone Count Integration       : Implemented
Device Fault Framework       : Implemented
System Log                   : Implemented
Security Audit               : Foundation Implemented
OCC Log Integration API      : Foundation Implemented
Event Recording / NVR        : Next Integration Stage
Field Deployment             : Ready for Preparation
SIT                          : Pending
Final Acceptance             : Pending
```
