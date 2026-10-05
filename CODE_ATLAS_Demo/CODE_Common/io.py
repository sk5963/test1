"""파일·설정·잠금 계약. 다른 구성요소의 처리 로직은 포함하지 않는다."""

from __future__ import annotations
import contextlib
import hashlib
import json
import os
import re
import copy
from pathlib import Path
import tempfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.2.1"
DEFAULT_CONFIG = {
    "schema_version": 1, "transport": "demo", "poll_seconds": 300,
    "retention_days": 7, "cleanup_enabled": True, "histogram_bins": 20,
    "intermediate_format": "parquet", "measurement_excel_enabled": True,
    "ftp": {"host": "ftp.example.invalid", "port": 21, "tls": False,
            "username_env": "ATLAS_FTP_USER", "password_env": "ATLAS_FTP_PASSWORD",
            "remote_input": "/ATE/STDF/incoming", "remote_output": "/ATE/results"},
}


def default_config(path=None):
    path = Path(path or ROOT / "config.json").resolve()
    c = copy.deepcopy(DEFAULT_CONFIG)
    c["_workspace"] = str(path.parent / "workspace")
    c["_config_path"] = str(path)
    return c


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix="." + path.name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_config(path=None):
    path = Path(path or ROOT / "config.json").resolve()
    c = read_json(path)
    if not isinstance(c, dict) or c.get("schema_version") != 1:
        raise ValueError("설정은 schema_version 1의 JSON 객체여야 합니다.")
    if set(c) - set(DEFAULT_CONFIG):
        raise ValueError("지원하지 않는 설정 항목입니다. 계정·비밀번호는 환경변수를 사용하세요.")
    # 이전 CSV 데모 설정은 명시 포맷이 없을 때 그대로 읽는다.
    c.setdefault("intermediate_format", "csv")
    c.setdefault("measurement_excel_enabled", True)
    if type(c.get("measurement_excel_enabled")) is not bool:
        raise ValueError("전체 측정값 Excel 출력 설정은 참 또는 거짓이어야 합니다.")
    if c.get("intermediate_format") not in ("csv", "parquet"):
        raise ValueError("중간 데이터 포맷은 csv 또는 parquet여야 합니다.")
    if c.get("transport") not in ("demo", "ftp"):
        raise ValueError("전송 방식은 demo 또는 ftp여야 합니다.")
    for key, lo, hi in [
        ("poll_seconds", 5, 86400),
        ("retention_days", 0, 3650),
        ("histogram_bins", 2, 200),
    ]:
        value = c.get(key)
        if type(value) is not int or not lo <= value <= hi:
            raise ValueError(f"{key}: {lo}~{hi} 범위의 정수가 필요합니다.")
    if type(c.get("cleanup_enabled")) is not bool:
        raise ValueError("중간 데이터 정리 설정이 필요합니다.")
    ftp = c.get("ftp", {})
    if (
        not isinstance(ftp, dict)
        or type(ftp.get("port")) is not int
        or not 1 <= ftp["port"] <= 65535
    ):
        raise ValueError("FTP 포트가 올바르지 않습니다.")
    if set(ftp) - set(DEFAULT_CONFIG["ftp"]):
        raise ValueError("지원하지 않는 FTP 설정 항목입니다.")
    if type(ftp.get("tls")) is not bool:
        raise ValueError("FTPS 설정은 참 또는 거짓이어야 합니다.")
    host = ftp.get("host")
    if not isinstance(host, str) or not host or any(ch.isspace() or ord(ch) < 32 for ch in host):
        raise ValueError("FTP 서버 주소가 올바르지 않습니다.")
    for key in ("username_env", "password_env"):
        value = ftp.get(key)
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
            raise ValueError("계정 환경변수 이름이 올바르지 않습니다.")
    for key in ("remote_input", "remote_output"):
        value = ftp.get(key)
        if not isinstance(value, str) or not value.startswith("/") or "\\" in value or any(ord(ch) < 32 for ch in value) or any(part in (".", "..") for part in value.split("/")):
            raise ValueError("FTP 경로는 안전한 절대 경로여야 합니다.")
    if c["transport"] == "ftp" and host.endswith(".invalid"):
        raise ValueError("실제 FTP 서버 주소를 먼저 입력하세요.")
    # 작업 경로는 고정해 UI 설정으로 다른 폴더를 지우지 않도록 한다.
    c["_workspace"] = str(path.parent / "workspace")
    c["_config_path"] = str(path)
    return c


@contextlib.contextmanager
def file_lock(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    f = path.open("a+b")
    if f.seek(0, 2) == 0:
        f.write(b"0")
        f.flush()
    f.seek(0)
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        raise RuntimeError(
            "다른 작업이 실행 중입니다. 완료 후 다시 실행하세요."
        ) from None
    try:
        yield
    finally:
        f.close()


def locked(path):
    try:
        with file_lock(path):
            return False
    except RuntimeError:
        return True
