# SEC-01 — HTTPS／登入傳輸安全部署指南

## 1. Architecture

正式與 Lab 的唯一對外 Web 入口如下：

```text
Browser
  │
  │ HTTPS :443
  ▼
Caddy TLS Reverse Proxy
  │
  │ HTTP（僅限 loopback）
  ▼
Waitress 127.0.0.1:8000
  │
  ▼
Django
```

`KRTCNotificationHost` 服務仍以 WinSW 啟動 Django／Waitress，但
`service/start_notification_host.cmd` 的安全預設已改為
`127.0.0.1:8000`。啟動腳本只接受 `127.0.0.1` 或 `localhost`，避免把
port 8000 意外重新公開到 LAN。

`KRTCNotificationProxy` 是獨立的 Caddy WinSW 服務。Caddy 對外監聽
port 443，並由 Automatic HTTPS 在 port 80 提供 HTTP→HTTPS 轉址；上游固定為
`http://127.0.0.1:8000`。Caddy 會設定並覆寫 `X-Forwarded-Proto`，Django
則透過 `SECURE_PROXY_SSL_HEADER` 辨識原始 HTTPS request。

## 2. Lab setup

### 2.1 檔案配置

1. 從 Caddy 官方下載未加商業 plugin 的 Windows amd64 binary。
2. 將 binary 放在
   `C:\KRTC\NotificationHost\caddy\caddy.exe`。`caddy.exe` 不提交 Git。
3. 將 `service/Caddyfile`、`service/start_caddy.cmd` 與
   `service/KRTCNotificationProxy.xml` 複製到正式安裝目錄的 `service`。
4. 在 `C:\KRTC\NotificationHost\config\https_site.txt` 寫入一行 Lab URL，
   例如 `https://192.0.2.10` 或 `https://pao-rxx.example.internal`。此檔為現場
   runtime config，不提交 Git。也可由服務環境變數 `KRTC_TLS_SITE` 提供相同值。
5. 在 `C:\KRTC\NotificationHost\config\.env` 設定：

```dotenv
KRTC_ENABLE_HTTPS=True
DJANGO_SECURE_HSTS_SECONDS=0
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost,192.0.2.10
DJANGO_CSRF_TRUSTED_ORIGINS=https://192.0.2.10
DJANGO_CORS_ALLOWED_ORIGINS=https://192.0.2.10
```

IP／hostname 必須替換為現場值，不可照抄範例保留位址。若同時支援 IP 與
hostname，`DJANGO_ALLOWED_HOSTS` 與 `DJANGO_CSRF_TRUSTED_ORIGINS` 應分別加入
兩者；CSRF origin 必須包含 `https://` scheme，非標準 port 時也必須包含 port。

### 2.2 Validate、啟動與停止

開發／Lab 前景執行可使用：

```powershell
.\tools\CADDY_LAB.ps1 -Action Validate `
  -Site https://<Lab-AIO-IP> `
  -PersistentRoot C:\KRTC\NotificationHost

.\tools\CADDY_LAB.ps1 -Action Run `
  -Site https://<Lab-AIO-IP> `
  -PersistentRoot C:\KRTC\NotificationHost
