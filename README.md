# uas-sec-oscal
OSCAL continuous-ATO evidence from UAS CI runs (pilot: P2 VE-07 / SR-005)

The `uas_oscal` Python package reads P1 requirements and trace data and a P2 evidence summary, and generates OSCAL from them. NIST oscal-cli validates the output. `uas-oscal component` generates the component definition; the `results` and `render` subcommands are still stubs.

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
oscal/generated/          generator output, committed: component-definition.json from `uas-oscal component`
docs/ve07-walkthrough.md  what the VE-07 results assert; summary.json -> OSCAL field mapping and UUID scheme
data/upstream/            vendored inputs from uas-sec-p2-verified-boot; do not edit
  PROVENANCE.md           source repo, commit and original paths
  SHA256SUMS              digests checked by tests/test_upstream.py
  p1/requirements.csv     P1 requirements
  p1/trace.csv            P1 threat-to-requirement trace
  evidence/ve07-ci/20261013-0d3ca38/summary.json   P2 VE-07 CI evidence summary
.github/workflows/ci.yml  tests, then installs oscal-cli and validates oscal/handwritten/*.json and oscal/generated/component-definition.json
```

## Running tests

```sh
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
uas-oscal --help
```

## Generating the component definition

```sh
uas-oscal component --requirements data/upstream/p1/requirements.csv --trace data/upstream/p1/trace.csv \
  --mapping mappings/controls.yaml -o oscal/generated/component-definition.json
```

The output has one component, the UAS P2 verified-boot subsystem, with a control implementation against the NIST SP 800-53 Rev. 5 catalog. Each (requirement, control) pair in `mappings/controls.yaml` becomes one implemented requirement. Its description holds the requirement statement, the mapping rationale, the threats that `trace.csv` traces to the requirement, and the P1 verification method. Props in the `https://github.com/samyoon727ca/uas-sec-oscal/ns/oscal` namespace carry `requirement-id`, `threat-id` (one per threat) and `mapping-status` (the mapping row's status). Rows that are not `approved` are still emitted, and the document title ends in `(DRAFT)` unless every row is approved.

The output has no verification-event (VE) links yet. Issue #4 asked for verification events taken from `trace.csv`, but `trace.csv` has only `threat_id,req_id`. So each implemented requirement carries its threat links plus the P1 verification method and evidence repo, but no VE IDs. VE-to-requirement links are in P1's verification table. P2 vendors that table at `data/p1/verification.csv`, in the same P1 snapshot pinned in P2's `data/p1/pin.txt`; for example, `VE-07` maps to `SR-005; SR-010`. Adding VE links (for example a `verification-event` prop) is a follow-up that vendors that file.

The output is deterministic. UUIDs are uuid5 values in the project namespace (see [docs/ve07-walkthrough.md](docs/ve07-walkthrough.md#deterministic-uuids)), with names `component-definition/uas-p2-verified-boot`, `component/uas-p2-verified-boot`, `control-implementation/uas-p2-verified-boot/nist-sp-800-53-rev5` and `implemented-requirement/uas-p2-verified-boot/<SR>/<control>`. Keys are sorted. `metadata.last-modified` is `--last-modified` if given, otherwise the committer date (UTC) of the latest git commit that touched an input file. The inputs may sit in different git repositories; each repository is checked for its own inputs. That default needs every input in a git work tree, full git history and committed inputs: for an input outside git, in a shallow clone (such as `actions/checkout` with its default `fetch-depth: 1`), or when an input file has uncommitted changes, the command fails and asks for `--last-modified`. After you change an input, commit it, rerun the command and commit the new output; `tests/test_component.py` fails if the committed file is out of date.

## Validating OSCAL locally

oscal-cli needs Java 11 or newer on `PATH` (or `JAVA_HOME`).

```sh
bash scripts/install-oscal-cli.sh          # downloads to .tools/oscal-cli/ and verifies the SHA-256
.tools/oscal-cli/bin/oscal-cli --version
bash scripts/validate.sh path/to/file.json [more files...]
```

`validate.sh` detects each file's model from its root (`component-definition`, `assessment-results`, `system-security-plan` and so on) in JSON, XML or YAML. It runs the matching `oscal-cli` command and exits non-zero if any file fails. Set `OSCAL_CLI` to use a different oscal-cli binary.
