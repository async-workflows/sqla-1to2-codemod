"""One test per rule plus registry sanity checks."""

from __future__ import annotations

import pytest

from sqla_1to2_codemod import RULES, analyze_source
from sqla_1to2_codemod.rules import ALL_RULE_IDS


def rule_ids(source: str) -> set[str]:
    findings, _ = analyze_source(source)
    return {f.rule_id for f in findings}


def rewrite(source: str) -> str:
    _findings, new_source = analyze_source(source)
    return new_source


# --------------------------------------------------------------------------- #
# SA001 / SA002 -- deprecated import locations.
# --------------------------------------------------------------------------- #
def test_sa001_declarative_base_import_rewritten():
    src = "from sqlalchemy.ext.declarative import declarative_base\n"
    findings, out = analyze_source(src)
    assert "SA001" in {f.rule_id for f in findings}
    assert all(f.fixable for f in findings if f.rule_id == "SA001")
    assert out == "from sqlalchemy.orm import declarative_base\n"


def test_sa002_declared_attr_import_rewritten():
    src = "from sqlalchemy.ext.declarative import declared_attr\n"
    out = rewrite(src)
    assert out == "from sqlalchemy.orm import declared_attr\n"
    assert "SA002" in rule_ids(src)


def test_sa001_sa002_combined_import_rewritten():
    src = "from sqlalchemy.ext.declarative import declarative_base, declared_attr\n"
    out = rewrite(src)
    assert out == "from sqlalchemy.orm import declarative_base, declared_attr\n"
    assert {"SA001", "SA002"} <= rule_ids(src)


def test_unknown_declarative_name_is_not_rewritten():
    # An unfamiliar name means we cannot safely swap the whole module path.
    src = "from sqlalchemy.ext.declarative import declarative_base, something_odd\n"
    findings, out = analyze_source(src)
    assert out == src  # unchanged
    assert any(f.rule_id == "SA001" and not f.fixable for f in findings)


# --------------------------------------------------------------------------- #
# SA003 -- Query.get().
# --------------------------------------------------------------------------- #
def test_sa003_session_query_get_rewritten():
    src = "x = session.query(User).get(pk)\n"
    out = rewrite(src)
    assert out == "x = session.get(User, pk)\n"
    assert "SA003" in rule_ids(src)


def test_sa003_model_query_get_flagged_not_rewritten():
    src = "x = User.query.get(pk)\n"
    findings, out = analyze_source(src)
    assert out == src  # not rewritten
    sa003 = [f for f in findings if f.rule_id == "SA003"]
    assert sa003 and not sa003[0].fixable


# --------------------------------------------------------------------------- #
# SA004 -- Query API -> select().
# --------------------------------------------------------------------------- #
def test_sa004_simple_all_rewritten_and_select_imported():
    src = "import sqlalchemy\n\nrows = session.query(User).all()\n"
    out = rewrite(src)
    assert "from sqlalchemy import select" in out
    assert "session.execute(select(User)).scalars().all()" in out
    assert "SA004" in rule_ids(src)


def test_sa004_complex_chain_flagged_not_rewritten():
    src = "rows = session.query(User).order_by(User.id).all()\n"
    findings, out = analyze_source(src)
    assert out == src  # too complex to rewrite safely
    sa004 = [f for f in findings if f.rule_id == "SA004"]
    assert sa004 and not sa004[0].fixable


def test_sa004_select_not_duplicated_when_already_imported():
    src = "from sqlalchemy import select\n\nrows = session.query(User).all()\n"
    out = rewrite(src)
    assert out.count("from sqlalchemy import select") == 1


# --------------------------------------------------------------------------- #
# SA005 -- Query.filter.
# --------------------------------------------------------------------------- #
def test_sa005_filter_flagged():
    src = "q = session.query(User).filter(User.id == 1)\n"
    ids = rule_ids(src)
    assert "SA005" in ids


def test_sa005_filter_by_flagged():
    src = "q = session.query(User).filter_by(id=1)\n"
    assert "SA005" in rule_ids(src)


# --------------------------------------------------------------------------- #
# SA006 -- implicit / string SQL execution.
# --------------------------------------------------------------------------- #
def test_sa006_engine_execute_flagged():
    src = "engine.execute('SELECT 1')\n"
    findings = analyze_source(src)[0]
    sa006 = [f for f in findings if f.rule_id == "SA006"]
    assert sa006 and not sa006[0].fixable


def test_sa006_conn_string_execute_flagged():
    src = "conn.execute('SELECT 1')\n"
    assert "SA006" in rule_ids(src)


def test_sa006_session_execute_select_not_flagged():
    # The correct 2.0 idiom must never be flagged.
    src = "session.execute(select(User))\n"
    assert "SA006" not in rule_ids(src)


# --------------------------------------------------------------------------- #
# SA007 -- Column() -> Mapped/mapped_column.
# --------------------------------------------------------------------------- #
def test_sa007_column_attribute_flagged():
    src = (
        "class User(Base):\n"
        "    id = Column(Integer, primary_key=True)\n"
    )
    findings, out = analyze_source(src)
    assert out == src  # flag-only, never rewritten
    sa007 = [f for f in findings if f.rule_id == "SA007"]
    assert sa007 and not sa007[0].fixable


# --------------------------------------------------------------------------- #
# Registry / selection.
# --------------------------------------------------------------------------- #
def test_every_rule_has_doc_url_and_explanation():
    for rule in RULES:
        assert rule.doc_url.startswith("https://async-workflows.com/")
        assert rule.explanation.strip()
        assert rule.summary.strip()


def test_rule_selection_limits_findings():
    src = "from sqlalchemy.ext.declarative import declarative_base\n"
    findings, _ = analyze_source(src, enabled=frozenset({"SA003"}))
    assert findings == []


def test_all_rule_ids_matches_registry():
    assert ALL_RULE_IDS == {r.id for r in RULES}
