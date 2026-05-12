from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os
from dotenv import load_dotenv

# ローカル開発時は .env.local を読み込む（本番環境では Cloud Run の環境変数が使われる）
load_dotenv('.env.local')

# 環境変数から DB 情報を取得
MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PWD = os.getenv("MYSQL_PWD")
MYSQL_HOST = os.getenv("MYSQL_HOST")        # ローカル: host.docker.internal
MYSQL_PORT = os.getenv("MYSQL_PORT", "3306")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE")

# Cloud SQL（Unix ソケット）かどうかを判定
# Cloud Run では MYSQL_HOST = /cloudsql/プロジェクト:リージョン:インスタンス名 を設定する
if MYSQL_HOST and MYSQL_HOST.startswith("/cloudsql/"):
    # Cloud Run → Cloud SQL: Unix ソケット接続
    DATABASE_URL = (
        f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PWD}@/{MYSQL_DATABASE}"
        f"?unix_socket={MYSQL_HOST}"
    )
else:
    # ローカル開発: TCP 接続
    DATABASE_URL = f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PWD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}"

# エンジン作成
engine = create_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
)

# セッションマネージャー作成
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ベースクラス（テーブル定義用）
Base = declarative_base()

# DB依存性関数
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
