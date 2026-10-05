"""로컬 FTP 서버와 실제 제어·데이터 연결로 검증한다. FTPS는 별도 검증 대상."""

import logging
import tempfile
import threading
import unittest
from pathlib import Path
import os
import ftplib
from unittest.mock import patch
from CODE_Controller.cleanup import cleanup
from CODE_Common.io import load_config, read_json, write_json, ROOT, digest
from CODE_Common.store import Store
from CODE_Demo_Data.generate import generate
from CODE_Controller.pipeline import pipeline

try:
    from pyftpdlib.authorizers import DummyAuthorizer
    from pyftpdlib.handlers import FTPHandler
    from pyftpdlib.servers import FTPServer
    from pyftpdlib.log import config_logging
except ImportError:
    FTPServer = None


@unittest.skipIf(FTPServer is None, "선택 검증 패키지 pyftpdlib 미설치")
class FTPIntegrationTests(unittest.TestCase):
    def test_real_ftp_receive_publish_and_skip(self):
        config_logging(level=logging.CRITICAL)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            remote = root / "remote"
            generate(remote / "incoming", parts=12, tests=8)
            auth = DummyAuthorizer()
            auth.add_user(
                "atlas-test", "local-test-only", str(remote), perm="elradfmwMT"
            )

            class Handler(FTPHandler):
                pass

            Handler.authorizer = auth
            server = FTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(
                target=lambda: server.serve_forever(timeout=0.05, handle_exit=False),
                daemon=True,
            )
            thread.start()
            before = {
                k: os.environ.get(k) for k in ("ATLAS_FTP_USER", "ATLAS_FTP_PASSWORD")
            }
            os.environ["ATLAS_FTP_USER"] = "atlas-test"
            os.environ["ATLAS_FTP_PASSWORD"] = "local-test-only"
            store = None
            try:
                c = read_json(ROOT / "config.json")
                c["transport"] = "ftp"
                c["ftp"].update(
                    host="127.0.0.1",
                    port=server.socket.getsockname()[1],
                    remote_input="/incoming",
                    remote_output="/results",
                )
                path = root / "config.json"
                write_json(path, c)
                c = load_config(path)
                store = Store(c["_workspace"])
                result = pipeline(store, c, lambda *a: None)
                self.assertEqual(result["failed"], [])
                self.assertEqual(len(result["completed"]), 1)
                run = result["completed"][0]
                manifest = read_json(remote / "results" / run / "complete.json")
                for f in manifest["files"]:
                    self.assertEqual(
                        digest(remote / "results" / run / f["path"]), f["sha256"]
                    )
                again = pipeline(store, c, lambda *a: None)
                self.assertEqual(again["receipt"]["skipped"], 1)
                self.assertEqual(again["completed"], [])
                c["histogram_bins"] += 1
                actual_store = ftplib.FTP.storbinary
                def interrupt(client, command, stream, *args, **kwargs):
                    actual_store(client, command, stream, *args, **kwargs)
                    raise OSError("시험용 전송 중단")
                with patch.object(ftplib.FTP, "storbinary", interrupt):
                    failed = pipeline(store, c, lambda *a: None)
                self.assertEqual(len(failed["failed"]), 1)
                retry_id = failed["failed"][0]
                self.assertFalse((remote / "results" / retry_id / "complete.json").exists())
                self.assertNotIn(retry_id, cleanup(store, 0)["removed_runs"])
                retried = pipeline(store, c, lambda *a: None)
                self.assertEqual(retried["completed"], [retry_id])
                self.assertEqual(retried["failed"], [])
                self.assertTrue((remote / "results" / retry_id / "complete.json").exists())
            finally:
                if store:
                    store.close()
                server.close_all()
                thread.join(timeout=2)
                for k, v in before.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v


if __name__ == "__main__":
    unittest.main()
