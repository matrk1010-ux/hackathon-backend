import json
import os
import numpy as np
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
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

# ハイブリッドスコアの重み（カテゴリ共起 と embedding類似度 の配合）
CAT_WEIGHT = 0.4   # α: カテゴリ共起スコア（多様性・文脈）
EMB_WEIGHT = 0.6   # β: embedding類似度（アイテム単位の好み）

# 行動シグナルの重み（嗜好ベクトル作成時）
VIEW_WEIGHT = 1.0
LIKE_WEIGHT = 5.0
# 候補プールの上限（embedding再ランクの計算対象）
CANDIDATE_POOL = 300


def _build_taste_vector(db: Session, user_id: int) -> Optional[np.ndarray]:
    """ユーザーが見た/いいねした商品のembeddingを重み付き平均し、嗜好ベクトルを作る。
    embedding付きの行動が1つも無ければ None を返す。"""
    weighted_sum = None
    total_weight = 0.0

    # いいねした商品（強いシグナル）
    liked_products = (
        db.query(Product.embedding)
        .join(Like, Like.product_id == Product.id)
        .filter(Like.user_id == user_id, Product.embedding.isnot(None))
        .all()
    )
    # 閲覧した商品（弱いシグナル）
    viewed_products = (
        db.query(Product.embedding)
        .join(UserView, UserView.product_id == Product.id)
        .filter(UserView.user_id == user_id, Product.embedding.isnot(None))
        .all()
    )

    for (emb,), weight in (
        [(row, LIKE_WEIGHT) for row in liked_products]
        + [(row, VIEW_WEIGHT) for row in viewed_products]
    ):
        if not emb:
            continue
        vec = np.array(emb, dtype=float)
        weighted_sum = vec * weight if weighted_sum is None else weighted_sum + vec * weight
        total_weight += weight

    if weighted_sum is None or total_weight == 0:
        return None

    avg = weighted_sum / total_weight
    norm = np.linalg.norm(avg)
    return avg / norm if norm > 0 else None


def _cosine(vec: np.ndarray, emb: list) -> float:
    """正規化済み嗜好ベクトル vec と 商品embedding のコサイン類似度"""
    if not emb:
        return 0.0
    b = np.array(emb, dtype=float)
    nb = np.linalg.norm(b)
    if nb == 0:
        return 0.0
    return float(np.dot(vec, b) / nb)


# ==================== メイン推薦関数 ====================

