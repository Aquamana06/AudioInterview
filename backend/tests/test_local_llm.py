"""Run without downloading model weights: python3 -m unittest discover -s backend/tests."""

import asyncio
import importlib.util
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LocalLLMTests(unittest.TestCase):
    def setUp(self):
        self.settings = types.ModuleType('api.settings')
        self.settings.setting = lambda name, default='': os.getenv(name, default)
        self.modules = patch.dict(sys.modules, {
            'api.settings': self.settings,
        })
        self.modules.start()
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.modules.stop)
        self.addCleanup(self.env.stop)

    def test_local_configuration(self):
        client = load('client_under_test', 'llm/client.py')
        self.assertEqual(client.status()['provider'], 'local')
        self.assertTrue(client.configured())
        self.assertEqual(client.status()['textModel'], 'Qwen/Qwen3.5-9B')
        os.environ['LOCAL_LLM_MODEL'] = ''
        self.assertFalse(client.configured())

    def test_json_prompt_and_async_dispatch(self):
        client = load('client_under_test', 'llm/client.py')
        generate = MagicMock(return_value='{"answer": "ok"}')
        schema = {'type': 'object', 'properties': {'answer': {'type': 'string'}}}
        with patch.dict(sys.modules, {'llm.local_qwen': types.SimpleNamespace(generate=generate)}):
            result = asyncio.run(client.complete_json('質問', schema))
        self.assertEqual(result, {'answer': 'ok'})
        self.assertIn('"type": "object"', generate.call_args.args[0])
        self.assertEqual(generate.call_args.args[1], 'Qwen/Qwen3.5-9B')

    def test_cuda_is_required_for_gpu_configuration(self):
        local = load('qwen_under_test', 'llm/local_qwen.py')
        torch = MagicMock()
        torch.cuda.is_available.return_value = False
        with patch.dict(sys.modules, {'torch': torch, 'transformers': MagicMock()}):
            with self.assertRaisesRegex(RuntimeError, 'CUDA is required'):
                local.generate('質問', 'Qwen/Qwen3.5-9B')

    def test_input_token_limit_prevents_unbounded_gpu_memory_use(self):
        local = load('qwen_under_test', 'llm/local_qwen.py')
        local._model = MagicMock()
        local._model_id = 'Qwen/Qwen3.5-9B'
        local._processor = MagicMock()
        inputs = local._processor.apply_chat_template.return_value.to.return_value
        inputs.__getitem__.return_value.shape = (1, local.CONFIG['max_input_tokens'] + 1)
        with patch.dict(sys.modules, {'torch': MagicMock(), 'transformers': MagicMock()}):
            with self.assertRaisesRegex(ValueError, 'max_input_tokens'):
                local.generate('長い質問', local._model_id)
        local._model.generate.assert_not_called()

    def test_generation_caches_model_and_decodes_only_new_tokens(self):
        local = load('qwen_under_test', 'llm/local_qwen.py')
        processor = MagicMock()
        model = MagicMock()
        inputs = MagicMock()
        inputs.__getitem__.return_value.shape = (1, 3)
        processor.apply_chat_template.return_value.to.return_value = inputs
        model.generate.return_value = [[1, 2, 3, 4, 5]]
        processor.decode.return_value = ' 応答 '
        transformers = types.SimpleNamespace(
            AutoProcessor=MagicMock(), AutoModelForMultimodalLM=MagicMock(),
        )
        transformers.AutoProcessor.from_pretrained.return_value = processor
        transformers.AutoModelForMultimodalLM.from_pretrained.return_value = model
        with patch.dict(sys.modules, {'torch': MagicMock(), 'transformers': transformers}):
            self.assertEqual(local.generate('質問', 'Qwen/Qwen3.5-9B'), '応答')
            local.generate('次の質問', 'Qwen/Qwen3.5-9B')
            with self.assertRaises(RuntimeError):
                local.generate('質問', 'another-model')
        transformers.AutoModelForMultimodalLM.from_pretrained.assert_called_once_with(
            'Qwen/Qwen3.5-9B', device_map='cuda:0', dtype='bfloat16',
        )
        processor.decode.assert_called_with([4, 5], skip_special_tokens=True)
        self.assertFalse(processor.apply_chat_template.call_args.kwargs['enable_thinking'])
        self.assertEqual(model.generate.call_args.kwargs['max_new_tokens'], 2048)


if __name__ == '__main__':
    unittest.main()
