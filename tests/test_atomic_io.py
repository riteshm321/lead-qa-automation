import json
import os

import pytest

from core.atomic_io import atomic_write_json


def test_atomic_write_json_creates_file_and_parent_dir(tmp_path):
    path = str(tmp_path / "nested" / "data.json")

    atomic_write_json(path, {"a": 1})

    assert os.path.isfile(path)
    with open(path, "r", encoding="utf-8") as f:
        assert json.load(f) == {"a": 1}


def test_atomic_write_json_overwrites_existing_file(tmp_path):
    path = str(tmp_path / "data.json")
    atomic_write_json(path, {"a": 1})

    atomic_write_json(path, {"a": 2})

    with open(path, "r", encoding="utf-8") as f:
        assert json.load(f) == {"a": 2}


def test_atomic_write_json_leaves_no_temp_files_behind(tmp_path):
    atomic_write_json(str(tmp_path / "data.json"), [1, 2, 3])

    assert os.listdir(tmp_path) == ["data.json"]


def test_atomic_write_json_does_not_corrupt_existing_file_on_failure(tmp_path, monkeypatch):
    path = str(tmp_path / "data.json")
    atomic_write_json(path, {"good": True})

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated crash mid-write")

    monkeypatch.setattr("json.dump", _boom)

    with pytest.raises(RuntimeError):
        atomic_write_json(path, {"bad": True})

    with open(path, "r", encoding="utf-8") as f:
        assert json.load(f) == {"good": True}
    assert os.listdir(tmp_path) == ["data.json"]
