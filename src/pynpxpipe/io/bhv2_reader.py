"""Pure-Python BHV2 binary format reader.

Reads MonkeyLogic BHV2 files directly without requiring MATLAB Engine.
The format is a custom MATLAB serialization (not HDF5).

Binary format summary (little-endian throughout):

  Each variable:
    uint64  name_length
    char[]  variable_name
    uint64  type_length
    char[]  type_string
    uint64  ndim
    uint64[ndim]  size_array
    <type-specific payload>

  File layout:
    [IndexPosition variable]  ← double scalar: byte offset of FileIndex
    [FileInfo variable]        ← struct{machinefmt, encoding}
    [Trial1, Trial2, ...MLConfig, ...]
    [FileIndex variable]       ← cell[N,3]: names / start_bytes / end_bytes

References:
  docs/specs/bhv2_binary_format.md
  docs/specs/bhv2_matlab_analysis.md
"""

from __future__ import annotations

import math
import struct
from pathlib import Path
from typing import IO, Any

import numpy as np

# BHV2 magic: first 21 bytes of every valid BHV2 file
# (uint64 LE = 13)  +  b'IndexPosition'
BHV2_MAGIC: bytes = b"\x0d\x00\x00\x00\x00\x00\x00\x00IndexPosition"

# MATLAB type string → numpy dtype (little-endian)
_DTYPE_MAP: dict[str, np.dtype] = {
    "double": np.dtype("<f8"),
    "single": np.dtype("<f4"),
    "uint8": np.dtype("<u1"),
    "uint16": np.dtype("<u2"),
    "uint32": np.dtype("<u4"),
    "uint64": np.dtype("<u8"),
    "int8": np.dtype("<i1"),
    "int16": np.dtype("<i2"),
    "int32": np.dtype("<i4"),
    "int64": np.dtype("<i8"),
    "logical": np.dtype("bool"),
}


