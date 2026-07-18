"""Detection and (conservative) transformation engine.

Built on `libcst <https://libcst.readthedocs.io/>`_ so that rewrites preserve the
original formatting, comments and whitespace of the source file. The public entry
point is :func:`analyze_source`, which returns the findings for a piece of source
plus the rewritten source (identical to the input when nothing safe could be
changed).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

import libcst as cst
from libcst.metadata import PositionProvider

from .rules import ALL_RULE_IDS, RULES_BY_ID

# Names that simply relocated from ``sqlalchemy.ext.declarative`` to
# ``sqlalchemy.orm``. When *every* name imported on a line is in this set the
# import can be rewritten by swapping the module path.
_MOVED_TO_ORM = {"declarative_base": "SA001", "declared_attr": "SA002"}

# Base object names that indicate legacy Core execution for SA006.
_ENGINE_LIKE = {"engine", "conn", "connection"}

_STRING_NODES = (cst.SimpleString, cst.ConcatenatedString, cst.FormattedString)


@dataclass
class Finding:
    """A single detected legacy pattern."""

    rule_id: str
    line: int
    summary: str
    fixable: bool
    file: str = "<string>"

    def as_dict(self) -> dict:
        data = asdict(self)
        # Stable, machine-friendly ordering for --json output.
        return {
            "file": data["file"],
            "line": data["line"],
            "rule_id": data["rule_id"],
            "summary": data["summary"],
            "fixable": data["fixable"],
        }


# --------------------------------------------------------------------------- #
# Small structural helpers on libcst nodes.
# --------------------------------------------------------------------------- #
def _dotted_name(node: cst.BaseExpression) -> str | None:
    """Return a dotted-name string for ``a.b.c`` style expressions, else None."""

    if isinstance(node, cst.Name):
        return node.value
    if isinstance(node, cst.Attribute):
        base = _dotted_name(node.value)
        if base is None:
            return None
        return f"{base}.{node.attr.value}"
    return None


def _method_call(node: cst.Call) -> tuple[str, cst.BaseExpression] | None:
    """If ``node`` is ``<expr>.<method>(...)`` return ``(method, <expr>)``."""

    func = node.func
    if isinstance(func, cst.Attribute):
        return func.attr.value, func.value
    return None


def _is_query_call(node: cst.BaseExpression) -> bool:
    """True for a ``<expr>.query(...)`` call node."""

    if not isinstance(node, cst.Call):
        return False
    call = _method_call(node)
    return call is not None and call[0] == "query"


def _base_label(expr: cst.BaseExpression) -> str | None:
    """Last identifier of a receiver, e.g. ``db.engine`` -> ``engine``."""

    if isinstance(expr, cst.Name):
        return expr.value
    if isinstance(expr, cst.Attribute):
        return expr.attr.value
    return None


def _first_arg_is_string(node: cst.Call) -> bool:
    return bool(node.args) and isinstance(node.args[0].value, _STRING_NODES)


# --------------------------------------------------------------------------- #
# Detection pass (metadata-aware, top-down so parents are seen before children).
# --------------------------------------------------------------------------- #
class _FindingCollector(cst.CSTVisitor):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, enabled: frozenset[str]) -> None:
        super().__init__()
        self.enabled = enabled
        self.findings: list[Finding] = []
        # ``id()`` of query-call nodes already accounted for by an outer
        # fixable pattern (SA003 get / SA004 all), so we do not double-flag them.
        self._consumed_query_calls: set[int] = set()

    def _line(self, node: cst.CSTNode) -> int:
        return self.get_metadata(PositionProvider, node).start.line

    def _add(self, rule_id: str, node: cst.CSTNode, fixable: bool) -> None:
        if rule_id not in self.enabled:
            return
        self.findings.append(
            Finding(
                rule_id=rule_id,
                line=self._line(node),
                summary=RULES_BY_ID[rule_id].summary,
                fixable=fixable,
            )
        )

    # -- imports (SA001 / SA002) -------------------------------------------- #
    def visit_ImportFrom(self, node: cst.ImportFrom) -> None:
        module = _dotted_name(node.module) if node.module is not None else None
        if module != "sqlalchemy.ext.declarative":
            return
        if isinstance(node.names, cst.ImportStar):
            return
        names = [alias.name.value for alias in node.names]
        all_moved = all(name in _MOVED_TO_ORM for name in names)
        for name in names:
            rule_id = _MOVED_TO_ORM.get(name)
            if rule_id is not None:
                self._add(rule_id, node, fixable=all_moved)

    # -- assignments (SA007) ------------------------------------------------ #
    def visit_Assign(self, node: cst.Assign) -> None:
        value = node.value
        if isinstance(value, cst.Call):
            func = value.func
            is_column = (isinstance(func, cst.Name) and func.value == "Column") or (
                isinstance(func, cst.Attribute) and func.attr.value == "Column"
            )
            if is_column:
                self._add("SA007", node, fixable=False)

    # -- calls (SA003 / SA004 / SA005 / SA006) ------------------------------ #
    def visit_Call(self, node: cst.Call) -> None:
        call = _method_call(node)
        if call is None:
            return
        method, base = call

        # SA003 -- primary-key get lookups.
        if method == "get":
            if _is_query_call(base):
                inner = base  # the <x>.query(<Model>) call
                fixable = (
                    isinstance(inner, cst.Call)
                    and len(inner.args) == 1
                    and len(node.args) == 1
                )
                self._add("SA003", node, fixable=fixable)
                self._consumed_query_calls.add(id(inner))
                return
            if isinstance(base, cst.Attribute) and base.attr.value == "query":
                # Model.query.get(pk) -- flag only.
                self._add("SA003", node, fixable=False)
                return

        # SA004 -- session.query(Model).all() fixable shape.
        if (
            method == "all"
            and not node.args
            and _is_query_call(base)
            and isinstance(base, cst.Call)
            and len(base.args) == 1
        ):
            self._add("SA004", node, fixable=True)
            self._consumed_query_calls.add(id(base))
            return

        # SA005 -- legacy Query filter/filter_by.
        if method in ("filter", "filter_by"):
            self._add("SA005", node, fixable=False)
            # Fall through: the inner .query(...) is still reported by SA004.

        # SA006 -- engine/connection execute or string SQL.
        if method == "execute":
            label = _base_label(base)
            if label in _ENGINE_LIKE or _first_arg_is_string(node):
                self._add("SA006", node, fixable=False)

        # SA004 -- any other legacy session.query(...) usage (flag).
        if method == "query" and id(node) not in self._consumed_query_calls:
            self._add("SA004", node, fixable=False)


# --------------------------------------------------------------------------- #
# Transformation pass (rewrites the safe shapes).
# --------------------------------------------------------------------------- #
class _Rewriter(cst.CSTTransformer):
    def __init__(self, enabled: frozenset[str], has_select_import: bool) -> None:
        super().__init__()
        self.enabled = enabled
        self._has_select_import = has_select_import
        self.needs_select = False

    # -- imports ------------------------------------------------------------ #
    def leave_ImportFrom(
        self, original_node: cst.ImportFrom, updated_node: cst.ImportFrom
    ) -> cst.ImportFrom:
        module = (
            _dotted_name(updated_node.module) if updated_node.module is not None else None
        )
        if module != "sqlalchemy.ext.declarative":
            return updated_node
        if isinstance(updated_node.names, cst.ImportStar):
            return updated_node
        names = [alias.name.value for alias in updated_node.names]
        if not names or not all(name in _MOVED_TO_ORM for name in names):
            return updated_node
        # Only rewrite when every affected rule is enabled.
        if not all(_MOVED_TO_ORM[name] in self.enabled for name in names):
            return updated_node
        new_module = cst.Attribute(
            value=cst.Name("sqlalchemy"), attr=cst.Name("orm")
        )
        return updated_node.with_changes(module=new_module)

    # -- calls -------------------------------------------------------------- #
    def leave_Call(
        self, original_node: cst.Call, updated_node: cst.Call
    ) -> cst.BaseExpression:
        call = _method_call(updated_node)
        if call is None:
            return updated_node
        method, base = call

        # SA003: <x>.query(<Model>).get(<pk>) -> <x>.get(<Model>, <pk>)
        if (
            "SA003" in self.enabled
            and method == "get"
            and _is_query_call(base)
            and isinstance(base, cst.Call)
            and len(base.args) == 1
            and len(updated_node.args) == 1
        ):
            query_call = base
            session_obj = query_call.func.value  # type: ignore[union-attr]
            model_value = query_call.args[0].value
            pk_value = updated_node.args[0].value
            return cst.Call(
                func=cst.Attribute(value=session_obj, attr=cst.Name("get")),
                args=[cst.Arg(value=model_value), cst.Arg(value=pk_value)],
            )

        # SA004: <x>.query(<Model>).all()
        #        -> <x>.execute(select(<Model>)).scalars().all()
        if (
            "SA004" in self.enabled
            and method == "all"
            and not updated_node.args
            and _is_query_call(base)
            and isinstance(base, cst.Call)
            and len(base.args) == 1
        ):
            query_call = base
            session_obj = query_call.func.value  # type: ignore[union-attr]
            model_value = query_call.args[0].value
            self.needs_select = True
            select_call = cst.Call(
                func=cst.Name("select"), args=[cst.Arg(value=model_value)]
            )
            execute_call = cst.Call(
                func=cst.Attribute(value=session_obj, attr=cst.Name("execute")),
                args=[cst.Arg(value=select_call)],
            )
            scalars_call = cst.Call(
                func=cst.Attribute(value=execute_call, attr=cst.Name("scalars")),
                args=[],
            )
            return cst.Call(
                func=cst.Attribute(value=scalars_call, attr=cst.Name("all")),
                args=[],
            )

        return updated_node

    # -- module: inject `from sqlalchemy import select` if we used it ------- #
    def leave_Module(
        self, original_node: cst.Module, updated_node: cst.Module
    ) -> cst.Module:
        if not self.needs_select or self._has_select_import:
            return updated_node

        import_line = cst.SimpleStatementLine(
            body=[
                cst.ImportFrom(
                    module=cst.Name("sqlalchemy"),
                    names=[cst.ImportAlias(name=cst.Name("select"))],
                )
            ]
        )

        body = list(updated_node.body)
        insert_at = 0
        for index, stmt in enumerate(body):
            if _is_import_line(stmt):
                insert_at = index + 1
            elif index == 0 and _is_docstring_line(stmt):
                insert_at = 1
        body.insert(insert_at, import_line)
        return updated_node.with_changes(body=tuple(body))


def _is_import_line(stmt: cst.CSTNode) -> bool:
    return isinstance(stmt, cst.SimpleStatementLine) and any(
        isinstance(node, (cst.Import, cst.ImportFrom)) for node in stmt.body
    )


def _is_docstring_line(stmt: cst.CSTNode) -> bool:
    return (
        isinstance(stmt, cst.SimpleStatementLine)
        and len(stmt.body) == 1
        and isinstance(stmt.body[0], cst.Expr)
        and isinstance(stmt.body[0].value, (cst.SimpleString, cst.ConcatenatedString))
    )


def _has_select_import(module: cst.Module) -> bool:
    """True if the module already imports the name ``select``."""

    found = False

    class _Scan(cst.CSTVisitor):
        def visit_ImportFrom(self, node: cst.ImportFrom) -> None:
            nonlocal found
            if isinstance(node.names, cst.ImportStar):
                return
            for alias in node.names:
                bound = alias.asname.name if alias.asname else alias.name
                if isinstance(bound, cst.Name) and bound.value == "select":
                    found = True

    module.visit(_Scan())
    return found


# --------------------------------------------------------------------------- #
# Public API.
# --------------------------------------------------------------------------- #
def normalize_rules(rule_ids: Iterable[str] | None) -> frozenset[str]:
    """Validate and normalise a selection of rule ids (``None`` -> all rules)."""

    if rule_ids is None:
        return frozenset(ALL_RULE_IDS)
    selected = {r.strip().upper() for r in rule_ids if r.strip()}
    unknown = selected - ALL_RULE_IDS
    if unknown:
        raise ValueError(
            "Unknown rule id(s): " + ", ".join(sorted(unknown))
        )
    return frozenset(selected)


def analyze_source(
    source: str,
    enabled: frozenset[str] | None = None,
    filename: str = "<string>",
) -> tuple[list[Finding], str]:
    """Analyse ``source`` and return ``(findings, new_source)``.

    ``new_source`` equals ``source`` when no safe rewrite applied. Raises
    :class:`libcst.ParserSyntaxError` if the source cannot be parsed.
    """

    if enabled is None:
        enabled = frozenset(ALL_RULE_IDS)

    module = cst.parse_module(source)
    wrapper = cst.MetadataWrapper(module)

    collector = _FindingCollector(enabled)
    wrapper.visit(collector)
    for finding in collector.findings:
        finding.file = filename
    collector.findings.sort(key=lambda f: (f.line, f.rule_id))

    rewriter = _Rewriter(enabled, has_select_import=_has_select_import(module))
    new_module = module.visit(rewriter)

    return collector.findings, new_module.code
