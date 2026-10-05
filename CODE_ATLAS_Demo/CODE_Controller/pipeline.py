"""단계 조정만 담당. FTP·변환·통계·Report 구현은 각 모듈에 둔다."""

import json
from pathlib import Path
import shutil
import uuid
from CODE_Common.io import digest, now, VERSION
from CODE_Common.artifacts import snapshot, verify
from CODE_STDF_Converter.service import convert
from CODE_Statistics.service import generate as statistics
from CODE_Report.service import generate as report
from CODE_FTP.service import receive, publish

STAGES = ("convert", "statistics", "report", "upload")
LABELS = {
    "download": "FTP 수신",
    "convert": "STDF 변환",
    "statistics": "기본 통계",
    "report": "Report 생성",
    "upload": "결과 업로드",
    "cleanup": "임시 중간 데이터 정리",
}


def job_key(c):
    return json.dumps(
        {
            "version": c.get("tool_version", VERSION),
            "histogram_bins": c["histogram_bins"],
            "intermediate_format": c.get("intermediate_format", "csv"),
            "measurement_excel_enabled": c.get("measurement_excel_enabled", True),
            "transport": c["transport"],
            "ftp": c["ftp"],
        },
        sort_keys=True,
    )


def create_run(store, source, c):
    source = Path(source).resolve()
    if not source.is_file():
        raise ValueError("원본 파일이 없습니다.")
    run_id = (
        now().replace(":", "").replace("+0000", "").replace("-", "")[:15]
        + "-"
        + uuid.uuid4().hex[:8]
    )
    store.create(
        run_id,
        source,
        digest(source),
        {
            **{k: v for k, v in c.items() if not k.startswith("_")},
            "tool_version": VERSION,
        },
    )
    return run_id


def verify_stage(store, run, stage):
    step = store.steps(run["id"]).get(stage, {})
    if step.get("status") != "성공":
        raise ValueError("선행 단계를 먼저 완료하세요.")
    result = json.loads(step["result_json"])
    verify(store.root / "runs" / run["id"], stage, result.get("_artifacts"), bool(run["cleaned"]))


def execute_stage(store, c, run_id, stage, emit):
    r = store.run(run_id)
    steps = store.steps(run_id)
    c = {**c, **json.loads(r["config_json"])}
    if steps.get(stage, {}).get("status") == "성공":
        try:
            verify_stage(store, r, stage)
        except (ValueError, OSError, KeyError) as exc:
            store.state(run_id, "실패", str(exc))
            raise ValueError("완료 결과 검증 실패. 새 실행 건으로 다시 생성하세요: " + str(exc)) from exc
        emit(
            stage,
            "이미 완료한 단계입니다. 새 결과는 새 실행 건으로 생성하세요.",
            100,
            run_id,
        )
        return
    source = Path(r["source"])
    if not source.is_file() or digest(source) != r["source_hash"]:
        raise ValueError("원본 누락 또는 변경이 확인되었습니다.")
    folder = store.root / "runs" / run_id
    folder.mkdir(parents=True, exist_ok=True)
    order = STAGES.index(stage)
    for prior in STAGES[:order]:
        try:
            verify_stage(store, r, prior)
        except (ValueError, OSError, KeyError) as exc:
            store.state(run_id, "실패", str(exc))
            raise
    if r["cleaned"] and stage in ("statistics",):
        raise ValueError("중간 데이터가 정리되었습니다. 새 실행 건으로 다시 변환하세요.")
    store.state(run_id, "실행 중")
    store.step(run_id, stage, "실행 중")
    emit(stage, LABELS[stage] + " 시작", 0, run_id)
    stage_dir = folder / (
        {"convert": "conversion", "statistics": "statistics", "report": "report"}.get(
            stage, stage
        )
    )
    try:
        if stage != "upload" and stage_dir.exists():
            shutil.rmtree(stage_dir)
        progress = lambda n, m: emit(stage, m, n, run_id)
        if stage == "convert":
            result = convert(source, stage_dir, progress, c["intermediate_format"])
        elif stage == "statistics":
            meta = json.loads(steps["convert"]["result_json"])
            csv_path = Path(meta.get("data_path") or meta["full_csv"])
            if not csv_path.is_file() or digest(csv_path) != meta.get("data_sha256", meta["csv_sha256"]):
                raise ValueError("중간 데이터 무결성 확인에 실패했습니다.")
            result = statistics(csv_path, stage_dir, c["histogram_bins"], progress,
                                c["measurement_excel_enabled"])
        elif stage == "report":
            result = report(
                folder / "conversion" / "conversion.json",
                folder / "statistics",
                stage_dir,
            )
        else:
            result = publish(
                c, store, run_id, folder, lambda s, m, n: emit(s, m, n, run_id)
            )
        result = {**result, "_artifacts": snapshot(folder, stage, result)}
        store.step(run_id, stage, "성공", result)
        store.state(run_id, "완료" if stage == "upload" else "단계 완료")
        emit(stage, LABELS[stage] + " 완료", 100, run_id)
    except BaseException as exc:
        store.step(run_id, stage, "실패", {"error": str(exc)})
        store.state(run_id, "실패", str(exc))
        emit(stage, "실패: " + str(exc), 0, run_id)
        raise


def pipeline(store, c, emit):
    incoming = receive(c, store, lambda s, m, n: emit(s, m, n, ""))
    failed = []
    completed = []
    for source in incoming["files"]:
        sha = digest(source)
        candidates = store.db.execute(
            "SELECT * FROM runs WHERE source=? AND source_hash=? ORDER BY created DESC",
            (source, sha),
        ).fetchall()
        existing = next(
            (
                r
                for r in candidates
                if job_key(json.loads(r["config_json"])) == job_key(c)
            ),
            None,
        )
        if existing:
            try:
                for stage, step in store.steps(existing["id"]).items():
                    if step["status"] == "성공":
                        verify_stage(store, existing, stage)
            except (ValueError, OSError, KeyError) as exc:
                store.state(existing["id"], "실패", str(exc))
                emit("pipeline", "결과 검증 실패로 새 실행 건 생성: " + str(exc), 0, existing["id"])
                existing = None
        if existing and existing["status"] == "완료":
            emit(
                "pipeline",
                "전체 처리 완료 이력으로 건너뜀: " + Path(source).name,
                100,
                existing["id"],
            )
            continue
        run_id = existing["id"] if existing else create_run(store, source, c)
        try:
            for stage in STAGES:
                execute_stage(store, c, run_id, stage, emit)
            completed.append(run_id)
        except Exception:
            failed.append(run_id)
    return dict(receipt=incoming, completed=completed, failed=failed)
