"""Preparación limpia con ZIP y red ficticios; nunca descarga modelos reales."""

import hashlib
import io
import json
import os
import stat
import tempfile
import unittest
import zipfile
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.error import URLError

from seguros import bootstrap as b


class Response(io.BytesIO):
    def geturl(self):
        return b.ARCHIVE_URL


def fixture_zip(entries=None):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, content in entries or [("ollama.exe", b"fixture: nunca ejecutar"), ("lib/lectura.txt", b"fixture")]:
            archive.writestr(name, content)
    return stream.getvalue()


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.archive = fixture_zip()
        self.server = False
        self.model = False
        self.events = []
        self.network_failure = None
        self.pull_lines = [{"status": "pulling fixture", "total": 100, "completed": 100}, {"status": "success"}]
        self.process = Mock(pid=22222)
        self.process.poll.return_value = None

    def network(self, request, timeout=0):
        url = request.full_url
        if url == b.ARCHIVE_URL:
            self.events.append("download")
            if self.network_failure:
                return self.network_failure
            return Response(self.archive)
        endpoint = url.split("/api/")[-1]
        self.events.append(endpoint)
        if endpoint == "version":
            if not self.server:
                raise URLError(ConnectionRefusedError(10061, "fixture: conexión rechazada"))
            result = {"version": "fixture"}
        elif endpoint == "tags":
            result = {"models": [{"name": "qwen2.5:7b"}] if self.model else []}
        elif endpoint == "pull":
            self.model = True
            return Response(b"".join((json.dumps(line) + "\n").encode() for line in self.pull_lines))
        elif endpoint == "generate":
            payload = json.loads(request.data)
            self.assertEqual(payload["prompt"], "")
            self.assertEqual(timeout, 300)
            result = {"done": True, "done_reason": "load"}
        else:
            raise AssertionError("Endpoint no previsto: " + endpoint)
        return Response(json.dumps(result).encode())

    def popen(self, args, **kwargs):
        self.assertTrue(Path(args[0]).is_file())
        self.assertEqual(Path(args[0]).read_bytes(), b"fixture: nunca ejecutar")
        self.assertEqual(args[1], "serve")
        self.assertEqual(kwargs["env"]["OLLAMA_MODELS"], str(self.root / ".runtime/models"))
        self.assertEqual(kwargs["env"]["USERPROFILE"], str(self.root / ".runtime/ollama-home"))
        self.assertEqual(kwargs["env"]["OLLAMA_NO_CLOUD"], "1")
        self.assertEqual(kwargs["creationflags"], 0x08000000)
        self.assertEqual(kwargs["startupinfo"].wShowWindow, 0)
        self.events.append("start")
        self.server = True
        return self.process

    def environment(self):
        stack = ExitStack()
        stack.enter_context(patch.dict(os.environ, {"USERPROFILE": str(self.root / "perfil")}, clear=True))
        stack.enter_context(patch.object(b.sys, "platform", "win32"))
        stack.enter_context(patch.object(b.platform, "machine", return_value="AMD64"))
        stack.enter_context(patch.object(b, "ARCHIVE_SHA256", hashlib.sha256(self.archive).hexdigest()))
        stack.enter_context(patch.object(b, "ARCHIVE_BYTES", len(self.archive)))
        stack.enter_context(patch.object(b, "urlopen", side_effect=self.network))
        stack.enter_context(patch.object(b.shutil, "which", return_value=None))
        stack.enter_context(patch.object(b.shutil, "disk_usage", return_value=SimpleNamespace(free=30 * b.GIB)))
        stack.enter_context(patch.object(b.subprocess, "Popen", side_effect=self.popen))
        stack.enter_context(patch.object(b.subprocess, "STARTUPINFO", side_effect=lambda: SimpleNamespace(dwFlags=0), create=True))
        stack.enter_context(patch.object(b.subprocess, "STARTF_USESHOWWINDOW", 1, create=True))
        stack.enter_context(patch.object(b.subprocess, "SW_HIDE", 0, create=True))
        stack.enter_context(patch.object(b.subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True))
        return stack

    def prepare(self, **kwargs):
        return b.ensure_ollama(root=self.root, progress=lambda _: None, **kwargs)

    def test_clean_setup_verifies_extracts_starts_pulls_and_warms_in_order(self):
        with self.environment():
            result = self.prepare()
            self.assertTrue(result["runtime_descargado"])
            self.assertTrue(result["servidor_iniciado"])
            self.assertTrue(result["modelo_descargado"])
            self.assertTrue(result["preparado"])
            self.assertLess(self.events.index("download"), self.events.index("start"))
            self.assertLess(self.events.index("start"), self.events.index("pull"))
            self.assertLess(self.events.index("pull"), self.events.index("generate"))
            self.assertFalse((self.root / ".runtime/setup.lock").exists())
            self.assertTrue((self.root / ".runtime/instalacion.json").is_file())
            self.assertFalse(list((self.root / ".runtime").glob("*.zip*")))
            self.assertNotIn("OLLAMA_MODELS", os.environ)

    def test_second_setup_reuses_server_and_model_without_download_pull_or_start(self):
        with self.environment():
            self.prepare()
            self.events.clear()
            result = self.prepare()
            self.assertEqual(self.events, ["version", "version", "tags", "generate"])
            self.assertFalse(result["runtime_descargado"])
            self.assertFalse(result["modelo_descargado"])
            self.assertFalse(result["servidor_iniciado"])

    def test_existing_binary_is_reused_without_reinstalling(self):
        installed = self.root / ".runtime/ollama/ollama.exe"
        installed.parent.mkdir(parents=True)
        installed.write_bytes(b"fixture: nunca ejecutar")
        with self.environment():
            result = self.prepare()
        self.assertFalse(result["runtime_descargado"])
        self.assertNotIn("download", self.events)
        self.assertIn("start", self.events)

    def test_hash_mismatch_never_starts_binary_or_marks_installation(self):
        with self.environment(), patch.object(b, "ARCHIVE_SHA256", "0" * 64):
            with self.assertRaisesRegex(b.SetupError, "SHA256"):
                self.prepare()
        self.assertNotIn("start", self.events)
        self.assertFalse((self.root / ".runtime/ollama").exists())
        self.assertFalse((self.root / ".runtime/instalacion.json").exists())
        self.assertFalse(list((self.root / ".runtime").glob("*.part")))

    def test_partial_download_error_removes_partial_and_does_not_execute(self):
        class BrokenResponse(Response):
            def read(self, count=-1):
                raise OSError("fixture: transferencia interrumpida")
        self.network_failure = BrokenResponse(b"")
        with self.environment():
            with self.assertRaises(b.SetupError):
                self.prepare()
        self.assertFalse(list((self.root / ".runtime").glob("*.part")))
        self.assertNotIn("start", self.events)

    def test_zip_slip_rejected_before_extracting_any_entry(self):
        archive = self.root / "bad.zip"
        archive.write_bytes(fixture_zip([("normal.txt", b"safe"), ("../escape.txt", b"bad")]))
        target = self.root / "target"
        target.mkdir()
        with self.assertRaisesRegex(b.SetupError, "inseguro"):
            b._safe_extract(archive, target)
        self.assertFalse(list(target.iterdir()))
        self.assertFalse((self.root / "escape.txt").exists())

    def test_symbolic_link_in_zip_is_rejected(self):
        archive = self.root / "bad.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            entry = zipfile.ZipInfo("link")
            entry.create_system = 3
            entry.external_attr = (stat.S_IFLNK | 0o777) << 16
            bundle.writestr(entry, "../../outside")
        target = self.root / "target"
        target.mkdir()
        with self.assertRaises(b.SetupError):
            b._safe_extract(archive, target)

    def test_failed_model_pull_is_not_successful_and_does_not_warm(self):
        self.pull_lines = [{"error": "fixture: modelo no disponible"}]
        with self.environment():
            with self.assertRaisesRegex(b.SetupError, "modelo no disponible"):
                self.prepare()
        self.assertNotIn("generate", self.events)

    def test_missing_pull_success_is_not_accepted(self):
        self.pull_lines = [{"status": "downloading", "completed": 10, "total": 100}]
        with self.environment():
            with self.assertRaisesRegex(b.SetupError, "sin confirmar"):
                self.prepare()
        self.assertNotIn("generate", self.events)

    def test_permission_error_is_not_mistaken_for_missing_server(self):
        with self.environment(), patch.object(b, "urlopen", side_effect=URLError(PermissionError(10013, "fixture"))):
            with self.assertRaisesRegex(b.SetupError, "permisos"):
                self.prepare()
        self.assertFalse((self.root / ".runtime").exists())
        self.assertNotIn("download", self.events)
        self.assertNotIn("start", self.events)

    def test_unsupported_system_requires_existing_server(self):
        with self.environment(), patch.object(b.sys, "platform", "linux"):
            with self.assertRaisesRegex(b.SetupError, "Windows x64"):
                self.prepare()
        self.assertNotIn("download", self.events)

    def test_other_os_can_reuse_server_model_and_skip_warmup(self):
        self.server, self.model = True, True
        with self.environment(), patch.object(b.sys, "platform", "linux"):
            result = self.prepare(prepare=False)
        self.assertFalse(result["preparado"])
        self.assertNotIn("download", self.events)
        self.assertNotIn("generate", self.events)

    def test_startup_failure_terminates_only_the_process_started_here(self):
        with self.environment(), patch.object(b, "_wait_ready", side_effect=b.SetupError("fixture: no inició")):
            with self.assertRaises(b.SetupError):
                self.prepare()
        self.process.terminate.assert_called_once()
        self.assertFalse((self.root / ".runtime/server.pid").exists())

    def test_local_url_without_explicit_port_uses_http_port_eighty(self):
        with self.environment():
            self.prepare(base_url="http://localhost")
            call = b.subprocess.Popen.call_args
            self.assertEqual(call.kwargs["env"]["OLLAMA_HOST"], "127.0.0.1:80")

    def test_insufficient_extraction_space_does_not_extract(self):
        archive = self.root / "file.zip"
        archive.write_bytes(self.archive)
        target = self.root / "target"
        target.mkdir()
        with patch.object(b.shutil, "disk_usage", return_value=SimpleNamespace(free=0)):
            with self.assertRaisesRegex(b.SetupError, "espacio"):
                b._safe_extract(archive, target)
        self.assertFalse(list(target.iterdir()))

    def test_existing_setup_lock_prevents_second_installer(self):
        runtime = self.root / ".runtime"
        with b._setup_lock(runtime, lambda _: None):
            with self.assertRaisesRegex(b.SetupError, "Otra preparación"):
                with b._setup_lock(runtime, lambda _: None, timeout=0):
                    self.fail("No debe adquirir el segundo lock")

    def test_model_names_normalize_default_tag_without_download(self):
        self.assertTrue(b._has_model({"models": [{"name": "registry.ollama.ai/library/fixture:latest"}]}, "fixture"))


if __name__ == "__main__":
    unittest.main()
