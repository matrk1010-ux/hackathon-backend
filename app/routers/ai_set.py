import os
import re
import json
import time
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
import numpy as np
from google import genai as genai_v2
from google.genai import types as genai_types

from app.database import get_db
from app.models import Product, ProductStatus
from app.schemas import ProductResponse
from app.ml.embeddings import get_embedding

router = APIRouter(prefix="/ai-set", tags=["ai-set"])

# 商品embeddingの行列キャッシュ。毎リクエストで全商品のembedding(JSON)を
# ORMロードすると時間もメモリも破綻する（数千件×数千次元）。正規化済みの
# float32行列としてプロセス内に保持し、TTLの間はDBアクセス無しで使い回す。
_EMB_CACHE: dict = {"ids": None, "matrix": None, "ts": 0.0}
_EMB_CACHE_TTL = 120  # 秒。新規出品はこの猶予後にRAG候補へ反映される。


def _get_embedding_matrix(db: Session):
    """available かつ embedding を持つ商品の (id一覧, 正規化済みfloat32行列) を返す。

    yield_per でストリーミングし、行列へ逐次コピーしてからPythonリストを捨てるため、
    全件のJSONを同時にメモリへ抱えない。結果は TTL の間キャッシュする。
    """
    now = time.time()
    if _EMB_CACHE["matrix"] is not None and (now - _EMB_CACHE["ts"]) < _EMB_CACHE_TTL:
        return _EMB_CACHE["ids"], _EMB_CACHE["matrix"]

    ids: list = []
    vecs: list = []
    q = (
        db.query(Product.id, Product.embedding)
        .filter(
            Product.status == ProductStatus.available,
            Product.hidden_by_penalty == False,  # noqa: E712
            Product.embedding.isnot(None),
        )
        .yield_per(200)
    )
    for pid, emb in q:
        if emb:
            ids.append(pid)
            vecs.append(np.asarray(emb, dtype=np.float32))

    if vecs:
        matrix = np.vstack(vecs)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        matrix = matrix / norms
    else:
        matrix = None

    _EMB_CACHE.update({"ids": ids, "matrix": matrix, "ts": now})
    return ids, matrix

SYSTEM_PROMPT = """あなたはフリマアプリ、EmporioのAIショッピングアシスタントです。
ユーザーの要望に本当に合った商品だけを、アプリ内の実在商品から厳選して提案します。

ルール：
- 必ず提示された【候補商品】リストの中からのみ選ぶ
- ユーザーの要望に関係のない商品は絶対に提案しない（無理に数を揃えない）
- 本当に関係する商品が1つもなければ、正直に「該当する商品が見つかりませんでした」と伝える
- 会話の文脈を踏まえて条件の絞り込みにも対応する

【提案の出し方：複数の「買い方プラン」で提案する】
要望を満たす方法が複数あるときは、最大3つの「プラン」に分けて提案する。各プランは独立した1つの買い方で、
ユーザーはそのうち1つを選んで購入する想定。
- 各プラン内の商品は互いに重複させない（そのプランを丸ごと買っても重複が出ないようにする）。
- プラン同士は内容が重複してもよい（ユーザーはどれか1プランだけを選ぶため）。
- 各プランには短いタイトル（例「不足分だけ揃える」「一気に全部揃える」）と、その買い方を薦める理由を付ける。
- 要望に合うプランが1つしか作れないなら1つでよい（無理に水増ししない）。

【巻もの・シリーズもの／一部を既に所有しているケースのプランの作り方（優先順位）】
1. 最優先プラン：ユーザーがまだ持っていない巻・アイテムだけをピンポイントで補完する（所有分と重複しない）。
   例：「21巻まで持っている」なら 22巻・23巻。候補に個別巻や部分セットがあれば、それらを組み合わせて欠けを過不足なく埋める。
2. 次点プラン：一度にまとめて揃う包括的な選択肢（全巻セットや広い範囲のセット）。
   所有分との重複ができるだけ少ないものを選び、重複が生じる場合は理由文でその旨を明記する。
3. 重複は可能な限り少なくする。不足分を過不足なく満たせる組み合わせがあれば、それを最優先プランにする。

【各プランに owned_overlap フラグを付ける（重要）】
- owned_overlap は「そのプランに、ユーザーが既に持っていると述べた巻・アイテムが含まれるか」を表す真偽値。
  - 既所有分を一切含まない（不足分だけ）プラン → false
  - 既所有分を含む（全巻セット等で持っている巻も再度買うことになる）プラン → true
- ユーザーが所有を明言していない（普通の買い物）場合は、全プラン false でよい。
- これは、不足分だけのプランがある時に重複プランを自動で隠すために使う。正確に付けること。

本文（ユーザーに見える返答）は、どんなプランを用意したかを親しみやすいトーンで150文字程度に要約する。
各プランの個別の理由は本文に書かず、後述のJSONのreasonに書くこと（重複を避ける）。

【出力フォーマット】
返答の最後に、提案を必ず以下のJSON形式で記載してください（このタグはユーザーには表示されません）。プランは最大3つ：
<PLANS>[{"title": "不足分だけ揃える", "reason": "このプランを薦める理由を15〜50字で", "ids": [22, 23], "owned_overlap": false}, {"title": "一気に全部揃える", "reason": "...", "ids": [100], "owned_overlap": true}]</PLANS>
提案できるプランが1つもなければ <PLANS>[]</PLANS> と記載してください。
ids は【候補商品】に実在するIDのみ。reason はそのプランならではの具体的な内容にすること（「おすすめです」のような汎用句は避ける）。
owned_overlap は上記ルールに従い必ず各プランに付けること（不明なら false）。"""

