# tests/test_harness/test_classifier.py
from pynpxpipe.harness.classifier import Classifier


def test_classify_cuda_oom() -> None:
    exc = RuntimeError("CUDA out of memory. Tried to allocate 2.50 GiB")
    result = Classifier.classify(exc, traceback_str="Traceback (most recent call last):\n...")
    assert result.error_class == "cuda_oom"
    assert result.fix_tier == "GREEN"
    assert result.auto_fixable is True
    assert "batch_size" in result.suggestion.lower()


def test_classify_cuda_unavailable() -> None:
    exc = RuntimeError("CUDA is not available on this machine")
    result = Classifier.classify(exc, traceback_str="")
    assert result.error_class == "cuda_unavailable"
    assert result.fix_tier == "GREEN"
    assert result.auto_fixable is True


def test_classify_sorter_not_found() -> None:
    exc = ImportError("No module named 'kilosort'")
    result = Classifier.classify(exc, traceback_str="")
    assert result.error_class == "sorter_not_found"
    assert result.fix_tier == "RED"
    assert result.auto_fixable is False


def test_classify_unknown_error() -> None:
    exc = ValueError("Something unexpected happened")
    result = Classifier.classify(exc, traceback_str="")
    assert result.error_class == "unknown"
    assert result.fix_tier == "RED"
    assert result.auto_fixable is False


def test_classify_zero_units_detection() -> None:
    result = Classifier.classify_zero_units(
        stage="curate",
        n_total=47,
        per_threshold={"isi": 42, "presence_ratio": 3, "snr": 45},
        bottleneck="presence_ratio_min=0.9",
    )
    assert result.error_class == "zero_units_after_curation"
    assert result.fix_tier == "RED"
    assert "presence_ratio_min" in result.suggestion


def test_classify_amplitude_cutoff_not_computed() -> None:
    result = Classifier.classify_amplitude_cutoff_missing()
    assert result.error_class == "amplitude_cutoff_not_computed"
    assert result.fix_tier == "YELLOW"
    assert result.auto_fixable is True


# ── ui_redesign §8.6: structured suggestions ──


def _sorting(batch_size):
    import dataclasses

    from pynpxpipe.core.config import SortingConfig

    base = SortingConfig()
    params = dataclasses.replace(base.sorter.params, batch_size=batch_size)
    return dataclasses.replace(base, sorter=dataclasses.replace(base.sorter, params=params))


def test_classification_has_structured_fields_by_default() -> None:
    from pynpxpipe.harness.classifier import Classifier

    result = Classifier.classify(RuntimeError("boom"), "")
    assert result.suggested_changes == () and result.probe_id is None


def test_cuda_oom_suggests_two_thirds_batch_size() -> None:
    from pynpxpipe.core.config import PipelineConfig
    from pynpxpipe.harness.classifier import Classifier

    result = Classifier.classify(RuntimeError("CUDA out of memory"), "")
    changes = Classifier.suggest_changes(
        result, PipelineConfig(), _sorting(60000), min_batch_size=10000
    )
    assert changes == (("sorter.params.batch_size", 40000),)


def test_cuda_oom_batch_size_has_floor_and_needs_a_number() -> None:
    from pynpxpipe.core.config import PipelineConfig
    from pynpxpipe.harness.classifier import Classifier

    result = Classifier.classify(RuntimeError("CUDA out of memory"), "")
    assert Classifier.suggest_changes(
        result, PipelineConfig(), _sorting(12000), min_batch_size=10000
    ) == (("sorter.params.batch_size", 10000),)
    assert (
        Classifier.suggest_changes(result, PipelineConfig(), _sorting(10000), min_batch_size=10000)
        == ()
    )
    assert (
        Classifier.suggest_changes(result, PipelineConfig(), _sorting("auto"), min_batch_size=10000)
        == ()
    )


def test_motion_memory_error_suggests_doubling_bin_s() -> None:
    from pynpxpipe.core.config import PipelineConfig, SortingConfig
    from pynpxpipe.harness.classifier import Classifier

    result = Classifier.classify(
        MemoryError("Unable to allocate 12.0 GiB for an array"),
        'File "spikeinterface/sortingcomponents/motion/dredge.py"',
    )
    assert result.error_class == "motion_oom"
    cfg = PipelineConfig()
    changes = Classifier.suggest_changes(result, cfg, SortingConfig(), min_batch_size=10000)
    assert changes == (
        ("preprocess.motion_correction.bin_s", cfg.preprocess.motion_correction.bin_s * 2),
    )


def test_unknown_error_has_no_structured_change() -> None:
    from pynpxpipe.core.config import PipelineConfig, SortingConfig
    from pynpxpipe.harness.classifier import Classifier

    result = Classifier.classify(ValueError("weird"), "")
    assert (
        Classifier.suggest_changes(result, PipelineConfig(), SortingConfig(), min_batch_size=1)
        == ()
    )
