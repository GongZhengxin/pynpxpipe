"""plots — Nature-style diagnostic figure package.

Applies the Nature rc-params on import so every submodule's first figure
already inherits the correct fonts and sizes. Subpackages:

- ``plots.style``        — rcParams, Okabe-Ito palette, figure_size, savefig
- ``plots.sync``         — Synchronize-stage diagnostic plots
- ``plots.curate``       — Curate-stage quality-metric & Bombcell plots
- ``plots.postprocess``  — Postprocess-stage unit summary plots
- ``plots.preprocess``   — Preprocess-stage traces & bad-channel plots

Every subpackage guards its matplotlib import so that simply importing
``pynpxpipe.plots`` in a core environment (no ``[plots]`` extra) does not
raise — you only need matplotlib when you actually call ``emit_all``.
"""

from __future__ import annotations

try:
    from pynpxpipe.plots.style import (
        PALETTE,
        UNITTYPE_COLORS,
        apply_nature_style,
        figure_size,
        savefig,
    )

    apply_nature_style()

    __all__ = [
        "PALETTE",
        "UNITTYPE_COLORS",
        "apply_nature_style",
        "figure_size",
        "savefig",
    ]
except ImportError:
    # matplotlib not installed — plots subpackage degrades gracefully.
    __all__ = []
