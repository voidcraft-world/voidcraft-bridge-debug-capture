"""Application-independent routes over the local capture ring."""
from __future__ import annotations

import os
from pathlib import Path

from voidcraft_world_bridge.policy import CallerPolicy
from voidcraft_world_bridge.routing import Route, RoutedPlugin

from .store import CaptureStore, CaptureStoreError

PLUGIN_NAME = "debug-capture"


def query_value(query: dict[str, list[str]], key: str, default: str = "") -> str:
    return (query.get(key) or [default])[0]


class DebugCapturePlugin(RoutedPlugin):
    request_policy = CallerPolicy()

    def __init__(self, context=None, store: CaptureStore | None = None,
                 empty_hint: str = "Use your application's capture button to send a diagnostic snapshot.") -> None:
        directory = os.environ.get("VOIDCRAFT_CAPTURE_DIR")
        self._store = store if store is not None else CaptureStore(Path(directory).expanduser() if directory else None)
        self._empty_hint = empty_hint
        super().__init__(PLUGIN_NAME, [
            Route("POST", "/capture", self._capture, "Save an application-selected snapshot"),
            Route("GET", "/latest", self._latest, "Read the newest snapshot"),
            Route("GET", "/list", self._list, "List capture metadata"),
            Route("GET", "/get", self._get, "Read one capture by id"),
            Route("GET", "/state", self._state, "Read local storage status"),
        ])

    def _capture(self, query, body) -> tuple:
        try:
            return 200, {"version": 1, "plugin": self.name, **self._store.save(body)}
        except CaptureStoreError as error:
            return 400, {"error": str(error)}
        except OSError:
            return 500, {"error": "could not write the capture"}

    def _latest(self, query, body) -> tuple:
        record = self._store.latest()
        return 200, {"version": 1, "plugin": self.name,
                     **(record if record is not None else {"capture": None, "hint": self._empty_hint})}

    def _list(self, query, body) -> tuple:
        try:
            limit = int(query_value(query, "limit", "10"))
        except ValueError:
            limit = 10
        return 200, {"version": 1, "plugin": self.name, "captures": self._store.listing(limit)}

    def _get(self, query, body) -> tuple:
        capture_id = query_value(query, "id")
        if not capture_id:
            return 400, {"error": "missing ?id — list captures with GET /list"}
        record = self._store.get(capture_id)
        if record is None:
            return 404, {"error": "capture not found"}
        return 200, {"version": 1, "plugin": self.name, **record}

    def _state(self, query, body) -> tuple:
        return 200, {"version": 1, "plugin": self.name, **self._store.state()}