```

另一個系統管理員 PowerShell 可執行：

```powershell
.\tools\CADDY_LAB.ps1 -Action Stop
```

Windows Service 整合沿用專案既有 WinSW 模式：將一份 WinSW v2 wrapper 命名為
`KRTCNotificationProxy.exe`，與 `KRTCNotificationProxy.xml` 放在同一目錄後執行：

```powershell
C:\KRTC\NotificationHost\service\KRTCNotificationProxy.exe install
C:\KRTC\NotificationHost\service\KRTCNotificationProxy.exe start
```

停止與移除：

```powershell
C:\KRTC\NotificationHost\service\KRTCNotificationProxy.exe stop
C:\KRTC\NotificationHost\service\KRTCNotificationProxy.exe uninstall
```

先啟動 `KRTCNotificationHost`，再啟動 `KRTCNotificationProxy`。設定變更後可用
`CADDY_LAB.ps1 -Action Reload` 進行 graceful reload。

### 2.3 Internal CA 信任

Lab 的 `tls internal` 會在 Caddy data directory 建立本機 CA 與 private key。
本專案把 data directory 固定至
`C:\KRTC\NotificationHost\caddy\data\caddy`；它是持久化安全資料，不是 cache，
不得提交 Git、任意刪除或複製到不受控位置。

執行 Caddy 的 Windows service account 可能無法自動修改用戶端 trust store。
應由管理員以受控方式匯出／派送 root CA，或在同一 service identity 與 data
directory 下執行 `CADDY_LAB.ps1 -Action Trust`。每台瀏覽器端都必須信任該 Lab
root CA，否則會出現 certificate warning；不得用「忽略憑證錯誤」當作驗收通過。

Access log：`C:\KRTC\NotificationHost\logs\caddy\access.log`。
WinSW process log：`C:\KRTC\NotificationHost\logs\caddy`。

## 3. Production／MIS certificate requirement

正式上線前由高捷 MIS 決定：

- 正式 hostname／AIO IP 與 certificate SAN；
- Internal CA chain、憑證有效期與更新責任；
- private key 的產生、ACL、備份與輪替方式；
- 是否由 MIS 提供 PEM certificate/key，或讓 Caddy 對 Internal ACME／PKI 申請；
- 用戶端 trust store 的派送方式；
- port 80 是否允許只作 HTTPS redirect。

若 MIS 提供 PEM 憑證，將 Caddyfile 的 `tls internal` 替換為指向安裝目錄外受控
runtime path 的 `tls <certificate-file> <private-key-file>`。private key、PFX/P12、
password 與憑證 runtime 檔案禁止進 Git；亦禁止把憑證 password 放在 command-line
argument 或 Installer log。

正式憑證、hostname 與 MIS 驗證完成前，保持
`DJANGO_SECURE_HSTS_SECONDS=0`。HSTS 提升必須是另一個經核准的部署步驟，避免
錯誤憑證或 hostname 尚未穩定時造成瀏覽器長期鎖定。

## 4. Firewall ports

- LAN inbound TCP 443：允許 Browser→Caddy。
- LAN inbound TCP 80：只有需要 HTTP→HTTPS redirect 時才允許。
- LAN inbound TCP 8000：明確封鎖，作為 loopback bind 之外的 defense in depth。
- TCP 2019：Caddy admin API 只綁 `127.0.0.1`，不得開放 LAN。

`Get-NetTCPConnection -LocalPort 8000` 的 LocalAddress 必須為 `127.0.0.1`，不得為
`0.0.0.0`、`::` 或任何 LAN address。

## 5. Waitress localhost requirement

Production 啟動腳本的預設值：

```text
KRTC_WEB_BIND_HOST=127.0.0.1
KRTC_WEB_BIND_PORT=8000
```

這兩個值是 WinSW process environment，不是 Django `.env` 設定。即使部署工具
覆寫它們，腳本也只接受 loopback hostname/address。port 可因測試需求調整，但若
變更 port，必須同步調整 Caddy upstream，且 Production 最終值仍應為 8000。

`tools/AIO_START.ps1 -Lan` 是舊有開發／SIT 工具，不屬於 Production chain，禁止
用它替代 `KRTCNotificationHost` 正式服務。

## 6. Caddy／reverse proxy setup

Lab Caddyfile 使用免費開源 Caddy：

```caddyfile
{$KRTC_TLS_SITE:https://localhost} {
    tls internal
    reverse_proxy 127.0.0.1:8000
}
```

Caddy Automatic HTTPS 會為明確 HTTPS site 建立 port 80 redirect。後端 upstream
不啟用 TLS，因其流量只在 localhost。Caddy admin API 固定綁 `127.0.0.1:2019`。

官方參考：

- <https://caddyserver.com/docs/caddyfile/directives/tls>
- <https://caddyserver.com/docs/running#windows-service>
- <https://caddyserver.com/docs/conventions#file-locations>

## 7. Django secure settings

`KRTC_ENABLE_HTTPS=False` 保留既有 development／HTTP regression flow：不強迫
redirect，secure cookies 為 False。

`KRTC_ENABLE_HTTPS=True` 啟用：

- `SECURE_SSL_REDIRECT=True`
- `SESSION_COOKIE_SECURE=True`
- `CSRF_COOKIE_SECURE=True`
- `SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https")`
- `SESSION_COOKIE_HTTPONLY=True`
- `SESSION_COOKIE_SAMESITE="Lax"`
- `SECURE_CONTENT_TYPE_NOSNIFF=True`
- `X_FRAME_OPTIONS="DENY"`
- `SECURE_HSTS_SECONDS=0`（Lab 預設）

因 Django 信任 proxy header，Waitress 必須維持 loopback-only；不可在 LAN 上公開
backend。Caddy 會覆寫 forwarded headers，避免直接沿用不可信 client 值。

## 8. Lab validation 與 Wireshark

