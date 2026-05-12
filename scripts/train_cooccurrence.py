"""
MerRecデータを使ってカテゴリ共起行列を学習するスクリプト

【やっていること】
1. MerRecから行動データをダウンロード
2. 同じセッション内で一緒に見られたカテゴリのペアを数える（共起）
3. 結果をJSONファイルに保存する

【使い方】
  python scripts/train_cooccurrence.py
"""

import json
import os
from collections import defaultdict
from math import sqrt
from datasets import load_dataset

# ============================================================
# 設定
# ============================================================

# 読み込む行数（多いほど精度UP・時間もかかる）
SAMPLE_SIZE = 1000

# アプリで使うカテゴリ一覧
APP_CATEGORIES = [
    "服・ファッション",
    "本・漫画",
    "家電・スマホ",
    "スポーツ",
    "おもちゃ",
    "家具・インテリア",
    "コスメ・美容",
    "その他",
]

# MerRecの英語カテゴリ → アプリの日本語カテゴリ 対応表
CATEGORY_MAPPING = {
    # 服・ファッション
    "women":       "服・ファッション",
    "men":         "服・ファッション",
    "kids":        "服・ファッション",
    "fashion":     "服・ファッション",
    "clothing":    "服・ファッション",
    "shoes":       "服・ファッション",
    "bags":        "服・ファッション",
    "jewelry":     "服・ファッション",
    "watch":       "服・ファッション",
    # 本・漫画
    "book":        "本・漫画",
    "manga":       "本・漫画",
    "comic":       "本・漫画",
    # 家電・スマホ
    "electron":    "家電・スマホ",
    "computer":    "家電・スマホ",
    "phone":       "家電・スマホ",
    "camera":      "家電・スマホ",
    "gaming":      "家電・スマホ",
    "console":     "家電・スマホ",
    "tablet":      "家電・スマホ",
    # スポーツ
    "sport":       "スポーツ",
    "outdoor":     "スポーツ",
    "fitness":     "スポーツ",
    "golf":        "スポーツ",
    # おもちゃ
    "toy":         "おもちゃ",
    "collectible": "おもちゃ",
    "doll":        "おもちゃ",
    "figure":      "おもちゃ",
    "game":        "おもちゃ",
    # 家具・インテリア
    "home":        "家具・インテリア",
    "furniture":   "家具・インテリア",
    "kitchen":     "家具・インテリア",
    "garden":      "家具・インテリア",
    "decor":       "家具・インテリア",
    # コスメ・美容
    "beauty":      "コスメ・美容",
    "health":      "コスメ・美容",
    "cosmetic":    "コスメ・美容",
    "makeup":      "コスメ・美容",
    "skincare":    "コスメ・美容",
}


# ============================================================
# ステップ1: MerRecのカテゴリ名をアプリのカテゴリに変換
# ============================================================

def map_category(merrec_category: str) -> str:
    """
    MerRecの英語カテゴリ（例: "Women > Tops"）を
    アプリのカテゴリ（例: "服・ファッション"）に変換する。
    どれにも当てはまらない場合は「その他」を返す。
    """
    lower = merrec_category.lower()
    for keyword, app_category in CATEGORY_MAPPING.items():
        if keyword in lower:
            return app_category
    return "その他"


# ============================================================
# ステップ2: MerRecデータを読み込んでカテゴリ共起を集計
# ============================================================

def compute_cooccurrence() -> dict:
    print(f"MerRecからデータを読み込み中... ({SAMPLE_SIZE:,}行)")

    # streaming=True で全データをダウンロードせず少しずつ読む
    ds = load_dataset("mercari-us/merrec", streaming=True, split="train")

    # セッションごとに「どのカテゴリが見られたか」を記録する辞書
    # 例: {"session_abc": {"服・ファッション", "スポーツ"}, ...}
    session_to_categories = defaultdict(set)

    # カテゴリごとの総出現回数
    category_counts = defaultdict(int)

    for i, row in enumerate(ds.take(SAMPLE_SIZE)):
        session_id = str(row["session_id"])
        app_cat    = map_category(str(row["c0_name"]))   # c0_name = 最上位カテゴリ

        session_to_categories[session_id].add(app_cat)
        category_counts[app_cat] += 1

        if (i + 1) % 100_000 == 0:
            print(f"  {i + 1:,} 行処理済み...")

    print(f"\n読み込み完了！")
    print(f"  総セッション数 : {len(session_to_categories):,}")
    print(f"  カテゴリ分布   : {dict(category_counts)}")

    # ----------------------------------------------------------
    # ステップ3: 共起カウント
    # 同じセッション内に「服・ファッション」と「スポーツ」が
    # 一緒に出てきたら、そのペアのカウントを +1 する
    # ----------------------------------------------------------

    cooccurrence = defaultdict(lambda: defaultdict(int))

    for categories in session_to_categories.values():
        cat_list = list(categories)
        for cat_a in cat_list:
            for cat_b in cat_list:
                if cat_a != cat_b:
                    cooccurrence[cat_a][cat_b] += 1

    # ----------------------------------------------------------
    # ステップ4: 類似度スコアに正規化（0〜1の値にする）
    # 式: 共起回数 / sqrt(カテゴリAの出現数 × カテゴリBの出現数)
    # ----------------------------------------------------------

    similarity = {}

    for cat_a in APP_CATEGORIES:
        similarity[cat_a] = {}
        for cat_b in APP_CATEGORIES:
            if cat_a == cat_b:
                similarity[cat_a][cat_b] = 1.0  # 自分自身は類似度1.0
                continue
            co    = cooccurrence[cat_a][cat_b]
            denom = sqrt(category_counts[cat_a] * category_counts[cat_b])
            similarity[cat_a][cat_b] = round(co / denom, 6) if denom > 0 else 0.0

    return similarity


# ============================================================
# 実行
# ============================================================

if __name__ == "__main__":
    # 学習
    similarity = compute_cooccurrence()

    # JSONとして保存
    output_path = os.path.join(os.path.dirname(__file__), "../app/ml/category_similarity.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(similarity, f, ensure_ascii=False, indent=2)

    print(f"\n保存完了: {output_path}")

    # 結果を表示
    print("\n--- 各カテゴリの類似Top3 ---")
    for cat, scores in similarity.items():
        top3 = sorted(
            [(c, s) for c, s in scores.items() if c != cat],
            key=lambda x: x[1],
            reverse=True,
        )[:3]
        print(f"  {cat}: {top3}")
