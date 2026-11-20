"""Run manifests and content hashing.

Every pipeline stage writes a manifest: inputs, parameters, outputs, package
versions, commit. Reproducibility is asserted over content hashes, excluding
run identity fields (which necessarily differ between runs).
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from datetime import datetime
from importlib import metadata
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .envelope import now_utc

TRACKED_PACKAGES = ("pandas", "shapely", "pyproj", "sqlalchemy", "pydantic", "pyarrow")


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(chunk_size):
            digest.update(block)
    return digest.hexdigest()


def sha256_obj(obj: Any) -> str:
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def git_commit(cwd: Path | None = None) -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return "unknown"


def package_versions() -> dict[str, str]:
    versions: dict[str, str] = {"python": platform.python_version()}
    for name in TRACKED_PACKAGES:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            continue
    return versions


class FileRef(BaseModel):
    path: str
    sha256: str
    bytes: int | None = None


class RunManifest(BaseModel):
    run_id: str
    stage: str
    git_commit: str
    inputs: list[FileRef] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    outputs: list[FileRef] = Field(default_factory=list)
    package_versions: dict[str, str] = Field(default_factory=dict)
    started_at: datetime
    finished_at: datetime | None = None

    def output_hashes(self) -> dict[str, str]:
        return {ref.path: ref.sha256 for ref in self.outputs}


class RunRecorder:
    """Collects inputs and outputs for one stage and writes a manifest."""

    def __init__(
        self,
        stage: str,
        *,
        manifest_dir: Path,
        parameters: dict[str, Any] | None = None,
        repo_root: Path | None = None,
    ) -> None:
        self.stage = stage
        self.manifest_dir = manifest_dir
        self.parameters = parameters or {}
        self._inputs: list[FileRef] = []
        self._outputs: list[FileRef] = []
        self.started_at = now_utc()
        self._commit = git_commit(repo_root)
        self.run_id = f"{self.started_at:%Y%m%dT%H%M%SZ}-{sha256_obj(self.parameters)[:8]}"

    @property
    def commit(self) -> str:
        return self._commit

    def add_input(self, path: Path) -> None:
        self._inputs.append(
            FileRef(path=str(path), sha256=sha256_file(path), bytes=path.stat().st_size)
        )

    def add_output(self, path: Path) -> None:
        self._outputs.append(
            FileRef(path=str(path), sha256=sha256_file(path), bytes=path.stat().st_size)
        )

    @property
    def inputs_hash(self) -> str:
        return sha256_obj([{"path": r.path, "sha256": r.sha256} for r in self._inputs])

    def finish(self) -> RunManifest:
        manifest = RunManifest(
            run_id=self.run_id,
            stage=self.stage,
            git_commit=self._commit,
            inputs=self._inputs,
            parameters=self.parameters,
            outputs=self._outputs,
            package_versions=package_versions(),
            started_at=self.started_at,
            finished_at=now_utc(),
        )
        self.manifest_dir.mkdir(parents=True, exist_ok=True)
        target = self.manifest_dir / f"{self.stage}-{self.run_id}.json"
        target.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        return manifest


def content_hash(
    rows: list[dict[str, Any]],
    *,
    exclude: tuple[str, ...] = ("run_id", "created_at", "envelope_json"),
) -> str:
    """Hash of published content, ignoring run identity.

    Two builds from the same inputs and commit must produce the same hash.
    `run_id` and `created_at` differ by design, so they are excluded.
    `envelope_json` is excluded because the run identity is embedded inside it
    as JSON, where a top-level key filter cannot reach it. Nothing analytically
    material is lost: value, scope, period, parameters, dataset_version,
    method_version, warnings and resolution are all flattened columns of the
    same envelope.
    """
    cleaned = [{k: v for k, v in row.items() if k not in exclude} for row in rows]
    cleaned.sort(key=lambda row: json.dumps(row, sort_keys=True, default=str))
    return sha256_obj(cleaned)
