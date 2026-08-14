# AudioInterview

ローカル音声認識、専門用語補正、Semantic Masking、GPT-5のインタビューロジック、Cloudflare D1、ブラウザ標準の音声読み上げを組み合わせた音声インタビューシステムです。ID/QR認証、管理者画面、多言語セッション、テキスト・ハンズフリー音声入力、履歴編集と再生成に対応します。

## Local Backend

GPUでfaster-whisper large-v3を使う場合:

```sh
uv sync --extra gpu
FASTER_WHISPER_DEVICE=cuda FASTER_WHISPER_COMPUTE_TYPE=float16 uv run audiointerview-local-backend
```

CPUで確認する場合:

```sh
FASTER_WHISPER_DEVICE=cpu FASTER_WHISPER_COMPUTE_TYPE=int8 uv run audiointerview-local-backend
```

ローカルバックエンドは `http://127.0.0.1:8000` で起動し、以下を提供します。

- `GET /health`: GPU・モデル・秘匿処理状態
- `POST /transcribe`: faster-whisper + VAD、Technical Normalizer、Semantic Masking
- `POST /mask-text`: テキスト入力のTechnical Normalizer、Semantic Masking

## Frontend / Worker

`.dev.vars` に少なくとも以下を設定します。

```sh
OPENAI_API_KEY=sk-...
OPENAI_TEXT_MODEL=gpt-5.5
LOCAL_INTERVIEW_BACKEND_URL=http://127.0.0.1:8000
```

起動:

```sh
npm install
npx wrangler d1 migrations apply RI_db --local
npm run dev
```

読み上げにはブラウザ標準の音声合成を使います。各端末への音声エンジンの導入や常駐、読み上げAPIの設定は不要です。画面上で端末が提供する声と読み上げ速度を変更できます。

アプリは `http://localhost:5173/` で開きます。初期管理者は `admin` / `admin` です。

ブラウザ側はRaw Transcriptと専門用語補正後テキストだけを表示します。`<TANK_A>` などのSemantic Masking placeholderと対応辞書はローカル処理境界内に留め、Worker・D1・GPTへはマスク済みテキストのみ送信します。

## Local Dictionaries

- Hotwords: `local_backend/config/hotwords.json`
- Technical Normalizer / Semantic Masking source: `local_backend/config/terminology.json`
- Placeholder category policy: `local_backend/config/masking_policy.json`
- GPT出力のplaceholder除去: `worker/privacy/maskingPolicy.ts`

辞書が存在しない場合、ローカルバックエンドは起動時にfail-fastします。
