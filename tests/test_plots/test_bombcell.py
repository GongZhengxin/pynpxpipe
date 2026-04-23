"""Tests for ``pynpxpipe.plots.bombcell.emit_bombcell_plots``.

Covers the three SI widget plots + fallback behaviour:
- Main path (labels_df + thresholds non-None): 3 PNGs saved.
- Fallback path (labels_df is None): only ``bombcell_unit_labels.png`` saved.
- Widget raises: fail-open — other widgets still run.
- matplotlib missing: returns ``[]`` and logs, no raise.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from pynpxpipe.plots.bombcell import emit_bombcell_plots


@pytest.fixture
def unit_ids() -> list[int]:
    return [0, 1, 2, 3]


@pytest.fixture
def unittype_map(unit_ids: list[int]) -> dict[int, str]:
    return {0: "SUA", 1: "MUA", 2: "NOISE", 3: "NON-SOMA"}


@pytest.fixture
def labels_df(unit_ids: list[int]) -> pd.DataFrame:
    return pd.DataFrame(
        {"bombcell_label": ["good", "mua", "noise", "non_soma"]},
        index=unit_ids,
    )


@pytest.fixture
def thresholds() -> dict:
    return {"noise": {}, "mua": {}, "non-somatic": {}}


@pytest.fixture
def mock_analyzer(unit_ids: list[int]) -> MagicMock:
    a = MagicMock()
    a.sorting.get_unit_ids.return_value = list(unit_ids)
    return a


def _stub_widget(saved_paths: list[Path]):
    """Return a side_effect callable that pretends to render a figure.

    Each call appends a dummy PNG to the output dir so the test can assert
    on file existence without importing matplotlib/SI widget internals.
    """

    def _call(*args, **kwargs):
        # Widget callers decide filename outside; nothing to do here.
        return MagicMock()

    return _call


class TestMainPath:
    def test_three_plots_saved(
        self,
        tmp_path: Path,
        mock_analyzer: MagicMock,
        unittype_map: dict,
        labels_df: pd.DataFrame,
        thresholds: dict,
    ) -> None:
        """All 3 PNGs exist when labels_df + thresholds are provided."""
        with (
            patch("pynpxpipe.plots.bombcell.sw.plot_unit_labels") as m_labels,
            patch("pynpxpipe.plots.bombcell.sw.plot_metric_histograms") as m_hist,
            patch("pynpxpipe.plots.bombcell.sw.plot_bombcell_labels_upset") as m_upset,
        ):
            # Make the widget mocks return something with a figure attribute
            # that savefig() can operate on (real matplotlib Figure would work,
            # but we patch savefig too for isolation).
            m_labels.return_value.figure = MagicMock()
            m_hist.return_value.figure = MagicMock()
            m_upset.return_value.figure = MagicMock()

            with patch(
                "pynpxpipe.plots.bombcell.savefig",
                side_effect=lambda fig, path, title=None: Path(path),
            ):
                paths = emit_bombcell_plots(
                    analyzer=mock_analyzer,
                    unittype_map=unittype_map,
                    labels_df=labels_df,
                    thresholds=thresholds,
                    probe_id="imec0",
                    output_dir=tmp_path,
                )

        assert m_labels.called
        assert m_hist.called
        assert m_upset.called
        names = {p.name for p in paths}
        assert "bombcell_unit_labels.png" in names
        assert "bombcell_metric_histograms.png" in names
        assert "bombcell_labels_upset.png" in names


class TestFallbackPath:
    def test_only_unit_labels_when_no_labels_df(
        self,
        tmp_path: Path,
        mock_analyzer: MagicMock,
        unittype_map: dict,
    ) -> None:
        """labels_df=None → only plot_unit_labels runs (uses manual labels)."""
        with (
            patch("pynpxpipe.plots.bombcell.sw.plot_unit_labels") as m_labels,
            patch("pynpxpipe.plots.bombcell.sw.plot_metric_histograms") as m_hist,
            patch("pynpxpipe.plots.bombcell.sw.plot_bombcell_labels_upset") as m_upset,
            patch(
                "pynpxpipe.plots.bombcell.savefig",
                side_effect=lambda fig, path, title=None: Path(path),
            ),
        ):
            m_labels.return_value.figure = MagicMock()

            paths = emit_bombcell_plots(
                analyzer=mock_analyzer,
                unittype_map=unittype_map,
                labels_df=None,
                thresholds=None,
                probe_id="imec0",
                output_dir=tmp_path,
            )

        assert m_labels.called
        assert not m_hist.called
        assert not m_upset.called
        names = {p.name for p in paths}
        assert names == {"bombcell_unit_labels.png"}


class TestFailOpen:
    def test_single_widget_failure_does_not_abort_others(
        self,
        tmp_path: Path,
        mock_analyzer: MagicMock,
        unittype_map: dict,
        labels_df: pd.DataFrame,
        thresholds: dict,
    ) -> None:
        """plot_metric_histograms raising does not prevent the other two plots."""
        with (
            patch("pynpxpipe.plots.bombcell.sw.plot_unit_labels") as m_labels,
            patch(
                "pynpxpipe.plots.bombcell.sw.plot_metric_histograms",
                side_effect=RuntimeError("boom"),
            ),
            patch("pynpxpipe.plots.bombcell.sw.plot_bombcell_labels_upset") as m_upset,
            patch(
                "pynpxpipe.plots.bombcell.savefig",
                side_effect=lambda fig, path, title=None: Path(path),
            ),
        ):
            m_labels.return_value.figure = MagicMock()
            m_upset.return_value.figure = MagicMock()

            paths = emit_bombcell_plots(
                analyzer=mock_analyzer,
                unittype_map=unittype_map,
                labels_df=labels_df,
                thresholds=thresholds,
                probe_id="imec0",
                output_dir=tmp_path,
            )

        names = {p.name for p in paths}
        assert "bombcell_unit_labels.png" in names
        assert "bombcell_labels_upset.png" in names
        assert "bombcell_metric_histograms.png" not in names


class TestMatplotlibMissing:
    def test_returns_empty_when_mpl_flag_false(
        self,
        tmp_path: Path,
        mock_analyzer: MagicMock,
        unittype_map: dict,
        labels_df: pd.DataFrame,
        thresholds: dict,
    ) -> None:
        """With _HAS_MPL=False the module returns [] and does not raise."""
        with patch("pynpxpipe.plots.bombcell._HAS_MPL", False):
            paths = emit_bombcell_plots(
                analyzer=mock_analyzer,
                unittype_map=unittype_map,
                labels_df=labels_df,
                thresholds=thresholds,
                probe_id="imec0",
                output_dir=tmp_path,
            )
        assert paths == []
