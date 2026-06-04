from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel
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


class BulkPurchaseRequest(BaseModel):
    product_ids: List[int]
    buyer_email: str


class BulkPurchaseResponse(BaseModel):
    purchased: List[PurchaseResponse]
    failed: List[dict]  # {product_id, reason}
    total_price: int


@router.post("/bulk", response_model=BulkPurchaseResponse, status_code=status.HTTP_201_CREATED)
def bulk_buy_products(request: BulkPurchaseRequest, db: Session = Depends(get_db)):
    """複数商品をまとめて購入する"""
    buyer = db.query(User).filter(User.email == request.buyer_email).first()
    if not buyer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    purchased = []
    failed = []
    total_price = 0

    for product_id in request.product_ids:
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            failed.append({"product_id": product_id, "reason": "商品が見つかりません"})
            continue
        if product.status != ProductStatus.available:
            failed.append({"product_id": product_id, "reason": "すでに売り切れです"})
            continue
        if product.seller_id == buyer.id:
            failed.append({"product_id": product_id, "reason": "自分の出品商品は購入できません"})
            continue

        purchase = Purchase(buyer_id=buyer.id, product_id=product.id, price=product.price)
        db.add(purchase)
        product.status = ProductStatus.sold
        total_price += product.price
        purchased.append(purchase)

    db.commit()
    for p in purchased:
        db.refresh(p)

    return BulkPurchaseResponse(purchased=purchased, failed=failed, total_price=total_price)


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
