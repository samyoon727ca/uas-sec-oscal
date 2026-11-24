"""Build OSCAL assessment results from a P2 evidence summary (``summary.json``).

The field mapping and UUID scheme are specified in docs/ve07-walkthrough.md, and
``oscal/handwritten/ve07-assessment-results.json`` is the golden reference.

The document has one result for the CI run, one observation per test case in
``test_cases`` (in file order), and one finding per (requirement, control) pair
that ``mappings/controls.yaml`` maps for the requirements the verification event
verifies. A finding is ``satisfied`` only when ``passed`` is true, ``test_cases``
has every test case the verification event expects, and every test case is
``passed``; otherwise it is ``not-satisfied``. A test case recorded as
``passed`` must have ``ok: true`` on every one of its runs, test and control alike.

Mapping rows that are not approved (see ``uas_oscal.mapping.is_approved``) are
marked as in ``uas_oscal.component``: every finding carries ``mapping-status`` (the
row's status), findings from unapproved rows get a DRAFT paragraph, and the document
title ends in ``(DRAFT)`` unless every row used is approved and the mapping's
``approved_by`` is set.

The output is deterministic: UUIDs are uuid5 values named from the run, keys are
sorted, and ``last-modified`` is the run's ``date_utc``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from uas_oscal.component import (
    DOCUMENT_VERSION,
    OSCAL_VERSION,
    _prop,
    load_requirements,
    normalize_timestamp,
    render,
    uuid5,
)
from uas_oscal.mapping import DEFAULT_MAPPING, DEFAULT_REQUIREMENTS, REPO_ROOT, is_approved, load_mapping

DEFAULT_SUMMARY = REPO_ROOT / "data" / "upstream" / "evidence" / "ve07-ci" / "20261013-0d3ca38" / "summary.json"

# Requirements each supported verification event verifies, the test cases its
# summary must record for its findings to be satisfied, and the assessment plan
# its results import. P1's verification table also lists SR-010 for VE-07,
# but that table is not vendored and SR-010 has no row in mappings/controls.yaml;
# the pilot assesses SR-005 only (docs/ve07-walkthrough.md).
VERIFICATION_EVENTS: dict[str, dict[str, Any]] = {
    "VE-07": {
        "requirements": ("SR-005",),
        "test_cases": ("TC-01", "TC-03", "TC-04", "TC-05", "TC-10"),
        "plan": REPO_ROOT / "oscal" / "handwritten" / "ve07-assessment-plan.json",
    },
}

# summary.json fields: required ones are mapped to OSCAL (docs/ve07-walkthrough.md);
# optional ones are known but not mapped. Any other field is rejected.
TOP_REQUIRED = ("event", "harness", "environment", "date_utc", "git", "passed", "test_cases", "runs")
TOP_OPTIONAL = (
    "host",
    "host_packages",
    "toolchain",
    "pins",
    "public_keys_sha256_der",
    "artifacts_sha256",
    "notes",
    "pcr_prediction",
    "provisioning",
)
ENV_REQUIRED = ("run_id", "run_attempt", "run_url", "workflow", "event", "ref", "sha")
ENV_OPTIONAL = ("kind", "runner_image")
GIT_REQUIRED = ("commit",)
GIT_OPTIONAL = ("cc_or_tests_modified",)
RUN_REQUIRED = ("id", "tc", "role", "title", "ok")
RUN_OPTIONAL = (
    "control_for",
    "checks",
    "data",
    "end",
    "flash",
    "keys_from",
    "keys_sent",
    "keys_until",
    "log",
    "log_sha256",
    "reboot",
    "seconds",
    "slot",
    "tpm",
    "uboot",
)

# Outcomes a test case may have in ``test_cases``. Any other value is rejected rather
# than silently treated as not passed.
TEST_OUTCOMES = ("passed", "failed", "skipped", "error")

RUN_URL_RE = re.compile(r"https://github\.com/([^/\s]+/[^/\s]+)/actions/runs/([0-9]+)")
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
CONTROL_TITLE_RE = re.compile(r"([a-z]{2})-([0-9]+)(?:\.([0-9]+))?")


class SummaryError(ValueError):
    """summary.json is malformed, has unknown fields or is missing a field."""


def _check_keys(obj: Any, where: str, required: tuple[str, ...], optional: tuple[str, ...]) -> None:
    if not isinstance(obj, dict):
        raise SummaryError(f"{where} must be an object, got {type(obj).__name__}")
    missing = [k for k in required if k not in obj]
    if missing:
        raise SummaryError(f"{where}: missing field(s) {', '.join(missing)}")
    unknown = sorted(set(obj) - set(required) - set(optional))
    if unknown:
        raise SummaryError(f"{where}: unknown field(s) {', '.join(unknown)}")


def _check_str(obj: dict[str, Any], key: str, where: str) -> None:
    value = obj[key]
    if not isinstance(value, str) or not value.strip():
        raise SummaryError(f"{where}.{key} must be a non-empty string, got {value!r}")


def _check_bool(obj: dict[str, Any], key: str, where: str) -> None:
    if not isinstance(obj[key], bool):
        raise SummaryError(f"{where}.{key} must be true or false, got {obj[key]!r}")


def validate_summary(summary: Any) -> None:
    """Raise ``SummaryError`` unless ``summary`` has every mapped field and no unknown ones."""
    _check_keys(summary, "summary", TOP_REQUIRED, TOP_OPTIONAL)
    for key in ("event", "harness"):
        _check_str(summary, key, "summary")
    _check_bool(summary, "passed", "summary")
    _check_str(summary, "date_utc", "summary")
    try:
        normalize_timestamp(summary["date_utc"])
    except ValueError as exc:
        raise SummaryError(f"summary.date_utc: {exc}") from exc

    env = summary["environment"]
    _check_keys(env, "environment", ENV_REQUIRED, ENV_OPTIONAL)
    for key in ENV_REQUIRED:
        _check_str(env, key, "environment")
    match = RUN_URL_RE.fullmatch(env["run_url"])
    if not match:
        raise SummaryError(
            f"environment.run_url must be https://github.com/<owner>/<repo>/actions/runs/<id>, got {env['run_url']!r}"
        )
    if match.group(2) != env["run_id"]:
        raise SummaryError(f"environment.run_url names run {match.group(2)}, but run_id is {env['run_id']}")

    git = summary["git"]
    _check_keys(git, "git", GIT_REQUIRED, GIT_OPTIONAL)
    _check_str(git, "commit", "git")
    if not COMMIT_RE.fullmatch(git["commit"]):
        raise SummaryError(f"git.commit must be a 40-character hex commit id, got {git['commit']!r}")
    if git["commit"] != env["sha"]:
        raise SummaryError(f"git.commit {git['commit']} differs from environment.sha {env['sha']}")

    test_cases = summary["test_cases"]
    if not isinstance(test_cases, dict) or not test_cases:
        raise SummaryError("test_cases must be a non-empty object of test case -> outcome")
    for tc, outcome in test_cases.items():
        _check_str(test_cases, tc, "test_cases")
        if outcome not in TEST_OUTCOMES:
            raise SummaryError(
                f"test_cases.{tc}: unknown outcome {outcome!r}; expected one of {', '.join(TEST_OUTCOMES)}"
            )

    runs = summary["runs"]
    if not isinstance(runs, list):
        raise SummaryError(f"runs must be a list, got {type(runs).__name__}")
    run_ids: dict[str, int] = {}
    for i, run in enumerate(runs):
        where = f"runs[{i}]"
        _check_keys(run, where, RUN_REQUIRED, RUN_OPTIONAL)
        for key in ("id", "tc", "role", "title"):
            _check_str(run, key, where)
        _check_bool(run, "ok", where)
        control_for = run.get("control_for")
        if control_for is not None and not (isinstance(control_for, str) and control_for.strip()):
            raise SummaryError(f"{where}.control_for must be null or a non-empty string, got {control_for!r}")
        if run["tc"] not in test_cases:
            raise SummaryError(f"{where} ({run['id']}): test case {run['tc']} is not in test_cases")
        if run["id"] in run_ids:
            raise SummaryError(f"{where}: duplicate run id {run['id']} (also runs[{run_ids[run['id']]}])")
        run_ids[run["id"]] = i
    for tc, outcome in test_cases.items():
        tc_runs = [run for run in runs if run["tc"] == tc]
        if not tc_runs:
            raise SummaryError(f"test_cases.{tc}: no runs recorded for it in runs")
        # A test case passes only if all its runs are ok. For a control run, ok means the
        # control showed the expected behaviour (e.g. stock U-Boot accepts what the test
        # build refuses), so a failed control also leaves the test case unproven.
        failed_runs = [run["id"] for run in tc_runs if not run["ok"]]
        if outcome == "passed" and failed_runs:
            raise SummaryError(
                f"test_cases.{tc} is 'passed', but its run(s) {', '.join(failed_runs)} have ok: false"
            )


def load_summary(path: Path) -> tuple[dict[str, Any], str]:
    """Parse and validate ``path``; return the summary and the SHA-256 of the file's bytes."""
    data = path.read_bytes()
    try:
        summary = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SummaryError(f"{path}: invalid JSON: {exc}") from exc
    try:
        validate_summary(summary)
    except SummaryError as exc:
        raise SummaryError(f"{path}: {exc}") from exc
    return summary, hashlib.sha256(data).hexdigest()


