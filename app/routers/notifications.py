"""通知センター（都度集計・軽量）。

自分の出品への「いいね／コメント／購入」を、新規テーブルを作らずに
既存データから集計して返す。既読は users.notifications_read_at で簡易管理する。
"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, Product, Like, Comment, Purchase

router = APIRouter(prefix="/notifications", tags=["notifications"])

PER_TYPE_LIMIT = 50   # 種別ごとの集計上限
TOTAL_LIMIT = 30      # 返す通知の総数


@router.get("/")
def list_notifications(user_email: str = Query(...), db: Session = Depends(get_db)):
    """自分の出品への いいね/コメント/購入 を新着順で返す。未読数も併せて返す。"""
    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    items = []

    # 他ユーザーから自分の商品へのいいね
    likes = (
        db.query(Like.liked_at, Product.id, Product.title, User.username)
        .join(Product, Product.id == Like.product_id)
        .join(User, User.id == Like.user_id)
        .filter(Product.seller_id == user.id, Like.user_id != user.id)
        .order_by(Like.liked_at.desc())
        .limit(PER_TYPE_LIMIT)
        .all()
    )
    for ts, pid, title, actor in likes:
        items.append({"type": "like", "product_id": pid, "product_title": title, "actor": actor, "created_at": ts})

    # 他ユーザーから自分の商品へのコメント
    comments = (
        db.query(Comment.created_at, Product.id, Product.title, User.username)
        .join(Product, Product.id == Comment.product_id)
        .join(User, User.id == Comment.user_id)
        .filter(Product.seller_id == user.id, Comment.user_id != user.id)
        .order_by(Comment.created_at.desc())
        .limit(PER_TYPE_LIMIT)
        .all()
    )
    for ts, pid, title, actor in comments:
        items.append({"type": "comment", "product_id": pid, "product_title": title, "actor": actor, "created_at": ts})

    # 自分の商品が購入された
    purchases = (
        db.query(Purchase.purchased_at, Product.id, Product.title, User.username)
        .join(Product, Product.id == Purchase.product_id)
        .join(User, User.id == Purchase.buyer_id)
        .filter(Product.seller_id == user.id)
        .order_by(Purchase.purchased_at.desc())
        .limit(PER_TYPE_LIMIT)
        .all()
    )
    for ts, pid, title, actor in purchases:
        items.append({"type": "sold", "product_id": pid, "product_title": title, "actor": actor, "created_at": ts})

    # 新着順にマージして上位を返す
    items.sort(key=lambda x: x["created_at"] or datetime.min, reverse=True)
    items = items[:TOTAL_LIMIT]

    read_at = user.notifications_read_at
    unread_count = sum(1 for it in items if read_at is None or (it["created_at"] and it["created_at"] > read_at))

    return {"items": items, "unread_count": unread_count}


@router.post("/read")
def mark_read(user_email: str = Query(...), db: Session = Depends(get_db)):
    """通知を既読にする（最後に開いた時刻を更新）。"""
    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user.notifications_read_at = datetime.utcnow()
    db.commit()
    return {"ok": True}
