# Emporio（エンボリオ） 要求仕様書 兼 再現仕様書

| 項目 | 内容 |
|---|---|
| プロダクト名 | Emporio（エンボリオ） ※ギリシャ語で「商売・市場」 |
| 種別 | AI搭載フリマ（フリーマーケット）アプリ |
| 文書バージョン | 2.0 |
| 作成日 | 2026-06-04 |
| 位置づけ | UTTC AIコース ハッカソン（Demo Day）提出物 |
| 本書の目的 | この1冊だけを参照して、アプリをゼロから再構築できること |

> 本書は「何を作るか（要求）」と「どう作るか（実装仕様）」の両方を記す。第4章までが要求、第5章以降が再現に必要な技術仕様。コード断片・定数・プロンプト・API契約は実装と一致させてある。

---

## 1. はじめに

### 1.1 目的
フリマアプリ「Emporio」が満たすべき機能要求・非機能要求を定義するとともに、**実装の詳細（データモデル・API契約・ビジネスロジック・AIプロンプト・推薦アルゴリズム・フロント構成・デプロイ）を完全に記述**し、本書のみからアプリを再現できる状態にする。

### 1.2 対象読者
開発メンバー、レビュア、ハッカソン審査員、本アプリを再構築する開発者。

### 1.3 用語定義
| 用語 | 意味 |
|---|---|
| 出品 | ユーザーが商品を販売登録すること |
| いいね | 商品への関心を示すブックマーク的操作 |
| 閲覧（view） | 商品詳細ページを開く行為。レコメンドの弱いシグナル |
| レコメンド | 「あなたへのおすすめ」のパーソナライズ商品提示 |
| AIセット | 会話形式で要望を伝え、関連商品のセットを提案してもらう機能 |
| embedding | 商品テキストをベクトル化したもの（意味的類似度の計算に使用） |
| MerRec | Mercari公開データセット。カテゴリ共起の学習元 |
| 嗜好ベクトル（taste vector） | ユーザーの閲覧・いいね商品のembeddingを重み付き平均した好みの表現 |

---

## 2. システム概要

### 2.1 背景・コンセプト
一般的なフリマアプリは「出品の手間」と「欲しい物の発見」に課題がある。Emporioは**生成AI（Gemini）**を中核に据え、

- **出品を写真1枚から**支援（画像解析で項目自動入力＋説明文の自動生成）
- **発見を“その人の好み”で**支援（embeddingによるパーソナライズ推薦／会話型のセット提案）

ことで、出品体験と購買体験の双方をAIで強化する。

### 2.2 主要な価値
1. 出品の摩擦を下げる（AI自動入力・自動説明生成）
2. 受動的発見の質を上げる（パーソナライズ推薦）
3. 能動的発見を会話で実現する（AIセット）

### 2.3 全体アーキテクチャ
```
[ブラウザ / モバイル]
      │  HTTPS
      ▼
[Frontend: React 19 + MUI v9]  ── Vercel（GitHub push 連動デプロイ）
      │  REST (axios, JSON)            REACT_APP_API_URL でバックエンドを指す
      ▼
[Backend: FastAPI + SQLAlchemy]  ── Cloud Run（Cloud Build / GitHub push→main で自動デプロイ）
      │                    │
      ▼                    ▼
[MySQL: Cloud SQL]   [Google Gemini API]
  PyMySQL接続          ├─ gemini-2.5-flash（説明生成・画像解析・AIセット会話）
  起動時マイグレーション  └─ text-embedding-004（商品・クエリのembedding）

[Firebase Authentication]（Googleログイン。フロントで完結、メールでバックエンドと同期）
```

- 認証はフロントエンド側でFirebaseにより完結。バックエンドはトークン検証を行わず、**メールアドレスを本人識別子**として各APIにクエリパラメータで受け取る（ハッカソン簡易実装）。
- 画像は外部ストレージを使わず、Base64データURIとしてDBに保存する。

---

## 3. ステークホルダー・想定ユーザー

| ロール | 説明 | 主要な関心 |
|---|---|---|
| 出品ユーザー | 不要品を売りたい人 | 出品が手軽・早い |
| 購入ユーザー | 欲しい物を探す人 | 自分に合う商品が見つかる |
| 審査員/評価者 | ハッカソン審査 | 技術的工夫・UXの完成度 |

### ペルソナ例
- **出品者A**：写真は得意だが説明文が面倒 → 画像AI入力＋説明肉付けで解決。
- **購入者B**：服が好きで何となく眺めたい → 嗜好に沿った「あなたへのおすすめ」で解決。
- **購入者C**：「一人暮らしを始める」など状況ベースでまとめ買いしたい → AIセットで解決。

---

## 4. 機能要求（Functional Requirements）

### 4.1 認証・ユーザー
| ID | 要求 | 優先度 |
|---|---|---|
| FR-A1 | Googleアカウントでログイン／ログアウトできる（Firebase Auth） | 必須 |
| FR-A2 | ログインユーザーはメールアドレスで一意に識別される | 必須 |
| FR-A3 | 未ログインでも商品一覧・詳細は閲覧できる | 必須 |
| FR-A4 | 出品・購入・いいね・レコメンドはログインを要する | 必須 |
| FR-A5 | 初回ログイン時、FirebaseユーザーをアプリDBに同期（無ければ作成）する | 必須 |

