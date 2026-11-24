"""Build the OSCAL component definition from the P1 requirements, trace and verification table and the control mapping.

The document has one component per P1 allocation (``requirements.csv``
``allocated_to``, such as ``CMP-CC``) that a mapped requirement has, each with
one control implementation against the NIST SP 800-53 Rev. 5 catalog. Every
(requirement, control) pair in the mapping becomes one implemented requirement
of the component its requirement is allocated to. Its description carries the
requirement statement, the mapping rationale, the threats that ``trace.csv``
traces to the requirement and the verification events that ``verification.csv``
lists for it.

Rows that are not approved (see ``uas_oscal.mapping.is_approved``) are still
emitted, but they carry ``mapping-status`` with the row's status, and the document
title ends in ``(DRAFT)`` unless every row is approved and the mapping's
``approved_by`` is set.

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
DEFAULT_VERIFICATION = REPO_ROOT / "data" / "upstream" / "p1" / "verification.csv"

NS = uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/samyoon727ca/uas-sec-oscal")
UAS_NS = "https://github.com/samyoon727ca/uas-sec-oscal/ns/oscal"
OSCAL_VERSION = "1.1.2"
DOCUMENT_VERSION = "1.0.0"

DOCUMENT_ID = "uas-p2-verified-boot"
DOCUMENT_TITLE = "UAS P2 verified-boot project"
# Component titles by P1 allocation; other allocations are titled by their ID.
COMPONENT_TITLES = {
    "CMP-CC": "UAS companion computer (CC)",
    "CMP-FC": "UAS flight controller (FC)",
    "CMP-GCS": "UAS ground control station (GCS)",
}
CATALOG_ID = "nist-sp-800-53-rev5"
# Pinned to the oscal-content v1.6.0 release tag so the href always names the same catalog.
CATALOG_HREF = (
    "https://raw.githubusercontent.com/usnistgov/oscal-content/v1.6.0/"
    "nist.gov/SP800-53/rev5/json/NIST_SP-800-53_rev5_catalog.json"
)

# Columns the generator reads from the P1 CSVs.
REQUIREMENT_COLUMNS = ("req_id", "statement", "allocated_to", "verification", "evidence_repo")
TRACE_COLUMNS = ("threat_id", "req_id")
VERIFICATION_COLUMNS = ("ve_id", "req_ids")

# P1 verification methods (requirements.csv `verification` column).
VERIFICATION_METHODS = {"T": "test", "D": "demonstration", "I": "inspection", "A": "analysis"}


def uuid5(name: str) -> str:
    return str(uuid.uuid5(NS, name))


def _prop(name: str, value: str) -> dict[str, str]:
    return {"name": name, "ns": UAS_NS, "value": value}


def _read_csv(path: Path, columns: tuple[str, ...]) -> list[tuple[int, dict[str, str]]]:
    """Read ``path`` as CSV into (line number, row) pairs.

    The line number is the file line on which the row ends. Raise ``ValueError``
    naming the file if a required column or value is missing. A required value
    is missing if the row is too short to have it or if it is empty or
    whitespace-only. Values that are present are returned unchanged.
    """
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in columns if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path}: missing column(s) {', '.join(missing)}")
        rows = []
        for row in reader:
            empty = [c for c in columns if row[c] is None or not row[c].strip()]
            if empty:
                raise ValueError(f"{path}:{reader.line_num}: missing value(s) for {', '.join(empty)}")
            rows.append((reader.line_num, row))
    return rows


def load_requirements(path: Path = DEFAULT_REQUIREMENTS) -> dict[str, dict[str, str]]:
    """Map each requirement ID to its row; raise ``ValueError`` if an ID repeats."""
    requirements: dict[str, dict[str, str]] = {}
    first_line: dict[str, int] = {}
    for line, row in _read_csv(path, REQUIREMENT_COLUMNS):
        req_id = row["req_id"]
        if req_id in requirements:
            raise ValueError(f"{path}:{line}: duplicate req_id {req_id} (first on line {first_line[req_id]})")
        requirements[req_id] = row
        first_line[req_id] = line
    return requirements


def load_trace(path: Path = DEFAULT_TRACE) -> dict[str, list[str]]:
    """Map each requirement ID to its sorted, de-duplicated threat IDs."""
    threats: dict[str, set[str]] = {}
    for _, row in _read_csv(path, TRACE_COLUMNS):
        threats.setdefault(row["req_id"], set()).add(row["threat_id"])
    return {req: sorted(ids) for req, ids in threats.items()}


def load_verification(path: Path = DEFAULT_VERIFICATION) -> dict[str, list[str]]:
    """Map each requirement ID to the sorted IDs of the verification events that verify it.

    ``req_ids`` is a ``;``-separated list. Raise ``ValueError`` if a ``ve_id`` repeats
    or a ``req_ids`` entry is empty.
    """
    events: dict[str, set[str]] = {}
    first_line: dict[str, int] = {}
    for line, row in _read_csv(path, VERIFICATION_COLUMNS):
        ve_id = row["ve_id"]
        if ve_id in first_line:
            raise ValueError(f"{path}:{line}: duplicate ve_id {ve_id} (first on line {first_line[ve_id]})")
        first_line[ve_id] = line
        req_ids = [req.strip() for req in row["req_ids"].split(";")]
        if not all(req_ids):
            raise ValueError(f"{path}:{line}: empty entry in req_ids {row['req_ids']!r}")
        for req_id in req_ids:
            events.setdefault(req_id, set()).add(ve_id)
    return {req: sorted(ids) for req, ids in events.items()}


def normalize_timestamp(value: str) -> str:
    """Return an ISO 8601 timestamp with a UTC offset as ``YYYY-MM-DDTHH:MM:SSZ``."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid timestamp {value!r}: {exc}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp {value!r} has no UTC offset")
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)


