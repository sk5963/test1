from __future__ import annotations

import mmap
from collections import Counter, OrderedDict
from contextlib import closing, nullcontext
from pathlib import Path
from typing import Callable

from .model import PartRow, TestColumn, WideDataset
from .stdf import binary_parser
from .stdf_metadata import StdfMetadataCollector
from .coordinates import apply_map_coordinate_rule
from .stdf.base import truncation_warning as bp_truncation_warning


_METADATA_RECORDS = {
    (0, 10), (0, 20),
    (1, 10), (1, 20), (1, 30), (1, 40), (1, 50), (1, 60), (1, 80),
    (2, 10), (2, 20), (2, 30),
}

_STDF_MISSING_COORDINATE = -32768


def _number(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _integer(value):
    number = _number(value)
    return None if number is None else int(number)


def _coordinate(value) -> int | None:
    """Return a usable PRR coordinate, excluding the STDF missing sentinel."""
    coordinate = _integer(value)
    return None if coordinate == _STDF_MISSING_COORDINATE else coordinate


def _unit_symbol(value: str) -> str:
    """Translate STDF long unit names to nd4core's approved unit symbols."""
    text = str(value or "").strip()
    upper = text.upper()
    aliases = {
        "A": "A", "V": "V", "R": "R", "W": "W", "S": "S", "HZ": "Hz",
        "AMPERE": "A", "AMPERES": "A", "AMP": "A", "AMPS": "A",
        "VOLT": "V", "VOLTS": "V", "OHM": "R", "OHMS": "R", "Ω": "R",
        "SECOND": "S", "SECONDS": "S", "SEC": "S",
        "WATT": "W", "WATTS": "W", "HERTZ": "Hz",
        "INT": "", "INTEGER": "", "DOUBLE": "", "FLOAT": "",
    }
    return aliases.get(upper, text)


def _passed_from_bins(
    sbin: int | None,
    hbin: int | None,
    sbin_pf: dict[int, str],
    hbin_pf: dict[int, str],
) -> bool:
    """Prefer standard BIN_PF flags and retain Bin 1 as the legacy fallback."""
    from .stdf.base import passed_from_bins
    return passed_from_bins(sbin, hbin, sbin_pf, hbin_pf)


def _next_stdf_shot(current_shot: int, has_active_parts: bool) -> int:
    """Advance once per PIR group and retain the Shot for every active DUT."""
    return current_shot if has_active_parts else current_shot + 1


def parse_stdf(
    path: str | Path,
    on_progress: Callable[[int, str], None] | None = None,
) -> WideDataset:
    """ND STDF V4 entry point. See :func:`parse_stdf_records`."""
    return parse_stdf_records(path, on_progress, binary_parser)


def parse_stdf_records(
    path: str | Path,
    on_progress: Callable[[int, str], None] | None,
    bp,
    *,
    split_mpr_title: bool = True,
    extra_metadata: dict[str, str] | None = None,
) -> WideDataset:
    """STDF V4 파일을 읽어 공통 WideDataset을 반환한다 (파일 출력 없음).

    path: 바이너리 STDF 경로. endian/레코드 디코딩은 stdf.binary_parser 담당.
    on_progress: (0~100 정수, 설명 문자열) 동기 콜백. 예외 발생 시 호출자에게 전파.
    처리 흐름: 레코드 -> 내부 items/rows -> TestColumn/PartRow.
    PIR/PRR로 DUT/Shot을 묶고, PTR/MPR/FTR로 측정값을 채운다.
    스케일/리밋/판정은 기존 변환 규칙을 유지하므로 소비자에서 중복 변환하지 말 것.
    """
    path = Path(path)

    last_progress = -1

    def progress(percent: int, label: str) -> None:
        nonlocal last_progress
        percent = max(0, min(100, int(percent)))
        if on_progress is not None and percent != last_progress:
            last_progress = percent
            on_progress(percent, label)

    progress(0, "Analyzing STDF header")
    metadata: dict[str, str] = {}
    pmr_names: dict[int, str] = {}
    items = OrderedDict()
    current_parts: dict[str, dict] = {}
    mpr_pin_specs: dict[int, list] = {}
    ftr_name_cache: dict[int, tuple] = {}
    ptr_name_cache: dict[int, tuple] = {}
    hbin_names: dict[int, str] = {}
    sbin_names: dict[int, str] = {}
    hbin_pf: dict[int, str] = {}
    sbin_pf: dict[int, str] = {}
    counts: Counter[tuple[int, int]] = Counter()
    warnings: list[str] = []

    if path.stat().st_size == 0:
        raise ValueError(f"Empty STDF file: {path.name}")
    from .row_spool import RowSpool, should_spool
    spool = RowSpool() if should_spool(path) else None
    # The spool is a temp file; close it even when parsing fails.
    with closing(spool) if spool is not None else nullcontext():
        rows = spool if spool is not None else []
        shot_number = 0
        with path.open("rb") as fp:
            mm = mmap.mmap(fp.fileno(), 0, access=mmap.ACCESS_READ)
            buf = memoryview(mm)
            try:
                little = bp._detect_endian(buf)
                metadata_collector = StdfMetadataCollector(bp, little)
                hdr = bp._HDR if little else bp._HDR_BE
                structs = bp._LE if little else bp._BE
                pos = 0
                total_bytes = max(1, len(buf))
                next_progress_offset = max(1, total_bytes // 75)
                while pos + 4 <= len(buf):
                    rec_len, rec_typ, rec_sub = hdr.unpack_from(buf, pos)
                    start = pos + 4
                    end = start + rec_len
                    if end > len(buf):
                        # Keep what was read (e.g. a lot still being written) and
                        # flag the dataset instead of failing the whole file.
                        warnings.append(bp_truncation_warning(pos, rec_typ, rec_sub))
                        metadata["incomplete"] = "1"
                        break
                    key = (rec_typ, rec_sub)
                    counts[key] += 1
                    if key in _METADATA_RECORDS:
                        metadata_collector.collect(key, buf, start, end)
                    if key == (15, 10):
                        bp._decode_ptr(buf, start, end, structs, current_parts, items, path.name, ptr_name_cache)
                    elif key == (15, 15):
                        bp._decode_mpr(buf, start, end, structs, little, current_parts, items, pmr_names, mpr_pin_specs, path.name)
                    elif key == (15, 20):
                        bp._decode_ftr(buf, start, end, structs, current_parts, items, ftr_name_cache, path.name)
                    elif key == (5, 10):
                        shot_number = _next_stdf_shot(shot_number, bool(current_parts))
                        part_key = bp._decode_pir(buf, start, end, structs, current_parts, path.name)
                        if part_key in current_parts:
                            current_parts[part_key]["_shot"] = shot_number
                    elif key == (5, 20):
                        bp._decode_prr(buf, start, end, structs, current_parts, rows, path.name)
                    elif key == (1, 10):
                        bp._decode_mir(buf, start, end, structs, little, metadata)
                    elif key == (1, 80):
                        bp._decode_sdr(buf, start, end, little, metadata)
                    elif key == (1, 60):
                        bp._decode_pmr(buf, start, end, little, pmr_names)
                    elif key == (1, 40):
                        bp._decode_bin(buf, start, end, little, hbin_names, hbin_pf)
                    elif key == (1, 50):
                        bp._decode_bin(buf, start, end, little, sbin_names, sbin_pf)
                    pos = end
                    if pos >= next_progress_offset:
                        percent = min(75, pos * 75 // total_bytes)
                        progress(percent, "Parsing STDF records")
                        next_progress_offset = max(next_progress_offset + 1, (percent + 1) * total_bytes // 75)
                else:
                    if pos != len(buf):
                        warnings.append(f"Trailing {len(buf) - pos} bytes after final STDF record")
                        metadata["incomplete"] = "1"
            finally:
                buf.release()
                mm.close()
        if current_parts:
            warnings.append(f"{len(current_parts)} DUT(s) opened by PIR without PRR were ignored")

        occurrence: Counter[int] = Counter()
        key_lookup: dict[tuple, str] = {}
        tests: list[TestColumn] = []
        total_items = max(1, len(items))
        for item_index, (item_key, spec) in enumerate(items.items()):
            ordinal = occurrence[spec.testnum]
            occurrence[spec.testnum] += 1
            # 같은 Test Number도 여러 항목일 수 있다. rows의 내부 키를 공개 키로 연결한다.
            public_key = f"{spec.testnum}_{ordinal}"
            key_lookup[item_key] = public_key
            title = spec.name
            pin = ""
            if spec.record_type == "MPR" and "/" in title:
                if split_mpr_title:
                    title, pin = title.rsplit("/", 1)
                else:  # V93K keeps the full "<test>/<pin>" title
                    _, pin = title.rsplit("/", 1)
            enriched = None
            if spec.record_type == "PTR" and getattr(spec, "_meta_optional_captured", False):
                enriched = (
                    getattr(spec, "_meta_res_scale", None),
                    getattr(spec, "_meta_low", None),
                    getattr(spec, "_meta_high", None),
                    getattr(spec, "_meta_units", ""),
                )
            result_scale = enriched[0] if enriched else None
            low_limit = _number(spec.ll)
            high_limit = _number(spec.ul)
            unit = spec.units
            if enriched:
                if low_limit is None: low_limit = enriched[1]
                if high_limit is None: high_limit = enriched[2]
                if not unit: unit = enriched[3]
            display_scale = spec.scaler or (bp.scale_label(result_scale) if result_scale not in (None, 0) else "")
            base_unit = _unit_symbol(unit)
            tests.append(TestColumn(
                key=public_key,
                test_num=spec.testnum,
                title=title,
                pin=pin,
                record_type=spec.record_type,
                unit=(display_scale + base_unit) if base_unit else "",
                lo_limit=low_limit,
                hi_limit=high_limit,
                scaler=display_scale,
                raw_unit=str(unit or ""),
            ))
            progress(75 + (item_index + 1) * 8 // total_items, "Building test items")

        parts: list[PartRow] = []
        shot = 0
        sites_in_shot: set[int] = set()
        total_rows = max(1, len(rows))
        for index, row in enumerate(rows):
            site = _integer(row.get("site")) or 0
            recorded_shot = _integer(row.get("_shot"))
            if recorded_shot is not None:
                shot = recorded_shot
            else:
                if not sites_in_shot or site in sites_in_shot:
                    shot += 1
                    sites_in_shot.clear()
                sites_in_shot.add(site)
            values: dict[str, float] = {}
            for item_key, raw in (row.get("values") or {}).items():
                public_key = key_lookup.get(item_key)
                if not public_key:
                    continue
                value = _number(raw)
                if value is None:
                    continue
                spec = items[item_key]
                if spec.record_type == "FTR":
                    value = 1.0 if int(value) & 0x80 else 0.0
                values[public_key] = value
            sbin = _integer(row.get("soft_bin"))
            hbin = _integer(row.get("hard_bin"))
            # DUT 판정은 BIN 기반. 위 FTR 단일 항목 값(0/1)과 구분한다.
            passed = _passed_from_bins(sbin, hbin, sbin_pf, hbin_pf)
            parts.append(PartRow(
                index=index,
                shot=shot,
                sample=None,
                x=_coordinate(row.get("x_coord")),
                y=_coordinate(row.get("y_coord")),
                test_time_ms=_integer(row.get("test_time")),
                real_time=str(row.get("temp") or ""),
                hbin=hbin,
                sbin=sbin,
                site=site,
                part_id=str(row.get("part_id") or ""),
                passed=passed,
                values=values,
            ))
            progress(83 + (index + 1) * 17 // total_rows, "Building DUT data")

        named_counts = {f"{typ}/{sub}": count for (typ, sub), count in sorted(counts.items())}
        metadata_collector.add_record_counts(named_counts)
        metadata.update(metadata_collector.canonical)
        metadata.update(metadata_collector.fields)
        metadata.update({
            "plan": metadata.get("program", ""),
            "lot": metadata.get("lotid", "").strip(),
            "sublot": metadata.get("sublotid", "").strip(),
            "station": metadata.get("tester_id", ""),
            "source_file": path.name,
            "numeric_encoding": "STDF_R4",
            **(extra_metadata or {}),
        })
        dataset = WideDataset(path, "STDF", metadata, tests, parts, warnings, named_counts)
        apply_map_coordinate_rule(dataset)
        progress(100, "STDF parsing complete")
        return dataset
