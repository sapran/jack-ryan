"""Where identical bytes were found, and what survives a second copy.

Deduplication is correct and is not what these test. What they test is that the
*set* of places one file was found survives it — because that set is evidence of
shared custody and distribution, and the second copy used to overwrite the first
with no record that it had.

A location is one path, and the path is the whole of its identity. Two dumps
each holding `ledger.txt` at their top level are two places because their paths
differ; the same file reached by walking a folder and by naming it directly is
one place, however it was reached. Tests that put both copies inside one
ingested folder cannot see either case, so both are tested directly.

Whether a document's record is whole is derived from when recording began,
never from a stored claim. The interrupted-write tests below are the reason:
a claim written in a different transaction from the rows it describes can
outlive them, and a later observation then reads as the whole history.
"""

from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from jackryan.cli import _render_document as _render_cli_document
from jackryan.interfaces.mcp.server import _render_document as _render_mcp_document
from jackryan.interfaces.mcp.server import build_mcp_server
from jackryan.rendering import render_report
from jackryan.server import create_app

LEDGER = "# Ledger\n\nThe tariff was deferred until the following quarter.\n"


@pytest.fixture
def casefile(context):
    return context.casefiles.create("Harbour Inquiry")


async def call(server, name, args):
    """Drive a tool the way the transport does, not by reaching past it."""
    result = await server.call_tool(name, args)
    return json.loads(result.content[0].text)


def _zip(path, entries):
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return path


def _at(root, relative, text=LEDGER):
    """Write `text` at `root/relative`, making the directories it needs."""
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _rows(context, casefile, **kwargs):
    return context.ingestion.list_document_page(casefile.short_id, **kwargs).documents


def _only(context, casefile):
    documents = _rows(context, casefile)
    assert len(documents) == 1, f"expected one document, got {len(documents)}"
    return documents[0]


def _located(context, casefile, document):
    return context.ingestion.document_locations(casefile.short_id, document.short_id)


def _observation_rows(context, document_id):
    """Read the table directly: a row count is the thing under test here."""
    return context.store._db.execute(
        "SELECT location_path, first_seen_at FROM document_observations"
        " WHERE document_id = ? ORDER BY first_seen_at, location_path",
        (document_id,),
    ).fetchall()


def _lose_the_observation(context, document_id):
    """Leave the store in the state an interrupted first write leaves.

    The document row is committed and the observation that opens its record is
    not. Reproduced by deleting the row rather than by killing a process,
    because the resulting state is identical and a test can assert on it — PM
    verification reached the same state with an exit code.
    """
    context.store._db.execute(
        "DELETE FROM document_observations WHERE document_id = ?", (document_id,)
    )
    context.store._db.commit()


def _make_the_observation_write_fail(context):
    """Fail the observation insert, and only it, with a real sqlite abort.

    A trigger rather than a patched method — `sqlite3.Connection.execute` is
    read-only, and wrapping the connection would prove the wrapper rather than
    the transaction.

    Dropping the table was tried first and is the wrong injection: the identity
    lookup reads the observations in a correlated subquery, so a missing table
    fails *before* the document is ever inserted. That version of this test
    passed while the write it names was never reached, and mutation proving is
    what caught it. The trigger leaves every read working, so the document
    insert genuinely runs and genuinely has to be rolled back.
    """
    context.store._db.execute(
        "CREATE TRIGGER refuse_observations BEFORE INSERT ON document_observations"
        " BEGIN SELECT RAISE(ABORT, 'observation write failed'); END"
    )
    context.store._db.commit()


# -- one document, several places -----------------------------------------


def test_the_same_bytes_in_two_folders_keep_both_locations(context, casefile, tmp_path):
    dump = tmp_path / "dump"
    _at(dump, "custodian-a/ledger.txt")
    _at(dump, "custodian-b/ledger.txt")

    report = context.ingestion.ingest(casefile.short_id, dump)

    document = _only(context, casefile)
    record = _located(context, casefile, document)
    assert record.recorded.total == 2, (
        f"both locations must be recorded, got {record.recorded.total}"
    )
    assert {location.path for location in record.recorded.locations} == {
        f"{dump.resolve()}/custodian-a/ledger.txt",
        f"{dump.resolve()}/custodian-b/ledger.txt",
    }
    # And the listing marks it without anyone having to open the document,
    # which is what makes "found in several places" answerable by scanning.
    assert document.location_count == 2, (
        f"the listing did not mark the second location: {document.location_count}"
    )
    assert report.complete is True


