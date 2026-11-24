"""The vendored upstream inputs must match the digests recorded in SHA256SUMS."""

import hashlib
from pathlib import Path

import pytest

UPSTREAM = Path(__file__).resolve().parent.parent / "data" / "upstream"


def _entries():
    for line in (UPSTREAM / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        if line.strip():
            digest, path = line.split(maxsplit=1)
            yield digest, path


ENTRIES = list(_entries())


def test_sha256sums_lists_the_vendored_inputs():
    assert sorted(path for _, path in ENTRIES) == [
        "evidence/ve07-ci/20261013-0d3ca38/summary.json",
        "p1/requirements.csv",
        "p1/trace.csv",
        "p1/verification.csv",
    ]


@pytest.mark.parametrize(("digest", "path"), ENTRIES, ids=[p for _, p in ENTRIES])
def test_upstream_file_unmodified(digest, path):
    data = (UPSTREAM / path).read_bytes()
    assert hashlib.sha256(data).hexdigest() == digest
