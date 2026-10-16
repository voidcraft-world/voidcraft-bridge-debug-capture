import json

import pytest

from voidcraft_bridge_debug_capture.store import CaptureStore, CaptureStoreError


def test_redaction_precedes_disk_and_does_not_mutate_input(tmp_path):
    payload = {"version": 1, "token": "example", "count": 2}
    store = CaptureStore(tmp_path, redact=lambda value: {k: v for k, v in value.items() if k != "token"})
    saved = store.save(payload)
    assert "token" not in store.get(saved["id"])["capture"]
    assert payload["token"] == "example"


def test_oversized_and_nonfinite_captures_are_rejected(tmp_path):
    store = CaptureStore(tmp_path, max_bytes=80)
    for payload in ({"version": 1, "text": "😀" * 30}, {"version": 1, "value": float("nan")}):
        with pytest.raises(CaptureStoreError):
            store.save(payload)
    assert not list(tmp_path.iterdir())


def test_unrelated_json_and_symlinks_are_neither_read_nor_pruned(tmp_path):
    directory = tmp_path / "captures"
    directory.mkdir()
    outside = tmp_path / "secret.json"
    outside.write_text(json.dumps({"capture": {"secret": True}}))
    (directory / "9999999999999-link.json").symlink_to(outside)
    unrelated = directory / "settings.json"
    unrelated.write_text('{"keep":true}')
    store = CaptureStore(directory, keep=1)
    for _ in range(3):
        store.save({"version": 1})
    assert unrelated.exists() and outside.exists()
    assert store.get("9999999999999-link") is None
    assert len(store.listing()) == 1


def test_malformed_envelopes_do_not_break_latest(tmp_path):
    store = CaptureStore(tmp_path)
    store.save({"version": 1})
    (tmp_path / "9999999999999-bad.json").write_text("[]")
    assert store.latest()["capture"] == {"version": 1}


def test_overdeep_json_is_skipped(tmp_path):
    store = CaptureStore(tmp_path)
    store.save({"version": 1})
    (tmp_path / "9999999999999-deep.json").write_text("[" * 1500 + "0" + "]" * 1500)
    assert store.latest()["capture"] == {"version": 1}


def test_lone_surrogate_is_refused_before_writing(tmp_path):
    with pytest.raises(CaptureStoreError):
        CaptureStore(tmp_path).save({"version": 1, "text": "\ud800"})
    assert not list(tmp_path.iterdir())
