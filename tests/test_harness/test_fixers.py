# tests/test_harness/test_fixers.py
from pathlib import Path

import pytest
import yaml

from pynpxpipe.harness.fixers import Fixer


@pytest.fixture
def sorting_yaml(tmp_path: Path) -> Path:
    cfg = {"mode": "local", "sorter": {"params": {"torch_device": "cuda", "batch_size": 60000}}}
    p = tmp_path / "sorting.yaml"
    p.write_text(yaml.dump(cfg), encoding="utf-8")
    return p


def test_fix_torch_device_cuda_to_auto(sorting_yaml: Path) -> None:
    fixer = Fixer()
    fix_record = fixer.fix_torch_device(sorting_yaml, current="cuda", target="auto")
    content = yaml.safe_load(sorting_yaml.read_text(encoding="utf-8"))
    assert content["sorter"]["params"]["torch_device"] == "auto"
    assert fix_record["tier"] == "GREEN"
    assert fix_record["before"] == "cuda"
    assert fix_record["after"] == "auto"


def test_fix_batch_size(sorting_yaml: Path) -> None:
    fixer = Fixer()
    fix_record = fixer.fix_batch_size(sorting_yaml, current=60000, target=40000)
    content = yaml.safe_load(sorting_yaml.read_text(encoding="utf-8"))
    assert content["sorter"]["params"]["batch_size"] == 40000
    assert fix_record["tier"] == "GREEN"
    assert fix_record["before"] == 60000
    assert fix_record["after"] == 40000


def test_record_yellow_fix(tmp_path: Path) -> None:
    fixer = Fixer()
    record = fixer.record_yellow_fix(
        description="Add amplitude_cutoff to curate metrics",
        file_path=tmp_path / "curate.py",
        diff="--- a/curate.py\n+++ b/curate.py\n@@ -1 +1 @@\n-old\n+new",
        rationale="amplitude_cutoff_max defined in config but never computed",
    )
    assert record["tier"] == "YELLOW"
    assert record["target"] == "source"
    assert "diff" in record
    assert record["reversible"] is True
