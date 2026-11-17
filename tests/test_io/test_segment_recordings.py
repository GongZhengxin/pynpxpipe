"""Real SpikeInterface slicing/splitting contracts against the locked version."""

import numpy as np
import pytest
import spikeinterface.core as si

from pynpxpipe.core.segments import Segment, SegmentManifest
from pynpxpipe.io.segment_recordings import (
    AcquisitionRateRecording,
    analysis_recording,
    check_channel_compatibility,
    split_analysis_sorting,
)


def test_joint_sorting_split_preserves_units_frames_and_isi_boundaries(tmp_path):
    manifest = SegmentManifest(
        [
            Segment("a", "imec0", 1000, 2000, 0, 1000, 1, 0),
            Segment("b", "imec0", 4000, 5000, 1000, 1000, 1.001, 10),
        ],
        join_guard_s=0.1,
    )
    rec = si.NumpyRecording(np.arange(4000, dtype=np.int16).reshape(2000, 2), 1000)
    sorting = si.NumpySorting.from_unit_dict(
        {7: np.array([100, 899, 950, 1050, 1100, 1999]), 9: np.array([800, 1200])}, 1000
    )
    split = split_analysis_sorting(sorting, manifest, "imec0", rec)
    split = split.save(folder=tmp_path / "sorting")
    np.testing.assert_array_equal(split.unit_ids, [7, 9])
    np.testing.assert_array_equal(split.get_unit_spike_train(7, segment_index=0), [100, 899])
    np.testing.assert_array_equal(split.get_unit_spike_train(7, segment_index=1), [0, 899])
    np.testing.assert_allclose(
        manifest.unit_times(split, "imec0", 7), [1.1, 1.899, 14.1041, 15.003999]
    )
    analyzed = analysis_recording(rec, manifest, "imec0")
    assert analyzed.get_num_segments() == 2
    assert sum(analyzed.get_num_samples(i) for i in range(2)) == 1800
    np.testing.assert_array_equal(
        analyzed.get_traces(segment_index=1), rec.get_traces(start_frame=1100, end_frame=2000)
    )
    # An ISI computation must not manufacture a 1 ms interval at the join.
    assert all(np.diff(split.get_unit_spike_train(7, segment_index=i)).min() > 1 for i in range(2))


def test_restoring_nominal_clock_never_resamples_raw_values():
    data = np.arange(60, dtype=np.int16).reshape(20, 3)
    rec = AcquisitionRateRecording(si.NumpyRecording(data, 999.7), 1000)
    assert rec.get_sampling_frequency() == 1000
    np.testing.assert_array_equal(
        rec.get_traces(start_frame=2, end_frame=7, channel_ids=[1]), data[2:7, 1:2]
    )


def test_changed_channel_order_rejected():
    a = si.NumpyRecording(np.zeros((20, 2)), 1000, channel_ids=[1, 2])
    b = si.NumpyRecording(np.zeros((20, 2)), 1000, channel_ids=[2, 1])
    with pytest.raises(ValueError, match="get_channel_ids"):
        check_channel_compatibility(a, b)
