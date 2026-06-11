# CLAUDE.md — hackathon-backend

Emporio（エンボリオ）の API。UTTC AIコース ハッカソン提出物。詳細仕様は `docs/requirements.md` を正典とする（着手前に必ず参照）。

## 技術スタック
- FastAPI + SQLAlchemy 2.0 + MySQL（Cloud SQL）、ドライバは PyMySQL
- 生成AI：Google Gemini `gemini-2.5-flash`（説明生成・画像解析・AIセット会話）
- 埋め込み：`models/gemini-embedding-001`（商品・クエリの embedding。旧 text-embedding-004 は廃止され embedContent で404になる）
- Python 3.11（Docker は `python:3.11-slim`）

## アーキテクチャ規約
- ルータはドメイン別に分割：`app/routers/{auth,users,purchases,ai,ai_set,recommendations}.py`
- `products` は責務分割：`router.py`(定義) / `crud.py`(作成・取得・更新・削除) / `list.py`(一覧・検索) / `interactions.py`(閲覧・いいね)
- ML ロジックは `app/ml/`（`embeddings.py` / `recommender.py` / `category_similarity.json`）
- DBアクセスは `Depends(get_db)`。モデルは `app/models.py`、Pydantic は `app/schemas.py`

## 認証方針（重要・誤解しやすい）
- **バックエンドはトークン検証をしない。** 認証は Firebase によりフロントで完結。
- 本人識別子は **メールアドレス**。各APIは `seller_email` / `buyer_email` / `user_email` をクエリで受け取る。
- 所有者前提の操作（商品の更新・削除）は `seller.id == 本人` を必ず確認すること（403で弾く）。
- → 「JWT検証が無い」「認証が甘い」は仕様。安易に指摘・追加しない。

## 検証方法（ローカルに依存パッケージは入っていない）
- 構文チェック：`python3 -c "import ast; ast.parse(open('PATH').read())"`
- **`import` 実行（例: `from app.ml import recommender`）は `ModuleNotFoundError` になるが、これは環境問題でコード不良ではない。** 本番には依存が入っている。
- numpy は `embeddings.py` 経由で依存に含まれる（追加不要）。

## デプロイ・運用
- main へ push すると Cloud Build → Cloud Run に自動デプロイ。**指示が無い限り push しない。**
- 起動時 `main.py:run_migrations()` がカラム差分を冪等に追加（既存カラムは握りつぶす）。
- Cloud SQL 接続は `MYSQL_HOST` が `/cloudsql/` 始まりなら Unix ソケット、それ以外は TCP に自動切替（`app/database.py`）。
- 必須環境変数：`MYSQL_USER/PWD/HOST/PORT/DATABASE`、`GEMINI_API_KEY`。

## AI / 推薦の不変条件（壊しやすいので注意）
- Gemini キー未設定時は **503** を返し本体機能は継続。embedding 生成失敗時も **出品自体は成功**（劣化動作）。
- AIセットの出力契約：本文末尾の `<PLANS>[{"title":str,"reason":str,"ids":[int,...],"owned_overlap":bool}]</PLANS>` タグ（最大3つの「買い方プラン」）。**プロンプトを変えるならパーサ（`ai_set.py`）も必ず合わせる。** ids は候補に実在するもののみ採用、プラン内重複は排除。`owned_overlap` はユーザーが既に所有と述べたアイテムを含むプランの印で、重複しないプランが1つでもあれば重複プランはコード側で除外する。
- embedding が無い商品は RAG 候補から除外される（`embedding.isnot(None)`）。大量シード後は `POST /ai-set/embed-all?limit=N&batch=M` を `remaining=0` まで繰り返して後埋めする。
- 画像解析（`/ai/analyze-image`）は title/category/condition のみ。**説明文は生成しない**（説明肉付けAIと役割分担）。category/condition は選択肢に厳密一致しなければ `None` に落とす。
- 推薦は全経路で `status==available` かつ `seller_id != user_id` かつ購入済み除外を守る。ハイブリッド再ランクの定数：`CAT_WEIGHT=0.35 / EMB_WEIGHT=0.50 / PRICE_WEIGHT=0.15`（合計1.0）/ `VIEW_WEIGHT=1.0 / LIKE_WEIGHT=5.0 / CANDIDATE_POOL=150`。PRICE_WEIGHT はユーザーの嗜好価格帯（閲覧/いいね商品の重み付き平均価格）への近さで、価格比の対数で評価する。

## マスタ値（フロント・AI・推薦で共通。変える時は3箇所同期）
- カテゴリ(8)：服・ファッション / 本・漫画 / 家電・スマホ / スポーツ / おもちゃ / 家具・インテリア / コスメ・美容 / その他
- 状態(6)：新品・未使用 / 未使用に近い / 目立った傷や汚れなし / やや傷や汚れあり / 傷や汚れあり / 全体的に状態が悪い

## やらないこと
- 勝手な push / 破壊的 git 操作 / 認証方式の独断変更
- 無断での新規ドキュメント(.md)作成
