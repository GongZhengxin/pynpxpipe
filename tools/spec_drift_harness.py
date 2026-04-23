"""Spec-code drift detection harness.

Compares YAML manifests (what specs claim) against AST-extracted code metadata
(what code actually does). Reports mismatches as FAIL/WARN.

Usage::

    python tools/spec_drift_harness.py check              # check all stages
    python tools/spec_drift_harness.py check --stage X    # check one stage
    python tools/spec_drift_harness.py diff --stage X     # show detailed diff
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
MANIFESTS_DIR = ROOT / "spec_manifests"
SRC_DIR = ROOT / "src"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    """Single comparison finding."""

    category: str  # config_keys, methods, checkpoint, imports, errors, outputs
    severity: str  # FAIL, WARN, INFO
    finding_type: str  # MISSING_IN_CODE, MISSING_IN_MANIFEST, VALUE_MISMATCH
    detail: str

    def __str__(self) -> str:
        return f"  {self.severity:4s} [{self.category}] {self.finding_type}: {self.detail}"


@dataclass
class StageReport:
    """Full report for one stage."""

    stage_name: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def has_failures(self) -> bool:
        return any(f.severity == "FAIL" for f in self.findings)

    @property
    def n_fail(self) -> int:
        return sum(1 for f in self.findings if f.severity == "FAIL")

    @property
    def n_warn(self) -> int:
        return sum(1 for f in self.findings if f.severity == "WARN")


# ---------------------------------------------------------------------------
# AST-based code introspector
# ---------------------------------------------------------------------------

class CodeIntrospector:
    """Extract structured metadata from a Python source file via AST."""

    def __init__(self, source_path: Path) -> None:
        self.source_path = source_path
        self.source = source_path.read_text(encoding="utf-8")
        self.tree = ast.parse(self.source, filename=str(source_path))

    def extract_config_keys(self) -> set[str]:
        """Find config access patterns like self.session.config.X.Y or cfg.X.Y."""
        keys: set[str] = set()

        KNOWN_SECTIONS = {
            "sync", "curation", "postprocess", "resources",
            "preprocess", "parallel",
        }

        # Find local aliases: e.g. sync = self.session.config.sync
        # or cfg = self.session.config (root alias)
        alias_map: dict[str, str] = {}
        # Pattern 1: alias = self.session.config.section (section-level alias)
        for m in re.finditer(
            r"(\w+)\s*=\s*self\.session\.config\.(\w+(?:\.\w+)*)", self.source
        ):
            alias_map[m.group(1)] = m.group(2)
        # Pattern 2: alias = self.session.config (root alias, no further dot)
        for m in re.finditer(
            r"(\w+)\s*=\s*self\.session\.config\b(?!\.)", self.source
        ):
            alias_map[m.group(1)] = ""  # Empty prefix = root of config

        # Direct self.session.config.X.Y access
        for m in re.finditer(
            r"self\.session\.config\.(\w+(?:\.\w+)+)", self.source
        ):
            keys.add(m.group(1))

        # Alias-based access: e.g. sync.foo → "sync.foo", cfg.postprocess.slay → "postprocess.slay"
        for alias, prefix in alias_map.items():
            for m in re.finditer(
                rf"\b{re.escape(alias)}\.(\w+(?:\.\w+)*)\b", self.source
            ):
                attr_chain = m.group(1)
                # Skip method calls, dunder, and non-config patterns
                first_part = attr_chain.split(".")[0]
                if first_part.startswith("_") or first_part in (
                    "return_value", "side_effect", "assert_called",
                ):
                    continue
                full_key = f"{prefix}.{attr_chain}" if prefix else attr_chain
                keys.add(full_key)

        # Filter: must start with a known config section
        filtered = set()
        for k in keys:
            parts = k.split(".")
            if parts[0] in KNOWN_SECTIONS:
                filtered.add(k)

        return filtered

    def extract_methods(self) -> dict[str, dict[str, Any]]:
        """Extract class method signatures from the first class definition."""
        methods: dict[str, dict[str, Any]] = {}
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        params = []
                        for arg in item.args.args:
                            if arg.arg != "self":
                                params.append(arg.arg)
                        ret = ast.unparse(item.returns) if item.returns else "None"
                        methods[item.name] = {"params": params, "returns": ret}
                break  # First class only
        return methods

    def extract_checkpoint_fields(self) -> set[str]:
        """Find _write_checkpoint({...}) dict keys."""
        fields: set[str] = set()
        # Use regex to find _write_checkpoint({ ... }) calls and extract keys
        # This handles multi-line dict literals
        pattern = r"self\._write_checkpoint\(\s*\{"
        for m in re.finditer(pattern, self.source):
            start = m.end() - 1  # Position of opening {
            depth = 0
            i = start
            while i < len(self.source):
                if self.source[i] == "{":
                    depth += 1
                elif self.source[i] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                i += 1
            dict_text = self.source[start : i + 1]
            # Extract top-level string keys
            for key_match in re.finditer(r'"(\w+)"\s*:', dict_text):
                fields.add(key_match.group(1))
        return fields

    def extract_imports(self) -> list[dict[str, Any]]:
        """Extract from X import Y statements."""
        imports: list[dict[str, Any]] = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                names = [alias.name for alias in node.names]
                imports.append({"from": node.module, "names": sorted(names)})
        return imports

    def extract_error_classes(self) -> set[str]:
        """Find raise XError(...) patterns."""
        errors: set[str] = set()
        for m in re.finditer(r"\braise\s+(\w+Error)\b", self.source):
            errors.add(m.group(1))
        # Also find except XError
        for m in re.finditer(r"\bexcept\s+(\w+Error)\b", self.source):
            errors.add(m.group(1))
        return errors

    def extract_file_outputs(self) -> set[str]:
        """Find file write patterns (paths written to)."""
        outputs: set[str] = set()
        # to_parquet patterns
        for m in re.finditer(r'\.to_parquet\([^)]*["\']([^"\']+\.parquet)["\']', self.source):
            outputs.add(m.group(1))
        # Path / "X" / "Y" → to_parquet/write_text
        for m in re.finditer(
            r'(?:to_parquet|write_text|to_csv)\(\s*(?:\w+\s*/\s*)?["\']([^"\']+)["\']',
            self.source,
        ):
            outputs.add(m.group(1))
        # Relative path strings in Path constructions near write calls
        for m in re.finditer(r'/\s*"([^"]+\.(json|parquet|csv|nwb))"', self.source):
            outputs.add(m.group(1))
        return outputs


# ---------------------------------------------------------------------------
# Manifest loader
# ---------------------------------------------------------------------------

def load_manifest(stage_name: str) -> dict[str, Any]:
    """Load a YAML manifest for a stage."""
    path = MANIFESTS_DIR / f"{stage_name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Comparator
# ---------------------------------------------------------------------------

def compare_config_keys(
    manifest: dict[str, Any],
    introspected: set[str],
) -> list[Finding]:
    """Compare manifest config_keys against introspected keys."""
    findings: list[Finding] = []
    manifest_keys = {item["key"] for item in manifest.get("config_keys", [])}

    for key in sorted(manifest_keys - introspected):
        findings.append(Finding(
            "config_keys", "FAIL", "MISSING_IN_CODE",
            f"{key} declared in manifest but not found in code",
        ))
    for key in sorted(introspected - manifest_keys):
        findings.append(Finding(
            "config_keys", "WARN", "MISSING_IN_MANIFEST",
            f"{key} found in code but not in manifest",
        ))
    return findings


def compare_methods(
    manifest: dict[str, Any],
    introspected: dict[str, dict[str, Any]],
) -> list[Finding]:
    """Compare manifest public_methods against introspected methods."""
    findings: list[Finding] = []
    manifest_methods = {m["name"]: m for m in manifest.get("public_methods", [])}

    for name in sorted(set(manifest_methods) - set(introspected)):
        findings.append(Finding(
            "methods", "FAIL", "MISSING_IN_CODE",
            f"method {name}() declared in manifest but not in code",
        ))

    for name in sorted(set(manifest_methods) & set(introspected)):
        m_spec = manifest_methods[name]
        m_code = introspected[name]
        spec_params = set(m_spec.get("params", []))
        code_params = set(m_code.get("params", []))
        if spec_params != code_params:
            findings.append(Finding(
                "methods", "WARN", "VALUE_MISMATCH",
                f"{name}() params: manifest={sorted(spec_params)}, code={sorted(code_params)}",
            ))

    return findings


def compare_checkpoint(
    manifest: dict[str, Any],
    introspected: set[str],
) -> list[Finding]:
    """Compare manifest checkpoint fields against introspected fields."""
    findings: list[Finding] = []
    manifest_fields = set(manifest.get("checkpoint", {}).get("fields", []))

    for f in sorted(manifest_fields - introspected):
        findings.append(Finding(
            "checkpoint", "FAIL", "MISSING_IN_CODE",
            f"field '{f}' in manifest but not found in _write_checkpoint()",
        ))
    for f in sorted(introspected - manifest_fields):
        findings.append(Finding(
            "checkpoint", "WARN", "MISSING_IN_MANIFEST",
            f"field '{f}' found in _write_checkpoint() but not in manifest",
        ))
    return findings


def compare_errors(
    manifest: dict[str, Any],
    introspected: set[str],
) -> list[Finding]:
    """Compare manifest errors_raised against introspected error classes."""
    findings: list[Finding] = []
    manifest_errors = set(manifest.get("errors_raised", []))

    for e in sorted(manifest_errors - introspected):
        findings.append(Finding(
            "errors", "WARN", "MISSING_IN_CODE",
            f"{e} in manifest but not raised/caught in code",
        ))
    for e in sorted(introspected - manifest_errors):
        findings.append(Finding(
            "errors", "WARN", "MISSING_IN_MANIFEST",
            f"{e} raised/caught in code but not in manifest",
        ))
    return findings


def compare_imports(
    manifest: dict[str, Any],
    introspected: list[dict[str, Any]],
) -> list[Finding]:
    """Compare manifest imports against introspected imports."""
    findings: list[Finding] = []

    # Build sets of (module, name) tuples
    manifest_pairs: set[tuple[str, str]] = set()
    for imp in manifest.get("imports", []):
        for name in imp.get("names", []):
            manifest_pairs.add((imp["from"], name))

    code_pairs: set[tuple[str, str]] = set()
    for imp in introspected:
        for name in imp.get("names", []):
            code_pairs.add((imp["from"], name))

    for mod, name in sorted(manifest_pairs - code_pairs):
        findings.append(Finding(
            "imports", "FAIL", "MISSING_IN_CODE",
            f"from {mod} import {name} — in manifest but not in code",
        ))
    for mod, name in sorted(code_pairs - manifest_pairs):
        # Only warn about project-internal imports, not stdlib
        if "pynpxpipe" in mod:
            findings.append(Finding(
                "imports", "WARN", "MISSING_IN_MANIFEST",
                f"from {mod} import {name} — in code but not in manifest",
            ))

    return findings


# ---------------------------------------------------------------------------
# Main check logic
# ---------------------------------------------------------------------------

def check_stage(stage_name: str) -> StageReport:
    """Run full comparison for one stage."""
    manifest = load_manifest(stage_name)
    source_path = ROOT / manifest["source_path"]

    if not source_path.exists():
        report = StageReport(stage_name)
        report.findings.append(Finding(
            "setup", "FAIL", "MISSING_IN_CODE",
            f"source file not found: {source_path}",
        ))
        return report

    intro = CodeIntrospector(source_path)
    report = StageReport(stage_name)

    report.findings.extend(compare_config_keys(manifest, intro.extract_config_keys()))
    report.findings.extend(compare_methods(manifest, intro.extract_methods()))
    report.findings.extend(compare_checkpoint(manifest, intro.extract_checkpoint_fields()))
    report.findings.extend(compare_errors(manifest, intro.extract_error_classes()))
    report.findings.extend(compare_imports(manifest, intro.extract_imports()))

    return report


def discover_manifests() -> list[str]:
    """Return stage names for all manifests found in spec_manifests/."""
    if not MANIFESTS_DIR.exists():
        return []
    return sorted(p.stem for p in MANIFESTS_DIR.glob("*.yaml"))


def print_report(report: StageReport) -> None:
    """Pretty-print a stage report."""
    status = "FAIL" if report.has_failures else "OK"
    print(f"\n=== {report.stage_name} [{status}] ===")
    if not report.findings:
        print("  All checks passed.")
        return
    for finding in report.findings:
        print(str(finding))
    print(f"  Summary: {report.n_fail} FAIL, {report.n_warn} WARN")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Spec-code drift detection harness")
    sub = parser.add_subparsers(dest="command")

    check_p = sub.add_parser("check", help="Check spec-code alignment")
    check_p.add_argument("--stage", help="Check a single stage (default: all)")

    sub.add_parser("list", help="List available manifests")

    args = parser.parse_args()

    if args.command == "list":
        stages = discover_manifests()
        if not stages:
            print("No manifests found in spec_manifests/")
        else:
            for s in stages:
                print(f"  {s}")
        return

    if args.command == "check":
        if args.stage:
            stages = [args.stage]
        else:
            stages = discover_manifests()
            if not stages:
                print("No manifests found in spec_manifests/")
                sys.exit(1)

        any_fail = False
        for stage_name in stages:
            report = check_stage(stage_name)
            print_report(report)
            if report.has_failures:
                any_fail = True

        print(f"\n{'='*40}")
        total = len(stages)
        failed = sum(
            1 for s in stages if check_stage(s).has_failures
        )
        print(f"Total: {total} stages checked, {failed} FAIL, {total - failed} OK")

        sys.exit(1 if any_fail else 0)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
