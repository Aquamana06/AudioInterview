# インタビューシステム動作調査

調査日: 2026-11-13

## 判定

React/Vite → FastAPI → SQLite の接続と、サーバー側 Whisper の実音声認識は動作した。
ただし終了要求の誤検出と LLM の JSON 解析失敗を再現したため、インタビュー全体が正常動作する状態とはまだ判断できない。
設定されている Qwen/Qwen3.5-9B の実推論は未確認。モデルのキャッシュが不足しており、大容量モデルの追加取得は行っていない。

## 確認結果

| 確認対象 | 結果 |
| --- | --- |
| frontend の TypeScript/Vite build | 成功 |
| frontend lint | 最終状態で警告・エラーなし |
| frontend テスト | 6件成功 |
| backend テスト | 40件成功。モデル推論部分はモック |
| Vite proxy 経由のログイン・オペレータ発行・QRログイン | 成功 |
| セッション作成・開始・テキスト回答・取得・終了 | HTTP 成功、SQLite 保存を確認 |
| Python サーバーからのビルド済み HTML / JS / CSS 配信 | HTTP 200 |
| 実音声の multipart upload → faster-whisper | 成功。HTTP 約0.7秒 |
| キャッシュ済み Qwen3.5-2B の実 GPU 応答生成 | 成功。推論経路の確認用に環境変数で一時指定 |
| 同 2B によるプロフィール・終了後の記憶保存 | 失敗。JSON 解析失敗を再現 |
| 現設定の Qwen3.5-9B | オフラインでは必要ファイル不足で読み込めず |
| ブラウザ画面でのクリック、実マイク、自動録音・読み上げ | 未確認。今回の実接続確認は HTTP クライアントで実施 |

サーバーは一時 SQLite DB で起動し、調査用プロセスは終了後に停止した。既存の業務 DB は使用していない。
テスト用モデル指定はプロセス内のみに限定し、リポジトリの 9B 設定は変更していない。

## 修正が必要な点

### 1. 通常の回答を終了要求と誤認する

interview/profile_agent.py の終了判定が部分文字列一致になっている。
次の回答は終了を依頼していないが、いずれも stateLabel=end、wants_to_stop=True になる。

- 日本語: 「作業終了後の設備点検を担当しています。」
- 英語: 「I do maintenance on weekends.」

「終了」や「end」を含むだけで終了するため、明示的な終了意思と通常の業務説明を区別する必要がある。
この判定はモデルの抽出結果が false でも成立する。

### 2. 実 LLM のコードフェンス付き JSON を解析できない

合成した業務回答を使った実 Qwen3.5-2B のプロフィール抽出と記憶抽出で、応答が Markdown の json コードフェンス付きになった。
llm/client.py は生成結果をそのまま json.loads() に渡すため、JSONDecodeError となった。

実 HTTP 確認でも、応答文の生成は成功したがプロフィール項目は0件だった。終了から90秒待っても longitudinal_session_summaries に保存されなかった。
小さい検証用モデルでの再現であり、9B でも常に同じ出力になると断定するものではない。
コードフェンス等の処理、スキーマ検証、失敗を観測できるエラー表示・ログを整える必要がある。

### 3. LLM の利用可能状態を API が正しく表していない

llm/client.py の configured() はモデル名が空かどうかだけを確認する。
profile_agent.py と db/memory.py は推論・JSON解析例外をフォールバックや無処理にする。

モデル取得を無効にした現在の 9B 構成で、開始・回答 API は200を返したが、質問は固定文で、プロフィール抽出も行われなかった。
HTTP 200 や configured=true だけでは、AIインタビューが実行できたとは判定できない。
モデル準備と実推論を確認する手順、または readiness の仕組みが必要。

## 依存環境

GPU は通常実行環境で RTX 5090 / VRAM 約32GB を認識。PyTorch の CUDA は利用可能だった。
torch 2.11.0+cu128、transformers 5.22.2 でキャッシュ済み2Bモデルの生成を確認した。

調査開始時の av 19.0.2 と faster-whisper 1.2.1 では、音声デコード時に
TypeError: open() got an unexpected keyword argument 'metadata_errors'
が発生した。最新の pyproject.toml / uv.lock の av<19 制約に環境を合わせた最終状態は av 18.1.0 で、同じ音声の認識に成功した。

今回の調査ではアプリケーションソースを修正していない。依存環境の同期、フロントエンドのビルド、およびキャッシュ済み2Bモデル用の小さい processor 設定ファイルの取得を行った。

## 再確認コマンド

~~~bash
cd backend
uv sync --locked
uv run python -m unittest discover -s tests -v

cd ../frontend
npm run build
npm test
npm run lint
~~~

テスト成功は実モデルの生成品質や、ブラウザでの録音・読み上げの成功まで保証するものではない。