### 4.2 出品（商品登録）
| ID | 要求 | 優先度 |
|---|---|---|
| FR-B1 | 商品名・カテゴリ・状態・価格・説明・画像を入力して出品できる | 必須 |
| FR-B2 | カテゴリは定義済み8分類から選択する | 必須 |
| FR-B3 | 状態は定義済み6段階から選択する | 必須 |
| FR-B4 | 画像は端末から選択し、ブラウザ側で自動縮小・JPEG圧縮して登録する | 必須 |
| FR-B5 | 商品名・価格は必須項目とする | 必須 |
| FR-B6 | 出品者は自分の出品を取り下げ（削除）できる | 必須 |
| FR-B7 | 出品者は自分の出品を更新できる（タイトル・価格・状態等） | 推奨 |
| FR-B8 | 出品時、商品テキストからembeddingを自動生成して保存する（失敗しても出品自体は成功） | 必須 |

### 4.3 AIによる出品支援
| ID | 要求 | 優先度 |
|---|---|---|
| FR-C1 | 出品時、アップロード写真をAIが解析し、商品名・カテゴリ・状態を自動入力できる（ボタン起動） | 必須 |
| FR-C2 | AIが推定したカテゴリ／状態は、フォームの選択肢に厳密一致する値のみ採用する | 必須 |
| FR-C3 | 写真から判断できない項目は空のままとし、捏造しない | 必須 |
| FR-C4 | AIが入力した欄にはその旨を表示し、ユーザーは自由に上書きできる | 必須 |
| FR-C5 | 説明欄に強調ポイントを書き、AIに紹介文を肉付け生成させられる | 必須 |
| FR-C6 | 説明文に価格・金額は含めない（アプリ側で別途表示するため） | 必須 |
| FR-C7 | 画像AIは説明欄に触れず、説明肉付けAIと役割を分担する（前工程＝事実抽出／後工程＝文章化） | 必須 |

### 4.4 商品の閲覧・検索
| ID | 要求 | 優先度 |
|---|---|---|
| FR-D1 | トップで出品中商品を一覧できる | 必須 |
| FR-D2 | キーワードで商品を検索できる（タイトル・説明文の部分一致） | 必須 |
| FR-D3 | カテゴリで商品を絞り込める | 必須 |
| FR-D4 | 商品詳細で商品名・価格・状態・カテゴリ・説明・出品者・画像を確認できる | 必須 |
| FR-D5 | 商品詳細で同カテゴリの関連商品を表示する | 推奨 |
| FR-D6 | 画像未登録の商品はカテゴリ別プレースホルダーを表示する | 推奨 |

### 4.5 いいね・閲覧
| ID | 要求 | 優先度 |
|---|---|---|
| FR-E1 | 商品にいいね／いいね解除ができる | 必須 |
| FR-E2 | 同一ユーザーが同一商品に重複していいねできない（DBユニーク制約） | 必須 |
| FR-E3 | 商品詳細を開いた行為を閲覧履歴として記録する | 必須 |

### 4.6 レコメンド（あなたへのおすすめ）
| ID | 要求 | 優先度 |
|---|---|---|
| FR-F1 | ログインユーザーの行動履歴に基づくおすすめを提示する | 必須 |
| FR-F2 | 行動シグナルはいいね（重）と閲覧（軽）で重み付けする | 必須 |
| FR-F3 | カテゴリ共起と商品embedding類似度のハイブリッドで再ランクする | 必須 |
| FR-F4 | カテゴリ絞り込み時はおすすめも同カテゴリに連動して絞り込む | 推奨 |
| FR-F5 | 行動履歴が無いユーザーには新着フォールバックを提示する（コールドスタート） | 必須 |
| FR-F6 | 購入済み・自分の出品はおすすめから除外する | 必須 |

### 4.7 AIセット（会話型提案）
| ID | 要求 | 優先度 |
|---|---|---|
| FR-G1 | 欲しい物や状況を自然文で入力すると、アプリ内の実在商品からセットを提案する | 必須 |
| FR-G2 | 提案はembedding検索（RAG）で候補を絞り、AIが要望に本当に合う商品だけを選ぶ | 必須 |
| FR-G3 | 各提案商品にAIの選定理由を表示する | 必須 |
| FR-G4 | 予算（下限・上限）を指定して範囲内で提案させられる | 推奨 |
| FR-G5 | 提案商品から選択してまとめ買い（一括購入）ができる | 必須 |
| FR-G6 | 要望に合う商品が無い場合は正直にその旨を伝える | 必須 |

### 4.8 購入
| ID | 要求 | 優先度 |
|---|---|---|
| FR-H1 | 商品を購入でき、購入後は売り切れ（sold）になる | 必須 |
| FR-H2 | 自分の出品は購入できない | 必須 |
| FR-H3 | 売り切れ商品は購入できない | 必須 |
| FR-H4 | 複数商品をまとめて購入できる（一部失敗時は理由を返す） | 必須 |

