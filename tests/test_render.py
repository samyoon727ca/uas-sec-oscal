"""The `uas-oscal render` Markdown page (src/uas_oscal/render.py)."""

import json
from pathlib import Path

import pytest

from uas_oscal.cli import main
from uas_oscal.component import UAS_NS
from uas_oscal.render import DEFAULT_COMPONENT, DEFAULT_OUTPUT, DEFAULT_RESULTS, _evidence_link, generate

ROOT = Path(__file__).resolve().parent.parent
SUMMARY = ROOT / "data" / "upstream" / "evidence" / "ve07-ci" / "20261013-0d3ca38" / "summary.json"


def _copy(tmp_path: Path, change_ar=None, change_cd=None) -> tuple[Path, Path]:
    """Copy the generated documents into tmp_path/oscal/, applying optional edits.

    The results file's relative evidence hrefs are rewritten so they still point
    at the vendored summary.json from the new location.
    """
    ar = json.loads(DEFAULT_RESULTS.read_text(encoding="utf-8"))
    cd = json.loads(DEFAULT_COMPONENT.read_text(encoding="utf-8"))
    for obs in ar["assessment-results"]["results"][0]["observations"]:
        for ev in obs["relevant-evidence"]:
            if "://" not in ev["href"]:
                ev["href"] = SUMMARY.as_posix()
    if change_ar:
        change_ar(ar["assessment-results"])
    if change_cd:
        change_cd(cd["component-definition"])
    (tmp_path / "oscal").mkdir()
    ar_path = tmp_path / "oscal" / "ar.json"
    cd_path = tmp_path / "oscal" / "cd.json"
    ar_path.write_text(json.dumps(ar), encoding="utf-8")
    cd_path.write_text(json.dumps(cd), encoding="utf-8")
    return ar_path, cd_path


def _set_status(obj, status):
    for prop in obj["props"]:
        if prop["ns"] == UAS_NS and prop["name"] == "mapping-status":
            prop["value"] = status


def _approve_all(ar=None, cd=None):
    if ar is not None:
        ar["metadata"]["title"] = ar["metadata"]["title"].removesuffix(" (DRAFT)")
        for finding in ar["results"][0]["findings"]:
            _set_status(finding, "approved")
    if cd is not None:
        cd["metadata"]["title"] = cd["metadata"]["title"].removesuffix(" (DRAFT)")
        for ir in cd["components"][0]["control-implementations"][0]["implemented-requirements"]:
            _set_status(ir, "approved")


# Snapshot


def test_committed_page_is_up_to_date():
    """docs/results/ve07.md is the snapshot of the render output for the committed OSCAL."""
    assert generate() == DEFAULT_OUTPUT.read_text(encoding="utf-8")


def test_snapshot_content():
    text = DEFAULT_OUTPUT.read_text(encoding="utf-8")
    assert text.startswith("# VE-07 assessment results\n")
    assert "> [!WARNING]\n> **DRAFT.**" in text
    assert "[`ve07-emu` run 38345035945, attempt 1](https://github.com/" in text
    assert "/commit/0d3ca389ee65ba4575c00aad9b5130c4c416c5e5) on `refs/heads/p2/tc05-unseal`" in text
    assert "- **Date:** 2026-10-13T04:15:29Z" in text
    for control in ("SI-7", "SI-7(9)", "SI-7(15)"):
        assert f"| SR-005 | {control} | ✅ satisfied | proposed | [summary.json](" in text
    assert "## How this was produced" in text


def test_links_resolve_from_the_page():
    text = DEFAULT_OUTPUT.read_text(encoding="utf-8")
    for rel in ("../../data/upstream/evidence/ve07-ci/20261013-0d3ca38/summary.json",
                "../../oscal/generated/component-definition.json",
                "../../oscal/generated/ve07-assessment-results.json"):
        assert f"]({rel})" in text
        assert (DEFAULT_OUTPUT.parent / rel).resolve().is_file()


def test_cli_writes_the_page_with_lf(tmp_path):
    out = tmp_path / "a" / "ve07.md"
    assert main(["render", "-o", str(out)]) == 0
    data = out.read_bytes()
    assert b"\r\n" not in data
    assert "[summary.json](" in data.decode("utf-8")


# Draft banner


def test_no_banner_when_everything_is_approved(tmp_path):
    ar, cd = _copy(tmp_path, lambda d: _approve_all(ar=d), lambda d: _approve_all(cd=d))
    text = generate(ar, cd, tmp_path / "out.md")
    assert "DRAFT" not in text
    assert "| SR-005 | SI-7 | ✅ satisfied | approved |" in text


