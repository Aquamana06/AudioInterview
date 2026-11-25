import contextlib
import io
import os
import unittest
from unittest.mock import patch

import backend_test_support
import main


class EntrypointTests(unittest.TestCase):
    def test_cli_overrides_environment_and_passes_port_as_integer(self):
        with patch.dict(os.environ, {"AUDIOINTERVIEW_HOST": "127.0.0.2", "AUDIOINTERVIEW_PORT": "8001"}), \
             patch.object(main, "_port_is_listening", return_value=False), \
             patch.object(main.uvicorn, "run") as run:
            main.main(["--host", "0.0.0.0", "--port", "8111"])
        run.assert_called_once_with(main.app, host="0.0.0.0", port=8111)

    def test_occupied_port_stops_before_models_are_loaded(self):
        output = io.StringIO()
        with patch.object(main, "_port_is_listening", return_value=True), \
             patch.object(main.uvicorn, "run") as run, contextlib.redirect_stderr(output):
            with self.assertRaises(SystemExit) as error:
                main.main(["--port", "8000"])
        self.assertEqual(error.exception.code, 1)
        self.assertIn("既に使用されています", output.getvalue())
        run.assert_not_called()

    def test_wildcard_hosts_check_the_local_interface(self):
        for host, target in (("0.0.0.0", "127.0.0.1"), ("::", "::1"), ("localhost", "localhost")):
            with self.subTest(host=host), patch.object(main.socket, "create_connection") as connect:
                self.assertTrue(main._port_is_listening(host, 8000))
                connect.assert_called_once_with((target, 8000), timeout=1)

    def test_refused_connection_allows_server_start(self):
        with patch.object(main.socket, "create_connection", side_effect=ConnectionRefusedError):
            self.assertFalse(main._port_is_listening("127.0.0.1", 8000))

    def test_environment_overrides_yaml_defaults(self):
        with patch.dict(os.environ, {"AUDIOINTERVIEW_PORT": "8112"}):
            self.assertEqual(main.parse_args([]).port, 8112)
        with patch.dict(os.environ, {}, clear=True):
            args = main.parse_args([])
        self.assertEqual(args.port, main.load_config("api")["server"]["port"])
        self.assertEqual(args.host, main.load_config("api")["server"]["host"])

    def test_invalid_port_is_rejected_before_server_start(self):
        for port in ("invalid", "0", "65536"):
            with self.subTest(port=port), contextlib.redirect_stderr(io.StringIO()), \
                 patch.object(main.uvicorn, "run") as run:
                with self.assertRaises(SystemExit) as error:
                    main.main(["--port", port])
                self.assertEqual(error.exception.code, 2)
                run.assert_not_called()


class StartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_models_are_warmed_before_startup_completes(self):
        events = []
        with patch.object(main, 'initialize_database'), patch.object(main, 'ensure_admin'), \
             patch.object(main, 'configured', return_value=True), \
             patch.object(main, 'llm_model', return_value='test/model'), \
             patch.object(main, 'warmup_qwen', side_effect=lambda _: events.append('qwen')), \
             patch.object(main.routes.local_whisper, 'warmup', side_effect=lambda: events.append('whisper')):
            async with main.lifespan(main.app):
                self.assertEqual(events, ['qwen', 'whisper'])

    async def test_failed_warmup_prevents_serving_requests(self):
        with patch.object(main, 'initialize_database'), patch.object(main, 'ensure_admin'), \
             patch.object(main, 'configured', return_value=True), \
             patch.object(main, 'warmup_qwen', side_effect=RuntimeError('out of memory')):
            with self.assertRaisesRegex(RuntimeError, 'out of memory'):
                async with main.lifespan(main.app):
                    self.fail('Startup must not complete after failed model initialization')
