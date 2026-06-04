import json
import os
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List
from app.models import Product, UserView, Like, Purchase, ProductStatus

# ==================== 学習済みモデルの読み込み ====================

_SIMILARITY_PATH = os.path.join(os.path.dirname(__file__), "category_similarity.json")

def _load_similarity() -> dict:
    """category_similarity.json を読み込む。なければ空の辞書を返す"""
    if os.path.exists(_SIMILARITY_PATH):
        with open(_SIMILARITY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

# 起動時に1回だけ読み込む
CATEGORY_SIMILARITY = _load_similarity()


# ==================== メイン推薦関数 ====================

def recommend_by_category(
    db: Session, user_id: int, limit: int = 10
) -> List[Product]:
    """
    MerRecで学習したカテゴリ共起スコアを使ってレコメンドする。
    category_similarity.json がない場合はフォールバックとして新着順を返す。
    """
    # 購入済み商品IDを除外リストに
    purchased_ids = [
        r[0]
        for r in db.query(Purchase.product_id)
        .filter(Purchase.buyer_id == user_id)
        .all()
    ]

    # ユーザーの閲覧カテゴリを頻度付きで取得
    viewed = (
        db.query(Product.category, func.count(UserView.id).label("cnt"))
        .join(UserView, UserView.product_id == Product.id)
        .filter(UserView.user_id == user_id)
        .group_by(Product.category)
        .all()
    )

    # ユーザーのいいねカテゴリを頻度付きで取得（いいねは×5の重み）
    liked = (
        db.query(Product.category, func.count(Like.id).label("cnt"))
        .join(Like, Like.product_id == Product.id)
        .filter(Like.user_id == user_id)
        .group_by(Product.category)
        .all()
    )

    # ユーザーの行動からカテゴリスコアを集計
    user_cat_scores: dict[str, float] = {}
    for cat, cnt in viewed:
        if cat:
            user_cat_scores[cat] = user_cat_scores.get(cat, 0) + cnt
    for cat, cnt in liked:
        if cat:
            user_cat_scores[cat] = user_cat_scores.get(cat, 0) + cnt * 5

    if not user_cat_scores:
        # 行動履歴がない場合は新着商品を返す
        return _recommend_popular(db, user_id, limit, purchased_ids)

    # MerRecの共起スコアで「推薦カテゴリスコア」を計算
    recommend_cat_scores: dict[str, float] = {}

    if CATEGORY_SIMILARITY:
        # 学習済みデータがある場合：共起スコアで拡張
        for user_cat, user_score in user_cat_scores.items():
            related = CATEGORY_SIMILARITY.get(user_cat, {})
            for rec_cat, sim_score in related.items():
                recommend_cat_scores[rec_cat] = (
                    recommend_cat_scores.get(rec_cat, 0) + user_score * sim_score
                )
    else:
        # 学習済みデータがない場合：閲覧カテゴリをそのまま使う
        recommend_cat_scores = user_cat_scores

    # スコア上位3カテゴリに絞る
    top_categories = sorted(
        recommend_cat_scores, key=lambda c: recommend_cat_scores[c], reverse=True
    )[:3]

    # 対象カテゴリの商品をDBから取得
    query = (
        db.query(Product)
        .filter(
            Product.status == ProductStatus.available,
            Product.seller_id != user_id,
            Product.category.in_(top_categories),
        )
    )
    if purchased_ids:
        query = query.filter(Product.id.notin_(purchased_ids))

    products = query.order_by(Product.created_at.desc()).limit(limit).all()

    # 足りなければ「ユーザーの興味カテゴリ内」だけで補完する。
    # （無関係な新着＝今は本・漫画でそのまま埋めない）
    if len(products) < limit:
        shown_ids = [p.id for p in products]
        exclude_ids = purchased_ids + shown_ids
        # 実際に見た/いいねしたカテゴリ ＋ 共起で選ばれた上位カテゴリ
        interest_categories = list(set(top_categories) | set(user_cat_scores.keys()))

        supp_query = db.query(Product).filter(
            Product.status == ProductStatus.available,
            Product.seller_id != user_id,
            Product.category.in_(interest_categories),
        )
        if exclude_ids:
            supp_query = supp_query.filter(Product.id.notin_(exclude_ids))

        supplements = (
            supp_query.order_by(Product.created_at.desc())
            .limit(limit - len(products))
            .all()
        )
        products.extend(supplements)

    return products


def _recommend_popular(
    db: Session, user_id: int, limit: int, exclude_ids: List[int]
) -> List[Product]:
    """新着商品を返すフォールバック"""
    query = db.query(Product).filter(
        Product.status == ProductStatus.available,
        Product.seller_id != user_id,
    )
    if exclude_ids:
        query = query.filter(Product.id.notin_(exclude_ids))
    return query.order_by(Product.created_at.desc()).limit(limit).all()
