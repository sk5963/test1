"""Common CSV writer used by every benchmark parser.

The format mirrors the existing ``v93k_stdf_convert`` Full-CSV schema so that
output from any of the three parsers can be diffed against ``CONV.csv``.
"""
from __future__ import annotations

import json
import re
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

BASE_HEADER = [
    "part_id",
    "temp",
    "x_coord",
    "y_coord",
    "wafer_id",
    "soft_bin",
    "hard_bin",
    "test_time",
    "site",
    "source_dataset",
    "plot_ul",
]

META_LABELS = [
    "lotid", "sublotid", "start_t", "program", "tester_type",
    "tester_id", "handler", "finish_t", "job_rev",
]

FULL_SCHEMA_VERSION = "2"
COMPLETE_MARKER = "#V93K_CONVERSION_COMPLETE"
COMPLETE_VALUE = "OK"
CONVERSION_SUBDIR = ".STDF_To_CSV_conversion"

# Trailing run timestamp on STDF names (CP: _YYYYMMDD_HHMMSS, FT: _YYYYMMDDHHMMSS).
_STDF_RUN_TS = re.compile(r"_\d{8}_\d{6}$")
_STDF_RUN_TS_COMPACT = re.compile(r"_\d{14}$")
_WAFER_LABEL = re.compile(r"([A-Z0-9][A-Z0-9]*-\d{2})(?:_|$)", re.I)


def stdf_output_base_name(path: Path) -> str:
    """Short export base name — drop trailing run timestamp from STDF/CSV name.

    Example::
        V1.0_S6M4W_S6M4W-01_CACP2025-03039_CP1_20260617_220913.stdf
        → V1.0_S6M4W_S6M4W-01_CACP2025-03039_CP1
    """
    name = path.name
    lower = name.lower()
    if lower.endswith(".csv"):
        stem = name[:-4]
    elif lower.endswith(".stdf"):
        stem = name[:-5]
    else:
        stem = name
    for pat in (_STDF_RUN_TS, _STDF_RUN_TS_COMPACT):
        m = pat.search(stem)
        if m:
            return stem[: m.start()]
    return stem


def wafer_label_from_path(path: Path) -> str:
    """Extract wafer tag such as ``S6M4W-01`` from an STDF/CSV file name."""
    stem = stdf_output_base_name(path)
    matches = list(_WAFER_LABEL.finditer(stem))
    if matches:
        return matches[-1].group(1).upper()
    return stem[:40]


def output_csv_filename(base: str, *, variant: str = "") -> str:
    """Build a ``.csv`` file name without pathlib ``with_suffix`` (breaks on ``V1.0_…``)."""
    tag = variant or ""
    return f"{base}{tag}.csv"


def output_data_xlsx_filename(base: str) -> str:
    """XLSX export (Summary · Map · Histogram) — distinct from the CSV base name."""
    return f"{base}_data.xlsx"


def output_histogram_group_wafers_xlsx_filename() -> str:
    """Combined Histogram_Group workbook — all wafers side-by-side."""
    return "Histogram_Group_by_wafer_data.xlsx"


def conversion_output_dir(stdf_path: Path) -> Path:
    """``<stdf_parent>/.STDF_To_CSV_conversion`` — flat, no subfolders."""
    return stdf_path.parent / CONVERSION_SUBDIR


def _ensure_csv_suffix(path: Path) -> Path:
    name = path.name
    if name.lower().endswith(".csv"):
        return path
    return path.parent / f"{name}.csv"


def conversion_csv_paths(
    stdf_path: Path,
    *,
    write_full: bool = True,
    write_pass: bool = False,
    write_ng: bool = False,
    out_dir: Path | None = None,
) -> dict[str, Path | None]:
    """Return FULL / PASS / NG output paths (always ``.csv`` extension)."""
    target = out_dir or conversion_output_dir(stdf_path)
    base = stdf_output_base_name(stdf_path)
    return {
        "out_dir": target,
        "full": (target / output_csv_filename(base)) if write_full else None,
        "pass": (target / output_csv_filename(base, variant="_pass")) if write_pass else None,
        "ng": (target / output_csv_filename(base, variant="_ng")) if write_ng else None,
    }


