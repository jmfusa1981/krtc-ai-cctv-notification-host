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