def test_the_same_bytes_under_two_ingest_roots_keep_both_locations(
    context, casefile, tmp_path
):
    """The case a relative location cannot express.

    Both files are `ledger.txt` at the top of their own dump, so their paths
    within what was ingested are identical and only the absolute path
    distinguishes them. Keyed on the relative path alone the second observation
    would collide with the first and the second custodian would be lost —
    silently, which is the whole defect the record exists for.

    It is also the test that stops the opposite fix going too far. One file
    reached through two roots is one place, and collapsing by path is what
    makes that true; this asserts that the same collapse does not merge two
    custodians whose paths genuinely differ.
    """
    alpha = tmp_path / "custodian-alpha"
    beta = tmp_path / "custodian-beta"
    _at(alpha, "ledger.txt")
    _at(beta, "ledger.txt")

    context.ingestion.ingest(casefile.short_id, alpha)
    report = context.ingestion.ingest(casefile.short_id, beta)

    document = _only(context, casefile)
    record = _located(context, casefile, document)
    assert record.recorded.total == 2, (
        "two dumps sharing a relative path collapsed into one location: "
        f"{[location.path for location in record.recorded.locations]}"
    )
    assert {location.path for location in record.recorded.locations} == {
        f"{alpha.resolve()}/ledger.txt",
        f"{beta.resolve()}/ledger.txt",
    }
    assert report.new_locations == [f"{beta.resolve()}/ledger.txt"]
    assert [location.path for location in record.observed_at] == [
        f"{alpha.resolve()}/ledger.txt",
        f"{beta.resolve()}/ledger.txt",
    ], (
        "the disclosure did not name both custodians, earliest first: "
        f"{[location.path for location in record.observed_at]}"
    )


def test_a_copy_found_later_does_not_overwrite_the_first_location(
    context, casefile, tmp_path
):
    """Different filenames as well as different paths, deliberately.

    A filename is not part of a document's identity, so identical bytes under
    two names are still one document — and unless the two names differ, the
    `filename = excluded.filename` clause this test guards against is invisible.
    """
    first = tmp_path / "first"
    second = tmp_path / "second"
    _at(first, "ledger.txt")
    _at(second, "custodian-b/ledger-copy.txt")

    context.ingestion.ingest(casefile.short_id, first)
    before = _only(context, casefile)
    context.ingestion.ingest(casefile.short_id, second)
    after = _only(context, casefile)

    assert after.id == before.id, "a second copy must not mint a second document"
    # The whole defect: both of these were overwritten from `excluded`.
    assert after.containment_path == "ledger.txt", (
        f"the first containment path was overwritten: {after.containment_path}"
    )
    assert after.filename == "ledger.txt", (
        f"the first filename was overwritten: {after.filename}"
    )

    record = _located(context, casefile, after)
    assert record.recorded.total == 2
    assert [location.path for location in record.observed_at] == [
        f"{first.resolve()}/ledger.txt",
        f"{second.resolve()}/custodian-b/ledger-copy.txt",
    ]


def test_reversing_the_order_preserves_the_same_locations(context, casefile, tmp_path):
    """Two runs, not one folder: `_initial_work` sorts a walk, so the order
    inside a single run is already fixed and would prove nothing."""
    alpha = tmp_path / "alpha"
    beta = tmp_path / "beta"
    _at(alpha, "custodian-a/ledger.txt")
    _at(beta, "custodian-b/ledger.txt")

    context.ingestion.ingest(casefile.short_id, beta)
    context.ingestion.ingest(casefile.short_id, alpha)

    document = _only(context, casefile)
    record = _located(context, casefile, document)
    assert {location.path for location in record.recorded.locations} == {
        f"{alpha.resolve()}/custodian-a/ledger.txt",
        f"{beta.resolve()}/custodian-b/ledger.txt",
    }
    # Whichever was observed first is the one the document reports, and that is
    # the run that went first.
    assert document.containment_path == "custodian-b/ledger.txt"