### Test 1 — Waitress bind

```powershell
Get-NetTCPConnection -State Listen -LocalPort 8000 |
    Format-Table LocalAddress,LocalPort,OwningProcess
```

預期只有 `127.0.0.1:8000`。

### Test 2 — 本機 backend

`KRTC_ENABLE_HTTPS=False` 的獨立 backend smoke test：

```powershell
curl.exe -I http://127.0.0.1:8000/login/
```

`KRTC_ENABLE_HTTPS=True` 時，直接 HTTP request 會被 Django redirect；這是正常安全
行為。此時應以 Caddy HTTPS URL 做功能驗證，不應把 port 8000 當 Browser 入口。

### Test 3／4／5 — HTTPS 與角色政策

```powershell
curl.exe -I https://<Lab-AIO-IP>/login/
```

在已信任 Lab CA 的瀏覽器驗證：

- `admin` HTTPS login→Dashboard PASS；`/admin/` 仍為 404 forbidden。
- `skynet` HTTPS login→Dashboard PASS。
- `KRTC_SUPERUSER_USB_REQUIRED=False` 的 Lab，`skynet /admin/` 仍依既有政策可用。

本任務不得改動 admin／skynet role model 或 USB gate；若結果不同，應視為既有功能
regression，而不是改 policy 遷就 HTTPS。

### Test 6 — HTTP redirect

```powershell
curl.exe -I http://<Lab-AIO-IP>/
```

預期 `308`（或部署核准的 redirect status）與 HTTPS Location。

### Test 7 — LAN bypass

從另一台電腦執行：

```powershell
Test-NetConnection <Lab-AIO-IP> -Port 8000
curl.exe --connect-timeout 5 http://<Lab-AIO-IP>:8000/login/
```

TCP connection 與 HTTP login 都必須失敗。

### Test 8 — Packet capture

在另一台有合法維運權限的測試主機擷取 Browser↔AIO 流量，Wireshark display filter：

```text
ip.addr == <Lab-AIO-IP> && (tcp.port == 443 || tcp.port == 80 || tcp.port == 8000)
```

執行一次 HTTPS login 後：

1. port 443 應呈現 TLS handshake 與 encrypted application data。
2. `Edit → Find Packet → Packet bytes → String` 搜尋 `username=admin`、`password=`
   與 `KRTC_DEFAULT_ADMIN_PASSWORD`，不得找到明文。
3. LAN 上不得出現 port 8000 login flow。
4. Browser F12 DevTools 顯示該使用者自己輸入的 form values 是端點本機行為，不是
   網路封包洩漏，不視為 failure。

## 9. Rollback

1. 停止 `KRTCNotificationProxy`。
2. 將 Django runtime config 的 `KRTC_ENABLE_HTTPS=False`，重啟
   `KRTCNotificationHost`，即可恢復本機 HTTP regression 測試。
3. Waitress 仍保持 `127.0.0.1:8000`；rollback 不得恢復 `0.0.0.0:8000`。
4. 不刪除 Caddy data directory；其中包含 Lab CA private key 與 certificate state。
5. 若需退回舊版檔案，使用已核准 release／Git commit 做精準 rollback，不可清除
   未提交的 Account Bootstrap 或 `system_header` 工作。

## 10. Installer integration notes

V6.8 Installer 後續必須收集／決定：

| 輸入 | 規則 |
|---|---|
| AIO Host/IP | 寫入 Allowed Hosts、CSRF origins 與 `https_site.txt` |
| HTTPS enable | Lab／Production 應為 True；development 可為 False |
| TLS certificate source | Caddy internal CA、MIS PEM 或未來 Internal ACME |
| Internal CA／certificate mode | 決定 trust distribution、renewal 與 key ACL |
| admin initial password | username 固定 `admin`；只接受安全輸入，不印 log |
| skynet initial password | username 固定 `skynet`；只接受安全輸入，不印 log |

Installer 還必須：

- 安裝／更新兩個 WinSW service，並在啟動前執行 `caddy validate`；
- 建立 `logs\caddy`、`caddy\data`、`caddy\config` 並套用最小 service-account ACL；
- 建立 Windows Firewall 規則：allow 80/443、deny 8000 inbound；
- 不把 password 放進 command-line argument，不在 console／Installer log 輸出；
- 不把 TLS private key、PFX/P12 password 或 Django secret 寫入 source tree；
- update 時保留 Caddy PKI data、Django database、runtime config 與 logs；
- 完成本文 Test 1–8 後才標示 SEC-01 LAB PASS。