# RAGで候補としてGeminiに渡す件数。シリーズ物（同一作品の多数の巻）でも
# 不足巻が候補から漏れないよう、やや多めに確保する。
TOP_K = 20

# Gemini の思考(thinking)予算。-1=モデルが必要に応じ自動で思考（精度優先）。
# 0=思考オフで高速化できるが、提案精度が落ちたため自動思考に戻している。
AI_SET_THINKING_BUDGET = -1


class Message(BaseModel):
    role: str  # "user" or "model"
    content: str


class AiSetChatRequest(BaseModel):
    messages: list[Message]
    min_budget: Optional[int] = None
    max_budget: Optional[int] = None


class AiSetPlan(BaseModel):
    title: str                       # 買い方の短いタイトル（例「不足分だけ揃える」）
    reason: str = ""                 # そのプランを薦める理由
    products: list[ProductResponse]  # プランに含まれる商品（互いに重複しない）
    total_price: int                 # プランの合計金額
    label: str = ""                  # コードが付ける一言（例「安さ重視ならこちら」）
    recommended: bool = False        # コスパ最良で最上位に出すプラン


class AiSetChatResponse(BaseModel):
    reply: str
    plans: list[AiSetPlan] = []      # 最大3つの「買い方プラン」（おすすめ順）


# 状態（コンディション）を良い順に 0..5 で数値化。不明は中間 3 として扱う。
CONDITION_RANK = {
    "新品・未使用": 0,
    "未使用に近い": 1,
    "目立った傷や汚れなし": 2,
    "やや傷や汚れあり": 3,
    "傷や汚れあり": 4,
    "全体的に状態が悪い": 5,
}


def _avg_condition_rank(plan: "AiSetPlan") -> float:
    """プラン内商品の状態ランク平均（小さいほど状態が良い）。"""
    ranks = [CONDITION_RANK.get(p.condition, 3) for p in plan.products]
    return sum(ranks) / len(ranks) if ranks else 3.0


