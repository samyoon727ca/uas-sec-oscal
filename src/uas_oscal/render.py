"""Render generated OSCAL as a one-page Markdown summary (``uas-oscal render``).

Reads the assessment results from ``uas-oscal results`` and the component definition
from ``uas-oscal component`` and returns Markdown with:

- a header naming the CI run, the commit it tested and the run date;
- a table of requirement -> control -> finding status -> evidence, with one row per
  (requirement, control) pair the component definition lists for each assessed
  requirement;
- a DRAFT banner when any mapping row in either document is not ``approved``, or
  either document title is marked ``(DRAFT)``;
- the test-case outcomes, the mapped requirements this run does not assess, and a
  short "how this was produced" section.

Links are relative to the output file, so the page works when browsed on GitHub.
The output is deterministic: it depends only on the two input documents and the
output path.
"""

from __future__ import annotations

import json
import os
import posixpath
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

from uas_oscal.component import UAS_NS
from uas_oscal.mapping import REPO_ROOT
from uas_oscal.results import control_title

DEFAULT_RESULTS = REPO_ROOT / "oscal" / "generated" / "ve07-assessment-results.json"
DEFAULT_COMPONENT = REPO_ROOT / "oscal" / "generated" / "component-definition.json"
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "results" / "ve07.md"

RUN_URL_RE = re.compile(r"https://github\.com/([^/\s]+/[^/\s]+)/actions/runs/([0-9]+)")
OBJECTIVE_RE = re.compile(r"(.+)_obj")
STATE_LABELS = {"satisfied": "✅ satisfied", "not-satisfied": "❌ not satisfied"}


class RenderError(ValueError):
    """An input document is missing something the page needs."""


def _get(obj: Any, *keys: str | int) -> Any:
    where = ""
    for key in keys:
        try:
            obj = obj[key]
        except (KeyError, IndexError, TypeError):
            raise RenderError(f"missing {where}{key}" if where else f"missing {key}") from None
        where += f"{key}."
    return obj


def _props(obj: dict[str, Any], name: str) -> list[str]:
    values = []
    for p in obj.get("props", []):
        if p.get("ns") == UAS_NS and p.get("name") == name:
            value = p.get("value")
            if not isinstance(value, str):
                raise RenderError(f"`{name}` prop has no string value")
            values.append(value)
    return values


def _prop(obj: dict[str, Any], name: str, where: str) -> str:
    values = _props(obj, name)
    if len(values) != 1:
        raise RenderError(f"{where}: expected one `{name}` prop, found {len(values)}")
    return values[0]


def _cell(text: str) -> str:
    """Escape text for a Markdown table cell."""
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def _link_text(text: str) -> str:
    """Escape text for Markdown link text inside a table cell."""
    return _cell(text).replace("[", "\\[").replace("]", "\\]")


def _url(href: str) -> str:
    """Percent-encode an absolute URL for use as a Markdown link destination.

    Spaces, parentheses, angle brackets, square brackets, pipes and other characters
    that would end or break the link (or the table cell) are encoded; existing
    ``%XX`` escapes and URL delimiters are kept.
    """
    return quote(href, safe="/:?#@!$&'*+,;=%~")


def _load(path: Path, root: str) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RenderError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(doc, dict) or root not in doc:
        raise RenderError(f"{path}: not an OSCAL {root} document")
    return doc[root]


def _link(target: Path, output: Path) -> str:
    try:
        rel = os.path.relpath(target.resolve(), output.resolve().parent)
    except ValueError as exc:  # e.g. different drives on Windows
        raise RenderError(f"cannot link {target} relative to {output}: {exc}") from exc
    return Path(rel).as_posix()


def _evidence_link(href: str, results_path: Path, output: Path) -> str:
    """Markdown link to an evidence href, rebased from the results file to the output."""
    match = RUN_URL_RE.fullmatch(href)
    if match:
        return f"[CI run {match.group(2)}]({_url(href)})"
    if "://" in href:
        return f"[{_link_text(href)}]({_url(href)})"
    target = results_path.parent / href
    return f"[{_link_text(posixpath.basename(href))}]({quote(_link(target, output))})"


def _is_draft(title: str) -> bool:
    return title.endswith("(DRAFT)")


