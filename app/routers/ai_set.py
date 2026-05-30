import os
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
import google.generativeai as genai

from app.database import get_db
from app.models import Product, ProductStatus
from app.schemas import ProductResponse
from app.ml.embeddings import get_embedding, cosine_similarity

router = APIRouter(prefix="/ai-set", tags=["ai-set"])

SYSTEM_PROMPT = """あなたはフリマアプリのAIショッピングアシスタントです。
ユーザーの要望に合った商品セットをアプリ内の実在商品から提案します。

ルール：
- 必ず提示された【アプリ内の関連商品】リストの中からのみ提案する
- 各商品を提案する理由を一言添える（なぜその人に必要か）
- 会話の文脈を踏まえて条件の絞り込みにも対応する
- マッチする商品がない場合は正直に「現在出品されていません」と伝える
- 返答は日本語で、親しみやすいトーンで200文字程度にまとめる"""

TOP_K = 6


class Message(BaseModel):
    role: str  # "user" or "model"
    content: str


class AiSetChatRequest(BaseModel):
    messages: list[Message]
    budget: Optional[int] = None


class AiSetChatResponse(BaseModel):
    reply: str
    suggested_products: list[ProductResponse]


def keyword_search(db: Session, query: str, budget: Optional[int], limit: int) -> list:
    """embeddingがない場合のフォールバック：タイトルキーワード検索"""
    q = db.query(Product).filter(
        Product.status == ProductStatus.available,
        Product.title.contains(query),
    )
    if budget:
        q = q.filter(Product.price <= budget)
    return q.limit(limit).all()


@router.post("/chat", response_model=AiSetChatResponse)
def ai_set_chat(request: AiSetChatRequest, db: Session = Depends(get_db)):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="GEMINI_API_KEY not configured")
    genai.configure(api_key=api_key)

    user_message = next((m.content for m in reversed(request.messages) if m.role == "user"), "")
    if not user_message:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No user message found")

    # Step 1: クエリをEmbedding化してRAG検索
    suggested_products = []
    query_embedding = get_embedding(user_message)

    if query_embedding:
        products_with_emb = db.query(Product).filter(
            Product.status == ProductStatus.available,
            Product.embedding.isnot(None),
        ).all()

        if request.budget:
            products_with_emb = [p for p in products_with_emb if p.price <= request.budget]

        if products_with_emb:
            scored = [
                (cosine_similarity(query_embedding, p.embedding), p)
                for p in products_with_emb
            ]
            scored.sort(key=lambda x: x[0], reverse=True)
            suggested_products = [p for _, p in scored[:TOP_K]]

    # Step 2: embeddingがある商品が0件ならキーワード検索にフォールバック
    if not suggested_products:
        suggested_products = keyword_search(db, user_message, request.budget, TOP_K)

    # Step 3: Geminiに渡すコンテキストを構築
    if suggested_products:
        product_context = "\n\n【アプリ内の関連商品】\n"
        for p in suggested_products:
            product_context += f"- ID:{p.id} 「{p.title}」 ¥{p.price:,}"
            if p.category:
                product_context += f" [{p.category}]"
            if p.description:
                product_context += f"\n  説明: {p.description[:80]}"
            product_context += "\n"
    else:
        product_context = "\n\n【アプリ内の関連商品】\n現在マッチする商品が出品されていません。\n"

    if request.budget:
        product_context += f"\n【予算】¥{request.budget:,}以内\n"

    # Step 4: Geminiにセット提案を依頼
    model = genai.GenerativeModel("gemini-2.5-flash", system_instruction=SYSTEM_PROMPT)
    history = [
        {"role": m.role, "parts": [m.content]}
        for m in request.messages[:-1]
    ]
    chat = model.start_chat(history=history)
    response = chat.send_message(user_message + product_context)

    return AiSetChatResponse(
        reply=response.text.strip(),
        suggested_products=suggested_products,
    )


@router.post("/embed-all")
def embed_all_products(db: Session = Depends(get_db)):
    """embeddingがない既存商品に一括でembeddingを生成する"""
    products = db.query(Product).filter(Product.embedding.is_(None)).all()
    success, failed = 0, 0
    for product in products:
        text = f"{product.title} {product.category or ''} {product.description or ''}"
        embedding = get_embedding(text)
        if embedding:
            product.embedding = embedding
            success += 1
        else:
            failed += 1
    db.commit()
    return {"success": success, "failed": failed, "total": len(products)}
