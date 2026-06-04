# ユーザー行動（閲覧・いいね）を記録するロジック
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.models import Product, User, UserView, Like

def get_liked_products(db: Session, user_email: str, skip: int = 0, limit: int = 100):
    """ユーザーがいいねした商品一覧を取得（新しい順）"""
    user = db.query(User).filter(User.email == user_email).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    products = (
        db.query(Product)
        .join(Like, Like.product_id == Product.id)
        .filter(Like.user_id == user.id)
        .order_by(Like.liked_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return products


def clear_view_history(db: Session, user_email: str):
    """指定ユーザーの閲覧履歴をすべて削除する"""
    user = db.query(User).filter(User.email == user_email).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    deleted = (
        db.query(UserView)
        .filter(UserView.user_id == user.id)
        .delete(synchronize_session=False)
    )
    db.commit()

    return {"message": "View history cleared", "deleted": deleted}


def record_view(db: Session, product_id: int, user_email: str):
    """商品の閲覧を記録"""
    user = db.query(User).filter(User.email == user_email).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    product = db.query(Product).filter(Product.id == product_id).first()
    
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found"
        )
    
    view = UserView(user_id=user.id, product_id=product_id)
    db.add(view)
    db.commit()
    
    return {"message": "View recorded successfully"}

def like_product(db: Session, product_id: int, user_email: str):
    """商品をいいね"""
    user = db.query(User).filter(User.email == user_email).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    product = db.query(Product).filter(Product.id == product_id).first()
    
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found"
        )
    
    existing_like = db.query(Like)\
        .filter(and_(Like.user_id == user.id, Like.product_id == product_id))\
        .first()
    
    if existing_like:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Already liked this product"
        )
    
    like = Like(user_id=user.id, product_id=product_id)
    db.add(like)
    db.commit()
    
    return {"message": "Product liked successfully"}

def get_like_status(db: Session, product_id: int, user_email: str) -> bool:
    """ユーザーがその商品をいいね済みかどうかを返す"""
    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        return False
    existing = db.query(Like)\
        .filter(and_(Like.user_id == user.id, Like.product_id == product_id))\
        .first()
    return existing is not None


def unlike_product(db: Session, product_id: int, user_email: str):
    """商品のいいねを取り消す"""
    user = db.query(User).filter(User.email == user_email).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    like = db.query(Like)\
        .filter(and_(Like.user_id == user.id, Like.product_id == product_id))\
        .first()
    
    if not like:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Like not found"
        )
    
    db.delete(like)
    db.commit()
    
    return {"message": "Like removed successfully"}
