"""Harness contract: the motion advisor resolves a coherent strategy end-to-end.

Exercises the real ``_max_recording_duration_s`` (parsing ``fileTimeSecs`` from a
real ``.ap.meta``) + the real ``recommend_motion_strategy`` math, then asserts the
runner applies a coherent outcome: either DREDge at a resolved ``bin_s``, or the
nblocks fallback with DREDge disabled. Must stay < 3s.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from pynpxpipe.core.config import (
    MotionCorrectionConfig,
    ParallelConfig,
    PipelineConfig,
    PreprocessConfig,
    ResourcesConfig,
    SorterConfig,
    SorterParams,
    SortingConfig,
)
from pynpxpipe.core.session import ProbeInfo, SessionManager, SubjectConfig
from pynpxpipe.pipelines.runner import PipelineRunner


def _subject() -> SubjectConfig:
    return SubjectConfig(
        subject_id="Mon",
        description="d",
        species="Macaca mulatta",
        sex="M",
        age="P3Y",
        weight="10kg",
    )


def test_long_recording_resolves_coherently(tmp_path: Path) -> None:
    # Real .ap.meta carrying fileTimeSecs (5.2h) for _max_recording_duration_s.
    meta = tmp_path / "rec_t0.imec0.ap.meta"
    meta.write_text(
        "imSampRate=30000.0\nfileTimeSecs=18720.0\nnSavedChans=385\n",
        encoding="utf-8",
    )
    session_dir = tmp_path / "session_g0"
    session_dir.mkdir()
    bhv = tmp_path / "s.bhv2"
    bhv.write_bytes(b"\x00" * 30)
    session = SessionManager.create(
        session_dir,
        bhv,
        _subject(),
        tmp_path / "out",
        experiment="nsd1w",
        probe_plan={"imec0": "V4"},
        date="240101",
    )
    session.probes = [
        ProbeInfo(
            probe_id="imec0",
            ap_bin=tmp_path / "rec_t0.imec0.ap.bin",
            ap_meta=meta,
            lf_bin=None,
            lf_meta=None,
            sample_rate=30000.0,
            n_channels=384,
            serial_number="SN",
            probe_type="NP1010",
            target_area="V4",
        )
    ]

    pipeline_config = PipelineConfig(
        resources=ResourcesConfig(n_jobs=4, chunk_duration="1s"),
        parallel=ParallelConfig(max_workers=1),
        preprocess=PreprocessConfig(
            motion_correction=MotionCorrectionConfig(
                method="dredge", auto_strategy=True, n_windows=10
            )
        ),
    )
    sorting_config = SortingConfig(
        sorter=SorterConfig(params=SorterParams(batch_size=60000, nblocks=0))
    )
    runner = PipelineRunner(session, pipeline_config, sorting_config)

    vm = MagicMock()
    vm.available = 40 * 1024**3  # tight enough to push bin_s above the floor
    with patch("pynpxpipe.pipelines.runner.psutil.virtual_memory", return_value=vm):
        runner._resolve_motion_strategy()

    mc = runner.pipeline_config.preprocess.motion_correction
    nblocks = runner.sorting_config.sorter.params.nblocks
    if mc.method == "dredge":
        # DREDge kept → bin_s resolved (possibly raised above the floor), sort untouched.
        assert mc.bin_s >= 1.0
        assert nblocks == 0
    else:
        # Fallback → DREDge disabled and sort drift handled by nblocks.
        assert mc.method is None
        assert nblocks == mc.fallback_nblocks
