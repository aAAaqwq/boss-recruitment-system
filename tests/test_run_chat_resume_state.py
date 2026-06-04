import sqlite3
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "run_chat_and_resume.py"

spec = importlib.util.spec_from_file_location("run_chat_and_resume", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_has_new_msg_normalize_ignores_whitespace_and_punctuation_variants(monkeypatch):
    monkeypatch.setattr(mod, "get_chat_text", lambda: "你好，  我对岗位感兴趣！")
    session = {"last_screen_text": "你好我对岗位感兴趣"}
    fresh, cur = mod.has_new_msg(session)
    assert fresh is False
    assert cur


def test_has_new_msg_detects_real_content_change(monkeypatch):
    monkeypatch.setattr(mod, "get_chat_text", lambda: "你好，我对岗位很感兴趣，方便了解下薪资范围吗？")
    session = {"last_screen_text": "你好我对岗位感兴趣"}
    fresh, _ = mod.has_new_msg(session)
    assert fresh is True


def test_should_skip_candidate_by_name_and_fingerprint():
    processed = {"Alice", "fp:abc"}
    assert mod.should_skip_candidate("Alice", "fp:xyz", processed) is True
    assert mod.should_skip_candidate("Bob", "fp:abc", processed) is True
    assert mod.should_skip_candidate("Bob", "fp:zzz", processed) is False


def test_load_and_save_runtime_state_roundtrip(tmp_path):
    state_path = tmp_path / "state.db"
    conn = sqlite3.connect(state_path)
    mod.init_db(conn=conn)

    mod.save_runtime_state(conn, global_idx=17)
    loaded = mod.load_runtime_state(conn)

    assert loaded["global_idx"] == 17

    conn.close()


def test_mark_candidate_processed_persists_name_and_fingerprint(tmp_path):
    state_path = tmp_path / "state.db"
    conn = sqlite3.connect(state_path)
    mod.init_db(conn=conn)

    mod.mark_candidate_processed(conn, "张三", "fp:001")
    loaded = mod.load_processed_candidates(conn)

    assert "张三" in loaded
    assert "fp:001" in loaded

    conn.close()
