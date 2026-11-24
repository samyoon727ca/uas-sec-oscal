# VE-07 assessment results: walkthrough

`oscal/handwritten/ve07-assessment-results.json` is a hand-written OSCAL 1.1.2 assessment-results document for one P2 CI run: the VE-07 evidence summary in `data/upstream/evidence/ve07-ci/20261013-0d3ca38/summary.json`. It is the golden reference for the `uas-oscal results` generator. The generator must reproduce the file from `summary.json`, and this page is its spec. Its output, `oscal/generated/ve07-assessment-results.json`, differs from the golden file only in the ways listed in `INTENTIONAL_DIFFERENCES` in `tests/test_results.py`. For example, it has a finding for every control that `mappings/controls.yaml` maps to SR-005, and it carries draft marking while the mapping is unapproved.

`oscal/handwritten/ve07-assessment-plan.json` is a minimal assessment-plan stub. The results document's `import-ap` points to it, so the href resolves to a real file. oscal-cli 1.0.3 does not follow `import-ap` when it validates, so the stub is not needed for validation itself. The project has no system security plan yet, so the stub's `import-ssp` points to a back-matter resource that says so and links to the P1 requirements.

Validate both files with:

```sh
bash scripts/validate.sh oscal/handwritten/*.json
```

## What the document asserts

- **Run.** GitHub Actions workflow `ve07-emu`, run 38345035945, attempt 1, was triggered by `push` on `refs/heads/p2/tc05-unseal`. It ran the harness `tests/ve07/boot_cases.py` against commit `0d3ca389ee65ba4575c00aad9b5130c4c416c5e5` (`0d3ca38`). Its timestamp is 2026-10-13T04:15:29Z.
- **Evidence.** The run's `summary.json`, vendored from `samyoon727ca/uas-sec-p2-verified-boot` with SHA-256 `34d37ae6…5e5129`, and the run's page on GitHub Actions.
- **Observations.** There is one observation per VE-07 test case: TC-01, TC-03, TC-04, TC-05 and TC-10. Each one is `passed`. Each observation lists the runs that `summary.json` records for that test case, including the control runs for TC-04 (for example TC-04e-control). Every run has `ok: true`.
- **Requirement and control.** Requirement SR-005 says "The CC shall boot only boot-chain components signed with the project boot key, verified from a hardware root of trust." It is assessed against NIST SP 800-53 control `si-7` (Software, Firmware, and Information Integrity).
- **Outcome.** The finding "SR-005 against SI-7" has status `satisfied`, because the run reports `passed: true` and every test case is `passed`. The finding cites all five observations.

## Field mapping: summary.json → OSCAL

Paths on the left are JSON paths in `summary.json`. Paths on the right are relative to `assessment-results` in the results document. `result` is `results[0]`. `obs` is one entry of `result.observations`. `finding` is any one entry of `result.findings`: there is one finding per control that `mappings/controls.yaml` maps to SR-005. Props marked *(uas)* use the namespace `https://github.com/samyoon727ca/uas-sec-oscal/ns/oscal`.

