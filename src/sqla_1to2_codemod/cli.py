"""Command-line interface for sqla-1to2-codemod."""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable, Sequence

import libcst as cst

from . import __version__
from .engine import Finding, analyze_source, normalize_rules
from .rules import RULES, RULES_BY_ID


def _iter_python_files(paths: Iterable[str]) -> list[Path]:
    """Expand paths into a sorted, de-duplicated list of ``.py`` files."""

    seen: dict[Path, None] = {}
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            for candidate in sorted(path.rglob("*.py")):
                seen.setdefault(candidate, None)
        elif path.suffix == ".py":
            seen.setdefault(path, None)
        elif path.exists():
            # A non-python file given explicitly: skip silently.
            continue
        else:
            print(f"warning: path not found: {path}", file=sys.stderr)
    return list(seen)


def _unified_diff(original: str, updated: str, filename: str) -> str:
    diff = difflib.unified_diff(
        original.splitlines(keepends=True),
        updated.splitlines(keepends=True),
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
    )
    return "".join(diff)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sqla-1to2-codemod",
        description=(
            "Upgrade legacy SQLAlchemy 1.x code to modern 2.0 style. "
            "Shows a unified diff by default; use --write to apply changes."
        ),
    )
    parser.add_argument("paths", nargs="*", help="files or directories to scan")
    parser.add_argument(
        "--write",
        action="store_true",
        help="apply safe rewrites in place (default is dry-run diff)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if any legacy pattern is found (for CI)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="emit a machine-readable JSON report instead of diffs",
    )
    parser.add_argument(
        "--rules",
        metavar="IDS",
        help="comma-separated rule ids to run (e.g. SA001,SA003); default is all",
    )
    parser.add_argument(
        "--explain",
        metavar="RULE",
        help="print a rule's full explanation and documentation link, then exit",
    )
    parser.add_argument(
        "--list-rules",
        action="store_true",
        help="list all available rules and exit",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    return parser


def _cmd_explain(rule_id: str) -> int:
    rule = RULES_BY_ID.get(rule_id.strip().upper())
    if rule is None:
        print(f"error: unknown rule id: {rule_id}", file=sys.stderr)
        return 2
    fix = "auto-fixable" if rule.autofix else "flag only"
    print(f"{rule.id}  {rule.summary}  [{fix}]")
    print()
    print(rule.explanation)
    print()
    print(f"Docs: {rule.doc_url}")
    return 0


def _cmd_list_rules() -> int:
    for rule in RULES:
        fix = "fix " if rule.autofix else "flag"
        print(f"{rule.id}  [{fix}]  {rule.summary}")
    return 0


def _print_summary(findings: Sequence[Finding]) -> None:
    if not findings:
        print("No legacy SQLAlchemy 1.x patterns found.")
        return

    counts = Counter(f.rule_id for f in findings)
    print("Summary:")
    for rule_id in sorted(counts):
        rule = RULES_BY_ID[rule_id]
        tag = "auto-fix" if rule.autofix else "flag"
        print(
            f"  {rule_id}  [{tag:>8}]  {counts[rule_id]:>3}x  {rule.summary}"
        )

    flags = [f for f in findings if not f.fixable]
    if flags:
        print()
        print("Needs manual review:")
        for finding in flags:
            print(
                f"  {finding.file}:{finding.line}  {finding.rule_id}  "
                f"{finding.summary}"
            )


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.explain:
        return _cmd_explain(args.explain)
    if args.list_rules:
        return _cmd_list_rules()

    try:
        enabled = normalize_rules(
            args.rules.split(",") if args.rules else None
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not args.paths:
        print("error: no paths given (see --help)", file=sys.stderr)
        return 2

    files = _iter_python_files(args.paths)
    all_findings: list[Finding] = []
    changed_files: list[tuple[Path, str, str]] = []  # (path, original, updated)

    for path in files:
        try:
            original = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            print(f"warning: could not read {path}: {exc}", file=sys.stderr)
            continue
        try:
            findings, updated = analyze_source(
                original, enabled, filename=str(path)
            )
        except cst.ParserSyntaxError as exc:
            print(f"warning: could not parse {path}: {exc}", file=sys.stderr)
            continue
        all_findings.extend(findings)
        if updated != original:
            changed_files.append((path, original, updated))

    if args.as_json:
        payload = [f.as_dict() for f in all_findings]
        print(json.dumps(payload, indent=2))
    else:
        for path, original, updated in changed_files:
            sys.stdout.write(_unified_diff(original, updated, str(path)))
        if changed_files and not args.write:
            print()
        if args.write:
            for path, _original, updated in changed_files:
                path.write_text(updated, encoding="utf-8")
                print(f"rewrote {path}")
            if changed_files:
                print()
        _print_summary(all_findings)

    if args.check and all_findings:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
