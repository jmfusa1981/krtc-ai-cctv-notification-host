# KRTC Notification Host V4(10) Integrated Repair V1

- Combines PAO-OCC Phase 1, Phase 2, and Inference Contract v1 prerequisites.
- Restores `OccSyncState` and `OccSyncLog` models and migrations.
- Preserves `LocalAlarmPolicy` as `events.0005_localalarmpolicy`.
- Moves the inference contract event schema migration to `events.0006_eventupdatelog_and_contract_v1`.
- Removes the obsolete conflicting migration only after confirming it was never applied.
- Makes every Django validation command fail-fast by checking its process exit code.
- Does not overwrite `.env`, database files, UI assets, Speaker configuration, or audio files.