def annotate_and_sort_plans(plans: list["AiSetPlan"]) -> list["AiSetPlan"]:
    """プランに一言ラベルを付け、コスパ（安さ0.6＋状態0.4）順に並べ替える。

    - 値段と状態を各プラン間で正規化し、総合スコアが最良のものを最上位＝おすすめに。
    - 最安プランには「安さ重視ならこちら」、最も状態が良いプランには「より状態が綺麗」。
    - プランが1つだけのときは並べ替え不要（そのプランをおすすめ扱い）。
    """
    if len(plans) <= 1:
        if plans:
            plans[0].recommended = True
        return plans

    prices = [p.total_price for p in plans]
    conds = [_avg_condition_rank(p) for p in plans]
    pmin, pmax = min(prices), max(prices)
    cmin, cmax = min(conds), max(conds)

    def norm(v: float, lo: float, hi: float) -> float:
        return 0.0 if hi == lo else (v - lo) / (hi - lo)

    # 小さいほど良いスコア（安さ重視のコスパ）
    scores = [
        0.6 * norm(prices[i], pmin, pmax) + 0.4 * norm(conds[i], cmin, cmax)
        for i in range(len(plans))
    ]
    cheapest_i = min(range(len(plans)), key=lambda i: (prices[i], conds[i]))
    best_cond_i = min(range(len(plans)), key=lambda i: (conds[i], prices[i]))

    for i, p in enumerate(plans):
        if i == cheapest_i and i == best_cond_i:
            p.label = "安さも状態も◎"
        elif i == cheapest_i:
            p.label = "安さ重視ならこちら"
        elif i == best_cond_i:
            p.label = "より状態が綺麗"
        else:
            p.label = ""

    order = sorted(range(len(plans)), key=lambda i: (scores[i], prices[i]))
    sorted_plans = [plans[i] for i in order]
    sorted_plans[0].recommended = True
    return sorted_plans


def in_budget(price: int, min_budget: Optional[int], max_budget: Optional[int]) -> bool:
    if min_budget is not None and price < min_budget:
        return False
    if max_budget is not None and price > max_budget:
        return False
    return True


def get_all_available(db: Session, min_budget: Optional[int], max_budget: Optional[int]) -> list:
    """embeddingがない場合のフォールバック：全商品をGeminiに渡す"""
    q = db.query(Product).filter(
        Product.status == ProductStatus.available,
        Product.hidden_by_penalty == False,  # noqa: E712
    )
    if min_budget is not None:
        q = q.filter(Product.price >= min_budget)
    if max_budget is not None:
        q = q.filter(Product.price <= max_budget)
    return q.limit(50).all()


