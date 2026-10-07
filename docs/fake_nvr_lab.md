# Fake NVR Lab 操作說明

此工具只供開發 Lab 驗證，不得用於正式環境。伺服器只允許綁定 loopback，且在 `DEBUG=False` 或 `KRTC_PRODUCTION=True` 時拒絕啟動。

## 啟動 Fake NVR

使用第一個終端機：

```powershell
python manage.py run_fake_nvr --port 18080 --delay-seconds 5 --username lab --password lab
```

啟動後提供：

- `GET /cam_list.cgi`
- `GET /export.cgi?channel=...&start_time=...&end_time=...&format=MP4`
- `GET /export.cgi?ID=...`
- `GET /export.cgi?ID=...&action=download`

## 預覽 Lab Camera 映射

預設為 dry-run，不修改資料庫：

```powershell
python manage.py configure_fake_nvr_lab --camera-code CAM-001
```

確認輸出正確後，才可明確套用：

```powershell
python manage.py configure_fake_nvr_lab --camera-code CAM-001 --apply --confirm FAKE-NVR-LAB
```

預設映射：

| Camera | 原攝影機 IP | Fake NVR channel |
|---|---:|---:|
| CAM-001 | 192.168.6.93 | 1 |
| CAM-002 | 192.168.6.90 | 2 |
| CAM-003 | 192.168.6.94 | 3 |
| CAM-004 | 192.168.6.92 | 4 |

套用命令只在使用者提供 `--apply --confirm FAKE-NVR-LAB` 時更新 Camera 的 NVR 欄位，不會自動覆寫資料。

## PAO Lab 設定

在第二個終端機暫時設定：

```powershell
$env:KRTC_NVR_RECORDING_MODE = "nvr"
$env:KRTC_NVR_POLL_INTERVAL_SECONDS = "2"
python manage.py run_event_recording_service
```

正式環境的預設輪詢仍是 60 秒；上述 2 秒只適用 Lab。

## MP4 fixture

Fake server 內嵌一個 1545-byte、16x16、0.2 秒的 H.264 MP4。檔案含有效 `ftyp`、`moov` 與 `mdat` box，不需要網路或本機 ffmpeg。

需要重新產生相同類型 fixture 時，可選擇執行：

```powershell
ffmpeg -f lavfi -i "color=c=black:s=16x16:d=0.2:r=5" -an -c:v libx264 -pix_fmt yuv420p -movflags +faststart fake_nvr.mp4
```

此重新產生命令不是 Fake NVR 的執行依賴。
