"""The `uas-oscal render` Markdown page (src/uas_oscal/render.py)."""

import json
from pathlib import Path

import pytest

from uas_oscal.cli import main
from uas_oscal.component import UAS_NS
from uas_oscal.render import (
    DEFAULT_COMPONENT,
    DEFAULT_OUTPUT,
    DEFAULT_RESULTS,
    RenderError,
    _code,
    _evidence_link,
    _inline,
    generate,
)

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


def _prop(obj, name):
    return next(p for p in obj["props"] if p["ns"] == UAS_NS and p["name"] == name)


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
        _prop(ar["results"][0]["observations"][0], "test-outcome")["value"] = "a|b"

    ar, cd = _copy(tmp_path, change_ar)
    assert "| TC-01 | a\\|b |" in generate(ar, cd, tmp_path / "out.md")


def test_evidence_link_text_is_escaped(tmp_path):
    results = tmp_path / "oscal" / "results.json"
    link = _evidence_link("ev/a|b]c.json", results, tmp_path / "out.md")
    assert link == r"[a\|b\]c.json](oscal/ev/a%7Cb%5Dc.json)"


def test_absolute_evidence_url_is_encoded(tmp_path):
    results = tmp_path / "oscal" / "results.json"
    link = _evidence_link("https://example.com/a b(1)|<x>.json?q=%41", results, tmp_path / "out.md")
    assert link == (
        r"[https://example.com/a b(1)\|\<x\>.json?q=%41]"
        "(https://example.com/a%20b%281%29%7C%3Cx%3E.json?q=%41)"
    )


def test_run_url_is_encoded(tmp_path):
    results = tmp_path / "oscal" / "results.json"
    link = _evidence_link("https://github.com/o/r(x)/actions/runs/1", results, tmp_path / "out.md")
    assert link == "[CI run 1](https://github.com/o/r%28x%29/actions/runs/1)"


def test_input_values_are_escaped_everywhere(tmp_path):
    def set_result_prop(result, name, value):
        _prop(result, name)["value"] = value

    def change_ar(ar):
        result = ar["results"][0]
        set_result_prop(result, "verification-event", "VE-#7 *x*\n<i>")
        set_result_prop(result, "ci-workflow", "`wf`")
        set_result_prop(result, "ci-run-id", "1_2")
        set_result_prop(result, "ci-run-attempt", "[a]")
        set_result_prop(result, "git-ref", "feat/`x`*y*[z]<b>|")
        set_result_prop(result, "git-commit", "ab``cdef")
        result["start"] = "2026 <b>*now*</b>"
        for obs in result["observations"]:
            obs["relevant-evidence"] = [ev for ev in obs["relevant-evidence"] if "://" not in ev["href"]]

    ar, cd = _copy(tmp_path, change_ar)
    text = generate(ar, cd, tmp_path / "out.md")
    lines = text.splitlines()
    assert lines[0] == r"# VE-\#7 \*x\* \<i\> assessment results"
    assert r"- **Run:** `` `wf` `` run 1\_2, attempt \[a\]" in lines
    assert r"- **Commit:** ```ab``cde``` on ``feat/`x`*y*[z]<b>|``" in lines
    assert r"- **Date:** 2026 \<b\>\*now\*\</b\>" in lines
    assert r"## Mapped requirements not assessed by VE-\#7 \*x\* \<i\>" in lines
    assert r"from the VE-\#7 \*x\* \<i\> CI evidence" in text
    # Raw HTML and emphasis survive only inside the ref's code span.
    assert text.count("<b>") == text.count("*y*") == 1
    for raw in ("<i>", "*x*", "*now*", "</b>"):
        assert raw not in text


@pytest.mark.parametrize(
    ("value", "escaped"),
    [
        ("- x", r"\- x"),
        ("+ x", r"\+ x"),
        ("12. x", r"12\. x"),
        ("3) x", r"3\) x"),
        ("a\n\n  b\tc", "a b c"),
        ("x|y\\z~$!", r"x\|y\\z\~\$\!"),
        ("SR-005", "SR-005"),
    ],
)
def test_inline_escape(value, escaped):
    assert _inline(value) == escaped


@pytest.mark.parametrize(
    ("value", "span"),
    [
        ("main", "`main`"),
        ("a`b", "``a`b``"),
        ("`a``", "``` `a`` ```"),
        ("a\nb", "`a b`"),
    ],
)
def test_code_span(value, span):
    assert _code(value) == span

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


def test_duplicate_finding_is_an_error(tmp_path):
    def change_ar(ar):
        findings = ar["results"][0]["findings"]
        findings.append(json.loads(json.dumps(findings[0])))

    ar, cd = _copy(tmp_path, change_ar)
    with pytest.raises(RenderError, match="duplicate finding for SR-005 / si-7"):
        generate(ar, cd, tmp_path / "out.md")


def test_duplicate_implemented_requirement_is_an_error(tmp_path):
    def change_cd(cd):
        irs = cd["components"][0]["control-implementations"][0]["implemented-requirements"]
        irs.append(json.loads(json.dumps(irs[0])))

    ar, cd = _copy(tmp_path, change_cd=change_cd)
    with pytest.raises(RenderError, match="duplicate implemented requirement for SR-003"):
        generate(ar, cd, tmp_path / "out.md")


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
    ar, cd = _copy(tmp_path, lambda d: _prop(d["results"][0], "ci-run-id").pop("value"))
    out = tmp_path / "out.md"
    assert main(["render", "--results", str(ar), "--component", str(cd), "-o", str(out)]) == 1
    err = capsys.readouterr().err
    assert err.startswith("uas-oscal render: ")
    assert "`ci-run-id` prop has no string value" in err
    assert not out.exists()