def _stderr(proc: subprocess.CompletedProcess[str]) -> str:
    return f" ({proc.stderr.strip()})" if proc.stderr.strip() else ""


def _repo_commit_seconds(files: list[str]) -> int:
    """Committer date (Unix seconds) of the latest commit that touched ``files``, all in one work tree."""
    cwd = Path(files[0]).parent
    # A shallow clone (e.g. actions/checkout's default fetch-depth: 1) lacks the
    # history needed to find the commit that last touched the inputs; git log
    # would silently report the boundary commit's date instead.
    shallow = _git(["rev-parse", "--is-shallow-repository"], cwd)
    if shallow.returncode == 0 and shallow.stdout.strip() == "true":
        raise ValueError(
            f"the git repository of {files[0]} is a shallow clone, so the input commit date is unknown; "
            "pass --last-modified explicitly or use a full clone (fetch-depth: 0)"
        )
    # Uncommitted or untracked inputs would get the date of an older commit
    # that does not describe their content.
    status = _git(["status", "--porcelain", "--", *files], cwd)
    if status.returncode != 0:
        raise ValueError(
            f"cannot check {', '.join(files)} for uncommitted changes; "
            "pass --last-modified explicitly" + _stderr(status)
        )
    if status.stdout.strip():
        changed = "; ".join(line.strip() for line in status.stdout.strip().splitlines())
        raise ValueError(
            f"input files have uncommitted changes ({changed}); "
            "commit them or pass --last-modified explicitly"
        )
    log = _git(["log", "-1", "--format=%ct", "--", *files], cwd)
    seconds = log.stdout.strip()
    if log.returncode != 0 or not seconds.isdigit():
        raise ValueError(
            f"cannot find a git commit for {', '.join(files)}; "
            "pass --last-modified explicitly" + _stderr(log)
        )
    return int(seconds)


