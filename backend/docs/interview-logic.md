# インタビューロジック

- interview/agent.py: 抽出、状態更新、質問方針、通常セッションのターン生成
- interview/profile_agent.py: 初回セッションのプロフィール形成
- interview/longitudinal.py: 継続セッション開始文と過去記憶の選択
- db/memory.py: 参加者プロフィール、セッション要約、記憶ノードと関係の保存
- api/routes.py: セッション作成・更新・終了、回答編集時の再構築

LLM が利用できない場合も、定型の質問や抽出フォールバックを使って会話を継続できます。
