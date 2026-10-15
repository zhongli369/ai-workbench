"""Fixtures for the multi-project workbench tests.

One session-scoped workbench install (into tmp) stands in for "the AI
Workbench workspace"; every test gets a FRESH per-test copy of the shared
harness-data dir so tests are fully independent.  Two target projects
(proj-a / proj-b) are real git repos with deliberately conflicting
CLAUDE.md rules.

This suite is collected by the default `pytest tests/` run and counted in
the repo totals (350 = 171 harness-core + 179 tests); the docs-drift gate
reconciles those counts live.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from multiproj_util import (
    WORKBENCH_CLI, base_env, mk_project,
)


@pytest.fixture(scope="session")
def workbench_target(tmp_path_factory) -> Path:
    """A real workbench install. Read-only for all tests."""
    target = tmp_path_factory.mktemp("wb-target")
    env = base_env()
    proc = subprocess.run(
        [sys.executable, str(WORKBENCH_CLI), "--target", str(target),
         "install", "--yes"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, timeout=300,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (target / "install-manifest.json").is_file()
    gate = target / "harness-data" / "gate.json"
    assert gate.is_file(), "workbench install must ship a default gate.json"
    return target


@pytest.fixture()
def data_dir(tmp_path, workbench_target) -> Path:
    """A per-test copy of the workbench's shared harness-data dir."""
    data = tmp_path / "harness-data"
    src = workbench_target / "harness-data"
    shutil.copytree(src, data)  # fresh: gate.json default (audit) only
    return data


@pytest.fixture()
def two_projects(tmp_path):
    """proj-a (typehints REQUIRED) and proj-b (typehints FORBIDDEN)."""
    proj_a = mk_project(tmp_path / "proj-a", "proj-a-id", typehints=True)
    proj_b = mk_project(tmp_path / "proj-b", "proj-b-id", typehints=False)
    return proj_a, proj_b