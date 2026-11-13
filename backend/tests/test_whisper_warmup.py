import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch


class WhisperWarmupTests(unittest.TestCase):
    def test_warmup_consumes_inference_and_initializes_vad_once(self):
        events = []

        def segments():
            events.append('inference')
            yield MagicMock(text='')

        spec = importlib.util.spec_from_file_location(
            'whisper.transcription.warmup_under_test',
            Path(__file__).resolve().parents[1] / 'whisper/transcription/local_whisper.py',
        )
        module = importlib.util.module_from_spec(spec)
        vad = MagicMock()
        with patch.dict(sys.modules, {
            'ctranslate2': MagicMock(), 'faster_whisper': MagicMock(),
            'faster_whisper.vad': vad, 'numpy': MagicMock(),
        }):
            spec.loader.exec_module(module)
            whisper = module.LocalWhisper('small', device='cpu', compute_type='int8')
            model = whisper._model = MagicMock()
            model.transcribe.return_value = (segments(), MagicMock())
            whisper.warmup()
            whisper.warmup()
        self.assertEqual(events, ['inference'])
        model.transcribe.assert_called_once()
        self.assertFalse(model.transcribe.call_args.kwargs['vad_filter'])
        vad.get_speech_timestamps.assert_called_once()
        self.assertIs(whisper.model, model)
