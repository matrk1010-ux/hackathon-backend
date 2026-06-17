# エンドポイント定義
from fastapi import APIRouter, Depends, Query, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from app.database import get_db
from app.models import Like, UserView
from app.schemas import (
    ProductCreate,
    ProductUpdate,
    ProductResponse,
    ProductWithSeller,
    CommentCreate,
    CommentResponse,
)
from app.ml.resale import assess_product_in_background
from . import crud, list as product_list, interactions, comments

router = APIRouter(prefix="/products", tags=["products"])

# ==================== CRUD ====================

@router.post("/", response_model=ProductResponse)
def create_product(
    product: ProductCreate,
    background_tasks: BackgroundTasks,
    seller_email: str = Query(...),
    db: Session = Depends(get_db)
):
    """新しい商品を出品する。出品成功後、転売判定を非同期で実行する。"""
    db_product = crud.create_product(db, product, seller_email)
    # 出品は即成功させ、重い転売判定（Gemini含む）は裏で実行する（失敗しても出品は有効）
    background_tasks.add_task(assess_product_in_background, db_product.id)
    return db_product

@router.get("/", response_model=List[ProductResponse])
def list_products_endpoint(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    category: Optional[str] = None,
    status: Optional[str] = None,
    min_price: Optional[int] = None,
    max_price: Optional[int] = None,
    keyword: Optional[str] = None,
    condition: Optional[str] = None,
    sort: Optional[str] = Query(None, description="newest(既定)/price_asc/price_desc/likes"),
    db: Session = Depends(get_db)
):
    """商品一覧を取得（検索・フィルタ・並び替え）"""
    products = product_list.list_products(
        db, skip, limit, category, status, min_price, max_price, keyword, condition, sort
    )
    return interactions.attach_like_counts(db, products)

@router.get("/{product_id}", response_model=ProductWithSeller)
def get_product_detail(
    product_id: int,
    user_email: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """商品詳細を取得。段階2で非表示の商品は所有者本人以外には 404 を返す。"""
    product = crud.get_product_for_viewer(db, product_id, user_email)
    # 詳細では いいね数・閲覧数 を付与（社会的証明の表示用）
    product.like_count = (
        db.query(func.count(Like.id)).filter(Like.product_id == product.id).scalar() or 0
    )
    product.view_count = (
        db.query(func.count(UserView.id)).filter(UserView.product_id == product.id).scalar() or 0
    )
    return product

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
    public_only: bool = Query(False, description="公開導線では取り下げ・非表示商品を除外"),
    db: Session = Depends(get_db)
):
    """出品者の商品を取得"""
    products = product_list.get_seller_products(db, seller_email, skip, limit, public_only)
    return interactions.attach_like_counts(db, products)

# ==================== Interactions ====================

@router.get("/liked/{user_email}", response_model=List[ProductResponse])
def get_liked_products(
    user_email: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """ユーザーがいいねした商品一覧を取得"""
    products = interactions.get_liked_products(db, user_email, skip, limit)
    return interactions.attach_like_counts(db, products)

# ==================== TEMP: 閲覧履歴クリア（実行後に削除する一時エンドポイント） ====================

@router.delete("/views/{user_email}")
def _temp_clear_view_history(user_email: str, db: Session = Depends(get_db)):
    return interactions.clear_view_history(db, user_email)

# ==================== Comments（購入前Q&A） ====================

@router.get("/{product_id}/comments", response_model=List[CommentResponse])
def list_product_comments(product_id: int, db: Session = Depends(get_db)):
    """商品のコメント一覧（古い順）"""
    return comments.list_comments(db, product_id)

@router.post("/{product_id}/comments", response_model=CommentResponse, status_code=201)
def create_product_comment(
    product_id: int,
    payload: CommentCreate,
    user_email: str = Query(...),
    db: Session = Depends(get_db),
):
    """商品にコメントを投稿"""
    return comments.create_comment(db, product_id, user_email, payload.body)

@router.delete("/comments/{comment_id}")
def delete_product_comment(
    comment_id: int,
    user_email: str = Query(...),
    db: Session = Depends(get_db),
):
    """自分のコメントを削除"""
    return comments.delete_comment(db, comment_id, user_email)


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
