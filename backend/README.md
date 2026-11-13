# Backend

FastAPI アプリ、インタビュー処理、LLM 接続、Local Whisper、SQLite を Python で実装しています。Python の依存関係は uv で管理します。

## 起動

    uv sync
    cp .env.example .env
    uv run main.py

ポートを指定する場合:

    uv run main.py --port 8111
    uv run main.py --host 0.0.0.0 --port 8111

ホストとポートは、起動引数、環境変数、api/config.yaml の順で優先されます。main.py に URL・HTTP メソッド・処理関数・機能名の対応をまとめています。

Vite 開発サーバーから接続する場合、ポート変更時は frontend/vite.config.ts の proxy 接続先も同じポートに変更してください。

Transformers の `AutoProcessor` / `AutoModelForMultimodalLM` を使い、`Qwen/Qwen3.6-27B` をローカルで直接実行します。別のサーバーは不要です。RTX 5090（32GB）で Whisper と併用するため、bitsandbytes の4bit NF4・二重量子化で重みを圧縮し、演算は BF16、配置は `cuda:0` に固定します。CPU へは自動退避しません。量子化は `llm/config.yaml` の `quantization` で設定でき、この項目を削除すると非量子化になりますが、27B の BF16 は32GBに収まりません。入力は最大8192トークン、生成は最大2048トークンです。CUDA が使えない場合や入力上限を超えた場合はエラーになります。

API 起動時に Qwen の短い生成と Whisper の無音認識・VAD 初期化を実行し、両方が完了してからリクエストを受け付けます。モデルはウォームアップと通常リクエストで共有し、プロセス終了まで常駐します。初回起動は公式モデル重み（約55GB）のダウンロードと量子化に時間がかかります。以後はダウンロードキャッシュを再利用しますが、プロセス再起動時は読み込み・量子化・ウォームアップを再実行します。起動時にモデルの準備が失敗した場合は API の起動も失敗させます。`/health` の `models.llm.ready` / `models.whisper.ready`、`/api/status` の `ready` で確認できます。Whisper 単独の `python -m whisper.main` も起動時にウォームアップします。

## 設定

各モジュールの `config.yaml` を編集し、バックエンドを再起動すると反映されます。既定値は従来の動作を維持しています。

| ファイル | 調整する値 |
| --- | --- |
| `llm/config.yaml` | モデル ID / ローカルパス、デバイス配置、精度・量子化、入力上限、thinking、生成上限・サンプリング |
| `whisper/config.yaml` | faster-whisper のモデル、デバイス、計算精度、VAD |
| `interview/config.yaml` | 履歴件数、終了判定、スコア加点、関連記憶の検索件数 |
| `db/config.yaml` | DB パス、接続待ち時間、記憶の取得件数 |
| `api/config.yaml` | `main.py` のホスト・ポート、ログイン有効日数 |

`docs`・`tests` やモデルの配布ファイルにはアプリの調整項目がないため設定ファイルを追加しません。プロンプト、抽出スキーマ、認証情報は YAML に含めません。

既存の `LOCAL_LLM_MODEL`、`LOCAL_LLM_MAX_NEW_TOKENS`、`FASTER_WHISPER_MODEL`、`FASTER_WHISPER_DEVICE`、`FASTER_WHISPER_COMPUTE_TYPE`、`DATABASE_PATH`、`AUDIOINTERVIEW_HOST`、`AUDIOINTERVIEW_PORT` は引き続き YAML より優先します。既存の `.env` に値がある場合、YAML で管理したい項目を `.env` から削除してください。

JSON 出力はスキーマをプロンプトに含めて要求し、応答を JSON として解析します。音声認識 API (`/api/speech/transcribe`、`/api/local/transcribe`) はどちらもローカルの faster-whisper を使用します。

SQLite DB の相対パスは `backend/` を基準に解決します。起動時に `db/migrations/` の SQL を適用します。

## モジュール

- api/: FastAPI ルート、認証、設定、静的フロント配信
- interview/: インタビュー状態、質問生成、縦断インタビュー
- llm/: ローカル Qwen クライアントとテキスト前処理
- whisper/: faster-whisper 音声認識
- db/: SQLite 接続、migration、参加者の縦断記憶

## テスト

backend/ で次を実行します。標準の unittest を利用します。

    uv run python -m unittest discover -s tests -v

認証・権限、セッション開始／投稿／編集／終了、音声アップロード、SQLite の保存・ロールバック、縦断記憶、インタビュー状態更新、Local LLM クライアントを検証します。DB はテストごとの一時ファイルを使い、開発用 .env は読み込みません。LLM の生成と Whisper 推論はモックを使うため、モデル取得や API キーは不要です。実際のモデルによる認識・生成品質は対象外です。

GPU 関連の依存関係をインストールせず実行する場合:

    uv run --no-project --with fastapi --with httpx --with python-dotenv --with python-multipart --with pyyaml --with uvicorn python -m unittest discover -s tests -v

フロントエンドの録音は `/api/speech/transcribe` へ送信されます。`rawText`、`normalizedText`、`maskedText`、`endOfTurn` を返し、末尾の「オーバー」等は回答から除きます。録音中の短い音声も同じ API で認識するため、音声認識はすべてサーバー側で実行されます。

RTX 5090 のドライバー570系に合わせ、uv は PyTorch / torchvision を公式の CUDA 12.8 配布元から取得します。`uv sync --locked` で反映してください。モデル設定に加え、GPUドライバーに対応したPyTorchが必要です。

faster-whisper 1.2.x と互換性を保つため、PyAV は19未満に固定しています。

2026-11-13 の RTX 5090 実測では、Qwen3.6-27B（4bit NF4）と Whisper-small（CUDA / FP16）の起動時ウォームアップ、API 経由の質問生成・JSON 情報抽出・音声認識が成功しました。両モデルを GPU 常駐させたウォームアップ直後は約18.2GiB、約7960トークン入力の短い要約後は約22.1GiBを使用しました（`nvidia-smi`。後者の生成上限は64トークン。PyTorch の予約領域も含み、負荷によって増減します）。通常の質問生成は約1.1秒、9.2秒の音声認識は約0.26秒、抽出と質問生成を含む回答投稿は約6.8秒でした。入力内容と出力長に依存する単発の測定値です。
