"""Rules this codebase states in prose, checked by parsing instead of trusted.

Each rule below is declared where a reader can find it — a docstring, a comment,
an archived design — and each has already been eroded once or is one edit away
from it. What they share is how they break: silently. Nothing raises, no suite
turns red, and a test that used to prove something starts proving something else
while still passing.

Every guard reads source with `ast` and imports nothing it inspects. An oracle
computed by the code it guards moves with the defect; a parsed declaration does
not. It also matters concretely for the first rule below, where what an import
binds *is* the defect.

Every guard asserts that its own scan reached its subject, and every one carries
a positive control: the same detector is pointed at a file that legitimately
holds what it hunts for, and must find it there. A guard that inspected nothing
passes, and that is how a guard goes blind rather than red.
"""

from __future__ import annotations

import ast
from pathlib import Path

#: The repository root, so failure messages name a path a reader can open.
_ROOT = Path(__file__).resolve().parents[1]


def _package() -> Path:
    """The source tree these guards read, located relative to this file.

    Deliberately not `jackryan.__file__`: importing the package would run the
    very code these guards are meant to judge independently of, and one of the
    rules here is about what an import binds. `tests/test_store.py` locates the
    package the same way.
    """
    package = _ROOT / "src" / "jackryan"
    assert package.is_dir(), (
        f"no package at {package}: it moved, and every guard in this file now "
        "checks nothing"
    )
    return package


def _where(path: Path) -> str:
    return path.relative_to(_ROOT).as_posix()


def _parsed(path: Path) -> ast.Module:
    """One module's syntax tree, refusing to inspect a file that is not there.

    The existence check is part of each guard's non-vacuity: a renamed module
    would otherwise turn an absence guard into an absence of guard.
    """
    assert path.is_file(), (
        f"no file at {_where(path) if path.is_relative_to(_ROOT) else path}: it "
        "moved or was renamed, and the guard reading it now checks nothing"
    )
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _bound_names(tree: ast.Module) -> dict[str, int]:
    """Every name an import or an assignment binds in a module, to its line.

    A re-export is an import or an assignment and nothing else, so those two are
    the whole search. `*` is excluded here and reported separately, because it
    binds names this scan cannot enumerate.
    """
    bound: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                # `import a.b.c` binds `a`; `import a.b as c` binds `c`.
                bound.setdefault(alias.asname or alias.name.split(".")[0], node.lineno)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name != "*":
                    bound.setdefault(alias.asname or alias.name, node.lineno)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    bound.setdefault(target.id, node.lineno)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            bound.setdefault(node.target.id, node.lineno)
    return bound


def _star_imports(tree: ast.Module) -> list[tuple[int, str]]:
    """Star imports, with the module each pulls from."""
    return [
        (node.lineno, "." * node.level + (node.module or ""))
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and any(alias.name == "*" for alias in node.names)
    ]


def _class_members(node: ast.ClassDef) -> dict[str, int]:
    """What a class body declares — methods, nested classes, fields — to lines.

    Only the body itself, never `ast.walk`: a name bound inside a method is a
    local, not a member, and counting it would make this fire on the wrong
    thing.
    """
    members: dict[str, int] = {}
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            members.setdefault(item.name, item.lineno)
        elif isinstance(item, ast.Assign):
            for target in item.targets:
                if isinstance(target, ast.Name):
                    members.setdefault(target.id, item.lineno)
        elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
            members.setdefault(item.target.id, item.lineno)
    return members


def _from_imports_of(tree: ast.Module, module: str) -> list[tuple[int, str]]:
    """`from …<module> import a, b` sites, with what each one pulls out.

    Matched on the last dotted component, so `from .migrations import x` and
    `from jackryan.storage.migrations import x` are one rule rather than two.
    `from . import migrations` is deliberately not matched: that binds the
    module object, which is the form the rule requires.
    """
    return [
        (node.lineno, ", ".join(alias.name for alias in node.names))
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module
        and node.module.split(".")[-1] == module
    ]


def _attributes_read_from(tree: ast.Module, name: str) -> set[str]:
    """Which attributes a module reads off the name `name`."""
    return {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == name
    }


