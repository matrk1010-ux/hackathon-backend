from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from sqlalchemy import text

from app.routers import auth
from app.routers.products.router import router as products_router
from app.routers.users import router as users_router
from app.routers.purchases import router as purchases_router
from app.routers.ai import router as ai_router
from app.routers.recommendations import router as recommendations_router
from app.routers.ai_set import router as ai_set_router
from app.routers.resale import router as resale_router
from app.routers.notifications import router as notifications_router
from app.database import engine

load_dotenv('.env.local')


def run_migrations():
    migrations = [
        "ALTER TABLE products ADD COLUMN embedding JSON",
        "ALTER TABLE products ADD COLUMN `condition` VARCHAR(50)",
        "ALTER TABLE products MODIFY image_url MEDIUMTEXT",
        "ALTER TABLE products ADD COLUMN image_urls JSON",  # 複数画像（最大5枚）の data URI 配列
        # ===== 転売対策: users 累積スコア =====
        "ALTER TABLE users ADD COLUMN resale_score FLOAT NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN resale_score_updated_at DATETIME NULL",
        "ALTER TABLE users ADD COLUMN resale_stage INT NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN resale_flagged_at DATETIME NULL",
        # ===== 転売対策: products 出品単位の結果 =====
        "ALTER TABLE products ADD COLUMN resale_score FLOAT NULL",
        "ALTER TABLE products ADD COLUMN resale_flagged BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE products ADD COLUMN hidden_by_penalty BOOLEAN NOT NULL DEFAULT FALSE",
        "CREATE INDEX idx_products_resale_flagged ON products (resale_flagged)",
        "CREATE INDEX idx_products_hidden_penalty ON products (hidden_by_penalty)",
        # ===== 検索高速化: 商品タイトル＋説明文の全文検索インデックス（日本語ngram） =====
        # LIKE '%kw%' は前方ワイルドカードで全件スキャンになり数千件で数秒かかる。
        # ngram パーサのFULLTEXTで転置インデックス化し、2文字以上の検索をMATCH AGAINSTで高速化する。
        "CREATE FULLTEXT INDEX ft_product_text ON products (title, description) WITH PARSER ngram",
        # ===== 転売対策: 判定の監査テーブル（create_all 不在のため明示作成） =====
        """CREATE TABLE IF NOT EXISTS resale_assessments (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            product_id INT NULL,
            score FLOAT NOT NULL,
            is_new BOOLEAN DEFAULT FALSE,
            is_mass_produced BOOLEAN DEFAULT FALSE,
            gate_passed BOOLEAN DEFAULT FALSE,
            dup_count INT DEFAULT 0,
            recent_count INT DEFAULT 0,
            list_price INT NULL,
            price_ratio FLOAT NULL,
            price_confidence FLOAT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_resale_user_created (user_id, created_at)
        )""",
        # ===== プロフィール（アバター・自己紹介）と通知既読時刻 =====
        "ALTER TABLE users ADD COLUMN avatar_url MEDIUMTEXT",
        "ALTER TABLE users ADD COLUMN bio TEXT",
        "ALTER TABLE users ADD COLUMN notifications_read_at DATETIME NULL",
        # ===== 商品コメント（購入前Q&A）。create_all 不在のため明示作成 =====
        """CREATE TABLE IF NOT EXISTS comments (
            id INT AUTO_INCREMENT PRIMARY KEY,
            product_id INT NOT NULL,
            user_id INT NOT NULL,
            body TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_comments_product_created (product_id, created_at)
        )""",
    ]
    for sql in migrations:
        with engine.connect() as conn:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception:
                pass  # カラムが既に存在する場合はスキップ


app = FastAPI(
    title="Hackathon Freemarket App",
    description="AI-powered freemarket application",
    version="1.0.0"
)

run_migrations()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users_router)
app.include_router(products_router)
app.include_router(purchases_router)
app.include_router(ai_router)
app.include_router(recommendations_router)
app.include_router(ai_set_router)
app.include_router(resale_router)
app.include_router(notifications_router)


@app.get("/")
def read_root():
    return {"message": "Welcome to Hackathon Freemarket API"}


@app.get("/health")
def health_check():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
