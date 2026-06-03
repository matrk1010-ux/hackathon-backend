import os
import re
import json
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
ユーザーの要望に本当に合った商品だけを、アプリ内の実在商品から厳選して提案します。

ルール：
- 必ず提示された【候補商品】リストの中からのみ選ぶ
- ユーザーの要望に関係のない商品は絶対に提案しない（無理に数を揃えない）
- 本当に関係する商品が1つもなければ、正直に「該当する商品が見つかりませんでした」と伝える
- 各商品を提案する理由を一言添える
- 会話の文脈を踏まえて条件の絞り込みにも対応する
- 複数の選択肢（例：「5巻単品」と「全巻セット」のように内容が重複するもの）を出す場合は、
  必ず「どちらか一方を選んでください」と明記する（両方買うと重複するため）
- 返答は日本語で、親しみやすいトーンで200文字程度にまとめる

【出力フォーマット】
返答の最後に、実際に提案した商品のIDを必ず以下のJSON形式で記載してください（ユーザーには表示されません）：
<SELECTED>[1, 5, 6]</SELECTED>
1つも提案しない場合は <SELECTED>[]</SELECTED> と記載してください。"""

TOP_K = 6


class Message(BaseModel):
    role: str  # "user" or "model"
    content: str


class AiSetChatRequest(BaseModel):
    messages: list[Message]
    min_budget: Optional[int] = None
    max_budget: Optional[int] = None


class AiSetChatResponse(BaseModel):
    reply: str
    suggested_products: list[ProductResponse]


def in_budget(price: int, min_budget: Optional[int], max_budget: Optional[int]) -> bool:
    if min_budget is not None and price < min_budget:
        return False
    if max_budget is not None and price > max_budget:
        return False
    return True


def get_all_available(db: Session, min_budget: Optional[int], max_budget: Optional[int]) -> list:
    """embeddingがない場合のフォールバック：全商品をGeminiに渡す"""
    q = db.query(Product).filter(Product.status == ProductStatus.available)
    if min_budget is not None:
        q = q.filter(Product.price >= min_budget)
    if max_budget is not None:
        q = q.filter(Product.price <= max_budget)
    return q.limit(50).all()


@router.post("/chat", response_model=AiSetChatResponse)
def ai_set_chat(request: AiSetChatRequest, db: Session = Depends(get_db)):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="GEMINI_API_KEY not configured")
    genai.configure(api_key=api_key)

    user_message = next((m.content for m in reversed(request.messages) if m.role == "user"), "")
    if not user_message:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No user message found")

    # Step 1: クエリをEmbedding化してRAG検索で候補を絞る
    candidates = []
    query_embedding = get_embedding(user_message)

    if query_embedding:
        products_with_emb = db.query(Product).filter(
            Product.status == ProductStatus.available,
            Product.embedding.isnot(None),
        ).all()

        products_with_emb = [
            p for p in products_with_emb
            if in_budget(p.price, request.min_budget, request.max_budget)
        ]

        if products_with_emb:
            scored = [
                (cosine_similarity(query_embedding, p.embedding), p)
                for p in products_with_emb
            ]
            scored.sort(key=lambda x: x[0], reverse=True)
            candidates = [p for _, p in scored[:TOP_K]]

    # Step 2: embeddingがある商品が0件なら全商品を候補として渡す
    if not candidates:
        candidates = get_all_available(db, request.min_budget, request.max_budget)

    # Step 3: Geminiに渡す候補リストを構築
    if candidates:
        product_context = "\n\n【候補商品】\n"
        for p in candidates:
            product_context += f"- ID:{p.id} 「{p.title}」 ¥{p.price:,}"
            if p.category:
                product_context += f" [{p.category}]"
            if p.description:
                product_context += f"\n  説明: {p.description[:80]}"
            product_context += "\n"
    else:
        product_context = "\n\n【候補商品】\n現在出品されている商品がありません。\n"

    if request.min_budget is not None or request.max_budget is not None:
        lo = f"¥{request.min_budget:,}" if request.min_budget is not None else "下限なし"
        hi = f"¥{request.max_budget:,}" if request.max_budget is not None else "上限なし"
        product_context += f"\n【予算】{lo} 〜 {hi}\n"

    # Step 4: Geminiにセット提案を依頼
    model = genai.GenerativeModel("gemini-2.5-flash", system_instruction=SYSTEM_PROMPT)
    history = [
        {"role": m.role, "parts": [m.content]}
        for m in request.messages[:-1]
    ]
    chat = model.start_chat(history=history)
    response = chat.send_message(user_message + product_context)
    raw_text = response.text.strip()

    # Step 5: Geminiが選んだ商品IDを抽出し、それだけをカード表示
    selected_ids = []
    match = re.search(r"<SELECTED>\s*(\[.*?\])\s*</SELECTED>", raw_text, re.DOTALL)
    if match:
        try:
            selected_ids = json.loads(match.group(1))
        except Exception:
            selected_ids = []
    reply = re.sub(r"<SELECTED>.*?</SELECTED>", "", raw_text, flags=re.DOTALL).strip()

    candidate_map = {p.id: p for p in candidates}
    suggested_products = [candidate_map[i] for i in selected_ids if i in candidate_map]

    return AiSetChatResponse(
        reply=reply,
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
