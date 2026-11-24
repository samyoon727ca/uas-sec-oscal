# Provenance of vendored upstream inputs

The files in this folder are byte-for-byte copies of files in the P2 repository. Do not edit them. To refresh them, copy the files again from a newer upstream commit, then update this file and `SHA256SUMS` in the same change. `tests/test_upstream.py` checks every file against `SHA256SUMS`.

| | |
|---|---|
| Source repository | `samyoon727ca/uas-sec-p2-verified-boot` (<https://github.com/samyoon727ca/uas-sec-p2-verified-boot>) |
| Source commit | `d23409a1be75b3ae3fd4211483ad049cc5b94864` (`main`, 2026-11-10, "Merge pull request #20 from samyoon727ca/p2/tools-hygiene") |
| Copied | 2026-11-20, with `git cat-file blob <commit>:<path>`; `p1/verification.csv` added 2026-11-24 from the same commit |

The task that requested these files (samyoon727ca/uas-sec-oscal#1) names the source as `Yoon-SSE/uas-sec-p2-verified-boot`. On 2026-11-20, cloning that URL returned "Repository not found". The files were taken from `samyoon727ca/uas-sec-p2-verified-boot`, and `git ls-remote` showed that its `main` pointed at the source commit above. `Yoon-SSE` is the name of the local folder that holds the P1 and P2 clones.

| Path here | Original path in the source repository | SHA-256 |
|---|---|---|
| `p1/requirements.csv` | `data/p1/requirements.csv` | `ec46c187915ba4618b4fe9ee595bb87ae20f4c3e068cb376b0d006e6fc84b248` |
| `p1/trace.csv` | `data/p1/trace.csv` | `4c3d04d631306da2300f22c609670b4a8f3b54631e692805b075b80013645a83` |
| `p1/verification.csv` | `data/p1/verification.csv` | `040272200b3f69965a8ac0de8a780df8ea4f1dfece9d4ed81ef2424cff7177cc` |
| `evidence/ve07-ci/20261013-0d3ca38/summary.json` | `evidence/ve07-ci/20261013-0d3ca38/summary.json` | `34d37ae64afffacef97fdbc24e5a1307d26c817a7a19c22904b2911b964e5129` |

## Notes

- **P1 snapshot.** P2's `data/p1/` is itself a pinned copy of P1. According to P2's `data/p1/pin.txt`, its CSVs are byte-for-byte copies of `data/` in `samyoon727ca/uas-sec-p1-architecture` at commit `e539aa638d3e44c1982341e927d974b4396e0576`. The three CSVs here also match P1's `data/requirements.csv`, `data/trace.csv` and `data/verification.csv` at that commit.
- **`trace.csv` location.** `trace.csv` is at the expected path, `data/p1/trace.csv`. It maps P1 threats to P1 requirements (`threat_id,req_id`). P2 also has `data/trace.csv`, a different file with columns `req_id,threat_id` that traces P2's child requirements (such as `SR-005.1`) to P1 threats. That file is not vendored here.
- **`verification.csv`.** P1's verification table, one row per verification event (`ve_id`), with the requirements it verifies in `req_ids` as a `; `-separated list (for example `VE-07` lists `SR-005; SR-010`). `uas-oscal component` reads `ve_id` and `req_ids` from it.
- **Evidence run.** The `summary.json` file records the `ve07-emu` CI run 38345035945 for commit `0d3ca389ee65ba4575c00aad9b5130c4c416c5e5`. In the source repository it was last changed by commit `331990ccb505ae6a8dab7a5da242654100a3bce1`. It is identical at the source commit above.
- **Line endings.** The files use LF line endings. `.gitattributes` marks `data/upstream/**` as `-text` so Git never converts them.
