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
