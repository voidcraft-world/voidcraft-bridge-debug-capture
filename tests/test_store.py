"""CaptureStore: the on-disk ring behind the plugin's routes."""
import json

import pytest

from voidcraft_bridge_debug_capture.store import CaptureStore, CaptureStoreError, capture_filename


def make_store(tmp_path, keep=25, start=1_700_000_000.0):
    """A store with an injected clock and id source, so nothing here is flaky."""
    clock = {"t": start}
    counter = {"n": 0}

    def now():
        clock["t"] += 1.0
        return clock["t"]

    def next_id():
        counter["n"] += 1
        return f"{counter['n']:06x}"

    return CaptureStore(tmp_path, keep=keep, now_fn=now, id_fn=next_id)


def digest(kind="example", **extra):
    return {"version": 1, "kind": kind, **extra}


def test_save_writes_a_readable_record(tmp_path):
    store = make_store(tmp_path)
    meta = store.save(digest(note="hello"))

    assert meta["bytes"] > 0
    stored = json.loads((tmp_path / f"{meta['id']}.json").read_text())
    assert stored["capture"]["note"] == "hello"
    assert stored["kind"] == "example"
    assert stored["id"] == meta["id"]


def test_payload_is_nested_not_merged(tmp_path):
    """A capture field must never be able to shadow an envelope field."""
    store = make_store(tmp_path)
    meta = store.save(digest(id="not-the-envelope-id", stored_at=1))
    record = store.get(meta["id"])

    assert record["id"] == meta["id"]
    assert record["capture"]["id"] == "not-the-envelope-id"


def test_rejects_a_payload_that_is_not_a_versioned_object(tmp_path):
    store = make_store(tmp_path)
    with pytest.raises(CaptureStoreError):
        store.save(["not", "an", "object"])
    with pytest.raises(CaptureStoreError):
        store.save({"kind": "example"})
    with pytest.raises(CaptureStoreError):
        store.save({"version": "1"})


def test_latest_is_the_newest(tmp_path):
    store = make_store(tmp_path)
    store.save(digest(note="first"))
    store.save(digest(note="second"))
    assert store.latest()["capture"]["note"] == "second"


def test_same_tick_captures_remain_ordered_and_do_not_evict_the_newest(tmp_path):
    ids = iter(["zzz", "aaa"])
    store = CaptureStore(tmp_path, keep=1, now_fn=lambda: 1_700_000_000, id_fn=lambda: next(ids))
    first = store.save(digest(note="first"))
    second = store.save(digest(note="second"))
    assert store.latest()["capture"]["note"] == "second"
    assert store.get(second["id"]) is not None
    assert store.get(first["id"]) is None


def test_reopening_store_after_clock_moves_back_preserves_newest(tmp_path):
    first = CaptureStore(tmp_path, now_fn=lambda: 1_700_000_010, id_fn=lambda: "same")
    first.save(digest(note="first"))
    reopened = CaptureStore(tmp_path, now_fn=lambda: 1_700_000_000, id_fn=lambda: "same")
    saved = reopened.save(digest(note="second"))
    assert reopened.latest()["id"] == saved["id"]
    assert [row["id"] for row in reopened.listing()][0] == saved["id"]
    assert reopened.state()["newest"] == saved["id"]
    assert saved["stored_at"] == 1_700_000_000_000


def test_unicode_budget_matches_browser_utf8_serialization(tmp_path):
    payload = digest(note="😀" * 900)
    browser_body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    assert len(browser_body) < 4096
    store = make_store(tmp_path)
    saved = store.save(payload)
    assert store.get(saved["id"])["capture"] == payload


def test_latest_is_none_on_an_empty_or_missing_directory(tmp_path):
    assert make_store(tmp_path).latest() is None
    assert CaptureStore(tmp_path / "does" / "not" / "exist").latest() is None


def test_ring_evicts_oldest_first(tmp_path):
    store = make_store(tmp_path, keep=3)
    for i in range(6):
        store.save(digest(note=f"n{i}"))

    rows = store.listing(limit=10)
    assert len(rows) == 3
    assert [store.get(row["id"])["capture"]["note"] for row in rows] == ["n5", "n4", "n3"]
    assert len(list(tmp_path.glob("*.json"))) == 3


def test_listing_is_newest_first_and_capped(tmp_path):
    store = make_store(tmp_path)
    for i in range(5):
        store.save(digest(note=f"n{i}"))
    rows = store.listing(limit=2)
    assert len(rows) == 2
    assert store.get(rows[0]["id"])["capture"]["note"] == "n4"


def test_a_corrupt_file_is_skipped_rather_than_breaking_the_listing(tmp_path):
    store = make_store(tmp_path)
    store.save(digest(note="good"))
    (tmp_path / "9999999999999-dead.json").write_text("{ not json")

    # The corrupt file sorts LAST, so a naive `latest` would return it.
    assert store.latest()["capture"]["note"] == "good"
    assert [row["id"] for row in store.listing()] == [store.latest()["id"]]


def test_get_matches_the_filename_stem_so_traversal_is_impossible(tmp_path):
    store = make_store(tmp_path)
    store.save(digest())
    assert store.get("../../../../etc/passwd") is None
    assert store.get("") is None
    assert store.get(None) is None


def test_non_capture_files_are_left_alone(tmp_path):
    """The directory may be shared; only *.json captures are ours to evict."""
    store = make_store(tmp_path, keep=1)
    (tmp_path / "notes.txt").write_text("keep me")
    for _ in range(4):
        store.save(digest())
    assert (tmp_path / "notes.txt").exists()


def test_filenames_sort_chronologically_as_plain_strings(tmp_path):
    """The lexical sort IS the chronological sort — that is load-bearing."""
    names = [capture_filename(stamp, "aaa") for stamp in (999, 1_700_000_000_000, 2_000_000_000_000)]
    assert names == sorted(names)


def test_state_is_side_effect_free(tmp_path):
    store = make_store(tmp_path)
    store.save(digest())
    before = store.state()
    assert store.state() == before
    assert before["count"] == 1
    assert before["directory"] == str(tmp_path)


def test_no_partial_file_is_left_behind(tmp_path):
    """Atomic write means a reader never sees a half-written capture."""
    store = make_store(tmp_path)
    store.save(digest(note="x" * 500))
    assert [p.suffix for p in tmp_path.iterdir()] == [".json"]
