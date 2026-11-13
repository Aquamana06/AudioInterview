# Backend 要件

- FastAPI の JSON API と React/Vite の Web UI を提供する。
- 認証、アカウント管理、セッション、メッセージ、状態を SQLite に保存する。
- インタビューは日本語、英語、ドイツ語で進める。
- 初回はプロフィール形成、以降は現在の業務と関連する縦断記憶を使う。
- ターンごとに回答から業務情報を抽出し、FRAM coverage、深さ、イレギュラー対応、ラポール等の状態を更新する。
- LLM は Transformers でローカル Qwen を実行する。モデル名や生成パラメータは llm/config.yaml で設定する。
- 音声認識は faster-whisper をローカルで実行する。
- Web UI と API は Vite proxy を通じて開発時に同一 origin で使う。
- Python の依存関係と起動は uv で管理する。
