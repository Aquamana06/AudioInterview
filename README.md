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
# 既定ではローカル Qwen/Qwen3.6-27B（4bit）を使用
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

ブラウザで `http://127.0.0.1:5173` を開きます。LLM は既定で Transformers を使って `Qwen/Qwen3.6-27B` を4bit（NF4）で直接ローカル実行します。起動時に Qwen と Whisper を読み込み、ウォームアップ完了後に API の受付を開始します。以後は両モデルを同じプロセス内に常駐させます。初回起動は公式モデル重みのダウンロード（約55GB）と量子化に時間がかかるため、十分な GPU / RAM と保存容量が必要です。`backend/llm/config.yaml` でモデル ID またはローカルパス、量子化を指定できます。Whisper のモデル、デバイス、計算精度は `backend/whisper/config.yaml` で指定できます。`/health` の `models` と `/api/status` の `ready` でウォームアップ状態を確認できます。

## 既存コマンド

```bash
cd frontend
npm run lint
npm run build
```

データベースの migration SQL は `backend/db/migrations/` にあります。

対象者へ配布する [操作マニュアルPDF](frontend/public/manual/interview-manual.pdf) と [依頼文・マニュアルの更新方法](docs/operation-manual/README.md) を用意しています。サイト内では初回インタビューの前に表示し、その後は「設定・履歴」の横の「操作マニュアル」から参照できます。

回答音声と音声パスを保存し、インタビュー終了時に会話JSONを `backend/instance/interviews/` へ自動保存します。参照・JSON出力・音声付き取り出し・DBバックアップのコマンドは [データ保存・取り出しのREADME](docs/data-storage/README.md) を参照してください。