def test_a_same_location_reingest_records_no_new_location(context, casefile, tmp_path):
    root = tmp_path / "root"
    _at(root, "ledger.txt")

    context.ingestion.ingest(casefile.short_id, root)
    again = context.ingestion.ingest(casefile.short_id, root)

    document = _only(context, casefile)
    record = _located(context, casefile, document)
    assert record.recorded.total == 1, (
        f"reingesting one path recorded {record.recorded.total} locations"
    )
    assert [o.location for o in again.outcomes] == ["known"], (
        "an ordinary reingest was reported as something else"
    )
    assert again.new_locations == []


def test_a_copy_at_a_new_location_does_not_make_the_run_incomplete(
    context, casefile, tmp_path
):
    first = tmp_path / "first"
    second = tmp_path / "second"
    _at(first, "ledger.txt")
    _at(second, "elsewhere/ledger.txt")

    context.ingestion.ingest(casefile.short_id, first)
    report = context.ingestion.ingest(casefile.short_id, second)

    assert [o.location for o in report.outcomes] == ["new"]
    assert report.new_locations == [f"{second.resolve()}/elsewhere/ledger.txt"]
    # A copy found somewhere new was read and stored, so the run covered
    # everything it was offered. A discovery is not a shortfall.
    assert report.complete is True, (
        f"a discovery made the run incomplete: {report.limitations}"
    )
    assert report.limitations == []


# -- expansions -----------------------------------------------------------


def test_an_attachment_on_two_messages_keeps_one_location_each(
    context, casefile, tmp_path
):
    """The existing expansion identity rule, unchanged: a path that is part of
    identity yields two documents, each with exactly one location."""
    bundle = _zip(
        tmp_path / "bundle.zip",
        [("first/report.txt", LEDGER), ("second/report.txt", LEDGER)],
    )

    context.ingestion.ingest(casefile.short_id, bundle)

    expanded = [d for d in _rows(context, casefile, include_expanded=True) if d.is_expanded]
    assert len(expanded) == 2, (
        f"identical bytes at two paths must be two documents: {expanded}"
    )
    for document in expanded:
        record = _located(context, casefile, document)
        assert record.recorded.total == 1
        # The path runs from the top-level file that was ingested down the
        # containment chain, so it is followable end to end: go to that
        # directory, open the archive, find this entry.
        assert [location.path for location in record.recorded.locations] == [
            f"{tmp_path.resolve()}/{document.containment_path}"
        ]


def test_reingesting_a_container_records_no_new_locations(context, casefile, tmp_path):
    """An expansion's bytes are materialised into a scratch directory that is
    new on every run. Recording that directory as the location would insert a
    fresh row and report a false discovery each time — so this asserts the row
    count does not grow and no discovery is reported."""
    bundle = _zip(tmp_path / "bundle.zip", [("first/report.txt", LEDGER)])

    context.ingestion.ingest(casefile.short_id, bundle)
    expanded = [d for d in _rows(context, casefile, include_expanded=True) if d.is_expanded]
    assert len(expanded) == 1
    before = _observation_rows(context, expanded[0].id)

    again = context.ingestion.ingest(casefile.short_id, bundle)

    after = _observation_rows(context, expanded[0].id)
    assert len(after) == len(before) == 1, (
        f"reingesting the container grew the location rows: {len(before)} -> {len(after)}"
    )
    assert [dict(r) for r in after] == [dict(r) for r in before]
    assert again.new_locations == [], (
        f"reingesting a container reported a discovery: {again.new_locations}"
    )


