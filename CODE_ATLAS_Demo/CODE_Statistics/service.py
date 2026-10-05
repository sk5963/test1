"""가로형 Parquet / CSV를 2회 읽어 통계·히스토그램·맵·통계시트를 생성한다."""

from collections import Counter
import json
import math
from pathlib import Path
import numpy as np
from .charts import save_map, save_histograms
from .workbook import save_workbook
from .measurement_workbook import save_measurements
from CODE_Common.measurements import header, records
from CODE_Common.io import digest, now, VERSION, write_json


def number(value):
    try:
        v = float(value)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def passed(part, flags):
    for field, kind in [("soft_bin", "sbin"), ("hard_bin", "hbin")]:
        value = part.get(field, "")
        if value not in ("", None):
            flag = flags[kind].get(str(int(float(value))))
            return flag == "P" if flag in ("P", "F") else int(float(value)) == 1
    return False


def generate(csv_path, output, bins=20, progress=None, measurement_excel=True):
    csv_path, output = Path(csv_path), Path(output)
    if type(bins) is not int or not 2 <= bins <= 200:
        raise ValueError("히스토그램 구간은 2~200의 정수여야 합니다.")
    before = digest(csv_path)
    output.mkdir(parents=True, exist_ok=False)
    base, tests, offset = header(csv_path)
    size = len(tests)
    count = np.zeros(size, dtype=np.int64)
    mean = np.zeros(size)
    m2 = np.zeros(size)
    minima = np.full(size, np.inf)
    maxima = np.full(size, -np.inf)
    missing = np.zeros(size, dtype=np.int64)
    lo = np.array(
        [
            number(t["lower"]) if number(t["lower"]) is not None else -np.inf
            for t in tests
        ]
    )
    hi = np.array(
        [
            number(t["upper"]) if number(t["upper"]) is not None else np.inf
            for t in tests
        ]
    )
    out_of_limit = np.zeros(size, dtype=np.int64)
    markers = {}
    parts = []
    batch = []

    def consume():
        if not batch:
            return
        values = np.array(batch, dtype=float)
        valid = np.isfinite(values)
        n = valid.sum(axis=0)
        safe = np.where(valid, values, 0)
        bm = np.divide(safe.sum(axis=0), n, out=np.zeros(size), where=n > 0)
        bm2 = np.where(valid, (safe - bm) ** 2, 0).sum(axis=0)
        total = count + n
        delta = bm - mean
        m2[:] += bm2 + np.divide(
            delta**2 * count * n, total, out=np.zeros(size), where=total > 0
        )
        mean[:] += np.divide(delta * n, total, out=np.zeros(size), where=total > 0)
        count[:] = total
        minima[:] = np.minimum(minima, np.where(valid, values, np.inf).min(axis=0))
        maxima[:] = np.maximum(maxima, np.where(valid, values, -np.inf).max(axis=0))
        missing[:] += (~valid).sum(axis=0)
        out_of_limit[:] += (valid & ((values < lo) | (values > hi))).sum(axis=0)
        batch.clear()

    for row in records(csv_path):
        if row[0] == "1":
            if len(row) < offset + size:
                raise ValueError("측정 데이터 열 수가 맞지 않습니다.")
            parts.append(dict(zip(base, row[1:offset])))
            batch.append([number(x) for x in row[offset : offset + size]])
            if len(batch) >= 1024:
                consume()
        elif row[0].startswith("#") and len(row) > 2:
            markers[row[0]] = row[2]
    consume()
    if not parts or markers.get("#V93K_CONVERSION_COMPLETE") != "OK":
        raise ValueError("완료된 변환 데이터가 아닙니다.")
    if int(markers.get("#V93K_ROW_COUNT", "-1")) != len(parts):
        raise ValueError("측정 데이터 행 수 검증에 실패했습니다.")
    bin_meta = json.loads(markers.get("#V93K_BIN_STATS_JSON", "{}"))
    flags = {
        kind: {str(x["num"]): x.get("pf", "") for x in bin_meta.get(kind, [])}
        for kind in ("sbin", "hbin")
    }
    pass_count = sum(passed(p, flags) for p in parts)
    if bin_meta and (
        bin_meta.get("total") != len(parts) or bin_meta.get("pass") != pass_count
    ):
        raise ValueError("기존 엔진 수율과 분석 수율이 일치하지 않습니다.")
    if progress:
        progress(45, "통계 집계 완료 · 히스토그램 생성 중")
    edges = []
    for i in range(size):
        low, high = (minima[i], maxima[i]) if count[i] else (0.0, 1.0)
        if low == high:
            pad = max(abs(low) * 0.01, 0.5)
            low -= pad
            high += pad
        edges.append(np.linspace(low, high, bins + 1))
    hist = np.zeros((size, bins), dtype=np.int64)
    batch = []

    def histogram_batch():
        if not batch:
            return
        a = np.array(batch, dtype=float)
        for i in range(size):
            hist[i] += np.histogram(a[:, i][np.isfinite(a[:, i])], bins=edges[i])[0]
        batch.clear()

    for row in records(csv_path):
        if row[0] == "1":
            batch.append([number(x) for x in row[offset : offset + size]])
            if len(batch) >= 1024:
                histogram_batch()
    histogram_batch()
    test_results = []
    for i, t in enumerate(tests):
        test_results.append(
            dict(
                t,
                count=int(count[i]),
                missing=int(missing[i]),
                mean=float(mean[i]) if count[i] else None,
                std=float(math.sqrt(max(0, m2[i]) / (count[i] - 1)))
                if count[i] > 1
                else None,
                minimum=float(minima[i]) if count[i] else None,
                maximum=float(maxima[i]) if count[i] else None,
                out_of_limit=int(out_of_limit[i]),
                edges=edges[i].tolist(),
                counts=hist[i].tolist(),
            )
        )
    map_cells = []
    unknown = 0
    for i, p in enumerate(parts):
        x, y = number(p.get("x_coord")), number(p.get("y_coord"))
        if x is None or y is None or x == -32768 or y == -32768:
            unknown += 1
            continue
        map_cells.append(
            dict(
                row=i,
                x=int(x),
                y=int(y),
                passed=passed(p, flags),
                site=p.get("site"),
                sbin=p.get("soft_bin"),
            )
        )
    if digest(csv_path) != before:
        raise ValueError("통계 처리 중 입력 데이터가 변경되었습니다.")
    if any(int(hist[i].sum()) != int(count[i]) for i in range(size)):
        raise ValueError("통계와 히스토그램 측정 수가 다릅니다.")
    summary = dict(
        schema_version=2,
        tool_version=VERSION,
        created=now(),
        data_sha256=before,
        data_format="parquet" if csv_path.suffix.lower() == ".parquet" else "csv",
        csv_sha256=before if csv_path.suffix.lower() == ".csv" else None,
        total=len(parts),
        passed=pass_count,
        failed=len(parts) - pass_count,
        yield_percent=round(pass_count / len(parts) * 100, 4),
        test_count=size,
        yield_policy="전체 PRR 측정 행 기준. 재시험 포함; 최신 좌표 기준 수율 아님.",
        map_policy="동일 좌표의 마지막 측정 행을 표시. 수율은 전체 행 기준.",
        measurement_excel=measurement_excel,
        missing_coordinates=unknown,
        sbin_counts=dict(Counter(p.get("soft_bin", "") for p in parts)),
        hbin_counts=dict(Counter(p.get("hard_bin", "") for p in parts)),
    )
    write_json(output / "summary.json", summary)
    write_json(output / "histograms.json", {"schema_version": 1, "tests": test_results})
    write_json(
        output / "map.json",
        {"schema_version": 1, "cells": map_cells, "policy": summary["map_policy"]},
    )
    save_map(output / "map.svg", map_cells)
    save_histograms(output / "histograms.html", test_results)
    save_workbook(output / "statistics.xlsx", summary, test_results, map_cells)
    if measurement_excel:
        save_measurements(output / "measurements.xlsx", csv_path, summary)
        if digest(csv_path) != before:
            raise ValueError("전체 측정값 Excel 생성 중 입력 데이터가 변경되었습니다.")
    if progress:
        progress(100, "통계 결과물 생성 완료")
    return summary
