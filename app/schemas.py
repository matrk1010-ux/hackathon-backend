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

class UserResponse(UserBase):
    id: int
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

class UserWithProducts(UserResponse):
    products: List['ProductResponse'] = []

# ==================== Product Schemas ====================

class ProductBase(BaseModel):
    title: str
    description: Optional[str] = None
    price: int
    category: Optional[str] = None
    condition: Optional[str] = None
    image_url: Optional[str] = None

class ProductCreate(ProductBase):
    pass

class ProductUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    price: Optional[int] = None
    category: Optional[str] = None
    condition: Optional[str] = None
    image_url: Optional[str] = None
    status: Optional[ProductStatusSchema] = None

class ProductResponse(ProductBase):
    id: int
    seller_id: int
    status: ProductStatusSchema
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

class ProductWithSeller(ProductResponse):
    seller: UserResponse

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
