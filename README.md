# AudioInterview

リアルタイム音声・テキスト対応のインタビューシステムです。アプリは UI とバックエンドの責務ごとに分割しています。

```text
frontend/                 React/Vite の Web UI
backend/api/              FastAPI の HTTP API
backend/interview/        Python のインタビュー進行ロジック
backend/llm/              Python のローカル Qwen 接続
backend/whisper/          Local Whisper 音声認識 API
backend/db/               SQLite アクセスと migration
data/                     入力データ・素材
analyze/                  データ分析スクリプト
```

## 開発

### Python API

```bash
cd backend
uv sync
cp .env.example .env
# 既定ではローカル Qwen/Qwen3.5-9B を使用
uv run main.py
```

初期 admin アカウントは `admin` / `admin` です。DB は既定で `backend/instance/audiointerview.sqlite3` に作成されます。

### Web UI

別のターミナルでフロントエンドを起動します。

```bash
cd frontend
npm install
npm run dev
```

ブラウザで `http://127.0.0.1:5173` を開きます。LLM は既定で Transformers を使って `Qwen/Qwen3.5-9B` を直接ローカル実行します。初回生成時にモデルをダウンロードするため、十分な GPU / RAM と保存容量が必要です。`backend/llm/config.yaml` でモデル ID またはローカルパスを指定できます。Whisper のモデル、デバイス、計算精度は `backend/whisper/config.yaml` で指定できます。

## 既存コマンド

```bash
cd frontend
npm run lint
npm run build
```

データベースの migration SQL は `backend/db/migrations/` にあります。