def _imports_module(tree: ast.Module, module: str) -> list[tuple[int, str]]:
    """Every import that reaches `module`, however it is spelled.

    Three spellings reach one module and all three must be caught: `import
    pkg.module`, `from …module import name`, and `from …pkg import module`.
    """
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[-1] == module:
                    found.append((node.lineno, f"import {alias.name}"))
        elif isinstance(node, ast.ImportFrom):
            source = "." * node.level + (node.module or "")
            names = ", ".join(alias.name for alias in node.names)
            if (node.module or "").split(".")[-1] == module:
                found.append((node.lineno, f"from {source} import {names}"))
            else:
                for alias in node.names:
                    if alias.name == module:
                        found.append((node.lineno, f"from {source} import {module}"))
    return found


# -- 1. the window budget has one name ------------------------------------


#: The module that owns the budget, and the name that must not travel out of it.
_WINDOW_MODULE = "services/windowing.py"
_WINDOW_BUDGET = "MAX_RESPONSE_CHARS"


def test_search_does_not_re_export_the_window_budget():
    """`services/search.py` SHALL NOT bind `MAX_RESPONSE_CHARS`.

    Declared in the archived `one-owner-for-the-window-rule` design, under the
    heading "`MAX_RESPONSE_CHARS` is not re-exported from `search.py`": the
    constant moved to `services/windowing.py` and is deliberately not imported
    back, so a stale reference is an `ImportError` rather than a second name for
    one value.

    What a re-export costs is the only test the budget has. `Windower.for_results`
    reads the constant off its own module at call time, and
    `tests/test_section_windows.py` shrinks it with a `monkeypatch.setattr` on
    the windowing module to drive a response into its bound. With the name also
    present in `search.py`, patching the search module is the plausible-looking
    line someone writes instead — and it binds a name the widening loop never
    reads. The budget silently stays at 60,000, nothing narrows, and the test's
    own `assert narrowed` guard does not catch it: measured while the constant
    was being moved, the failure surfaced three assertions later on something
    unrelated. The rule holds today only because nobody has added the import.
    """
    package = _package()

    # Positive control: the collector must find this exact name where it does
    # live, or it is hunting something that no longer exists and would pass
    # whatever `search.py` did.
    windowing = _parsed(package / "services" / "windowing.py")
    assert _WINDOW_BUDGET in _bound_names(windowing), (
        f"{_WINDOW_BUDGET} is no longer declared in {_WINDOW_MODULE}; this "
        "guard's name collector now proves nothing"
    )

    search_path = package / "services" / "search.py"
    search = _parsed(search_path)
    bound = _bound_names(search)
    # And the subject was reached: these two are what `search.py` legitimately
    # takes from the windowing module, so seeing them proves the scan read this
    # file's imports rather than an empty tree.
    assert {"Windower", "DEFAULT_WINDOW_MAX_CHARS"} <= set(bound), (
        f"{_where(search_path)} no longer imports Windower or "
        "DEFAULT_WINDOW_MAX_CHARS; this guard is not reading what it thinks"
    )

    offences = []
    if _WINDOW_BUDGET in bound:
        offences.append(
            f"{_where(search_path)}:{bound[_WINDOW_BUDGET]} binds {_WINDOW_BUDGET}"
        )
    offences += [
        f"{_where(search_path)}:{lineno} star-imports {source}, which may bind "
        f"{_WINDOW_BUDGET} where this guard cannot see it"
        for lineno, source in _star_imports(search)
    ]
    assert not offences, (
        f"the window budget has a second name in {_where(search_path)}, so a "
        f"monkeypatch aimed there binds a name the widening loop never reads: "
        + "; ".join(offences)
    )


# -- 2. corpus identity renders and does not parse ------------------------


#: An inverse of `__str__` under either name it would plausibly be given. Two
#: names rather than one because the rule refuses the capability, not a spelling.
_PARSING_MEMBERS = ("parse", "from_string")


