"""실행별 결과 파일 목록과 무결성 계약. 중간 데이터 정리 후에도 최종 결과를 검증한다."""

from pathlib import Path
from CODE_Common.io import digest

REQUIRED = {
    "convert": {"conversion/conversion.json"},
    "statistics": {"statistics/summary.json", "statistics/histograms.json",
                   "statistics/map.json", "statistics/map.svg",
                   "statistics/histograms.html", "statistics/statistics.xlsx"},
    "report": {"report/index.html", "report/report.json"},
    "upload": {"complete.json"},
}


def checked_path(folder, relative):
    folder = Path(folder).resolve()
    relative = Path(relative)
    path = (folder / relative).resolve()
    if relative.is_absolute() or not path.is_relative_to(folder):
        raise ValueError("결과물 경로가 실행 폴더를 벗어납니다.")
    return path


def snapshot(folder, stage, result):
    folder = Path(folder)
    if stage == "convert":
        paths = [folder / "conversion/conversion.json", Path(result.get("data_path") or result["full_csv"])]
    elif stage == "upload":
        paths = [folder / "complete.json"]
    else:
        paths = sorted(p for p in (folder / stage).rglob("*") if p.is_file())
    files = []
    for p in paths:
        relative = p.relative_to(folder).as_posix()
        p = checked_path(folder, relative)
        files.append({"path": relative, "size": p.stat().st_size, "sha256": digest(p)})
    verify(folder, stage, files)
    if stage == "statistics" and result.get("measurement_excel") and not any(f["path"] == "statistics/measurements.xlsx" for f in files):
        raise ValueError("전체 측정값 Excel 결과가 누락되었습니다.")
    return files


def verify(folder, stage, files, cleaned=False):
    if not isinstance(files, list) or not files:
        raise ValueError("결과물 검증 기록이 없습니다. 새 실행 건을 생성하세요.")
    names = {f["path"] for f in files}
    if not REQUIRED[stage].issubset(names):
        raise ValueError("필수 결과물 목록이 누락되었습니다.")
    csvs = [f for f in files if f["path"].startswith("conversion/") and f["path"].endswith((".csv", ".parquet"))]
    if stage == "convert" and len(csvs) != 1:
        raise ValueError("변환 데이터 목록이 올바르지 않습니다.")
    for f in files:
        path = checked_path(folder, f["path"])
        if cleaned and stage == "convert" and f in csvs and not path.exists():
            continue
        if not path.is_file() or path.stat().st_size != f["size"] or digest(path) != f["sha256"]:
            raise ValueError("결과물 누락 또는 손상: " + f["path"])