### 4.9 マイページ
| ID | 要求 | 優先度 |
|---|---|---|
| FR-I1 | 出品中／売り切れ／いいね／購入履歴をタブで確認できる | 必須 |
| FR-I2 | 各タブの件数を表示する | 推奨 |
| FR-I3 | 出品中の商品から取り下げができる | 必須 |

---

## 5. 非機能要求（Non-Functional Requirements）

### 5.1 ユーザビリティ・UX
| ID | 要求 |
|---|---|
| NFR-U1 | モバイル／PC双方に対応するレスポンシブUI。モバイルでは下部ナビゲーションを提供 |
| NFR-U2 | 読み込み中はスケルトン表示、空状態は統一コンポーネントで表示 |
| NFR-U3 | 操作結果はトースト通知で明示 |
| NFR-U4 | ブランディング（名称・配色 #ff6b35）を全画面で統一 |

### 5.2 性能
| ID | 要求 |
|---|---|
| NFR-P1 | 一覧・詳細の主要画面は実用的な応答時間で表示される |
| NFR-P2 | レコメンド計算の候補プールは上限（CANDIDATE_POOL=300）を設け計算コストを制御 |
| NFR-P3 | 画像はクライアント側で縮小・圧縮し転送量を抑える |

### 5.3 可用性・運用
| ID | 要求 |
|---|---|
| NFR-O1 | バックエンドはCloud Run上で稼働し、push連動で自動デプロイ |
| NFR-O2 | フロントエンドはVercel上で稼働し、push連動で自動デプロイ |
| NFR-O3 | AI機能はキー未設定時に503を返し、本体機能は継続する |
| NFR-O4 | embedding生成失敗時も出品自体は成功する（劣化動作） |
| NFR-O5 | DBスキーマ差分は起動時マイグレーションで吸収（カラム存在時は無視） |

### 5.4 セキュリティ
| ID | 要求 |
|---|---|
| NFR-S1 | 認証情報（APIキー等）は環境変数で管理し、コードに含めない |
| NFR-S2 | 出品の更新・削除など所有者前提の操作は本人（メール一致）のみ実行できる |
| NFR-S3 | 開発用・破壊的な暫定エンドポイントは公開前に削除する |

### 5.5 保守性
| ID | 要求 |
|---|---|
| NFR-M1 | 共通UI（カード・スケルトン・空状態・商品画像）はコンポーネント化する |
| NFR-M2 | バックエンドのルータはドメインごとに分割する |

---

## 6. 技術スタック（再現に必要な正確なバージョン）

### 6.1 バックエンド（`requirements.txt`）
| パッケージ | バージョン | 用途 |
|---|---|---|
| fastapi | 0.104.1 | Web フレームワーク |
| uvicorn | 0.24.0 | ASGI サーバ（ローカル/コンテナ起動） |
| gunicorn | 21.2.0 | 本番プロセスマネージャ（任意） |
| sqlalchemy | 2.0.23 | ORM |
| pymysql | 1.1.0 | MySQL ドライバ |
| pydantic | 2.5.0 | スキーマ検証 |
| email-validator | 2.0.0 | `EmailStr` 用 |
| python-dotenv | 1.0.0 | `.env.local` 読み込み |
| google-generativeai | 0.8.3 | Gemini / embedding |
| numpy | 1.24.3 | 推薦のベクトル計算 |
| datasets | 2.16.1 | MerRec 読み込み（学習スクリプトのみ） |
| scikit-learn / pandas | 1.3.2 / 2.1.3 | 学習補助 |

- 実行環境：Python 3.11（`Dockerfile` は `python:3.11-slim`）

### 6.2 フロントエンド（`package.json` 主要依存）
| パッケージ | バージョン |
|---|---|
| react / react-dom | 19.2.5 |
| react-router-dom | 7.15.0 |
| @mui/material / @mui/icons-material | 9.0.1 |
| @emotion/react / @emotion/styled | 11.x |
| axios | 1.16.0 |
| firebase | 12.12.1 |
| react-scripts | 5.0.1（Create React App） |

- ビルド：`npm run build`（`react-scripts build`）。**CI環境では `CI=true` によりESLint警告がビルド失敗になる**点に注意。

---

## 7. リポジトリ構成

2リポジトリ構成（親ディレクトリ自体はGitリポジトリではない）。

### 7.1 バックエンド `hackathon-backend/`
```
main.py                         # FastAPI エントリ。CORS・ルータ登録・起動時マイグレーション
Dockerfile                      # python:3.11-slim, uvicorn 起動
requirements.txt
app/
  database.py                   # engine / SessionLocal / Base / get_db
  models.py                     # SQLAlchemy モデル（User/Product/Purchase/Like/UserView/Recommendation）
  schemas.py                    # Pydantic スキーマ
  __init__.py
  routers/
    auth.py                     # /auth
    users.py                    # /users
    purchases.py                # /purchases
    ai.py                       # /ai（説明生成・画像解析）
    ai_set.py                   # /ai-set（会話型RAG提案）
    recommendations.py          # /recommendations
    products/
      router.py                 # /products エンドポイント定義
      crud.py                   # 作成/取得/更新/削除（embedding生成含む）
      list.py                   # 一覧・検索・出品者商品
      interactions.py           # 閲覧記録・いいね
  ml/
    embeddings.py               # get_embedding / cosine_similarity
    recommender.py              # ハイブリッド推薦ロジック
    category_similarity.json    # 学習済みカテゴリ共起（8x8）
scripts/
  train_cooccurrence.py         # MerRec からカテゴリ共起を学習
  seed_products.py / seed_random_products.py / seed_series_products.py  # ダミーデータ投入
docs/
  requirements.md               # 本書
```

