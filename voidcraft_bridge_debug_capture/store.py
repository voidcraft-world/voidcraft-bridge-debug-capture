"""Bounded, atomically written captures. Only recognized capture files belong to this store."""
from __future__ import annotations

import json
import os
import re
import secrets
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

DEFAULT_DIRECTORY = Path.home() / ".local" / "state" / "voidcraft-world-bridge" / "debug-capture"

#: How many captures survive. A capture is a few KB, so this is about keeping the
#: directory readable by a human running `ls`, not about disk.
DEFAULT_KEEP = 25

SUFFIX = ".json"

#: Epoch-millisecond prefix, zero-padded to a fixed width so a plain lexical sort
#: of the filenames IS chronological order. 13 digits covers every date until the
#: year 2286; the pad keeps that true if the clock is ever set to something absurd.
STAMP_WIDTH = 13
CAPTURE_NAME = re.compile(r"[0-9]{13,}-[a-zA-Z0-9_-]{1,64}\.json")
MAX_CAPTURE_BYTES = 4096


class CaptureStoreError(ValueError):
    """The payload is not something this store will persist."""


def capture_filename(stamp_ms: int, capture_id: str) -> str:
    return f"{stamp_ms:0{STAMP_WIDTH}d}-{capture_id}{SUFFIX}"


def atomic_write(path: Path, text: str) -> None:
    """Write via a temp file in the DESTINATION's directory, then os.replace.

    Atomic replacement keeps readers from observing partial JSON.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=str(path.parent), delete=False
    )
    try:
        with handle as stream:
            stream.write(text)
        os.replace(handle.name, path)
    except OSError:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise


class CaptureStore:
    def __init__(
        self,
        directory: str | os.PathLike | None = None,
        keep: int = DEFAULT_KEEP,
        now_fn: Callable[[], float] = time.time,
        id_fn: Callable[[], str] = lambda: secrets.token_hex(8),
        max_bytes: int = MAX_CAPTURE_BYTES,
        redact: Callable[[dict], dict] | None = None,
    ) -> None:
        self._directory = Path(directory) if directory is not None else DEFAULT_DIRECTORY
        self._keep = max(1, min(int(keep), 1000))
        self._max_bytes = max(1, min(int(max_bytes), 5 * 1024 * 1024))
        self._redact = redact
        self._now_fn = now_fn
        self._id_fn = id_fn
        self._lock = threading.Lock()

    @property
    def directory(self) -> Path:
        return self._directory

    # -- write --------------------------------------------------------------

    def save(self, payload: dict) -> dict:
        """Persist one capture and prune the ring. Returns its metadata."""
        if not isinstance(payload, dict):
            raise CaptureStoreError("capture must be a JSON object")
        if type(payload.get("version")) is not int:
            raise CaptureStoreError("capture must carry an integer 'version'")

        try:
            text = json.dumps(payload, allow_nan=False, separators=(",", ":"))
            if self._redact is not None:
                payload = self._redact(json.loads(text))
                if not isinstance(payload, dict) or type(payload.get("version")) is not int:
                    raise CaptureStoreError("redaction must return a versioned object")
                text = json.dumps(payload, allow_nan=False, separators=(",", ":"))
            if len(text.encode("utf-8")) > self._max_bytes:
                raise CaptureStoreError("capture exceeds byte budget")
            payload = json.loads(text)
        except (TypeError, ValueError, RecursionError) as error:
            raise CaptureStoreError("capture must be finite JSON within the byte budget") from error

        stamp_ms = int(self._now_fn() * 1000)
        capture_id = self._id_fn()
        name = capture_filename(stamp_ms, capture_id)
        if CAPTURE_NAME.fullmatch(name) is None:
            raise CaptureStoreError("invalid generated capture id")

        # The stored envelope adds only what the SERVER knows. The payload is
        # nested rather than merged so a future field in either half can never
        # silently shadow the other.
        record = {
            "version": 1,
            "id": Path(name).stem,
            "stored_at": stamp_ms,
            "kind": payload["kind"][:128] if isinstance(payload.get("kind"), str) else None,
            "capture": payload,
        }
        text = json.dumps(record, separators=(",", ":"))

        with self._lock:
            atomic_write(self._directory / name, text)
            pruned = self._prune_locked()

        return {"id": record["id"], "stored_at": stamp_ms, "bytes": len(text.encode("utf-8")), "pruned": pruned}

    def _prune_locked(self) -> int:
        files = self._files()
        excess = len(files) - self._keep
        if excess <= 0:
            return 0
        removed = 0
        for path in files[:excess]:
            try:
                path.unlink()
                removed += 1
            except OSError:
                # A file that vanished under us is the outcome we wanted anyway.
                pass
        return removed

    # -- read ---------------------------------------------------------------

    def _files(self) -> list[Path]:
        """Capture files, oldest first. A missing directory is empty, not an error."""
        try:
            entries = [p for p in self._directory.iterdir() if not p.is_symlink() and p.is_file() and CAPTURE_NAME.fullmatch(p.name)]
        except OSError:
            return []
        return sorted(entries, key=lambda p: p.name)

    def _read(self, path: Path) -> dict | None:
        try:
            with path.open("rb") as stream:
                data = stream.read(self._max_bytes + 1025)
            if len(data) > self._max_bytes + 1024:
                return None
            record = json.loads(data)
            if not isinstance(record, dict) or not isinstance(record.get("capture"), dict):
                return None
            return record
        except (OSError, ValueError):
            # Tolerant load, for independent readers: a corrupt file is
            # skipped rather than allowed to break the listing it appears in.
            return None

    def latest(self) -> dict | None:
        files = self._files()
        for path in reversed(files):
            record = self._read(path)
            if record is not None:
                return record
        return None

    def listing(self, limit: int = 10) -> list[dict]:
        """Newest-first index. Metadata only — bodies are fetched by id."""
        limit = max(1, min(int(limit), 100))
        rows: list[dict] = []
        for path in reversed(self._files()):
            record = self._read(path)
            if record is None:
                continue
            rows.append(
                {
                    "id": record.get("id"),
                    "stored_at": record.get("stored_at"),
                    "kind": record.get("kind"),
                    "bytes": path.stat().st_size if path.exists() else None,
                }
            )
            if len(rows) >= limit:
                break
        return rows

    def get(self, capture_id: str) -> dict | None:
        """One capture by id. The id is matched against the filename STEM rather
        than joined into a path, so no caller-supplied string ever reaches the
        filesystem — traversal is impossible by construction, not by check."""
        if not isinstance(capture_id, str) or not capture_id:
            return None
        for path in self._files():
            if path.stem == capture_id:
                return self._read(path)
        return None

    def state(self) -> dict:
        """Side-effect-free status, for `GET /state`."""
        files = self._files()
        return {
            "directory": str(self._directory),
            "count": len(files),
            "keep": self._keep,
            "newest": files[-1].stem if files else None,
        }
