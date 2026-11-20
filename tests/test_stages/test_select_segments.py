"""Selection integration: sources, behavior identity, real clocks and resume."""

import json

import numpy as np
import pandas as pd
import pytest

from pynpxpipe.core.config import (
    PipelineConfig,
    SortingConfig,
    TaskWindowConfig,
    load_pipeline_config,
)
from pynpxpipe.core.run_signature import input_signature, prepare_run
from pynpxpipe.core.segments import SegmentManifest
from pynpxpipe.core.session import RecordingSource, SessionManager, SubjectConfig
from pynpxpipe.io.spikeglx import SpikeGLXDiscovery
from pynpxpipe.stages.select_segments import SelectSegmentsStage


@pytest.fixture
def joint_session(tmp_path):
    sources = []
    for i, name in enumerate(("a", "b")):
        root = tmp_path / f"rec_{name}_g0"
        directory = root / f"rec_{name}_g0_imec0"
        directory.mkdir(parents=True)
        meta = {
            "imSampRate": 100,
            "nSavedChans": 2,
            "imProbeSN": "SN-1",
            "imProbeType": "NP1",
            "fileCreateTime": f"2026-11-17T10:0{2 * i}:00+00:00",
            "fileSizeBytes": 40000,
            "snsSaveChanSubset": "0:1",
            "~imroTbl": "same",
        }
        (directory / "rec.ap.meta").write_text("\n".join(f"{k}={v}" for k, v in meta.items()))
        (directory / "rec.ap.bin").write_bytes(np.zeros((10000, 2), dtype=np.int16).tobytes())
        (root / "rec.nidq.meta").write_text("niSampRate=100\nnSavedChans=2")
        (root / "rec.nidq.bin").write_bytes(np.zeros((10000, 2), dtype=np.int16).tobytes())
        bhv = tmp_path / f"{name}.bhv2"
        bhv.write_bytes(b"test")
        sources.append(
            RecordingSource(name, root, bhv, probes=SpikeGLXDiscovery(root).discover_probes())
        )
    subject = SubjectConfig("monkey", "test", "Macaca mulatta", "M", "P5Y", "10kg")
    session = SessionManager.create_from_recordings(
        sources,
        subject,
        tmp_path / "out",
        experiment="test",
        probe_plan={"imec0": "V4"},
        date="261117",
    )
    session.probes = sources[0].probes
    session.config = PipelineConfig(
        task_windows=TaskWindowConfig(
            enabled=True, max_idle_s=10, padding_before_s=2, padding_after_s=2
        )
    )
    for source in sources:
        directory = session.output_dir / "sources" / source.source_id / "04_sync"
        directory.mkdir(parents=True)
        (directory / "sync_tables.json").write_text(
            json.dumps({"probes": {"imec0": {"a": 1.0, "b": 0.0, "residual_ms": 0.01}}})
        )
        pd.DataFrame(
            {
                "trial_id": [1, 2],
                "condition_id": [1, 1],
                "start_time": [10.0, 60.0],
                "stop_time": [11.0, 61.0],
                "bhv_zero_nidq_s": [10.0, 60.0],
                "trial_error": [0, 4],
            }
        ).to_parquet(directory / "trial_intervals.parquet")
        pd.DataFrame(
            {
                "trial_id": [1],
                "condition_id": [1],
                "stim_index": [1],
                "trial_valid": [1.0],
                "onset_nidq_s": [10.0],
                "stim_onset_nidq_s": [10.5],
                "stim_onset_imec_s": ['{"imec0": 10.5}'],
                "onset_time_ms": [150.0],
                "offset_time_ms": [150.0],
            }
        ).to_parquet(directory / "behavior_events.parquet")
    return session


def test_selection_keeps_failed_trials_and_namespaces_sources(joint_session):
    SelectSegmentsStage(joint_session).run()
    manifest = SegmentManifest.load(joint_session.output_dir / "03_segments" / "segments.json")
    ap = manifest.for_probe("imec0")
    assert [(s.source_id, s.start_frame, s.stop_frame) for s in ap] == [
        ("a", 800, 1300),
        ("a", 5800, 6300),
        ("b", 800, 1300),
        ("b", 5800, 6300),
    ]
    assert [s.time(s.start_frame) for s in ap] == [8, 58, 128, 178]
    trials = pd.read_parquet(joint_session.output_dir / "04_sync" / "full_trials.parquet")
    assert trials.trial_key.tolist() == ["a:1", "a:2", "b:1", "b:2"]
    events = pd.read_parquet(joint_session.output_dir / "04_sync" / "behavior_events.parquet")
    assert json.loads(events.iloc[1].stim_onset_imec_s)["imec0"] == 130.5
    assert manifest.sources[1]["offset_method"] == "acquisition_wall_clock"
    before = manifest.signature
    SelectSegmentsStage(joint_session).run()
    assert (
        SegmentManifest.load(joint_session.output_dir / "03_segments" / "segments.json").signature
        == before
    )


