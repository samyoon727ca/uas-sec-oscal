# uas-sec-oscal
OSCAL continuous-ATO evidence from UAS CI runs (pilot: P2 VE-07 / SR-005)

The `uas_oscal` Python package reads P1 requirements and trace data and a P2 evidence summary, and generates OSCAL from them. NIST oscal-cli validates the output. The generator itself is not written yet: the `component`, `results` and `render` subcommands are stubs.

## Pins

| Tool | Version | Where |
|---|---|---|
| OSCAL model | 1.1.2 | Bundled schemas in oscal-cli 1.0.3 (liboscal-java 3.0.3) |
| oscal-cli | 1.0.3, SHA-256 `c90166b6f94a8b32a4c0012bb3f3d32dfa54b950aed31ac1a4902ce75fc6a57e` | `scripts/install-oscal-cli.sh`, downloaded from Maven Central (`gov.nist.secauto.oscal.tools.oscal-cli:cli-core`) |
| Python | 3.11+ | `pyproject.toml` |
| Java (for oscal-cli) | 17+ (CI uses Temurin 17) | `.github/workflows/ci.yml` |

## Layout

```
src/uas_oscal/            Python package; `uas-oscal` console entry point in cli.py
tests/                    pytest suite
scripts/
  install-oscal-cli.sh    install the pinned oscal-cli into .tools/ (gitignored)
  validate.sh             run `oscal-cli <model> validate` on OSCAL files
oscal/handwritten/        hand-written OSCAL: golden VE-07 assessment results and a stub assessment plan
docs/ve07-walkthrough.md  what the VE-07 results assert; summary.json -> OSCAL field mapping and UUID scheme
data/upstream/            vendored inputs from uas-sec-p2-verified-boot; do not edit
  PROVENANCE.md           source repo, commit and original paths
  SHA256SUMS              digests checked by tests/test_upstream.py
  p1/requirements.csv     P1 requirements
  p1/trace.csv            P1 threat-to-requirement trace
  evidence/ve07-ci/20261013-0d3ca38/summary.json   P2 VE-07 CI evidence summary
.github/workflows/ci.yml  tests, then installs oscal-cli and validates oscal/handwritten/*.json
```

## Running tests

```sh
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
uas-oscal --help
```

## Validating OSCAL locally

oscal-cli needs Java 11 or newer on `PATH` (or `JAVA_HOME`).

```sh
bash scripts/install-oscal-cli.sh          # downloads to .tools/oscal-cli/ and verifies the SHA-256
.tools/oscal-cli/bin/oscal-cli --version
bash scripts/validate.sh path/to/file.json [more files...]
```

`validate.sh` detects each file's model from its root (`component-definition`, `assessment-results`, `system-security-plan` and so on) in JSON, XML or YAML. It runs the matching `oscal-cli` command and exits non-zero if any file fails. Set `OSCAL_CLI` to use a different oscal-cli binary.
