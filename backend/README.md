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

バックエンドは1つだけ起動します。`main.py` は起動先ポートを事前確認し、既に使われていればモデルを読み込む前に終了します。起動済みのサーバーをそのまま利用する場合は、追加で `uv run main.py` を実行する必要はありません。

起動したターミナルの標準出力に、時刻・セッション ID 付きの `[interview]` ログを自動表示します。`uvicorn main:app` で起動した場合も同じです。

- 開始時: 初回プロフィール面談／通常面談の区別、初期状態、長期プロフィール、保存済みのドメイン知識（用語集）。過去セッションの要約・対話履歴は取得しません。
- 各回答後 (`turn_completed`): `task_coverage_by_fram`（FRAM の6側面）、`task_coverage`、`task_depth`、`irregular_coverage`、`rapport` などの状態値、抽出情報、`guide`（質問方針）、生成した発話。`state.known_facts` と `state.persona_notes` に面談中の記憶が表示されます。
- 通常面談中: 参照した過去の要約・記憶 (`memory_referenced`) と、深さが停滞した際の追加方針 (`stagnation_guidance`)。
- 終了後: 要約生成開始 (`memory_finalizing`) と、DB 保存が完了した要約・プロフィール・記憶 (`memory_saved`)。生成を省略した場合や失敗した場合も表示します。要約はバックグラウンドで生成するため、終了操作の少し後に表示されます。

回答編集による再計算は `replay: true` として表示します。初回プロフィール面談では FRAM・depth などのスコアは更新せず、`profileExtraction` と `persona_notes` に抽出内容を表示します。ログには実際の要約・記憶の内容が含まれます。

FRAM の `task_coverage` は6項目のスコア合計に、0より大きい項目数に応じたボーナス合計を加えます。2項目は+0.05、3項目は+0.10、4項目は+0.20、5項目は+0.20、6項目は+0.40で、全体の上限は1です。0.05でも網羅した項目として数えます。例えば0.1が3項目なら0.40、0.05が4項目でも0.40です。ボーナスは毎ターン再計算し、段階間やターン間で重ねて加算しません。値は `interview/config.yaml` の `scoring.fram_bonuses` で調整します。

通常面談の深さに関する抽出は、1回答につき `reasons`（直接の理由）・`sources`（具体的な組織方針や教育などの源泉）・`values`（本人の価値観・優先基準）・`personal_meanings`（個人的経験と価値観形成のつながり）の最大1分類に限定します。モデルには `depth_classification` の単一分類と根拠を要求し、既存の抽出フィールドへ変換します。曖昧な場合は浅い分類を選ぶよう指示し、複数分類の配列が返った場合も浅い分類だけを保持します。「安全が重要だから」だけでは価値観に格上げしません。作業内容の `practices`、FRAM、イレギュラー情報、深掘り用のフラグは独立して抽出します。質問生成と guide のロジック・プロンプトは変更していません。既に保存された深さや過去の抽出結果は自動では再計算しません。

終了時には回答の抜粋を先に保存し (`memory_record_saved`)、バックグラウンドで要約・記憶を生成します。生成に失敗した場合は抜粋を保持し (`memory_fallback`)、次のバックエンド起動時に再試行します。終了済みで要約がない過去セッションも起動後に復旧します。抜粋の件数・文字数は `db/config.yaml` の `fallback_answers` / `fallback_answer_chars` で設定します。

要約・記憶はバックエンドで保持し、ユーザー画面には表示しません。`GET /api/sessions/{session_id}` の `memory` では、確認用に `summary` と `status` (`not_started` / `pending` / `ready` / `fallback`) を返します。

インタビュー開始時に読み込む参加者情報は長期プロフィールと、その人から教わったドメイン知識です（初回面談かどうかの判定用に終了済み件数も取得します）。開始時点では過去セッションの要約・記憶ノードを読み込みません。冒頭の「直前にしていた業務」への最初の回答から対象業務が分かった時点で、同じアカウントの終了済みセッション全体から対象業務が一致する履歴を検索します。対象が曖昧なら、特定できる回答が来るまで検索を待ちます。最近の数件だけに限定しません。参照するのは要約・保存済みの構造化情報（`info.known_facts` / `info.persona_notes`）・記憶ノードなどで、過去の `messages` は取得しません。coverage と depth の質問生成では、これらと参加者の長期プロフィールを背景として使います。

ドメイン知識は `participant_domain_knowledge` に参加者ごとの用語集として保存します。今後の終了時の記憶生成で、本人が説明した用語・意味・適用範囲・根拠を抽出し、次回は開始発話から全フェーズの質問生成に渡します。例えば「全交換」の意味を教わったら毎回聞き直さず、未説明の部分を尋ねます。訂正は同じ用語・適用範囲の記録を更新します。用語の意味を今回の実施条件とは扱わず、FRAM・depthを加点しません。`session_started` の `memory.domain_knowledge` と `memory_saved` の `domain_knowledge` で保存・読み込みを確認できます。既に要約生成が完了した過去セッションの用語集を自動で再生成する処理はありません。