def test_old_trial_anchor_algorithm_invalidates_cached_outputs(joint_session, monkeypatch):
    import pynpxpipe.core.run_signature as signatures

    cfg, sorting = joint_session.config, SortingConfig()
    with monkeypatch.context() as legacy:
        legacy.setattr(signatures, "_SIGNATURE_VERSION", 1, raising=False)
        old_signature = signatures.input_signature(joint_session, cfg, sorting)
    marker = joint_session.output_dir / "input_signature.json"
    marker.write_text(json.dumps({"signature": old_signature}), encoding="utf-8")
    cached = joint_session.output_dir / "checkpoints" / "synchronize.json"
    cached.parent.mkdir(exist_ok=True)
    cached.write_text(json.dumps({"status": "completed"}), encoding="utf-8")

    prepare_run(joint_session, cfg, sorting)

    assert not cached.exists()
    archives = list((joint_session.output_dir / ".invalidated").iterdir())
    assert len(archives) == 1
    assert (archives[0] / "checkpoints" / "synchronize.json").exists()
    assert (archives[0] / "sources" / "a" / "04_sync" / "trial_intervals.parquet").exists()
    assert json.loads(marker.read_text())["signature"] != old_signature
    assert all(source.bhv_file.exists() for source in joint_session.recordings)
    assert all(
        (source.session_dir / "rec.nidq.bin").exists() for source in joint_session.recordings
    )


def test_changed_metadata_or_order_rejected(joint_session):
    joint_session.recordings[1].probes[0].serial_number = "different"
    SelectSegmentsStage(joint_session).run()
    summary = json.loads((joint_session.output_dir / "03_segments" / "summary.json").read_text())
    assert summary["joint_sorting_compatible"] is False
    assert "serial_number" in summary["joint_sorting_error"]
    from pynpxpipe.stages.preprocess import PreprocessStage
    from pynpxpipe.stages.sort import SortStage

    for stage in (PreprocessStage(joint_session), SortStage(joint_session)):
        with pytest.raises(ValueError, match="serial_number"):
            stage.run()


def test_missing_identity_allows_preview_but_blocks_joint_processing(joint_session):
    from pynpxpipe.io.segment_recordings import validate_sources

    for source in joint_session.recordings:
        source.probes[0].serial_number = "unknown"
    SelectSegmentsStage(joint_session).run()
    summary = json.loads((joint_session.output_dir / "03_segments" / "summary.json").read_text())
    assert summary["n_sources"] == 2
    assert summary["joint_sorting_compatible"] is False
    assert "imDatPrb_sn" in summary["joint_sorting_error"]
    with pytest.raises(ValueError, match="imDatPrb_sn"):
        validate_sources(joint_session)


def test_source_persistence_yaml_and_legacy_defaults(joint_session, tmp_path):
    SessionManager.save(joint_session)
    restored = SessionManager.load(joint_session.output_dir)
    assert [s.source_id for s in restored.recordings] == ["a", "b"]
    assert restored.recordings[1].probes[0].ap_bin == joint_session.recordings[1].probes[0].ap_bin
    assert load_pipeline_config().task_windows.enabled is False
    config_path = tmp_path / "config.yaml"
    config_path.write_text("task_windows:\n  enabled: true\n  max_idle_s: 75\n")
    assert load_pipeline_config(config_path).task_windows.max_idle_s == 75


def test_config_change_archives_derived_results_and_preserves_originals(joint_session):
    cfg = joint_session.config
    prepare_run(joint_session, cfg, SortingConfig())
    stage_dir = joint_session.output_dir / "06_postprocessed"
    stage_dir.mkdir()
    (stage_dir / "cache.txt").write_text("stale")
    prepare_run(joint_session, cfg, SortingConfig())
    assert stage_dir.exists()
    cfg.task_windows.padding_before_s = 5
    prepare_run(joint_session, cfg, SortingConfig())
    assert not stage_dir.exists()
    assert list((joint_session.output_dir / ".invalidated").rglob("cache.txt"))
    assert all(
        source.bhv_file.exists() and source.session_dir.exists()
        for source in joint_session.recordings
    )