def test_a_document_that_predates_the_record_stays_unknown_across_a_reingest(
    context, casefile, tmp_path
):
    """Standing in for a corpus filled before locations were recorded.

    The flag is cleared by hand, which is exactly the state the migration
    leaves an existing row in. Reingesting must not launder it into a complete
    record: the copies it lost are still lost, so the verdict stays `unknown`,
    the caveat is offered, and the outcome is not reported as a discovery.
    """
    root = tmp_path / "root"
    _at(root, "ledger.txt")
    context.ingestion.ingest(casefile.short_id, root)
    document = _only(context, casefile)

    _lose_the_observation(context, document.id)

    elsewhere = tmp_path / "elsewhere"
    _at(elsewhere, "ledger.txt")
    report = context.ingestion.ingest(casefile.short_id, elsewhere)

    assert [o.location for o in report.outcomes] == ["unknown"], (
        "a document predating the record reported a location it cannot support"
    )
    # And therefore not a discovery: `new_locations` must stay empty, or the
    # run would announce a finding this instance cannot stand behind.
    assert report.new_locations == []

    record = _located(context, casefile, _only(context, casefile))
    assert record.verdict == "unknown", (
        f"a reingest laundered a migrated document into {record.verdict!r}"
    )
    assert record.note != "", "the unknown verdict was offered with no caveat"


def test_a_migrated_document_hides_no_recorded_location(context, casefile, tmp_path):
    """Every recorded location must reach a surface, verdict notwithstanding.

    For a migrated document the document's own path was written before any
    location row existed, so the earliest row is whatever the *next* ingest
    observed — not the one `containment_path` came from. Dropping it by
    position therefore hides the only copy the record holds, on the exact
    corpus this change exists to serve, while every surface still prints a
    count that includes it.
    """
    root = tmp_path / "custodian-a"
    _at(root, "ledger.txt")
    context.ingestion.ingest(casefile.short_id, root)
    document = _only(context, casefile)

    # Exactly what the migration leaves behind for an existing document.
    _lose_the_observation(context, document.id)

    second = tmp_path / "custodian-b"
    _at(second, "archive/ledger-copy.txt")
    context.ingestion.ingest(casefile.short_id, second)

    record = _located(context, casefile, _only(context, casefile))
    assert record.verdict == "unknown"
    assert record.recorded.total == 1
    shown = [location.path for location in record.observed_at]
    assert shown == [f"{second.resolve()}/archive/ledger-copy.txt"], (
        "the only recorded location reached no surface, while the count still "
        f"included it: {shown}"
    )


def test_a_migrated_document_is_marked_in_a_listing_at_its_first_location(
    context, casefile, tmp_path
):
    """The listing threshold has to account for the missing own-location row.

    A document created by the new code holds a row for its own location, so a
    second place means two rows. A migrated document holds none, so its *first*
    recorded row is already an additional place — and a bare `> 1` marks it one
    location too late, leaving the row a scan of the inventory cannot find.
    """
    root = tmp_path / "custodian-a"
    _at(root, "ledger.txt")
    context.ingestion.ingest(casefile.short_id, root)
    document = _only(context, casefile)

    _lose_the_observation(context, document.id)

    second = tmp_path / "custodian-b"
    _at(second, "archive/ledger-copy.txt")
    context.ingestion.ingest(casefile.short_id, second)

    row = _render_cli_document(_only(context, casefile))
    assert row.get("locations") == 1, (
        f"a migrated document's recorded location went unmarked: {row.get('locations')}"
    )


def test_a_flag_without_rows_is_unanswerable_rather_than_one_place(
    context, casefile, tmp_path
):
    """`complete` with an empty record must not render as "found in one place".

    The row and its location are two separate commits, so a death between them
    leaves the flag raised over an empty table. Read as complete, that produces
    a payload identical to a healthy single-location document — the one reading
    that is certainly wrong, and the only one with no caveat attached.
    """
    root = tmp_path / "root"
    _at(root, "ledger.txt")
    context.ingestion.ingest(casefile.short_id, root)
    document = _only(context, casefile)

    _lose_the_observation(context, document.id)

    record = _located(context, casefile, document)
    assert record.verdict == "unknown", (
        "a raised flag over an empty record was read as a whole one"
    )
    assert record.note != "", "the contradiction was offered with no caveat"


