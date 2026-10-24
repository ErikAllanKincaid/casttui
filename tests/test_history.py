"""History kept in a JSON lines file across runs."""
from __future__ import annotations


import casttui.history as hist
from casttui.config import Config
from casttui.history import Entry


def test_append_load_newest_first(tmp_path):
    p = tmp_path / "h.jsonl"
    hist.append(Entry("2026-10-22T20:00", "cast a.mp4", "file", "/a.mp4"), p)
    hist.append(Entry("2026-10-23T21:04", "cast b.mp4", "file", "/b.mp4"), p)
    assert [e.text for e in hist.load(p)] == ["cast b.mp4", "cast a.mp4"]


def test_broken_lines_and_missing_file_are_harmless(tmp_path):
    p = tmp_path / "h.jsonl"
    assert hist.load(p) == []
    p.write_text('not json\n{"when": "2026-10-23T21:04", "text": "ok"}\n{"text": "no when"}\n')
    assert [e.text for e in hist.load(p)] == ["ok"]


def test_file_is_trimmed_to_the_newest(tmp_path, monkeypatch):
    monkeypatch.setattr(hist, "KEEP", 3)
    p = tmp_path / "h.jsonl"
    for i in range(7):
        hist.append(Entry(f"2026-10-23T21:0{i}", f"e{i}"), p)
    assert len(p.read_text().splitlines()) <= 6
    assert [e.text for e in hist.load(p)] == ["e6", "e5", "e4"]


def test_rewrite_keeps_order(tmp_path):
    p = tmp_path / "h.jsonl"
    hist.rewrite([Entry("2026-10-23T21:05", "new"), Entry("2026-10-23T21:01", "old")], p)
    assert [e.text for e in hist.load(p)] == ["new", "old"]


def test_shown_when():
    assert hist.shown_when("2026-10-23T21:04", today="2026-10-23") == "21:04"
    assert hist.shown_when("2026-10-22T21:04", today="2026-10-23") == "10-22 21:04"


def _app(cfg):
    from test_panes import device, make, service

    svc = service([device()])
    app = make(svc, cfg)
    app.start()
    return app, svc


def test_history_survives_a_restart_and_scans_are_not_kept(tmp_path):
    app, _ = _app(Config(last_device="Living Room TV"))
    app.cast_url("http://h/a.mp4")
    texts = [e.text for e in hist.load()]
    assert texts[0] == "cast http://h/a.mp4" and texts[1].startswith("connected")
    assert not any(t.startswith("scan") for t in texts)
    again, svc = _app(Config(last_device="Living Room TV"))
    assert any(e.text == "cast http://h/a.mp4" for e in again.history)
    again.focus = 4
    again.history_list.select(next(i for i, e in enumerate(again.history) if e.kind == "url"))
    again.press("enter")
    svc.play_url.assert_called_once_with("http://h/a.mp4")


def test_delete_rewrites_the_file():
    app, _ = _app(Config(last_device="Living Room TV"))
    app.cast_url("http://h/a.mp4")
    app.focus = 4
    app.history_list.focus_position = 0
    app.press("d")
    assert not any(e.text == "cast http://h/a.mp4" for e in hist.load())


def test_history_off_neither_loads_nor_saves():
    hist.append(Entry("2026-10-23T21:00", "old"))
    app, _ = _app(Config(last_device="Living Room TV", history=False))
    assert not any(e.text == "old" for e in app.history)
    app.cast_url("http://h/a.mp4")
    assert [e.text for e in hist.load()] == ["old"]
