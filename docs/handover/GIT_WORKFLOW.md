# Git Handover Workflow

## Repository
`https://github.com/jmfusa1981/krtc-ai-cctv-notification-host.git`

## Handover baseline
Use tag `v6.6.5.3-handover-20260827` after the current developer completes the backup/sync script.

## Recommended student workflow
```powershell
git clone https://github.com/jmfusa1981/krtc-ai-cctv-notification-host.git krtc_notification_host_v6
cd krtc_notification_host_v6
git fetch --all --tags
git checkout v6.6.5.3-handover-20260827
git checkout -b feature/<developer>-v6-followup
```

Daily:
```powershell
git status
python manage.py check
python manage.py makemigrations --check --dry-run
git add <explicit files>
git commit -m "type: concise scope"
git push -u origin HEAD
```

Prefer explicit `git add <file>` during normal development. Avoid blind staging of runtime directories.

## Commit prefixes
- `feat:` new function
- `fix:` bug correction
- `ui:` UI/UX-only change
- `refactor:` structural change without intended behavior change
- `test:` tests
- `docs:` documentation
- `chore:` packaging/tooling/release maintenance
