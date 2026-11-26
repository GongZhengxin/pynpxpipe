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
                "trial_id": [1, 2, 3],
                "condition_id": [1, 1, 1],
                "start_time": [10.0, 60.0, 90.0],
                "stop_time": [11.0, 61.0, 91.0],
                "bhv_zero_nidq_s": [10.0, 60.0, 90.0],
                "trial_error": [0, 4, 4],
            }
        ).to_parquet(directory / "trial_intervals.parquet")
        pd.DataFrame(
            {
                "trial_id": [1, 2, 3],
                "condition_id": [1, 1, 1],
                "stim_index": [1, 0, 0],
                "trial_valid": [1.0, 0.0, np.nan],
                "onset_nidq_s": [10.0, 60.0, 90.0],
                "stim_onset_bhv_ms": [500.0, 500.0, np.nan],
                "stim_onset_nidq_s": [10.5, 60.5, np.nan],
                "stim_onset_imec_s": ['{"imec0": 10.5}', '{"imec0": 60.5}', '{"imec0": NaN}'],
                "onset_time_ms": [150.0] * 3,
                "offset_time_ms": [150.0] * 3,
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
    assert trials.n_presentations.tolist() == [1, 1, 1, 1]
    events = pd.read_parquet(joint_session.output_dir / "04_sync" / "behavior_events.parquet")
    assert events.trial_key.tolist() == trials.trial_key.tolist()
    assert json.loads(events.iloc[2].stim_onset_imec_s)["imec0"] == 130.5
    assert manifest.sources[1]["offset_method"] == "acquisition_wall_clock"
    before = manifest.signature
    SelectSegmentsStage(joint_session).run()
    assert (
        SegmentManifest.load(joint_session.output_dir / "03_segments" / "segments.json").signature
        == before
    )


def test_timeline_what_if_matches_formal_selection_on_each_clock(joint_session):
    from dataclasses import replace

    from pynpxpipe.ui.components.run_panel import RunPanel

    out = joint_session.output_dir
    sync = out / "sources" / "b" / "04_sync" / "sync_tables.json"
    sync.write_text(json.dumps({"probes": {"imec0": {"a": 1.02, "b": 0.15, "residual_ms": 0.1}}}))
    stage = SelectSegmentsStage(joint_session)
    stage.run()
    timeline = RunPanel._read_preview(out).timeline
    assert timeline.trials.trial_key.tolist() == ["a:1", "a:2", "b:1", "b:2"]
    # Each source's NIDQ clock starts afresh; AP and BHV are on experiment time.
    assert timeline.trials.start_time.iloc[2] == pytest.approx(120 + (10 - 0.15) / 1.02)
    assert [(s.start, s.duration) for s in timeline.sources] == [(0, 100), (120, 100)]
    original = (out / "03_segments" / "segments.json").read_bytes()
    cfg = replace(
        joint_session.config.task_windows, max_idle_s=49, padding_before_s=25, padding_after_s=80
    )
    candidate = timeline.select(cfg)
    assert len(candidate) == 2
    assert (out / "03_segments" / "segments.json").read_bytes() == original
    assert not (out / ".invalidated").exists()
    joint_session.config.task_windows = cfg
    stage._select()
    actual = SegmentManifest.load(out / "03_segments" / "segments.json").for_probe("imec0")
    assert candidate == actual


def test_empty_trials_split_padded_windows_and_empty_sources_contribute_no_frames(joint_session):
    from pynpxpipe.ui.components.run_panel import RunPanel

    out = joint_session.output_dir
    cfg = joint_session.config.task_windows
    cfg.max_idle_s = cfg.padding_before_s = cfg.padding_after_s = 180
    for sid in ("a", "b"):
        path = out / "sources" / sid / "04_sync" / "behavior_events.parquet"
        events = pd.read_parquet(path)
        if sid == "a":
            # No event rows at all for these trials, as for a fixation-only target task.
            events = events.iloc[:0].assign(planned_event_id=pd.Series(dtype="Int64"))
        else:
            interval_path = path.with_name("trial_intervals.parquet")
            intervals = pd.read_parquet(interval_path)
            intervals.loc[intervals.trial_id == 2, "stop_time"] = 61.003
            intervals.to_parquet(interval_path)
            # Trial 2 is empty. Trial 3 shows an image at BHV time 0 even though
            # fixation failed and the digital onset was unmatched.
            events["stim_onset_bhv_ms"] = [500.0, np.nan, 0.0]
            events["stim_onset_nidq_s"] = [10.5, np.nan, np.nan]
            events = pd.concat([events, events.iloc[[0]].assign(stim_onset_bhv_ms=700.0)])
        events.to_parquet(path, index=False)

    SelectSegmentsStage(joint_session).run()
    preview = RunPanel._read_preview(out)
    assert "planned_event_id" not in pd.read_parquet(out / "04_sync" / "behavior_events.parquet")
    assert preview.timeline.trials.trial_key.tolist() == ["b:1", "b:3"]
    assert preview.timeline.trials.n_presentations.tolist() == [2, 1]
    assert [s.id for s in preview.timeline.sources] == ["a", "b"]
    assert preview.timeline.select(cfg) == preview.timeline.saved
    assert [(s.source_id, s.start_frame, s.stop_frame) for s in preview.timeline.saved] == [
        ("b", 0, 6000),
        ("b", 6101, 10000),  # sample 6100 still falls inside the empty trial
    ]
    assert "空 trial：4 个" in preview.text
    # Don't let an all-empty input silently fall back to sorting the entire file.
    path = out / "sources" / "b" / "04_sync" / "behavior_events.parquet"
    pd.read_parquet(path).iloc[:0].to_parquet(path, index=False)
    with pytest.raises(ValueError, match="没有呈现刺激的 trial"):
        SelectSegmentsStage(joint_session)._select()


@pytest.mark.parametrize("entry", ["list", "url"])
def test_open_preview_from_fresh_ui_is_read_only(joint_session, monkeypatch, entry):
    from dataclasses import replace
    from unittest.mock import Mock

    import panel as pn

    from pynpxpipe.core.config import save_pipeline_config, save_sorting_config
    from pynpxpipe.pipelines.runner import PipelineRunner
    from pynpxpipe.ui.app import create_app

    out = joint_session.output_dir
    joint_session.config.export.repair_verify = "full"
    sort_cfg = SortingConfig()
    sort_cfg.import_cfg.paths = {"imec0": out / "first", "imec1": out / "second"}
    save_sorting_config(sort_cfg, out / "used_sorting.yaml")
    SelectSegmentsStage(joint_session).run()
    SessionManager.save(joint_session)
    save_pipeline_config(joint_session.config, out / "used_pipeline.yaml")
    (out / "input_signature.json").write_text('{"signature": "historical"}')

    def snapshot():
        return {
            p.relative_to(out): (p.stat().st_mtime_ns, p.read_bytes())
            for p in out.rglob("*")
            if p.is_file()
        }

    before = snapshot()
    runner = Mock(side_effect=AssertionError("restoring a session must not prepare a run"))
    monkeypatch.setattr(PipelineRunner, "__init__", runner)
    app = create_app()
    execute = app._pynpx_sections["execute"]
    app._pynpx_switch("execute")
    (heading,) = [p for p in execute.select(pn.pane.Markdown) if p.object == "### 任务时段时间轴"]
    (plot,) = execute.select(pn.pane.Bokeh)
    assert heading.visible and plot.object is None
    session_list = app._pynpx_session_list

    def reopen_from_list():
        # P1-2: the session list's "open existing directory" replaces both SessionLoaders.
        session_list.open_input.value = str(out)
        session_list.open_btn.clicks += 1

    if entry == "list":
        reopen_from_list()
    else:  # a refreshed page or shared link: ?view=session&dir=…
        app._pynpx_router.go("session", output_dir=str(out))
    assert app._pynpx_router.view == "session"
    assert plot.object.select_one({"name": "有刺激的 trial"}).data_source.data["trial"] == [
        "a:1",
        "a:2",
        "b:1",
        "b:2",
    ]
    assert app._pynpx_state.input_mode == "joint" and app._pynpx_state.run_status == "idle"
    (gap,) = [w for w in execute.select(pn.widgets.FloatInput) if w.name == "最大连续空闲 (s)"]
    gap.value = 60
    assert app._pynpx_state.pipeline_config == replace(
        joint_session.config, task_windows=replace(joint_session.config.task_windows, max_idle_s=60)
    )
    assert app._pynpx_state.sorting_config == sort_cfg
    assert before == snapshot()
    runner.assert_not_called()
    (out / "03_segments" / "summary.json").unlink()
    reopen_from_list()
    assert plot.object is None and heading.visible
    assert any(
        "缺少 `03_segments/summary.json`" in p.object for p in execute.select(pn.pane.Markdown)
    )


def test_saved_timeline_reacts_to_both_editors_and_drops_stale_alignment(joint_session):
    from unittest.mock import Mock

    from pynpxpipe.ui.components.pipeline_form import PipelineForm
    from pynpxpipe.ui.components.run_panel import RunPanel
    from pynpxpipe.ui.state import AppState

    SelectSegmentsStage(joint_session).run()
    state = AppState(
        input_mode="joint",
        recordings=[s.to_dict() for s in joint_session.recordings],
        output_dir=joint_session.output_dir,
    )
    form = PipelineForm(state)
    form.apply_pipeline(joint_session.config)
    controls = form.task_preview_controls()
    run = Mock(side_effect=AssertionError("tuning must never launch a pipeline"))
    panel = RunPanel(state, pipeline_fn=run, preview_fn=run, tuning_controls=controls)
    panel.load_saved_preview()
    view = panel.timeline
    assert view.layout.visible
    fig = view.plot.object
    raw, saved, trials = (
        fig.select_one({"name": name}).data_source.data
        for name in ("原始记录", "已保存", "有刺激的 trial")
    )
    assert raw["start"] == [0, 120] and raw["stop"] == [100, 220]
    assert list(trials["trial"]) == ["a:1", "a:2", "b:1", "b:2"]
    assert view.candidate.data["start"] == saved["start"] == [8, 58, 128, 178]
    fig.x_range.start, fig.x_range.end = 6, 67
    controls[0].value = 49
    assert form.task_max_idle.value == state.pipeline_config.task_windows.max_idle_s == 49
    assert view.candidate.data["start"] == [8, 128]
    assert view.candidate.data["stop"] == [63, 183]
    assert "110.0 s" in view.stats.object and "2.0%" in view.stats.object
    form.task_pre.value = 0
    assert controls[1].value == 0 and view.candidate.data["start"] == [10, 130]
    assert (fig.x_range.start, fig.x_range.end) == (6, 67)
    assert saved["start"] == [8, 58, 128, 178]
    assert panel.preview_table.object.start_s.tolist() == saved["start"]
    controls[0].value = 60
    panel.refresh_btn.clicks += 1
    assert "**60 s**" in view.stats.object and "空 trial：2 个" in view.stats.object
    state.recordings = list(reversed(state.recordings))
    assert not view.layout.visible and not panel.preview_table.visible and view.data is None
    assert "重新" in panel.preview_result.object
    run.assert_not_called()


def test_live_tuning_updates_only_the_latest_preview_on_its_browser_document(
    joint_session, monkeypatch
):
    from dataclasses import replace
    from unittest.mock import Mock, PropertyMock

    from bokeh.document import Document

    from pynpxpipe.ui.components.run_panel import RunPanel
    from pynpxpipe.ui.components.task_timeline import TaskTimeline

    SelectSegmentsStage(joint_session).run()
    cfg = joint_session.config.task_windows
    data = RunPanel._read_preview(joint_session.output_dir).timeline
    view = TaskTimeline()
    view.show(data, replace(cfg, max_idle_s=180))
    doc = Document()
    doc.add_root(view.plot.object)
    monkeypatch.setattr(type(doc), "session_context", PropertyMock(return_value=Mock()))
    callbacks = []
    monkeypatch.setattr(doc, "add_next_tick_callback", callbacks.append)
    view.update(replace(cfg, max_idle_s=60))
    view.update(replace(cfg, max_idle_s=10))
    assert len(callbacks) == 2 and "**180 s**" in view.stats.object
    # Even if an older callback arrives late it cannot overwrite the new choice.
    callbacks.pop()()
    callbacks.pop()()
    assert "**10 s**" in view.stats.object and len(view.candidate.data["start"]) == 4
    view.update(replace(cfg, max_idle_s=60))
    view.clear()
    callbacks.pop()()
    assert view.plot.object is None and view.stats.object == ""


@pytest.mark.parametrize("saved_header", [True, False])
def test_old_preview_uses_embedded_header_or_shows_saved_only(joint_session, saved_header):
    from pynpxpipe.ui.components.run_panel import RunPanel
    from pynpxpipe.ui.components.task_timeline import TaskTimeline

    for source in joint_session.recordings:
        if saved_header:
            meta = source.session_dir / "rec.nidq.meta"
            with meta.open("a") as f:
                f.write("\nfileSizeBytes=40000\n")
        # Recreate an old selection whose blue bars include even the last trial.
        path = (
            joint_session.output_dir
            / "sources"
            / source.source_id
            / "04_sync"
            / "behavior_events.parquet"
        )
        events = pd.read_parquet(path)
        events.loc[events.trial_id == 3, "stim_onset_bhv_ms"] = 500.0
        events.to_parquet(path)
    SelectSegmentsStage(joint_session).run()
    out = joint_session.output_dir
    summary = out / "03_segments" / "summary.json"
    info = json.loads(summary.read_text())
    del info["nidq_durations_s"]
    del info["n_empty_trials"]
    summary.write_text(json.dumps(info))
    path = out / "04_sync" / "behavior_events.parquet"
    events = pd.read_parquet(path)
    events.loc[(events.source_id == "a") & (events.trial_id == 3), "stim_onset_bhv_ms"] = np.nan
    events.to_parquet(path)
    chart = TaskTimeline()
    chart.show(RunPanel._read_preview(out).timeline, joint_session.config.task_windows)
    assert chart.layout.visible
    assert bool(chart.candidate.data["start"]) == saved_header
    assert ("缺少原始 NIDQ 时长" in chart.stats.object) != saved_header
    assert len(chart.plot.object.select_one({"name": "已保存"}).data_source.data["start"]) == 6
    assert chart.data.trials.trial_key.tolist() == ["a:1", "a:2", "b:1", "b:2", "b:3"]
    if saved_header:
        assert len(chart.candidate.data["start"]) == 5


@pytest.mark.parametrize("crop_enabled", [True, False])
def test_preview_checks_later_source_clock_before_sync(joint_session, monkeypatch, crop_enabled):
    from pynpxpipe.pipelines.runner import PipelineRunner
    from pynpxpipe.stages.discover import BHV2_MAGIC

    cfg = joint_session.config
    cfg.task_windows.enabled = crop_enabled
    for source in joint_session.recordings:
        source.bhv_file.write_bytes(BHV2_MAGIC)
    second_meta = joint_session.recordings[1].probes[0].ap_meta
    second_meta.write_text(second_meta.read_text().replace("+00:00", ""))
    stages = ["discover", "synchronize", "select_segments"]
    called = []
    run_stage = PipelineRunner.run_stage

    def track_stage(runner, name):
        called.append(name)
        if name == "discover":
            run_stage(runner, name)

    monkeypatch.setattr(PipelineRunner, "run_stage", track_stage)
    runner = PipelineRunner(joint_session, cfg, SortingConfig())
    with pytest.raises(ValueError) as caught:
        runner.run(stages=stages)
    assert called == ["discover"]
    assert f"Source b ({second_meta})" in str(caught.value)
    assert "采集时区 (IANA)" in str(caught.value)
    assert "Asia/Shanghai" in str(caught.value)
    failed = joint_session.output_dir / "checkpoints" / "select_segments.json"
    assert json.loads(failed.read_text())["status"] == "failed"

    called.clear()
    cfg.task_windows.recording_timezone = "Asia/Shanghai"
    PipelineRunner(joint_session, cfg, SortingConfig()).run(stages=stages)
    assert called == stages

    called.clear()
    cfg.task_windows.recording_timezone = None
    runner.run(stages=["synchronize"])
    assert called == ["synchronize"]
    second_meta.write_text(second_meta.read_text().replace("10:02:00", "10:02:00+08:00"))
    called.clear()
    PipelineRunner(joint_session, cfg, SortingConfig()).run(stages=stages)
    assert called == stages


@pytest.mark.parametrize("old_version", [1, 2])
def test_old_selection_algorithm_invalidates_cached_outputs(
    joint_session, monkeypatch, old_version
):
    import pynpxpipe.core.run_signature as signatures

    cfg, sorting = joint_session.config, SortingConfig()
    with monkeypatch.context() as legacy:
        legacy.setattr(signatures, "_SIGNATURE_VERSION", old_version)
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
    # Production cleanup retires the preprocessed store before segmented export.
    if not bombcell_and_merge:
        store = joint_session.output_dir / "01_preprocessed" / "imec0.zarr"
        store.rename(store.with_suffix(".retired"))
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
        assert nf.trials["trial_key"][:].tolist() == ["a:1", "a:2", "b:1", "b:2"]
        assert len(nf.acquisition) == 8  # four AP plus four NIDQ blocks
    from pynpxpipe.pipelines.verify import EXIT_SELECTED_RAW_ONLY, verify_safe_to_delete

    verification = verify_safe_to_delete(joint_session.output_dir)
    assert not verification.safe
    assert verification.exit_code == EXIT_SELECTED_RAW_ONLY


def test_export_only_recovery_checks_identity_without_invalidating(
    joint_session, monkeypatch, tmp_path
):
    import hashlib
    from types import SimpleNamespace

    from click.testing import CliRunner

    from pynpxpipe.cli.main import cli
    from pynpxpipe.core.checkpoint import CheckpointManager
    from pynpxpipe.core.config import save_pipeline_config, save_sorting_config

    s = joint_session
    root = s.output_dir
    sorting_cfg = SortingConfig()
    recorded_root = tmp_path / "old_acquisition_machine_vault"
    s.subject.image_vault_paths = [recorded_root]
    sig = input_signature(s, s.config, sorting_cfg)
    s.input_signature = sig
    SessionManager.save(s)
    assert SessionManager.load(root).subject.image_vault_paths == [recorded_root]
    saved = json.loads((root / "session.json").read_text())
    del saved["subject"]["image_vault_paths"]  # legacy UI output
    (root / "session.json").write_text(json.dumps(saved))
    save_pipeline_config(s.config, root / "used_pipeline.yaml")
    save_sorting_config(sorting_cfg, root / "used_sorting.yaml")
    (root / "input_signature.json").write_text(json.dumps({"signature": sig}))
    SelectSegmentsStage(s).run()
    cp = CheckpointManager(root)
    cp.mark_complete("postprocess", {"input_signature": sig})
    cp.mark_complete("postprocess", {"input_signature": sig, "n_units": 1}, "imec0")
    (root / "06_postprocessed/imec0/recording_info").mkdir(parents=True)

    vault = tmp_path / "packages"
    old = vault / "images.tsv"
    old.parent.mkdir()
    old.write_text("FileName\nwrong.png\n")
    pkg = vault / "original"
    pkg.mkdir()
    table = pkg / old.name
    table.write_text("FileName\ncorrect.png\n")
    manifest = pkg / "manifest.tsv"
    manifest.write_bytes(b"original")
    events_path = root / "04_sync/behavior_events.parquet"
    events = pd.read_parquet(events_path).assign(
        planned_event_id=1,
        stim_index=1,
        stimulus_table_sha256=hashlib.sha256(table.read_bytes()).hexdigest(),
        stimulus_manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
    )
    events.to_parquet(events_path)
    monkeypatch.setattr(
        "pynpxpipe.io.segmented_nwb.BHV2Parser",
        lambda _: SimpleNamespace(get_dataset_tsv_path=lambda: str(old)),
    )
    calls = []

    def export(stage):
        from pynpxpipe.io.segmented_nwb import resolve_source_stimuli

        names = resolve_source_stimuli(stage.session, events)
        assert names.stim_name.unique().tolist() == ["correct.png"]
        assert set(names.stimulus_key) == {"a:1", "b:1"}
        calls.append(stage.session.input_signature)

    monkeypatch.setattr("pynpxpipe.stages.export.ExportStage.run", export)
    args = [
        "resume-export",
        str(root),
        "--image-vault",
        str(vault),
        "--recorded-vault",
        str(recorded_root),
    ]
    runner = CliRunner()
    check = runner.invoke(cli, [*args, "--check-only"])
    assert check.exit_code == 0, check.output
    assert not calls
    check = runner.invoke(cli, args)
    assert check.exit_code == 0, check.output
    assert calls == [sig]
    manifest.write_bytes(b"different")
    check = runner.invoke(cli, [*args, "--check-only"])
    assert check.exit_code != 0 and "manifest SHA-256 mismatch" in check.output
    manifest.unlink()
    check = runner.invoke(cli, [*args, "--check-only"])
    assert check.exit_code != 0 and "manifest.tsv: missing" in check.output
    s.recordings[0].bhv_file.write_bytes(b"changed input")
    check = runner.invoke(cli, args)
    assert check.exit_code != 0 and "Inputs/config changed" in check.output
    assert calls == [sig] and not (root / ".invalidated").exists()


def test_task_window_page_loads_a_saved_preview(joint_session):
    """S11: the confirmation page reads what select_segments saved (no raw access)."""
    from pynpxpipe.ui.components.task_window_page import TaskWindowPage
    from pynpxpipe.ui.state import AppState

    SelectSegmentsStage(joint_session).run()
    state = AppState()
    state.pipeline_config = joint_session.config
    page = TaskWindowPage(state, apply_fn=print, confirm_fn=print, later_fn=print)
    page.load(joint_session.output_dir)
    assert not page.message.visible
    assert page.timeline.data is not None
    # Two joint sources × two presented trials each.
    assert "全部 4 个有刺激 trial 都在保留区内" in page.coverage.object


@pytest.fixture
def single_session(joint_session):
    """Single-source session whose sync tables live in the output's own 04_sync/."""
    session = joint_session
    source = session.recording_sources[0]
    session.recordings = [source]
    src_dir = session.output_dir / "sources" / source.source_id / "04_sync"
    sync_dir = session.output_dir / "04_sync"
    sync_dir.mkdir(parents=True, exist_ok=True)
    for name in ("sync_tables.json", "trial_intervals.parquet", "behavior_events.parquet"):
        (sync_dir / name).write_bytes((src_dir / name).read_bytes())
    events = pd.read_parquet(sync_dir / "behavior_events.parquet")
    events["attempt_id"] = [1, 2, 3]
    events.to_parquet(sync_dir / "behavior_events.parquet")
    return session


def _rerun_select(session):
    from pynpxpipe.core.checkpoint import CheckpointManager

    CheckpointManager(session.output_dir).clear("select_segments")
    SelectSegmentsStage(session).run()


def test_single_source_rerun_does_not_reuse_its_own_output(single_session):
    out = single_session.output_dir / "04_sync" / "behavior_events.parquet"
    SelectSegmentsStage(single_session).run()
    first = pd.read_parquet(out)

    _rerun_select(single_session)
    second = pd.read_parquet(out)

    pd.testing.assert_frame_equal(first, second)
    assert second.attempt_id.tolist() == ["a:1", "a:2"]
    assert second.source_stim_onset_imec_s.tolist() == ['{"imec0": 10.5}', '{"imec0": 60.5}']
    source_copy = single_session.output_dir / "04_sync" / "behavior_events_source.parquet"
    assert "source_stim_onset_imec_s" not in pd.read_parquet(source_copy).columns


def test_previously_namespaced_table_asks_to_rerun_synchronize(single_session):
    out = single_session.output_dir / "04_sync" / "behavior_events.parquet"
    events = pd.read_parquet(out)
    events["source_stim_onset_imec_s"] = events.stim_onset_imec_s
    events.to_parquet(out)

    with pytest.raises(ValueError, match="synchronize"):
        SelectSegmentsStage(single_session).run()
