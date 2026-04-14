"""ui/components/sorting_form.py — SortingConfig parameter form."""

from __future__ import annotations

import panel as pn

from pynpxpipe.core.config import (
    AnalyzerConfig,
    ImportConfig,
    RandomSpikesConfig,
    SorterConfig,
    SorterParams,
    SortingConfig,
    WaveformConfig,
)
from pynpxpipe.ui.state import AppState

_SORTER_OPTIONS = ["kilosort4"]
_MODE_OPTIONS = ["local", "import"]

_DEFAULT_PARAMS = SorterParams()
_DEFAULT_ANALYZER = AnalyzerConfig()
_DEFAULT_SORTING = SortingConfig(
    sorter=SorterConfig(name="kilosort4", params=_DEFAULT_PARAMS),
    import_cfg=ImportConfig(format="kilosort4", paths={}),
    analyzer=_DEFAULT_ANALYZER,
)


class SortingForm:
    """Widgets for configuring the spike sorter."""

    def __init__(self, state: AppState) -> None:
        self._state = state

        self.sorter_select = pn.widgets.Select(
            name="Sorter",
            options=_SORTER_OPTIONS,
            value="kilosort4",
            description="Spike sorting algorithm. Kilosort4 is the default GPU-accelerated sorter.",
        )
        self.mode_select = pn.widgets.Select(
            name="Mode",
            options=_MODE_OPTIONS,
            value="local",
            description="'local' = run sorting here. 'import' = load external sorting results from a path.",
        )
        self.nblocks_input = pn.widgets.IntInput(
            name="nblocks",
            value=_DEFAULT_PARAMS.nblocks,
            start=0,
            description="KS4 internal drift correction blocks. Default 0 (mutually exclusive with preprocess DREDge — keep 0 unless DREDge is disabled). Set to 1 (rigid) or 5/15 (non-rigid) only when preprocess motion correction is OFF.",
        )
        self.th_learned_input = pn.widgets.FloatInput(
            name="Th_learned",
            value=_DEFAULT_PARAMS.Th_learned,
            step=0.5,
            description="Learned template detection threshold. Lower = more spikes detected (more noise). Default 7.0 is conservative.",
        )
        self.do_car_checkbox = pn.widgets.Checkbox(
            name="do_CAR (disable when preprocessing already applied CMR)",
            value=_DEFAULT_PARAMS.do_CAR,
        )
        self.batch_size_input = pn.widgets.TextInput(
            name="batch_size",
            value=str(_DEFAULT_PARAMS.batch_size),
            description="Samples per GPU batch. 'auto' = estimate from free VRAM. Reduce if GPU OOM. Typical: 30000-60000.",
        )
        self.n_jobs_input = pn.widgets.IntInput(
            name="n_jobs",
            value=_DEFAULT_PARAMS.n_jobs,
            start=1,
            description="Internal KS4 parallelism. Usually 1 for GPU sorting (GPU is the bottleneck, not CPU).",
        )
        self.torch_device_select = pn.widgets.Select(
            name="Device",
            options=["auto", "cuda", "cpu"],
            value=_DEFAULT_PARAMS.torch_device,
            description="PyTorch device. 'cuda' = GPU (required for fast sorting). 'cpu' = CPU only (very slow). 'auto' = use CUDA if available.",
        )
        self.import_path_input = pn.widgets.TextInput(
            name="Import Path",
            placeholder="/path/to/kilosort_output",
            visible=False,
            description="Path to external sorting output directory (only used in 'import' mode).",
        )

        # ── Analyzer: Random Spikes ──
        self.analyzer_max_spikes_input = pn.widgets.IntInput(
            name="Max Spikes Per Unit",
            value=_DEFAULT_ANALYZER.random_spikes.max_spikes_per_unit,
            start=1,
            description="Max spikes sampled per unit for SortingAnalyzer. Lower = faster postprocess, less accurate templates.",
        )
        self.analyzer_random_method_select = pn.widgets.Select(
            name="Random Spikes Method",
            options=["uniform", "all", "smart"],
            value=_DEFAULT_ANALYZER.random_spikes.method,
            description="'uniform' = random sample. 'all' = use every spike (slow). 'smart' = stratified by firing rate.",
        )

        # ── Analyzer: Waveforms ──
        self.analyzer_ms_before_input = pn.widgets.FloatInput(
            name="Waveform ms_before",
            value=_DEFAULT_ANALYZER.waveforms.ms_before,
            start=0.0,
            step=0.1,
            description="Pre-spike window (ms) for waveform extraction. Typical 1.0 ms.",
        )
        self.analyzer_ms_after_input = pn.widgets.FloatInput(
            name="Waveform ms_after",
            value=_DEFAULT_ANALYZER.waveforms.ms_after,
            start=0.0,
            step=0.1,
            description="Post-spike window (ms) for waveform extraction. Typical 2.0 ms.",
        )

        # ── Analyzer: Template / Similarity ──
        self.analyzer_template_operators_input = pn.widgets.MultiChoice(
            name="Template Operators",
            options=["average", "std", "median"],
            value=list(_DEFAULT_ANALYZER.template_operators),
            description="Operators for template computation. 'average' is the conventional template; 'std' gives per-sample variability.",
        )
        self.analyzer_unit_locations_select = pn.widgets.Select(
            name="Unit Locations Method",
            options=["monopolar_triangulation", "center_of_mass", "grid_convolution"],
            value=_DEFAULT_ANALYZER.unit_locations_method,
            description="Spatial localization algorithm for unit positions. monopolar_triangulation is most accurate for Neuropixels.",
        )
        self.analyzer_template_similarity_select = pn.widgets.Select(
            name="Template Similarity Method",
            options=["cosine_similarity", "l1", "l2"],
            value=_DEFAULT_ANALYZER.template_similarity_method,
            description="Metric for cross-unit template similarity. cosine_similarity is the SpikeInterface default.",
        )

        for widget in (
            self.sorter_select,
            self.mode_select,
            self.nblocks_input,
            self.th_learned_input,
            self.do_car_checkbox,
            self.batch_size_input,
            self.n_jobs_input,
            self.torch_device_select,
            self.import_path_input,
            self.analyzer_max_spikes_input,
            self.analyzer_random_method_select,
            self.analyzer_ms_before_input,
            self.analyzer_ms_after_input,
            self.analyzer_template_operators_input,
            self.analyzer_unit_locations_select,
            self.analyzer_template_similarity_select,
        ):
            widget.param.watch(self._rebuild_config, "value")

        self.mode_select.param.watch(self._on_mode_change, "value")

        # Initialize state
        self._rebuild_config()

    # ── Internal ──

    def _on_mode_change(self, event) -> None:
        self.import_path_input.visible = event.new == "import"

    def _rebuild_config(self, event=None) -> None:
        batch_raw = self.batch_size_input.value
        try:
            batch_size = int(batch_raw)
        except (ValueError, TypeError):
            batch_size = batch_raw or "auto"

        self._state.sorting_config = SortingConfig(
            mode=self.mode_select.value,
            sorter=SorterConfig(
                name=self.sorter_select.value,
                params=SorterParams(
                    nblocks=self.nblocks_input.value,
                    Th_learned=self.th_learned_input.value,
                    do_CAR=self.do_car_checkbox.value,
                    batch_size=batch_size,
                    n_jobs=self.n_jobs_input.value,
                    torch_device=self.torch_device_select.value,
                ),
            ),
            import_cfg=ImportConfig(
                format=self.sorter_select.value,
                paths={"0": self.import_path_input.value} if self.import_path_input.value else {},
            ),
            analyzer=AnalyzerConfig(
                random_spikes=RandomSpikesConfig(
                    max_spikes_per_unit=self.analyzer_max_spikes_input.value,
                    method=self.analyzer_random_method_select.value,
                ),
                waveforms=WaveformConfig(
                    ms_before=self.analyzer_ms_before_input.value,
                    ms_after=self.analyzer_ms_after_input.value,
                ),
                template_operators=list(self.analyzer_template_operators_input.value),
                unit_locations_method=self.analyzer_unit_locations_select.value,
                template_similarity_method=self.analyzer_template_similarity_select.value,
            ),
        )

    # ── Layout ──

    def panel(self) -> pn.viewable.Viewable:
        return pn.Column(
            pn.pane.Markdown("### Sorting Configuration"),
            self.sorter_select,
            self.mode_select,
            self.import_path_input,
            pn.Card(
                self.nblocks_input,
                self.th_learned_input,
                self.do_car_checkbox,
                self.batch_size_input,
                self.n_jobs_input,
                self.torch_device_select,
                title="Sorter Parameters",
                collapsed=False,
            ),
            pn.Card(
                self.analyzer_max_spikes_input,
                self.analyzer_random_method_select,
                self.analyzer_ms_before_input,
                self.analyzer_ms_after_input,
                self.analyzer_template_operators_input,
                self.analyzer_unit_locations_select,
                self.analyzer_template_similarity_select,
                title="Analyzer (Postprocess SortingAnalyzer)",
                collapsed=True,
            ),
        )