def test_the_shared_report_names_the_location_it_recorded(context, casefile, tmp_path):
    """A JSON or REST caller must be able to recover the location a run reported.

    `path` is where the bytes were read from, and for a document produced by
    expansion that is a scratch file deleted before the response is returned —
    asserted below, because it is the whole reason this field exists. Both human
    surfaces render this one function, so without it the CLI's text prints a
    location the JSON form cannot express.
    """
    first = tmp_path / "custodian-a"
    second = tmp_path / "custodian-b"
    first.mkdir()
    second.mkdir()
    _zip(first / "dump.zip", [("ledger.txt", LEDGER)])
    _zip(second / "dump.zip", [("ledger.txt", LEDGER)])

    context.ingestion.ingest(casefile.short_id, first)
    rendered = render_report(context.ingestion.ingest(casefile.short_id, second))

    discovered = [o for o in rendered["outcomes"] if o["location"] == "new"]
    assert discovered, f"no new location was reported: {rendered['outcomes']}"
    expanded = [o for o in discovered if o["location_path"].endswith("dump.zip/ledger.txt")]
    assert expanded, (
        "the expansion's new location was not named in the shared report: "
        f"{[o['location_path'] for o in discovered]}"
    )
    for outcome in expanded:
        assert outcome["location_path"] == f"{second.resolve()}/dump.zip/ledger.txt"
        assert not Path(outcome["path"]).exists(), (
            "the scratch path still resolves, so this test no longer proves why "
            "`location_path` is needed"
        )



def test_deleting_a_document_deletes_its_locations(context, casefile, tmp_path):
    root = tmp_path / "root"
    _at(root, "ledger.txt")
    context.ingestion.ingest(casefile.short_id, root)
    document = _only(context, casefile)

    assert context.store.delete_document(document.id) is True

    assert _observation_rows(context, document.id) == [], (
        "location rows outlived their document"
    )


# -- the agent surface ----------------------------------------------------


@pytest.mark.anyio
async def test_a_document_found_in_one_place_reads_exactly_as_it_did(
    context, casefile, tmp_path
):
    """The negative twin. Without this, emitting the block unconditionally
    passes every other test here."""
    root = tmp_path / "root"
    _at(root, "ledger.txt")
    context.ingestion.ingest(casefile.short_id, root)
    document = _only(context, casefile)

    server = build_mcp_server(context, "analyst")
    payload = await call(
        server,
        "case_read_document",
        {"casefile": casefile.short_id, "document": document.short_id},
    )

    assert "locations" not in payload["provenance"], (
        "a document found in one place gained a locations block: "
        f"{payload['provenance'].get('locations')}"
    )


@pytest.mark.anyio
async def test_a_document_found_in_two_places_says_so_in_its_provenance(
    context, casefile, tmp_path
):
    dump = tmp_path / "dump"
    _at(dump, "custodian-a/ledger.txt")
    _at(dump, "custodian-b/ledger.txt")
    context.ingestion.ingest(casefile.short_id, dump)
    document = _only(context, casefile)

    server = build_mcp_server(context, "analyst")
    payload = await call(
        server,
        "case_read_document",
        {"casefile": casefile.short_id, "document": document.short_id},
    )

    locations = payload["provenance"]["locations"]
    assert locations["recorded"] == "complete"
    assert locations["total"] == 2
    assert locations["truncated"] is False
    assert locations["observed_at"] == [
        f"{dump.resolve()}/custodian-a/ledger.txt",
        f"{dump.resolve()}/custodian-b/ledger.txt",
    ]
    # The document still reports one path, and it is the one a citation names.
    assert payload["provenance"]["found_at"] == "custodian-a/ledger.txt"


