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
from app.database import engine

load_dotenv('.env.local')


def run_migrations():
    migrations = [
        "ALTER TABLE products ADD COLUMN embedding JSON",
        "ALTER TABLE products ADD COLUMN condition VARCHAR(50)",
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


@app.get("/")
def read_root():
    return {"message": "Welcome to Hackathon Freemarket API"}


@app.get("/health")
def health_check():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