def control_title(control: str) -> str:
    """``si-7`` -> ``SI-7``; ``si-7.15`` -> ``SI-7(15)``."""
    match = CONTROL_TITLE_RE.fullmatch(control)
    if not match:
        return control.upper()
    family, number, enhancement = match.groups()
    title = f"{family.upper()}-{number}"
    return f"{title}({enhancement})" if enhancement else title


def _relative_href(target: Path, output: Path) -> str:
    try:
        rel = os.path.relpath(target.resolve(), output.resolve().parent)
    except ValueError as exc:  # e.g. different drives on Windows
        raise ValueError(f"cannot link {target} relative to {output}: {exc}") from exc
    return Path(rel).as_posix()


def _runs_text(summary: dict[str, Any], tc: str) -> str:
    lines = []
    for run in summary["runs"]:
        if run["tc"] != tc:
            continue
        role = f"control for {run['control_for']}" if run.get("control_for") else run["role"]
        ok = "true" if run["ok"] else "false"
        lines.append(f"- {run['id']} ({role}): {run['title']}. ok: {ok}")
    return "\n".join(lines)


def _finding_description(
    summary: dict[str, Any],
    statement: str,
    req_id: str,
    control: str,
    row: dict[str, Any],
    state: str,
    missing: list[str],
) -> str:
    event = summary["event"]
    run_id = summary["environment"]["run_id"]
    commit = summary["git"]["commit"]
    passed = "true" if summary["passed"] else "false"
    failing = [(tc, outcome) for tc, outcome in summary["test_cases"].items() if outcome != "passed"]
    if failing:
        listed = ", ".join(f"{tc} (`{outcome}`)" for tc, outcome in failing)
        cases = f"these test cases are not `passed`: {listed}"
    else:
        cases = f"test cases {', '.join(summary['test_cases'])} are all `passed`"
    if missing:
        cases += f". Expected test case(s) {', '.join(missing)} are missing from `test_cases`"
    parts = [
        f'Requirement {req_id}: "{statement}"',
        f"{event} CI run {run_id} at commit {commit} reports `passed: {passed}`, and {cases}. "
        f"The {control_title(control)} objective is therefore `{state}` for {req_id} at this commit.",
    ]
    if not is_approved(row):
        parts.append(f"DRAFT: this mapping row is `{row['status']}`, not approved by the owner.")
    return "\n\n".join(parts)