@pytest.mark.anyio
async def test_every_surface_reports_the_same_locations_verdict(
    context, casefile, tmp_path
):
    dump = tmp_path / "dump"
    _at(dump, "custodian-a/ledger.txt")
    _at(dump, "custodian-b/ledger.txt")
    context.ingestion.ingest(casefile.short_id, dump)
    document = _only(context, casefile)

    record = _located(context, casefile, document)
    service_paths = [location.path for location in record.observed_at]

    server = build_mcp_server(context, "analyst")
    payload = await call(
        server,
        "case_read_document",
        {"casefile": casefile.short_id, "document": document.short_id},
    )
    agent = payload["provenance"]["locations"]

    app = create_app(context)
    with TestClient(app) as client:
        rest = client.get(
            f"/api/casefiles/{casefile.short_id}/documents/{document.short_id}"
        ).json()

    assert record.verdict == agent["recorded"] == rest["locations_recorded"]
    assert service_paths == agent["observed_at"] == rest["observed_at"]
    assert record.recorded.total == agent["total"] == rest["locations"]


# -- one place, however it was reached ------------------------------------


def test_one_file_reached_through_two_roots_is_one_location(context, casefile, tmp_path):
    """The identity defect PM verification found.

    A location is a place, not an observation. Walking a folder and then naming
    the file inside it directly are two ways to the same file, and the prior
    key — the ingest root paired with the path within it — made them two
    locations: two rows, a `new` outcome for the second, and the identical
    rendered path shown twice.
    """
    dump = tmp_path / "dump"
    _at(dump, "sub/note.txt")

    context.ingestion.ingest(casefile.short_id, dump)
    named_directly = context.ingestion.ingest(casefile.short_id, dump / "sub" / "note.txt")
    its_folder = context.ingestion.ingest(casefile.short_id, dump / "sub")

    document = _only(context, casefile)
    record = _located(context, casefile, document)
    assert record.recorded.total == 1, (
        "one physical file was recorded as several places: "
        f"{[location.path for location in record.recorded.locations]}"
    )
    assert record.recorded.locations[0].path == f"{dump.resolve()}/sub/note.txt"
    # And neither later run claimed to have discovered anything.
    assert [o.location for o in named_directly.outcomes] == ["known"]
    assert [o.location for o in its_folder.outcomes] == ["known"]
    assert named_directly.new_locations == []
    assert its_folder.new_locations == []
    # Nothing to mark in a listing either: one place is the ordinary case.
    assert document.additional_locations == 0
    assert "locations" not in _render_cli_document(document)


def test_two_roots_holding_one_path_each_are_still_two_locations(
    context, casefile, tmp_path
):
    """The case the root was added for, which collapsing must not undo.

    Both files are `ledger.txt` at the top of their own dump, so their relative
    paths are identical and only the absolute path separates them. Keying on
    the path keeps them apart because the paths differ — this is the test that
    stops the fix for one file reached twice from merging two custodians.
    """
    alpha = tmp_path / "custodian-alpha"
    beta = tmp_path / "custodian-beta"
    _at(alpha, "ledger.txt")
    _at(beta, "ledger.txt")

    context.ingestion.ingest(casefile.short_id, alpha)
    report = context.ingestion.ingest(casefile.short_id, beta)

    record = _located(context, casefile, _only(context, casefile))
    assert {location.path for location in record.recorded.locations} == {
        f"{alpha.resolve()}/ledger.txt",
        f"{beta.resolve()}/ledger.txt",
    }
    assert record.verdict == "complete"
    assert report.new_locations == [f"{beta.resolve()}/ledger.txt"]


# -- an interrupted first write ------------------------------------------


