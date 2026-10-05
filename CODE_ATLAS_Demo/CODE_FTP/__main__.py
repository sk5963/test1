import argparse
import json
from CODE_Common.io import load_config, file_lock
from CODE_Common.store import Store
from .service import receive


def main():
    p = argparse.ArgumentParser(description="FTP 자료 수신 또는 결과 업로드 독립 실행")
    p.add_argument("action", choices=["download", "upload"])
    p.add_argument("--config")
    p.add_argument("--run-id")
    a = p.parse_args()
    s = None
    try:
        c = load_config(a.config)
        s = Store(c["_workspace"])
        with file_lock(s.root / "pipeline.lock"):
            if a.action == "download":
                result = receive(c, s)
            else:
                if not a.run_id or not a.run_id.replace("-", "").isalnum():
                    raise ValueError("안전한 실행 ID가 필요합니다.")
                from CODE_Controller.pipeline import execute_stage
                execute_stage(s, c, a.run_id, "upload", lambda *a: None)
                result = json.loads(s.steps(a.run_id)["upload"]["result_json"])
        print(json.dumps({"type": "result", "result": result}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False))
        return 1
    finally:
        if s:
            s.close()


if __name__ == "__main__":
    raise SystemExit(main())
