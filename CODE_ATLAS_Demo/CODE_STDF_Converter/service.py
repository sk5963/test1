"""기존 binary_parser.run을 감싸는 변환 어댑터. 원본 엔진은 수정하지 않는다."""

import sys
import time
from pathlib import Path
from CODE_Common.io import ROOT, VERSION, now, digest, write_json
from CODE_Common.measurements import write_parquet

sys.path.insert(0, str(ROOT / "CODE_Vendor"))
from ate_parsers.stdf.binary_parser import run as legacy_convert


def convert(source, output, progress=None, data_format="parquet"):
    source, output = Path(source).resolve(), Path(output).resolve()
    if data_format not in ("csv", "parquet"):
        raise ValueError("출력 포맷은 csv 또는 parquet여야 합니다.")
    if not source.is_file() or source.suffix.lower() not in (".stdf", ".std"):
        raise ValueError("바이너리 .stdf 또는 .std 파일을 선택하세요.")
    output.mkdir(parents=True, exist_ok=False)
    start = time.perf_counter()
    before = digest(source)
    result = legacy_convert(
        source,
        output,
        progress_callback=(lambda n, text: progress(n, "기존 STDF 엔진 처리 중"))
        if progress
        else None,
        write_full=True,
        write_pass=False,
        write_ng=False,
    )
    if not result["rows"] or not result["items"]:
        raise ValueError("변환 가능한 칩 또는 테스트 항목이 없습니다.")
    if result.get("warnings"):
        raise ValueError(
            "원본 파서 경고가 발생해 완료 처리를 중단합니다: "
            + "; ".join(result["warnings"])
        )
    if before != digest(source):
        raise ValueError("변환 중 원본 파일이 변경되었습니다.")
    csv_path = Path(result["full_csv"])
    result.update(
        schema_version=2,
        tool_version=VERSION,
        created=now(),
        source=str(source),
        source_sha256=before,
        csv_sha256=digest(csv_path),
        duration_seconds=round(time.perf_counter() - start, 3),
        format="legacy_full_wide_csv",
    )
    result.update(data_path=str(csv_path), data_sha256=result["csv_sha256"],
                  data_bytes=csv_path.stat().st_size, data_format="csv", compression=None)
    if data_format == "parquet":
        if progress:
            progress(95, "가로형 Parquet · ZSTD 압축 생성 중")
        parquet = write_parquet(csv_path, csv_path.with_suffix(".parquet"),
                                {"metadata": result["metadata"], "source_sha256": before})
        result.update(parquet, format="wide_parquet_v1", full_csv=None)
    if digest(source) != before:
        raise ValueError("중간 데이터 생성 중 원본이 변경되었습니다.")
    result["duration_seconds"] = round(time.perf_counter() - start, 3)
    write_json(output / "conversion.json", result)
    if data_format == "parquet":
        # 기존 엔진의 연결 CSV는 Parquet 및 변환 기록 확정 후 즉시 제거한다.
        csv_path.unlink()
    return result
