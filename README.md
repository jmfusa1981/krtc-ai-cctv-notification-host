# KRTC AI CCTV Notification Host

本專案為 KRTC AI CCTV 通報主機系統之 Django 版本。前期已完成 PoC 與 MVP 測試，包含 Dashboard UI、Flask + OpenCV 影像串流，以及 IP Camera RTSP 接入。後續系統改採 Django 架構，以利整合資料庫、API、AI 模型、事件紀錄、通報流程與正式部署。

## Current Status

目前已完成或規劃中的功能：

- Dashboard UI 架構
- 1 / 4 / 9 / 16 分割攝影機畫面
- IP Camera RTSP 串流接入規劃
- Camera 資料庫管理
- AI 模型資料庫管理
- AI 偵測事件接收 API
- 事件紀錄查詢
- 通報流程設計
- 系統設定模組

## System Architecture

主要 Django Apps：

```text
apps/
├─ accounts/        使用者、角色與權限
├─ dashboard/       通報主機主畫面
├─ cameras/         IP Camera 管理與串流
├─ events/          AI 事件與事件處理流程
├─ ai_bridge/       AI 模型與 API 串接
├─ notifications/   通報紀錄
├─ records/         歷史紀錄查詢
└─ settings_app/    系統設定


##Main Flow
IP Camera
   ↓
Camera Stream Service
   ↓
Django Backend
   ↓
AI Bridge
   ↓
AI Detection Result
   ↓
Event Database
   ↓
Dashboard Notification
   ↓
Operator Confirmation / Notification / Close