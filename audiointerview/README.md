# AudioInterview

## ターミナルでインタビューを試す

`.dev.vars` に `OPENAI_API_KEY` を設定して、ブラウザ版と同じ
`worker/agent.ts` のインタビューロジックを対話形式で実行できます。

```bash
npm run interview
```

既定では各ターンの depth や抽出結果も表示します。会話だけを表示する場合は
`npm run interview -- --no-debug`、言語を変える場合は
`npm run interview -- --lang en`（`ja` / `en` / `de`）を使用します。

入力中は `/state`、`/history`、`/help`、`/quit` を利用できます。

インタビューモデルは起動時に切り替えられます。`original` は既存の単発モデル、`longitudinal` は今回追加した縦断型モデルです。縦断型では同じ参加者IDを指定すると、前回までのプロフィール・要約・因果記憶を引き継ぎます。

`longitudinal` の第1セッションは、担当、役割・役職、経験、責任範囲、一日の流れなどを差し支えない範囲で尋ねるプロフィール形成回です。第2セッション以降は「先ほどの業務」から入り、既存の調整行動を起点とするインタビューへ自動的に切り替わります。

```bash
npm run interview -- --model original
npm run interview -- --model longitudinal --participant user-001
```

OpenAIの基盤モデル自体を切り替える場合は、区別して `--llm-model` を使います。

```bash
npm run interview -- --model longitudinal --participant user-001 --llm-model gpt-5.5
```

記憶は `.terminal-interview-memory.local` に保存され、`/memory` で現在の内容を確認できます。

## React + TypeScript + Vite

This template provides a minimal setup to get React working in Vite with HMR and some Oxlint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the Oxlint configuration

If you are developing a production application, we recommend enabling type-aware lint rules by installing `oxlint-tsgolint` and editing `.oxlintrc.json`:

```json
{
  "$schema": "./node_modules/oxlint/configuration_schema.json",
  "plugins": ["react", "typescript", "oxc"],
  "options": {
    "typeAware": true
  },
  "rules": {
    "react/rules-of-hooks": "error",
    "react/only-export-components": ["warn", { "allowConstantExport": true }]
  }
}
```

See the [Oxlint rules documentation](https://oxc.rs/docs/guide/usage/linter/rules) for the full list of rules and categories.