class BHV2Reader:
    """Pure-Python BHV2 binary format reader.

    Opens the file, reads FileIndex for fast random-access, then exposes
    ``read(var_name)`` and ``list_variables()``.  Supports context manager.

    Args:
        bhv_file: Path to the ``.bhv2`` file.

    Raises:
        FileNotFoundError: File does not exist.
        IOError: File is not a valid BHV2 file, or header is corrupt.
    """

    def __init__(self, bhv_file: Path) -> None:
        self._path = Path(bhv_file)
        if not self._path.exists():
            raise FileNotFoundError(f"BHV2 file not found: {self._path}")
        self._fh: IO[bytes] = self._path.open("rb")
        self._index: dict[str, tuple[int, int]] = {}
        self._encoding: str = "windows-1252"
        try:
            self._init()
        except OSError:
            self._fh.close()
            raise
        except Exception as exc:
            self._fh.close()
            raise OSError(f"Failed to parse BHV2 header in {self._path}: {exc}") from exc

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_variables(self) -> list[str]:
        """Return all variable names present in the file.

        Returns:
            List of variable name strings in FileIndex order.
        """
        return list(self._index.keys())

    def read(self, var_name: str) -> Any:
        """Read a variable by name and return a Python-native value.

        Type mapping:

        * Numeric scalar (1-element) → ``float``, ``int``, or ``bool``
        * Numeric array → ``np.ndarray``
        * ``char`` → ``str``
        * ``struct`` (1×1) → ``dict``
        * ``struct`` array → ``list[dict]``
        * ``cell`` → ``list``
        * ``containers.Map`` → ``dict``

        Args:
            var_name: Variable name as it appears in the BHV2 file.

        Returns:
            Deserialized variable value.

        Raises:
            KeyError: Variable not found in the file.
        """
        if var_name not in self._index:
            available = list(self._index.keys())[:5]
            raise KeyError(
                f"Variable '{var_name}' not found in BHV2 file (first 5 available: {available})"
            )
        start, _end = self._index[var_name]
        self._fh.seek(start)
        _name, value = self._read_variable()
        return value

    def close(self) -> None:
        """Close the underlying file handle."""
        if self._fh and not self._fh.closed:
            self._fh.close()

    def __enter__(self) -> BHV2Reader:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Initialisation helpers
    # ------------------------------------------------------------------

    def _init(self) -> None:
        """Verify magic, read FileInfo encoding, build FileIndex."""
        header = self._fh.read(21)
        if len(header) < 21 or header != BHV2_MAGIC:
            raise OSError(f"Not a valid BHV2 file: {self._path}")

        # Re-read IndexPosition from byte 0 to get FileIndex offset
        self._fh.seek(0)
        ip_name, ip_value = self._read_variable()
        if ip_name != "IndexPosition":
            raise OSError(f"Expected 'IndexPosition' as first variable, got '{ip_name}'")
        file_index_offset = int(ip_value)

        # Read FileInfo (second variable) to determine char encoding
        try:
            fi_name, fi_value = self._read_variable()
            if fi_name == "FileInfo" and isinstance(fi_value, dict):
                enc = fi_value.get("encoding", "")
                if enc and isinstance(enc, str):
                    self._encoding = enc.strip()
        except Exception:
            pass  # Old files may lack FileInfo; fall back to windows-1252

        # Build variable index from FileIndex cell
        self._fh.seek(file_index_offset)
        fi_start = file_index_offset
        self._build_index()
        fi_end = self._fh.tell()
        # FileIndex is not self-referencing in the index — add it explicitly
        if "FileIndex" not in self._index:
            self._index["FileIndex"] = (fi_start, fi_end)

    def _build_index(self) -> None:
        """Read FileIndex cell[N,3] and build name → (start, end) mapping.

        FileIndex is a cell array of shape [N, 3] stored in Fortran
        (column-major) order:
          elements 0..N-1    → variable names  (col 0)
          elements N..2N-1   → start offsets   (col 1)
          elements 2N..3N-1  → end offsets     (col 2)
        Offsets are stored as IEEE 754 doubles.
        """
        # Read FileIndex variable header manually to get shape
        name_len = self._read_uint64()
        self._fh.read(name_len)  # skip "FileIndex" name
        type_len = self._read_uint64()
        self._fh.read(type_len)  # skip "cell"
        ndim = self._read_uint64()
        sizes = [self._read_uint64() for _ in range(ndim)]
        n_vars = sizes[0]  # [N, 3] → N variables
        total = int(math.prod(sizes))  # N * 3

        # Read all cell elements (each is a full variable with name + body)
        elements: list[Any] = []
        for _ in range(total):
            _, val = self._read_variable()
            elements.append(val)

        # Fortran order: col 0 = names [0..N-1], col 1 = starts [N..2N-1],
        #                col 2 = ends [2N..3N-1]
        names = [str(elements[i]) for i in range(n_vars)]
        starts = [int(elements[n_vars + i]) for i in range(n_vars)]
        ends = [int(elements[2 * n_vars + i]) for i in range(n_vars)]
        self._index = dict(zip(names, zip(starts, ends, strict=True), strict=True))

    # ------------------------------------------------------------------
    # Binary reading primitives
    # ------------------------------------------------------------------

    def _read_uint64(self) -> int:
        return struct.unpack("<Q", self._fh.read(8))[0]

    def _read_variable(self) -> tuple[str, Any]:
        """Read one complete BHV2 variable from the current file position.

        Returns:
            ``(name, value)`` where name may be empty for cell elements.

        Raises:
            OSError: If the file position is at EOF or the data is corrupt.
        """
        raw_name_len = self._fh.read(8)
        if len(raw_name_len) < 8:
            raise OSError("Unexpected end-of-file reading variable name length")
        name_len = struct.unpack("<Q", raw_name_len)[0]
        if name_len > 65536:
            raise OSError(f"Implausible name_len={name_len} at offset {self._fh.tell()}")
        name = self._fh.read(name_len).decode("ascii")

        type_len = self._read_uint64()
        type_str = self._fh.read(type_len).decode("ascii")

        ndim = self._read_uint64()
        sizes = list(struct.unpack(f"<{ndim}Q", self._fh.read(8 * ndim))) if ndim > 0 else []

        value = self._read_typed(type_str, sizes)
        return name, value

    def _read_typed(self, type_str: str, sizes: list[int]) -> Any:
        """Dispatch to the appropriate deserializer for *type_str*."""
        # ml* prefix → MonkeyLogic custom class, treat as struct
        if type_str.startswith("ml"):
            type_str = "struct"

        n = int(math.prod(sizes)) if sizes else 1

        if type_str in _DTYPE_MAP:
            return self._read_numeric(type_str, sizes, n)
        if type_str == "char":
            return self._read_char(n)
        if type_str == "struct":
            return self._read_struct(sizes, n)
        if type_str == "cell":
            return self._read_cell(n)
        if type_str == "containers.Map":
            return self._read_map()
        if type_str == "function_handle":
            # Stored as a single char sub-variable (the function name string)
            _, func_name = self._read_variable()
            return func_name
        # Unknown type: surface clearly rather than silently corrupt state
        raise ValueError(
            f"Unsupported BHV2 type '{type_str}' — "
            f"add handling or report this file to the developers"
        )

    def _read_numeric(self, type_str: str, sizes: list[int], n: int) -> Any:
        """Read a numeric or logical array from the file.

        Args:
            type_str: MATLAB type string (e.g. ``"double"``, ``"uint16"``).
            sizes:    MATLAB size vector (Fortran order).
            n:        Total element count ``== prod(sizes)``.

        Returns:
            Python scalar (if n==1) or ``np.ndarray`` shaped to *sizes*
            in Fortran order.
        """
        dtype = _DTYPE_MAP[type_str]
        raw = self._fh.read(n * dtype.itemsize)
        arr = np.frombuffer(raw, dtype=dtype)
        if n == 1:
            # Scalar: return native Python type
            val = arr[0]
            if type_str == "logical":
                return bool(val)
            if type_str in (
                "uint8",
                "uint16",
                "uint32",
                "uint64",
                "int8",
                "int16",
                "int32",
                "int64",
            ):
                return int(val)
            return float(val)
        # Multi-element: reshape with Fortran (column-major) order
        return arr.reshape(sizes, order="F")

    def _read_char(self, n: int) -> str:
        """Read *n* characters and decode as a string.

        MATLAB ``fread(fid, n, 'char*1=>char')`` reads *n* characters,
        which for UTF-8 may consume more than *n* bytes (up to 4 per char).
        For single-byte encodings (windows-1252, latin-1, ascii) the byte
        count equals the character count.

        Uses ``self._encoding`` (set from FileInfo, defaults to
        ``windows-1252``).
        """
        if n == 0:
            return ""

        enc_norm = self._encoding.lower().replace("-", "").replace("_", "")

        if enc_norm in ("utf8",):
            # UTF-8: read up to 4*n bytes (UTF-8 max), decode, take n chars,
            # then seek the file pointer to the exact end of those chars.
            start = self._fh.tell()
            buf = self._fh.read(n * 4)
            text = buf.decode("utf-8", errors="replace")
            result = text[:n]
            consumed = len(result.encode("utf-8"))
            self._fh.seek(start + consumed)
            return result

        # Single-byte encodings: 1 byte == 1 character
        raw = self._fh.read(n)
        return raw.decode(self._encoding, errors="replace")

    def _read_struct(self, sizes: list[int], n: int) -> Any:
        """Read a MATLAB struct (possibly an array of structs).

        Layout:
          uint64  nfield
          for each element × each field: full sub-variable

        Args:
            sizes: MATLAB size vector.
            n:     ``prod(sizes)`` — number of struct elements.

        Returns:
            Single ``dict`` when ``n == 1``; ``list[dict]`` otherwise.
        """
        nfield = self._read_uint64()
        elements: list[dict[str, Any]] = []
        for _ in range(n):
            elem: dict[str, Any] = {}
            for _ in range(nfield):
                fname, fval = self._read_variable()
                elem[fname] = fval
            elements.append(elem)
        return elements[0] if n == 1 else elements

    def _read_cell(self, n: int) -> list:
        """Read *n* cell elements, each a complete sub-variable.

        Returns a flat list in the order elements appear in the file
        (Fortran column-major for multi-dimensional cells).

        Args:
            n: Total element count (``prod(sizes)``).

        Returns:
            Flat list of deserialized values.
        """
        elements: list[Any] = []
        for _ in range(n):
            _, val = self._read_variable()
            elements.append(val)
        return elements

    def _read_map(self) -> dict:
        """Read a ``containers.Map``: two consecutive sub-variables (keys, values).

        Returns:
            ``dict`` mapping each key to the corresponding value.
        """
        _, keys = self._read_variable()
        _, values = self._read_variable()
        if isinstance(keys, list) and isinstance(values, list):
            return dict(zip(keys, values, strict=True))
        return {}
