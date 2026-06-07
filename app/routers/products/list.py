# 商品一覧取得ロジック（検索・フィルタ対応）
from sqlalchemy.orm import Session
from sqlalchemy import and_
from fastapi import HTTPException, status
from app.models import Product, User, ProductStatus
from typing import List, Optional

def list_products(
    db: Session,
    skip: int = 0,
    limit: int = 10,
    category: Optional[str] = None,
    status_filter: Optional[str] = None,
    min_price: Optional[int] = None,
    max_price: Optional[int] = None,
    keyword: Optional[str] = None,
) -> List[Product]:
    """商品一覧を取得（検索・フィルタ対応）"""
    # 転売対策・段階2: 公開導線では出品制限中ユーザーの商品を除外
    query = db.query(Product).filter(
        Product.status == ProductStatus.available,
        Product.hidden_by_penalty == False,  # noqa: E712
    )

    # カテゴリでフィルタ
    if category:
        query = query.filter(Product.category == category)
    
    # ステータスでフィルタ
    if status_filter:
        try:
            status_enum = ProductStatus(status_filter)
            query = query.filter(Product.status == status_enum)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status. Must be one of: {', '.join([s.value for s in ProductStatus])}"
            )
    
    # キーワードでフィルタ（タイトル・説明文の部分一致）
    if keyword:
        like_pattern = f"%{keyword}%"
        query = query.filter(
            Product.title.like(like_pattern) | Product.description.like(like_pattern)
        )

    # 価格範囲でフィルタ
    if min_price is not None:
        query = query.filter(Product.price >= min_price)
    if max_price is not None:
        query = query.filter(Product.price <= max_price)
    
    # ページネーション
    products = query.offset(skip).limit(limit).all()
    return products

def get_seller_products(
    db: Session,
    seller_email: str,
    skip: int = 0,
    limit: int = 10
) -> List[Product]:
    """特定の出品者の商品を取得"""
    seller = db.query(User).filter(User.email == seller_email).first()
    
    if not seller:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    products = db.query(Product)\
        .filter(Product.seller_id == seller.id)\
        .offset(skip)\
        .limit(limit)\
        .all()
    
    return products