def test_banner_when_one_component_row_is_unapproved(tmp_path):
    def change_cd(cd):
        _approve_all(cd=cd)
        _set_status(cd["components"][0]["control-implementations"][0]["implemented-requirements"][0], "proposed")

    ar, cd = _copy(tmp_path, lambda d: _approve_all(ar=d), change_cd)
    text = generate(ar, cd, tmp_path / "out.md")
    assert "> **DRAFT.** The control mapping for SR-003 is not approved" in text


def test_banner_when_only_the_title_is_draft(tmp_path):
    def change_cd(cd):
        _approve_all(cd=cd)
        cd["metadata"]["title"] += " (DRAFT)"

    ar, cd = _copy(tmp_path, lambda d: _approve_all(ar=d), change_cd)
    text = generate(ar, cd, tmp_path / "out.md")
    assert "> **DRAFT.** The control mapping has no `approved_by` set." in text


# Findings


def test_not_satisfied_finding_is_shown(tmp_path):
    def change_ar(ar):
        ar["results"][0]["findings"][1]["target"]["status"]["state"] = "not-satisfied"

    ar, cd = _copy(tmp_path, change_ar)
    text = generate(ar, cd, tmp_path / "out.md")
    assert "| SR-005 | SI-7(9) | ❌ not satisfied | proposed |" in text


def test_mapped_control_without_finding_is_not_assessed(tmp_path):
    ar, cd = _copy(tmp_path, lambda d: d["results"][0]["findings"].pop(2))
    text = generate(ar, cd, tmp_path / "out.md")
    assert "| SR-005 | SI-7(15) | not assessed | proposed | — |" in text


def test_evidence_links_are_relative_to_the_output(tmp_path):
    ar, cd = _copy(tmp_path)
    out = tmp_path / "deep" / "er" / "page.md"
    text = generate(ar, cd, out)
    rel = text.split("[summary.json](", 1)[1].split(")", 1)[0]
    assert not Path(rel).is_absolute()
    assert (out.parent / rel).resolve() == SUMMARY.resolve()


def test_table_cells_are_escaped(tmp_path):
    def change_ar(ar):
        ar["results"][0]["observations"][0]["props"][1]["value"] = "a|b"

    ar, cd = _copy(tmp_path, change_ar)
    assert "| TC-01 | a\\|b |" in generate(ar, cd, tmp_path / "out.md")



def test_evidence_link_text_is_escaped(tmp_path):
    results = tmp_path / "oscal" / "results.json"
    link = _evidence_link("ev/a|b]c.json", results, tmp_path / "out.md")
    assert link == r"[a\|b\]c.json](oscal/ev/a%7Cb%5Dc.json)"


# Errors


def test_finding_missing_from_component_definition_is_an_error(tmp_path, capsys):
    def change_cd(cd):
        irs = cd["components"][0]["control-implementations"][0]["implemented-requirements"]
        irs[:] = [ir for ir in irs if ir["control-id"] != "si-7.9"]

    ar, cd = _copy(tmp_path, change_cd=change_cd)
    out = tmp_path / "out.md"
    assert main(["render", "--results", str(ar), "--component", str(cd), "-o", str(out)]) == 1
    err = capsys.readouterr().err
    assert err.startswith("uas-oscal render: ")
    assert "SR-005 / si-7.9 is not in the component definition" in err
    assert not out.exists()


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("{", "invalid JSON"),
        ('{"catalog": {}}', "not an OSCAL assessment-results document"),
    ],
)
def test_bad_results_file_is_a_clean_cli_error(tmp_path, capsys, content, message):
    bad = tmp_path / "ar.json"
    bad.write_text(content, encoding="utf-8")
    out = tmp_path / "out.md"
    assert main(["render", "--results", str(bad), "-o", str(out)]) == 1
    assert message in capsys.readouterr().err
    assert not out.exists()


def test_prop_without_value_is_an_error(tmp_path, capsys):
    ar, cd = _copy(tmp_path, lambda d: d["results"][0]["props"][1].pop("value"))
    out = tmp_path / "out.md"
    assert main(["render", "--results", str(ar), "--component", str(cd), "-o", str(out)]) == 1
    err = capsys.readouterr().err
    assert err.startswith("uas-oscal render: ")
    assert "`ci-run-id` prop has no string value" in err
    assert not out.exists()