def test_nested_output_does_not_change_input_signature(joint_session):
    joint_session.output_dir = joint_session.recordings[0].session_dir / "output"
    before = input_signature(joint_session, joint_session.config, SortingConfig())
    generated = joint_session.output_dir / ".invalidated" / "old" / "sorter"
    generated.mkdir(parents=True)
    (generated / "recording.ap.bin").write_bytes(b"derived")
    assert input_signature(joint_session, joint_session.config, SortingConfig()) == before
    joint_session.recordings[0].probes[0].ap_meta.write_text("changed input")
    assert input_signature(joint_session, joint_session.config, SortingConfig()) != before


def test_mixed_behavior_protocols_are_rejected(joint_session):
    path = joint_session.output_dir / "sources" / "b" / "04_sync" / "behavior_events.parquet"
    events = pd.read_parquet(path)
    events["planned_event_id"] = "target-1"
    events.to_parquet(path)
    with pytest.raises(ValueError, match="same behavioral event protocol"):
        SelectSegmentsStage(joint_session).run()


@pytest.mark.parametrize("bombcell_and_merge", [False, True])
def test_joint_processing_through_real_analyzers_and_nwb(
    joint_session, monkeypatch, bombcell_and_merge
):
    """Run actual SI filters/analyzers and NWB; substitute only input/sorter IO."""
    from types import SimpleNamespace

    import spikeinterface.core as si
    from pynwb import NWBHDF5IO, validate

    from pynpxpipe.io.spikeglx import SpikeGLXLoader
    from pynpxpipe.stages.curate import CurateStage
    from pynpxpipe.stages.export import ExportStage
    from pynpxpipe.stages.merge import MergeStage
    from pynpxpipe.stages.postprocess import PostprocessStage
    from pynpxpipe.stages.preprocess import PreprocessStage
    from pynpxpipe.stages.sort import SortStage

    raw_by_path = {}
    rng = np.random.default_rng(42)
    fs = 10000 if bombcell_and_merge else 1000
    for source in joint_session.recordings:
        probe = source.probes[0]
        probe.sample_rate, probe.n_channels = fs, 8
        data = rng.normal(0, 30, (100 * fs, 8)).astype(np.int16)
        probe.ap_bin.write_bytes(data.tobytes())
        meta = SpikeGLXDiscovery.parse_meta(probe.ap_meta)
        meta.update(
            imSampRate=fs, nSavedChans=8, fileSizeBytes=data.nbytes, snsSaveChanSubset="0:7"
        )
        probe.ap_meta.write_text("\n".join(f"{k}={v}" for k, v in meta.items()))
        probe.target_area = "V4"
        rec = si.NumpyRecording(data, fs)
        rec.set_channel_locations(
            np.column_stack((np.tile([0.0, 20.0], 4), np.repeat(np.arange(4) * 20.0, 2)))
        )
        rec.set_channel_gains(np.ones(8))
        rec.set_channel_offsets(np.zeros(8))
        rec.set_property("inter_sample_shift", np.zeros(8))
        raw_by_path[probe.ap_bin] = rec
    monkeypatch.setattr(SpikeGLXLoader, "load_ap", lambda p, **k: raw_by_path[p.ap_bin])
    monkeypatch.setattr(
        SpikeGLXLoader,
        "load_nidq",
        lambda *a: si.NumpyRecording(np.zeros((10000, 2), dtype=np.int16), 100),
    )
    for module in ("preprocess", "curate", "postprocess"):
        monkeypatch.setattr(f"pynpxpipe.plots.{module}.emit_all", lambda **k: [])
    monkeypatch.setattr("pynpxpipe.plots.bombcell.emit_bombcell_plots", lambda **k: [])
    count = []

    def bad_channels(rec, **kwargs):
        count.append(1)
        return np.array([len(count) % 2]), np.array([])

    monkeypatch.setattr("pynpxpipe.stages.preprocess.spp.detect_bad_channels", bad_channels)
    cfg = joint_session.config
    cfg.resources.n_jobs = 1
    cfg.resources.chunk_duration = "1s"
    cfg.preprocess.bandpass.freq_min = 100
    cfg.preprocess.bandpass.freq_max = 400
    cfg.preprocess.motion_correction.method = None
    cfg.postprocess.eye_validation.enabled = False
    cfg.export.derivatives.enabled = False
    cfg.curation.use_bombcell = bombcell_and_merge
    cfg.merge.enabled = bombcell_and_merge
    cfg.curation.snr_min = -1
    cfg.curation.presence_ratio_min = 0
    cfg.curation.amplitude_cutoff_max = 1
    SelectSegmentsStage(joint_session).run()
    PreprocessStage(joint_session, cfg).run()
    preprocessed = si.load(joint_session.output_dir / "01_preprocessed" / "imec0.zarr")
    assert preprocessed.get_num_channels() == 6  # union of bad channels across all blocks
    assert preprocessed.get_num_samples() == 20 * fs
    calls = []

    def sorter(name, recording, **kwargs):
        calls.append(recording.get_num_segments())
        return si.NumpySorting.from_unit_dict(
            {7: np.arange(int(0.1 * fs), int(19.9 * fs), int(0.05 * fs))}, fs
        )

    monkeypatch.setattr("pynpxpipe.stages.sort.ss.run_sorter", sorter)
    sorting_config = SortingConfig()
    sorting_config.sorter.params.torch_device = "cpu"
    SortStage(joint_session, sorting_config).run()
    assert calls == [1]
    if bombcell_and_merge:
        MergeStage(joint_session).run()

        def reject_fallback(*args):
            raise AssertionError("Bombcell must handle independent analysis segments")

        monkeypatch.setattr(CurateStage, "_classify_manual", reject_fallback)
    CurateStage(joint_session).run()
    kept = si.load(joint_session.output_dir / "05_curated" / "imec0")
    if bombcell_and_merge:
        metrics = pd.read_csv(
            joint_session.output_dir / "05_curated" / "imec0" / "quality_metrics.csv"
        )
        assert {"drift_ptp", "rp_contamination", "amplitude_median", "firing_rate"} <= set(
            metrics.columns
        )
        # All four analysis segments contribute; discarded gaps do not dilute rate.
        merged = si.load(joint_session.output_dir / "03_merged" / "imec0")
        assert metrics.firing_rate.iloc[0] == pytest.approx(len(merged.to_spike_vector()) / 19.4)
    PostprocessStage(joint_session).run()
    parser = SimpleNamespace(get_dataset_tsv_path=lambda: None, get_analog_data=lambda channel: {})
    monkeypatch.setattr("pynpxpipe.io.segmented_nwb.BHV2Parser", lambda *a: parser)
    if not bombcell_and_merge:
        from pynpxpipe.core.errors import ExportError

        derivative_calls = []
        original_phase2 = ExportStage._export_phase2

        def interrupted_derivatives(stage, path, events):
            derivative_calls.append(1)
            if len(derivative_calls) == 1:
                raise RuntimeError("interrupted derivatives")
            original_phase2(stage, path, events)

        monkeypatch.setattr(ExportStage, "_export_phase2", interrupted_derivatives)
        with pytest.raises(ExportError, match="interrupted derivatives"):
            ExportStage(joint_session).run()
    ExportStage(joint_session).run()
    if not bombcell_and_merge:
        assert len(derivative_calls) == 2
    path = joint_session.output_dir / f"{joint_session.session_id.canonical()}.nwb"
    assert validate(path=path) == []
    with NWBHDF5IO(path, "r") as io:
        nf = io.read()
        assert (len(nf.units) if nf.units is not None else 0) == len(kept.unit_ids)
        if not bombcell_and_merge:
            assert len(nf.units) == 1
            assert len(nf.units["obs_intervals"][0]) == 4
            assert nf.units["spike_times"][0].max() > 180
        assert nf.trials["trial_key"][:].tolist() == ["a:1", "b:1"]
        assert len(nf.acquisition) == 8  # four AP plus four NIDQ blocks
    from pynpxpipe.pipelines.verify import EXIT_SELECTED_RAW_ONLY, verify_safe_to_delete

    verification = verify_safe_to_delete(joint_session.output_dir)
    assert not verification.safe
    assert verification.exit_code == EXIT_SELECTED_RAW_ONLY
