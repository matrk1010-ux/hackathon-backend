from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from app.database import get_db
from app.models import User
from app.schemas import ProductResponse
from app.ml.recommender import recommend_by_category, profile_recommend

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.get("/debug-timing")
def debug_timing(
    user_email: str = Query(...),
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """【一時】無カテゴリ推薦の各フェーズ所要時間を返す。原因特定後に撤去。"""
    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return profile_recommend(db, user.id, limit)


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
    return products