| summary.json | OSCAL | Notes |
|---|---|---|
| `event` (`VE-07`) | `result.props[verification-event]` *(uas)*; titles of the document, the result and each observation; finding `description`; UUID names | |
| `harness` | `result.description` | |
| `environment.run_id` | `result.props[ci-run-id]` *(uas)*; `result.title`; `result.description`; observation and finding descriptions; UUID names | |
| `environment.run_attempt` | `result.props[ci-run-attempt]` *(uas)*; `result.description`; observation descriptions; UUID names | |
| `environment.run_url` | `obs.relevant-evidence[1].href` | |
| `environment.workflow` | `result.props[ci-workflow]` *(uas)*; `result.title`; `result.description`; `obs.relevant-evidence[1].description` | |
| `environment.event` | `result.description` | The trigger, such as `push`. Not the same as the top-level `event`. |
| `environment.ref` | `result.props[git-ref]` *(uas)*; `result.description` | |
| `git.commit` | `result.props[git-commit]` *(uas)*; `obs.props[git-commit]` *(uas)*; descriptions of the result, each observation, `obs.relevant-evidence[0]` and the finding; first 7 characters in `metadata.title` and `result.title` | `environment.sha` holds the same value. |
| `date_utc` | `result.start`; `obs.collected`; `metadata.last-modified` (results and plan stub) | `summary.json` has only one timestamp, so `result.end` is left out. `last-modified` uses the run time rather than the editing time so that the output is deterministic. |
| `passed` | `finding.target.status.state` (with `test_cases`); `finding.description` | See [Finding status](#finding-status). |
| `test_cases` (keys) | one `obs` per key, in file order; `obs.props[test-case]` *(uas)*; `obs.title`; `finding.description` | |
| `test_cases.<TC>` (values) | `obs.props[test-outcome]` *(uas)*; `obs.title`; `obs.description`; `finding.target.status.state` | One of `passed`, `failed`, `skipped` or `error`; any other value is an error. A test case recorded as `passed` must have `ok: true` on all its runs, control runs included, or the summary is rejected. |
| `runs[]` where `tc` is `<TC>` | one bullet per run in that test case's `obs.description`: `- <id> (<role>): <title>. ok: <ok>` | If `control_for` is set, `<role>` is written as `control for <control_for>`. Run `id`s must be unique; a repeated `id` is an error. |

Values that do not come from `summary.json`:

| OSCAL | Value | Source |
|---|---|---|
| `obs.relevant-evidence[0].href` | `../../data/upstream/evidence/ve07-ci/20261013-0d3ca38/summary.json` | Path of the input file, relative to the output file |
| SHA-256 in `obs.relevant-evidence[0].description` | `34d37ae6…5e5129` | `data/upstream/SHA256SUMS` (the SHA-256 of the input file) |
| `finding.props[requirement-id]` *(uas)*; requirement text in `finding.description` | `SR-005` and its `statement` | `data/upstream/p1/requirements.csv` |
| `result.reviewed-controls…control-id`; `finding.target.target-id` | each control mapped to SR-005 (`si-7`, `si-7.9`, `si-7.15`); `<control>_obj` (such as `si-7_obj`) | `mappings/controls.yaml`. The generator emits one finding per mapped control. The hand-written golden file has only the pilot's SR-005 → SI-7 finding (issue #2); `INTENTIONAL_DIFFERENCES` in `tests/test_results.py` lists how the generated file differs from it. `si-7_obj` is the id of SI-7's assessment objective in the SP 800-53 rev. 5 OSCAL catalog. Control ids are lowercase, as in the catalog. |
| `finding.target.type` | `objective-id` | Constant |
| `obs.methods`; `obs.types` | `["TEST"]`; `["control-objective"]` | Constants. VE-07 is an automated test. |
| `import-ap.href` | `ve07-assessment-plan.json` | The plan stub next to the results file |
| `metadata.version`; `metadata.oscal-version` | `1.0.0`; `1.1.2` | Constants. `1.1.2` is the OSCAL version pinned in the README. |

These `summary.json` fields are not mapped: `environment.kind`, `environment.runner_image`, `git.cc_or_tests_modified`, `host`, `host_packages`, `toolchain`, `pins`, `public_keys_sha256_der`, `artifacts_sha256`, `notes`, `pcr_prediction`, `provisioning`, and the per-run detail in `runs[]` (`checks`, `log`, `log_sha256`, `seconds` and so on). They stay available through the `summary.json` evidence link.

## Finding status

`finding.target.status.state` is `satisfied` only when `passed` is `true`, `test_cases` has every test case VE-07 expects (TC-01, TC-03, TC-04, TC-05 and TC-10, listed in `VERIFICATION_EVENTS` in `src/uas_oscal/results.py`), and every value in `test_cases` is `passed`. Otherwise it is `not-satisfied`, and the finding description names any expected test case that is missing. In this run, `passed` is `true` and all five test cases are `passed`, so the state is `satisfied`.

## Deterministic UUIDs

Every UUID is a version-5 UUID computed from a fixed project namespace:

```python
import uuid

NS = uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/samyoon727ca/uas-sec-oscal")
# NS == fbf96b6c-1b0d-5a82-be27-d8f66045bb16
```

The name is built from `event`, `environment.run_id` and `environment.run_attempt` (`RUN` below is `VE-07/38345035945/1`):

| Object | uuid5 name | UUID |
|---|---|---|
| assessment-results document | `assessment-results/RUN` | `ef1a7bb0-8b8b-51e1-a64c-51ba26bb0cf3` |
| `result` | `result/RUN` | `0c567bd4-c554-56fc-a919-322bff3b63c1` |
| observation for test case `<TC>` | `observation/RUN/<TC>`, for example `observation/VE-07/38345035945/1/TC-01` | TC-01: `39e153e7-135d-53bb-9fcb-59018575a501` |
| finding | `finding/RUN/SR-005/si-7` | `2f56c1d6-d499-5be0-b2b5-789c6971a895` |
| assessment-plan stub | `assessment-plan/VE-07` | `72792f9b-6cfc-5047-9bec-ef541b978535` |
| plan stub's SSP placeholder resource | `assessment-plan/VE-07/import-ssp` | `202a8f19-b629-5aca-bfdf-071fa093c95a` |
