import json
import os
import time
import numpy as np
from sqlalchemy.orm import Session, defer
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

# ハイブリッドスコアの重み（カテゴリ共起 × embedding類似度 × 価格帯近接）。合計1.0。
CAT_WEIGHT = 0.35   # α: カテゴリ共起スコア（多様性・文脈）
EMB_WEIGHT = 0.50   # β: embedding類似度（アイテム単位の好み）
PRICE_WEIGHT = 0.15  # γ: ユーザーがよく見る価格帯への近さ

# 行動シグナルの重み（嗜好ベクトル作成時）
VIEW_WEIGHT = 1.0
LIKE_WEIGHT = 5.0
# 嗜好ベクトルに使う行動履歴の上限（直近のみ）。
# 履歴全件の3072次元embeddingをロード＆パースすると毎回数十秒かかるため、
# 直近の行動だけを使う。recency重視は推薦としても自然。
TASTE_LIKE_LIMIT = 100
TASTE_VIEW_LIMIT = 200
# 候補プールの上限（embedding再ランクの計算対象）
# 1件あたり3072次元のJSON embeddingをロード＆パースするため、
# 大きいと再ランクが重くなる。精度を大きく落とさない範囲で控えめに設定。
CANDIDATE_POOL = 100  # 再ランクのembeddingパース量を抑えるため控えめに（150→100）

# 推薦結果のキャッシュ（無カテゴリのパーソナライズ経路のみ）。
# embeddingロード＋再ランクが重いため、ユーザー単位でキャッシュして
# 2回目以降を即時化する。TTL内はいいね/閲覧が反映されない点に注意（デモ用途では許容）。
# 一度温まれば長く効くよう TTL を延長（プロセス内キャッシュなのでインスタンス毎）。
REC_CACHE_TTL = 1800  # 秒（30分）
_REC_CACHE: dict = {}


def _get_cached_rec(user_id: int, limit: int):
    entry = _REC_CACHE.get((user_id, limit))
    if not entry:
        return None
    ts, products = entry
    if time.time() - ts > REC_CACHE_TTL:
        _REC_CACHE.pop((user_id, limit), None)
        return None
    return products


def _set_cached_rec(user_id: int, limit: int, products: list):
    _REC_CACHE[(user_id, limit)] = (time.time(), products)