@router.post("/chat", response_model=AiSetChatResponse)
def ai_set_chat(request: AiSetChatRequest, db: Session = Depends(get_db)):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="GEMINI_API_KEY not configured")

    user_message = next((m.content for m in reversed(request.messages) if m.role == "user"), "")
    if not user_message:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No user message found")

    # Step 1: クエリをEmbedding化してRAG検索で候補を絞る
    candidates = []
    query_embedding = get_embedding(user_message)

    if query_embedding:
        ids, matrix = _get_embedding_matrix(db)
        if matrix is not None and len(ids) > 0:
            q = np.asarray(query_embedding, dtype=np.float32)
            qn = np.linalg.norm(q)
            if qn > 0:
                q = q / qn
            # 正規化済み行列との内積＝コサイン類似度を一括計算
            scores = matrix @ q
            # 予算で絞られる分を見込み、TOP_K より多めに上位を取り出す
            k = min(len(ids), TOP_K * 4)
            top_idx = np.argpartition(-scores, k - 1)[:k]
            top_idx = top_idx[np.argsort(-scores[top_idx])]
            top_ids = [ids[i] for i in top_idx]

            # 上位候補だけを実体取得（在庫変化に追従するため status を再確認）
            prod_map = {
                p.id: p
                for p in db.query(Product)
                .filter(
                    Product.id.in_(top_ids),
                    Product.status == ProductStatus.available,
                    Product.hidden_by_penalty == False,  # noqa: E712
                )
                .all()
            }
            for pid in top_ids:
                p = prod_map.get(pid)
                if p and in_budget(p.price, request.min_budget, request.max_budget):
                    candidates.append(p)
                    if len(candidates) >= TOP_K:
                        break

    # Step 2: embeddingがある商品が0件なら全商品を候補として渡す
    if not candidates:
        candidates = get_all_available(db, request.min_budget, request.max_budget)

    # Step 3: Geminiに渡す候補リストを構築
    if candidates:
        product_context = "\n\n【候補商品】\n"
        for p in candidates:
            product_context += f"- ID:{p.id} 「{p.title}」 ¥{p.price:,}"
            if p.category:
                product_context += f" [{p.category}]"
            if p.description:
                product_context += f"\n  説明: {p.description[:80]}"
            product_context += "\n"
    else:
        product_context = "\n\n【候補商品】\n現在出品されている商品がありません。\n"

    if request.min_budget is not None or request.max_budget is not None:
        lo = f"¥{request.min_budget:,}" if request.min_budget is not None else "下限なし"
        hi = f"¥{request.max_budget:,}" if request.max_budget is not None else "上限なし"
        product_context += f"\n【予算】{lo} 〜 {hi}\n"

    # Step 4: Geminiにセット提案を依頼（google-genai SDKで thinking を制御し高速化）
    client = genai_v2.Client(api_key=api_key)
    contents = [
        genai_types.Content(role=m.role, parts=[genai_types.Part(text=m.content)])
        for m in request.messages[:-1]
    ]
    contents.append(
        genai_types.Content(
            role="user", parts=[genai_types.Part(text=user_message + product_context)]
        )
    )
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=contents,
        config=genai_types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            thinking_config=genai_types.ThinkingConfig(thinking_budget=AI_SET_THINKING_BUDGET),
        ),
    )
    raw_text = (response.text or "").strip()

    # Step 5: Geminiが提案した「買い方プラン」を抽出する
    plans_raw = []
    # ids が入れ子配列になるため、外側配列を貪欲マッチで丸ごと取る
    match = re.search(r"<PLANS>\s*(\[.*\])\s*</PLANS>", raw_text, re.DOTALL)
    if match:
        try:
            plans_raw = json.loads(match.group(1))
        except Exception:
            plans_raw = []
    reply = re.sub(r"<PLANS>.*?</PLANS>", "", raw_text, flags=re.DOTALL).strip()

    candidate_map = {p.id: p for p in candidates}
    plans: list[AiSetPlan] = []
    overlaps: list[bool] = []  # 各プランが既所有分と重複するか（plansと同順）
    for item in plans_raw:
        if not isinstance(item, dict):
            continue
        # プラン内の商品＝候補に実在するIDのみ・重複排除・順序維持
        seen: set = set()
        products = []
        for pid in item.get("ids") or []:
            if isinstance(pid, int) and pid in candidate_map and pid not in seen:
                products.append(candidate_map[pid])
                seen.add(pid)
        if not products:
            continue
        title = (item.get("title") or "").strip() or "おすすめセット"
        reason = (item.get("reason") or "").strip()
        plans.append(
            AiSetPlan(
                title=title,
                reason=reason,
                products=products,
                total_price=sum(p.price for p in products),
            )
        )
        overlaps.append(bool(item.get("owned_overlap")))
        if len(plans) >= 3:
            break

    # 既所有分と重複しないプランが1つでもあれば、重複するプランは表示しない
    if any(not o for o in overlaps):
        plans = [p for p, o in zip(plans, overlaps) if not o]

    # 一言ラベル付与＋コスパ順（おすすめを先頭）に並べ替え
    plans = annotate_and_sort_plans(plans)

    return AiSetChatResponse(reply=reply, plans=plans)


@router.post("/embed-all")
def embed_all_products(
    db: Session = Depends(get_db),
    limit: int = 200,
    batch: int = 50,
):
    """embeddingがない既存商品にembeddingを生成する（バッチ処理）。

    Cloud Run のリクエストタイムアウト（既定300秒）で全ロールバックしないよう、
    一度に処理する件数を ``limit`` で絞り、``batch`` 件ごとに commit する。
    NULL の商品だけが対象なので、分割して繰り返し叩けば全件を安全に埋められる。

    - ``limit``: この呼び出しで処理する最大件数（既定200）
    - ``batch``: 何件ごとに commit するか（既定50）

    返り値の ``remaining`` が 0 になるまで繰り返し呼び出すこと。
    """
    products = (
        db.query(Product)
        .filter(Product.embedding.is_(None))
        .limit(limit)
        .all()
    )
    success, failed = 0, 0
    for i, product in enumerate(products):
        text = f"{product.title} {product.category or ''} {product.description or ''}"
        embedding = get_embedding(text)
        if embedding:
            product.embedding = embedding
            success += 1
        else:
            failed += 1
        # batch 件ごとに途中 commit（タイムアウト時も進捗を保全）
        if (i + 1) % max(1, batch) == 0:
            db.commit()
    db.commit()
    remaining = db.query(Product).filter(Product.embedding.is_(None)).count()
    return {
        "processed": len(products),
        "success": success,
        "failed": failed,
        "remaining": remaining,
    }
