"""기존 Full CSV의 행 마커 계약. 측정 단위와 스케일을 다시 변환하지 않는다."""

import csv
from pathlib import Path


def header(path):
    rows = {}
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        for row in csv.reader(f):
            if not row:
                continue
            if row[0] in ("0.2", "0.3", "0.5", "0.6", "0.7", "0.9"):
                rows[row[0]] = row
            if row[0] == "0.9":
                break
    if "0.2" not in rows or "0.9" not in rows:
        raise ValueError("기존 Full CSV 헤더가 없습니다.")
    offset = rows["0.2"].index("testnum") + 1
    base = rows["0.9"][1:offset]
    tests = []
    for i, number in enumerate(rows["0.2"][offset:]):

        def field(tag):
            r = rows.get(tag, [])
            return r[offset + i] if offset + i < len(r) else ""

        tests.append(
            {
                "key": f"col_{i + 1:04d}",
                "number": number,
                "title": field("0.3"),
                "unit": field("0.5"),
                "lower": field("0.6"),
                "upper": field("0.7"),
            }
        )
    return base, tests, offset


def records(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        yield from (row for row in csv.reader(f) if row)