def build_markdown(results_path: Path, component_path: Path, output: Path) -> str:
    ar = _load(results_path, "assessment-results")
    cd = _load(component_path, "component-definition")

    ar_title = _get(ar, "metadata", "title")
    cd_title = _get(cd, "metadata", "title")
    results = _get(ar, "results")
    if len(results) != 1:
        raise RenderError(f"{results_path}: expected one result, found {len(results)}")
    result = results[0]

    ve = _prop(result, "verification-event", "result")
    run_id = _prop(result, "ci-run-id", "result")
    attempt = _prop(result, "ci-run-attempt", "result")
    workflow = _prop(result, "ci-workflow", "result")
    ref = _prop(result, "git-ref", "result")
    commit = _prop(result, "git-commit", "result")
    start = _get(result, "start")

    observations = {_get(o, "uuid"): o for o in _get(result, "observations")}
    run_url = next(
        (
            ev["href"]
            for o in observations.values()
            for ev in o.get("relevant-evidence", [])
            if (m := RUN_URL_RE.fullmatch(ev.get("href", ""))) and m.group(2) == run_id
        ),
        None,
    )

    # (requirement, control) -> mapping status, in component-definition order.
    implemented: dict[tuple[str, str], str] = {}
    for component in _get(cd, "components"):
        for ci in component.get("control-implementations", []):
            for ir in _get(ci, "implemented-requirements"):
                where = f"implemented requirement {ir.get('uuid', '?')}"
                key = (_prop(ir, "requirement-id", where), _get(ir, "control-id"))
                if key in implemented:
                    raise RenderError(f"{where}: duplicate implemented requirement for {key[0]} / {key[1]}")
                implemented[key] = _prop(ir, "mapping-status", where)

    # (requirement, control) -> finding
    findings: dict[tuple[str, str], dict[str, Any]] = {}
    for finding in _get(result, "findings"):
        where = f"finding {finding.get('uuid', '?')}"
        target_id = _get(finding, "target", "target-id")
        match = OBJECTIVE_RE.fullmatch(target_id)
        if not match:
            raise RenderError(f"{where}: target-id {target_id!r} is not a control objective")
        key = (_prop(finding, "requirement-id", where), match.group(1))
        if key not in implemented:
            raise RenderError(
                f"{where}: {key[0]} / {key[1]} is not in the component definition; "
                "regenerate both documents from the same mapping"
            )
        if key in findings:
            raise RenderError(f"{where}: duplicate finding for {key[0]} / {key[1]}")
        findings[key] = finding

    assessed = list(dict.fromkeys(req for req, _ in findings))
    statuses = [*implemented.items(), *((k, _prop(f, "mapping-status", "finding")) for k, f in findings.items())]
    unapproved = sorted({req for (req, _), status in statuses if status != "approved"})
    draft = bool(unapproved) or _is_draft(ar_title) or _is_draft(cd_title)

    out: list[str] = []
    out.append(f"# {ve} assessment results")
    out.append("")
    out.append("<!-- Generated by `uas-oscal render`. Do not edit by hand. -->")
    out.append("")

    if draft:
        if unapproved:
            reason = (
                f"The control mapping for {', '.join(unapproved)} is not approved by the owner "
                "(`mapping-status` is not `approved`)."
            )
        else:
            reason = "The control mapping has no `approved_by` set."
        out.append("> [!WARNING]")
        out.append(
            f"> **DRAFT.** {reason} The requirement-to-control links below are proposals, "
            "so these findings are not an assessment of record."
        )
        out.append("")

    run_text = f"`{workflow}` run {run_id}, attempt {attempt}"
    out.append(f"- **Run:** [{run_text}]({_url(run_url)})" if run_url else f"- **Run:** {run_text}")
    repo = RUN_URL_RE.fullmatch(run_url).group(1) if run_url else None
    commit_text = f"`{commit[:7]}`"
    if repo:
        commit_text = f"[{commit_text}]({_url(f'https://github.com/{repo}/commit/{commit}')})"
    out.append(f"- **Commit:** {commit_text} on `{ref}`")
    out.append(f"- **Date:** {start}")
    out.append("")

    out.append("## Findings")
    out.append("")
    out.append("| Requirement | Control | Finding | Mapping | Evidence |")
    out.append("|---|---|---|---|---|")
    for req in assessed:
        for (r, control), status in implemented.items():
            if r != req:
                continue
            finding = findings.get((r, control))
            if finding is None:
                state = "not assessed"
                evidence: list[str] = []
            else:
                state = _get(finding, "target", "status", "state")
                state = STATE_LABELS.get(state, state)
                hrefs: list[str] = []
                for rel in finding.get("related-observations", []):
                    obs = observations.get(_get(rel, "observation-uuid"))
                    if obs is None:
                        raise RenderError(f"finding {finding.get('uuid', '?')}: unknown observation")
                    hrefs += [_get(ev, "href") for ev in obs.get("relevant-evidence", [])]
                evidence = [_evidence_link(h, results_path, output) for h in dict.fromkeys(hrefs)]
            out.append(
                f"| {_cell(req)} | {_cell(control_title(control))} | {_cell(state)} "
                f"| {_cell(status)} | {', '.join(evidence) or '—'} |"
            )
    out.append("")

    out.append("## Test cases")
    out.append("")
    out.append("| Test case | Outcome |")
    out.append("|---|---|")
    for obs in observations.values():
        where = f"observation {obs['uuid']}"
        out.append(f"| {_cell(_prop(obs, 'test-case', where))} | {_cell(_prop(obs, 'test-outcome', where))} |")
    out.append("")

    others: dict[str, list[str]] = {}
    for (req, control) in implemented:
        if req not in assessed:
            others.setdefault(req, []).append(control_title(control))
    if others:
        out.append(f"## Mapped requirements not assessed by {ve}")
        out.append("")
        for req, controls in others.items():
            out.append(f"- {req}: {', '.join(controls)}")
        out.append("")

    ar_link = _link(results_path, output)
    cd_link = _link(component_path, output)
    out.append("## How this was produced")
    out.append("")
    out.append(
        f"1. `uas-oscal component` built the [component definition]({cd_link}) from the P1 "
        "requirements and threat trace and the control mapping in `mappings/controls.yaml`."
    )
    out.append(
        f"2. `uas-oscal results` built the [assessment results]({ar_link}) from the {ve} CI evidence "
        "summary (`summary.json`) vendored from the P2 verified-boot repository. A finding is "
        "satisfied only when the run passed and every test case passed."
    )
    out.append("3. `uas-oscal render` produced this page from those two OSCAL files.")
    out.append("")
    out.append(
        "CI reruns all three commands, fails if the committed files differ from the rebuilt ones, "
        "and validates the OSCAL with NIST oscal-cli."
    )
    return "\n".join(out) + "\n"


def generate(
    results_path: Path = DEFAULT_RESULTS,
    component_path: Path = DEFAULT_COMPONENT,
    output: Path = DEFAULT_OUTPUT,
) -> str:
    """Return the Markdown page for ``results_path`` and ``component_path``."""
    return build_markdown(results_path, component_path, output)
