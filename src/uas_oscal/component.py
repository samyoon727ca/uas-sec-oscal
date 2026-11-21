"""Build the OSCAL component definition from the P1 requirements, the P1 trace and the control mapping.

The document has one component, the UAS P2 verified-boot subsystem, with one
control implementation against the NIST SP 800-53 Rev. 5 catalog. Every
(requirement, control) pair in the mapping becomes one implemented requirement.
Its description carries the requirement statement, the mapping rationale and the
threats that ``trace.csv`` traces to the requirement.

Rows that are not approved (see ``uas_oscal.mapping.is_approved``) are still
emitted, but they carry ``mapping-status`` with the row's status, and the document
title ends in ``(DRAFT)`` unless every row is approved.

The output is deterministic: UUIDs are uuid5 values in the project namespace
(docs/ve07-walkthrough.md), keys are sorted, and ``last-modified`` comes from the
caller rather than the clock.
"""

from __future__ import annotations

import csv
import json
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from uas_oscal.mapping import DEFAULT_MAPPING, DEFAULT_REQUIREMENTS, REPO_ROOT, is_approved, load_mapping

DEFAULT_TRACE = REPO_ROOT / "data" / "upstream" / "p1" / "trace.csv"

NS = uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/samyoon727ca/uas-sec-oscal")
UAS_NS = "https://github.com/samyoon727ca/uas-sec-oscal/ns/oscal"
OSCAL_VERSION = "1.1.2"
DOCUMENT_VERSION = "1.0.0"

COMPONENT_ID = "uas-p2-verified-boot"
COMPONENT_TITLE = "UAS P2 verified-boot subsystem"
CATALOG_ID = "nist-sp-800-53-rev5"
CATALOG_HREF = (
    "https://raw.githubusercontent.com/usnistgov/oscal-content/main/"
    "nist.gov/SP800-53/rev5/json/NIST_SP-800-53_rev5_catalog.json"
)

# P1 verification methods (requirements.csv `verification` column).
VERIFICATION_METHODS = {"T": "test", "D": "demonstration", "I": "inspection", "A": "analysis"}


def uuid5(name: str) -> str:
    return str(uuid.uuid5(NS, name))


def _prop(name: str, value: str) -> dict[str, str]:
    return {"name": name, "ns": UAS_NS, "value": value}


def load_requirements(path: Path = DEFAULT_REQUIREMENTS) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return {row["req_id"]: row for row in csv.DictReader(f)}


def load_trace(path: Path = DEFAULT_TRACE) -> dict[str, list[str]]:
    """Map each requirement ID to its sorted, de-duplicated threat IDs."""
    threats: dict[str, set[str]] = {}
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            threats.setdefault(row["req_id"], set()).add(row["threat_id"])
    return {req: sorted(ids) for req, ids in threats.items()}