### 7.2 フロントエンド `hackathon-frontend/`
```
public/
  index.html                    # title/description/theme-color (#ff6b35)
  manifest.json
src/
  index.js
  App.js                        # MUIテーマ・ルーティング・Provider・BottomNav
  firebase.js                   # Firebase初期化（環境変数から）
  LoginForm.jsx                 # Googleログイン
  context/
    UserContext.js              # onAuthStateChanged→/users/sync、{user,setUser,loading}
    ToastContext.jsx            # トースト通知
  api/
    client.js                   # axios（baseURL=REACT_APP_API_URL）
    users.js / products.js / purchases.js / recommendations.js / ai.js / ai_set.js
  components/
    Header.jsx                  # ロゴ(Emporio)・ナビ・ログイン状態
    BottomNav.jsx               # モバイル下部ナビ（ログイン時のみ）
    ProductCard.jsx             # 商品カード
    ProductImage.jsx            # 画像/カテゴリ別プレースホルダー
    ProductGridSkeleton.jsx     # 読み込みスケルトン
    EmptyState.jsx              # 空状態
  pages/
    HomePage.jsx                # 一覧・検索・カテゴリ・おすすめ
    ProductDetailPage.jsx       # 詳細・いいね・購入・関連商品
    SellPage.jsx                # 出品フォーム・画像AI・説明AI
    MyPage.jsx                  # 出品中/売切/いいね/購入のタブ
    AiSetPage.jsx               # 会話型セット提案・まとめ買い
```

---

## 8. 環境変数

### 8.1 バックエンド（Cloud Run の環境変数 / ローカルは `.env.local`）
| 変数 | 例・説明 |
|---|---|
| `MYSQL_USER` | DB ユーザー名 |
| `MYSQL_PWD` | DB パスワード |
| `MYSQL_HOST` | ローカル: `host.docker.internal` / Cloud Run: `/cloudsql/PROJECT:REGION:INSTANCE`（先頭が `/cloudsql/` ならUnixソケット接続に切替） |
| `MYSQL_PORT` | 既定 `3306`（TCP接続時のみ使用） |
| `MYSQL_DATABASE` | データベース名 |
| `GEMINI_API_KEY` | Google Generative AI のキー。未設定時はAI系が503 |
| `PORT` | Cloud Run が注入（既定8000） |

接続URL組み立て（`app/database.py`）：
- `MYSQL_HOST` が `/cloudsql/` 始まり → `mysql+pymysql://USER:PWD@/DB?unix_socket=HOST`
- それ以外 → `mysql+pymysql://USER:PWD@HOST:PORT/DB`
- `create_engine(..., pool_pre_ping=True)`

### 8.2 フロントエンド（Vercel / ローカル `.env`）
| 変数 | 説明 |
|---|---|
| `REACT_APP_API_URL` | バックエンドのベースURL（未設定時 `http://localhost:8000`） |
| `REACT_APP_API_KEY` | Firebase apiKey |
| `REACT_APP_AUTH_DOMAIN` | Firebase authDomain |
| `REACT_APP_PROJECT_ID` | Firebase projectId |
| `REACT_APP_STORAGE_BUCKET` | Firebase storageBucket |
| `REACT_APP_MESSAGING_SENDER_ID` | Firebase messagingSenderId |
| `REACT_APP_APP_ID` | Firebase appId |

---

## 9. データモデル（SQLAlchemy 定義）

ステータス Enum `ProductStatus`：`available` / `sold` / `removed`
レコメンド種別 Enum `RecommendationType`：`category_based` / `price_based` / `collaborative` / `sequential`

### 9.1 `users`
| カラム | 型 | 制約 |
|---|---|---|
| id | Integer | PK |
| username | String(100) | unique, not null, index |
| email | String(100) | unique, not null, index |
| password_hash | String(255) | not null（Firebase利用時は固定文字列 `"firebase_auth"`） |
| created_at / updated_at | DateTime | 既定 utcnow / onupdate utcnow |

### 9.2 `products`
| カラム | 型 | 制約 |
|---|---|---|
| id | Integer | PK |
| seller_id | Integer | FK users.id, not null, index |
| title | String(255) | not null, index |
| description | Text | |
| price | Integer | not null |
| category | String(100) | index |
| condition | String(50) | nullable |
| image_url | Text(16777215)＝MEDIUMTEXT | Base64データURIを格納 |
| status | Enum(ProductStatus) | 既定 available, index |
| embedding | JSON | nullable（text-embedding-004 のベクトル） |
| created_at / updated_at | DateTime | |

