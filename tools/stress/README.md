# KRTC V6.8 Lab Multi-Stream Stress Harness

此工具僅供 Lab 使用。它不讀寫 Camera DB，不改動正式 `cam001`～`cam004` bridge，並只管理 `runtime/stress/stress_processes.json` 中具有相同 PID 與 process start time 的 stress FFmpeg。

## 前置條件

1. 使用 `config/mediamtx.lab.yml` 啟動既有 Lab MediaMTX。
2. Django 必須以 `DEBUG=True` 執行，並先在瀏覽器登入 superuser。
3. 設定 `KRTC_LAB_CAMERA_USERNAME` 與 `KRTC_LAB_CAMERA_PASSWORD`。
4. 確認四台來源均為 Native H.264。
5. 建議關閉與測試無關的 Edge/Chrome 視窗，避免 Browser process/RAM 指標混入其他工作負載。

## 30 分鐘 SOP

正式測試前先執行 Collector smoke：

```powershell
.\tools\stress\Start_1_Minute_Collector_Smoke.ps1
```

Smoke 只驗證 Collector 可持續執行一分鐘、至少寫入五筆 sample、產生完整輸出並正常結束；不會啟動或停止 Camera、正式 bridge、MediaMTX 或 stress publisher。

在 PowerShell 執行：

```powershell
.\tools\stress\Start_30_Minute_Stress.ps1
```

腳本會啟動 9 條 copy publisher、開啟自動 layout 頁面、啟動每 30 秒 metrics 收集，5 分鐘後擴充至 16 條 publisher，最後進行 layout switching 與 16-grid soak。

每次執行會在 `stress_results/<run>/` 產生 `metrics.csv`、`summary.txt`、`collector.stdout.log`、`collector.stderr.log`、`collector.pid` 與 `run_metadata.json`。自動summary涵蓋 paths、sessions、readers、process與記憶體成長；persistent black screen、Browser畫面凍結與AIO freeze必須由操作人員同步目視確認，工具不使用OCR或自動refresh掩蓋問題。

## 手動模式

```powershell
.\tools\stress\Start_9_Stream_Stress.ps1
.\tools\stress\Start_16_Stream_Stress.ps1
```

Lab頁面：`/dashboard/lab/media-stress/`

## 停止 SOP

```powershell
.\tools\stress\Stop_Stress.ps1
```

Stop腳本只會停止由 harness 記錄且 start time 相符的 stress FFmpeg。它不停止正式 bridge、Django 或 MediaMTX，也不刪除 `stress_results/`。
