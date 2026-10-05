"""원본·완료 목록·최종 결과를 확인하고 해당 실행 중간 데이터만 정리한다."""

from datetime import datetime, timezone
from pathlib import Path
from CODE_Common.io import read_json, digest
from CODE_Common.artifacts import verify, checked_path, REQUIRED
import json


def cleanup(store, days, emit=lambda *a: None):
    removed, deferred = [], []
    for run in store.db.execute("SELECT * FROM runs WHERE status='완료' AND cleaned=0").fetchall():
        try:
            elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(run["updated"])).total_seconds()
            if elapsed < days * 86400:
                continue
            source = Path(run["source"])
            if not source.is_file() or digest(source) != run["source_hash"]:
                raise ValueError("원본 누락 또는 변경으로 중간 데이터를 보존합니다.")
            folder = store.root / "runs" / run["id"]
            steps = store.steps(run["id"])
            for stage in REQUIRED:
                if steps.get(stage, {}).get("status") != "성공":
                    raise ValueError("미완료 단계가 있어 중간 데이터를 보존합니다.")
                result = json.loads(steps[stage]["result_json"])
                # CSV는 아래에서 정리 경로와 별도로 검증한다.
                verify(folder, stage, result.get("_artifacts"), cleaned=True)
            meta = read_json(folder / "conversion/conversion.json")
            manifest = read_json(folder / "complete.json")
            expected = set().union(*(REQUIRED[s] for s in ("convert", "statistics", "report")))
            if manifest.get("run_id") != run["id"] or not expected.issubset({f["path"] for f in manifest["files"]}):
                raise ValueError("완료 목록의 실행 ID 또는 필수 결과가 다릅니다.")
            for f in manifest["files"]:
                path = checked_path(folder, f["path"])
                if not path.is_file() or digest(path) != f["sha256"]:
                    raise ValueError("최종 결과가 누락되거나 손상되었습니다.")
            csv_path = Path(meta.get("data_path") or meta["full_csv"]).resolve()
            if csv_path.parent != (folder / "conversion").resolve() or csv_path.suffix.lower() not in (".csv", ".parquet"):
                raise ValueError("정리 대상 경로가 변환 폴더 밖입니다.")
            if csv_path.exists() and digest(csv_path) != meta.get("data_sha256", meta["csv_sha256"]):
                raise ValueError("중간 데이터 변경으로 정리를 보류합니다.")
            csv_path.unlink(missing_ok=True)
            store.db.execute("UPDATE runs SET cleaned=1 WHERE id=?", (run["id"],))
            store.db.commit()
            removed.append(run["id"])
            emit("cleanup", f"임시 중간 데이터 정리: {run['id']}", 100)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            deferred.append({"run_id": run["id"], "reason": str(exc)})
            emit("cleanup", f"중간 데이터 정리 보류 ({run['id']}): {exc}", 0)
    return {"removed_runs": removed, "deferred_runs": deferred}