def test_a_later_root_cannot_claim_the_history_of_an_interrupted_ingest(
    context, casefile, tmp_path
):
    """The acceptance blocker, at the transition rather than at rest.

    A document stored without the observation that opens its record reads
    `unknown`, which the previous change already got right. What it got wrong
    was the retry: one observation from a second root became the only row, the
    stored claim still said the record was whole, and the verdict flipped to
    `complete` while the place the document actually came from was never
    recorded and never could be.
    """
    root_a = tmp_path / "custodian-a"
    root_b = tmp_path / "custodian-b"
    _at(root_a, "ledger.txt")
    _at(root_b, "ledger.txt")

    context.ingestion.ingest(casefile.short_id, root_a)
    document = _only(context, casefile)
    _lose_the_observation(context, document.id)

    at_rest = _located(context, casefile, _only(context, casefile))
    assert at_rest.verdict == "unknown"
    assert at_rest.recorded.total == 0

    report = context.ingestion.ingest(casefile.short_id, root_b)

    after = _located(context, casefile, _only(context, casefile))
    assert after.recorded.total == 1
    assert after.verdict == "unknown", (
        "a later root turned missing history into a whole record: "
        f"{[location.path for location in after.recorded.locations]}"
    )
    assert after.note != "", "the unknown verdict was offered with no caveat"
    # Nor is it announced as a discovery: this instance cannot tell whether
    # root B was among the places it had already lost.
    assert [o.location for o in report.outcomes] == ["unknown"]
    assert report.new_locations == []
    # And it stays unknown however many more arrive.
    root_c = tmp_path / "custodian-c"
    _at(root_c, "ledger.txt")
    context.ingestion.ingest(casefile.short_id, root_c)
    still = _located(context, casefile, _only(context, casefile))
    assert still.recorded.total == 2
    assert still.verdict == "unknown", "a third sighting laundered the record"


def test_a_document_is_not_stored_without_its_observation(context, casefile, tmp_path):
    """One transaction, so the interrupted state is unreachable rather than handled.

    The observation insert is made to raise inside the call that stores the
    document. Both writes share a transaction, so neither may survive — if the
    document did, the state above would be reachable again by an ordinary
    failure.
    """
    root = tmp_path / "root"
    _at(root, "ledger.txt")

    _make_the_observation_write_fail(context)
    with pytest.raises(sqlite3.IntegrityError, match="observation write failed"):
        context.ingestion.ingest(casefile.short_id, root)

    surviving = context.store._db.execute(
        "SELECT COUNT(*) AS n FROM documents"
    ).fetchone()["n"]
    assert surviving == 0, (
        "a document survived the failure of the write that opens its record, so "
        "the interrupted state is reachable by an ordinary failure"
    )
    assert (
        context.store._db.execute(
            "SELECT COUNT(*) AS n FROM document_observations"
        ).fetchone()["n"]
        == 0
    )


def test_a_new_documents_record_begins_when_the_document_does(
    context, casefile, tmp_path
):
    """The equality the derived verdict rests on, asserted rather than assumed.

    A document and its first observation are written with one clock reading, so
    the earliest observation equals `created_at` and the record reads whole. A
    refactor that read the clock twice would leave the observation microseconds
    later and quietly report every new document as `unknown` — the safe
    direction, but wrong, and invisible without this.
    """
    root = tmp_path / "root"
    _at(root, "ledger.txt")
    context.ingestion.ingest(casefile.short_id, root)

    document = _only(context, casefile)
    record = _located(context, casefile, document)
    assert record.recorded.locations[0].first_seen_at == document.created_at, (
        "the first observation and the document were not written with one clock "
        f"reading: {record.recorded.locations[0].first_seen_at} vs {document.created_at}"
    )
    assert record.verdict == "complete"
    assert document.locations_are_whole is True

    # And through `resolve_document`, not only through the listing. The two
    # reach the store by different queries, and the rule needs values a query
    # has to select: one that omitted them would yield a document reading as
    # not whole, silently, on the path every single-document surface uses.
    resolved = context.ingestion.resolve_document(casefile.short_id, document.short_id)
    assert resolved.locations_are_whole is True, (
        "a freshly ingested document did not read as whole when resolved by "
        "reference, so a query on that path is missing what the rule needs"
    )
    assert resolved.location_count == 1
    assert resolved.additional_locations == 0
    # The same for the full identifier, which takes the other branch of
    # `resolve_document`, and for a prefix, which takes the third.
    by_id = context.ingestion.resolve_document(casefile.short_id, document.id)
    assert by_id.locations_are_whole is True


