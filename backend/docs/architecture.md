# AudioInterview アーキテクチャ

flowchart LR
  browser[React + Vite] -->|/api| api[FastAPI]
  browser -->|モデルファイル| api
  api --> interview[Interview engine]
  api --> llm[LLM provider]
  api --> whisper[Local faster-whisper]
  api --> db[(SQLite)]

- 開発時は Vite が /api を FastAPI に proxy します。
- Python API は認証、セッション、管理機能、LLM の呼び出しを担当します。
- LLM は llm/config.yaml で指定した Qwen を Transformers でローカル実行します。
- 音声認識はバックエンドの faster-whisper を使います。フロントエンドは録音を /api/speech/transcribe へ送信し、認識・専門用語補正・マスキング結果を受け取ります。
- セッション、メッセージ、参加者プロフィール、縦断記憶は SQLite に保存します。
- 本番では frontend/dist が存在すれば FastAPI が SPA として配信します。
