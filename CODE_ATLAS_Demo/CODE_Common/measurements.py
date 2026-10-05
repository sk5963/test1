"""가로형 CSV·Parquet 공통 읽기 계약과 배치 Parquet 변환."""

import json
import math
import os
from pathlib import Path
from . import full_csv
from .io import digest


def _parquet(path):
    import pyarrow.parquet as pq
    return pq.ParquetFile(path)


def _definition(file):
    meta = file.metadata.metadata or {}
    if meta.get(b"atlas.format") != b"wide_measurements_v1":
        raise ValueError("ATLAS 가로형 Parquet 메타데이터가 없습니다.")
    definition = json.loads(meta[b"atlas.header"])
    expected = definition["base"] + [t["key"] for t in definition["tests"]]
    if file.schema_arrow.names != expected:
        raise ValueError("Parquet 열과 테스트 정의가 다릅니다.")
    return definition


def header(path):
    if Path(path).suffix.lower() != ".parquet":
        return full_csv.header(path)
    with _parquet(path) as file:
        d = _definition(file)
        return d["base"], d["tests"], len(d["base"]) + 1


def records(path):
    if Path(path).suffix.lower() != ".parquet":
        yield from full_csv.records(path)
        return
    with _parquet(path) as file:
        _definition(file)
        for batch in file.iter_batches(batch_size=1024):
            columns = [batch.column(i).to_pylist() for i in range(batch.num_columns)]
            for row in zip(*columns):
                yield ["1", *row]
        markers = json.loads(file.metadata.metadata[b"atlas.markers"])
        for key, value in markers.items():
            yield [key, "", value]


def write_parquet(csv_path, target, source_metadata=None, row_group_size=4096):
    import pyarrow as pa
    import pyarrow.parquet as pq
    csv_path, target = Path(csv_path), Path(target)
    if target.exists():
        raise ValueError("Parquet 출력 파일이 이미 존재합니다.")
    before = digest(csv_path)
    base, tests, offset = full_csv.header(csv_path)
    fields = [pa.field(name, pa.string()) for name in base]
    fields += [pa.field(t["key"], pa.float64()) for t in tests]
    schema = pa.schema(fields)
    rows, markers, total = [], {}, 0
    part = target.with_name(target.name + ".part")

    def numeric(value):
        try:
            n = float(value)
            return n if math.isfinite(n) else None
        except (ValueError, TypeError):
            return None

    def flush(writer):
        if not rows:
            return
        columns = list(zip(*rows))
        arrays = [pa.array(v, type=schema.field(i).type) for i, v in enumerate(columns)]
        writer.write_batch(pa.RecordBatch.from_arrays(arrays, schema=schema), row_group_size=row_group_size)
        rows.clear()

    try:
        with pq.ParquetWriter(part, schema, compression="zstd", compression_level=3,
                              use_dictionary=base, write_page_checksum=True, store_schema=False) as writer:
            for row in full_csv.records(csv_path):
                if row[0] == "1":
                    if len(row) != offset + len(tests):
                        raise ValueError("CSV 측정 열 수가 맞지 않습니다.")
                    rows.append(row[1:offset] + [numeric(x) for x in row[offset:]])
                    total += 1
                    if len(rows) >= row_group_size:
                        flush(writer)
                elif row[0].startswith("#") and len(row) > 2:
                    markers[row[0]] = row[2]
            flush(writer)
            if not total or markers.get("#V93K_CONVERSION_COMPLETE") != "OK" or int(markers.get("#V93K_ROW_COUNT", -1)) != total:
                raise ValueError("완료된 변환 CSV가 아닙니다.")
            writer.add_key_value_metadata({
                "atlas.format": "wide_measurements_v1",
                "atlas.header": json.dumps({"base": base, "tests": tests}, ensure_ascii=False),
                "atlas.markers": json.dumps(markers, ensure_ascii=False),
                "atlas.source_metadata": json.dumps(source_metadata or {}, ensure_ascii=False),
                "atlas.legacy_csv_sha256": before,
            })
        if digest(csv_path) != before:
            raise ValueError("Parquet 생성 중 CSV가 변경되었습니다.")
        with pq.ParquetFile(part) as file:
            _definition(file)
            if file.metadata.num_rows != total:
                raise ValueError("Parquet 행 수 검증에 실패했습니다.")
        os.replace(part, target)
    finally:
        part.unlink(missing_ok=True)
    return {"data_path": str(target), "data_sha256": digest(target),
            "data_bytes": target.stat().st_size, "data_format": "parquet", "compression": "zstd"}
