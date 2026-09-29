# KRTC V5 Inference WebSocket Autostart V1

- Starts the multi-host inference WebSocket listener with the Django server.
- Keeps the standalone `run_inference_listener` command for diagnostics only.
- Prevents duplicate startup under the Django development autoreloader.
- Skips autostart for migrations, tests, shell, checks, polling CLI, and listener CLI.
- Detects enabled, disabled, deleted, and changed inference-host records every 30 seconds.
- Uses each active host's database `websocket_url`, with `/ws/alerts` as the fallback.
- Keeps automatic reconnect behavior from `InferenceWebSocketReceiver.run_forever()`.
- Adds an environment switch: `INFERENCE_WS_AUTOSTART=False`.
