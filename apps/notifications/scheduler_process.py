import json
import os
import socket
import tempfile
from datetime import datetime, timezone
from pathlib import Path


class SchedulerAlreadyRunning(RuntimeError):
    pass


class SchedulerProcessLock:
    """Hold a non-blocking, cross-process lock for one scheduler instance."""

    def __init__(self, path):
        self.path = Path(path)
        self._handle = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                if handle.tell() == 0 and self.path.stat().st_size == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            handle.close()
            raise SchedulerAlreadyRunning(
                f"Another broadcast scheduler owns lock: {self.path}"
            ) from exc

        self._handle = handle
        return self

    def release(self):
        if self._handle is None:
            return
        try:
            self._handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, exc_type, exc_value, traceback):
        self.release()


def utc_now_text():
    return datetime.now(timezone.utc).isoformat()


def scheduler_identity():
    return {
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
    }


def write_scheduler_status(path, **values):
    """Atomically replace the scheduler health JSON file."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **scheduler_identity(),
        "updated_at": utc_now_text(),
        **values,
    }
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            json.dump(payload, temp_file, ensure_ascii=False, indent=2)
            temp_file.write("\n")
            temp_path = Path(temp_file.name)
        temp_path.replace(target)
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()
    return payload
