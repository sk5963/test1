"""Portable STDF V4 / ADVANTEST DataLog parsing (Python 3.10+).

Copy this entire directory next to your application's entry point.
Only the Python standard library is required.
"""
from pathlib import Path
from typing import Callable

from .datalog import parse_datalog
from .stdf_reader import parse_stdf
from .model import PartRow, TestColumn, WideDataset

__version__ = "1.0.0"
__all__ = ["parse_file", "parse_stdf", "parse_datalog", "WideDataset", "TestColumn", "PartRow"]


def parse_file(
    path: str | Path,
    *,
    format: str | None = None,
    pin: bool = False,
    on_progress: Callable[[int, str], None] | None = None,
) -> WideDataset:
    """Parse a file without generating reports or writing output files.

    Auto detection uses the extension, not content sniffing. For an unusual
    extension specify format='stdf' or format='datalog' explicitly.
    Callback exceptions propagate, allowing caller-controlled cancellation.
    Pin grouping applies only to DataLog; STDF retains its native pin metadata.

    연동 인자:
        path: 읽을 파일 경로(str/Path). 파서는 원본 파일을 수정하지 않는다.
        format: None이면 확장자로 분기. 'stdf'/'datalog'로 명시 가능.
        pin: DataLog 핀별 항목 분리 여부. STDF에는 적용하지 않는다.
        on_progress: (percent: int, message: str)를 받는 동기 콜백.
            작업 스레드에서 호출했다면 콜백도 같은 스레드에서 실행된다.
            GUI 위젯 직접 갱신 대신 호출 프로그램의 signal/queue를 사용한다.
    반환값:
        WideDataset. dataset.test_map()[key]로 part.values[key]의 정의를 찾는다.
        누락 값은 0으로 채우지 말고 key 존재 여부로 구분한다.
    예외:
        미지원 포맷은 ValueError. 읽기/파싱 오류와 콜백 예외는 호출자에게 전달한다.
        호출자는 오류 안내, 재시도, 작업 취소 UI를 담당한다.
    """
    path = Path(path)
    if format is None:
        formats = {".stdf": "stdf", ".log": "datalog", ".log_a": "datalog"}
        kind = formats.get(path.suffix.lower())
    else:
        kind = format.strip().casefold()
    if kind == "stdf":
        return parse_stdf(path, on_progress=on_progress)
    if kind == "datalog":
        return parse_datalog(path, pin=pin, on_progress=on_progress)
    raise ValueError("Unsupported format: use .stdf/.log/.log_a or specify format='stdf'/'datalog'")
