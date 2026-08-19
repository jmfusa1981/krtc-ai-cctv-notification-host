# KRTC PAO Notification Host V5

V5 implements the approved physical inference-host contract for
`INF-KRTC-ST-001-01` at `192.168.6.20:8000`.

## Upgrade

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py configure_v5_inference_host
python manage.py check
python manage.py test apps.ai_bridge.tests.test_v5_listener
```

Run Django and the listener as two independent processes:

```powershell
python manage.py runserver 0.0.0.0:8000
python manage.py run_inference_listener --host-code INF-KRTC-ST-001-01
```

The listener connects directly to `/ws/alerts` without token, envelope, or ACK.
REST recovery uses `/api/notify/events` with `since`, `until`, `limit`, and `offset`.

## Acceptance boundary

Automated tests cover schema normalization, exact source IDs, unmapped-event
storage, bbox/ROI persistence, fire-event suppression, and WebSocket/REST
deduplication. P-01 through P-04 and P-12 through P-15 require the actual PAO,
inference host, OCC, and network and must be recorded during field testing.
