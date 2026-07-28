# KRTC v3 事件紀錄功能 v1

## 功能

- `/dashboard/records/` 事件紀錄列表
- 查詢條件：開始時間、結束時間、事件類型、攝影機編號、區域、AI 模型、來源推論主機、關鍵字
- 顯示欄位：事件編號、發生時間、事件類型、攝影機編號、區域、處理狀態、AI 模型、來源推論主機、事件說明、快照
- 每頁 50 筆
- CSV 匯出（UTF-8 BOM）
- Excel `.xlsx` 匯出
- 本地 snapshot 優先，遠端 snapshot_url 備援

## 安裝

1. 將本 ZIP 解壓後的所有檔案複製到：

   `C:\Users\USER\krtc_notification_host_v3`

2. 在專案根目錄執行：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\apply_event_records_feature.ps1
python -m pip install -r requirements.txt
python manage.py check
python manage.py runserver
```

3. 開啟：

`http://127.0.0.1:8000/dashboard/records/`

## 匯出行為

匯出按鈕沿用畫面中的全部查詢條件。瀏覽器會下載到本機預設下載資料夾，或依瀏覽器設定顯示另存新檔視窗。

## 注意

- `apps/dashboard/urls.py` 會被本套件版本覆蓋。
- 安裝腳本只會修改三個既有模板中的「事件紀錄」導覽按鈕，並在 `requirements.txt` 加入 `openpyxl==3.1.5`。
- 腳本找不到預期舊內容時會停止，不會盲目覆寫模板。