def build_assessment_results(
    summary: dict[str, Any],
    summary_sha256: str,
    mapping: dict[str, Any],
    requirements: dict[str, dict[str, str]],
    ve: str,
    summary_href: str,
    plan_href: str,
) -> dict[str, Any]:
    event = summary["event"]
    if event != ve:
        raise SummaryError(f"summary.json is for {event}, not {ve}")
    if ve not in VERIFICATION_EVENTS:
        raise ValueError(f"unsupported verification event {ve}; supported: {', '.join(VERIFICATION_EVENTS)}")

    env = summary["environment"]
    commit = summary["git"]["commit"]
    short = commit[:7]
    date = normalize_timestamp(summary["date_utc"])
    run_name = f"{event}/{env['run_id']}/{env['run_attempt']}"
    source_repo = RUN_URL_RE.fullmatch(env["run_url"]).group(1)

    # (requirement, control, mapping row) for every control mapped to a requirement this VE verifies.
    rows = {row["requirement_id"]: row for row in mapping["mappings"]}
    ve_requirements = VERIFICATION_EVENTS[ve]["requirements"]
    unmapped = [req for req in ve_requirements if req not in rows]
    if unmapped:
        raise ValueError(f"{ve} verifies {', '.join(unmapped)}, which has no row in the control mapping")
    pairs = [(req, control, rows[req]) for req in ve_requirements for control in rows[req]["controls"]]
    draft = mapping["approved_by"] is None or not all(is_approved(rows[req]) for req in ve_requirements)

    evidence = [
        {
            "href": summary_href,
            "description": (
                f"{event} evidence summary for commit {commit}, vendored from {source_repo} "
                f"(SHA-256 {summary_sha256})."
            ),
        },
        {
            "href": env["run_url"],
            "description": f"GitHub Actions run {env['run_id']} of workflow `{env['workflow']}`.",
        },
    ]
    observations = []
    for tc, outcome in summary["test_cases"].items():
        observations.append(
            {
                "uuid": uuid5(f"observation/{run_name}/{tc}"),
                "title": f"{event} {tc}: {outcome}",
                "description": (
                    f"summary.json records {tc} as `{outcome}` (`test_cases.{tc}`) for {event} CI run "
                    f"{env['run_id']}, attempt {env['run_attempt']}, at commit {commit}.\n\n"
                    f"Runs recorded for {tc} in `runs`:\n\n{_runs_text(summary, tc)}"
                ),
                "props": [_prop("test-case", tc), _prop("test-outcome", outcome), _prop("git-commit", commit)],
                "methods": ["TEST"],
                "types": ["control-objective"],
                "collected": date,
                "relevant-evidence": [dict(e) for e in evidence],
            }
        )

    # A summary that leaves out an expected test case does not prove the requirement,
    # even if everything it does record passed.
    missing = [tc for tc in VERIFICATION_EVENTS[ve]["test_cases"] if tc not in summary["test_cases"]]
    satisfied = (
        summary["passed"] is True
        and not missing
        and all(v == "passed" for v in summary["test_cases"].values())
    )
    state = "satisfied" if satisfied else "not-satisfied"
    findings = []
    for req_id, control, row in pairs:
        findings.append(
            {
                "uuid": uuid5(f"finding/{run_name}/{req_id}/{control}"),
                "title": f"{req_id} against {control_title(control)}: {state}",
                "description": _finding_description(
                    summary, requirements[req_id]["statement"], req_id, control, row, state, missing
                ),
                "props": [_prop("requirement-id", req_id), _prop("mapping-status", row["status"])],
                "target": {
                    "type": "objective-id",
                    "target-id": f"{control}_obj",
                    "title": f"Assessment objective of control {control}",
                    "status": {"state": state},
                },
                "related-observations": [{"observation-uuid": obs["uuid"]} for obs in observations],
            }
        )

    against = "; ".join(
        f"{req} against " + _join([control_title(c) for c in rows[req]["controls"]]) for req in ve_requirements
    )
    title = f"{event} assessment results: {against} at commit {short}"
    if draft:
        title += " (DRAFT)"
    controls = list(dict.fromkeys(control for _, control, _ in pairs))

    return {
        "assessment-results": {
            "uuid": uuid5(f"assessment-results/{run_name}"),
            "metadata": {
                "title": title,
                "last-modified": date,
                "version": DOCUMENT_VERSION,
                "oscal-version": OSCAL_VERSION,
                "remarks": (
                    "Generated by `uas-oscal results` from the evidence summary, the P1 requirements and "
                    "mappings/controls.yaml; see docs/ve07-walkthrough.md. Do not edit by hand."
                ),
            },
            "import-ap": {"href": plan_href},
            "results": [
                {
                    "uuid": uuid5(f"result/{run_name}"),
                    "title": f"{event} CI run {env['run_id']} (`{env['workflow']}`, commit {short})",
                    "description": (
                        f"Results of the `{env['workflow']}` GitHub Actions workflow, run {env['run_id']}, "
                        f"attempt {env['run_attempt']}, triggered by `{env['event']}` on `{env['ref']}` "
                        f"at commit {commit}. The harness was `{summary['harness']}`."
                    ),
                    "start": date,
                    "props": [
                        _prop("verification-event", event),
                        _prop("ci-run-id", env["run_id"]),
                        _prop("ci-run-attempt", env["run_attempt"]),
                        _prop("ci-workflow", env["workflow"]),
                        _prop("git-ref", env["ref"]),
                        _prop("git-commit", commit),
                    ],
                    "reviewed-controls": {
                        "control-selections": [
                            {"include-controls": [{"control-id": control} for control in controls]}
                        ]
                    },
                    "observations": observations,
                    "findings": findings,
                }
            ],
        }
    }


def _join(items: list[str]) -> str:
    if len(items) <= 2:
        return " and ".join(items)
    return ", ".join(items[:-1]) + f" and {items[-1]}"


def generate(
    summary_path: Path,
    output_path: Path,
    ve: str,
    mapping_path: Path = DEFAULT_MAPPING,
    requirements_path: Path = DEFAULT_REQUIREMENTS,
) -> str:
    """Return the assessment results for ``summary_path`` as JSON text.

    Hrefs to the evidence summary and the assessment plan are relative to ``output_path``.
    """
    if ve not in VERIFICATION_EVENTS:
        raise ValueError(f"unsupported verification event {ve}; supported: {', '.join(VERIFICATION_EVENTS)}")
    summary, sha256 = load_summary(summary_path)
    requirements = load_requirements(requirements_path)
    mapping = load_mapping(mapping_path, requirements_path)
    doc = build_assessment_results(
        summary,
        sha256,
        mapping,
        requirements,
        ve,
        summary_href=_relative_href(summary_path, output_path),
        plan_href=_relative_href(VERIFICATION_EVENTS[ve]["plan"], output_path),
    )
    return render(doc)
