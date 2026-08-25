# 縦断型インタビュー拡張

既存の `worker/agent.ts` と `worker/openai.ts` は変更せず、調整行動から価値観へ進む現在のインタビューを中核として再利用する。

## エージェント構成

1. **Profile interview agent** — ユーザーIDごとの初回だけ、担当、役割、経験、責任範囲、一日の流れ、関係者を雑談的に尋ねる。
2. **Starter agent** — 2回目以降、直前の具体的業務を聞く同じ目的の開始質問を、直近の表現と重複しない形で生成する。
3. **Existing interview agent** — 2回目以降は現行どおり、今回の業務・調整行動から理由、価値観、形成背景を掘り下げる。
4. **Memory context adapter** — ユーザーのプロフィールと今回の発話に関連する過去情報だけを、参照用の system message として既存エージェントへ加える。
5. **Session memory agent** — 終了後、発言根拠付きのプロフィール差分、要約、因果ノード・エッジを抽出する。
6. **Memory repository** — ユーザーID単位で記憶を統合する。セッション固有の `InterviewState` とは分離する。

## 呼び出し例

```ts
const memory = await loadParticipantMemory(env, accountId);

const opening = await generateSessionStarter(env, {
  accountId,
  language,
  sessionCount: memory.session_count,
  recentStarters,
  profile: memory.profile,
});

// 各回答ターン
const relevant = selectRelevantMemory(memory, userInput);
const result = await runContextualInterviewTurn(
  env,
  state,
  userInput,
  currentSessionMessages,
  language,
  relevant,
);

// セッション終了後（レスポンスを待たせない非同期処理が望ましい）
const update = await extractSessionMemory(env, {
  accountId,
  sessionId,
  language,
  messages,
  previousMemory: memory,
});
await saveSessionMemory(env, accountId, sessionId, memory.profile, update);
```

`relevantMemory` は `InterviewState.known_facts` に加えない。過去セッションで深い情報が得られていても、今回のセッションの coverage/depth や終了判定を進めないためである。

## 開始質問

開始質問は過去の価値観を持ち出さず、常に今日のリアルタイムな具体経験を入口にする。プロフィールは将来的な不自然さの検査に使えるが、質問内容は「先ほどの業務」から動かさない。API障害時にも固定候補を巡回して開始できる。

## 統合上の制約

- 推論は `hypothesis` とし、本人の明言と区別する。
- ノードとエッジは発言IDを保持する。
- 過去の理由・価値観を今回へ自動適用しない。
- 現実装の統合キーは `kind:text`。意味的な言い換え統合や矛盾検出は、運用データを確認してから別ジョブとして追加する。
