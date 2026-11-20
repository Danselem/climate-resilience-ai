"""Manifests and content hashing."""

from __future__ import annotations

import json
from pathlib import Path

from climate_resilience.manifest import (
    RunRecorder,
    content_hash,
    sha256_file,
    sha256_obj,
)


def test_file_hash_is_stable(tmp_path: Path) -> None:
    target = tmp_path / "a.csv"
    target.write_text("cell,date,value\nc1,2020-01-01,30\n", encoding="utf-8")
    assert sha256_file(target) == sha256_file(target)


def test_file_hash_detects_a_single_character_change(tmp_path: Path) -> None:
    first = tmp_path / "a.txt"
    second = tmp_path / "b.txt"
    first.write_text("365", encoding="utf-8")
    second.write_text("366", encoding="utf-8")
    assert sha256_file(first) != sha256_file(second)


def test_object_hash_ignores_key_order() -> None:
    assert sha256_obj({"a": 1, "b": 2}) == sha256_obj({"b": 2, "a": 1})


def test_content_hash_ignores_run_identity() -> None:
    first = [{"indicator_id": "x", "value": 1.0, "run_id": "run-a", "created_at": "2026-01-01"}]
    second = [{"indicator_id": "x", "value": 1.0, "run_id": "run-b", "created_at": "2026-06-01"}]
    assert content_hash(first) == content_hash(second)


def test_content_hash_detects_a_changed_value() -> None:
    first = [{"indicator_id": "x", "value": 1.0, "run_id": "run-a"}]
    second = [{"indicator_id": "x", "value": 1.5, "run_id": "run-a"}]
    assert content_hash(first) != content_hash(second)


def test_recorder_writes_a_manifest_with_hashed_outputs(tmp_path: Path) -> None:
    inputs = tmp_path / "input.parquet"
    inputs.write_bytes(b"payload")
    outputs = tmp_path / "output.json"
    outputs.write_text('{"rows": []}', encoding="utf-8")

    recorder = RunRecorder(
        "build_mart",
        manifest_dir=tmp_path / "manifests",
        parameters={"threshold_c": 35.0},
        repo_root=tmp_path,
    )
    recorder.add_input(inputs)
    recorder.add_output(outputs)
    manifest = recorder.finish()

    written = json.loads(
        (tmp_path / "manifests" / f"build_mart-{recorder.run_id}.json").read_text()
    )
    assert written["stage"] == "build_mart"
    assert written["parameters"]["threshold_c"] == 35.0
    assert written["inputs"][0]["sha256"] == sha256_file(inputs)
    assert written["outputs"][0]["sha256"] == sha256_file(outputs)
    assert manifest.finished_at is not None
    assert "python" in manifest.package_versions


def test_inputs_hash_tracks_input_changes(tmp_path: Path) -> None:
    target = tmp_path / "input.txt"
    target.write_text("one", encoding="utf-8")

    first = RunRecorder("stage", manifest_dir=tmp_path, repo_root=tmp_path)
    first.add_input(target)
    hash_before = first.inputs_hash

    target.write_text("two", encoding="utf-8")
    second = RunRecorder("stage", manifest_dir=tmp_path, repo_root=tmp_path)
    second.add_input(target)

    assert hash_before != second.inputs_hash


def test_manifest_records_parameters_and_timestamps(tmp_path: Path) -> None:
    recorder = RunRecorder(
        "stage", manifest_dir=tmp_path, parameters={"b": 2, "a": 1}, repo_root=tmp_path
    )
    recorder.finish()
    path = tmp_path / f"stage-{recorder.run_id}.json"
    payload = json.loads(path.read_text())
    assert payload["parameters"] == {"b": 2, "a": 1}
    assert payload["stage"] == "stage"
    assert payload["started_at"]
    assert payload["finished_at"]
