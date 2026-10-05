"""FTP 및 로컬 모의 전송. 완료 이력은 원본 처리 이력과 별도 관리한다."""

import ftplib
import hashlib
import json
import os
from pathlib import Path
import posixpath
import shutil
import ssl
from CODE_Common.io import digest, now, write_json
from CODE_Common.artifacts import checked_path, REQUIRED


def connect(c):
    f = c["ftp"]
    client = (
        ftplib.FTP_TLS(context=ssl.create_default_context())
        if f["tls"]
        else ftplib.FTP()
    )
    try:
        client.connect(f["host"], f["port"], timeout=60)
        client.login(os.environ[f["username_env"]], os.environ[f["password_env"]])
        if f["tls"]:
            client.prot_p()
        client.set_pasv(True)
        return client
    except BaseException:
        client.close()
        raise


def remote_files(client, root, relative=""):
    for name, meta in list(client.mlsd(posixpath.join(root, relative))):
        if meta.get("type") in ("cdir", "pdir"):
            continue
        if name in ("", ".", "..") or any(
            t in name for t in ("/", "\\", ":", "\r", "\n")
        ):
            raise ValueError("안전하지 않은 FTP 파일명입니다.")
        rel = posixpath.join(relative, name)
        if meta.get("type") == "dir":
            yield from remote_files(client, root, rel)
        elif meta.get("type") == "file" and name.lower().endswith((".stdf", ".std")):
            yield rel, meta


def receive(c, store, emit=lambda *a: None):
    origin = json.dumps([c["transport"], c["ftp"]["host"], c["ftp"]["port"], c["ftp"]["tls"], c["ftp"]["remote_input"]], sort_keys=True)
    root = store.root / "raw" / hashlib.sha256(origin.encode()).hexdigest()[:16]
    root.mkdir(parents=True, exist_ok=True)
    client = connect(c) if c["transport"] == "ftp" else None
    try:
        if client:
            entries = list(remote_files(client, c["ftp"]["remote_input"]))
        else:
            incoming = store.root / "demo_remote" / "incoming"
            incoming.mkdir(parents=True, exist_ok=True)
            entries = [
                (p.relative_to(incoming).as_posix(), {"size": str(p.stat().st_size)})
                for p in incoming.rglob("*")
                if p.is_file() and p.suffix.lower() in (".std", ".stdf")
            ]
        output = []
        downloaded = skipped = 0
        for rel, meta in entries:
            target = (root / rel).resolve()
            if not target.is_relative_to(root.resolve()):
                raise ValueError("수신 경로가 원본 보관 폴더를 벗어납니다.")
            source = (
                posixpath.join(c["ftp"]["remote_input"], rel)
                if client
                else str(incoming / rel)
            )
            identity = json.dumps(
                [
                    c["transport"],
                    c["ftp"]["host"],
                    c["ftp"]["port"],
                    c["ftp"]["tls"],
                    source,
                    str(root),
                ]
            )
            previous = store.db.execute(
                "SELECT * FROM receipts WHERE identity=?", (identity,)
            ).fetchone()
            if (
                previous
                and target.is_file()
                and target.stat().st_size == previous["size"]
                and digest(target) == previous["sha256"]
            ):
                skipped += 1
                emit("download", f"완료 이력으로 건너뜀: {rel}", 100)
                output.append(target)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            part = target.with_name(target.name + ".part")
            try:
                if client:
                    with part.open("wb") as out:
                        client.retrbinary("RETR " + source, out.write)
                    after = dict(client.mlsd(posixpath.dirname(source))).get(
                        posixpath.basename(source)
                    )
                    if not after or any(
                        meta.get(k) != after.get(k) for k in ("size", "modify")
                    ):
                        raise ValueError("전송 중 FTP 원본이 변경되었습니다.")
                else:
                    shutil.copyfile(incoming / rel, part)
                if part.stat().st_size != int(meta["size"]):
                    raise ValueError("수신 파일 크기가 다릅니다.")
                sha = digest(part)
                os.replace(part, target)
                store.db.execute(
                    "INSERT OR REPLACE INTO receipts VALUES (?,?,?,?,?)",
                    (identity, str(target), sha, target.stat().st_size, now()),
                )
                store.db.commit()
                downloaded += 1
                emit("download", f"자료 수신: {rel}", 100)
                output.append(target)
            finally:
                part.unlink(missing_ok=True)
        return {
            "files": [str(p) for p in output],
            "downloaded": downloaded,
            "skipped": skipped,
        }
    finally:
        if client:
            client.close()