def test_the_port_cannot_store_a_document_without_saying_where(context):
    """A seam that can be used in the wrong order eventually is.

    Asserted against the port rather than the implementation, and by inspecting
    the signature rather than by calling it: what must not exist is the
    *option*, so a default value for the location would satisfy any call-based
    check while leaving the hazard in place.
    """
    import inspect

    from jackryan.storage.port import StorePort

    storing = [
        name
        for name, member in inspect.getmembers(StorePort, inspect.isfunction)
        if "document" in name and name.startswith(("store", "upsert", "insert", "save"))
    ]
    assert storing == ["store_document"], (
        f"another way to store a document appeared: {storing}"
    )
    parameters = inspect.signature(StorePort.store_document).parameters
    for required in ("location_path", "observed_at"):
        assert required in parameters, f"{required} is not part of storing a document"
        assert parameters[required].default is inspect.Parameter.empty, (
            f"{required} has a default, so a caller can omit it"
        )


def test_a_listing_mark_says_whether_the_count_is_the_whole_story(
    context, casefile, tmp_path
):
    """A count alone over-claims where the record began late.

    Reingest a pre-record document from the very place it came from and it has
    exactly one recorded observation — its own. `additional_locations` counts
    it, because for such a document nothing identifies which row is its own,
    and suppressing the mark instead would hide a genuine second place for a
    migrated document whose one row really is elsewhere.

    So the mark stays and the row says what it is worth. Without the verdict a
    listing reports "found in another place" for a file that was found in one,
    which is a false finding — and the change's own reasoning is that a false
    finding on this surface is worse than an absent one.
    """
    dump = tmp_path / "dump"
    _at(dump, "ledger.txt")
    context.ingestion.ingest(casefile.short_id, dump)
    document = _only(context, casefile)
    _lose_the_observation(context, document.id)

    # Reingested from the same root, so the single recorded place is its own.
    context.ingestion.ingest(casefile.short_id, dump)
    document = _only(context, casefile)
    record = _located(context, casefile, document)
    assert record.recorded.total == 1
    assert record.observed_at[0].path == f"{dump.resolve()}/ledger.txt"

    for label, row in (
        ("cli", _render_cli_document(document)),
        ("mcp", _render_mcp_document(document)),
    ):
        assert row.get("locations") == 1, f"{label}: the count went missing"
        assert row.get("locations_recorded") == "unknown", (
            f"{label}: the listing reported a second place with nothing to say the "
            f"count cannot be attributed: {row.get('locations_recorded')!r}"
        )

    # A document whose record is whole says so, and is not marked at all when
    # it was found in one place.
    other = tmp_path / "other"
    _at(other, "memo.txt", "# Memo\n\nA different document entirely.\n")
    context.ingestion.ingest(casefile.short_id, other)
    fresh = next(
        d for d in _rows(context, casefile) if d.filename == "memo.txt"
    )
    assert fresh.additional_locations == 0
    assert "locations" not in _render_cli_document(fresh)
    assert "locations_recorded" not in _render_cli_document(fresh)


def test_the_document_handed_back_by_the_store_does_not_misreport_itself(
    context, casefile, tmp_path
):
    """`store_document` returns the stored document; the value must be truthful.

    Nothing in the ingest reads wholeness off this return value today — it uses
    the identifier and little else — so the derived aliases on the post-commit
    read-back are defensive. They are asserted rather than left to a comment
    because the failure they prevent is silent: a later caller that did read
    wholeness from it would be told `unknown` for a document whose record is
    whole, and no test would notice.

    Mutation proving is why this exists. Dropping those aliases changed nothing
    observable, which makes the safety unfalsifiable — and an unfalsifiable
    guard is one a later change removes as dead weight.
    """
    root = tmp_path / "root"
    _at(root, "ledger.txt")
    context.ingestion.ingest(casefile.short_id, root)
    document = _only(context, casefile)

    # Reingest the same bytes at the same place, through the port directly, so
    # the value under test is the one `store_document` hands back.
    stored, was_new = context.store.store_document(
        document, f"{root.resolve()}/ledger.txt", document.created_at
    )
    assert was_new is False, "the place was already recorded"
    assert stored.locations_are_whole is True, (
        "the document handed back by the store reported its own record as not "
        "whole, which would mislead any caller that asked it"
    )
    assert stored.location_count == 1
    assert stored.additional_locations == 0
