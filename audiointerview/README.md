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
