from fastapi import APIRouter

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/logout")
def logout():
    """ログアウト（実質的にはフロントで完結）"""
    return {"message": "Logged out successfully"}