def normalize_timestamp(value: str) -> str:
    """Return an ISO 8601 timestamp with a UTC offset as ``YYYY-MM-DDTHH:MM:SSZ``."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid timestamp {value!r}: {exc}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp {value!r} has no UTC offset")
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def commit_timestamp(paths: list[Path]) -> str:
    """Committer date (UTC) of the most recent commit that touched any of ``paths``."""
    resolved = [str(p.resolve()) for p in paths]
    cwd = Path(resolved[0]).parent
    # A shallow clone (e.g. actions/checkout's default fetch-depth: 1) lacks the
    # history needed to find the commit that last touched the inputs; git log
    # would silently report the boundary commit's date instead.
    shallow = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if shallow.returncode == 0 and shallow.stdout.strip() == "true":
        raise ValueError(
            "the git repository is a shallow clone, so the input commit date is unknown; "
            "pass --last-modified explicitly or use a full clone (fetch-depth: 0)"
        )
    proc = subprocess.run(
        ["git", "log", "-1", "--format=%ct", "--", *resolved],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    seconds = proc.stdout.strip()
    if proc.returncode != 0 or not seconds.isdigit():
        raise ValueError(
            "cannot find a git commit for the input files; pass --last-modified explicitly"
            + (f" ({proc.stderr.strip()})" if proc.stderr.strip() else "")
        )
    return datetime.fromtimestamp(int(seconds), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _description(req: dict[str, str], row: dict[str, Any], control: str, threats: list[str]) -> str:
    method = req["verification"]
    method_text = VERIFICATION_METHODS.get(method, method)
    trace = ", ".join(threats) if threats else "none recorded in trace.csv"
    parts = [
        f"{req['req_id']}: {req['statement']}",
        f"Mapped to `{control}`: {row['rationale']}",
        f"Traces to threats: {trace}.",
        f"Verification: {method_text} ({method}), evidence in {req['evidence_repo']}. "
        f"Allocated to {req['allocated_to']}.",
    ]
    if not is_approved(row):
        parts.append(f"DRAFT: this mapping row is `{row['status']}`, not approved by the owner.")
    return "\n\n".join(parts)


def build_component_definition(
    mapping: dict[str, Any],
    requirements: dict[str, dict[str, str]],
    trace: dict[str, list[str]],
    last_modified: str,
) -> dict[str, Any]:
    rows = mapping["mappings"]
    draft = not all(is_approved(row) for row in rows)

    implemented = []
    for row in rows:
        req_id = row["requirement_id"]
        req = requirements[req_id]
        threats = trace.get(req_id, [])
        for control in row["controls"]:
            props = [_prop("requirement-id", req_id), _prop("mapping-status", row["status"])]
            props += [_prop("threat-id", threat) for threat in threats]
            implemented.append(
                {
                    "uuid": uuid5(f"implemented-requirement/{COMPONENT_ID}/{req_id}/{control}"),
                    "control-id": control,
                    "description": _description(req, row, control, threats),
                    "props": props,
                }
            )

    title = f"{COMPONENT_TITLE}: NIST SP 800-53 Rev. 5 control implementation"
    if draft:
        title += " (DRAFT)"

    return {
        "component-definition": {
            "uuid": uuid5(f"component-definition/{COMPONENT_ID}"),
            "metadata": {
                "title": title,
                "last-modified": last_modified,
                "version": DOCUMENT_VERSION,
                "oscal-version": OSCAL_VERSION,
                "remarks": (
                    "Generated by `uas-oscal component` from data/upstream/p1/requirements.csv, "
                    "data/upstream/p1/trace.csv and mappings/controls.yaml. Do not edit by hand."
                ),
            },
            "components": [
                {
                    "uuid": uuid5(f"component/{COMPONENT_ID}"),
                    "type": "software",
                    "title": COMPONENT_TITLE,
                    "description": (
                        "Verified boot of the UAS companion computer (CC), built and tested in "
                        "samyoon727ca/uas-sec-p2-verified-boot. The control implementation covers "
                        "every requirement in mappings/controls.yaml, including requirements "
                        "allocated to other UAS components; each description names the allocation."
                    ),
                    "control-implementations": [
                        {
                            "uuid": uuid5(f"control-implementation/{COMPONENT_ID}/{CATALOG_ID}"),
                            "source": CATALOG_HREF,
                            "description": (
                                "P1 security requirements mapped to NIST SP 800-53 Rev. 5 controls "
                                "in mappings/controls.yaml. Each implemented requirement is one "
                                "(requirement, control) pair; its `mapping-status` prop is the "
                                "mapping row's status, and only `approved` rows are final."
                            ),
                            "implemented-requirements": implemented,
                        }
                    ],
                }
            ],
        }
    }


def render(doc: dict[str, Any]) -> str:
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def generate(
    requirements_path: Path = DEFAULT_REQUIREMENTS,
    trace_path: Path = DEFAULT_TRACE,
    mapping_path: Path = DEFAULT_MAPPING,
    last_modified: str | None = None,
) -> str:
    """Return the component definition as JSON text.

    ``last_modified`` defaults to the date of the latest commit that touched an input.
    """
    mapping = load_mapping(mapping_path, requirements_path)
    if last_modified is None:
        last_modified = commit_timestamp([requirements_path, trace_path, mapping_path])
    else:
        last_modified = normalize_timestamp(last_modified)
    doc = build_component_definition(
        mapping, load_requirements(requirements_path), load_trace(trace_path), last_modified
    )
    return render(doc)
