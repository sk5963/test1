"""ADVANTEST DataLog to the common WideDataset model; no report rendering."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Callable

from . import datalog_core as core
from .model import PartRow, TestColumn, WideDataset
from .coordinates import apply_map_coordinate_rule


def _datalog_shot_numbers(chip_records: list[dict]) -> list[int]:
    """Use Sample # as Shot; synthesize groups only for records without it."""
    shots: list[int] = []
    source_shots = {
        int(rec["sample"])
        for rec in chip_records
        if rec.get("sample") is not None and str(rec.get("sample")).strip() != ""
    }
    fallback_shot = max(source_shots, default=0)
    seen_sites: set[int] = set()

    for rec in chip_records:
        sample = rec.get("sample")
        if sample is not None and str(sample).strip() != "":
            shots.append(int(sample))
            seen_sites.clear()
            continue

        site = int(rec.get("dut") or 0)
        if not seen_sites or site in seen_sites:
            fallback_shot += 1
            seen_sites.clear()
        seen_sites.add(site)
        shots.append(fallback_shot)

    return shots


def parse_datalog(
    path: str | Path,
    *,
    pin: bool = False,
    on_progress: Callable[[int, str], None] | None = None,
) -> WideDataset:
    """ADVANTEST DataLog 파일을 공통 모델로 변환한다.

    path는 UTF-8로 읽을 원본 경로, pin은 핀별 그룹화 옵션이다.
    on_progress(percent, message)는 읽기/항목/행 변환 진행률을 받는다.
    반환 결과는 FT와 재측정 행을 보존한다. 표시/수율 필터는 호출자가 적용한다.
    내부 parsed(dict, SI 값)를 공개 WideDataset으로 바꾸는 경계가 이 함수이다.
    """
    path = Path(path)
    last_progress = -1

    def progress(percent: int, label: str) -> None:
        nonlocal last_progress
        percent = max(0, min(100, int(percent)))
        if on_progress is not None and percent != last_progress:
            last_progress = percent
            on_progress(percent, label)

    # Category/FT records stay in the source dataset; display filtering is downstream.
    from .row_spool import should_spool
    parse_cfg = dict(pin=pin, ft=True, mode="REAL", _metadata_only=True,
                     _spool_rows=should_spool(path))
    parsed = core.parse_file_records(
        str(path), parse_cfg,
        on_progress=lambda percent: progress(percent * 75 // 100, "Parsing DataLog file"),
    )

    tests: list[TestColumn] = []
    # 원본 복합 키(tid/title/pin) -> 공개 TestColumn.key. 두 키 체계를 혼용하지 않는다.
    item_keys: dict[str, str] = {}
    occurrence: Counter[int] = Counter()
    parsed_items = parsed.get("items", [])
    total_items = max(1, len(parsed_items))
    for item_index, item in enumerate(parsed_items):
        tid = int(item["tid"])
        ordinal = occurrence[tid]
        occurrence[tid] += 1
        key = f"{tid}_{ordinal}"
        item_keys[item["key"]] = key
        unit = str(item.get("baseUnit") or "")
        # 내부 SI 값 / 단위 배율 -> 공개 표시 값. 예: 1e-6 A / 1e-6 = 1 uA.
        # 아래 리밋과 PartRow.values 변환에 동일한 배율을 적용한다.
        multiplier = float(core.UM.get(unit, 1) or 1)
        tests.append(TestColumn(
            key=key,
            test_num=tid,
            title=str(item.get("title") or ""),
            pin=str(item.get("pin") or ""),
            record_type="FTR" if item.get("type") == "FT" else "PTR",
            unit=unit,
            lo_limit=(item["_lo"] / multiplier) if item.get("_lo") is not None else None,
            hi_limit=(item["_up"] / multiplier) if item.get("_up") is not None else None,
            scaler="",
            raw_unit=unit,
        ))
        progress(75 + (item_index + 1) * 7 // total_items, "Building test items")

    parts: list[PartRow] = []
    chip_records = parsed.get("chipRecords", [])
    shot_numbers = _datalog_shot_numbers(chip_records)
    total_records = max(1, len(chip_records))
    test_lookup = {test.key: test for test in tests}
    for index, (rec, shot) in enumerate(zip(chip_records, shot_numbers)):
        site = int(rec.get("dut") or 0)
        values: dict[str, float] = {}
        result_pass = True
        for native_key, measurement in (rec.get("meas") or {}).items():
            public_key = item_keys.get(native_key)
            if public_key is None:
                # Group-by-title keys and chip-record keys can differ only in
                # display grouping; fall back to matching on tid + title.
                bits = native_key.split("|")
                for item in parsed_items:
                    if int(item["tid"]) == int(bits[0]) and str(
                        item.get("title") or ""
                    ) == (bits[1] if len(bits) > 1 else ""):
                        public_key = item_keys.get(item["key"])
                        if public_key:
                            break
            if public_key is None:
                continue
            test = test_lookup.get(public_key)
            multiplier = float(core.UM.get(test.unit, 1) or 1) if test else 1.0
            values[public_key] = float(measurement["si"]) / multiplier
            result_pass = result_pass and bool(measurement.get("pass", True))
        category = str(rec.get("category") or "")
        soft_bin = None
        if category:
            try:
                category_number = float(category)
                result_pass = result_pass and category_number == 1
                if category_number.is_integer():
                    soft_bin = int(category_number)
            except ValueError:
                token = category.strip().casefold()
                if token in {"fail", "f", "ng"}:
                    result_pass = False
                elif token in {"pass", "p", "ok"}:
                    result_pass = result_pass and True
        parts.append(PartRow(
            index=index,
            shot=shot,
            sample=rec.get("sample"),
            x=rec.get("x"),
            y=rec.get("y"),
            test_time_ms=None,
            real_time="",
            hbin=None,
            sbin=soft_bin,
            site=site,
            part_id="",
            passed=result_pass,
            category=category,
            values=values,
        ))
        progress(82 + (index + 1) * 18 // total_records, "Converting Data Table")

    hdr = dict(parsed.get("hdr") or {})
    hdr["source_file"] = path.name
    dataset = WideDataset(path, "DataLog", hdr, tests, parts)
    apply_map_coordinate_rule(dataset)
    progress(100, "DataLog parsing complete")
    return dataset
