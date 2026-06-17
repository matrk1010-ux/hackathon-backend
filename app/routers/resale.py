"""転売対策の補助エンドポイント。

- /resale/assess/{product_id} : 判定の手動トリガ（BackgroundTasksが不安定な環境向けフォールバック）
- /resale/status/{user_email}  : 本人向けの段階表示（警告バナー用。検知ロジックは非開示）
- /resale/appeal               : 異議申し立て（スタブ。受付応答のみ・管理者審査フローは未実装）
- /resale/admin/set-score      : デモ用に累積スコアを直接設定し段階を発火させる
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import datetime

from app.database import get_db
from app.models import User
from app.ml import resale
from app import resale_config as cfg

router = APIRouter(prefix="/resale", tags=["resale"])


@router.post("/assess/{product_id}")
def assess(product_id: int, db: Session = Depends(get_db)):
    """指定出品の転売判定を同期実行する（フロントからの明示トリガ用）。"""
    result = resale.assess_product(db, product_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    # 内訳は非開示のため、最小限のみ返す
    return {"ok": True}


# ==================== TEMP: 生スコア読み出し（取得後に削除する一時エンドポイント） ====================

@router.get("/_temp/raw-score/{user_email}")
def _temp_raw_score(user_email: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    decayed = resale.decayed_score(user.resale_score or 0.0, user.resale_score_updated_at)
    return {
        "email": user.email,
        "raw_stored_score": user.resale_score,        # 最後の更新時点の値（減衰前）
        "decayed_now": round(decayed, 2),             # 参照時点の減衰後スコア（実効値）
        "stage": resale.current_user_stage(user),
        "score_updated_at": user.resale_score_updated_at,
    }


@router.get("/status/{user_email}")
def get_status(user_email: str, db: Session = Depends(get_db)):
    """本人向けの段階情報。検知ロジックや内訳は返さない。"""
    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    stage = resale.current_user_stage(user)
    return {
        "stage": stage,
        "flagged": stage >= 1,     # 段階1: 警告バナー＋買い手向けバッジ
        "restricted": stage >= 2,  # 段階2: 新規出品制限＋既存非表示
    }


class AppealRequest(BaseModel):
    user_email: str
    message: str = ""


@router.post("/appeal")
def submit_appeal(request: AppealRequest, db: Session = Depends(get_db)):
    """異議申し立て（スタブ）。受付応答のみ返す。管理者審査フローは今後の課題。"""
    user = db.query(User).filter(User.email == request.user_email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return {
        "received": True,
        "message": "異議申し立てを受け付けました。担当者が確認します（デモ版のため自動処理は行いません）。",
    }


class SetScoreRequest(BaseModel):
    user_email: str
    score: float


@router.post("/admin/set-score")
def admin_set_score(request: SetScoreRequest, db: Session = Depends(get_db)):
    """デモ用: 累積スコアを直接設定して段階を発火させる（減衰は当然この時点起算）。"""
    user = db.query(User).filter(User.email == request.user_email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    now = datetime.utcnow()
    user.resale_score = max(0.0, float(request.score))
    user.resale_score_updated_at = now
    if user.resale_score < cfg.STAGE1_THRESHOLD:
        user.resale_flagged_at = None
    db.commit()
    db.refresh(user)
    stage = resale.apply_stage_effects(db, user, now)
    db.commit()
    return {"user_email": user.email, "score": user.resale_score, "stage": stage}
