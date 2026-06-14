# 商品一覧取得ロジック（検索・フィルタ対応）
from sqlalchemy.orm import Session, defer
from sqlalchemy import text, func
from fastapi import HTTPException, status
from app.models import Product, User, ProductStatus, Like
from typing import List, Optional

def list_products(
    db: Session,
    skip: int = 0,
    limit: int = 10,
    category: Optional[str] = None,
    status_filter: Optional[str] = None,
    min_price: Optional[int] = None,
    max_price: Optional[int] = None,
    keyword: Optional[str] = None,
    condition: Optional[str] = None,
    sort: Optional[str] = None,
) -> List[Product]:
    """商品一覧を取得（検索・フィルタ・並び替え対応）"""
    # 転売対策・段階2: 公開導線では出品制限中ユーザーの商品を除外。
    # embedding（1件3072次元のJSON）は一覧では使わないので defer で読み込まない
    # （AIセット用に後埋め後、全カラム読みで一覧が激重になっていた）。
    query = db.query(Product).options(defer(Product.embedding)).filter(
        Product.status == ProductStatus.available,
        Product.hidden_by_penalty == False,  # noqa: E712
    )

    # カテゴリでフィルタ
    if category:
        query = query.filter(Product.category == category)

    # 状態（コンディション）でフィルタ
    if condition:
        query = query.filter(Product.condition == condition)

    # ステータスでフィルタ
    if status_filter:
        try:
            status_enum = ProductStatus(status_filter)
            query = query.filter(Product.status == status_enum)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status. Must be one of: {', '.join([s.value for s in ProductStatus])}"
            )
    
    # キーワードでフィルタ（タイトル・説明文の部分一致）
    if keyword:
        kw = keyword.strip()
        if len(kw) >= 2:
            # 2文字以上は ngram FULLTEXT インデックスで高速検索（全件スキャン回避）。
            # BOOLEAN MODE では検索語をダブルクォートで囲みフレーズ検索にする。
            # こうしないと ngram が語を2文字ずつに分解し各bigramがOR扱いになって
            # 無関係な結果が大量に混じる。フレーズ検索なら「その語を丸ごと含む」=LIKE相当。
            # 語中のダブルクォートは構文を壊すので除去する。
            phrase = '"' + kw.replace('"', " ") + '"'
            query = query.filter(
                text("MATCH(products.title, products.description) AGAINST(:kw IN BOOLEAN MODE)")
            ).params(kw=phrase)
        else:
            # 1文字は ngram(2文字単位) では引けないため従来の LIKE にフォールバック。
            like_pattern = f"%{kw}%"
            query = query.filter(
                Product.title.like(like_pattern) | Product.description.like(like_pattern)
            )

    # 価格範囲でフィルタ
    if min_price is not None:
        query = query.filter(Product.price >= min_price)
    if max_price is not None:
        query = query.filter(Product.price <= max_price)

    # 並び替え（既定は新着順）
    if sort == "price_asc":
        query = query.order_by(Product.price.asc(), Product.id.desc())
    elif sort == "price_desc":
        query = query.order_by(Product.price.desc(), Product.id.desc())
    elif sort == "likes":
        # いいね数の多い順。MATCH 等の WHERE を壊さないよう集計はサブクエリで外付けする。
        like_sub = (
            db.query(Like.product_id, func.count(Like.id).label("cnt"))
            .group_by(Like.product_id)
            .subquery()
        )
        query = query.outerjoin(like_sub, like_sub.c.product_id == Product.id).order_by(
            func.coalesce(like_sub.c.cnt, 0).desc(), Product.created_at.desc()
        )
    else:  # newest（既定）
        query = query.order_by(Product.created_at.desc(), Product.id.desc())

    # ページネーション
    products = query.offset(skip).limit(limit).all()
    return products

def get_seller_products(
    db: Session,
    seller_email: str,
    skip: int = 0,
    limit: int = 10,
    public_only: bool = False,
) -> List[Product]:
    """特定の出品者の商品を取得。

    public_only=True のときは公開導線向けに、取り下げ済み(removed)と
    転売ペナルティで非表示中(hidden_by_penalty)の商品を除外する（出品中・売却済みのみ）。
    マイページ（本人）は全件見たいので既定は False。
    """
    seller = db.query(User).filter(User.email == seller_email).first()

    if not seller:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    q = db.query(Product).options(defer(Product.embedding)).filter(Product.seller_id == seller.id)
    if public_only:
        q = q.filter(
            Product.status != ProductStatus.removed,
            Product.hidden_by_penalty == False,  # noqa: E712
        )
    # 出品中→売却済みの順、各群は新着順
    products = (
        q.order_by(Product.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return products
