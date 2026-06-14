# 商品コメント（購入前Q&A）のロジック
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from app.models import Comment, User, Product

MAX_COMMENT_LEN = 1000


def list_comments(db: Session, product_id: int) -> list:
    """商品のコメントを古い順に取得（表示名を join で付与）。"""
    rows = (
        db.query(Comment, User.username)
        .join(User, User.id == Comment.user_id)
        .filter(Comment.product_id == product_id)
        .order_by(Comment.created_at.asc())
        .all()
    )
    return [
        {
            "id": c.id,
            "product_id": c.product_id,
            "user_id": c.user_id,
            "username": uname,
            "body": c.body,
            "created_at": c.created_at,
        }
        for c, uname in rows
    ]


def create_comment(db: Session, product_id: int, user_email: str, body: str) -> dict:
    """商品にコメントを投稿する。"""
    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    text = (body or "").strip()
    if not text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="コメントを入力してください")

    comment = Comment(product_id=product_id, user_id=user.id, body=text[:MAX_COMMENT_LEN])
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return {
        "id": comment.id,
        "product_id": comment.product_id,
        "user_id": comment.user_id,
        "username": user.username,
        "body": comment.body,
        "created_at": comment.created_at,
    }


def delete_comment(db: Session, comment_id: int, user_email: str) -> dict:
    """自分のコメントを削除する（投稿者本人のみ）。"""
    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    comment = db.query(Comment).filter(Comment.id == comment_id).first()
    if not comment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")
    if comment.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="自分のコメントのみ削除できます")

    db.delete(comment)
    db.commit()
    return {"message": "Comment deleted"}
