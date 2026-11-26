# インタビューデータの保存・参照・取り出し

ユーザーの回答音声をサーバーPCに保存し、発言と音声パスをSQLiteで紐づけます。手動・自動どちらの終了時にも、会話をまとめたJSONを自動保存します。質問側の音声、訂正履歴、回答編集UIは追加しません。

## 保存先とJSON形式

既定の保存先は次のとおりです。`DATABASE_PATH` を変更した場合、音声・JSONはそのDBと同じディレクトリの `interviews/` に保存されます。

```text
backend/instance/
├── audiointerview.sqlite3
└── interviews/
    └── interview_セッションID/
        ├── transcript.json
        └── audio/
            └── 録音ID.webm
```

録音の拡張子はブラウザの形式に応じて `.webm` / `.mp4` / `.ogg` などになります。音声パスは `transcript.json` からの相対パスです。JSONと音声フォルダを一緒に保管すると、そのまま対応を辿れます。

```json
{
  "account_id": "baba",
  "user_name": "馬場",
  "session_id": "interview_a1b2c3",
  "messages": [
    {
      "role": "system",
      "message": "どんな業務をしていましたか？"
    },
    {
      "message_id": "usr_001",
      "role": "user",
      "message": "上流工程の運転立ち上げです",
      "audio_file": "audio/録音ID.webm"
    }
  ]
}
```

- `account_id`：ログインに使うID。
- `user_name`：セッション作成時の表示名。以後アカウントの表示名を変更しても維持します。
- `session_id`：一意なセッションID。
- ユーザー発言だけに `message_id` と `audio_file` を付けます。キーボード入力など録音がない発言は `audio_file: null` です。
- 質問側のroleは既存DBと同じ `system` のままです。`session_name` や重複する利用者IDは出力しません。
- テキストは既存の正規化・マスキング後の内容です。録音にはマスキング前の内容が残ります。

録音は回答全体の文字起こし前に保存します。終了判定用の短い録音は保存しません。同じ録音ID・内容の再送は重複登録せず、別内容でのIDの使い回しは拒否します。質問への回答を送る際に録音IDを渡し、発言と紐づけます。別セッションの音声は紐づけできません。

文字起こしに失敗した音声もファイルとDBの録音一覧に残りますが、回答が確定していないためJSONの会話には載りません。音声込みの取り出しでは、このような未紐づけの保存済み録音もコピーします。録音中にテキスト入力へ切り替えたり終了したりしてキャンセルした未送信録音は保存しません。文字起こし・送信中は終了操作を無効にし、回答と終了処理の競合を避けます。

## 現在のDB構造

会話の正本はSQLiteです。次の関係で保存し、終了時にJSONへまとめます。

```text
accounts.id（ログインID）
  └── interview_sessions.account_id
        interview_sessions.id（セッションID）
          ├── messages.session_id（質問・回答）
          ├── interview_archives.session_id（表示名・JSON出力状態）
          └── interview_recordings.session_id（録音）
                └── message_id → messages.id
```

| テーブル | 主な情報 |
| --- | --- |
| `accounts` | `id`, `display_name`, 権限、有効状態、認証情報、日時 |
| `interview_sessions` | `id`, `account_id`, `title`, `language`, `status`, 開始・終了日時 |
| `messages` | `id`, `session_id`, `role`, `content`, `input_mode`, `language`, `meta_json`, 日時 |
| `interview_archives`（追加） | `session_id`, `user_name`, `status`, `exported_at`, `last_error` |
| `interview_recordings`（追加） | `id`＝録音ID, `session_id`, `message_id`, `audio_file`, `content_type`, `sha256`, `created_at` |

`messages.content` が会話本文です。`input_mode` は `text` / `voice` / `system`、`meta_json` は質問側に付く抽出情報・質問方針・状態などです。このほか要約・プロフィール・記憶・進行状態は既存の別テーブルに保存します。訂正履歴のテーブルは追加していません。

既存の `title` は画面用として残しますが、保存用JSONには出力しません。旧来のバックエンドには `editMessageId` を受け付ける処理が残っていますが、現在の画面からは使いません。この変更では編集機能の拡張はしていません。

## 反映と過去データ

バックエンドを再起動すると、既存データを保持して新テーブルとトリガーを作成します。既存テーブルの列変更はなく、繰り返し起動しても適用できます。新しいフロントも利用してください。静的配信なら `frontend/` で `npm run build`、Vite開発サーバーなら更新後の画面を再読み込みします。

起動時に過去の終了済みセッションもJSON化します。過去の録音は保存されていないため `audio_file: null` です。過去セッションの表示名は移行時の現在の表示名で補完し、当時の名前の復元はできません。未終了のセッションは自動JSON化の対象外です。

JSONは一時ファイルに書き、書き込み完了後に置き換えます。要約処理とは独立して保存し、要約生成に失敗しても会話JSONを残します。JSON保存に失敗した場合はDBの出力状態を `pending` として残し、次の起動や `rebuild` で再試行します。`ready` でもJSONが見つからなければ起動時に再生成します。

## ブラウザ・APIで参照する

起動中のアプリにログインし、セッション履歴から選択します。管理者は「ID発行・管理画面」→「全インタビュー履歴」→「開く」から全員分を確認できます。一般利用者は自分のセッションだけを参照できます。

ログイン済みの既存APIでは、`GET /api/sessions` が一覧、`GET /api/sessions/{session_id}` が詳細です。管理者専用の一覧は `GET /api/admin/histories` です。詳細の `messages` に会話、`state` に状態、`memory` に要約、`archive` にJSON出力状態・出力日時・エラーが入ります。APIの会話本文のキーは `content` です。

## 管理コマンドで参照・取り出す

