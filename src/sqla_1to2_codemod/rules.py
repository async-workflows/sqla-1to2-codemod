"""Rule registry for sqla-1to2-codemod.

Each :class:`Rule` describes one legacy SQLAlchemy 1.x pattern the codemod knows
how to detect. The detection and transformation logic lives in
:mod:`sqla_1to2_codemod.engine`; this module is the single source of truth for
rule identity, human-facing text and documentation links.
"""

from __future__ import annotations

from dataclasses import dataclass

# Documentation pages on async-workflows.com used as the canonical guidance for
# each rule. Kept as named constants so the same URL is reused consistently.
_DOC_MIGRATE = (
    "https://async-workflows.com/mastering-sqlalchemy-20-core-and-orm-architecture/"
    "migrating-legacy-14-code-to-20-syntax/"
)
_DOC_CHECKLIST = (
    "https://async-workflows.com/mastering-sqlalchemy-20-core-and-orm-architecture/"
    "migrating-legacy-14-code-to-20-syntax/legacy-1-4-to-2-0-codemod-checklist/"
)
_DOC_QUERY_TO_SELECT = (
    "https://async-workflows.com/mastering-sqlalchemy-20-core-and-orm-architecture/"
    "core-vs-orm-architecture-decisions/"
    "how-to-replace-queryfilter-with-selectwhere-in-sqlalchemy-20/"
)
_DOC_REMOVEDIN20 = (
    "https://async-workflows.com/mastering-sqlalchemy-20-core-and-orm-architecture/"
    "migrating-legacy-14-code-to-20-syntax/fixing-removedin20warning-deprecation-warnings/"
)
_DOC_TYPING = (
    "https://async-workflows.com/mastering-sqlalchemy-20-core-and-orm-architecture/"
    "migrating-legacy-14-code-to-20-syntax/step-by-step-guide-to-sqlalchemy-20-type-annotations/"
)


@dataclass(frozen=True)
class Rule:
    """A single codemod rule."""

    id: str
    summary: str
    #: ``True`` when the rule *can* rewrite code automatically (at least for the
    #: simple shapes). ``False`` means the rule only ever flags for manual work.
    autofix: bool
    explanation: str
    doc_url: str


RULES: tuple[Rule, ...] = (
    Rule(
        id="SA001",
        summary="Deprecated declarative_base import location",
        autofix=True,
        explanation=(
            "In SQLAlchemy 2.0 `declarative_base` lives in `sqlalchemy.orm`, not in "
            "`sqlalchemy.ext.declarative` (which now only re-exports it for backwards "
            "compatibility and emits a RemovedIn20Warning). Rewrite\n"
            "    from sqlalchemy.ext.declarative import declarative_base\n"
            "to\n"
            "    from sqlalchemy.orm import declarative_base\n"
            "This is a pure import-location change and is always safe."
        ),
        doc_url=_DOC_REMOVEDIN20,
    ),
    Rule(
        id="SA002",
        summary="Deprecated declared_attr import location",
        autofix=True,
        explanation=(
            "`declared_attr` moved to `sqlalchemy.orm` in modern SQLAlchemy. Rewrite\n"
            "    from sqlalchemy.ext.declarative import declared_attr\n"
            "to\n"
            "    from sqlalchemy.orm import declared_attr\n"
            "A pure import-location change; the object itself is unchanged."
        ),
        doc_url=_DOC_REMOVEDIN20,
    ),
    Rule(
        id="SA003",
        summary="Query.get() / Model.query.get() replaced by Session.get()",
        autofix=True,
        explanation=(
            "`Query.get()` is legacy in 2.0. The primary-key lookup is now a first-class "
            "Session method:\n"
            "    session.query(Model).get(pk)   ->   session.get(Model, pk)\n"
            "The `session.query(Model).get(pk)` shape is rewritten automatically. The "
            "Flask-SQLAlchemy `Model.query.get(pk)` shape is only flagged, because the "
            "`Model.query` proxy hides which Session to call `.get()` on, so a safe "
            "mechanical rewrite is not possible."
        ),
        doc_url=_DOC_CHECKLIST,
    ),
    Rule(
        id="SA004",
        summary="Legacy Query API (session.query) should become select()",
        autofix=True,
        explanation=(
            "The 1.x `Session.query()` API is superseded by `select()` executed through "
            "`Session.execute()`:\n"
            "    session.query(Model).all()\n"
            "        ->  session.execute(select(Model)).scalars().all()\n"
            "The codemod rewrites only the simplest `session.query(Model).all()` shape "
            "(single entity, no filters) and adds `from sqlalchemy import select` if "
            "needed. Any richer chain (filters, ordering, joins, columns, `.first()`, "
            "`.one()`, ...) is flagged rather than rewritten, so you migrate it by hand "
            "and keep the behaviour provably correct."
        ),
        doc_url=_DOC_QUERY_TO_SELECT,
    ),
    Rule(
        id="SA005",
        summary="Query.filter()/filter_by() should become select().where()",
        autofix=True,
        explanation=(
            "On a legacy `Query`, `.filter(...)` and `.filter_by(...)` map onto "
            "`.where(...)` on a `select()` construct:\n"
            "    session.query(Model).filter(Model.x == 1)\n"
            "        ->  select(Model).where(Model.x == 1)\n"
            "Because a filter is almost always part of a larger query chain, this rule "
            "flags the call as part of the broader Query-to-select migration instead of "
            "rewriting a fragment in isolation."
        ),
        doc_url=_DOC_QUERY_TO_SELECT,
    ),
    Rule(
        id="SA006",
        summary="Implicit / string-SQL execution removed in 2.0",
        autofix=False,
        explanation=(
            "SQLAlchemy 2.0 removed 'connectionless'/implicit execution and the "
            "autocommit behaviour behind `engine.execute(...)`, and it no longer accepts "
            "a bare SQL string. Replace patterns like\n"
            "    engine.execute('UPDATE ...')\n"
            "    conn.execute('SELECT ...')\n"
            "with an explicit transaction and a `text()`-wrapped statement:\n"
            "    with engine.begin() as conn:\n"
            "        conn.execute(text('UPDATE ...'))\n"
            "This is flagged (not auto-fixed) because choosing the right transaction "
            "scope is a design decision the tool cannot make safely for you."
        ),
        doc_url=_DOC_REMOVEDIN20,
    ),
    Rule(
        id="SA007",
        summary="Column() attribute should use Mapped[...] = mapped_column()",
        autofix=False,
        explanation=(
            "Modern declarative models use PEP 484 typed attributes:\n"
            "    id = Column(Integer, primary_key=True)\n"
            "        ->  id: Mapped[int] = mapped_column(primary_key=True)\n"
            "This rule flags legacy `Column(...)` class attributes and recommends the "
            "typed `Mapped[...] = mapped_column(...)` form. It is intentionally "
            "flag-only: a blind `Column(Integer)` -> `Mapped[int]` rewrite would silently "
            "flip the column from nullable to NOT NULL (2.0 infers nullability from the "
            "annotation), so the correct annotation is left to you."
        ),
        doc_url=_DOC_TYPING,
    ),
)

RULES_BY_ID: dict[str, Rule] = {rule.id: rule for rule in RULES}
ALL_RULE_IDS: frozenset[str] = frozenset(RULES_BY_ID)


def get_rule(rule_id: str) -> Rule:
    """Return the rule with ``rule_id`` or raise ``KeyError``."""

    return RULES_BY_ID[rule_id]