複合インデックス：`idx_seller_status(seller_id,status)`、`idx_category_status(category,status)`

### 9.3 `purchases`
| カラム | 型 | 制約 |
|---|---|---|
| id | Integer | PK |
| buyer_id | Integer | FK users.id, not null, index |
| product_id | Integer | FK products.id, not null, index |
| price | Integer | not null（購入時点の価格を保存） |
| purchased_at | DateTime | 既定 utcnow |

### 9.4 `user_views`
| id, user_id(FK), product_id(FK), viewed_at | 複合index `idx_user_product_view(user_id,product_id)` |

### 9.5 `likes`
| id, user_id(FK), product_id(FK), liked_at | **ユニーク**複合index `idx_user_product_like(user_id,product_id,unique=True)` |

### 9.6 `recommendations`
| id, user_id(FK), recommended_product_id(FK), score(Float not null), recommendation_type(String(50)), created_at | 推薦結果の任意保存用 |

### 9.7 起動時マイグレーション（`main.py` `run_migrations()`）
以下を順に実行し、既存カラムによる失敗は握りつぶす（冪等）：
```sql
ALTER TABLE products ADD COLUMN embedding JSON;
ALTER TABLE products ADD COLUMN `condition` VARCHAR(50);
ALTER TABLE products MODIFY image_url MEDIUMTEXT;
```
※ テーブル自体は `Base.metadata.create_all` ではなく既存DB前提。新規DBでは別途テーブル作成が必要（モデル定義に基づく）。

### 9.8 マスタ値（フロント・AI・推薦で共通）
- カテゴリ（8）：`服・ファッション` / `本・漫画` / `家電・スマホ` / `スポーツ` / `おもちゃ` / `家具・インテリア` / `コスメ・美容` / `その他`
- 状態（6）：`新品・未使用` / `未使用に近い` / `目立った傷や汚れなし` / `やや傷や汚れあり` / `傷や汚れあり` / `全体的に状態が悪い`

---

## 10. API 仕様（全エンドポイント）

- ベース：`{REACT_APP_API_URL}`。CORSは `allow_origins=["*"]`。
- 認証はトークン検証なし。所有者前提の操作は `seller_email` / `buyer_email` などメールで本人判定。
- `created_at`/`updated_at` 等は ISO 8601。

### 10.1 ルート/ヘルス
| メソッド | パス | レスポンス |
|---|---|---|
| GET | `/` | `{"message":"Welcome to Hackathon Freemarket API"}` |
| GET | `/health` | `{"status":"ok"}` |

### 10.2 認証 `/auth`
| メソッド | パス | 内容 |
|---|---|---|
| POST | `/auth/logout` | `{"message":"Logged out successfully"}`（実体はフロント完結） |

### 10.3 ユーザー `/users`
| メソッド | パス | 入力 | 出力 |
|---|---|---|---|
| POST | `/users/sync` | body `UserCreate{username,email,password}` | `UserResponse`。emailで既存検索、無ければ `password_hash="firebase_auth"` で作成 |
| GET | `/users/me?email=` | query `email` | `UserResponse`（無ければ404） |
| GET | `/users/{user_id}` | path | `UserResponse`（無ければ404） |

### 10.4 商品 `/products`
| メソッド | パス | 入力 | 出力・備考 |
|---|---|---|---|
| POST | `/products/?seller_email=` | body `ProductCreate{title,description?,price,category?,condition?,image_url?}` | `ProductResponse`。作成後にembedding生成（§12.1）。sellerが存在しなければ404 |
| GET | `/products/` | query `skip=0&limit=10(1..100)&category?&status?&min_price?&max_price?&keyword?` | `ProductResponse[]`。既定で `available` のみ。keywordはtitle/description部分一致。statusは enum 値以外で400 |
| GET | `/products/{id}` | path | `ProductWithSeller`（seller含む）。無ければ404 |
| PUT | `/products/{id}?seller_email=` | body `ProductUpdate`（全項目optional, status可） | `ProductResponse`。本人以外は403 |
| DELETE | `/products/{id}?seller_email=` | path+query | `{"message":"Product deleted successfully"}`。本人以外403。関連 Like/UserView/Recommendation を先に削除 |
| GET | `/products/seller/{seller_email}` | query `skip,limit` | その出品者の商品（statusに依らず全件） |
| GET | `/products/liked/{user_email}` | query `skip,limit(既定100)` | いいねした商品（liked_at降順） |
| POST | `/products/{id}/view?user_email=` | | `{"message":"View recorded successfully"}` |
| GET | `/products/{id}/like?user_email=` | | `{"liked": bool}` |
| POST | `/products/{id}/like?user_email=` | | `{"message":"Product liked successfully"}`。既いいねは400 |
| DELETE | `/products/{id}/like?user_email=` | | `{"message":"Like removed successfully"}`。未いいねは404 |

### 10.5 購入 `/purchases`
| メソッド | パス | 入力 | 出力 |
|---|---|---|---|
| POST | `/purchases/?product_id=&buyer_email=` | query | `PurchaseResponse`(201)。sold/自分の出品/不存在で400・404。成功時 product.status→sold |
| POST | `/purchases/bulk` | body `{product_ids:int[], buyer_email}` | `{purchased:PurchaseResponse[], failed:[{product_id,reason}], total_price}`(201) |
| GET | `/purchases/me?buyer_email=` | query `skip,limit(既定20)` | `PurchaseWithDetails[]`（purchased_at降順、product/buyer含む） |

