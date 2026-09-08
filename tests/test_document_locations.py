"""Where identical bytes were found, and what survives a second copy.

Deduplication is correct and is not what these test. What they test is that the
*set* of places one file was found survives it — because that set is evidence of
shared custody and distribution, and the second copy used to overwrite the first
with no record that it had.

A location is the ingest root joined to the containment path, and the root is
load-bearing: a containment path is relative to whatever was ingested, so two
custodian dumps each holding `ledger.txt` at their top level produce the same
relative path. Tests that put both copies inside one ingested folder cannot see
that, so the cross-root case is tested directly.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from jackryan.cli import _render_document as _render_cli_document
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


def _location_rows(context, document_id):
    """Read the table directly: a count is the thing under test here."""
    return context.store._db.execute(
        "SELECT source_root, containment_path FROM document_locations"
        " WHERE document_id = ? ORDER BY first_seen_at",
        (document_id,),
    ).fetchall()


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
    assert {location.containment_path for location in record.recorded.locations} == {
        "custodian-a/ledger.txt",
        "custodian-b/ledger.txt",
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
    """The case a root-relative location cannot express.

    Both files are `ledger.txt` at the top of their own dump, so both have the
    identical containment path. Only the ingest root distinguishes them, and
    without it in the key the second observation collides with the first and
    the second custodian is lost — silently, which is the whole defect.

    This is also the only test that can see how `also_found_at` excludes the
    document's own location. It does so by position, taking the earliest — and
    a version comparing `containment_path` against the document's looks
    identical everywhere except here, where both locations share that path and
    such a comparison discards *both*. Asserting the recorded set alone left
    that mutation green, which is why the assertion below is on
    `also_found_at`.
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
        f"{[location.full_path for location in record.recorded.locations]}"
    )
    assert {location.full_path for location in record.recorded.locations} == {
        f"{alpha.resolve()}/ledger.txt",
        f"{beta.resolve()}/ledger.txt",
    }
    assert report.new_locations == [f"{beta.resolve()}/ledger.txt"]
    assert [location.full_path for location in record.observed_at] == [
        f"{alpha.resolve()}/ledger.txt",
        f"{beta.resolve()}/ledger.txt",
    ], (
        "the disclosure did not name both custodians, earliest first: "
        f"{[location.full_path for location in record.observed_at]}"
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
    assert [location.full_path for location in record.observed_at] == [
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
    assert {location.full_path for location in record.recorded.locations} == {
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
        assert [location.containment_path for location in record.recorded.locations] == [
            document.containment_path
        ]
        # The root is the top-level file's, so the location is followable end to
        # end: go to that directory, open the archive, find this entry.
        assert record.recorded.locations[0].source_root == str(tmp_path.resolve())


def test_reingesting_a_container_records_no_new_locations(context, casefile, tmp_path):
    """An expansion's bytes are materialised into a scratch directory that is
    new on every run. Recording that directory as the location would insert a
    fresh row and report a false discovery each time — so this asserts the row
    count does not grow and no discovery is reported."""
    bundle = _zip(tmp_path / "bundle.zip", [("first/report.txt", LEDGER)])

    context.ingestion.ingest(casefile.short_id, bundle)
    expanded = [d for d in _rows(context, casefile, include_expanded=True) if d.is_expanded]
    assert len(expanded) == 1
    before = _location_rows(context, expanded[0].id)

    again = context.ingestion.ingest(casefile.short_id, bundle)

    after = _location_rows(context, expanded[0].id)
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

    context.store._db.execute(
        "UPDATE documents SET locations_recorded = 0 WHERE id = ?", (document.id,)
    )
    context.store._db.execute("DELETE FROM document_locations WHERE document_id = ?", (document.id,))
    context.store._db.commit()

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
    context.store._db.execute(
        "UPDATE documents SET locations_recorded = 0 WHERE id = ?", (document.id,)
    )
    context.store._db.execute(
        "DELETE FROM document_locations WHERE document_id = ?", (document.id,)
    )
    context.store._db.commit()

    second = tmp_path / "custodian-b"
    _at(second, "archive/ledger-copy.txt")
    context.ingestion.ingest(casefile.short_id, second)

    record = _located(context, casefile, _only(context, casefile))
    assert record.verdict == "unknown"
    assert record.recorded.total == 1
    shown = [location.full_path for location in record.observed_at]
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

    context.store._db.execute(
        "UPDATE documents SET locations_recorded = 0 WHERE id = ?", (document.id,)
    )
    context.store._db.execute(
        "DELETE FROM document_locations WHERE document_id = ?", (document.id,)
    )
    context.store._db.commit()

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

    # The flag stays raised; only the rows are lost.
    context.store._db.execute(
        "DELETE FROM document_locations WHERE document_id = ?", (document.id,)
    )
    context.store._db.commit()

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

    assert _location_rows(context, document.id) == [], (
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
    service_paths = [location.full_path for location in record.observed_at]

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
