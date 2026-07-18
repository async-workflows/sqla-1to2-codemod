"""CLI behaviour: diffs, --write, --check, --json, --explain and idempotency."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from sqla_1to2_codemod import analyze_source
from sqla_1to2_codemod.cli import main

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def legacy_copy(tmp_path: Path) -> Path:
    dst = tmp_path / "legacy_app.py"
    shutil.copy(FIXTURES / "legacy_app.py", dst)
    return dst


def test_dry_run_prints_diff_but_does_not_write(legacy_copy, capsys):
    before = legacy_copy.read_text()
    rc = main([str(legacy_copy)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "from sqlalchemy.orm import declarative_base" in out  # diff shows fix
    assert legacy_copy.read_text() == before  # file untouched


def test_write_applies_changes(legacy_copy):
    rc = main([str(legacy_copy), "--write"])
    assert rc == 0
    text = legacy_copy.read_text()
    assert "from sqlalchemy.orm import declarative_base" in text
    assert "session.get(User, user_id)" in text
    assert "session.execute(select(User)).scalars().all()" in text
    assert "from sqlalchemy import select" in text


def test_write_is_idempotent(legacy_copy):
    assert main([str(legacy_copy), "--write"]) == 0
    first = legacy_copy.read_text()
    # A second run must not change the already-migrated file.
    assert main([str(legacy_copy), "--write"]) == 0
    assert legacy_copy.read_text() == first


def test_analyze_source_idempotent():
    src = (FIXTURES / "legacy_app.py").read_text()
    _f1, once = analyze_source(src)
    _f2, twice = analyze_source(once)
    assert once == twice


def test_check_exit_code_nonzero_on_legacy(legacy_copy):
    assert main([str(legacy_copy), "--check"]) == 1


def test_check_exit_code_zero_on_modern(tmp_path):
    dst = tmp_path / "modern_app.py"
    shutil.copy(FIXTURES / "modern_app.py", dst)
    assert main([str(dst), "--check"]) == 0


def test_modern_file_is_unchanged():
    src = (FIXTURES / "modern_app.py").read_text()
    findings, out = analyze_source(src)
    assert out == src
    assert findings == []


def test_json_output_shape(legacy_copy, capsys):
    rc = main([str(legacy_copy), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, list) and payload
    for item in payload:
        assert set(item) == {"file", "line", "rule_id", "summary", "fixable"}
        assert isinstance(item["line"], int)
        assert isinstance(item["fixable"], bool)
    assert {item["rule_id"] for item in payload} >= {"SA001", "SA003", "SA004"}


def test_explain_prints_doc_link(capsys):
    rc = main(["--explain", "SA004"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "SA004" in out
    assert "https://www.async-workflows.com/" in out


def test_explain_unknown_rule_errors(capsys):
    rc = main(["--explain", "SA999"])
    assert rc == 2


def test_rules_filter_selects_subset(legacy_copy, capsys):
    rc = main([str(legacy_copy), "--json", "--rules", "SA001"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert {item["rule_id"] for item in payload} == {"SA001"}


def test_directory_recursion(tmp_path, capsys):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    shutil.copy(FIXTURES / "legacy_app.py", pkg / "a.py")
    (pkg / "sub").mkdir()
    shutil.copy(FIXTURES / "legacy_app.py", pkg / "sub" / "b.py")
    rc = main([str(pkg), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    files = {item["file"] for item in payload}
    assert any(f.endswith("a.py") for f in files)
    assert any(f.endswith("b.py") for f in files)


def test_invalid_rule_id_errors(capsys):
    rc = main(["some_path.py", "--rules", "NOPE"])
    assert rc == 2
