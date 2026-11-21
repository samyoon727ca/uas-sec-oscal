import csv
import re
import textwrap

import pytest

from uas_oscal.mapping import (
    DEFAULT_REQUIREMENTS,
    MappingError,
    is_approved,
    load_mapping,
)


def _statements():
    with DEFAULT_REQUIREMENTS.open(encoding="utf-8", newline="") as f:
        return {row["req_id"]: row["statement"] for row in csv.DictReader(f)}


def _write(tmp_path, body):
    path = tmp_path / "controls.yaml"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


def _row(req="SR-005", controls="[si-7, si-7.15]", status="proposed"):
    return f"""
      - requirement_id: {req}
        controls: {controls}
        rationale: The CC "shall boot only boot-chain components signed with the project boot key".
        status: {status}
    """


def _doc(*rows, approved_by="null"):
    body = f"approved_by: {approved_by}\nmappings:\n"
    for row in rows or (_row(),):
        body += textwrap.indent(textwrap.dedent(row).strip("\n"), "  ") + "\n"
    return body


# The shipped mapping file


def test_shipped_mapping_loads():
    doc = load_mapping()
    assert doc["approved_by"] is None
    assert len(doc["mappings"]) == 5


def test_shipped_mapping_includes_sr005():
    ids = [row["requirement_id"] for row in load_mapping()["mappings"]]
    assert "SR-005" in ids


def test_shipped_rows_are_all_proposed():
    for row in load_mapping()["mappings"]:
        assert row["status"] == "proposed"
        assert not is_approved(row)


def test_shipped_rationales_quote_the_requirement():
    statements = _statements()
    for row in load_mapping()["mappings"]:
        quotes = re.findall(r'"([^"]+)"', row["rationale"])
        assert quotes, row["requirement_id"]
        for quote in quotes:
            assert quote in statements[row["requirement_id"]], (row["requirement_id"], quote)


# Valid input


def test_valid_file_loads(tmp_path):
    doc = load_mapping(_write(tmp_path, _doc(_row(), _row("SR-003", "[sc-8, sc-23]"))))
    assert [r["requirement_id"] for r in doc["mappings"]] == ["SR-005", "SR-003"]
    assert doc["mappings"][0]["controls"] == ["si-7", "si-7.15"]


def test_approved_by_may_be_a_name(tmp_path):
    assert load_mapping(_write(tmp_path, _doc(approved_by="owner")))["approved_by"] == "owner"


# Failure cases


def test_unknown_requirement_id_fails(tmp_path):
    with pytest.raises(MappingError, match="unknown requirement_id 'SR-999'"):
        load_mapping(_write(tmp_path, _doc(_row("SR-999"))))


def test_requirement_id_checked_against_given_csv(tmp_path):
    reqs = tmp_path / "requirements.csv"
    reqs.write_text("req_id,statement\nSR-003,x\n", encoding="utf-8")
    with pytest.raises(MappingError, match="unknown requirement_id 'SR-005'"):
        load_mapping(_write(tmp_path, _doc()), requirements_path=reqs)


@pytest.mark.parametrize(
    "controls",
    [
        "[SI-7]",
        "[si-07]",
        "[si7]",
        "[si-7(15)]",
        "[si-7.15.1]",
        "[si-7.0]",
        "[sia-7]",
        "[' si-7']",
        "[7]",
        "[]",
        "si-7",
        "[si-7, si-7]",
    ],
)
def test_malformed_controls_fail(tmp_path, controls):
    with pytest.raises(MappingError, match="control"):
        load_mapping(_write(tmp_path, _doc(_row(controls=controls))))


def test_duplicate_rows_fail(tmp_path):
    with pytest.raises(MappingError, match="duplicate row for SR-005"):
        load_mapping(_write(tmp_path, _doc(_row(), _row(controls="[si-7.9]"))))


def test_unknown_status_fails(tmp_path):
    with pytest.raises(MappingError, match="status"):
        load_mapping(_write(tmp_path, _doc(_row(status="Approved"))))


def test_missing_row_key_fails(tmp_path):
    body = _doc().replace("    status: proposed\n", "")
    with pytest.raises(MappingError, match="keys must be"):
        load_mapping(_write(tmp_path, body))


def test_missing_approved_by_fails(tmp_path):
    body = _doc().replace("approved_by: null\n", "")
    with pytest.raises(MappingError, match="top-level keys"):
        load_mapping(_write(tmp_path, body))


def test_empty_mappings_fail(tmp_path):
    with pytest.raises(MappingError, match="non-empty list"):
        load_mapping(_write(tmp_path, "approved_by: null\nmappings: []\n"))


def test_invalid_yaml_fails(tmp_path):
    with pytest.raises(MappingError, match="invalid YAML"):
        load_mapping(_write(tmp_path, "approved_by: [\n"))


# is_approved


@pytest.mark.parametrize(
    ("status", "expected"),
    [("approved", True), ("proposed", False), ("rejected", False), ("Approved", False), (None, False)],
)
def test_is_approved(status, expected):
    assert is_approved({"requirement_id": "SR-005", "status": status}) is expected


def test_is_approved_missing_status():
    assert is_approved({"requirement_id": "SR-005"}) is False