def test_corpus_identity_offers_no_parser():
    """`CorpusIdentity` SHALL NOT carry an inverse of `__str__`.

    Refused explicitly at `src/jackryan/config.py:327-331` and in the archived
    `one-value-for-corpus-identity` proposal.

    `tests/test_config.py` splits an identity string with a parser written for
    the test, to prove that a crafted embedder or summariser name cannot
    impersonate another component. Routing that test through a `parse` here
    would make the check and the thing checked one piece of code: an escaping
    bug would appear identically on both sides of the assertion, and the test
    would agree with the defect instead of catching it. A parser added for any
    other caller puts that test one refactor away from being rewritten to use
    it, which is why the refusal is of the method rather than of the call.
    """
    config_path = _package() / "config.py"
    config = _parsed(config_path)

    declared = [
        node
        for node in config.body
        if isinstance(node, ast.ClassDef) and node.name == "CorpusIdentity"
    ]
    assert declared, (
        f"no CorpusIdentity class in {_where(config_path)}: it was renamed or "
        "moved, and this guard now inspects nothing"
    )

    members = _class_members(declared[0])
    # Positive control: the member collector must see the rendering half, which
    # is the thing a parser would be the inverse of.
    assert "__str__" in members, (
        f"CorpusIdentity in {_where(config_path)} no longer declares __str__; "
        "this guard's member collector is reading the wrong body"
    )

    offences = [
        f"{_where(config_path)}:{members[name]} declares CorpusIdentity.{name}"
        for name in _PARSING_MEMBERS
        if name in members
    ]
    assert not offences, (
        "CorpusIdentity is deliberately not parseable; a parser here would let "
        "tests/test_config.py check escaping with the code that does it: "
        + "; ".join(offences)
    )


# -- 3. the store reaches the ladder through the module object ------------


_MIGRATIONS = "migrations"


def test_the_store_reaches_migrations_by_attribute():
    """`storage/sqlite.py` SHALL reach `migrations` through the module object.

    Declared in the archived `three-owners-in-the-store` design: "`sqlite.py`
    does not re-export any of them" — the same call the window change made one
    file over, for the same reason.

    `tests/test_migrations.py` exercises the ladder by patching module
    attributes: `_STEPS`, `SCHEMA_VERSION` and `backup_before_migrating` on
    `jackryan.storage.migrations`. A `from .migrations import SCHEMA_VERSION`
    here would copy the value into this module at import time, so the store
    would keep reading the real one while the test believed it had moved it.
    The patch goes half dead — the half that still works through the module
    object is enough to keep the test green — and the ladder's additive rule
    stops being checked against the code that runs it.
    """
    package = _package()

    # Positive control: the detector must find a real `from`-import of this
    # module where one exists. `tests/test_migrations.py` imports the ladder's
    # internals by name precisely so it can read them.
    control = _parsed(Path(__file__).resolve().parent / "test_migrations.py")
    assert _from_imports_of(control, _MIGRATIONS), (
        "tests/test_migrations.py no longer imports from jackryan.storage."
        f"{_MIGRATIONS}; this guard's import detector now proves nothing"
    )

    sqlite_path = package / "storage" / "sqlite.py"
    sqlite = _parsed(sqlite_path)

    bound = _bound_names(sqlite)
    assert _MIGRATIONS in bound, (
        f"{_where(sqlite_path)} does not bind the {_MIGRATIONS} module at all; "
        "this guard is reading the wrong file or the store stopped migrating"
    )
    reached = _attributes_read_from(sqlite, _MIGRATIONS)
    assert "SCHEMA_VERSION" in reached and len(reached) >= 3, (
        f"{_where(sqlite_path)} reads only {sorted(reached)} off {_MIGRATIONS}; "
        "the store no longer reaches the ladder the way this guard assumes"
    )

    offences = [
        f"{_where(sqlite_path)}:{lineno} imports {names} out of {_MIGRATIONS}"
        for lineno, names in _from_imports_of(sqlite, _MIGRATIONS)
    ]
    assert not offences, (
        "a from-import copies the ladder's values in at import time, leaving "
        "tests/test_migrations.py patching a module attribute the store no "
        "longer reads: " + "; ".join(offences)
    )


# -- 4. one definition per file signature ---------------------------------


#: A name marks a file signature when it says so. Narrower than "every bytes
#: constant" on purpose: an unrelated byte string — a terminator, a delimiter —
#: may legitimately equal another, and sweeping those in would make this fire on
#: something that is not the rule.
_SIGNATURE_MARKERS = ("MAGIC", "SIGNATURE")

