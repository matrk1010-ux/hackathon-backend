from sqlalchemy import Column, Integer, String, Text, Float, DateTime, Enum, ForeignKey, Boolean, Index
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from app.database import Base

# 商品ステータスの Enum
class ProductStatus(str, enum.Enum):
    available = "available"
    sold = "sold"
    removed = "removed"

# レコメンドタイプの Enum
class RecommendationType(str, enum.Enum):
    category_based = "category_based"
    price_based = "price_based"
    collaborative = "collaborative"
    sequential = "sequential"

# ==================== テーブル定義 ====================

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    email = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # リレーション
    products = relationship("Product", back_populates="seller", foreign_keys="Product.seller_id")
    purchases = relationship("Purchase", back_populates="buyer")
    views = relationship("UserView", back_populates="user")
    likes = relationship("Like", back_populates="user")
    recommendations = relationship("Recommendation", back_populates="user")

class Product(Base):
    __tablename__ = "products"
    
    id = Column(Integer, primary_key=True, index=True)
    seller_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(255), nullable=False, index=True)
    description = Column(Text)
    price = Column(Integer, nullable=False)
    category = Column(String(100), index=True)
    image_url = Column(String(255))
    status = Column(Enum(ProductStatus), default=ProductStatus.available, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # リレーション
    seller = relationship("User", back_populates="products", foreign_keys=[seller_id])
    purchases = relationship("Purchase", back_populates="product")
    views = relationship("UserView", back_populates="product")
    likes = relationship("Like", back_populates="product")
    recommended_by = relationship("Recommendation", back_populates="product")
    
    # インデックス
    __table_args__ = (
        Index('idx_seller_status', 'seller_id', 'status'),
        Index('idx_category_status', 'category', 'status'),
    )

class Purchase(Base):
    __tablename__ = "purchases"
    
    id = Column(Integer, primary_key=True, index=True)
    buyer_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    price = Column(Integer, nullable=False)
    purchased_at = Column(DateTime, default=datetime.utcnow)
    
    # リレーション
    buyer = relationship("User", back_populates="purchases")
    product = relationship("Product", back_populates="purchases")

class UserView(Base):
    __tablename__ = "user_views"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    viewed_at = Column(DateTime, default=datetime.utcnow)
    
    # リレーション
    user = relationship("User", back_populates="views")
    product = relationship("Product", back_populates="views")
    
    # インデックス
    __table_args__ = (
        Index('idx_user_product_view', 'user_id', 'product_id'),
    )

class Like(Base):
    __tablename__ = "likes"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    liked_at = Column(DateTime, default=datetime.utcnow)
    
    # リレーション
    user = relationship("User", back_populates="likes")
    product = relationship("Product", back_populates="likes")
    
    # 同じユーザーが同じ商品をいいねできないようにするユニーク制約
    __table_args__ = (
        Index('idx_user_product_like', 'user_id', 'product_id', unique=True),
    )

class Recommendation(Base):
    __tablename__ = "recommendations"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    recommended_product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    score = Column(Float, nullable=False)
    recommendation_type = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # リレーション
    user = relationship("User", back_populates="recommendations")
    product = relationship("Product", back_populates="recommended_by", foreign_keys=[recommended_product_id])