def legacy_conversion_csv_paths(stdf_path: Path) -> dict[str, Path]:
    """Older output names kept for cache lookup."""
    out_dir = conversion_output_dir(stdf_path)
    stem = stdf_path.name.rsplit(".", 1)[0] if stdf_path.suffix else stdf_path.name
    base = stdf_output_base_name(stdf_path)
    return {
        "full": out_dir / output_csv_filename(base),
        "pass": out_dir / output_csv_filename(base, variant="_pass"),
        "ng": out_dir / output_csv_filename(base, variant="_ng"),
        "full_stem": out_dir / output_csv_filename(stem),
        "pass_stem": out_dir / output_csv_filename(stem, variant="_pass"),
        "ng_stem": out_dir / output_csv_filename(stem, variant="_ng"),
        "full_binary": out_dir / f"{stem}__binary.csv",
        "pass_binary": out_dir / f"{stem}__binary_pass.csv",
        "ng_binary": out_dir / f"{stem}__binary_ng.csv",
    }


def format_number(value: Any) -> str:
    """Format numbers like the legacy converter (``%.15g``).

    Empty / None / NaN become ``""``.
    """
    if value is None or value == "":
        return ""
    if isinstance(value, float):
        if value != value:  # NaN
            return ""
        return f"{value:.15g}"
    if isinstance(value, int):
        return str(value)
    return str(value)


def scale_label(power: int) -> str:
    return {0: "", 3: "m", 6: "u", 9: "n", 12: "p",
            -3: "k", -6: "M", -9: "G"}.get(power, str(power) if power else "")


def apply_scale(value: float | None, power: int | None) -> float | None:
    if value is None:
        return None
    if power is None or power == 0:
        return value
    return value * (10 ** power)


def format_stdf_time(timestamp: Any) -> str:
    try:
        ts = int(timestamp)
    except Exception:
        return ""
    if ts <= 0:
        return ""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def normalize_int_text(raw: Any) -> str:
    text = str(raw).strip() if raw is not None else ""
    if not text:
        return ""
    try:
        n = float(text)
    except ValueError:
        return text
    return str(int(n)) if n.is_integer() else text


class ItemSpec:
    __slots__ = (
        "testnum", "name", "scaler", "units", "ll", "ul", "record_type", "_res_scale",
        "_meta_optional_captured", "_meta_res_scale", "_meta_low", "_meta_high", "_meta_units",
    )

    def __init__(self, testnum: int, name: str, scaler: str = "", units: str = "",
                 ll: str = "", ul: str = "", record_type: str = "PTR") -> None:
        self.testnum = testnum
        self.name = name
        self.scaler = scaler
        self.units = units
        self.ll = ll
        self.ul = ul
        self.record_type = record_type
        self._res_scale = None
        self._meta_optional_captured = False
        self._meta_res_scale = None
        self._meta_low = None
        self._meta_high = None
        self._meta_units = ""


def is_pass_row(part: dict[str, Any]) -> bool:
    """Legacy Bin-1 rule, used only when no SBR/HBR pass flags are known."""
    soft_bin = normalize_int_text(part.get("soft_bin", ""))
    hard_bin = normalize_int_text(part.get("hard_bin", ""))
    return soft_bin == "1" or (not soft_bin and hard_bin == "1")