def _build_taste_vector(db: Session, user_id: int) -> Optional[np.ndarray]:
    """ユーザーが見た/いいねした商品のembeddingを重み付き平均し、嗜好ベクトルを作る。
    embedding付きの行動が1つも無ければ None を返す。"""
    weighted_sum = None
    total_weight = 0.0

    # いいねした商品（強いシグナル）。直近 TASTE_LIKE_LIMIT 件のみ。
    liked_products = (
        db.query(Product.embedding)
        .join(Like, Like.product_id == Product.id)
        .filter(Like.user_id == user_id, Product.embedding.isnot(None))
        .order_by(Like.liked_at.desc())
        .limit(TASTE_LIKE_LIMIT)
        .all()
    )
    # 閲覧した商品（弱いシグナル）。直近 TASTE_VIEW_LIMIT 件のみ。
    viewed_products = (
        db.query(Product.embedding)
        .join(UserView, UserView.product_id == Product.id)
        .filter(UserView.user_id == user_id, Product.embedding.isnot(None))
        .order_by(UserView.viewed_at.desc())
        .limit(TASTE_VIEW_LIMIT)
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


def _build_taste_price(db: Session, user_id: int) -> Optional[float]:
    """嗜好の中心価格＝閲覧/いいねした商品の重み付き平均価格（直近のみ）。
    価格付きの行動が無ければ None を返す。"""
    liked = (
        db.query(Product.price)
        .join(Like, Like.product_id == Product.id)
        .filter(Like.user_id == user_id)
        .order_by(Like.liked_at.desc())
        .limit(TASTE_LIKE_LIMIT)
        .all()
    )
    viewed = (
        db.query(Product.price)
        .join(UserView, UserView.product_id == Product.id)
        .filter(UserView.user_id == user_id)
        .order_by(UserView.viewed_at.desc())
        .limit(TASTE_VIEW_LIMIT)
        .all()
    )
    num = 0.0
    den = 0.0
    for (price,), weight in (
        [(row, LIKE_WEIGHT) for row in liked]
        + [(row, VIEW_WEIGHT) for row in viewed]
    ):
        if not price or price <= 0:
            continue
        num += float(price) * weight
        den += weight
    return (num / den) if den > 0 else None


def _price_proximity(price: Optional[int], taste_price: Optional[float]) -> float:
    """価格帯の近さを [0,1] で返す。嗜好価格と同じ＝1.0、約3倍/3分の1で0。
    価格比の対数で測るため、安い帯でも高い帯でも対称に効く。"""
    if not price or not taste_price or price <= 0 or taste_price <= 0:
        return 0.0
    ratio = abs(np.log(float(price) / taste_price)) / np.log(3.0)
    return float(max(0.0, 1.0 - min(1.0, ratio)))


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
        cat_query = db.query(Product).options(defer(Product.embedding)).filter(
            Product.status == ProductStatus.available,
            Product.hidden_by_penalty == False,  # noqa: E712
            Product.seller_id != user_id,
            Product.category == category,
        )
        if purchased_ids:
            cat_query = cat_query.filter(Product.id.notin_(purchased_ids))
        return cat_query.order_by(Product.created_at.desc()).limit(limit).all()

    # --- 無カテゴリ＝パーソナライズ推薦（重い）。ユーザー単位で短時間キャッシュ ---
    cached = _get_cached_rec(user_id, limit)
    if cached is not None:
        return cached
    result = _recommend_personalized(db, user_id, limit, purchased_ids)
    _set_cached_rec(user_id, limit, result)
    return result


def _recommend_personalized(
    db: Session, user_id: int, limit: int, purchased_ids: List[int]
) -> List[Product]:
    """嗜好ベクトル × カテゴリ共起によるパーソナライズ推薦（無カテゴリ経路の本体）。"""
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
        taste_price = _build_taste_price(db, user_id)
        reranked = _hybrid_rerank(
            db, user_id, limit, purchased_ids,
            recommend_cat_scores, user_cat_scores, top_categories, taste_vec, taste_price,
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

        cat_query = db.query(Product).options(defer(Product.embedding)).filter(
            Product.status == ProductStatus.available,
            Product.hidden_by_penalty == False,  # noqa: E712
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

        supp_query = db.query(Product).options(defer(Product.embedding)).filter(
            Product.status == ProductStatus.available,
            Product.hidden_by_penalty == False,  # noqa: E712
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
    taste_price: Optional[float] = None,
) -> List[Product]:
    """興味カテゴリの候補プールを、カテゴリ共起 × embedding類似度 × 価格帯近接で再ランクする"""
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
    #
    # 重要：embedding（3072次元のJSON）を ORDER BY created_at と同じクエリで引くと、
    # (category,status,created_at) の複合インデックスが無いため MySQL が filesort し、
    # その際に巨大な embedding を sort buffer に載せてカテゴリ全件をソートするので
    # 数百件で数十秒かかる。そこで「並べ替え＋件数制限」は小さいカラム(id)だけで行い、
    # embedding は確定した候補IDに対して主キー一括取得（ソート無し）で別途読む。
    per_cat = max(25, CANDIDATE_POOL // max(1, len(interest_categories)))
    cand_cats: dict[int, str] = {}  # id -> category（候補の順序保持用）
    cand_price: dict[int, int] = {}  # id -> price（価格帯近接の計算用）
    cand_order: list[int] = []
    for cat in interest_categories:
        q = db.query(Product.id, Product.category, Product.price).filter(
            Product.status == ProductStatus.available,
            Product.hidden_by_penalty == False,  # noqa: E712
            Product.seller_id != user_id,
            Product.category == cat,
        )
        if purchased_ids:
            q = q.filter(Product.id.notin_(purchased_ids))
        for pid, pcat, pprice in q.order_by(Product.created_at.desc()).limit(per_cat).all():
            if pid not in cand_cats:
                cand_cats[pid] = pcat
                cand_price[pid] = pprice
                cand_order.append(pid)

    # 確定した候補IDの embedding を主キーで一括取得（ORDER BY 無し＝filesortしない）
    emb_by_id: dict[int, list] = {}
    if cand_order:
        for pid, pemb in (
            db.query(Product.id, Product.embedding)
            .filter(Product.id.in_(cand_order))
            .all()
        ):
            emb_by_id[pid] = pemb

    candidates = [
        (pid, cand_cats[pid], emb_by_id.get(pid)) for pid in cand_order
    ]

    if not candidates:
        return []

    # カテゴリ共起スコアを [0,1] に正規化（embedding類似度とスケールを揃える）
    max_cat = max(recommend_cat_scores.values()) if recommend_cat_scores else 1.0
    max_cat = max_cat or 1.0

    scored = []
    for pid, pcat, pemb in candidates:
        cat_component = recommend_cat_scores.get(pcat, 0.0) / max_cat
        emb_component = _cosine(taste_vec, pemb) if pemb else 0.0
        emb_component = max(0.0, emb_component)  # 負の類似度は0に
        price_component = _price_proximity(cand_price.get(pid), taste_price)
        score = (
            CAT_WEIGHT * cat_component
            + EMB_WEIGHT * emb_component
            + PRICE_WEIGHT * price_component
        )
        scored.append((score, pid))

    scored.sort(key=lambda x: x[0], reverse=True)
    top_ids = [pid for _, pid in scored[:limit]]

    # 最終表示する上位だけ Product 本体を取得し、スコア順を保って返す
    # （embedding はスコア計算済みで応答に不要なので defer）
    objs = db.query(Product).options(defer(Product.embedding)).filter(Product.id.in_(top_ids)).all()
    by_id = {p.id: p for p in objs}
    return [by_id[i] for i in top_ids if i in by_id]


# 似た商品（商品詳細ページ）の候補プール上限。
# この商品の embedding と全候補のコサイン類似度を取るため、
# 大きすぎると 3072 次元 embedding のロード＆計算が重くなる。
SIMILAR_POOL = 200


def recommend_similar_products(
    db: Session, product_id: int, limit: int = 4
) -> List[Product]:
    """商品詳細ページ用の「この商品に似た商品」。
    対象商品の embedding に対してコサイン類似度が高い順に返す。
    embedding が無い／候補が組めない場合は同カテゴリ新着でフォールバックする。
    出品中のみ・自分自身は除外。パーソナライズはしない（純粋なアイテム類似度）。"""
    base = db.query(Product).filter(Product.id == product_id).first()
    if not base:
        return []

    def _fallback() -> List[Product]:
        # 同カテゴリの出品中・新着（自分を除く）でフォールバック
        q = db.query(Product).options(defer(Product.embedding)).filter(
            Product.status == ProductStatus.available,
            Product.hidden_by_penalty == False,  # noqa: E712
            Product.id != product_id,
        )
        if base.category:
            q = q.filter(Product.category == base.category)
        return q.order_by(Product.created_at.desc()).limit(limit).all()

    base_emb = base.embedding
    if not base_emb:
        return _fallback()

    base_vec = np.array(base_emb, dtype=float)
    base_norm = np.linalg.norm(base_vec)
    if base_norm == 0:
        return _fallback()
    base_vec = base_vec / base_norm

    # 候補プール：出品中で embedding を持つ商品（自分を除く）。
    # 同カテゴリを優先し、足りなければ他カテゴリの新着で補う。
    cand_ids: list[int] = []
    seen: set[int] = {product_id}

    def _collect(query, room: int):
        for (pid,) in query.order_by(Product.created_at.desc()).limit(room).all():
            if pid not in seen:
                seen.add(pid)
                cand_ids.append(pid)

    base_q = db.query(Product.id).filter(
        Product.status == ProductStatus.available,
        Product.hidden_by_penalty == False,  # noqa: E712
        Product.embedding.isnot(None),
        Product.id != product_id,
    )
    if base.category:
        _collect(base_q.filter(Product.category == base.category), SIMILAR_POOL)
    if len(cand_ids) < SIMILAR_POOL:
        _collect(base_q, SIMILAR_POOL - len(cand_ids))

    if not cand_ids:
        return _fallback()

    # 候補の embedding を主キー一括取得（ソート無し）してコサイン類似度を計算
    scored: list[tuple[float, int]] = []
    for pid, pemb in (
        db.query(Product.id, Product.embedding)
        .filter(Product.id.in_(cand_ids))
        .all()
    ):
        sim = _cosine(base_vec, pemb)
        scored.append((sim, pid))

    if not scored:
        return _fallback()

    scored.sort(key=lambda x: x[0], reverse=True)
    top_ids = [pid for _, pid in scored[:limit]]
    objs = db.query(Product).options(defer(Product.embedding)).filter(Product.id.in_(top_ids)).all()
    by_id = {p.id: p for p in objs}
    result = [by_id[i] for i in top_ids if i in by_id]
    return result if result else _fallback()


def _recommend_popular(
    db: Session, user_id: int, limit: int, exclude_ids: List[int]
) -> List[Product]:
    """新着商品を返すフォールバック"""
    query = db.query(Product).options(defer(Product.embedding)).filter(
        Product.status == ProductStatus.available,
        Product.hidden_by_penalty == False,  # noqa: E712
        Product.seller_id != user_id,
    )
    if exclude_ids:
        query = query.filter(Product.id.notin_(exclude_ids))
    return query.order_by(Product.created_at.desc()).limit(limit).all()