同じ業務の履歴がある場合は、冒頭で今回いつもと違うことがあったかを尋ねます。その後は「いつも通り」という回答かどうかにかかわらず、初回と同じcoverage・anchor・depth・イレギュラー確認と終了条件で進みます。過去の事実を選んで同一か確認する専用ガイドや、FRAM項目を切り替える分岐はありません。既に普段どおり／例外の説明があれば、冒頭の確認は繰り返しません。

coverage と depth では、過去の同じ業務の情報と長期プロフィールを質問生成の背景として渡し、「今回の会話も踏まえて同じことを聞き直さず、今の質問方針に沿って進める」と伝えます。過去情報の有無でガイドを追加・変更せず、質問文に過去の話を入れることも求めません。過去の回答を今回のスコアや新しい事実として加算しません。`guide.past_memory_used` で質問生成に過去情報を渡したかを確認できます。

質問生成では、トレーニーとして相手に教わる姿勢で聞きます。用語や前提の確認は、対象業務と今の質問方針を理解するために必要な範囲で行います。保存済みの用語の意味は聞き直さず、今回の説明を優先します。

anchor 終了後も coverage が `0.45` 未満なら網羅性の確認へ、達成済みなら通常の depth・イレギュラー確認へ戻ります。深さの回数条件を満たしても `irregular_coverage` が `0.6` 未満なら自動終了せず、平常時の条件が整わない場合の対応などを一問ずつ確認し、0.6以上になるまで続けます。最低値は `interview/config.yaml` の `ending.min_irregular_coverage` で設定します。実際の経験に限らず、本人が説明した仮定の例外状況・対応も情報として扱います。聞き手が仮定を出しただけでは加点しません。本人の終了意思や手動終了は優先します。`signs_of_no_information` は使用せず、明確な抵抗だけを理由に圧を下げます。「ルールだから」「分からない」だけでは抵抗としません。聞き手の誤解には短く謝り、訂正を反映したうえで通常の方針に沿って質問を続けます。

対象業務名の日本語の助詞・空白・半角カタカナの違いを考慮して照合します。業務名のない古い履歴では要約を検索します。意味による検索ではないため、共通する語がない言い換えは照合できない場合があります。参照件数・抜粋量は `interview/config.yaml` の `retrieval` で設定します。検索した対象業務と参照したセッションは `memory_referenced` ログで確認できます。

FRAM `resource` は作業遂行に必要な道具・設備・人員・知識・情報・経験などを対象とし、材料（原料・食材など）は除外します。材料の種類や一覧は尋ねず、今回の話と既知の情報に沿って意味のある観点を一つずつ尋ねます。抽出も同じ定義を使い、材料を挙げただけの回答は `fram_resource` に加点しません。

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

終了合図は `whisper/terminology/turn_commands.py` で判定します。「オーバー」「オーバ」「おば」「おばー」などが発話末尾にある場合に検出し、全角の「，」「．」、引用符、半角カナにも対応します。文中の「オーバーフロー」などは終了合図として扱いません。録音中は約1秒間隔で直近4秒の音声を確認し、認識要求の処理中は次の要求を重ねません。実際の停止までの時間にはサーバーの認識時間も加わります。

専門用語の認識ヒントは `whisper/terminology/hotwords.py` の `DOMAIN_TERMS` で管理します。計器・計装・圧力計などの正しい表記を faster-whisper の `hotwords` に、現場の文脈を `initial_prompt` に渡します。設備固有の用語はこの短いリストに追加し、バックエンドを再起動してください。ヒントは認識を誘導するもので、誤認識の解消を保証しません。「ケーキ」を一律に「計器」へ置換すると、ろ過ケーキなどの正しい発言も変わるため、そのような無条件の置換は行いません。

確認済みの誤認識は `whisper/terminology/technical_normalizer.py` で文脈を限定して補正します。例えば「15等の温度」は「重合塔の温度」に補正しますが、「15度」「15棟」「15等」単独は変更しません。画面には `normalizedText` を表示し、生の認識結果は API の `rawText` に残します。用語ヒントや例文だけで改善しない場合は、同じ録音を使って別のモデルと認識精度・応答時間を比較してください。現在の既定モデルは `small` です。

RTX 5090 のドライバー570系に合わせ、uv は PyTorch / torchvision を公式の CUDA 12.8 配布元から取得します。`uv sync --locked` で反映してください。モデル設定に加え、GPUドライバーに対応したPyTorchが必要です。

faster-whisper 1.2.x と互換性を保つため、PyAV は19未満に固定しています。

2026-11-13 の RTX 5090 実測では、Qwen3.6-27B（4bit NF4）と Whisper-small（CUDA / FP16）の起動時ウォームアップ、API 経由の質問生成・JSON 情報抽出・音声認識が成功しました。両モデルを GPU 常駐させたウォームアップ直後は約18.2GiB、約7960トークン入力の短い要約後は約22.1GiBを使用しました（`nvidia-smi`。後者の生成上限は64トークン。PyTorch の予約領域も含み、負荷によって増減します）。通常の質問生成は約1.1秒、9.2秒の音声認識は約0.26秒、抽出と質問生成を含む回答投稿は約6.8秒でした。入力内容と出力長に依存する単発の測定値です。
