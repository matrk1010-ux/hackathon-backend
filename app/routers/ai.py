import os
import re
import json
import base64
import google.generativeai as genai
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/ai", tags=["ai"])

# 出品フォームと厳密に一致させる選択肢
CATEGORIES = [
    "服・ファッション",
    "本・漫画",
    "家電・スマホ",
    "スポーツ",
    "おもちゃ",
    "家具・インテリア",
    "コスメ・美容",
    "その他",
]

CONDITIONS = [
    "新品・未使用",
    "未使用に近い",
    "目立った傷や汚れなし",
    "やや傷や汚れあり",
    "傷や汚れあり",
    "全体的に状態が悪い",
]


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
    condition_text = f"商品の状態: {request.condition}" if request.condition else ""

    notes_block = ""
    if request.notes and request.notes.strip():
        notes_block = f"""
【出品者が特に伝えたいポイント】
{request.notes.strip()}

上記のポイントは出品者が強調したい内容です。必ず説明文に自然に盛り込み、その意図を汲み取って魅力的に表現してください。事実に反する誇張や、書かれていない情報の捏造はしないでください。"""

    prompt = f"""フリマアプリに出品する以下の商品の説明文を日本語で作成してください。
できるだけ簡潔に、100文字以内でまとめてください。要点だけを伝え、冗長な前置きや過剰な装飾表現は避けてください。
価格や金額（「600円」など）は説明文に含めないでください。価格はアプリ側で別途表示されるため、本文に書くと重複します。

商品名: {request.title}
{category_text}
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


class AnalyzeImageRequest(BaseModel):
    image_base64: str  # data URI（例: "data:image/jpeg;base64,...."）または素のbase64


class AnalyzeImageResponse(BaseModel):
    title: str = ""
    category: Optional[str] = None
    condition: Optional[str] = None


def _parse_data_uri(image_base64: str):
    """data URI または素のbase64を (mime_type, bytes) に分解する"""
    m = re.match(r"^data:(?P<mime>[^;]+);base64,(?P<data>.+)$", image_base64, re.DOTALL)
    if m:
        mime = m.group("mime")
        data = m.group("data")
    else:
        mime = "image/jpeg"
        data = image_base64
    try:
        return mime, base64.b64decode(data)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid image data",
        )


@router.post("/analyze-image", response_model=AnalyzeImageResponse)
def analyze_product_image(request: AnalyzeImageRequest):
    """商品画像をGeminiで解析し、商品名・カテゴリ・状態を推定する（説明文には触れない）"""
    model = _get_gemini_model()
    mime_type, image_bytes = _parse_data_uri(request.image_base64)

    prompt = f"""あなたはフリマアプリの出品アシスタントです。
添付された商品写真を見て、出品フォームの入力候補を推定してください。

【出力ルール】
- 必ず次のキーだけを持つJSONのみを返す（前後に説明文やコードフェンスを付けない）：
  {{"title": string, "category": string, "condition": string}}
- title: 写真から分かる範囲で簡潔な商品名（20文字以内、ブランドや種類が読み取れれば含める）
- category: 次のいずれかから1つだけ厳密に選ぶ → {CATEGORIES}
- condition: 写真の見た目から推定し、次のいずれかから1つだけ厳密に選ぶ → {CONDITIONS}
- 写真から判断できない項目は空文字 "" にする（無理に埋めない・捏造しない）
- 価格や説明文は推定しない（含めない）"""

    try:
        response = model.generate_content([
            prompt,
            {"mime_type": mime_type, "data": image_bytes},
        ])
        raw = response.text.strip()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"AI analysis failed: {str(e)}",
        )

    # コードフェンスを除去してJSON部分を抽出
    cleaned = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    data = {}
    if match:
        try:
            data = json.loads(match.group(0))
        except Exception:
            data = {}

    title = (data.get("title") or "").strip()
    category = (data.get("category") or "").strip()
    condition = (data.get("condition") or "").strip()

    # 選択肢に一致しないものは捨てる（フォームの値と必ず整合させる）
    if category not in CATEGORIES:
        category = None
    if condition not in CONDITIONS:
        condition = None

    return AnalyzeImageResponse(title=title, category=category, condition=condition)
