"""Stage validator registry."""

from pynpxpipe.harness.validators.curate_validator import CurateValidator
from pynpxpipe.harness.validators.discover_validator import DiscoverValidator
from pynpxpipe.harness.validators.export_validator import ExportValidator
from pynpxpipe.harness.validators.postprocess_validator import PostprocessValidator
from pynpxpipe.harness.validators.preprocess_validator import PreprocessValidator
from pynpxpipe.harness.validators.sort_validator import SortValidator
from pynpxpipe.harness.validators.sync_validator import SyncValidator

VALIDATORS = {
    "discover": DiscoverValidator(),
    "preprocess": PreprocessValidator(),
    "sort": SortValidator(),
    "synchronize": SyncValidator(),
    "curate": CurateValidator(),
    "postprocess": PostprocessValidator(),
    "export": ExportValidator(),
}
