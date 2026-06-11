"""一時的な運用エンドポイント（デモ準備用）。

目的: ダミー商品の seller_id を複数アカウントへランダムに付け替える。
注意: これはデモ準備のための使い捨て。実行・確認が済んだら
      このファイルと main.py の include を削除すること。
ガード: 固定トークン（_TOKEN）一致を必須にする簡易保護。
"""
import random
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, Product

router = APIRouter(prefix="/admin-temp", tags=["admin-temp"])

# 一時トークン（このルータ削除時に無効化される）
_TOKEN = "f0EE2My3b_J83kVGhm5U_gl1mkUPl7qD"


@router.get("/seller-counts")
def seller_counts(token: str = Query(...), db: Session = Depends(get_db)):
    """出品者ごとの商品件数を返す（確認用）。"""
    if token != _TOKEN:
        raise HTTPException(status_code=403, detail="forbidden")
    rows = (
        db.query(Product.seller_id, User.email, User.username)
        .join(User, User.id == Product.seller_id)
        .all()
    )
    counts: dict = {}
    for seller_id, email, username in rows:
        key = f"{seller_id}:{username}:{email}"
        counts[key] = counts.get(key, 0) + 1
    return {"counts": counts, "total": sum(counts.values())}


@router.post("/reassign-random")
def reassign_random(
    token: str = Query(...),
    source_email: str = Query(...),
    target_emails: str = Query(..., description="カンマ区切りの宛先メール"),
    seed: int = Query(42),
    db: Session = Depends(get_db),
):
    """source_email の出品を target_emails 群へランダムに付け替える。"""
    if token != _TOKEN:
        raise HTTPException(status_code=403, detail="forbidden")

    source = db.query(User).filter(User.email == source_email).first()
    if not source:
        raise HTTPException(status_code=404, detail="source not found")

    targets = []
    for em in [e.strip() for e in target_emails.split(",") if e.strip()]:
        u = db.query(User).filter(User.email == em).first()
        if not u:
            raise HTTPException(status_code=404, detail=f"target not found: {em}")
        targets.append(u)
    if not targets:
        raise HTTPException(status_code=400, detail="no targets")

    products = db.query(Product).filter(Product.seller_id == source.id).all()
    rnd = random.Random(seed)
    counts: dict = {}
    for p in products:
        t = rnd.choice(targets)
        p.seller_id = t.id
        counts[t.email] = counts.get(t.email, 0) + 1
    db.commit()
    return {"reassigned": len(products), "source": source_email, "by": counts}
