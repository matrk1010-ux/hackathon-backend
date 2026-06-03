import os
import google.generativeai as genai
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/ai", tags=["ai"])


def _get_gemini_model():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GEMINI_API_KEY is not configured",
        )
    genai.configure(api_key=api_key)
    return genai.GenerativeModel("gemini-2.5-flash")


class GenerateDescriptionRequest(BaseModel):
    title: str
    category: Optional[str] = None
    price: Optional[int] = None
    condition: Optional[str] = None
    notes: Optional[str] = None  # ユーザーが強調したいポイント（説明欄のメモ）


class GenerateDescriptionResponse(BaseModel):
    description: str



@router.post("/generate-description", response_model=GenerateDescriptionResponse)
def generate_product_description(request: GenerateDescriptionRequest):
    """商品タイトルからGeminiで商品説明を自動生成する"""
    model = _get_gemini_model()

    category_text = f"カテゴリ: {request.category}" if request.category else ""
    price_text = f"価格: {request.price}円" if request.price else ""
    condition_text = f"商品の状態: {request.condition}" if request.condition else ""

    notes_block = ""
    if request.notes and request.notes.strip():
        notes_block = f"""
【出品者が特に伝えたいポイント】
{request.notes.strip()}

上記のポイントは出品者が強調したい内容です。必ず説明文に自然に盛り込み、その意図を汲み取って魅力的に表現してください。事実に反する誇張や、書かれていない情報の捏造はしないでください。"""

    prompt = f"""フリマアプリに出品する以下の商品の説明文を日本語で200文字程度で作成してください。
魅力的で購買意欲を高める説明にしてください。

商品名: {request.title}
{category_text}
{price_text}
{condition_text}
{notes_block}

説明文のみを返してください。"""

    try:
        response = model.generate_content(prompt)
        return GenerateDescriptionResponse(description=response.text.strip())
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"AI generation failed: {str(e)}",
        )
