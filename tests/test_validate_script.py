"""scripts/validate.sh, run against a stub oscal-cli that records how it was called."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "validate.sh"
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(BASH is None, reason="bash is not available")

STUB = """#!/usr/bin/env bash
echo "$*" >> "${STUB_LOG}"
exit "${STUB_EXIT:-0}"
"""


@pytest.fixture
def stub(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    cli = bin_dir / "oscal-cli"
    cli.write_text(STUB, newline="\n")
    cli.chmod(0o755)
    return cli


def run(stub, *files, oscal_cli=None, exit_code=0):
    log = stub.parent.parent / "calls.log"
    log.write_text("")
    env = dict(os.environ)
    env["PATH"] = f"{stub.parent}{os.pathsep}{env['PATH']}"
    env["OSCAL_CLI"] = oscal_cli or stub.as_posix()
    env["STUB_LOG"] = log.as_posix()
    env["STUB_EXIT"] = str(exit_code)
    proc = subprocess.run(
        [BASH, SCRIPT.as_posix(), *(Path(f).as_posix() for f in files)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    calls = [line.split() for line in log.read_text().splitlines()]
    return proc, calls


def write_json(path, doc):
    path.write_text(json.dumps(doc, indent=2))
    return path


def test_json_model_comes_from_the_top_level_key(stub, tmp_path):
    # A nested key named like a root ("profile") appears in the file before the
    # real root, and other top-level keys ("$schema") precede the root.
    doc = {
        "$schema": "https://example.org/oscal_complete_schema.json",
        "x-note": {"profile": "not the root"},
        "component-definition": {"metadata": {}},
    }
    path = write_json(tmp_path / "cd.json", doc)
    text = path.read_text()
    assert text.index('"profile"') < text.index('"component-definition"')
    proc, calls = run(stub, path)
    assert proc.returncode == 0, proc.stderr
    assert calls == [["component-definition", "validate", path.as_posix()]]


def test_json_nested_root_name_alone_is_not_detected(stub, tmp_path):
    path = write_json(tmp_path / "x.json", {"not-oscal": {"profile": {}}})
    proc, calls = run(stub, path)
    assert proc.returncode != 0
    assert "cannot detect the OSCAL model" in proc.stderr
    assert calls == []


def test_xml_and_yaml_models(stub, tmp_path):
    xml = tmp_path / "ar.xml"
    xml.write_text('<?xml version="1.0"?>\n<assessment-results xmlns="http://csrc.nist.gov/ns/oscal/1.0">\n</assessment-results>\n')
    yaml = tmp_path / "ssp.yaml"
    yaml.write_text("system-security-plan:\n  uuid: x\n")
    proc, calls = run(stub, xml, yaml)
    assert proc.returncode == 0, proc.stderr
    assert calls == [["ar", "validate", xml.as_posix()], ["ssp", "validate", yaml.as_posix()]]


def test_validation_failure_exits_non_zero(stub, tmp_path):
    path = write_json(tmp_path / "ap.json", {"assessment-plan": {}})
    proc, calls = run(stub, path, exit_code=1)
    assert proc.returncode != 0
    assert f"FAIL {path.as_posix()}" in proc.stderr
    assert calls == [["ap", "validate", path.as_posix()]]


def test_oscal_cli_may_be_a_command_on_path(stub, tmp_path):
    path = write_json(tmp_path / "cat.json", {"catalog": {}})
    proc, calls = run(stub, path, oscal_cli="oscal-cli")
    assert proc.returncode == 0, proc.stderr
    assert calls == [["catalog", "validate", path.as_posix()]]


def test_missing_oscal_cli_exits_2(stub, tmp_path):
    path = write_json(tmp_path / "cat.json", {"catalog": {}})
    proc, calls = run(stub, path, oscal_cli="no-such-oscal-cli")
    assert proc.returncode == 2
    assert "not found" in proc.stderr
    assert calls == []
