"""The `uas-oscal component` generator (src/uas_oscal/component.py)."""

import json
import os
import subprocess
import uuid
from pathlib import Path

import pytest

from uas_oscal.cli import main
from uas_oscal.component import (
    CATALOG_HREF,
    DEFAULT_TRACE,
    DEFAULT_VERIFICATION,
    UAS_NS,
    build_component_definition,
    commit_timestamp,
    generate,
    load_requirements,
    load_trace,
    load_verification,
    normalize_timestamp,
)
from uas_oscal.mapping import DEFAULT_MAPPING, DEFAULT_REQUIREMENTS, load_mapping

ROOT = Path(__file__).resolve().parent.parent
GENERATED = ROOT / "oscal" / "generated" / "component-definition.json"
NS = uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/samyoon727ca/uas-sec-oscal")
FIXED = "2026-11-21T00:00:00Z"


def _build(mapping=None):
    return build_component_definition(
        mapping or load_mapping(),
        load_requirements(),
        load_trace(),
        load_verification(),
        FIXED,
    )["component-definition"]


def _implemented(cd):
    """Every implemented requirement, across components, in document order."""
    irs = []
    for component in cd["components"]:
        (impl,) = component["control-implementations"]
        irs += impl["implemented-requirements"]
    return irs


def _props(obj, name):
    values = []
    for prop in obj["props"]:
        assert prop["ns"] == UAS_NS
        if prop["name"] == name:
            values.append(prop["value"])
    return values


def _with_statuses(*statuses, approved_by="owner"):
    mapping = load_mapping()
    mapping["approved_by"] = approved_by
    rows = mapping["mappings"]
    for row, status in zip(rows, statuses, strict=True):
        row["status"] = status
    return mapping


# Determinism


def test_generate_twice_is_byte_identical():
    assert generate(last_modified=FIXED) == generate(last_modified=FIXED)


def test_cli_twice_is_byte_identical(tmp_path):
    outputs = []
    for name in ("a.json", "b.json"):
        out = tmp_path / name
        argv = [
            "component",
            "--requirements", str(DEFAULT_REQUIREMENTS),
            "--trace", str(DEFAULT_TRACE),
            "--verification", str(DEFAULT_VERIFICATION),
            "--mapping", str(DEFAULT_MAPPING),
            "--last-modified", FIXED,
            "-o", str(out),
        ]
        assert main(argv) == 0
        outputs.append(out.read_bytes())
    assert outputs[0] == outputs[1]
    assert b"\r\n" not in outputs[0]


def test_output_has_sorted_keys():
    text = generate(last_modified=FIXED)
    assert text == json.dumps(json.loads(text), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def test_committed_file_is_up_to_date():
    committed = GENERATED.read_text(encoding="utf-8")
    last_modified = json.loads(committed)["component-definition"]["metadata"]["last-modified"]
    assert generate(last_modified=last_modified) == committed


def test_last_modified_is_normalized_to_utc():
    assert normalize_timestamp("2026-11-21T07:48:49-06:00") == "2026-11-21T13:48:49Z"
    with pytest.raises(ValueError, match="UTC offset"):
        normalize_timestamp("2026-11-21T07:48:49")
    with pytest.raises(ValueError):
        normalize_timestamp("yesterday")


def test_cli_rejects_bad_last_modified(tmp_path, capsys):
    out = tmp_path / "cd.json"
    assert main(["component", "--last-modified", "2026-11-21", "-o", str(out)]) == 1
    assert "UTC offset" in capsys.readouterr().err
    assert not out.exists()


def _git(cwd, *args, date=None):
    env = dict(os.environ)
    if date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=cwd, env=env, check=True, capture_output=True,
    )


def test_default_last_modified_is_the_input_commit_date(tmp_path):
    _git(tmp_path, "init", "-q")
    first, second = tmp_path / "a.csv", tmp_path / "b.csv"
    first.write_text("x\n", encoding="utf-8")
    _git(tmp_path, "add", "a.csv")
    _git(tmp_path, "commit", "-q", "-m", "a", date="2026-01-02T03:04:05+00:00")
    second.write_text("y\n", encoding="utf-8")
    _git(tmp_path, "add", "b.csv")
    _git(tmp_path, "commit", "-q", "-m", "b", date="2026-02-03T04:05:06-06:00")
    assert commit_timestamp([first]) == "2026-01-02T03:04:05Z"
    assert commit_timestamp([first, second]) == "2026-02-03T10:05:06Z"