### 10.6 レコメンド `/recommendations`
| メソッド | パス | 入力 | 出力 |
|---|---|---|---|
| GET | `/recommendations/?user_email=` | query `limit=10(1..50)&category?` | `ProductResponse[]`。アルゴリズムは§13 |

### 10.7 AI（出品支援）`/ai`
| メソッド | パス | 入力 | 出力 |
|---|---|---|---|
| POST | `/ai/generate-description` | `{title, category?, price?, condition?, notes?}` | `{description}`。プロンプトは§12.2。キー未設定503、生成失敗500 |
| POST | `/ai/analyze-image` | `{image_base64}`（data URI可） | `{title:"", category:null, condition:null}`。§12.3。選択肢外のcategory/conditionはnullに落とす |

### 10.8 AIセット `/ai-set`
| メソッド | パス | 入力 | 出力 |
|---|---|---|---|
| POST | `/ai-set/chat` | `{messages:[{role:"user"\|"model",content}], min_budget?, max_budget?}` | `{reply, suggested_products:ProductResponse[], reasons:{[id]:string}}`。RAGフローは§12.4。キー未設定503、user message無し400 |
| POST | `/ai-set/embed-all` | なし | `{success, failed, total}`。embedding未生成の既存商品に一括付与（運用用） |

---

## 11. Pydantic スキーマ（主要）

```
UserCreate      = {username:str, email:EmailStr, password:str}
UserResponse    = {id, username, email, created_at, updated_at}   # from_attributes
ProductCreate   = {title:str, description?:str, price:int, category?:str, condition?:str, image_url?:str}
ProductUpdate   = 全項目 optional + status?:ProductStatus
ProductResponse = ProductCreate + {id, seller_id, status, created_at, updated_at}
ProductWithSeller = ProductResponse + {seller:UserResponse}
PurchaseResponse  = {id, buyer_id, product_id, price, purchased_at}
PurchaseWithDetails = PurchaseResponse + {product:ProductResponse, buyer:UserResponse}
```
（`embedding` はレスポンスに含めない。`password_hash` も返さない）

---

## 12. AI機能の実装仕様（プロンプト・フロー）

使用モデル：会話・画像・説明＝`gemini-2.5-flash`、埋め込み＝`models/text-embedding-004`（`app/ml/embeddings.py`）。
`get_embedding(text)` はキー未設定/失敗時 `None` を返す（例外を投げない）。`cosine_similarity(a,b)` は標準的なコサイン。

### 12.1 出品時のembedding生成（`products/crud.create_product`）
1. 商品をINSERT・commit。
2. `embed_text = f"{title} {category or ''} {condition or ''} {description or ''}"` を生成。
3. `get_embedding(embed_text)` が成功すれば `product.embedding` に保存・commit。失敗は握りつぶす（出品は成功）。

### 12.2 説明文生成（`/ai/generate-description`）
- 100文字以内・簡潔・**価格は含めない**。`notes`（強調ポイント）があれば「必ず自然に盛り込み、捏造はしない」と指示。
- プロンプト要旨：
```
フリマアプリに出品する以下の商品の説明文を日本語で作成してください。
できるだけ簡潔に、100文字以内。冗長な前置きや過剰な装飾は避ける。
価格や金額は説明文に含めない（アプリ側で別途表示するため）。
商品名: {title}
カテゴリ: {category}        # 任意
商品の状態: {condition}     # 任意
【出品者が特に伝えたいポイント】{notes}  # 任意。盛り込むが捏造禁止
説明文のみを返してください。
```

### 12.3 画像解析オートフィル（`/ai/analyze-image`）
- `image_base64` を `_parse_data_uri` で `(mime_type, bytes)` に分解（data URIでなければ `image/jpeg` とみなす。デコード失敗400）。
- `model.generate_content([prompt, {"mime_type":..., "data":...}])`。
- プロンプト要旨：
```
あなたはフリマアプリの出品アシスタント。商品写真から出品フォームの入力候補を推定。
次のキーだけを持つJSONのみ返す（コードフェンス禁止）：{"title","category","condition"}
- title: 20文字以内の簡潔な商品名
- category: {CATEGORIES（8値）} から厳密に1つ
- condition: {CONDITIONS（6値）} から厳密に1つ
- 判断できない項目は "" にする（捏造しない）
- 価格や説明文は推定しない
```
- 後処理：コードフェンス除去 → `{.*}` を正規表現抽出 → `json.loads`。`category`/`condition` が選択肢外なら `None` に落とす（**説明欄は一切生成しない**＝FR-C7）。

