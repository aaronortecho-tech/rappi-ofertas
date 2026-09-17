import json

from monitor.state import State, offer_key

NOW = 1_800_000_000


def test_offer_key_is_stable_and_hides_details():
    key = offer_key("o", "restaurante", "23402", "2092703306", 70)
    assert key == offer_key("o", "restaurante", "23402", "2092703306", 70)
    assert len(key) == 16 and "23402" not in key
    assert key != offer_key("o", "restaurante", "23402", "2092703306", 71)


def test_seen_window_and_prune():
    state = State()
    assert state.first_run
    assert state.is_new("k", NOW, 24)
    state.mark_seen("k", NOW)
    assert not state.is_new("k", NOW + 3600, 24)
    assert state.is_new("k", NOW + 24 * 3600, 24)
    state.prune(NOW + 49 * 3600, 48)
    assert "k" not in state.seen


def test_save_only_when_changed(tmp_path):
    path = tmp_path / "sub" / "state.json"
    state = State.load(path)
    assert not state.existed
    state.mark_started(NOW)
    assert state.save(path, NOW)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["started_at"] == NOW and saved["saved_at"] == NOW

    again = State.load(path)
    assert not again.first_run
    assert not again.save(path, NOW + 60)  # nada cambió
    assert not again.save(path, NOW + 90 * 24 * 3600)  # ni aunque pase mucho tiempo

    again.mark_seen("x", NOW + 100)
    assert again.changed()
    assert again.save(path, NOW + 200)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["seen"] == {"x": NOW + 100} and saved["saved_at"] == NOW + 200
    assert not again.changed()


def test_corrupt_file_starts_fresh(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{no es json", encoding="utf-8")
    state = State.load(path)
    assert state.existed and state.first_run and state.seen == {}


def test_failures_and_cooldown():
    state = State()
    assert state.record_result("tiendas", False) == 1
    assert state.record_result("tiendas", False) == 2
    assert state.record_result("tiendas", True) == 0
    assert state.can_notify_failure(NOW)
    state.last_failure_notice = NOW
    assert not state.can_notify_failure(NOW + 3600)
    assert state.can_notify_failure(NOW + 24 * 3600)


def test_cached_store_list():
    state = State()
    assert state.cached_stores(NOW) is None
    state.set_stores([(1, "a"), (2, "b")], NOW)
    assert state.cached_stores(NOW + 3600) == [(1, "a"), (2, "b")]
    assert state.cached_stores(NOW + 25 * 3600) is None
    state.store_list = {"fetched_at": NOW, "stores": [["x", "bad"]]}
    assert state.cached_stores(NOW) is None
