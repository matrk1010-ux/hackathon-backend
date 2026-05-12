from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User
from app.schemas import UserCreate, UserResponse

router = APIRouter(prefix="/users", tags=["users"])


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


@router.get("/{user_id}", response_model=UserResponse)
def get_user(user_id: int, db: Session = Depends(get_db)):
    """IDからユーザーを取得"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user