### 12.4 AIセット会話（`/ai-set/chat`）RAGフロー
1. messages から最新の user 発話を取り出す（無ければ400）。
2. `get_embedding(user_message)` でクエリをベクトル化。
3. embedding を持つ available 商品を全取得→予算フィルタ→クエリとのコサイン類似度で降順、**上位 `TOP_K=6`** を候補に。
4. 候補が0件なら available 商品を最大50件そのまま候補に（フォールバック）。
5. 候補を `- ID:{id} 「{title}」 ¥{price:,} [{category}]\n  説明: {description[:80]}` 形式で整形し、予算があれば併記。
6. `system_instruction=SYSTEM_PROMPT`、`history=messages[:-1]`、`send_message(user_message + 候補文脈)`。
7. SYSTEM_PROMPT 要旨：候補内からのみ選ぶ／無関係は出さない／該当無しは正直に伝える／重複（巻単品と全巻等）は「どちらか選んで」と明記／本文は全体理由を150字程度・親しみやすく／**個別理由は本文に書かずJSONのreasonへ**。
8. 出力末尾に機械可読タグ：
```
<SELECTED>[{"id":1,"reason":"15〜40字の具体的理由"}, {"id":5,"reason":"..."}]</SELECTED>
該当無しは <SELECTED>[]</SELECTED>
```
9. パース：`<SELECTED>...</SELECTED>` を正規表現抽出→`json.loads`。各要素 `{"id":int,"reason":str}`（後方互換で素のintも許容）。本文は同タグを除去したもの。`selected_ids` と `reasons` を作り、**候補集合に存在するIDだけ**に絞ってカード化。

---

## 13. 推薦アルゴリズム（`app/ml/recommender.py`）

### 13.1 定数
```
CAT_WEIGHT  = 0.4   # カテゴリ共起の重み α
EMB_WEIGHT  = 0.6   # embedding類似度の重み β
VIEW_WEIGHT = 1.0   # 閲覧シグナル
LIKE_WEIGHT = 5.0   # いいねシグナル
CANDIDATE_POOL = 300
CATEGORY_SIMILARITY = category_similarity.json（起動時1回読み込み。無ければ{}）
```

### 13.2 `recommend_by_category(db, user_id, limit, category)`
1. 購入済み product_id を除外集合に。
2. **category 指定時**：そのカテゴリの available（自分・購入済み除く）を新着順で返す（FR-F4）。
3. ユーザーの閲覧/いいねカテゴリを頻度集計し、`user_cat_scores`（いいねは×5）を作成。
4. 行動が皆無 → 新着フォールバック `_recommend_popular`（FR-F5）。
5. カテゴリ共起で拡張：`CATEGORY_SIMILARITY` があれば `recommend_cat_scores[rec] += user_score * sim`。無ければ `user_cat_scores` をそのまま使用。上位3カテゴリを `top_categories`。
6. **嗜好ベクトルがあればハイブリッド再ランク**（§13.3）。組めなければ従来のカテゴリ枠割当へフォールバック。
7. 従来ロジック：`top_categories` にスコア比例で枠を配分し各カテゴリ新着順で収集→不足分は興味カテゴリ内の新着で補完。

### 13.3 嗜好ベクトルとハイブリッド再ランク
- `_build_taste_vector`：ユーザーのいいね商品（重み5）・閲覧商品（重み1）の `embedding` を重み付き平均→L2正規化。embedding付き行動が無ければ `None`。
- `_hybrid_rerank`：
  - 候補カテゴリ＝`recommend_cat_scores ∪ user_cat_scores ∪ top_categories`。
  - **カテゴリごとに**新着 `per_cat = max(50, CANDIDATE_POOL // カテゴリ数)` 件取得して重複排除（1カテゴリが新しさで枠を独占しない工夫）。
  - 各候補 `score = CAT_WEIGHT * (cat_score/max_cat) + EMB_WEIGHT * max(0, cosine(taste_vec, product.embedding))`。
  - 降順ソートし上位 `limit` を返す。
- 除外条件：全経路で `status==available` かつ `seller_id != user_id` かつ購入済み除外（FR-F6）。

### 13.4 カテゴリ共起の学習（`scripts/train_cooccurrence.py`）
- MerRec（`mercari-us/merrec`、streaming）から `SAMPLE_SIZE=100,000` 行を読み、`c0_name`（最上位カテゴリ）を `CATEGORY_MAPPING`（英語キーワード→日本語8カテゴリ）で写像。未一致は「その他」。
- `session_id` 単位で同一セッション内のカテゴリ集合を作り、ペア共起をカウント。
- 正規化：`similarity[a][b] = 共起数 / sqrt(count[a]*count[b])`（自己は1.0）。
- 出力：`app/ml/category_similarity.json`（8×8）。アプリ起動時に読み込まれる。

---

## 14. フロントエンド実装仕様

### 14.1 テーマ・ルーティング（`App.js`）
- MUIテーマ：primary `#ff6b35`（contrastText白）、secondary `#1976d2`。
- Provider順：`ThemeProvider > CssBaseline > UserProvider > ToastProvider > BrowserRouter`。
- ルート：`/`=Home、`/products/:id`=Detail、`/sell`=Sell、`/mypage`=MyPage、`/ai-set`=AiSet。
- Routes 後にモバイル余白 `<Box sx={{height:{xs:56,sm:0}}}/>` と `<BottomNav/>`。

