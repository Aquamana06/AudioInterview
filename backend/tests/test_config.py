"""Configuration loading and behavior when tuning selected parameters."""

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config


class ConfigTests(unittest.TestCase):
    def test_reads_yaml_from_module_directory_and_rejects_non_mapping(self):
        with tempfile.TemporaryDirectory() as temporary:
            module = Path(temporary) / 'example'
            module.mkdir()
            path = module / 'config.yaml'
            path.write_text('model: custom/model\ngeneration:\n  temperature: 0.2\n', encoding='utf-8')
            with patch.object(config, 'CONFIG_ROOT', Path(temporary)):
                config.load_config.cache_clear()
                self.addCleanup(config.load_config.cache_clear)
                self.assertEqual(config.load_config('example')['generation']['temperature'], 0.2)
                path.write_text('- invalid\n', encoding='utf-8')
                config.load_config.cache_clear()
                with self.assertRaisesRegex(ValueError, 'YAML mapping'):
                    config.load_config('example')

    def test_retrieval_uses_configured_item_limit(self):
        import backend_test_support
        from interview import longitudinal
        memory = {'nodes': [{'id': str(i), 'text': '点検', 'confidence': 1} for i in range(4)]}
        with patch.dict(longitudinal.CONFIG, {'items': 1}):
            self.assertEqual(len(longitudinal.select_relevant(memory, '点検')['nodes']), 1)
            self.assertEqual(len(longitudinal.select_relevant(memory, '点検', limit=2)['nodes']), 2)

    def test_yaml_defaults_and_environment_override(self):
        import backend_test_support
        from api.settings import database_path
        import os
        with patch.dict(config.load_config('db')['database'], {'path': 'instance/custom.sqlite3'}), \
             patch.dict(os.environ, {}, clear=True):
            self.assertEqual(database_path(), config.CONFIG_ROOT / 'instance/custom.sqlite3')
            os.environ['DATABASE_PATH'] = '/tmp/override.sqlite3'
            self.assertEqual(database_path(), Path('/tmp/override.sqlite3'))
