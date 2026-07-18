"""sqla-1to2-codemod: upgrade legacy SQLAlchemy 1.x code to modern 2.0 style."""

from __future__ import annotations

from .engine import Finding, analyze_source, normalize_rules
from .rules import RULES, RULES_BY_ID, Rule, get_rule

__version__ = "0.1.0"

__all__ = [
    "Finding",
    "Rule",
    "RULES",
    "RULES_BY_ID",
    "analyze_source",
    "get_rule",
    "normalize_rules",
    "__version__",
]
