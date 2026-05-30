# 商品 CRUD ロジック
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from app.models import Product, User, ProductStatus
from app.schemas import ProductCreate, ProductUpdate
from app.ml.embeddings import get_embedding
from datetime import datetime

def get_product_by_id(db: Session, product_id: int):
    """ID で商品を取得"""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found"
        )
    return product

def create_product(db: Session, product: ProductCreate, seller_email: str):
    """新しい商品を作成"""
    seller = db.query(User).filter(User.email == seller_email).first()
    
    if not seller:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    db_product = Product(
        seller_id=seller.id,
        title=product.title,
        description=product.description,
        price=product.price,
        category=product.category,
        image_url=product.image_url,
        status=ProductStatus.available
    )
    
    db.add(db_product)
    db.commit()
    db.refresh(db_product)

    # Embeddingを非同期的に生成して保存（失敗しても出品は成功とする）
    try:
        embed_text = f"{product.title} {product.category or ''} {product.description or ''}"
        embedding = get_embedding(embed_text)
        if embedding:
            db_product.embedding = embedding
            db.commit()
    except Exception:
        pass

    return db_product

def update_product(db: Session, product_id: int, product_update: ProductUpdate, seller_email: str):
    """商品を更新"""
    db_product = get_product_by_id(db, product_id)
    
    # 出品者を確認
    seller = db.query(User).filter(User.email == seller_email).first()
    
    if not seller or db_product.seller_id != seller.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to update this product"
        )
    
    # 更新可能なフィールドを更新
    if product_update.title is not None:
        db_product.title = product_update.title
    if product_update.description is not None:
        db_product.description = product_update.description
    if product_update.price is not None:
        db_product.price = product_update.price
    if product_update.category is not None:
        db_product.category = product_update.category
    if product_update.image_url is not None:
        db_product.image_url = product_update.image_url
    if product_update.status is not None:
        db_product.status = product_update.status
    
    db_product.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(db_product)
    return db_product

def delete_product(db: Session, product_id: int, seller_email: str):
    """商品を削除"""
    db_product = get_product_by_id(db, product_id)
    
    # 出品者を確認
    seller = db.query(User).filter(User.email == seller_email).first()
    
    if not seller or db_product.seller_id != seller.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to delete this product"
        )
    
    db.delete(db_product)
    db.commit()
    return {"message": "Product deleted successfully"}
