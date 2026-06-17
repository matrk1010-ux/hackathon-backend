from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.models import User, Product, ProductStatus
from app.schemas import UserCreate, UserResponse, UserUpdate, SellerProfileResponse
from app.ml.resale import current_user_stage

router = APIRouter(prefix="/users", tags=["users"])

MAX_USERNAME_LEN = 50


@router.post("/sync", response_model=UserResponse)
def sync_user(user_data: UserCreate, db: Session = Depends(get_db)):
    """Firebase ログイン後にユーザーをDBと同期する（存在しなければ作成）"""
    existing = db.query(User).filter(User.email == user_data.email).first()
    if existing:
        return existing

    new_user = User(
        username=user_data.username,
        email=user_data.email,
        password_hash="firebase_auth",
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


@router.get("/me", response_model=UserResponse)
def get_me(email: str, db: Session = Depends(get_db)):
    """メールアドレスからログイン中のユーザーを取得"""
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.patch("/me", response_model=UserResponse)
def update_me(email: str, user_update: UserUpdate, db: Session = Depends(get_db)):
    """本人（メールで識別）のプロフィールを更新する。現状はユーザー名のみ。"""
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if user_update.username is not None:
        new_name = user_update.username.strip()
        if not new_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ユーザー名を入力してください",
            )
        if len(new_name) > MAX_USERNAME_LEN:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"ユーザー名は{MAX_USERNAME_LEN}文字以内にしてください",
            )
        # ユーザー名は一意。自分以外が同名を使っていれば 409 で弾く
        dup = (
            db.query(User)
            .filter(User.username == new_name, User.id != user.id)
            .first()
        )
        if dup:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="このユーザー名は既に使われています",
            )
        user.username = new_name

    if user_update.avatar_url is not None:
        # 空文字なら画像クリア
        user.avatar_url = user_update.avatar_url or None
    if user_update.bio is not None:
        user.bio = (user_update.bio.strip()[:300]) or None

    user.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(user)
    return user


@router.get("/seller-profile/{email}", response_model=SellerProfileResponse)
def get_seller_profile(email: str, db: Session = Depends(get_db)):
    """出品者プロフィール（出品者ページのヘッダー用）。出品数・売却数・転売段階を返す。"""
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    active_count = (
        db.query(func.count(Product.id))
        .filter(
            Product.seller_id == user.id,
            Product.status == ProductStatus.available,
            Product.hidden_by_penalty == False,  # noqa: E712
        )
        .scalar()
        or 0
    )
    sold_count = (
        db.query(func.count(Product.id))
        .filter(Product.seller_id == user.id, Product.status == ProductStatus.sold)
        .scalar()
        or 0
    )
    return SellerProfileResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        created_at=user.created_at,
        active_count=active_count,
        sold_count=sold_count,
        resale_stage=current_user_stage(user),
        avatar_url=user.avatar_url,
        bio=user.bio,
    )


@router.get("/{user_id}", response_model=UserResponse)
def get_user(user_id: int, db: Session = Depends(get_db)):
    """IDからユーザーを取得"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user
