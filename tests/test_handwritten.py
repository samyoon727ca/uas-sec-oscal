"""The hand-written VE-07 assessment results must agree with summary.json (docs/ve07-walkthrough.md)."""

import csv
import json
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HANDWRITTEN = ROOT / "oscal" / "handwritten"
REQUIREMENTS_PATH = ROOT / "data" / "upstream" / "p1" / "requirements.csv"
SUMMARY_PATH = ROOT / "data" / "upstream" / "evidence" / "ve07-ci" / "20261013-0d3ca38" / "summary.json"
NS = uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/samyoon727ca/uas-sec-oscal")
UAS_NS = "https://github.com/samyoon727ca/uas-sec-oscal/ns/oscal"

SUMMARY = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
AR = json.loads((HANDWRITTEN / "ve07-assessment-results.json").read_text(encoding="utf-8"))["assessment-results"]
AP = json.loads((HANDWRITTEN / "ve07-assessment-plan.json").read_text(encoding="utf-8"))["assessment-plan"]
RESULT = AR["results"][0]
RUN = f"{SUMMARY['event']}/{SUMMARY['environment']['run_id']}/{SUMMARY['environment']['run_attempt']}"


def uuid5(name):
    return str(uuid.uuid5(NS, name))


def props(obj):
    out = {}
    for prop in obj.get("props", []):
        assert prop["ns"] == UAS_NS
        out[prop["name"]] = prop["value"]
    return out


def test_namespace_matches_walkthrough():
    assert str(NS) == "fbf96b6c-1b0d-5a82-be27-d8f66045bb16"


def test_document_metadata_and_import():
    assert AR["uuid"] == uuid5(f"assessment-results/{RUN}")
    assert AR["metadata"]["oscal-version"] == "1.1.2"
    assert AR["metadata"]["last-modified"] == SUMMARY["date_utc"]
    assert (HANDWRITTEN / AR["import-ap"]["href"]).is_file()
    assert AP["uuid"] == uuid5(f"assessment-plan/{SUMMARY['event']}")
    assert AR["metadata"]["title"] == (
        f"{SUMMARY['event']} assessment results: SR-005 against SI-7 at commit {SUMMARY['git']['commit'][:7]}"
    )


def test_plan_stub_import_ssp_resource():
    (resource,) = AP["back-matter"]["resources"]
    assert resource["uuid"] == uuid5(f"assessment-plan/{SUMMARY['event']}/import-ssp")
    assert AP["import-ssp"]["href"] == f"#{resource['uuid']}"
    assert AP["metadata"]["last-modified"] == SUMMARY["date_utc"]


def test_single_result_describes_the_run():
    env = SUMMARY["environment"]
    assert len(AR["results"]) == 1
    assert RESULT["uuid"] == uuid5(f"result/{RUN}")
    assert RESULT["start"] == SUMMARY["date_utc"]
    assert "end" not in RESULT
    assert props(RESULT) == {
        "verification-event": SUMMARY["event"],
        "ci-run-id": env["run_id"],
        "ci-run-attempt": env["run_attempt"],
        "ci-workflow": env["workflow"],
        "git-ref": env["ref"],
        "git-commit": SUMMARY["git"]["commit"],
    }
    assert SUMMARY["git"]["commit"] == env["sha"]
    assert SUMMARY["git"]["commit"].startswith("0d3ca38")
    assert RESULT["title"] == (
        f"{SUMMARY['event']} CI run {env['run_id']} (`{env['workflow']}`, commit {SUMMARY['git']['commit'][:7]})"
    )
    assert RESULT["description"] == (
        f"Results of the `{env['workflow']}` GitHub Actions workflow, run {env['run_id']}, "
        f"attempt {env['run_attempt']}, triggered by `{env['event']}` on `{env['ref']}` "
        f"at commit {SUMMARY['git']['commit']}. The harness was `{SUMMARY['harness']}`."
    )
    assert RESULT["reviewed-controls"] == {"control-selections": [{"include-controls": [{"control-id": "si-7"}]}]}


def test_one_observation_per_test_case():
    observations = RESULT["observations"]
    assert [props(o)["test-case"] for o in observations] == list(SUMMARY["test_cases"])
    for obs in observations:
        tc = props(obs)["test-case"]
        assert obs["uuid"] == uuid5(f"observation/{RUN}/{tc}")
        assert props(obs) == {
            "test-case": tc,
            "test-outcome": SUMMARY["test_cases"][tc],
            "git-commit": SUMMARY["git"]["commit"],
        }
        assert obs["title"] == f"{SUMMARY['event']} {tc}: {SUMMARY['test_cases'][tc]}"
        assert obs["collected"] == SUMMARY["date_utc"]
        hrefs = [e["href"] for e in obs["relevant-evidence"]]
        assert (HANDWRITTEN / hrefs[0]).resolve() == SUMMARY_PATH
        assert hrefs[1] == SUMMARY["environment"]["run_url"]
        expected = []
        for run in SUMMARY["runs"]:
            if run["tc"] != tc:
                continue
            role = f"control for {run['control_for']}" if run.get("control_for") else run["role"]
            ok = "true" if run["ok"] else "false"
            expected.append(f"- {run['id']} ({role}): {run['title']}. ok: {ok}")
        assert expected
        bullets = [line for line in obs["description"].splitlines() if line.startswith("- ")]
        assert bullets == expected


def test_finding_status_follows_the_run_outcome():
    (finding,) = RESULT["findings"]
    passed = SUMMARY["passed"] is True and all(v == "passed" for v in SUMMARY["test_cases"].values())
    assert finding["uuid"] == uuid5(f"finding/{RUN}/SR-005/si-7")
    assert props(finding) == {"requirement-id": "SR-005"}
    assert finding["title"] == f"SR-005 against SI-7: {finding['target']['status']['state']}"
    with REQUIREMENTS_PATH.open(newline="", encoding="utf-8") as f:
        (statement,) = [row["statement"] for row in csv.DictReader(f) if row["req_id"] == "SR-005"]
    assert f'Requirement SR-005: "{statement}"' in finding["description"]
    assert f"test cases {', '.join(SUMMARY['test_cases'])} are all `passed`" in finding["description"]
    assert f"{SUMMARY['event']} CI run {SUMMARY['environment']['run_id']}" in finding["description"]
    assert SUMMARY["git"]["commit"] in finding["description"]
    assert finding["target"]["type"] == "objective-id"
    assert finding["target"]["target-id"] == "si-7_obj"
    assert finding["target"]["status"]["state"] == ("satisfied" if passed else "not-satisfied")
    assert [r["observation-uuid"] for r in finding["related-observations"]] == [
        o["uuid"] for o in RESULT["observations"]
    ]


@pytest.mark.parametrize("path", sorted(HANDWRITTEN.glob("*.json")), ids=lambda p: p.name)
def test_uuids_are_unique(path):
    text = path.read_text(encoding="utf-8")
    seen = {}

    def collect(node):
        if isinstance(node, dict):
            if "uuid" in node:
                assert node["uuid"] not in seen
                seen[node["uuid"]] = node
            for value in node.values():
                collect(value)
        elif isinstance(node, list):
            for value in node:
                collect(value)

    collect(json.loads(text))
    assert seen
