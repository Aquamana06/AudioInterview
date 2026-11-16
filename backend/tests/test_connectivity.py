"""Exercise real routing, agents, algorithms and SQLite; stub only model inference."""

import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend_test_support import DatabaseTestCase, app
from db.memory import load_participant_memory
from interview.agent import _history_text, empty_extraction
from interview.profile_agent import PROFILE_FIELDS


def model_response(prompt, model_id):
    if '"profile_patch"' in prompt:
        return json.dumps({
            'summary': '設備 点検を担当',
            'profile_patch': {'role': '設備担当', 'typical_day': ['設備 点検']},
            'nodes': [{'key': 'inspection', 'kind': 'practice', 'text': '設備 点検', 'confidence': 0.9}],
            'edges': [],
        }, ensure_ascii=False)
    if '"position_or_seniority"' in prompt:
        return json.dumps({**{key: [] for key in PROFILE_FIELDS}, 'role': ['設備担当'], 'wants_to_stop': False}, ensure_ascii=False)
    if '"target_work"' in prompt:
        return json.dumps({**empty_extraction(), 'target_work': '設備 点検', 'practices': ['温度を確認'],
                           'fram_input': ['設備'], 'reasons': ['安全のため']}, ensure_ascii=False)
    return '普段の設備点検について教えてください。'


class ConnectivityTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = self.enterContext(TestClient(app))
        self.enterContext(patch.dict('os.environ', {'LOCAL_LLM_MODEL': 'test/local-qwen'}))
        self.generate = self.enterContext(patch('llm.local_qwen.generate', side_effect=model_response))

    def request(self, method, path, **kwargs):
        response = self.client.request(method, '/api' + path, **kwargs)
        self.assertLess(response.status_code, 400, response.text)
        return response.json()

    def test_operator_profile_memory_and_followup_agent(self):
        logs = self.enterContext(self.assertLogs("audiointerview", level="INFO"))
        self.request('POST', '/auth/login', json={'id': 'admin', 'password': 'admin'})
        issued = self.request('POST', '/admin/accounts', json={'id': 'integration_operator', 'displayName': '接続確認'})
        self.request('POST', '/auth/logout')
        self.request('POST', '/auth/login', json={'qrToken': issued['qrToken']})
        self.assertEqual(self.request('GET', '/me')['account']['id'], issued['id'])
        first = self.request('POST', '/sessions', json={'language': 'ja'})['session']['id']
        self.request('POST', f'/sessions/{first}/start')
        with patch('api.routes.local_whisper.transcribe', return_value='設備 点検'):
            speech = self.request('POST', '/speech/transcribe', files={'audio': ('sample.webm', b'audio', 'audio/webm')}, data={'language': 'ja'})
        result = self.request('POST', f'/sessions/{first}/messages', json={'maskedText': speech['maskedText'], 'inputMode': 'voice'})
        self.assertEqual(result['state']['turn_count'], 1)
        self.assertIn('初回プロフィール/role: 設備担当', result['state']['persona_notes'])
        self.assertEqual(result['messages'][1]['inputMode'], 'voice')
        self.request('POST', f'/sessions/{first}/end')
        memory = load_participant_memory(issued['id'])
        self.assertEqual(memory['profile']['role'], '設備担当')
        self.assertEqual(memory['nodes'][0]['text'], '設備 点検')
        second = self.request('POST', '/sessions', json={'language': 'ja'})['session']['id']
        self.request('POST', f'/sessions/{second}/start')
        result = self.request('POST', f'/sessions/{second}/messages', json={'maskedText': '設備', 'inputMode': 'text'})
        self.assertEqual(result['state']['target_work'], '設備 点検')
        self.assertEqual(result['state']['task_depth'], 3)
        self.assertGreater(result['state']['task_coverage'], 0)
        self.assertTrue(any('過去セッションからの参照情報' in call.args[0] and '設備担当' in call.args[0] for call in self.generate.call_args_list))
        self.assertEqual(self.request('GET', f'/sessions/{second}')['state'], result['state'])
        self.assertGreaterEqual(self.generate.call_count, 7)
        events = [json.loads(record.getMessage().split("[interview] ", 1)[1]) for record in logs.records]
        saved_memory = next(event for event in events if event["event"] == "memory_saved")
        self.assertEqual(saved_memory["session_id"], first)
        self.assertEqual(saved_memory["summary"], memory["recent_summaries"][0]["summary"])
        self.assertEqual(saved_memory["nodes"][0]["text"], memory["nodes"][0]["text"])
        turn = next(event for event in events if event["event"] == "turn_completed" and event["session_id"] == second)
        self.assertEqual(turn["state"], result["state"])
        self.assertTrue(turn["guide"]["guidance"])
        self.assertEqual(turn["extracted"]["fram_input"], ["設備"])
        reference = next(event for event in events if event["event"] == "memory_referenced")
        self.assertEqual(reference["memory"]["summaries"][0]["summary"], saved_memory["summary"])

    def test_memory_context_survives_long_history(self):
        context = {'context': True, 'role': 'system', 'content': '【過去セッションからの参照情報】設備担当'}
        history = [context] + [{'role': 'user', 'content': f'回答{i}'} for i in range(35)]
        self.assertIn(context['content'], _history_text(history))
        self.assertNotIn('user: 回答0\n', _history_text(history))

    def test_explicit_end_returns_ended_state_label(self):
        self.request('POST', '/auth/login', json={'id': 'admin', 'password': 'admin'})
        session_id = self.request('POST', '/sessions', json={})['session']['id']
        self.request('POST', f'/sessions/{session_id}/start')
        result = self.request('POST', f'/sessions/{session_id}/end')
        self.assertEqual(result['stateLabel'], 'end')
        self.assertEqual(self.request('GET', f'/sessions/{session_id}')['stateLabel'], 'end')