def recommend_by_category(
    db: Session, user_id: int, limit: int = 10, category: str = None
) -> List[Product]:
    """
    MerRecで学習したカテゴリ共起スコアを使ってレコメンドする。
    category_similarity.json がない場合はフォールバックとして新着順を返す。
    category を指定した場合は、そのカテゴリの商品だけに絞ってレコメンドする。
    """
    # 購入済み商品IDを除外リストに
    purchased_ids = [
        r[0]
        for r in db.query(Purchase.product_id)
        .filter(Purchase.buyer_id == user_id)
        .all()
    ]

    # カテゴリ指定時は、そのカテゴリ内の出品から（自分・購入済みを除く）新着順で返す
    if category:
        cat_query = db.query(Product).filter(
            Product.status == ProductStatus.available,
            Product.seller_id != user_id,
            Product.category == category,
        )
        if purchased_ids:
            cat_query = cat_query.filter(Product.id.notin_(purchased_ids))
        return cat_query.order_by(Product.created_at.desc()).limit(limit).all()

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

    # --- A+B: 嗜好ベクトルがあれば embedding × カテゴリ共起 のハイブリッドで再ランク ---
    taste_vec = _build_taste_vector(db, user_id)
    if taste_vec is not None:
        reranked = _hybrid_rerank(
            db, user_id, limit, purchased_ids,
            recommend_cat_scores, user_cat_scores, top_categories, taste_vec,
        )
        if reranked:
            return reranked
        # 万一候補が組めなければ従来ロジックにフォールバック

    # カテゴリスコアに比例して各カテゴリの枠数を割り当てる。
    # （全カテゴリを一括の新着順にすると、最近大量投入したカテゴリが枠を
    #   独占してしまうため。スコアの高いカテゴリほど多く出す）
    total_score = sum(recommend_cat_scores[c] for c in top_categories) or 1
    products = []
    seen_ids = set(purchased_ids)

    for cat in top_categories:
        if len(products) >= limit:
            break
        quota = max(1, round(limit * recommend_cat_scores[cat] / total_score))
        quota = min(quota, limit - len(products))

        cat_query = db.query(Product).filter(
            Product.status == ProductStatus.available,
            Product.seller_id != user_id,
            Product.category == cat,
        )
        if seen_ids:
            cat_query = cat_query.filter(Product.id.notin_(list(seen_ids)))

        cat_products = (
            cat_query.order_by(Product.created_at.desc()).limit(quota).all()
        )
        for p in cat_products:
            products.append(p)
            seen_ids.add(p.id)

    # 足りなければ「ユーザーの興味カテゴリ内」だけで補完する。
    # （無関係な新着＝今は本・漫画でそのまま埋めない）
    if len(products) < limit:
        # 実際に見た/いいねしたカテゴリ ＋ 共起で選ばれた上位カテゴリ
        interest_categories = list(set(top_categories) | set(user_cat_scores.keys()))

        supp_query = db.query(Product).filter(
            Product.status == ProductStatus.available,
            Product.seller_id != user_id,
            Product.category.in_(interest_categories),
        )
        if seen_ids:
            supp_query = supp_query.filter(Product.id.notin_(list(seen_ids)))

        supplements = (
            supp_query.order_by(Product.created_at.desc())
            .limit(limit - len(products))
            .all()
        )
        products.extend(supplements)

    return products


def _hybrid_rerank(
    db: Session,
    user_id: int,
    limit: int,
    purchased_ids: List[int],
    recommend_cat_scores: dict,
    user_cat_scores: dict,
    top_categories: List[str],
    taste_vec: np.ndarray,
) -> List[Product]:
    """興味カテゴリの候補プールを、カテゴリ共起 × embedding類似度のハイブリッドで再ランクする"""
    # 候補とするカテゴリ＝共起で選ばれた全カテゴリ ＋ ユーザーが実際に触れたカテゴリ
    interest_categories = (
        set(recommend_cat_scores.keys())
        | set(user_cat_scores.keys())
        | set(top_categories)
    )
    interest_categories.discard(None)
    if not interest_categories:
        return []

    # カテゴリごとに新着を取得してプールに入れる。
    # （全カテゴリ一括の新着順だと、大量投入されたカテゴリが新しさで枠を独占し、
    #   好きなカテゴリの商品がプールから漏れてしまうため。各カテゴリの代表性を確保する）
    per_cat = max(50, CANDIDATE_POOL // max(1, len(interest_categories)))
    candidates = []
    seen_ids = set()
    for cat in interest_categories:
        q = db.query(Product).filter(
            Product.status == ProductStatus.available,
            Product.seller_id != user_id,
            Product.category == cat,
        )
        if purchased_ids:
            q = q.filter(Product.id.notin_(purchased_ids))
        for p in q.order_by(Product.created_at.desc()).limit(per_cat).all():
            if p.id not in seen_ids:
                candidates.append(p)
                seen_ids.add(p.id)

    if not candidates:
        return []

    # カテゴリ共起スコアを [0,1] に正規化（embedding類似度とスケールを揃える）
    max_cat = max(recommend_cat_scores.values()) if recommend_cat_scores else 1.0
    max_cat = max_cat or 1.0

    scored = []
    for p in candidates:
        cat_component = recommend_cat_scores.get(p.category, 0.0) / max_cat
        emb_component = _cosine(taste_vec, p.embedding) if p.embedding else 0.0
        emb_component = max(0.0, emb_component)  # 負の類似度は0に
        score = CAT_WEIGHT * cat_component + EMB_WEIGHT * emb_component
        scored.append((score, p))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in scored[:limit]]


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