### 14.2 認証フロー（`UserContext.js` + `firebase.js`）
- `onAuthStateChanged` でログイン検知→`syncUser(displayName||email, email)`＝`POST /users/sync`→`{...res.data, displayName, photoURL}` を `user` に格納。同期失敗時はFirebase情報のみで継続。
- `useUser()` で `{user, setUser, loading}` を参照。

### 14.3 APIレイヤ（`api/*.js`）
- `client.js`：axios、`baseURL = REACT_APP_API_URL || http://localhost:8000`、JSONヘッダ。
- 所有者操作はクエリでメールを渡す（例 `createProduct(data, sellerEmail)` → `params:{seller_email}`）。
- `aiSetChat(messages, minBudget, maxBudget)` → `POST /ai-set/chat`。
- `analyzeImage(imageBase64)` → `POST /ai/analyze-image`。`generateDescription(title,category,price,condition,notes)` → `POST /ai/generate-description`。

### 14.4 画面要件（ページ別）
- **HomePage**：新着一覧（`getProducts`）、キーワード検索、カテゴリ絞り込み、ログイン時「あなたへのおすすめ」（`/recommendations`）。読み込み中 `ProductGridSkeleton`、0件 `EmptyState`。
- **ProductDetailPage**：詳細・出品者・いいねトグル・購入・閲覧記録（`recordView`）・同カテゴリ関連商品（自分自身/売切れ除外で最大4件）。
- **SellPage**：出品フォーム。画像は端末選択→canvasで縮小・JPEG圧縮→data URI化。「この写真からAIで入力」ボタンで `analyzeImage`（title/category/conditionのみ反映、AI入力欄にヘルパー表示、手動編集でマーカー解除）。説明欄は「強調ポイント→AI肉付け」（`generateDescription`）。**2つのAIは説明欄で衝突しない**（FR-C7）。
- **MyPage**：出品中/売り切れ/いいね/購入履歴のタブ＋件数。出品中から取り下げ（`deleteProduct`）。各空状態は `EmptyState`。
- **AiSetPage**：チャットUI（messages配列）、予算指定、提案カードに `reasons[id]` をバッジ表示、選択して `purchases/bulk` でまとめ買い。

### 14.5 共通コンポーネント
- `ProductImage`：`image_url` があれば表示、無ければカテゴリ別プレースホルダー。
- `ProductGridSkeleton({count})`：Grid（xs=6 sm=4 md=3）でスケルトン。
- `EmptyState({icon,message,actionLabel,onAction})`：中央寄せの空状態。
- `Header`：ロゴ「Emporio／エンボリオ」（モバイルでcaption非表示）、AIセット/出品リンク（モバイルで折りたたみ）。
- `BottomNav`：`isMobile && user` のときのみ。ホーム/AIセット/出品/マイページ。

---

## 15. デプロイ・実行手順

### 15.1 バックエンド
- ローカル：`.env.local` を用意 → `pip install -r requirements.txt` → `uvicorn main:app --reload`（または `python main.py` で 8000）。
- コンテナ：`Dockerfile`（`python:3.11-slim`）。起動 `uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}`。
- 本番：Cloud Run。Cloud SQL は `MYSQL_HOST=/cloudsql/...` でUnixソケット接続。GitHub push→main で Cloud Build 自動デプロイ。
- 起動時に `run_migrations()` がカラム追加を冪等実行。
- 初期データ：`scripts/seed_*.py`、`scripts/train_cooccurrence.py` で共起JSON生成、`POST /ai-set/embed-all` で既存商品にembedding付与。

### 15.2 フロントエンド
- ローカル：`.env` に `REACT_APP_*` → `npm install` → `npm start`。
- 本番：Vercel。GitHub push 連動デプロイ。**`CI=true` でESLint警告がビルド失敗**になるため警告ゼロを保つ。

---

## 16. 制約・前提

- 決済は実課金を伴わない擬似購入（ハッカソン用）。
- 認証はバックエンドでトークン検証せず、メールアドレスを本人識別子とする簡易方式。
- 画像はBase64データURIとしてDB（MEDIUMTEXT）に保存（外部ストレージ未使用）。
- AI機能・embedding再ランクは `GEMINI_API_KEY` 設定と対象商品のembedding存在を前提（未設定/未生成時はフォールバック動作）。
- テーブルは既存DB前提（起動時はカラム差分のみ吸収）。新規構築時はモデル定義に基づくテーブル作成が必要。

---

## 17. 今後の拡張（スコープ外）

| 区分 | 候補 |
|---|---|
| 認証 | バックエンドでのFirebase IDトークン検証・RBAC |
| 画像配信 | 外部ストレージ＋CDN（現状はBase64） |
| 推薦 | 購入を最強の正シグナルに／時間減衰／hit-rate@k のオフライン評価 |
| リアルタイム | 「いいねした商品が売れた」等の通知（WebSocket） |
| 検索 | 音声検索・ベクトル検索の常時利用 |
| 安全性 | 不適切コンテンツの自動検出 |
| 品質 | 単体テスト・CIの整備 |

---

*本書はハッカソン提出時点の実装に基づく。仕様は今後の開発で更新されうる。*
