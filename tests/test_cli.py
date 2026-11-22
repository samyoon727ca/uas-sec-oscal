import subprocess
import sys

import pytest

from uas_oscal.cli import SUBCOMMANDS, main


def test_help_lists_subcommands(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for name in ("component", "results", "render"):
        assert name in out


@pytest.mark.parametrize("name", sorted(set(SUBCOMMANDS) - {"component"}))
def test_stub_subcommands_exit_not_implemented(name, capsys):
    assert main([name]) == 1
    assert "not implemented" in capsys.readouterr().err


def test_subcommand_is_required():
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2


def test_module_entry_point():
    proc = subprocess.run(
        [sys.executable, "-m", "uas_oscal", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "component" in proc.stdout
