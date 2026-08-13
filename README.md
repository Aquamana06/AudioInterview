# AudioInterview

リアルタイム音声・テキスト対応のインタビューシステムです。実アプリは `audiointerview/` 配下にあります。

## ローカルでの動かし方

### 1. アプリディレクトリへ移動

```bash
cd audiointerview
```

### 2. 依存関係をインストール

```bash
npm install
```

### 3. 環境変数を設定

```bash
cp .dev.vars.example .dev.vars
```

`.dev.vars` の `OPENAI_API_KEY` に自分の OpenAI API key を設定してください。

```env
OPENAI_API_KEY=sk-...
OPENAI_TEXT_MODEL=gpt-5.5
OPENAI_TRANSCRIBE_MODEL=whisper-1
```

### 4. ローカル D1 DB を初期化

```bash
npx wrangler d1 migrations apply RI-db --local
```

### 5. 開発サーバーを起動

```bash
npm run dev -- --host 127.0.0.1
```

起動後、ブラウザで次を開きます。

```text
http://127.0.0.1:5173
```

初期 admin アカウントは次の通りです。

```text
ID: admin
Password: admin
```

## 動作確認

```bash
npm run lint
npm run build
```

## Deploy 方法

このアプリは Cloudflare Workers + D1 にデプロイします。

### 1. Cloudflare にログイン

```bash
cd audiointerview
npx wrangler login
```

### 2. D1 DB を確認または作成

既存の `wrangler.jsonc` には `RI-db` の設定があります。同じ Cloudflare アカウントで使う場合はそのまま進めます。

別の Cloudflare アカウントで初回デプロイする場合は、D1 DB を作成して `wrangler.jsonc` の `database_id` を作成された ID に更新します。

```bash
npx wrangler d1 create RI-db
```

### 3. 本番 D1 に migration を適用

```bash
npx wrangler d1 migrations apply RI-db --remote
```

### 4. 本番用 secret を設定

```bash
npx wrangler secret put OPENAI_API_KEY
```

`OPENAI_TEXT_MODEL` や `OPENAI_TRANSCRIBE_MODEL` を変更したい場合は、`audiointerview/wrangler.jsonc` の `vars` に設定します。未設定の場合はアプリ内のデフォルト値が使われます。

### 5. デプロイ

```bash
npm run deploy
```

デプロイ後、Wrangler が表示する URL にアクセスしてください。
