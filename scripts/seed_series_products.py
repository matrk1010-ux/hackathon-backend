"""本番にシリーズ断片（連作小説・漫画の一部）の商品を大量投入するシードスクリプト。

使い方:
    python3 scripts/seed_series_products.py [件数]   # 既定1000件

すべて「本・漫画」カテゴリ。単巻 / 部分巻セット / 飛び巻 をランダム生成し、
同一作品の巻が重複・欠落するように散らす（AIセットの欠巻提案が活きるように）。
出品者は SELLER_EMAIL 固定、画像なし。
"""
import os
import sys
import time
import random
import requests

# 誤爆防止のため既定はローカル。本番投入時のみ環境変数で明示的に上書きする。
#   例: SEED_BASE_URL=https://...run.app SEED_SELLER_EMAIL=foo@example.com python3 scripts/seed_series_products.py
BASE_URL = os.getenv("SEED_BASE_URL", "http://localhost:8000")
SELLER_EMAIL = os.getenv("SEED_SELLER_EMAIL", "")

CONDITIONS = [
    "新品・未使用",
    "未使用に近い",
    "目立った傷や汚れなし",
    "やや傷や汚れあり",
    "傷や汚れあり",
    "全体的に状態が悪い",
]

# (作品名, 最大巻数, 1巻あたりの目安価格)
SERIES = [
    # --- 漫画 ---
    ("スラムダンク", 31, 450),
    ("ONE PIECE", 108, 400),
    ("鬼滅の刃", 23, 450),
    ("呪術廻戦", 25, 450),
    ("NARUTO", 72, 400),
    ("BLEACH", 74, 400),
    ("ドラゴンボール", 42, 450),
    ("進撃の巨人", 34, 450),
    ("約束のネバーランド", 20, 450),
    ("東京リベンジャーズ", 31, 450),
    ("ハイキュー!!", 45, 450),
    ("名探偵コナン", 105, 450),
    ("銀魂", 77, 420),
    ("黒子のバスケ", 30, 430),
    ("鋼の錬金術師", 27, 450),
    ("暗殺教室", 21, 450),
    ("七つの大罪", 41, 450),
    ("Dr.STONE", 26, 450),
    ("僕のヒーローアカデミア", 40, 450),
    ("チェンソーマン", 17, 480),
    ("SPY×FAMILY", 13, 500),
    ("北斗の拳", 27, 400),
    ("幽☆遊☆白書", 19, 420),
    ("るろうに剣心", 28, 420),
    ("美少女戦士セーラームーン", 18, 450),
    ("カードキャプターさくら", 12, 480),
    ("フルーツバスケット", 23, 430),
    ("NANA", 21, 450),
    ("のだめカンタービレ", 25, 430),
    ("君に届け", 30, 430),
    ("ちはやふる", 50, 450),
    ("ジョジョの奇妙な冒険", 63, 450),
    ("HUNTER×HUNTER", 37, 450),
    ("青の祓魔師", 30, 450),
    ("金色のガッシュ!!", 33, 420),
    # --- 連作小説・ライトノベル ---
    ("ハリー・ポッター", 7, 900),
    ("銀河英雄伝説", 10, 800),
    ("十二国記", 9, 850),
    ("指輪物語", 9, 950),
    ("ナルニア国物語", 7, 700),
    ("ビブリア古書堂の事件手帖", 10, 700),
    ("薬屋のひとりごと", 15, 700),
    ("ソードアート・オンライン", 27, 650),
    ("転生したらスライムだった件", 22, 680),
    ("Re:ゼロから始める異世界生活", 35, 680),
    ("オーバーロード", 16, 1100),
    ("本好きの下剋上", 33, 750),
    ("この素晴らしい世界に祝福を!", 17, 650),
    ("狼と香辛料", 23, 650),
    ("ダンジョンに出会いを求めるのは間違っているだろうか", 19, 650),
    ("デルトラ・クエスト", 8, 600),
    ("獣の奏者", 11, 750),
    ("守り人シリーズ", 12, 780),
]

DESC_TEMPLATES = [
    "{label}です。{cond}。続きを集めている方や読み返したい方におすすめです。",
    "人気作『{title}』の{label}。{cond}で、まとめてどうぞ。",
    "{title} {label}。自宅で保管していました。{cond}です。",
    "{label}。バラ売り・まとめ売りのご相談OKです。{cond}。",
    "読み終わったので出品します。{title} {label}（{cond}）。",
]


def make_fragment(title, max_vol, rng):
    """単巻 / 範囲セット / 飛び巻 のいずれかの断片を作る。"""
    r = rng.random()
    if max_vol <= 1:
        return "全1巻", 1
    if r < 0.50:
        # 単巻
        v = rng.randint(1, max_vol)
        return f"{v}巻", 1
    elif r < 0.85:
        # 範囲セット
        start = rng.randint(1, max_vol)
        length = rng.randint(2, min(10, max_vol - start + 1)) if max_vol - start + 1 >= 2 else 1
        end = start + length - 1
        if start == end:
            return f"{start}巻", 1
        return f"{start}〜{end}巻", length
    else:
        # 飛び巻（2冊）
        if max_vol >= 2:
            a, b = rng.sample(range(1, max_vol + 1), 2)
            a, b = sorted((a, b))
            return f"{a}巻・{b}巻", 2
        return "1巻", 1


def gen_product(rng):
    title, max_vol, per = rng.choice(SERIES)
    label, vol_count = make_fragment(title, max_vol, rng)
    condition = rng.choice(CONDITIONS)
    # 価格: 1冊あたり目安 × 冊数 に揺らぎを掛けて100円単位
    raw = per * vol_count * rng.uniform(0.7, 1.2)
    price = max(100, int(round(raw / 100)) * 100)
    desc = rng.choice(DESC_TEMPLATES).format(title=title, label=label, cond=condition)
    return {
        "title": f"{title} {label}",
        "description": desc,
        "price": price,
        "category": "本・漫画",
        "condition": condition,
        "image_url": "",
    }


def main():
    if not SELLER_EMAIL:
        raise SystemExit("SEED_SELLER_EMAIL を設定してください（既存ユーザーのメール）。")
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
    print(f"投入先: {BASE_URL} / 出品者: {SELLER_EMAIL} / 件数: {count}")
    rng = random.Random(777)
    success, failed = 0, 0
    for i in range(count):
        payload = gen_product(rng)
        try:
            res = requests.post(
                f"{BASE_URL}/products/",
                json=payload,
                params={"seller_email": SELLER_EMAIL},
                timeout=40,
            )
            if res.status_code in (200, 201):
                success += 1
            else:
                failed += 1
                print(f"[NG {res.status_code}] {payload['title']} -> {res.text[:100]}", flush=True)
        except Exception as e:
            failed += 1
            print(f"[ERR] {payload['title']} -> {e}", flush=True)
        if (i + 1) % 50 == 0:
            print(f"進捗: {i + 1}/{count} (成功 {success} / 失敗 {failed})", flush=True)
        time.sleep(0.05)

    print(f"\n完了: 成功 {success} / 失敗 {failed} / 合計 {count}", flush=True)


if __name__ == "__main__":
    main()
