"""転売スコアの判定・蓄積・段階ペナルティのコアロジック。

設計思想：
- 主シグナル（ゲート）＝「新品 × 既製品」を両方満たすときだけ加点に進む。
- 補助シグナル＝大量出品 / 出品サイクル / 定価超え×確信度 で 0-100 を算出。
- 累積はユーザー単位で 30日半減の減衰付き。減衰は「参照時に計算」する（段階2でも
  出品試行のたびに再評価され、自己回復が機能する）。
- Gemini 呼び出しは失敗しても劣化動作（既存の embeddings.py と同じ思想）。
"""
import os
import re
import json
import math
from datetime import datetime, timedelta
from typing import Optional

import google.generativeai as genai
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import Product, User, ProductStatus, ResaleAssessment
from app.ml.embeddings import cosine_similarity
from app import resale_config as cfg


# ==================== Gemini ヘルパ（失敗時は劣化） ====================

def _get_model():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        genai.configure(api_key=api_key)
        return genai.GenerativeModel("gemini-2.5-flash")
    except Exception:
        return None


def _extract_json(raw: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {}


def assess_is_mass_produced(title: str, description: str, image_data_uri: Optional[str]) -> bool:
    """既製品か（ハンドメイド/自作/一点物でないか）を Gemini で判定。失敗時は True（＝ゲートを塞がない）。

    狙い：ハンドメイド作家の自作品をゲートで除外する。判定不能なら既製品扱いにして
    後段の補助シグナルに委ねる（補助が立たなければどのみち低スコア）。
    """
    model = _get_model()
    if model is None:
        return True
    prompt = f"""次のフリマ出品が「既製品（メーカー量産品）」か「ハンドメイド/自作/一点物（作家の手作り）」かを判定してください。
- 手作り・ハンドメイド・自作・オリジナル作品・一点物 と読み取れるなら is_mass_produced=false
- メーカーの量産品・既製品（本、ゲーム機、家電、ブランド既製服など）なら is_mass_produced=true
- 判断できないときは is_mass_produced=true（既製品寄り）にする

商品名: {title}
説明: {description or "（なし）"}

次のJSONのみ返す（説明やコードフェンス禁止）: {{"is_mass_produced": true/false}}"""
    try:
        parts = [prompt]
        if image_data_uri and image_data_uri.startswith("data:"):
            m = re.match(r"^data:(?P<mime>[^;]+);base64,(?P<data>.+)$", image_data_uri, re.DOTALL)
            if m:
                import base64
                parts.append({"mime_type": m.group("mime"), "data": base64.b64decode(m.group("data"))})
        resp = model.generate_content(parts)
        data = _extract_json(resp.text.strip())
        val = data.get("is_mass_produced")
        return True if val is None else bool(val)
    except Exception:
        return True


def estimate_list_price(title: str, category: Optional[str]) -> tuple:
    """定価とその確信度を Gemini の内部知識から推定する（初期版・グラウンディングなし）。

    返り値: (list_price:int|None, confidence:float 0-1)
    失敗・不明時は (None, 0.0) を返し、定価超えシグナルを無効化する。
    """
    model = _get_model()
    if model is None:
        return None, 0.0
    prompt = f"""次の商品の日本での新品「定価（メーカー希望小売価格や一般的な新品販売価格）」を推定してください。
- 確実に分かる有名商品のみ自信を持って答える。型番不明・無名・判断不能なら confidence を低くする。
- 中古相場ではなく「新品の定価」を答える。

商品名: {title}
カテゴリ: {category or "（不明）"}

次のJSONのみ返す（説明やコードフェンス禁止）:
{{"list_price": 整数(円)またはnull, "confidence": 0.0〜1.0}}"""
    try:
        resp = model.generate_content(prompt)
        data = _extract_json(resp.text.strip())
        lp = data.get("list_price")
        conf = data.get("confidence")
        list_price = int(lp) if isinstance(lp, (int, float)) and lp and lp > 0 else None
        confidence = float(conf) if isinstance(conf, (int, float)) else 0.0
        confidence = max(0.0, min(1.0, confidence))
        if list_price is None:
            confidence = 0.0
        return list_price, confidence
    except Exception:
        return None, 0.0


# ==================== 補助シグナル（DB集計） ====================

def _normalize_title(t: str) -> str:
    return re.sub(r"\s+", "", (t or "")).lower()


def count_duplicate_listings(db: Session, product: Product) -> int:
    """同一出品者の「同一商品」の総個数（この出品を含む）。

    embedding があれば類似度で、無ければ正規化タイトル一致で数える。
    既知リスク: シリーズ別巻も高類似のため誤って同一商品とみなしうる。
    """
    others = (
        db.query(Product)
        .filter(
            Product.seller_id == product.seller_id,
            Product.status == ProductStatus.available,
            Product.id != product.id,
        )
        .all()
    )
    same = 0
    if product.embedding:
        for o in others:
            if o.embedding and cosine_similarity(product.embedding, o.embedding) >= cfg.SAME_PRODUCT_SIM:
                same += 1
    else:
        norm = _normalize_title(product.title)
        for o in others:
            if _normalize_title(o.title) == norm:
                same += 1
    return same + 1  # この出品自身を含めた総個数


def count_recent_new_listings(db: Session, product: Product, now: datetime) -> int:
    """直近 CYCLE_WINDOW_DAYS 日の新品出品数（この出品を含む）。"""
    since = now - timedelta(days=cfg.CYCLE_WINDOW_DAYS)
    cnt = (
        db.query(Product)
        .filter(
            Product.seller_id == product.seller_id,
            Product.condition == cfg.NEW_CONDITION,
            Product.created_at >= since,
        )
        .count()
    )
    return max(cnt, 1)


# ==================== スコア化（0〜100） ====================

def _linear_score(value: float, lo: float, hi: float, max_score: float) -> float:
    if value <= lo:
        return 0.0
    if value >= hi:
        return max_score
    return (value - lo) / (hi - lo) * max_score


def _is_new(product: Product) -> bool:
    """新品ゲート: フォーム状態が主、説明文の新品語で弱く補強。"""
    if product.condition == cfg.NEW_CONDITION:
        return True
    desc = product.description or ""
    return any(kw in desc for kw in cfg.NEW_KEYWORDS)


def compute_listing_score(db: Session, product: Product, now: Optional[datetime] = None) -> dict:
    """1出品の転売スコアと内訳を計算する。"""
    now = now or datetime.utcnow()

    is_new = _is_new(product)
    breakdown = {
        "score": 0.0,
        "is_new": is_new,
        "is_mass_produced": False,
        "gate_passed": False,
        "dup_count": 0,
        "recent_count": 0,
        "list_price": None,
        "price_ratio": None,
        "price_confidence": None,
    }

    # ゲート①: 新品でなければ即終了（Gemini も呼ばない）
    if not is_new:
        return breakdown

    # ゲート②: 既製品か（Gemini）
    is_mass = assess_is_mass_produced(product.title, product.description or "", product.image_url)
    breakdown["is_mass_produced"] = is_mass
    if not is_mass:
        return breakdown

    breakdown["gate_passed"] = True

    # 補助①: 同一商品の大量出品（5個から加点・10個で満点に厳格化）
    dup_count = count_duplicate_listings(db, product)
    dup_score = _linear_score(dup_count, cfg.DUP_MIN_COUNT, cfg.DUP_FULL_COUNT, cfg.DUP_MAX_SCORE)
    breakdown["dup_count"] = dup_count

    # 補助②: 新品出品サイクル。断捨離での一括出品を誤検知しないよう単独では加点せず、
    #         ①③の根拠を裏付ける増幅係数(0〜1)として使う。
    recent_count = count_recent_new_listings(db, product, now)
    cycle_factor = _linear_score(recent_count, cfg.CYCLE_MIN_COUNT, cfg.CYCLE_FULL_COUNT, 1.0)
    breakdown["recent_count"] = recent_count

    # 補助③: 定価超え × 確信度
    list_price, confidence = estimate_list_price(product.title, product.category)
    price_score = 0.0
    if list_price and list_price > 0 and confidence >= cfg.PRICE_MIN_CONFIDENCE:
        ratio = product.price / list_price
        breakdown["price_ratio"] = round(ratio, 3)
        raw = _linear_score(ratio, cfg.PRICE_RATIO_MIN, cfg.PRICE_RATIO_FULL, cfg.PRICE_MAX_SCORE)
        price_score = raw * confidence
    breakdown["list_price"] = list_price
    breakdown["price_confidence"] = confidence

    # 核となる転売の根拠 = 同一商品の大量出品(①) ＋ 定価超え(③)。
    # どちらも無ければ、新品を多数・高頻度に出していても通常の出品として加点しない
    # （断捨離で一気に出す一般ユーザーを段階制裁から守る）。
    # ②(出品サイクル)は core がある時だけ、その疑いを増幅する裏付けとして効かせる。
    core = dup_score + price_score
    if core <= 0:
        score = 0.0
    else:
        score = cfg.BASE_SCORE + core * (1.0 + cfg.CYCLE_BOOST * cycle_factor)

    breakdown["score"] = round(max(0.0, min(100.0, score)), 2)
    return breakdown


# ==================== 累積スコアの蓄積（減衰） ====================

def decayed_score(score: float, updated_at: Optional[datetime], now: Optional[datetime] = None) -> float:
    """最後の更新からの経過で半減減衰させた現在の累積スコア（参照時計算）。"""
    if not score or score <= 0:
        return 0.0
    now = now or datetime.utcnow()
    if updated_at is None:
        return score
    elapsed_days = max(0.0, (now - updated_at).total_seconds() / 86400.0)
    return score * math.pow(0.5, elapsed_days / cfg.DECAY_HALF_LIFE_DAYS)


def current_user_stage(user: User, now: Optional[datetime] = None) -> int:
    """ユーザーの現在（減衰後）の段階を参照時に算出する。"""
    return cfg.stage_for_score(decayed_score(user.resale_score or 0.0, user.resale_score_updated_at, now))


def _atomic_accumulate(db: Session, user_id: int, delta: float, now: datetime) -> None:
    """旧スコアを経過分減衰させてから delta を加算（単一SQLでロストアップデート回避）。"""
    half_life_seconds = cfg.DECAY_HALF_LIFE_DAYS * 86400.0
    db.execute(
        text(
            "UPDATE users SET "
            "resale_score = resale_score * POW(0.5, "
            "  TIMESTAMPDIFF(SECOND, COALESCE(resale_score_updated_at, :now), :now) / :hl) "
            "  + :delta, "
            "resale_score_updated_at = :now "
            "WHERE id = :uid"
        ),
        {"now": now, "hl": half_life_seconds, "delta": delta, "uid": user_id},
    )


def apply_stage_effects(db: Session, user: User, now: Optional[datetime] = None) -> int:
    """現在の累積スコアから段階を再計算し、通知時刻・商品バッジ・非表示を反映する。

    返り値: 反映後の段階(0/1/2)。
    """
    now = now or datetime.utcnow()
    stage = current_user_stage(user, now)
    user.resale_stage = stage
    if stage >= 1 and user.resale_flagged_at is None:
        user.resale_flagged_at = now
    if stage < 1:
        user.resale_flagged_at = None

    # 出品中の商品へバッジ／非表示を一括反映（公開導線の表示に使う非正規化フラグ）
    flagged = 1 if stage >= 1 else 0
    hidden = 1 if stage >= 2 else 0
    db.execute(
        text(
            "UPDATE products SET resale_flagged = :f, hidden_by_penalty = :h "
            "WHERE seller_id = :uid AND status = 'available'"
        ),
        {"f": flagged, "h": hidden, "uid": user.id},
    )
    return stage


# ==================== オーケストレーション（背景タスクから呼ぶ） ====================

def assess_product(db: Session, product_id: int) -> Optional[dict]:
    """1出品を判定 → 監査保存 → 累積更新 → 段階反映までを実行する。"""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        return None
    seller = db.query(User).filter(User.id == product.seller_id).first()
    if not seller:
        return None

    now = datetime.utcnow()
    breakdown = compute_listing_score(db, product, now)
    score = breakdown["score"]

    # この出品のスコアを保存
    product.resale_score = score

    # 監査レコード
    db.add(ResaleAssessment(
        user_id=seller.id,
        product_id=product.id,
        score=score,
        is_new=breakdown["is_new"],
        is_mass_produced=breakdown["is_mass_produced"],
        gate_passed=breakdown["gate_passed"],
        dup_count=breakdown["dup_count"],
        recent_count=breakdown["recent_count"],
        list_price=breakdown["list_price"],
        price_ratio=breakdown["price_ratio"],
        price_confidence=breakdown["price_confidence"],
    ))

    # 累積へ加算（0点でも減衰だけは進めたいので常に実行）
    _atomic_accumulate(db, seller.id, score, now)
    db.commit()

    # 反映後のスコアを読み直して段階反映
    db.refresh(seller)
    apply_stage_effects(db, seller, now)
    db.commit()

    breakdown["user_score"] = round(decayed_score(seller.resale_score, seller.resale_score_updated_at, now), 2)
    breakdown["stage"] = seller.resale_stage
    return breakdown


def assess_product_in_background(product_id: int) -> None:
    """BackgroundTasks から呼ぶエントリ。専用セッションを張り、失敗は握り潰す。"""
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        assess_product(db, product_id)
    except Exception:
        db.rollback()
    finally:
        db.close()
