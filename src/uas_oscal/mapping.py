"""Load and validate the requirements-to-800-53 control mapping (``mappings/controls.yaml``).

A mapping row is only usable once the owner has approved it: ``is_approved`` is
true only for rows whose ``status`` is ``approved``.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MAPPING = REPO_ROOT / "mappings" / "controls.yaml"
DEFAULT_REQUIREMENTS = REPO_ROOT / "data" / "upstream" / "p1" / "requirements.csv"

# OSCAL control ids in the SP 800-53 Rev. 5 catalog: "si-7", or "si-7.15" for an enhancement.
CONTROL_ID_RE = re.compile(r"[a-z]{2}-[1-9][0-9]*(\.[1-9][0-9]*)?")
STATUSES = frozenset({"proposed", "approved", "rejected"})
ROW_KEYS = frozenset({"requirement_id", "controls", "rationale", "status"})


class MappingError(ValueError):
    """The mapping file is malformed or refers to unknown requirements."""


def load_requirement_ids(path: Path = DEFAULT_REQUIREMENTS) -> set[str]:
    with path.open(encoding="utf-8", newline="") as f:
        return {row["req_id"] for row in csv.DictReader(f)}


def load_mapping(
    path: Path = DEFAULT_MAPPING,
    requirements_path: Path = DEFAULT_REQUIREMENTS,
) -> dict[str, Any]:
    """Parse and validate a mapping file; raise ``MappingError`` on any problem."""
    with path.open(encoding="utf-8") as f:
        try:
            doc = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            raise MappingError(f"{path}: invalid YAML: {exc}") from exc
    validate_mapping(doc, load_requirement_ids(requirements_path))
    return doc


def validate_mapping(doc: Any, requirement_ids: set[str]) -> None:
    if not isinstance(doc, dict):
        raise MappingError("mapping file must be a mapping with 'approved_by' and 'mappings'")
    if set(doc) != {"approved_by", "mappings"}:
        raise MappingError(f"top-level keys must be approved_by and mappings, got {sorted(doc)}")
    approved_by = doc["approved_by"]
    if approved_by is not None and not (isinstance(approved_by, str) and approved_by.strip()):
        raise MappingError("approved_by must be null or a non-empty string")
    rows = doc["mappings"]
    if not isinstance(rows, list) or not rows:
        raise MappingError("mappings must be a non-empty list")

    seen: set[str] = set()
    for i, row in enumerate(rows):
        where = f"mappings[{i}]"
        if not isinstance(row, dict) or set(row) != ROW_KEYS:
            got = sorted(row) if isinstance(row, dict) else type(row).__name__
            raise MappingError(f"{where}: keys must be {sorted(ROW_KEYS)}, got {got}")

        req = row["requirement_id"]
        if not isinstance(req, str) or req not in requirement_ids:
            raise MappingError(f"{where}: unknown requirement_id {req!r}")
        if req in seen:
            raise MappingError(f"{where}: duplicate row for {req}")
        seen.add(req)

        controls = row["controls"]
        if not isinstance(controls, list) or not controls:
            raise MappingError(f"{where} ({req}): controls must be a non-empty list")
        for control in controls:
            if not isinstance(control, str) or not CONTROL_ID_RE.fullmatch(control):
                raise MappingError(f"{where} ({req}): malformed control id {control!r}")
        if len(set(controls)) != len(controls):
            raise MappingError(f"{where} ({req}): duplicate control ids in {controls}")

        rationale = row["rationale"]
        if not isinstance(rationale, str) or not rationale.strip():
            raise MappingError(f"{where} ({req}): rationale must be a non-empty string")

        if row["status"] not in STATUSES:
            raise MappingError(
                f"{where} ({req}): status must be one of {sorted(STATUSES)}, got {row['status']!r}"
            )


def is_approved(row: dict[str, Any]) -> bool:
    """True only when the row's status is exactly ``approved``."""
    return row.get("status") == "approved"