#: The declarations that exist today, asserted as a floor. If a later change to
#: the collection rule stops finding these, the scan has gone blind and every
#: duplicate would pass. A floor rather than an exact set, because adding a new
#: signature is allowed — declaring one twice is not.
_KNOWN_SIGNATURES = {
    ("src/jackryan/ingestion/containers.py", "_RAR3_SIGNATURE"),
    ("src/jackryan/ingestion/containers.py", "_RAR5_SIGNATURE"),
    ("src/jackryan/ingestion/sniffing.py", "_OLE2_MAGIC"),
    ("src/jackryan/ingestion/sniffing.py", "_RTF_MAGIC"),
    ("src/jackryan/ingestion/sniffing.py", "_ZIP_MAGIC"),
}


def test_a_file_signature_has_one_definition():
    """No two declarations under `src/jackryan/` SHALL hold the same signature.

    Declared in `CLAUDE.md` — "`sniffing.py` owns every file signature, and
    `legacy_office` imports them by name" — and argued at
    `src/jackryan/ingestion/sniffing.py:93-106`.

    This is not hypothetical. `sniffing.py` and `legacy_office.py` each declared
    their own `_OLE2_MAGIC` and `_ZIP_MAGIC`, asking a wider and a narrower
    question about the same bytes. Two spellings of one fact drift apart
    silently: a file routes one way and converts another, with nothing raising
    anywhere, and the corpus ends up holding two renderings of one kind of
    document.

    Stated as duplicate detection rather than as "every signature lives in
    `sniffing.py`", because `ingestion/containers.py:527-528` legitimately holds
    the RAR signatures. Those answer a different question — which libarchive
    reader a file needs, not what the file is — and each generation's value is
    its own. The unit is therefore the declaration site: the defect that
    happened was one name declared in two files, which a name-collision check
    would have caught and a value-collision check across sites also catches.
    """
    package = _package()

    declarations: dict[bytes, list[str]] = {}
    sites: set[tuple[str, str]] = set()
    scanned = 0
    for module in sorted(package.rglob("*.py")):
        scanned += 1
        for node in ast.walk(_parsed(module)):
            if isinstance(node, ast.Assign):
                targets = [t for t in node.targets if isinstance(t, ast.Name)]
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                targets = [node.target]
            else:
                continue
            value = node.value
            if not isinstance(value, ast.Constant) or not isinstance(
                value.value, bytes
            ):
                continue
            for target in targets:
                if not any(m in target.id.upper() for m in _SIGNATURE_MARKERS):
                    continue
                sites.add((_where(module), target.id))
                declarations.setdefault(value.value, []).append(
                    f"{_where(module)}:{node.lineno} {target.id}"
                )

    assert scanned >= 20, (
        f"only {scanned} modules found under {_where(package)}; the package "
        "moved or thinned out and this scan no longer covers it"
    )
    missing = _KNOWN_SIGNATURES - sites
    assert not missing, (
        "the collection rule no longer finds signatures that are declared: "
        f"{sorted(missing)}. Until that is fixed this guard scans nothing and "
        "a duplicated signature would pass"
    )

    offences = [
        f"{value!r} is declared at " + " and at ".join(sorted(where))
        for value, where in sorted(declarations.items())
        if len(where) > 1
    ]
    assert not offences, (
        "one file signature has two owners, and two spellings of one fact drift "
        "apart with nothing raising: " + "; ".join(offences)
    )


# -- 5. the agent surface stays out of the shared renderers ---------------


_RENDERING = "rendering"