def test_default_last_modified_refuses_a_shallow_clone(tmp_path):
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-q")
    (origin / "a.csv").write_text("x\n", encoding="utf-8")
    _git(origin, "add", "a.csv")
    _git(origin, "commit", "-q", "-m", "a", date="2026-01-02T03:04:05+00:00")
    (origin / "b.csv").write_text("y\n", encoding="utf-8")
    _git(origin, "add", "b.csv")
    _git(origin, "commit", "-q", "-m", "b", date="2026-02-03T04:05:06+00:00")
    _git(tmp_path, "clone", "-q", "--depth", "1", origin.resolve().as_uri(), "shallow")
    with pytest.raises(ValueError, match="shallow clone"):
        commit_timestamp([tmp_path / "shallow" / "a.csv"])


def test_default_last_modified_refuses_uncommitted_inputs(tmp_path):
    _git(tmp_path, "init", "-q")
    committed, untracked = tmp_path / "a.csv", tmp_path / "b.csv"
    committed.write_text("x\n", encoding="utf-8")
    _git(tmp_path, "add", "a.csv")
    _git(tmp_path, "commit", "-q", "-m", "a", date="2026-01-02T03:04:05+00:00")
    untracked.write_text("y\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"uncommitted changes \(.*b\.csv"):
        commit_timestamp([committed, untracked])
    assert commit_timestamp([committed]) == "2026-01-02T03:04:05Z"
    committed.write_text("changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"uncommitted changes \(.*a\.csv"):
        commit_timestamp([committed])


def _commit_copy(repo, src, date):
    repo.mkdir(exist_ok=True)
    if not (repo / ".git").exists():
        _git(repo, "init", "-q")
    dst = repo / src.name
    dst.write_bytes(src.read_bytes())
    _git(repo, "add", src.name)
    _git(repo, "commit", "-q", "-m", src.name, date=date)
    return dst


def test_default_last_modified_spans_inputs_in_different_repos(tmp_path):
    # The P1 CSVs in one repository, the mapping in another (e.g. --mapping outside this repo).
    data, maps = tmp_path / "data", tmp_path / "maps"
    requirements = _commit_copy(data, DEFAULT_REQUIREMENTS, "2026-01-02T03:04:05+00:00")
    trace = _commit_copy(data, DEFAULT_TRACE, "2026-01-02T03:04:05+00:00")
    mapping = _commit_copy(maps, DEFAULT_MAPPING, "2026-02-03T04:05:06+00:00")
    assert commit_timestamp([requirements, trace, mapping]) == "2026-02-03T04:05:06Z"
    assert commit_timestamp([mapping, requirements]) == "2026-02-03T04:05:06Z"
    out = tmp_path / "cd.json"
    argv = ["component", "--requirements", str(requirements), "--trace", str(trace), "--mapping", str(mapping)]
    assert main([*argv, "-o", str(out)]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["component-definition"]["metadata"]["last-modified"] == "2026-02-03T04:05:06Z"


def test_default_last_modified_refuses_an_input_outside_git(tmp_path, monkeypatch):
    committed = _commit_copy(tmp_path / "repo", DEFAULT_MAPPING, "2026-01-02T03:04:05+00:00")
    plain = tmp_path / "plain" / "trace.csv"
    plain.parent.mkdir()
    plain.write_text("threat_id,req_id\n", encoding="utf-8")
    # Keep git from finding a repository above tmp_path.
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.resolve()))
    with pytest.raises(ValueError, match=r"trace\.csv is not in a git work tree"):
        commit_timestamp([committed, plain])


# Malformed inputs

# The full header of the vendored requirements.csv.
REQ_HEADER = "req_id,statement,rationale,allocated_to,verification,evidence_repo,resiliency_approach\n"


@pytest.mark.parametrize(
    ("flag", "content", "message"),
    [
        ("--trace", "threat,req\nTHR-001,SR-001\n", "missing column(s) threat_id, req_id"),
        ("--trace", "", "missing column(s) threat_id, req_id"),
        ("--trace", "threat_id,req_id\nTHR-001\n", ":2: missing value(s) for req_id"),
        ("--requirements", "id,statement\nSR-001,x\n", "missing column(s) req_id, allocated_to"),
        ("--trace", "threat_id,req_id\nTHR-001,SR-001\nTHR-008,\n", ":3: missing value(s) for req_id"),
        ("--requirements", REQ_HEADER + "SR-005,,r,CMP-CC,T,P2,a\n", ":2: missing value(s) for statement"),
        ("--requirements", REQ_HEADER + "SR-005,s,r,CMP-CC, \t,P2,a\n", ":2: missing value(s) for verification"),
        (
            "--requirements",
            REQ_HEADER + "SR-005,s,r,CMP-CC,T,P2,a\nSR-003,s,r,CMP-FC,T,P2,a\nSR-005,t,r,CMP-CC,T,P2,a\n",
            ":4: duplicate req_id SR-005 (first on line 2)",
        ),
        ("--verification", "ve,reqs\nVE-07,SR-005\n", "missing column(s) ve_id, req_ids"),
        ("--verification", "ve_id,req_ids\nVE-07,\n", ":2: missing value(s) for req_ids"),
        ("--verification", "ve_id,req_ids\nVE-07,SR-005;\n", ":2: empty entry in req_ids"),
        ("--verification", "ve_id,req_ids\nVE-07,SR-005\nVE-07,SR-010\n", ":3: duplicate ve_id VE-07 (first on line 2)"),
    ],
)
def test_malformed_csv_is_a_clean_cli_error(tmp_path, capsys, flag, content, message):
    bad = tmp_path / "bad.csv"
    bad.write_text(content, encoding="utf-8")
    out = tmp_path / "cd.json"
    assert main(["component", flag, str(bad), "--last-modified", FIXED, "-o", str(out)]) == 1
    err = capsys.readouterr().err
    assert err.startswith(f"uas-oscal component: {bad}")
    assert message in err
    assert not out.exists()


# Content


def test_identifiers_follow_the_uuid5_scheme():
    cd = _build()
    assert cd["uuid"] == str(uuid.uuid5(NS, "component-definition/uas-p2-verified-boot"))
    uuids = [cd["uuid"]]
    for component in cd["components"]:
        (slug,) = [p["value"].lower() for p in component["props"] if p["name"] == "allocated-to"]
        (impl,) = component["control-implementations"]
        assert component["uuid"] == str(uuid.uuid5(NS, f"component/uas-p2-verified-boot/{slug}"))
        assert impl["uuid"] == str(
            uuid.uuid5(NS, f"control-implementation/uas-p2-verified-boot/{slug}/nist-sp-800-53-rev5")
        )
        assert "800-53" in impl["source"] and "rev5" in impl["source"]
        for ir in impl["implemented-requirements"]:
            (req,) = _props(ir, "requirement-id")
            name = f"implemented-requirement/uas-p2-verified-boot/{slug}/{req}/{ir['control-id']}"
            assert ir["uuid"] == str(uuid.uuid5(NS, name))
        uuids += [component["uuid"], impl["uuid"]] + [ir["uuid"] for ir in impl["implemented-requirements"]]
    assert len(set(uuids)) == len(uuids)


def test_catalog_href_is_pinned_to_a_release():
    assert "/oscal-content/v1.6.0/" in CATALOG_HREF
    for component in _build()["components"]:
        (impl,) = component["control-implementations"]
        assert impl["source"] == CATALOG_HREF


def test_each_component_holds_only_requirements_allocated_to_it():
    requirements = load_requirements()
    cd = _build()
    allocations = []
    for component in cd["components"]:
        (allocation,) = [p["value"] for p in component["props"] if p["name"] == "allocated-to"]
        allocations.append(allocation)
        (impl,) = component["control-implementations"]
        for ir in impl["implemented-requirements"]:
            (req_id,) = _props(ir, "requirement-id")
            assert requirements[req_id]["allocated_to"] == allocation
    assert allocations == ["CMP-CC", "CMP-FC", "CMP-GCS"]
    titles = [c["title"] for c in cd["components"]]
    assert titles == ["UAS companion computer (CC)", "UAS flight controller (FC)", "UAS ground control station (GCS)"]
    assert all("verified-boot" not in title for title in titles)


def test_unknown_allocation_gets_a_component_titled_by_its_id():
    requirements = load_requirements()
    requirements["SR-027"] = {**requirements["SR-027"], "allocated_to": "CMP-NEW"}
    cd = build_component_definition(load_mapping(), requirements, load_trace(), load_verification(), FIXED)
    titles = [c["title"] for c in cd["component-definition"]["components"]]
    assert titles == ["UAS companion computer (CC)", "UAS flight controller (FC)", "UAS component CMP-NEW"]


def test_only_mapped_requirements_and_controls_appear():
    mapping = load_mapping()
    statements = load_requirements()
    # Grouped by component (allocation, sorted), in mapping order within each.
    rows = sorted(mapping["mappings"], key=lambda row: statements[row["requirement_id"]]["allocated_to"])
    expected = [(row["requirement_id"], c) for row in rows for c in row["controls"]]
    got = [(_props(ir, "requirement-id")[0], ir["control-id"]) for ir in _implemented(_build())]
    assert got == expected
    unmapped = set(statements) - {row["requirement_id"] for row in mapping["mappings"]}
    text = generate(last_modified=FIXED)
    for req_id in unmapped:
        assert f'"{req_id}"' not in text
        assert f"{req_id}:" not in text


def test_description_has_requirement_text_and_trace_links():
    statements = load_requirements()
    for ir in _implemented(_build()):
        (req_id,) = _props(ir, "requirement-id")
        assert ir["description"].startswith(f"{req_id}: {statements[req_id]['statement']}")
        threats = load_trace()[req_id]
        assert threats
        assert _props(ir, "threat-id") == threats
        assert f"Traces to threats: {', '.join(threats)}." in ir["description"]


def test_sr005_trace_links():
    (si7,) = [ir for ir in _implemented(_build()) if ir["control-id"] == "si-7"]
    assert _props(si7, "requirement-id") == ["SR-005"]
    assert _props(si7, "threat-id") == ["THR-008", "THR-010", "THR-032"]
    assert "Traces to threats: THR-008, THR-010, THR-032." in si7["description"]
    assert "Verification: test (T), evidence in P2." in si7["description"]


def test_sr005_verification_events():
    for ir in _implemented(_build()):
        if _props(ir, "requirement-id") == ["SR-005"]:
            assert _props(ir, "verification-event") == ["VE-07"]
            assert "Verification events: VE-07." in ir["description"]


def test_every_mapped_requirement_carries_its_verification_events():
    events = load_verification()
    for ir in _implemented(_build()):
        (req_id,) = _props(ir, "requirement-id")
        assert events[req_id]
        assert _props(ir, "verification-event") == events[req_id]
        assert f"Verification events: {', '.join(events[req_id])}." in ir["description"]


def test_verification_events_are_split_and_sorted(tmp_path):
    table = tmp_path / "verification.csv"
    table.write_text("ve_id,req_ids\nVE-09,SR-005\nVE-07,SR-005; SR-010\n", encoding="utf-8")
    assert load_verification(table) == {"SR-005": ["VE-07", "VE-09"], "SR-010": ["VE-07"]}


def test_requirement_without_verification_rows_says_so(tmp_path):
    table = tmp_path / "verification.csv"
    table.write_text("ve_id,req_ids\n", encoding="utf-8")
    cd = build_component_definition(load_mapping(), load_requirements(), load_trace(), load_verification(table), FIXED)
    for ir in _implemented(cd["component-definition"]):
        assert _props(ir, "verification-event") == []
        assert "Verification events: none recorded in verification.csv." in ir["description"]


def test_trace_links_are_deduplicated():
    # trace.csv lists THR-004 -> SR-013 twice.
    assert load_trace()["SR-013"] == ["THR-004"]


def test_requirement_without_trace_rows_says_so(tmp_path):
    trace = tmp_path / "trace.csv"
    trace.write_text("threat_id,req_id\n", encoding="utf-8")
    cd = build_component_definition(load_mapping(), load_requirements(), load_trace(trace), load_verification(), FIXED)
    for ir in _implemented(cd["component-definition"]):
        assert _props(ir, "threat-id") == []
        assert "Traces to threats: none recorded in trace.csv." in ir["description"]


# Approval gate


def test_proposed_rows_are_marked_draft():
    cd = _build()
    assert cd["metadata"]["title"].endswith(" (DRAFT)")
    for ir in _implemented(cd):
        assert _props(ir, "mapping-status") == ["proposed"]
        assert "DRAFT" in ir["description"]


def test_all_approved_is_not_draft():
    cd = _build(_with_statuses(*["approved"] * 5))
    assert "DRAFT" not in cd["metadata"]["title"]
    for ir in _implemented(cd):
        assert _props(ir, "mapping-status") == ["approved"]
        assert "DRAFT" not in ir["description"]


def test_approved_rows_without_approved_by_keep_the_document_draft():
    cd = _build(_with_statuses(*["approved"] * 5, approved_by=None))
    assert cd["metadata"]["title"].endswith(" (DRAFT)")
    for ir in _implemented(cd):
        assert _props(ir, "mapping-status") == ["approved"]


def test_one_unapproved_row_keeps_the_document_draft():
    cd = _build(_with_statuses("approved", "approved", "rejected", "approved", "approved"))
    assert cd["metadata"]["title"].endswith(" (DRAFT)")
    statuses = {_props(ir, "requirement-id")[0]: _props(ir, "mapping-status") for ir in _implemented(cd)}
    assert statuses["SR-007"] == ["rejected"]
    assert statuses["SR-005"] == ["approved"]
    # Unapproved rows are still emitted.
    assert any(ir["control-id"] == "cm-14" for ir in _implemented(cd))
