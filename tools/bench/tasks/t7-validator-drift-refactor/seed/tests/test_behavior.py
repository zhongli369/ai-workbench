"""Shipped behavior suite for confcfg (hash-pinned; do not modify).

Encodes spec.md. On the drifted seed this suite FAILS (the report path
accepts port 0 / relative paths and ignores reserved keys). A correct
unification makes every test pass without touching this file.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import confcfg
from confcfg.report import report_config


# ---------- spec rule 1: ports ----------

def test_port_zero_rejected_by_public_api():
    assert confcfg.validate_config({"server": {"port": 0}}) == ["server.port"]


def test_port_zero_rejected_by_report_path(tmp_path):
    f = tmp_path / "c.json"
    f.write_text(json.dumps({"server": {"port": 0}}), encoding="utf-8")
    assert report_config(f) == "INVALID: server.port"


@pytest.mark.parametrize("port", [1, 8080, 65535])
def test_valid_ports_accepted(port):
    assert confcfg.validate_config({"server": {"port": port}}) == []


@pytest.mark.parametrize("port", [-1, 65536, True, "8080"])
def test_invalid_ports_rejected(port):
    assert confcfg.validate_config({"backup": {"port": port}}) == ["backup.port"]


# ---------- spec rule 2: paths ----------

def test_relative_path_rejected_by_public_api():
    assert confcfg.validate_config({"backup": {"path": "rel/dir"}}) == ["backup.path"]


def test_relative_path_rejected_by_report_path(tmp_path):
    f = tmp_path / "c.json"
    f.write_text(json.dumps({"backup": {"path": "rel/dir"}}), encoding="utf-8")
    assert report_config(f) == "INVALID: backup.path"


def test_absolute_path_accepted():
    assert confcfg.validate_config({"backup": {"path": "/var/backups"}}) == []


# ---------- spec rule 3: reserved keys ----------

def test_reserved_keys_rejected_by_public_api():
    assert confcfg.validate_config({"__meta__": 1}) == ["__meta__"]


def test_reserved_keys_rejected_by_report_path(tmp_path):
    f = tmp_path / "c.json"
    f.write_text(json.dumps({"__comment__": "x", "server": {"port": 1}}),
                 encoding="utf-8")
    assert report_config(f) == "INVALID: __comment__"


# ---------- spec rule 4: sorted combined output ----------

def test_multiple_bad_fields_sorted():
    cfg = {"server": {"port": 0}, "backup": {"path": "rel"}}
    assert confcfg.validate_config(cfg) == ["backup.path", "server.port"]


def test_empty_means_valid():
    assert confcfg.validate_config({}) == []


# ---------- spec rule 5: type errors raise ----------

def test_non_mapping_config_raises():
    with pytest.raises(Exception):
        confcfg.validate_config([1, 2, 3])


def test_non_mapping_section_raises():
    with pytest.raises(Exception):
        confcfg.validate_config({"server": "oops"})


# ---------- loader/CLI compatibility ----------

def test_load_config_applies_defaults_and_validates(tmp_path):
    f = tmp_path / "c.json"
    f.write_text("{}", encoding="utf-8")
    cfg = confcfg.load_config(f)
    assert cfg["server"]["port"] == 8080
    assert cfg["backup"]["path"] == "/var/backups"


def test_load_config_rejects_port_zero_after_merge(tmp_path):
    f = tmp_path / "c.json"
    f.write_text(json.dumps({"server": {"port": 0}}), encoding="utf-8")
    with pytest.raises(Exception):
        confcfg.load_config(f)


def test_dump_config_roundtrip(tmp_path):
    f = tmp_path / "out.json"
    confcfg.dump_config({"server": {"port": 1}}, f)
    assert json.loads(f.read_text(encoding="utf-8"))["server"]["port"] == 1


def test_cli_check_valid(tmp_path):
    f = tmp_path / "c.json"
    f.write_text(json.dumps({"server": {"port": 22, "host": "x"}}),
                 encoding="utf-8")
    r = subprocess.run([sys.executable, "-m", "confcfg", "check", str(f)],
                       capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip() == "OK"


def test_cli_check_port_zero_invalid(tmp_path):
    f = tmp_path / "c.json"
    f.write_text(json.dumps({"server": {"port": 0}}), encoding="utf-8")
    r = subprocess.run([sys.executable, "-m", "confcfg", "check", str(f)],
                       capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip() == "INVALID: server.port"


def test_cli_normalize_fails_on_invalid(tmp_path):
    f = tmp_path / "c.json"
    f.write_text(json.dumps({"server": {"port": 0}}), encoding="utf-8")
    r = subprocess.run([sys.executable, "-m", "confcfg", "normalize", str(f)],
                       capture_output=True, text=True)
    assert r.returncode == 1
