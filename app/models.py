from sqlalchemy import Column, Integer, String, Text, Float, DateTime, Enum, ForeignKey, Boolean, Index, JSON
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

    # 転売対策：累積スコア（最後の更新時点の値）と更新時刻。参照時に減衰させて使う。
    resale_score = Column(Float, default=0.0, nullable=False)
    resale_score_updated_at = Column(DateTime, nullable=True)
    resale_stage = Column(Integer, default=0, nullable=False)  # 0=通常 1=警告 2=制限
    resale_flagged_at = Column(DateTime, nullable=True)        # 段階1で本人に通知した時刻

    # プロフィール
    avatar_url = Column(Text(length=16777215), nullable=True)  # base64 data URI（プロフィール画像）
    bio = Column(Text, nullable=True)                          # 自己紹介文
    notifications_read_at = Column(DateTime, nullable=True)    # 通知を最後に開いた時刻（既読管理）

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
    condition = Column(String(50), nullable=True)
    image_url = Column(Text(length=16777215))  # 一覧・カード用のサムネ（先頭画像）。Base64 data URI も格納できるよう MEDIUMTEXT
    image_urls = Column(JSON, nullable=True)  # 全画像（最大5枚）の data URI 配列。詳細ページ用。先頭が image_url と一致
    status = Column(Enum(ProductStatus), default=ProductStatus.available, index=True)
    embedding = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 転売対策：この出品のスコア／買い手向けバッジ／公開導線からの非表示フラグ
    resale_score = Column(Float, nullable=True)             # この1出品の0-100スコア（未判定はNULL）
    resale_flagged = Column(Boolean, default=False, nullable=False, index=True)   # 段階1: バッジ表示
    hidden_by_penalty = Column(Boolean, default=False, nullable=False, index=True)  # 段階2: 公開導線から非表示

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


class ResaleAssessment(Base):
    """出品ごとの転売判定結果（シグナル内訳・監査用）。

    内訳はユーザーには非開示だが、運営確認・発表説明・減衰計算の原資として保持する。
    """
    __tablename__ = "resale_assessments"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True, index=True)
    score = Column(Float, nullable=False)            # この出品の0-100スコア
    # 主シグナル（ゲート）
    is_new = Column(Boolean, default=False)
    is_mass_produced = Column(Boolean, default=False)
    gate_passed = Column(Boolean, default=False)
    # 補助シグナル
    dup_count = Column(Integer, default=0)           # 同一商品の重複出品数
    recent_count = Column(Integer, default=0)        # 直近の新品出品数
    list_price = Column(Integer, nullable=True)      # 取得した定価
    price_ratio = Column(Float, nullable=True)       # 出品価格 / 定価
    price_confidence = Column(Float, nullable=True)  # 定価情報の確信度 0-1
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    # インデックス（ユーザー単位＋時系列で減衰計算しやすく）
    __table_args__ = (
        Index('idx_resale_user_created', 'user_id', 'created_at'),
    )


class Comment(Base):
    """商品への質問・コメント（購入前のQ&A）。"""
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    user = relationship("User")
    product = relationship("Product")

    __table_args__ = (
        Index('idx_comments_product_created', 'product_id', 'created_at'),
    )

