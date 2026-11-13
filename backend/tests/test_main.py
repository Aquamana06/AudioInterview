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
             patch.object(main.uvicorn, "run") as run:
            main.main(["--host", "0.0.0.0", "--port", "8111"])
        run.assert_called_once_with(main.app, host="0.0.0.0", port=8111)

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
