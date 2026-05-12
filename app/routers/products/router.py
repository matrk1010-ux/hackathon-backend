# エンドポイント定義
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from app.database import get_db
from app.schemas import ProductCreate, ProductUpdate, ProductResponse, ProductWithSeller
from . import crud, list as product_list, interactions

router = APIRouter(prefix="/products", tags=["products"])

# ==================== CRUD ====================

@router.post("/", response_model=ProductResponse)
def create_product(
    product: ProductCreate,
    seller_email: str = Query(...),
    db: Session = Depends(get_db)
):
    """新しい商品を出品する"""
    return crud.create_product(db, product, seller_email)

@router.get("/", response_model=List[ProductResponse])
def list_products_endpoint(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    category: Optional[str] = None,
    status: Optional[str] = None,
    min_price: Optional[int] = None,
    max_price: Optional[int] = None,
    keyword: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """商品一覧を取得"""
    return product_list.list_products(
        db, skip, limit, category, status, min_price, max_price, keyword
    )

@router.get("/{product_id}", response_model=ProductWithSeller)
def get_product_detail(
    product_id: int,
    db: Session = Depends(get_db)
):
    """商品詳細を取得"""
    return crud.get_product_by_id(db, product_id)

@router.put("/{product_id}", response_model=ProductResponse)
def update_product(
    product_id: int,
    product_update: ProductUpdate,
    seller_email: str = Query(...),
    db: Session = Depends(get_db)
):
    """商品を更新"""
    return crud.update_product(db, product_id, product_update, seller_email)

@router.delete("/{product_id}")
def delete_product(
    product_id: int,
    seller_email: str = Query(...),
    db: Session = Depends(get_db)
):
    """商品を削除"""
    return crud.delete_product(db, product_id, seller_email)

# ==================== Seller ====================

@router.get("/seller/{seller_email}", response_model=List[ProductResponse])
def get_seller_products(
    seller_email: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """出品者の商品を取得"""
    return product_list.get_seller_products(db, seller_email, skip, limit)

# ==================== Interactions ====================

@router.post("/{product_id}/view")
def record_product_view(
    product_id: int,
    user_email: str = Query(...),
    db: Session = Depends(get_db)
):
    """商品の閲覧を記録"""
    return interactions.record_view(db, product_id, user_email)

@router.get("/{product_id}/like")
def get_like_status(
    product_id: int,
    user_email: str = Query(...),
    db: Session = Depends(get_db)
):
    """ユーザーがこの商品をいいね済みか確認"""
    liked = interactions.get_like_status(db, product_id, user_email)
    return {"liked": liked}

@router.post("/{product_id}/like")
def like_product(
    product_id: int,
    user_email: str = Query(...),
    db: Session = Depends(get_db)
):
    """商品をいいね"""
    return interactions.like_product(db, product_id, user_email)

@router.delete("/{product_id}/like")
def unlike_product(
    product_id: int,
    user_email: str = Query(...),
    db: Session = Depends(get_db)
):
    """商品のいいねを取り消す"""
    return interactions.unlike_product(db, product_id, user_email)
