from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.models import Purchase, Product, User, ProductStatus
from app.schemas import PurchaseResponse, PurchaseWithDetails

router = APIRouter(prefix="/purchases", tags=["purchases"])


@router.post("/", response_model=PurchaseResponse, status_code=status.HTTP_201_CREATED)
def buy_product(
    product_id: int = Query(...),
    buyer_email: str = Query(...),
    db: Session = Depends(get_db),
):
    """商品を購入する"""
    buyer = db.query(User).filter(User.email == buyer_email).first()
    if not buyer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    if product.status != ProductStatus.available:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Product is not available")

    if product.seller_id == buyer.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot buy your own product")

    purchase = Purchase(buyer_id=buyer.id, product_id=product.id, price=product.price)
    db.add(purchase)

    product.status = ProductStatus.sold
    db.commit()
    db.refresh(purchase)
    return purchase


@router.get("/me", response_model=List[PurchaseWithDetails])
def get_my_purchases(
    buyer_email: str = Query(...),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """自分の購入履歴を取得"""
    buyer = db.query(User).filter(User.email == buyer_email).first()
    if not buyer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    purchases = (
        db.query(Purchase)
        .filter(Purchase.buyer_id == buyer.id)
        .order_by(Purchase.purchased_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return purchases
