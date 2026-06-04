"""本番にランダムなダミー商品を大量投入するシードスクリプト。

使い方:
    python3 scripts/seed_random_products.py [件数]   # 既定1000件

出品者は SELLER_EMAIL（既存ユーザー）に固定。画像はなし。
タイトル/説明/価格/カテゴリ/状態をランダムに組み合わせて生成する。
"""
import os
import sys
import time
import random
import requests

# 誤爆防止のため既定はローカル。本番投入時のみ環境変数で明示的に上書きする。
#   例: SEED_BASE_URL=https://...run.app SEED_SELLER_EMAIL=foo@example.com python3 scripts/seed_random_products.py
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

# カテゴリごとの (ブランド/修飾語, アイテム名, 価格レンジ, バリエーション)
CATALOG = {
    "服・ファッション": {
        "brands": ["ナイキ", "アディダス", "ユニクロ", "無印良品", "GU", "ザラ", "H&M", "コーチ", "リーバイス", "ノースフェイス", "チャンピオン", "ニューバランス"],
        "items": ["スニーカー", "Tシャツ", "パーカー", "デニムパンツ", "ダウンジャケット", "コート", "ニット", "シャツ", "スカート", "ワンピース", "トートバッグ", "キャップ", "マフラー", "ブーツ"],
        "price": (800, 18000),
        "variants": ["Sサイズ", "Mサイズ", "Lサイズ", "XLサイズ", "ブラック", "ホワイト", "ネイビー", "ベージュ", "27cm", "25cm"],
    },
    "本・漫画": {
        "brands": ["講談社", "集英社", "小学館", "角川", "技術評論社", "オライリー"],
        "items": ["全巻セット", "1〜10巻", "文庫版", "技術書", "参考書", "写真集", "図鑑", "小説", "ビジネス書", "コミック"],
        "price": (400, 12000),
        "variants": ["美品", "初版", "帯付き", "限定版", "新装版", "上下巻"],
    },
    "家電・スマホ": {
        "brands": ["ソニー", "アップル", "アンカー", "ロジクール", "パナソニック", "ダイソン", "シャープ", "東芝", "任天堂"],
        "items": ["イヤホン", "モバイルバッテリー", "ワイヤレスマウス", "キーボード", "スマートウォッチ", "ドライヤー", "電気シェーバー", "タブレット", "スピーカー", "充電器", "Webカメラ"],
        "price": (1200, 45000),
        "variants": ["新型", "第2世代", "ホワイト", "ブラック", "箱付き", "付属品完備"],
    },
    "スポーツ": {
        "brands": ["ミズノ", "アシックス", "ヨネックス", "モンベル", "アディダス", "ナイキ", "コールマン"],
        "items": ["ランニングシューズ", "ヨガマット", "ダンベル", "リュック", "テニスラケット", "野球グローブ", "サッカーボール", "縄跳び", "プロテインシェイカー", "トレーニングウェア"],
        "price": (900, 16000),
        "variants": ["軽量モデル", "26cm", "5kg", "10kg", "30L", "新品同様"],
    },
    "おもちゃ": {
        "brands": ["レゴ", "バンダイ", "タカラトミー", "ポケモン", "任天堂"],
        "items": ["ブロックセット", "プラレール", "カードパック", "フィギュア", "ボードゲーム", "ぬいぐるみ", "パズル", "ラジコン", "ガンプラ", "ミニカー"],
        "price": (500, 9000),
        "variants": ["未開封", "限定版", "全パーツ揃い", "1000ピース", "RGモデル"],
    },
    "家具・インテリア": {
        "brands": ["無印良品", "ニトリ", "IKEA", "不二貿易"],
        "items": ["ローテーブル", "デスクチェア", "本棚", "収納ボックス", "間接照明", "壁掛け時計", "カラーボックス", "ラグマット", "観葉植物", "クッション"],
        "price": (800, 14000),
        "variants": ["北欧風", "オーク材", "3段", "組み立て式", "ホワイト", "ナチュラル"],
    },
    "コスメ・美容": {
        "brands": ["資生堂", "SK-II", "MAC", "ReFa", "サロニア", "無印良品", "キャンメイク"],
        "items": ["化粧水", "美容液", "リップスティック", "ヘアアイロン", "美容ローラー", "日焼け止め", "ファンデーション", "マスカラ", "ヘアブラシ", "フェイスパック"],
        "price": (500, 13000),
        "variants": ["新品", "残量9割", "限定色", "32mm", "大容量", "未開封"],
    },
    "その他": {
        "brands": ["無印良品", "サーモス", "象印", "100均", "ニトリ"],
        "items": ["キッチンタイマー", "タンブラー", "折りたたみ傘", "エコバッグ", "マグカップ", "文房具セット", "アロマディフューザー", "水筒", "弁当箱", "卓上ライト"],
        "price": (300, 5000),
        "variants": ["新品", "真空断熱", "軽量", "大容量", "北欧デザイン", "未使用"],
    },
}

DESC_TEMPLATES = [
    "{item}です。{cond}の状態で、まだまだお使いいただけます。",
    "{brand}の{item}。{variant}。気になる点があればお気軽にご質問ください。",
    "人気の{item}を出品します。{cond}。即購入OKです。",
    "{variant}の{item}。自宅保管していました。よろしくお願いします。",
    "使わなくなったので出品。{brand}製で品質も安心です。",
    "{item}。写真の通り{cond}です。値下げ交渉も歓迎します。",
]


def gen_product(rng: random.Random):
    category = rng.choice(list(CATALOG.keys()))
    c = CATALOG[category]
    brand = rng.choice(c["brands"])
    item = rng.choice(c["items"])
    variant = rng.choice(c["variants"])
    condition = rng.choice(CONDITIONS)
    lo, hi = c["price"]
    price = rng.randint(lo // 100, hi // 100) * 100  # 100円単位
    title = f"{brand} {item} {variant}"
    desc = rng.choice(DESC_TEMPLATES).format(brand=brand, item=item, variant=variant, cond=condition)
    return {
        "title": title,
        "description": desc,
        "price": price,
        "category": category,
        "condition": condition,
        "image_url": "",
    }


def main():
    if not SELLER_EMAIL:
        raise SystemExit("SEED_SELLER_EMAIL を設定してください（既存ユーザーのメール）。")
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
    print(f"投入先: {BASE_URL} / 出品者: {SELLER_EMAIL} / 件数: {count}")
    rng = random.Random(20260603)
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
