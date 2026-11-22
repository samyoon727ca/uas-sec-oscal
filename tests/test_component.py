"""The `uas-oscal component` generator (src/uas_oscal/component.py)."""

import json
import os
import subprocess
import uuid
from pathlib import Path

import pytest

from uas_oscal.cli import main
from uas_oscal.component import (
    DEFAULT_TRACE,
    UAS_NS,
    build_component_definition,
    commit_timestamp,
    generate,
    load_requirements,
    load_trace,
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
        FIXED,
    )["component-definition"]


def _implemented(cd):
    (component,) = cd["components"]
    (impl,) = component["control-implementations"]
    return impl["implemented-requirements"]


def _props(obj, name):
    values = []
    for prop in obj["props"]:
        assert prop["ns"] == UAS_NS
        if prop["name"] == name:
            values.append(prop["value"])
    return values


def _with_statuses(*statuses):
    mapping = load_mapping()
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
    (component,) = cd["components"]
    (impl,) = component["control-implementations"]
    assert cd["uuid"] == str(uuid.uuid5(NS, "component-definition/uas-p2-verified-boot"))
    assert component["uuid"] == str(uuid.uuid5(NS, "component/uas-p2-verified-boot"))
    assert impl["uuid"] == str(uuid.uuid5(NS, "control-implementation/uas-p2-verified-boot/nist-sp-800-53-rev5"))
    assert "800-53" in impl["source"] and "rev5" in impl["source"]
    for ir in _implemented(cd):
        (req,) = _props(ir, "requirement-id")
        assert ir["uuid"] == str(uuid.uuid5(NS, f"implemented-requirement/uas-p2-verified-boot/{req}/{ir['control-id']}"))
    uuids = [cd["uuid"], component["uuid"], impl["uuid"]] + [ir["uuid"] for ir in _implemented(cd)]
    assert len(set(uuids)) == len(uuids)


def test_only_mapped_requirements_and_controls_appear():
    mapping = load_mapping()
    expected = [(row["requirement_id"], c) for row in mapping["mappings"] for c in row["controls"]]
    got = [(_props(ir, "requirement-id")[0], ir["control-id"]) for ir in _implemented(_build())]
    assert got == expected
    statements = load_requirements()
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


def test_trace_links_are_deduplicated():
    # trace.csv lists THR-004 -> SR-013 twice.
    assert load_trace()["SR-013"] == ["THR-004"]


def test_requirement_without_trace_rows_says_so(tmp_path):
    trace = tmp_path / "trace.csv"
    trace.write_text("threat_id,req_id\n", encoding="utf-8")
    cd = build_component_definition(load_mapping(), load_requirements(), load_trace(trace), FIXED)
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


def test_one_unapproved_row_keeps_the_document_draft():
    cd = _build(_with_statuses("approved", "approved", "rejected", "approved", "approved"))
    assert cd["metadata"]["title"].endswith(" (DRAFT)")
    statuses = {_props(ir, "requirement-id")[0]: _props(ir, "mapping-status") for ir in _implemented(cd)}
    assert statuses["SR-007"] == ["rejected"]
    assert statuses["SR-005"] == ["approved"]
    # Unapproved rows are still emitted.
    assert any(ir["control-id"] == "cm-14" for ir in _implemented(cd))