def _bin_number(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def passed_from_bins(sbin: Any, hbin: Any, sbin_pf: dict[int, str], hbin_pf: dict[int, str]) -> bool:
    """Single DUT pass rule for CSV, Bin statistics and analysis.

    Prefer the standard SBR/HBR BIN_PF flags and keep Bin 1 as the fallback
    when a bin has no P/F flag (legacy converter behaviour).
    """
    sbin = _bin_number(sbin)
    hbin = _bin_number(hbin)
    if sbin is not None:
        flag = str(sbin_pf.get(sbin) or "").strip().upper()
        if flag in {"P", "F"}:
            return flag == "P"
        return sbin == 1
    if hbin is not None:
        flag = str(hbin_pf.get(hbin) or "").strip().upper()
        if flag in {"P", "F"}:
            return flag == "P"
        return hbin == 1
    return False


def truncation_warning(offset: int, rec_typ: int, rec_sub: int) -> str:
    return (f"Truncated STDF record at offset {offset} ({rec_typ}/{rec_sub}); "
            "data up to this point was used (incomplete file)")


def write_csv_outputs(
    stdf_path: Path,
    metadata: dict[str, str],
    items: "OrderedDict[tuple[int, str], ItemSpec]",
    rows: list[dict[str, Any]],
    *,
    full_path: Path | None = None,
    pass_path: Path | None = None,
    ng_path: Path | None = None,
    progress_callback: Any = None,
    progress_range: tuple[int, int] = (60, 96),
    marker_values: dict[str, Any] | None = None,
    header_metadata: dict[str, Any] | None = None,
    metadata_labels: Iterable[str] | None = None,
    pass_rule: Callable[[dict[str, Any]], bool] | None = None,
) -> tuple[int, int, int]:
    """Write FULL / PASS / NG CSV files (any combination) in one pass.

    Returns ``(full_row_count, pass_row_count, ng_row_count)``.
    """
    if not any((full_path, pass_path, ng_path)):
        raise ValueError("At least one output path is required")
    item_list = list(items.values())
    width = len(item_list) + len(BASE_HEADER) + 1
    item_offset = len(BASE_HEADER) + 1
    active_metadata_labels = list(metadata_labels) if metadata_labels is not None else META_LABELS
    if len(active_metadata_labels) > len(BASE_HEADER) - 1:
        raise ValueError("Metadata labels overlap the reserved test metadata column")
    blank = [""] * width

    def make_row(first: str) -> list[str]:
        row = blank.copy()
        row[0] = first
        return row

    def meta_row(values: list[str], label_value: str, items_attr: str) -> list[str]:
        row = make_row("0.4")
        row[item_offset - 1] = label_value
        for idx, spec in enumerate(item_list):
            row[item_offset + idx] = getattr(spec, items_attr)
        return row

    # Header rows ------------------------------------------------------------
    head: list[list[str]] = []
    head.append(make_row("0.1"))
    if header_metadata:
        for field, value in header_metadata.items():
            head.append(["#STDF_HEADER", str(field), format_number(value)])

    # 0.2 meta labels
    r02 = make_row("0.2")
    for i, label in enumerate(active_metadata_labels, start=1):
        r02[i] = label
    r02[item_offset - 1] = "testnum"
    for idx, spec in enumerate(item_list):
        r02[item_offset + idx] = str(spec.testnum)
    head.append(r02)

    # 0.3 meta values
    r03 = make_row("0.3")
    for i, label in enumerate(active_metadata_labels, start=1):
        r03[i] = metadata.get(label, "")
    r03[item_offset - 1] = "testname"
    for idx, spec in enumerate(item_list):
        r03[item_offset + idx] = spec.name
    head.append(r03)

    for attr, row_id, label in (
        ("scaler", "0.4", "scaler"),
        ("units", "0.5", "units"),
        ("ll", "0.6", "ll"),
        ("ul", "0.7", "ul"),
    ):
        row = make_row(row_id)
        row[item_offset - 1] = label
        for idx, spec in enumerate(item_list):
            row[item_offset + idx] = getattr(spec, attr)
        head.append(row)

    # 0.8 plot_ll empty
    row = make_row("0.8")
    row[item_offset - 1] = "plot_ll"
    head.append(row)

    # 0.9 column headers
    row = ["0.9", *BASE_HEADER, *[spec.name for spec in item_list]]
    head.append(row)

    stat = stdf_path.stat()
    src_name = stdf_path.name

    full_count = 0
    pass_count = 0
    ng_count = 0

    def join_csv(cells: list[str]) -> str:
        out: list[str] = []
        for c in cells:
            if c is None:
                out.append("")
                continue
            s = c if isinstance(c, str) else str(c)
            if "," in s or '"' in s or "\n" in s:
                out.append('"' + s.replace('"', '""') + '"')
            else:
                out.append(s)
        return ",".join(out)

    handles: dict[str, Any] = {}
    try:
        for kind, path in (("full", full_path), ("pass", pass_path), ("ng", ng_path)):
            if path is None:
                continue
            path = _ensure_csv_suffix(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            # UTF-8 without BOM so Windows Explorer shows "CSV" (not "Unicode text").
            handles[kind] = open(path, "w", encoding="utf-8", newline="", buffering=1 << 20)

        for hr in head:
            line = join_csv(hr) + "\n"
            for handle in handles.values():
                handle.write(line)

        total_rows = len(rows)
        prog_lo, prog_hi = progress_range
        prog_span = max(0, prog_hi - prog_lo)
        last_prog = prog_lo
        prog_step = max(1, total_rows // 50)  # ~50 callbacks during write

        for row_idx, part in enumerate(rows):
            if progress_callback and total_rows and (row_idx % prog_step == 0):
                pct = prog_lo + int(row_idx / total_rows * prog_span)
                if pct > last_prog:
                    last_prog = pct
                    progress_callback(pct, f"Writing CSV {row_idx:,}/{total_rows:,}")
            # The reference converter writes "1" as a per-row type marker
            # (not a sequential index). Match that convention exactly.
            data = ["1"]
            for column in BASE_HEADER:
                data.append(format_number(part.get(column, "")) if column == "test_time" else str(part.get(column, "")))
            values = part.get("values") or {}
            for spec_key in items.keys():
                v = values.get(spec_key, "")
                data.append(v if isinstance(v, str) else format_number(v))
            line = join_csv(data) + "\n"
            passed = pass_rule(part) if pass_rule is not None else is_pass_row(part)
            if "full" in handles:
                handles["full"].write(line)
                full_count += 1
            if "pass" in handles and passed:
                handles["pass"].write(line)
                pass_count += 1
            if "ng" in handles and not passed:
                handles["ng"].write(line)
                ng_count += 1

        counts = {"full": full_count, "pass": pass_count, "ng": ng_count}
        marker_rows = [
            [COMPLETE_MARKER, "", COMPLETE_VALUE],
            ["#V93K_FULL_SCHEMA", "", FULL_SCHEMA_VERSION],
            ["#V93K_SOURCE_STDF", "", str(stdf_path)],
            ["#V93K_SOURCE_SIZE", "", str(stat.st_size)],
            ["#V93K_SOURCE_MTIME", "", str(int(stat.st_mtime))],
            ["#V93K_CONVERTED_AT", "", datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
        ]
        if marker_values:
            # Keep them as simple 3-column CSV marker rows: KEY,,VALUE
            for k, v in marker_values.items():
                if not k:
                    continue
                key = str(k)
                if not key.startswith("#"):
                    key = "#V93K_" + key
                if isinstance(v, (dict, list)):
                    val = json.dumps(v, ensure_ascii=False, separators=(",", ":"))
                else:
                    val = "" if v is None else str(v)
                marker_rows.append([key, "", val])
        for kind, handle in handles.items():
            rows_marker = marker_rows + [["#V93K_ROW_COUNT", "", str(counts[kind])]]
            for mr in rows_marker:
                handle.write(join_csv(mr) + "\n")
    finally:
        for handle in handles.values():
            try:
                handle.close()
            except Exception:
                pass

    _ = src_name
    return full_count, pass_count, ng_count


def write_full_csv(
    output_path: Path,
    stdf_path: Path,
    metadata: dict[str, str],
    items: "OrderedDict[tuple[int, str], ItemSpec]",
    rows: list[dict[str, Any]],
    ng_output_path: Path | None = None,
) -> tuple[int, int]:
    """Backward-compatible wrapper: full CSV (+ optional NG)."""
    full, _pass, ng = write_csv_outputs(
        stdf_path, metadata, items, rows,
        full_path=output_path,
        pass_path=None,
        ng_path=ng_output_path,
    )
    return full, ng
