# depth評価シミュレーション

本番DBには接続せず、半構造化インタビューをターミナルで実行する実験用エージェントです。

```bash
cd ../../
npm run depth-evaluation
```

生成データは `sample_data/depth-evaluations/` に保存されます。各JSONには会話履歴、agentのdepth判定、抽出結果、state、人間のdepth評価、任意メモが含まれます。