サーバーPC上のターミナルで実行します。出力先を省略すると、プロジェクト直下の `tmp/`（`/home/mana/AudioInterview/tmp/`）へ日時・識別子付きの新しいファイルまたはフォルダを毎回作成し、保存先を表示します。既存の出力は上書きしません。実行するカレントディレクトリにかかわらず保存先は同じです。このフォルダはGitの管理対象外です。既存の仮想環境を使い、APIやGPUモデルの起動は不要です。Webログインとは別に、DBファイルを読める人が実行する管理用の操作です。

```bash
cd /home/mana/AudioInterview/backend

# 全セッションの一覧（JSON）。未終了も表示
.venv/bin/python -m tools.interviews list

# ログインIDで絞り込む
.venv/bin/python -m tools.interviews list --account-id baba

# 表示名で絞り込む
.venv/bin/python -m tools.interviews list --user-name Mana

# 終了済みの会話をJSON配列として一括出力
# 各発言はrole/messageだけ。account_id/user_name/session_idは残す
.venv/bin/python -m tools.interviews export \
  --all

# 利用者を限定
.venv/bin/python -m tools.interviews export \
  --account-id baba

# テストオペレータ4の全セッション（未終了も含む）
.venv/bin/python -m tools.interviews export \
  --account-id operetor_test4 --status all

# 特定セッションの会話だけ。IDはlistで確認した実際の値に置き換える
.venv/bin/python -m tools.interviews export \
  --session-id interview_実際のID

# 保存用JSONと音声をセットで取り出す
.venv/bin/python -m tools.interviews export \
  --all --format archive --include-audio

# 表示名Manaの全会話と音声（未終了も含む）
.venv/bin/python -m tools.interviews export \
  --user-name Mana --status all --format archive --include-audio

# 特定セッションを音声付きで取り出す
.venv/bin/python -m tools.interviews export \
  --session-id interview_実際のID --format archive --include-audio
```

`export` は既定で終了済みだけが対象です。未終了を取り出す場合は `--status running`、終了済み・未終了をすべて含める場合は `--status all` を指定します。`list` は既定で両方を表示します。`running` には途中離脱したものも含まれ、今面談中とは限りません。1件だけでもsimple形式の出力はセッションの配列です。

`--user-name`（別名 `--display-name`）は現在のアカウントの表示名で完全一致検索し、そのログインIDに属する全セッションを対象にします。名前に空白がある場合は `--user-name "Mana Yamada"` のように引用符で囲んでください。同じ表示名のアカウントが複数ある場合は出力せず、候補のログインIDを表示するので `--account-id` で指定してください。JSON内の `user_name` は保存時点の表示名のままです。

simple形式の例：

```json
[
  {
    "account_id": "baba",
    "user_name": "馬場",
    "session_id": "interview_a1b2c3",
    "messages": [
      { "role": "system", "message": "どんな業務をしていましたか？" },
      { "role": "user", "message": "上流工程の運転立ち上げです" }
    ]
  }
]
```

archive形式はセッションごとのフォルダに `transcript.json` を出力します。`--include-audio` で `audio/` もコピーし、相対パスを維持します。音声を持ち出す場合は必ずこのオプションを指定してください。参照される音声が欠けている場合はエラーにし、未完成の出力フォルダを残しません。

`list` / `export` はDBを読み取り専用で開きます。自動生成名は `interviews_20261126_153000_123456_a1b2c3.json` のようになります。archive形式では同様の名前のフォルダを作ります。保存先を自分で決める場合は従来どおりsimple形式に `--output パス`、archive形式に `--output-dir パス` を指定できます。明示した保存先が既に存在する場合も上書きしません。プロジェクト内の `tmp/` はOSの一時フォルダ `/tmp/` とは別の場所です。出力後のテキストを別途修正しても、DBへ書き戻す処理や訂正履歴の記録は行いません。

### 初回移行・JSON保存の再試行

バックエンドの再起動前に管理コマンドを使う場合は、まず `rebuild` を実行してください。このコマンドはDBの新テーブル作成とJSONの書き込みを行います。音声入力機能の反映にはバックエンドの再起動も必要です。

```bash
cd /home/mana/AudioInterview/backend

# DB更新と、未出力・失敗・ファイル欠落の終了済みJSONの出力
.venv/bin/python -m tools.interviews rebuild

# 出力済みのJSONもDBから作り直す（既存JSONを置き換える）
.venv/bin/python -m tools.interviews rebuild --force
```

未出力のJSONが残った場合は終了コード1になります。`list` の `archive_status` と `last_error` で確認できます。保存用JSONを手で編集した場合、`--force` や終了APIの再実行でDBの内容に戻るため、修正作業は取り出したコピーで行ってください。

## DB全体と音声のバックアップ

会話のsimple出力には、要約・プロフィール・認証情報などは含まれません。DB全体はSQLiteのバックアップAPIでコピーできます。次は起動中も使え、既存ファイルには上書きしません。

```bash
cd /home/mana/AudioInterview/backend
.venv/bin/python - /tmp/audiointerview-backup.sqlite3 <<'PYTHON'
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from api.settings import database_path

source = database_path().resolve()
destination = Path(sys.argv[1])
with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src:
    with destination.open("xb"):
        pass
    with closing(sqlite3.connect(destination)) as dst:
        src.backup(dst)
print("DBバックアップ:", destination)
PYTHON
```

DBバックアップには認証情報や全利用者の記録が含まれます。音声はDB内には入っていないため、DBと同じ場所の `interviews/` フォルダも保管してください。全体を同じ時点で保管したい場合は、インタビューを終了してバックエンドを停止した状態でDBとフォルダの両方をコピーします。同じPC内への保存とは別に、PC故障に備える場合は別媒体にも保管します。