def test_the_agent_surface_does_not_import_the_shared_renderers():
    """Nothing under `src/jackryan/interfaces/` SHALL import `rendering`.

    Declared at `src/jackryan/rendering.py:14-19`: "**The agent surface is
    deliberately absent.**"

    `rendering.py` holds what the CLI and the REST route agree on, because those
    two describe a domain object for the same kind of reader — a person — and
    their copies had drifted. The MCP surface renders the same objects
    differently on purpose: `document_id` rather than `id`, every corpus value
    collapsed to one line, no chunk summary at all, and `tests/test_mcp_fencing.py`
    pins those differences. The risk the module's own docstring names is a
    reader concluding the third renderer is an oversight and finishing the job.
    Folding the agent surface in would make deliberate differences look like
    drift; unfolding them afterwards would change a payload an agent parses,
    which is a contract, not a presentation choice.
    """
    package = _package()

    # Positive control: the CLI does import the shared renderers, and the
    # detector must see it. Otherwise an interfaces module importing them the
    # same way would also go unseen.
    cli_path = package / "cli.py"
    assert _imports_module(_parsed(cli_path), _RENDERING), (
        f"{_where(cli_path)} no longer imports {_RENDERING}; this guard's "
        "import detector now proves nothing about the agent surface"
    )

    interfaces = package / "interfaces"
    assert interfaces.is_dir(), (
        f"no adapter package at {_where(interfaces)}: it moved, and this guard "
        "now checks nothing"
    )

    offences, scanned, relative_imports = [], 0, 0
    for module in sorted(interfaces.rglob("*.py")):
        scanned += 1
        tree = _parsed(module)
        relative_imports += sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.level > 0
        )
        offences += [
            f"{_where(module)}:{lineno} `{statement}`"
            for lineno, statement in _imports_module(tree, _RENDERING)
        ]

    assert scanned >= 5, (
        f"only {scanned} modules under {_where(interfaces)}; the agent surface "
        "moved and this guard no longer covers it"
    )
    # The offence this hunts is a relative import, so seeing several proves the
    # walk reached real import statements rather than an empty tree.
    assert relative_imports >= 5, (
        f"only {relative_imports} relative imports across {_where(interfaces)}; "
        "this scan is not reading what it thinks it is"
    )
    assert not offences, (
        "the agent surface reaches the two human surfaces' shared renderers; "
        "its payloads differ from theirs on purpose and those differences are "
        "a contract an agent parses: " + "; ".join(offences)
    )


# -- the agent surface's search bound is its own, tighter rule ----------------

_AGENT_SURFACE = "interfaces/mcp/server.py"
_SEARCH_CLAMP = "MAX_SEARCH_RESULTS"


def test_the_agent_search_bound_is_not_the_listing_bound():
    """The agent surface clamps a search below the service's own limit, by a literal.

    Declared at the listing-bound comment in `services/ingestion.py` and in the
    `guard-the-rules-that-had-only-prose` proposal: a search result carries
    prose while a listing row carries metadata, so the agent surface sets a
    tighter bound of its own. Folding it into the listing pair would raise the
    clamped maximum from 50 to 200 — four times the prose an agent asked for,
    with nothing in the payload saying so.

    Two assertions, because either alone is passable. The numeric one catches a
    value raised past the service limit. The literal one catches the coupling
    itself: `MAX_SEARCH_RESULTS = DEFAULT_LISTING_PAGE` is 50 today and would
    satisfy every numeric check, while making the search clamp move silently the
    next time a listing bound is retuned.

    This guard exists because the mutation proved it was needed: raising the
    constant to 200 left the entire suite green.
    """
    from jackryan.interfaces.mcp.server import MAX_SEARCH_RESULTS
    from jackryan.services.search import MAX_LIMIT

    module = _package() / _AGENT_SURFACE
    assignments = [
        node
        for node in ast.walk(_parsed(module))
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == _SEARCH_CLAMP
            for target in node.targets
        )
    ]
    # Without this the guard passes on a renamed or relocated constant, which is
    # the state it exists to notice.
    assert len(assignments) == 1, (
        f"expected exactly one {_SEARCH_CLAMP} assignment in {_where(module)}, "
        f"found {len(assignments)}; the bound moved and this guard is blind"
    )

    assert MAX_SEARCH_RESULTS < MAX_LIMIT, (
        f"{_SEARCH_CLAMP} is {MAX_SEARCH_RESULTS}, not below the service's own "
        f"MAX_LIMIT of {MAX_LIMIT}: the agent surface's bound is deliberately "
        "the tighter of the two, because a search result carries prose"
    )
    assert isinstance(assignments[0].value, ast.Constant) and isinstance(
        assignments[0].value.value, int
    ), (
        f"{_where(module)}:{assignments[0].lineno} sets {_SEARCH_CLAMP} from an "
        "expression rather than a literal, which couples the search clamp to "
        "whatever it names; a listing bound retuned later would move it too"
    )
