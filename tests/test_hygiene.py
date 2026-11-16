"""The repository check that keeps recordings and secrets out of Git."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("hygiene", ROOT / "scripts" / "check_repo_hygiene.py")
hygiene = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hygiene)


def test_recordings_and_secret_files_are_caught(tmp_path):
    (tmp_path / "notes.txt").write_text("nothing to see")
    (tmp_path / "config.py").write_text('KEY = "sk-ant-' + "a" * 40 + '"')
    found = hygiene.problems(["call.wav", "clip.MP4", ".env", "notes.txt", "config.py"], tmp_path)
    assert len(found) == 4
    assert not any("notes.txt" in problem for problem in found)


def test_env_example_is_allowed(tmp_path):
    (tmp_path / ".env.example").write_text("BAITREEL_MODEL=gemma4:12b\n")
    assert hygiene.problems([".env.example"], tmp_path) == []


def test_this_repository_is_clean():
    assert hygiene.main() == 0
