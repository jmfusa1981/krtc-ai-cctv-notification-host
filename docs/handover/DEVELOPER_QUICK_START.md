# Developer Quick Start

## 1. Clone
```powershell
cd C:\Users\<USER>
git clone https://github.com/jmfusa1981/krtc-ai-cctv-notification-host.git krtc_notification_host_v6
cd .\krtc_notification_host_v6
git fetch --all --tags
git checkout v6.6.5.3-handover-20260827
```

For continued development, create a branch from the handover baseline:
```powershell
git checkout -b feature/<developer>-v6-followup
```

## 2. Python environment
```powershell
python -m venv venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 3. Local environment file
```powershell
Copy-Item .env.example .env
```
Edit `.env` locally. Do not commit it. Obtain authorized secrets through a separate secure channel.

## 4. Database
```powershell
python manage.py check
python manage.py migrate
python manage.py makemigrations --check --dry-run
```

## 5. Start development server
```powershell
python manage.py runserver 0.0.0.0:8010
```
Open `http://127.0.0.1:8010/dashboard/`.

## 6. Optional integration processes
Use only when testing the corresponding functions:
```powershell
python manage.py poll_inference_hosts
python manage.py run_broadcast_scheduler
python manage.py run_occ_sync_service
```

## 7. Before every commit
```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
git status
git diff
```
Never stage secrets/runtime data.