def mkdir_remote(client, path):
    current = ""
    for name in path.strip("/").split("/"):
        current += "/" + name
        try:
            client.mkd(current)
        except ftplib.error_perm:
            previous = client.pwd()
            client.cwd(current)
            client.cwd(previous)


def publish(c, store, run_id, run_folder, emit=lambda *a: None):
    run_folder = Path(run_folder)
    required = set().union(*(REQUIRED[s] for s in ("convert", "statistics", "report")))
    if any(not checked_path(run_folder, name).is_file() for name in required):
        raise ValueError("업로드할 필수 최종 결과물이 없습니다.")
    sources = [run_folder / "conversion" / "conversion.json"]
    for directory in ("statistics", "report"):
        sources.extend(p for p in (run_folder / directory).rglob("*") if p.is_file() and p.suffix.lower() not in (".csv", ".parquet"))
    for p in sources:
        checked_path(run_folder, p.relative_to(run_folder).as_posix())
    files = [
        {
            "path": p.relative_to(run_folder).as_posix(),
            "size": p.stat().st_size,
            "sha256": digest(p),
        }
        for p in sources
    ]
    manifest = {"schema_version": 1, "run_id": run_id, "files": files}
    write_json(run_folder / "complete.json", manifest)
    client = connect(c) if c["transport"] == "ftp" else None
    try:
        if client:
            remote = posixpath.join(c["ftp"]["remote_output"], run_id)
            mkdir_remote(client, remote)
            for entry, p in zip(files, sources):
                destination = posixpath.join(remote, entry["path"])
                mkdir_remote(client, posixpath.dirname(destination))
                with p.open("rb") as f:
                    client.storbinary("STOR " + destination + ".part", f)
                if digest(p) != entry["sha256"]:
                    raise ValueError("업로드 중 로컬 결과물이 변경되었습니다.")
                client.voidcmd("TYPE I")
                if client.size(destination + ".part") != entry["size"]:
                    raise ValueError("업로드 파일 크기가 다릅니다.")
                client.rename(destination + ".part", destination)
                emit("upload", f"결과 업로드: {entry['path']}", 80)
            with (run_folder / "complete.json").open("rb") as f:
                client.storbinary("STOR " + remote + "/complete.json.part", f)
            client.voidcmd("TYPE I")
            if client.size(remote + "/complete.json.part") != (run_folder / "complete.json").stat().st_size:
                raise ValueError("완료 목록 업로드 크기가 다릅니다.")
            client.rename(remote + "/complete.json.part", remote + "/complete.json")
            destination = remote
        else:
            destination = store.root / "demo_remote" / "results" / run_id
            destination.mkdir(parents=True, exist_ok=True)
            for entry, p in zip(files, sources):
                out = destination / entry["path"]
                out.parent.mkdir(parents=True, exist_ok=True)
                part = out.with_name(out.name + ".part")
                try:
                    shutil.copyfile(p, part)
                    if digest(part) != entry["sha256"]:
                        raise ValueError("모의 전송 검증에 실패했습니다.")
                    os.replace(part, out)
                finally:
                    part.unlink(missing_ok=True)
            write_json(destination / "complete.json", manifest)
        identity = json.dumps(
            [
                c["transport"],
                c["ftp"]["host"],
                c["ftp"]["port"],
                c["ftp"]["remote_output"],
                run_id,
            ]
        )
        store.db.execute(
            "INSERT OR REPLACE INTO publications VALUES (?,?)", (identity, now())
        )
        store.db.commit()
        return {
            "destination": str(destination),
            "file_count": len(files),
            "manifest_sha256": digest(run_folder / "complete.json"),
        }
    finally:
        if client:
            client.close()
