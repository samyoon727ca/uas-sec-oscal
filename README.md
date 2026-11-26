# uas-sec-oscal
OSCAL continuous-ATO evidence from UAS CI runs (pilot: P2 VE-07 / SR-005)

The `uas_oscal` Python package reads P1 requirements and trace data and a P2 evidence summary, and generates OSCAL from them. NIST oscal-cli validates the output. `uas-oscal component` generates the component definition, `uas-oscal results` generates VE-07 assessment results and `uas-oscal render` turns both into a one-page Markdown summary.

**Rendered VE-07 results: [docs/results/ve07.md](docs/results/ve07.md)**

Guide to how the repo works and where it stands: [docs/GUIDE.md](docs/GUIDE.md)

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
tests/                    pytest suite; tests/fixtures/ holds a failing VE-07 summary.json for tests
scripts/
  install-oscal-cli.sh    install the pinned oscal-cli into .tools/ (gitignored)
  validate.sh             run `oscal-cli <model> validate` on OSCAL files
oscal/handwritten/        hand-written OSCAL: golden VE-07 assessment results and a stub assessment plan
oscal/generated/          generator output, committed: component-definition.json from `uas-oscal component`,
                          ve07-assessment-results.json from `uas-oscal results`
docs/results/ve07.md      rendered VE-07 results page from `uas-oscal render`, committed
docs/ve07-walkthrough.md  what the VE-07 results assert; summary.json -> OSCAL field mapping and UUID scheme
data/upstream/            vendored inputs from uas-sec-p2-verified-boot; do not edit
  PROVENANCE.md           source repo, commit and original paths
  SHA256SUMS              digests checked by tests/test_upstream.py
  p1/requirements.csv     P1 requirements
  p1/trace.csv            P1 threat-to-requirement trace
  p1/verification.csv     P1 verification events and the requirements each verifies
  evidence/ve07-ci/20261013-0d3ca38/summary.json   P2 VE-07 CI evidence summary
.github/workflows/ci.yml  `test` job: tests, then oscal-cli validation of hand-written and generated OSCAL;
                          `rebuild` job: reruns component, results and render, fails if the committed outputs
                          differ, then validates all OSCAL JSON
```

## Running tests

```sh
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
uas-oscal --help
```

Install the package before running `pytest`: the tests import `uas_oscal` and run `python -m uas_oscal`, so `pytest` in a fresh checkout without the install fails with `ModuleNotFoundError`.

## Generating the component definition

```sh
uas-oscal component --requirements data/upstream/p1/requirements.csv --trace data/upstream/p1/trace.csv \
  --mapping mappings/controls.yaml -o oscal/generated/component-definition.json
```

`--verification` (default `data/upstream/p1/verification.csv`) is the P1 verification table.

The output has one component for each P1 allocation (`allocated_to` in `requirements.csv`) that a mapped requirement has: today the companion computer (`CMP-CC`), the flight controller (`CMP-FC`) and the ground control station (`CMP-GCS`). Each component has a control implementation against the NIST SP 800-53 Rev. 5 catalog, pinned to the oscal-content `v1.6.0` release, and an `allocated-to` prop. Each (requirement, control) pair in `mappings/controls.yaml` becomes one implemented requirement of the component its requirement is allocated to. Its description holds the requirement statement, the mapping rationale, the threats that `trace.csv` traces to the requirement, the verification events that `verification.csv` lists for it, and the P1 verification method. Props in the `https://github.com/samyoon727ca/uas-sec-oscal/ns/oscal` namespace carry `requirement-id`, `threat-id` (one per threat), `verification-event` (one per event, such as `VE-07` for SR-005) and `mapping-status` (the mapping row's status). Rows that are not `approved` are still emitted, and the document title ends in `(DRAFT)` unless every row is approved and the mapping's `approved_by` is set.

