"""Test fixtures: temporary SQLite and a stub at the native Whisper boundary."""

import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class WhisperStub:
    def __init__(self, model_name, device="auto", compute_type="auto"):
        self.model_name = model_name
        self.device = "cpu"
        self.compute_type = "int8"
        self.transcribe = MagicMock(side_effect=AssertionError("Unexpected Whisper inference"))
        self.warmup = MagicMock()
        self.ready = False


whisper_module = types.ModuleType("whisper.transcription.local_whisper")
whisper_module.LocalWhisper = WhisperStub
# Import the real application without reading developer secrets or native ML libraries.
module_name = "whisper.transcription.local_whisper"
previous_module = sys.modules.get(module_name)
sys.modules[module_name] = whisper_module
try:
    with patch("dotenv.load_dotenv"):
        from main import app
        from db.database import database, initialize_database
        from api.auth import ensure_admin
finally:
    if previous_module is None:
        sys.modules.pop(module_name, None)
    else:
        sys.modules[module_name] = previous_module


class DatabaseTestCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        environment = patch.dict(os.environ, {
            "DATABASE_PATH": str(Path(temporary.name) / "test.sqlite3"),
            "LOCAL_LLM_MODEL": "",
        })
        environment.start()
        self.addCleanup(environment.stop)
        initialize_database()
        ensure_admin()

    def add_session(self, session_id="interview_test", account_id="admin"):
        with database() as connection:
            connection.execute(
                "INSERT INTO interview_sessions (id, account_id, title) VALUES (?, ?, ?)",
                (session_id, account_id, "Test interview"),
            )
        return session_id


def irregular_evidence(level=3):
    """Evidence fixture for an exception, its direct reason, and its deeper background."""
    return {
        "irregular_situations": ["会計中にレジが停止した"] if level >= 1 else [],
        "irregular_responses": ["レジ停止時は責任者に対応を依頼する"] if level >= 1 else [],
        "irregular_reasons": ["誤った会計でお客さんに不利益を与えないため"] if level >= 2 else [],
        "irregular_deeper_reasons": ["過去の誤会計の経験から、お客さんとの信頼を守ることを重視する"] if level >= 3 else [],
    }
