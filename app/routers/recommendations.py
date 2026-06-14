from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from app.database import get_db
from app.models import User
from app.schemas import ProductResponse
from app.ml.recommender import recommend_by_category, recommend_similar_products
from app.routers.products.interactions import attach_like_counts

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.get("/", response_model=List[ProductResponse])
def get_recommendations(
    user_email: str = Query(...),
    limit: int = Query(10, ge=1, le=50),
    category: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """ユーザーの行動履歴に基づいた商品レコメンド（categoryでカテゴリ絞り込み可）"""
    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    products = recommend_by_category(db, user.id, limit, category)
    return attach_like_counts(db, products)


@router.get("/similar/{product_id}", response_model=List[ProductResponse])
def get_similar_products(
    product_id: int,
    limit: int = Query(4, ge=1, le=20),
    db: Session = Depends(get_db),
):
    """商品詳細ページ用「この商品に似た商品」。embedding のコサイン類似度順。"""
    products = recommend_similar_products(db, product_id, limit)
    return attach_like_counts(db, products)