The output is deterministic. UUIDs are uuid5 values in the project namespace (see [docs/ve07-walkthrough.md](docs/ve07-walkthrough.md#deterministic-uuids)), with names `component-definition/uas-p2-verified-boot`, `component/uas-p2-verified-boot/<allocation>`, `control-implementation/uas-p2-verified-boot/<allocation>/nist-sp-800-53-rev5` and `implemented-requirement/uas-p2-verified-boot/<allocation>/<SR>/<control>`, where `<allocation>` is the lower-cased `allocated_to` value (such as `cmp-cc`). Keys are sorted. `metadata.last-modified` is `--last-modified` if given, otherwise the committer date (UTC) of the latest git commit that touched `requirements.csv`, `trace.csv` or the mapping. `verification.csv` does not count: it comes from the same pinned P1 snapshot as the other two CSVs, so their commits date it; a snapshot refresh that changes only `verification.csv` leaves the date unchanged. The inputs may sit in different git repositories; each repository is checked for its own inputs. That default needs every input in a git work tree, full git history and committed inputs: for an input outside git, in a shallow clone (such as `actions/checkout` with its default `fetch-depth: 1`), or when an input file has uncommitted changes, the command fails and asks for `--last-modified`. After you change an input, commit it, rerun the command and commit the new output; `tests/test_component.py` fails if the committed file is out of date.

## Generating the VE-07 assessment results

```sh
uas-oscal results --summary data/upstream/evidence/ve07-ci/20261013-0d3ca38/summary.json \
  --mapping mappings/controls.yaml --ve VE-07 -o oscal/generated/ve07-assessment-results.json
```

The generator follows the field mapping and UUID scheme in [docs/ve07-walkthrough.md](docs/ve07-walkthrough.md), and `oscal/handwritten/ve07-assessment-results.json` is its golden reference. It emits one result for the CI run and one observation per test case. It also emits one finding for each control that `mappings/controls.yaml` maps to the requirement VE-07 verifies (SR-005), so `si-7`, `si-7.9` and `si-7.15`. A finding is `satisfied` only when `passed` is `true`, `test_cases` has every test case VE-07 expects (TC-01, TC-03, TC-04, TC-05 and TC-10), and every test case is `passed`. Otherwise it is `not-satisfied`. Findings carry the same draft marking as the component definition: a `mapping-status` prop, a DRAFT paragraph for unapproved rows, and a `(DRAFT)` title until the SR-005 row is approved and `approved_by` is set. A `summary.json` with a missing or unknown field is rejected with an error that names the field. Only VE-07 is supported.

The output is deterministic. `last-modified` is the run's `date_utc`, and the hrefs to `summary.json` and to the assessment-plan stub are relative to the output file. `tests/test_results.py` fails if the committed file is out of date. It also checks the file against the golden file and lists the intentional differences in `INTENTIONAL_DIFFERENCES`.

## Rendering the results page

```sh
uas-oscal render --results oscal/generated/ve07-assessment-results.json \
  --component oscal/generated/component-definition.json -o docs/results/ve07.md
```

These are the defaults, so `uas-oscal render` alone does the same. Like the other commands' defaults, they resolve against the checkout the package is installed from, not the current directory, so pass explicit paths when running an install from another checkout. The page has a header with the CI run, the commit it tested and the run date; a table of requirement, control, finding status, mapping status and evidence links; the test-case outcomes; the mapped requirements this run does not assess; and a short "how this was produced" section. A DRAFT banner appears when any mapping row in either document is not `approved` or either document's title ends in `(DRAFT)`. Links are relative to the output file. `tests/test_render.py` fails if the committed page is out of date.

The CI `rebuild` job reruns `component`, `results` and `render` on a full-history checkout, then runs `git diff --exit-code` on `oscal/generated/` and `docs/results/` (and fails on untracked files there). After changing an input, regenerate all three outputs in that order and commit them.

## Validating OSCAL locally

oscal-cli needs Java 11 or newer on `PATH` (or `JAVA_HOME`).

```sh
bash scripts/install-oscal-cli.sh          # downloads to .tools/oscal-cli/ and verifies the SHA-256
.tools/oscal-cli/bin/oscal-cli --version
bash scripts/validate.sh path/to/file.json [more files...]
```

`validate.sh` detects each file's model from its root (`component-definition`, `assessment-results`, `system-security-plan` and so on) in JSON, XML or YAML. It runs the matching `oscal-cli` command and exits non-zero if any file fails. Set `OSCAL_CLI` to use a different oscal-cli binary, as a path or a command name on `PATH`. JSON files are read with Python, so `python3` or `python` must be on `PATH`.
