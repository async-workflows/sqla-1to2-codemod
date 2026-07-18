# sqla-1to2-codemod

A conservative command-line codemod that upgrades legacy **SQLAlchemy 1.x** code to
modern **2.0** style — it rewrites the patterns that are provably safe and flags the
rest with actionable guidance, so you never end up with silently-broken code.

By default it prints a unified diff (a dry run) and changes nothing. Every finding is
tagged with a stable rule id and a one-line explanation, and unrewritable patterns are
reported instead of guessed at.

## Before → after

Given this legacy module:

```python
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

def get_user(session, user_id):
    return session.query(User).get(user_id)

def all_users(session):
    return session.query(User).all()
```

`sqla-1to2-codemod app.py --write` produces:

```python
from sqlalchemy.orm import declarative_base
from sqlalchemy import select

Base = declarative_base()

def get_user(session, user_id):
    return session.get(User, user_id)

def all_users(session):
    return session.execute(select(User)).scalars().all()
```

Rewrites preserve your formatting and comments — the tool is built on
[LibCST](https://libcst.readthedocs.io/), a concrete syntax tree, not a regex pass.

## Install

The tool is distributed from GitHub (it is **not** on PyPI):

```bash
pip install "git+https://github.com/async-workflows/sqla-1to2-codemod.git"
```

It requires Python 3.10+ and installs [LibCST](https://libcst.readthedocs.io/) as its
only runtime dependency.

## Usage

Scan a path (dry run — prints a diff of proposed changes and a grouped summary of
flags, exit code 0):

```bash
sqla-1to2-codemod path/to/project/
```

| Flag | Effect |
| --- | --- |
| _(none)_ | Dry run: print a unified diff plus a grouped flag summary, exit 0. |
| `--write` | Apply the safe rewrites in place. |
| `--check` | Exit non-zero if any legacy pattern is found (for CI gates). |
| `--rules SA001,SA003` | Run only the listed rules. |
| `--json` | Emit a machine-readable report: a list of `{file, line, rule_id, summary, fixable}`. |
| `--explain SA004` | Print a rule's full explanation and documentation link, then exit. |
| `--list-rules` | List every available rule and exit. |
| `--version` | Print the version and exit. |

You can pass multiple files or directories; directories are searched recursively for
`.py` files.

## Rules

| Rule | Pattern | Action |
| --- | --- | --- |
| `SA001` | `from sqlalchemy.ext.declarative import declarative_base` | **Auto-fix** → `from sqlalchemy.orm import declarative_base` |
| `SA002` | `from sqlalchemy.ext.declarative import declared_attr` | **Auto-fix** → `from sqlalchemy.orm import declared_attr` |
| `SA003` | `session.query(Model).get(pk)` | **Auto-fix** → `session.get(Model, pk)`; `Model.query.get(pk)` is flagged |
| `SA004` | `session.query(...)` | **Auto-fix** the simple `.all()` shape → `session.execute(select(...)).scalars().all()`; richer chains are flagged |
| `SA005` | `Query.filter(...)` / `filter_by(...)` | **Flag** — migrate to `select().where(...)` |
| `SA006` | `engine.execute(...)` / `conn.execute("raw sql")` | **Flag** — use a connection + `text()` in an explicit transaction |
| `SA007` | `x = Column(...)` in a model | **Flag** — adopt `x: Mapped[...] = mapped_column(...)` |

Run `sqla-1to2-codemod --explain SA00X` for the full rationale and a link to the
relevant migration guide.

## Continuous integration

Use `--check` to fail a build when legacy patterns remain. It exits non-zero as soon
as any rule matches, so it doubles as a ratchet once a module is migrated:

```yaml
# .github/workflows/ci.yml
- name: Check for legacy SQLAlchemy 1.x patterns
  run: |
    pip install "git+https://github.com/async-workflows/sqla-1to2-codemod.git"
    sqla-1to2-codemod src/ --check
```

Prefer machine-readable output? `sqla-1to2-codemod src/ --json` emits one JSON object
per finding for your own dashboards or review bots.

## Limitations and safety

- **Rewrites are deliberately narrow.** Only shapes that are provably behaviour-
  preserving are changed (import relocations, `Query.get()`, and the single-entity
  `session.query(Model).all()`). Everything else is flagged so a human keeps control.
- **`SA004` only rewrites the trivial `.all()` case.** Any filters, ordering, joins,
  column selections, or terminal methods such as `.first()` / `.one()` are reported,
  not auto-migrated.
- **`SA007` never rewrites.** Turning `Column(Integer)` into `Mapped[int]` would flip a
  column from nullable to NOT NULL, since 2.0 infers nullability from the annotation, so
  the codemod recommends the change but leaves the exact annotation to you.
- **Heuristics can over-flag.** `SA006` keys off receiver names (`engine`, `conn`,
  `connection`) and string-literal arguments, so a non-SQLAlchemy `cursor.execute("...")`
  may be flagged. Review flags before acting on them.
- Run it in dry-run mode first, review the diff, then re-run with `--write`. Rewrites are
  idempotent — running twice makes no further changes.

## Further reading

Deeper background on the migration these rules automate:

- [Migrating legacy 1.4 code to 2.0 syntax](https://www.async-workflows.com/mastering-sqlalchemy-20-core-and-orm-architecture/migrating-legacy-14-code-to-20-syntax/) — the overall upgrade path.
- [The legacy 1.4-to-2.0 codemod checklist](https://www.async-workflows.com/mastering-sqlalchemy-20-core-and-orm-architecture/migrating-legacy-14-code-to-20-syntax/legacy-1-4-to-2-0-codemod-checklist/) — a step-by-step companion to this tool.
- [Replacing `Query.filter` with `select().where`](https://www.async-workflows.com/mastering-sqlalchemy-20-core-and-orm-architecture/core-vs-orm-architecture-decisions/how-to-replace-queryfilter-with-selectwhere-in-sqlalchemy-20/) — the reasoning behind `SA004` and `SA005`.
- [Fixing `RemovedIn20Warning` deprecation warnings](https://www.async-workflows.com/mastering-sqlalchemy-20-core-and-orm-architecture/migrating-legacy-14-code-to-20-syntax/fixing-removedin20warning-deprecation-warnings/) — context for `SA001`, `SA002`, and `SA006`.
- [A step-by-step guide to SQLAlchemy 2.0 type annotations](https://www.async-workflows.com/mastering-sqlalchemy-20-core-and-orm-architecture/migrating-legacy-14-code-to-20-syntax/step-by-step-guide-to-sqlalchemy-20-type-annotations/) — the typed `Mapped[...]` style behind `SA007`.

## License

[MIT](LICENSE) © 2026 async-workflows
