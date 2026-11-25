# uas-sec-oscal: guide

This repo turns the security requirements of an uncrewed aircraft system (UAS) project, and the evidence its CI runs produce, into OSCAL documents. OSCAL is NIST's machine-readable format for security controls and assessments, and the goal is continuous authorization evidence (a "continuous ATO") that is regenerated whenever the inputs change. The pilot covers one verification event, the VE-07 verified-boot test run, assessed against NIST SP 800-53 controls. The owner reviews the outputs, and CI checks that they are current and valid.

## How it fits

- **Upstream: `samyoon727ca/uas-sec-p2-verified-boot` (P2).** P2 is the verified-boot project whose CI produced the VE-07 evidence. It also holds a pinned copy of the P1 architecture data from `samyoon727ca/uas-sec-p1-architecture`: requirements, threat trace and verification table. This repo vendors four files from P2 at commit `d23409a1…` into `data/upstream/`. The source commit, original paths and SHA-256 digests are in `data/upstream/PROVENANCE.md`.
- **Downstream:** nothing in this repo consumes its outputs yet. The committed OSCAL in `oscal/generated/` and the page `docs/results/ve07.md` are the products.
- **Tools and pinned versions** (the README's "Pins" table is the source of truth):
  - OSCAL model 1.1.2 (`OSCAL_VERSION` in `src/uas_oscal/component.py:39`).
  - NIST oscal-cli 1.0.3 from Maven Central, checked against a SHA-256 before unpacking (`scripts/install-oscal-cli.sh:14-15`). It needs Java; CI uses Temurin 17.
  - Python 3.11+ and PyYAML ≥ 6, with pytest ≥ 7 for development (`pyproject.toml`).
  - The NIST SP 800-53 Rev. 5 catalog is referenced by a URL pinned to the oscal-content `v1.6.0` tag (`src/uas_oscal/component.py:51-55`). It is never downloaded.
  - GitHub Actions are pinned by commit SHA (`.github/workflows/ci.yml`).

## How it works

Three commands of the `uas-oscal` CLI (`src/uas_oscal/cli.py`) run in order. Each output is committed.

```text
requirements.csv, trace.csv, verification.csv ─┐
mappings/controls.yaml ────────────────────────┼─► uas-oscal component ─► oscal/generated/component-definition.json
                                               │
VE-07 summary.json + mapping + requirements ───┴─► uas-oscal results ───► oscal/generated/ve07-assessment-results.json

both generated documents ─► uas-oscal render ─► docs/results/ve07.md
all OSCAL JSON ─► scripts/validate.sh (oscal-cli)
```

1. **Control mapping.** `mappings/controls.yaml` proposes which 800-53 controls each P1 requirement maps to (five rows: SR-003, SR-005, SR-007, SR-013, SR-027), with a rationale and a `status`. `src/uas_oscal/mapping.py` loads it and rejects unknown keys, unknown requirement IDs, malformed control IDs and duplicates (`validate_mapping`, `src/uas_oscal/mapping.py:49`). A row counts as approved only when its status is exactly `approved` (`is_approved`, `src/uas_oscal/mapping.py:94`).
2. **Component definition.** `src/uas_oscal/component.py` reads the three P1 CSVs and the mapping. It builds one OSCAL component for each P1 allocation (`allocated_to`, such as `CMP-CC`) and one implemented requirement for each (requirement, control) pair. Each one carries the requirement text, the rationale, its threats and its verification events (`build_component_definition`, `src/uas_oscal/component.py:268`). The document `last-modified` defaults to the date of the last git commit that touched the inputs (`commit_timestamp`, `src/uas_oscal/component.py:193`).
3. **Assessment results.** `src/uas_oscal/results.py` validates the P2 `summary.json` field by field (`validate_summary`, `src/uas_oscal/results.py:131`). It emits one result for the CI run, one observation per test case and one finding per control mapped to SR-005. A finding is `satisfied` only if the run passed, all expected test cases are present and every one passed (`src/uas_oscal/results.py:342-350`). The field mapping and UUID scheme are specified in `docs/ve07-walkthrough.md`.
4. **Results page.** `src/uas_oscal/render.py` reads the two generated documents and writes a one-page Markdown summary, `docs/results/ve07.md`. Every input value is escaped before it reaches the Markdown (`src/uas_oscal/render.py:167-169`).
5. **Validation.** `scripts/validate.sh` detects each file's OSCAL model from its root key and runs `oscal-cli <model> validate` on it.

Draft marking runs through all three outputs. Until every relevant mapping row is `approved` and `approved_by` is set in `mappings/controls.yaml`, titles end in `(DRAFT)`, props carry `mapping-status`, and the page shows a DRAFT banner.

## Code map

| Path | What's there |
|---|---|
| `src/uas_oscal/cli.py` | `uas-oscal` entry point and its three subcommands, with their arguments and defaults |
| `src/uas_oscal/mapping.py` | Loads and validates `mappings/controls.yaml`; `is_approved` |
| `src/uas_oscal/component.py` | Component-definition generator, the shared uuid5 namespace and the JSON writer |
| `src/uas_oscal/results.py` | Assessment-results generator; `VERIFICATION_EVENTS` lists the supported events (only VE-07) |
| `src/uas_oscal/render.py` | Markdown renderer for the results page |
| `mappings/controls.yaml` | Requirement → control mapping; every row is `proposed` and awaits owner review |
| `data/upstream/` | Vendored P1/P2 inputs; do not edit (`PROVENANCE.md`, `SHA256SUMS`) |
| `oscal/handwritten/` | Hand-written golden VE-07 assessment results and the assessment-plan stub they import |
| `oscal/generated/` | Committed generator output |
| `docs/results/ve07.md` | Committed rendered results page |
| `docs/ve07-walkthrough.md` | What the VE-07 results assert, the summary.json → OSCAL field mapping and the UUID scheme |
| `scripts/install-oscal-cli.sh`, `scripts/validate.sh` | Install the pinned oscal-cli into `.tools/` (gitignored); validate OSCAL files |
| `tests/` | pytest suite; `tests/fixtures/` has a failing VE-07 summary and an invalid catalog |
| `.github/workflows/ci.yml` | CI jobs `test` and `rebuild` |

## Run it and test it

Setup and tests, as in the README:

```sh
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
```

Install the package first: the tests import `uas_oscal` and run `python -m uas_oscal`.

Regenerate the outputs in this order (the same commands the CI `rebuild` job runs):

```sh
uas-oscal component --requirements data/upstream/p1/requirements.csv --trace data/upstream/p1/trace.csv \
  --mapping mappings/controls.yaml -o oscal/generated/component-definition.json
uas-oscal results --summary data/upstream/evidence/ve07-ci/20261013-0d3ca38/summary.json \
  --mapping mappings/controls.yaml --ve VE-07 -o oscal/generated/ve07-assessment-results.json
uas-oscal render --results oscal/generated/ve07-assessment-results.json \
  --component oscal/generated/component-definition.json -o docs/results/ve07.md
```

`uas-oscal component` needs a full-history git checkout with the inputs committed. Otherwise pass `--last-modified`. This is why the `rebuild` job checks out with `fetch-depth: 0`.

Validate OSCAL (needs network for the download and Java on `PATH`):

```sh
bash scripts/install-oscal-cli.sh
.tools/oscal-cli/bin/oscal-cli --version
bash scripts/validate.sh oscal/handwritten/*.json oscal/generated/*.json
```

Special needs: `pytest` needs no network, Java or oscal-cli. `tests/test_validate_script.py` runs `validate.sh` against a stub oscal-cli and is skipped if `bash` is missing. The real oscal-cli runs only in CI: both jobs install it on `ubuntu-latest` with Python 3.11 and Java 17. Its download from Maven Central retries on rate limits (`scripts/install-oscal-cli.sh:41-42`).

CI (`.github/workflows/ci.yml`) runs on every push and pull request:

- **`test`:** `pip install -e ".[dev]"`, `pytest`, then installs oscal-cli. It validates the hand-written and the generated OSCAL, and checks that `validate.sh` rejects `tests/fixtures/invalid-catalog.json`.
- **`rebuild`:** reruns the three commands above and fails if `git diff` shows changes in `oscal/generated/` or `docs/results/`, or if those folders have untracked files. It then validates all OSCAL JSON.

## What's verified

- **Vendored inputs are unmodified:** every file in `data/upstream/` matches `SHA256SUMS` (`tests/test_upstream.py`).
- **Mapping validation:** malformed, unknown or duplicate rows are rejected, and the shipped rows are all `proposed` (`tests/test_mapping.py`). The same file also checks a few things about the shipped rationales, such as SR-007 addressing anti-rollback and SR-013 mapping AU-3 without AU-10.
- **Component definition** (`tests/test_component.py`):
  - The output is byte-identical across runs, has sorted keys and matches the committed file.
  - Its UUIDs follow the uuid5 scheme, and the catalog href is pinned to a release.
  - Each component holds only the requirements allocated to it, and the trace and verification links are present.
  - Draft marking follows the mapping.
  - The `last-modified` default handles shallow clones, uncommitted inputs, inputs in several repos and inputs outside git.
- **Assessment results** (`tests/test_results.py`):
  - The output equals the hand-written golden file except for the listed `INTENTIONAL_DIFFERENCES`, and it matches the committed file.
  - The satisfied/not-satisfied rule holds, including missing expected test cases and the failing fixture `tests/fixtures/ve07-summary-failing.json`.
  - A passed test case with a failed control run is rejected, and malformed summaries are clean CLI errors.
  - Draft marking follows the mapping.
- **Hand-written golden file** agrees with `summary.json` and the walkthrough's UUIDs (`tests/test_handwritten.py`).
- **Results page** (`tests/test_render.py`):
  - The page matches the committed file, and its links resolve.
  - The DRAFT banner appears exactly when it should.
  - Input values are escaped everywhere, and malformed inputs give errors rather than broken Markdown.
- **CLI wiring and `python -m uas_oscal`** (`tests/test_cli.py`).
- **`validate.sh` logic** (model detection, exit codes, `OSCAL_CLI`) is tested with a stub oscal-cli (`tests/test_validate_script.py`). Real schema validation happens only in CI.

Not tested or only documented:

- No test checks that mapped control IDs exist in the 800-53 catalog. `mapping.py` only checks their shape with a regex (`src/uas_oscal/mapping.py:21`), and oscal-cli does not resolve the catalog href.
- Nothing checks that the mapping is correct. The rationales are proposals for the owner, and the tests only confirm a few phrases.
- `scripts/install-oscal-cli.sh` has no test; CI exercises it.
- `pytest` never runs oscal-cli, so a local `pytest` pass says nothing about OSCAL schema validity.
- The vendored inputs are not checked against the live P2 repo, only against the recorded digests.

## Decisions and constraints

- **Outputs are deterministic and committed**, and CI fails if they are stale. UUIDs are uuid5 values in a fixed project namespace (`src/uas_oscal/component.py:37`), keys are sorted, and no timestamp comes from the clock (`docs/ve07-walkthrough.md`, "Deterministic UUIDs").
- **`last-modified` comes from git history**, not the clock. `verification.csv` is deliberately left out of that date because it belongs to the same pinned P1 snapshot as the other CSVs (`src/uas_oscal/component.py:347-351`).
- **Only the owner approves mappings.** Unapproved rows are still emitted, but marked DRAFT everywhere. Tooling must treat any status other than `approved` as unapproved (`mappings/controls.yaml` header).
- **The hand-written golden file is the spec** for `uas-oscal results`. The README and walkthrough say so, and `tests/test_results.py` enforces it.
- **`summary.json` is strict:** any unknown field, or a missing required one, is rejected with an error that names it (`src/uas_oscal/results.py:61-98`). Fields the generator knows but doesn't map are listed in the walkthrough.
- **Vendored inputs are byte-for-byte copies** with LF line endings, and `.gitattributes` keeps git from converting them (`data/upstream/PROVENANCE.md`).
- **Supply chain:** oscal-cli is checksum-verified before it is unpacked, Actions are SHA-pinned, the CI token is read-only (`permissions: contents: read`), and the 800-53 catalog URL is pinned to a release tag.
- **The assessment plan is a stub.** It exists so `import-ap` resolves. Because there is no system security plan yet, its `import-ssp` points to a back-matter note (`docs/ve07-walkthrough.md`).

## Open edges

- **Only VE-07 is supported** (`VERIFICATION_EVENTS`, `src/uas_oscal/results.py:51-58`). Other events need their own entry and evidence.
- **SR-010 is not assessed.** P1's verification table lists VE-07 as verifying SR-005 and SR-010 (`data/upstream/p1/verification.csv:8`), but SR-010 has no row in `mappings/controls.yaml`, so the results cover SR-005 only.
- **A code comment is stale.** The comment at `src/uas_oscal/results.py:48-50` says P1's verification table "is not vendored", but it now is (`data/upstream/p1/verification.csv`).
- **The whole mapping is still a draft.** Every row is `proposed` and `approved_by` is `null` (`mappings/controls.yaml`), so all outputs carry DRAFT marking.
- **There is no system security plan.** The assessment plan is a stub (`oscal/handwritten/ve07-assessment-plan.json`).
- **Evidence is one fixed run.** Results come from a single vendored `summary.json`. Nothing pulls new CI evidence from P2 automatically; a refresh is a manual re-vendor (`data/upstream/PROVENANCE.md`).
- **The README disagrees with itself on Java.** One section says oscal-cli needs "Java 11 or newer", while the Pins table says 17+ (`README.md:15`, `README.md:90`). The install script says Java 11+ (`scripts/install-oscal-cli.sh:11`).
- **Install-tree defaults.** The CLI's default paths resolve against the checkout the package is installed from, not the current directory (`REPO_ROOT`, `src/uas_oscal/mapping.py:16`), so pass explicit paths when running from another checkout.