def commit_timestamp(paths: list[Path]) -> str:
    """Committer date (UTC) of the most recent commit that touched any of ``paths``.

    The inputs may sit in different git work trees: each work tree is queried
    for its own inputs, and the latest date wins.
    """
    by_repo: dict[str, list[str]] = {}
    for path in paths:
        resolved = path.resolve()
        top = _git(["rev-parse", "--show-toplevel"], resolved.parent)
        if top.returncode != 0 or not top.stdout.strip():
            raise ValueError(
                f"{path} is not in a git work tree, so its commit date is unknown; "
                "pass --last-modified explicitly" + _stderr(top)
            )
        by_repo.setdefault(top.stdout.strip(), []).append(str(resolved))
    seconds = max(_repo_commit_seconds(files) for files in by_repo.values())
    return datetime.fromtimestamp(seconds, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _description(
    req: dict[str, str], row: dict[str, Any], control: str, threats: list[str], events: list[str]
) -> str:
    method = req["verification"]
    method_text = VERIFICATION_METHODS.get(method, method)
    trace = ", ".join(threats) if threats else "none recorded in trace.csv"
    verified_by = ", ".join(events) if events else "none recorded in verification.csv"
    parts = [
        f"{req['req_id']}: {req['statement']}",
        f"Mapped to `{control}`: {row['rationale']}",
        f"Traces to threats: {trace}.",
        f"Verification events: {verified_by}.",
        f"Verification: {method_text} ({method}), evidence in {req['evidence_repo']}. "
        f"Allocated to {req['allocated_to']}.",
    ]
    if not is_approved(row):
        parts.append(f"DRAFT: this mapping row is `{row['status']}`, not approved by the owner.")
    return "\n\n".join(parts)


def _component(allocation: str, implemented: list[dict[str, Any]]) -> dict[str, Any]:
    """The component for one P1 allocation, holding the implemented requirements allocated to it."""
    slug = allocation.lower()
    title = COMPONENT_TITLES.get(allocation, f"UAS component {allocation}")
    description = (
        f"{title}, P1 allocation {allocation}. The control implementation covers the requirements in "
        f"mappings/controls.yaml that data/upstream/p1/requirements.csv allocates to {allocation}."
    )
    if allocation == "CMP-CC":
        description += (
            " Verified boot of the CC is built and tested in samyoon727ca/uas-sec-p2-verified-boot; "
            "each implemented requirement names the project (P2, P3, ...) that holds its evidence."
        )
    return {
        "uuid": uuid5(f"component/{DOCUMENT_ID}/{slug}"),
        "type": "software",
        "title": title,
        "description": description,
        "props": [_prop("allocated-to", allocation)],
        "control-implementations": [
            {
                "uuid": uuid5(f"control-implementation/{DOCUMENT_ID}/{slug}/{CATALOG_ID}"),
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


def build_component_definition(
    mapping: dict[str, Any],
    requirements: dict[str, dict[str, str]],
    trace: dict[str, list[str]],
    verification: dict[str, list[str]],
    last_modified: str,
) -> dict[str, Any]:
    rows = mapping["mappings"]
    # The owner approves the mapping by setting each row's status and approved_by
    # (mappings/controls.yaml); until both are done the document is a draft.
    draft = mapping["approved_by"] is None or not all(is_approved(row) for row in rows)

    # Implemented requirements by allocation, each in mapping order.
    by_allocation: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        req_id = row["requirement_id"]
        req = requirements[req_id]
        allocation = req["allocated_to"]
        threats = trace.get(req_id, [])
        events = verification.get(req_id, [])
        for control in row["controls"]:
            props = [_prop("requirement-id", req_id), _prop("mapping-status", row["status"])]
            props += [_prop("threat-id", threat) for threat in threats]
            props += [_prop("verification-event", event) for event in events]
            by_allocation.setdefault(allocation, []).append(
                {
                    "uuid": uuid5(f"implemented-requirement/{DOCUMENT_ID}/{allocation.lower()}/{req_id}/{control}"),
                    "control-id": control,
                    "description": _description(req, row, control, threats, events),
                    "props": props,
                }
            )

    title = f"{DOCUMENT_TITLE}: NIST SP 800-53 Rev. 5 control implementations"
    if draft:
        title += " (DRAFT)"

    return {
        "component-definition": {
            "uuid": uuid5(f"component-definition/{DOCUMENT_ID}"),
            "metadata": {
                "title": title,
                "last-modified": last_modified,
                "version": DOCUMENT_VERSION,
                "oscal-version": OSCAL_VERSION,
                "remarks": (
                    "Generated by `uas-oscal component` from data/upstream/p1/requirements.csv, "
                    "data/upstream/p1/trace.csv, data/upstream/p1/verification.csv and "
                    "mappings/controls.yaml. Do not edit by hand."
                ),
            },
            "components": [_component(allocation, by_allocation[allocation]) for allocation in sorted(by_allocation)],
        }
    }


def render(doc: dict[str, Any]) -> str:
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def generate(
    requirements_path: Path = DEFAULT_REQUIREMENTS,
    trace_path: Path = DEFAULT_TRACE,
    mapping_path: Path = DEFAULT_MAPPING,
    last_modified: str | None = None,
    verification_path: Path = DEFAULT_VERIFICATION,
) -> str:
    """Return the component definition as JSON text.

    ``last_modified`` defaults to the date of the latest commit that touched
    requirements.csv, trace.csv or the mapping.
    """
    # Load the CSVs first so a malformed header is reported as such, before
    # load_mapping reads requirements.csv for its requirement IDs.
    requirements = load_requirements(requirements_path)
    trace = load_trace(trace_path)
    verification = load_verification(verification_path)
    mapping = load_mapping(mapping_path, requirements_path)
    if last_modified is None:
        # verification.csv is left out: it comes from the same pinned P1 snapshot as
        # requirements.csv and trace.csv (data/upstream/PROVENANCE.md), so their commits
        # date it. It was vendored later, in the same commit as the output it changed,
        # and a commit cannot contain its own date.
        last_modified = commit_timestamp([requirements_path, trace_path, mapping_path])
    else:
        last_modified = normalize_timestamp(last_modified)
    return render(build_component_definition(mapping, requirements, trace, verification, last_modified))
