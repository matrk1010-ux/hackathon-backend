from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime
from enum import Enum

# ==================== Enum ====================

class ProductStatusSchema(str, Enum):
    available = "available"
    sold = "sold"
    removed = "removed"

class RecommendationTypeSchema(str, Enum):
    category_based = "category_based"
    price_based = "price_based"
    collaborative = "collaborative"
    sequential = "sequential"

# ==================== User Schemas ====================

class UserBase(BaseModel):
    username: str
    email: EmailStr

class UserCreate(UserBase):
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

class UserUpdate(BaseModel):
    username: Optional[str] = None  # 取引時の表示名。本人がマイページで変更できる
    avatar_url: Optional[str] = None  # プロフィール画像（base64 data URI）
    bio: Optional[str] = None         # 自己紹介文

class UserResponse(UserBase):
    id: int
    created_at: datetime
    updated_at: datetime
    avatar_url: Optional[str] = None
    bio: Optional[str] = None

    class Config:
        from_attributes = True

class UserWithProducts(UserResponse):
    products: List['ProductResponse'] = []

class SellerProfileResponse(BaseModel):
    """出品者プロフィールページ用。出品数・売却数・転売段階を含む。"""
    id: int
    username: str
    email: EmailStr
    created_at: datetime
    active_count: int = 0   # 出品中（公開）の商品数
    sold_count: int = 0     # 売却済みの商品数
    resale_stage: int = 0   # 0=通常 1=警告 2=制限（買い手への注意表示に使う）
    avatar_url: Optional[str] = None  # プロフィール画像
    bio: Optional[str] = None         # 自己紹介文

# ==================== Product Schemas ====================

class ProductBase(BaseModel):
    title: str
    description: Optional[str] = None
    price: int
    category: Optional[str] = None
    condition: Optional[str] = None
    image_url: Optional[str] = None

class ProductCreate(ProductBase):
    image_urls: Optional[List[str]] = None  # 出品時の全画像（最大5枚）。先頭が image_url に採用される

class ProductUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    price: Optional[int] = None
    category: Optional[str] = None
    condition: Optional[str] = None
    image_url: Optional[str] = None
    image_urls: Optional[List[str]] = None
    status: Optional[ProductStatusSchema] = None

class ProductResponse(ProductBase):
    # 注意: 一覧・検索・推薦で使うため image_urls（全画像）は含めない。
    # 全画像を載せると 20件×最大5枚のbase64でレスポンスが肥大化し検索が遅くなる。
    # サムネは image_url（先頭1枚）のみ。全画像が要る詳細は ProductWithSeller を使う。
    id: int
    seller_id: int
    status: ProductStatusSchema
    created_at: datetime
    updated_at: datetime
    resale_flagged: bool = False       # 段階1: 買い手向け「転売の可能性」バッジ
    hidden_by_penalty: bool = False    # 段階2: 公開導線から非表示（本人マイページ用）
    like_count: int = 0                # いいね総数（一覧で付与。未集計の経路では0）

    class Config:
        from_attributes = True

class ProductWithSeller(ProductResponse):
    seller: UserResponse
    image_urls: Optional[List[str]] = None  # 詳細ページ用の全画像
    view_count: int = 0                # 閲覧総数（詳細でのみ付与）

# ==================== Purchase Schemas ====================

class PurchaseBase(BaseModel):
    product_id: int

class PurchaseCreate(PurchaseBase):
    pass

class PurchaseResponse(BaseModel):
    id: int
    buyer_id: int
    product_id: int
    price: int
    purchased_at: datetime
    
    class Config:
        from_attributes = True

class PurchaseWithDetails(PurchaseResponse):
    product: ProductResponse
    buyer: UserResponse

# ==================== UserView Schemas ====================

class UserViewCreate(BaseModel):
    product_id: int

class UserViewResponse(BaseModel):
    id: int
    user_id: int
    product_id: int
    viewed_at: datetime
    
    class Config:
        from_attributes = True

# ==================== Like Schemas ====================

class LikeCreate(BaseModel):
    product_id: int

class LikeResponse(BaseModel):
    id: int
    user_id: int
    product_id: int
    liked_at: datetime
    
    class Config:
        from_attributes = True

# ==================== Comment Schemas ====================

class CommentCreate(BaseModel):
    body: str

class CommentResponse(BaseModel):
    id: int
    product_id: int
    user_id: int
    username: str       # 表示名（join で付与）
    body: str
    created_at: datetime

    class Config:
        from_attributes = True

# ==================== Recommendation Schemas ====================

class RecommendationCreate(BaseModel):
    user_id: int
    recommended_product_id: int
    score: float
    recommendation_type: Optional[RecommendationTypeSchema] = None

class RecommendationResponse(BaseModel):
    id: int
    user_id: int
    recommended_product_id: int
    score: float
    recommendation_type: Optional[str]
    created_at: datetime
    
    class Config:
        from_attributes = True

class RecommendationWithProduct(RecommendationResponse):
    product: ProductResponse

# ==================== Auth Schemas ====================

class Token(BaseModel):
    access_token: str
    token_type: str
    user: UserResponse

class TokenData(BaseModel):
    username: Optional[str] = None

# ==================== Generic Schemas ====================

class ListResponse(BaseModel):
    total: int
    items: List[dict]

class ErrorResponse(BaseModel):
    detail: str
    status_code: int

# ==================== AI/Recommendation Schemas ====================

class RecommendationRequest(BaseModel):
    user_id: int
    limit: int = 10
    recommendation_type: Optional[RecommendationTypeSchema] = None

class RecommendationBatchResponse(BaseModel):
    user_id: int
    recommendations: List[RecommendationWithProduct]
    total_count: int

# Update forward references
UserWithProducts.update_forward_refs()
ProductWithSeller.update_forward_refs()
PurchaseWithDetails.update_forward_refs()
RecommendationWithProduct.update_forward_refs()
