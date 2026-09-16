# AudioInterview

## ターミナルでインタビューを試す

`.dev.vars` に `OPENAI_API_KEY` を設定して、ブラウザ版と同じ
`worker/agent.ts` のインタビューロジックを対話形式で実行できます。

```bash
npm run interview
```

これは実験用エージェントではなく、本番の `worker/agent.ts` を呼び出す対話CLIです。coverageやFRAM内訳などの内部状態は既定で各ターンに表示されます。

既定では各ターンの depth や抽出結果も表示します。会話だけを表示する場合は
`npm run interview -- --no-debug`、言語を変える場合は
`npm run interview -- --lang en`（`ja` / `en` / `de`）を使用します。

入力中は `/state`、`/history`、`/help`、`/quit` を利用できます。

インタビューモデルは起動時に切り替えられます。`original` は既存の単発モデル、`longitudinal` は今回追加した縦断型モデルです。縦断型では同じ参加者IDを指定すると、前回までのプロフィール・要約・因果記憶を引き継ぎます。

`longitudinal` の第1セッションは、担当、役割・役職、経験、責任範囲、一日の流れなどを差し支えない範囲で尋ねるプロフィール形成回です。第2セッション以降は「先ほどの業務」から入り、既存の調整行動を起点とするインタビューへ自動的に切り替わります。

coverageの変更を長期記憶なしで確認する場合は、次のように `original` を指定します。

```bash
npm run interview -- --model original --debug
```

本番の縦断型と同じ動作（長期記憶を含む）を確認する場合は、参加者IDを固定して実行します。

```bash
npm run interview -- --model longitudinal --participant test-user --debug
```

各ターンに `task_coverage`、FRAM 6要素の内訳、`practice_covered`、`task_depth`、抽出結果、`deep_dive_opportunity`、guideが表示されます。途中で `/state` を入力するとstate全体、`/memory` で縦断型の長期記憶を確認できます。

```bash
npm run interview -- --model original
npm run interview -- --model longitudinal --participant user-001
```

OpenAIの基盤モデル自体を切り替える場合は、区別して `--llm-model` を使います。

```bash
npm run interview -- --model longitudinal --participant user-001 --llm-model gpt-5.5
```

記憶は `.terminal-interview-memory.local` に保存され、`/memory` で現在の内容を確認できます。

## depth判定の人間評価

半構造化インタビュー用の実験エージェントを動かしながら、各回答に対するdepthと人間の自己評価をファイルへ保存できます。質問の方向性は固定せず、直前の発話と履歴から柔軟に次の発話を生成します。depth抽出は本番と同じ階層基準を使い、depth 5以上が2回観測されると終了します。DBは使用せず、既定では `sample_data/depth-evaluations/` に1セッション1 JSONで保存します（`sample_data/` はgit管理外です）。

```bash
npm run depth-evaluation
npm run depth-evaluation -- --model longitudinal
```

`--model` は過去の実験記録との互換用に残しており、評価CLIの質問生成はどちらを指定しても実験用の半構造化エージェントを使います。本番のlongitudinal agent側でもdepth階層は連続判定に統一しています。

各回答の後に `human depth (0-6, /skip, /quit):` と表示されます。`4 理由までは具体的` のように数値と任意メモを入力してください。履歴・agent state・抽出結果・会話方針・agent depth・人間評価は、ターンごとに即時保存されます。

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
