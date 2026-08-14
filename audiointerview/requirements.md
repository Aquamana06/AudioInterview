# Audio Interview 要件定義書

## 1. 目的

本システムは、化学プラント等の現場オペレータに対して、AIインタビュアーが業務経験・判断・価値観・イレギュラー対応を聞き取るためのWebインタビューシステムである。  
Cloudflare Pages / Workers / D1 を用いて、フロントエンド、API、データ保存、認証、履歴管理を一体として提供する。

## 2. 対象ユーザー

- オペレータ: 発行されたIDまたはQRコードでログインし、インタビューに回答する。
- 管理者: 初期ID `admin` / 初期パスワード `admin` でログインし、オペレータID発行、QR表示、全セッション履歴の確認を行う。

## 3. システム構成

- Frontend: React + TypeScript + Vite
- Backend: Cloudflare Workers + TypeScript
- Database: Cloudflare D1
- Hosting: Cloudflare Pages / Workers Assets
- AI: OpenAI Responses API（マスク済みテキストのみ）
- Local AI: faster-whisper large-v3（GPU）、専門用語補正、Semantic Masking
- Local/Deploy: Wrangler

## 4. 主要機能

### 4.1 認証・アカウント管理

- 管理者はIDとパスワードでログインできる。
- オペレータは管理者が発行したID、またはQRコードでログインできる。
- ログイン状態はHttpOnly Cookieのセッションで管理する。
- 管理者はオペレータIDを新規発行できる。
- 管理者は全オペレータのインタビュー履歴を確認できる。

### 4.2 インタビューセッション

- ユーザーは新規セッションを作成できる。
- セッションごとに言語、日本語・英語・ドイツ語を選択できる。
- セッション開始時、AIインタビュアーが言語別の開始発話を行う。
- セッションは `running` または `ended` の状態を持つ。
- ユーザー操作による手動終了、またはAI側の終了判定でセッションを終了する。

### 4.3 テキスト入力

- オペレータはテキストボックスから回答を入力し、送信できる。
- 送信された回答はD1に保存される。
- AIインタビュアーの応答もD1に保存される。
- 過去のユーザー発話は編集可能とし、編集時はその時点以降の会話を再生成する。

### 4.4 音声入力

- ブラウザの音声認識で `hey whisper` 相当の起動語を検知する。
- 起動後、MediaRecorderで音声を録音する。
- `over` 相当の終了語を検知したら録音を終了する。
- 録音中は一定間隔でローカルfaster-whisper large-v3に渡し、文字起こしプレビューを更新する。
- 録音終了後、音声をローカルfaster-whisperで確定文字起こしする。
- ローカル境界内で専門用語補正とSemantic Maskingを行い、マスク済みテキストだけをWorkerへ送る。
- テキスト入力も同じローカル補正・マスク処理を通してからWorkerへ送る。
- 音声モードではAI応答をブラウザのSpeechSynthesisで読み上げる。
- テキスト入力欄にフォーカスした場合は音声モードを停止する。

### 4.5 AIインタビュー処理

- Worker上のTypeScript実装で、各ターンごとに以下を行う。
  - 直前の回答と履歴から情報を構造化抽出する。
  - インタビュー状態を更新する。
  - 会話方針を決定する。
  - 次の自然な発話を生成する。
- 抽出項目は以下とする。
  - `target_work`
  - `situations`
  - `practices`
  - `reasons`
  - `values`
  - `sources`
  - `personal_meanings`
  - `irregular_situations`
  - `irregular_responses`
  - `persona_notes`
  - `emotions`
  - `user_questions`
  - `signs_of_friction`
  - `signs_of_resistance`
  - `signs_of_no_information`
  - `wants_to_stop`
- インタビュー状態は、対象業務、業務理解の網羅性、深さ、イレギュラー網羅、ラポール、既知事実、質問済み内容等を保持する。
- 深さは `personal_meanings` まで到達した場合に最大6段階として扱う。
- AIは重複質問を避け、既知情報を前提として使う。

### 4.6 履歴・状態保存

- D1に以下を保存する。
  - アカウント
  - 認証セッション
  - インタビューセッション
  - ユーザー/システム発話
  - インタビュー状態
- 各AI応答のメタ情報として、抽出結果、会話方針、状態スナップショットを保存する。

### 4.7 ターミナル確認

- ブラウザを使わず、ターミナルでインタビュー挙動を確認できる。
- `terminal-interview.mjs` から、実際の `worker/agent.ts` と同じロジックを呼び出す。
- 各ターン後に、網羅性、深さ、イレギュラー網羅、抽出項目、会話方針を表示する。

## 5. 画面要件

- ログイン画面はIDログインとQRログインを切り替えられる。
- メイン画面は、セッション一覧、言語切替、チャット履歴、入力欄、音声開始/停止、終了ボタンを持つ。
- 状態表示として、Ready、Listening for wake word、Recording、Transcribing、Speaking、Interviewer thinking、Ended等を表示する。
- 管理者画面では、ID発行、QRコード表示、履歴一覧を表示する。

## 6. API要件

- `/api/auth/login`: ID/QRログイン
- `/api/auth/logout`: ログアウト
- `/api/me`: ログイン中アカウント取得
- `/api/status`: OpenAI設定状態取得
- `/api/me/password`: 管理者パスワード変更
- `/api/sessions`: セッション一覧取得・新規作成
- `/api/sessions/:id`: セッション詳細取得
- `/api/sessions/:id/start`: インタビュー開始
- `/api/sessions/:id/messages`: ユーザー発話投稿・編集再投稿
- `/api/sessions/:id/end`: セッション終了
- `/api/admin/accounts`: 管理者によるアカウント一覧取得・発行
- `/api/admin/histories`: 管理者による履歴一覧取得
- Local `POST /transcribe`: faster-whisper文字起こし、専門用語補正、Semantic Masking
- Local `POST /mask-text`: テキスト入力の専門用語補正、Semantic Masking

## 7. 非機能要件

- Cloudflare Workers上で動作するTypeScript実装とする。
- データはCloudflare D1に保存する。
- OpenAI APIキーは環境変数またはCloudflare Secretで管理する。
- 管理者CookieはHttpOnly、SameSite=Laxとし、HTTPSではSecureを付与する。
- フロントエンドとバックエンドは同一Cloudflareプロジェクト内で扱う。
- ローカル開発では `.dev.vars` とローカルD1を利用できる。

## 8. 初期仕様からの主な変更点

- バックエンドはPythonではなくTypeScript Workersで実装する。
- 音声認識はローカルfaster-whisper large-v3を使用し、録音中の逐次プレビューと録音後の確定文字起こしを行う。
- `hey whisper` / `over` の検知はブラウザ音声認識で行う。
- インタビューアルゴリズムはTypeScriptの `worker/agent.ts` に統合する。
- 抽出項目に `personal_meanings` を追加し、インタビュー深さを最大6段階で扱う。
- ターミナル上でインタビュー挙動と内部状態を確認するCLIを追加する。

## 9. 完了条件

- 管理者がログインし、オペレータIDを発行できる。
- オペレータがIDまたはQRでログインできる。
- セッションを作成し、日本語・英語・ドイツ語で開始できる。
- テキスト回答からAI応答が生成され、履歴に保存される。
- 音声回答が文字起こしされ、AI応答に接続される。
- セッションを終了できる。
- 管理者が全履歴を確認できる。
- ターミナルでインタビュー挙動と内部状態を確認できる。
