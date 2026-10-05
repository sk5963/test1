"""Electron 및 서버에서 공유하는 JSON Lines 명령 경계."""

import argparse
import json
import os
from pathlib import Path
import signal
import sys
import time
from CODE_Common.io import (
    load_config,
    write_json,
    read_json,
    now,
    file_lock,
    locked,
    VERSION,
    default_config,
)
from CODE_Common.store import Store
from CODE_Controller.pipeline import pipeline, create_run, execute_stage
from CODE_Controller.cleanup import cleanup
from CODE_FTP.service import receive
from CODE_Demo_Data.generate import generate


def output(value):
    print(json.dumps(value, ensure_ascii=False, allow_nan=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description="ATLAS 자동화 엔진")
    parser.add_argument(
        "command", choices=["status", "run", "watch", "stop", "demo", "save-config"]
    )
    parser.add_argument("--config")
    parser.add_argument(
        "--stage",
        default="pipeline",
        choices=[
            "pipeline",
            "download",
            "convert",
            "statistics",
            "report",
            "upload",
            "cleanup",
        ],
    )
    parser.add_argument("--input")
    parser.add_argument("--run-id")
    args = parser.parse_args()
    store = None
    c = default_config(args.config)
    root = Path(c["_workspace"])
    config_error = ""

    def emit(stage, message, percent=0, run_id=""):
        store.event(run_id, stage, message)
        output(
            dict(
                type="progress",
                stage=stage,
                message=message,
                percent=percent,
                run_id=run_id,
                time=now(),
            )
        )

    def stop_signal(*unused):
        raise KeyboardInterrupt()

    signal.signal(signal.SIGTERM, stop_signal)
    try:
        # 잘못된 기존 설정도 수정·중지할 수 있도록 해당 명령은 독립 경로를 사용한다.
        if args.command not in ("save-config", "stop"):
            try:
                c = load_config(args.config)
            except (ValueError, OSError, TypeError) as exc:
                if args.command != "status":
                    raise
                config_error = str(exc)
        store = Store(root)
        if args.command == "status":
            try:
                service = read_json(root / "service.json") if (root / "service.json").exists() else {}
                if not isinstance(service, dict):
                    service = {}
            except (ValueError, OSError):
                service = {}
            service["running"] = locked(root / "service.lock")
            result = {
                "type": "status",
                "version": VERSION,
                "config_error": config_error,
                "service": service,
                "busy": locked(root / "pipeline.lock"),
                "config": {k: v for k, v in c.items() if not k.startswith("_")},
                "runs": store.runs(),
                "events": [
                    dict(x)
                    for x in store.db.execute(
                        "SELECT * FROM events ORDER BY id DESC LIMIT 100"
                    )
                ],
                "steps": {r["id"]: store.steps(r["id"]) for r in store.runs()},
            }
            output(result)
            return 0
        if args.command == "save-config":
            proposed = json.load(sys.stdin)
            # 현재 경로를 유지하며 저장 전 동일 검증을 수행한다.
            from tempfile import TemporaryDirectory

            with TemporaryDirectory() as d:
                test = Path(d) / "config.json"
                write_json(test, proposed)
                load_config(test)
            write_json(c["_config_path"], proposed)
            output({"type": "saved"})
            return 0
        if args.command == "stop":
            write_json(root / "stop.json", {"requested": now()})
            output(
                {
                    "type": "stopping",
                    "message": "현재 작업을 완료한 후 자동 실행을 중지합니다.",
                }
            )
            return 0
        if args.command == "demo":
            source = generate(root / "demo_remote" / "incoming")
            output(
                {
                    "type": "demo",
                    "source": str(source),
                    "message": "96개 칩 · 500개 테스트의 합성 STDF 준비 완료",
                }
            )
            return 0

        def once():
            with file_lock(root / "pipeline.lock"):
                store.db.execute(
                    "UPDATE steps SET status='실패' WHERE status='실행 중'"
                )
                store.db.execute(
                    "UPDATE runs SET status='실패',error='이전 작업이 중단되었습니다.' WHERE status='실행 중'"
                )
                store.db.commit()
                if args.command == "watch" or args.stage == "pipeline":
                    result = pipeline(store, c, emit)
                elif args.stage == "download":
                    result = receive(c, store, lambda s, m, n: emit(s, m, n, ""))
                elif args.stage == "cleanup":
                    result = cleanup(
                        store, c["retention_days"], lambda s, m, n: emit(s, m, n, "")
                    )
                else:
                    run_id = args.run_id
                    if args.stage == "convert":
                        if not args.input:
                            raise ValueError("변환할 STDF 입력 파일을 선택하세요.")
                        run_id = create_run(store, args.input, c)
                    if not run_id:
                        raise ValueError("실행 이력을 선택하세요.")
                    execute_stage(store, c, run_id, args.stage, emit)
                    result = {"run_id": run_id}
                if c["cleanup_enabled"] and args.stage != "cleanup":
                    cleanup(
                        store, c["retention_days"], lambda s, m, n: emit(s, m, n, "")
                    )
                output({"type": "result", "result": result})
                return not result.get("failed")

        if args.command == "run":
            return 0 if once() else 1
        with file_lock(root / "service.lock"):
            (root / "stop.json").unlink(missing_ok=True)
            write_json(
                root / "service.json",
                {"pid": os.getpid(), "started": now(), "running": True},
            )
            try:
                while not (root / "stop.json").exists():
                    try:
                        c = load_config(args.config)
                        once()
                    except Exception as exc:
                        emit("service", "자동 처리 오류: " + str(exc))
                    deadline = time.monotonic() + c["poll_seconds"]
                    while (
                        time.monotonic() < deadline
                        and not (root / "stop.json").exists()
                    ):
                        write_json(
                            root / "service.json",
                            {"pid": os.getpid(), "running": True, "heartbeat": now()},
                        )
                        time.sleep(1)
            finally:
                write_json(
                    root / "service.json",
                    {"pid": os.getpid(), "running": False, "stopped": now()},
                )
        return 0
    except KeyboardInterrupt:
        output({"type": "error", "message": "실행이 중단되었습니다."})
        return 130
    except Exception as exc:
        output({"type": "error", "message": str(exc)})
        return 1
    finally:
        if store:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
