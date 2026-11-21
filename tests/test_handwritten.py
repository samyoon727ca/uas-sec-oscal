"""The hand-written VE-07 assessment results must agree with summary.json (docs/ve07-walkthrough.md)."""

import json
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HANDWRITTEN = ROOT / "oscal" / "handwritten"
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
        assert obs["collected"] == SUMMARY["date_utc"]
        hrefs = [e["href"] for e in obs["relevant-evidence"]]
        assert (HANDWRITTEN / hrefs[0]).resolve() == SUMMARY_PATH
        assert hrefs[1] == SUMMARY["environment"]["run_url"]
        runs = [r for r in SUMMARY["runs"] if r["tc"] == tc]
        assert runs
        for run in runs:
            ok = "true" if run["ok"] else "false"
            assert f"- {run['id']} (" in obs["description"]
            assert f"{run['title']}. ok: {ok}" in obs["description"]


def test_finding_status_follows_the_run_outcome():
    (finding,) = RESULT["findings"]
    passed = SUMMARY["passed"] is True and all(v == "passed" for v in SUMMARY["test_cases"].values())
    assert finding["uuid"] == uuid5(f"finding/{RUN}/SR-005/si-7")
    assert props(finding) == {"requirement-id": "SR-005"}
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
