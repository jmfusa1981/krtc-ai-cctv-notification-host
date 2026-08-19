# PAO → OCC Heartbeat 1.0 收斂更新

- 將 Heartbeat 改為 OCC `schema_version: "1.0"` 合約。
- 使用 `host_status` 與巢狀 `host`，包含主機名稱、IP、作業系統與應用版本。
- 新增資料庫持久化 `heartbeat_sequence`；只有 OCC 接受或判定 duplicate 後才遞增。
- 加入正確的 `Idempotency-Key: {notification_host_code}-{sequence}`。
- OCC 回傳 400 時保存經過敏感資料遮罩的回應本文。
- Heartbeat 路徑修正為 `/api/v1/heartbeat/`。
- 本測試站預設通報主機 IP 為 `192.168.6.25`，可由 `KRTC_NOTIFICATION_HOST_IP` 覆寫。
- 安裝程序不會送出 Heartbeat，亦不會啟動週期同步。

安裝與測試完成後，第一次實機驗證由操作人員明確執行：

```powershell
python manage.py sync_occ_once --kind heartbeat --force
```

預期 OCC 新資料回傳 `201 Created / accepted`；若 OCC 已接收相同序號，則回傳 `200 OK / duplicate`，兩者均視為成功。
