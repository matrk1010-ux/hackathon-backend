"""
テストデータ投入用の一時的なエンドポイント
使用後は削除すること
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, Product, ProductStatus

router = APIRouter()

DEMO_PRODUCTS = [
    {"title": "ナイキ エアマックス 27cm", "description": "ほぼ未使用。購入後2回着用のみ。箱あり。", "price": 8500, "category": "服・ファッション", "image_url": "https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=400"},
    {"title": "アディダス スタンスミス 26cm", "description": "1年使用。状態良好。汚れなし。", "price": 5000, "category": "服・ファッション", "image_url": "https://images.unsplash.com/photo-1608231387042-66d1773070a5?w=400"},
    {"title": "ユニクロ ダウンジャケット Mサイズ", "description": "2シーズン着用。目立った傷・汚れなし。", "price": 3500, "category": "服・ファッション", "image_url": "https://images.unsplash.com/photo-1548126032-079a0fb0099d?w=400"},
    {"title": "iPhone 14 Pro ケース", "description": "透明タイプ。傷なし美品。1ヶ月使用。", "price": 800, "category": "家電・スマホ", "image_url": "https://images.unsplash.com/photo-1601784551446-20c9e07cdbdb?w=400"},
    {"title": "Anker 65W 充電器", "description": "2ヶ月使用。動作確認済み。付属ケーブルあり。", "price": 2800, "category": "家電・スマホ", "image_url": "https://images.unsplash.com/photo-1609429019995-8c40f49535a5?w=400"},
    {"title": "AirPods Pro 第2世代", "description": "半年使用。ケース付き。バッテリー良好。", "price": 18000, "category": "家電・スマホ", "image_url": "https://images.unsplash.com/photo-1588156979435-379b9d23a305?w=400"},
    {"title": "iPad mini 第6世代 256GB", "description": "1年使用。フィルム・ケース付き。傷なし。", "price": 55000, "category": "家電・スマホ", "image_url": "https://images.unsplash.com/photo-1544244015-0df4b3ffc6b0?w=400"},
    {"title": "ワンピース 全巻セット 1〜105巻", "description": "全巻揃い。状態良好。", "price": 25000, "category": "本・漫画", "image_url": "https://images.unsplash.com/photo-1544947950-fa07a98d237f?w=400"},
    {"title": "鬼滅の刃 全巻セット", "description": "1〜23巻全巻。帯付き美品。", "price": 8000, "category": "本・漫画", "image_url": "https://images.unsplash.com/photo-1612178537253-bccd437b730e?w=400"},
    {"title": "東大英単語 参考書セット", "description": "書き込みなし。ほぼ新品。", "price": 2000, "category": "本・漫画", "image_url": "https://images.unsplash.com/photo-1497633762265-9d179a990aa6?w=400"},
    {"title": "ヨガマット 6mm", "description": "10回程度使用。汚れなし。", "price": 2000, "category": "スポーツ", "image_url": "https://images.unsplash.com/photo-1601925228008-0f3a98a45f87?w=400"},
    {"title": "ダンベルセット 5kg×2", "description": "半年使用。傷少々あり。", "price": 3500, "category": "スポーツ", "image_url": "https://images.unsplash.com/photo-1571019614242-c5c5dee9f50b?w=400"},
    {"title": "IKEA ダイニングテーブル 120cm", "description": "2年使用。小傷あり。引き取り限定（渋谷区）。", "price": 8000, "category": "家具・インテリア", "image_url": "https://images.unsplash.com/photo-1555041469-a586c61ea9bc?w=400"},
    {"title": "ニトリ 収納ラック 5段", "description": "1年使用。組み立て式。状態良好。", "price": 3000, "category": "家具・インテリア", "image_url": "https://images.unsplash.com/photo-1616627547584-bf28cee262db?w=400"},
    {"title": "資生堂 クレ・ド・ポー 美容液", "description": "未開封新品。定価2万円。", "price": 12000, "category": "コスメ・美容", "image_url": "https://images.unsplash.com/photo-1571781926291-c477ebfd024b?w=400"},
    {"title": "SK-II フェイシャルトリートメント", "description": "残量8割。使用期限2025年。", "price": 5000, "category": "コスメ・美容", "image_url": "https://images.unsplash.com/photo-1556228720-195a672e8a03?w=400"},
    {"title": "レゴ テクニック トラック", "description": "箱・説明書あり。完品。一度組み立てのみ。", "price": 6000, "category": "おもちゃ", "image_url": "https://images.unsplash.com/photo-1587654780291-39c9404d746b?w=400"},
    {"title": "ポケモンカード パック未開封10パック", "description": "スカーレット&バイオレット。未開封新品。", "price": 4500, "category": "おもちゃ", "image_url": "https://images.unsplash.com/photo-1613771404784-3a5686aa2be3?w=400"},
    {"title": "Nintendo Switch 本体", "description": "2年使用。Joy-Con・ケース付き。動作確認済み。", "price": 22000, "category": "家電・スマホ", "image_url": "https://images.unsplash.com/photo-1578303512597-81e6cc155b3e?w=400"},
    {"title": "キャンプ用テント 2〜3人用", "description": "3回使用。付属品全あり。", "price": 12000, "category": "スポーツ", "image_url": "https://images.unsplash.com/photo-1504280390367-361c6d9f38f4?w=400"},
]

@router.post("/seed/products", tags=["seed"])
def seed_products(db: Session = Depends(get_db)):
    """テストデータを投入する（使用後は削除すること）"""

    # ダミー出品者を作成（なければ）
    demo_user = db.query(User).filter(User.email == "demo@hackathon.com").first()
    if not demo_user:
        demo_user = User(username="デモ出品者", email="demo@hackathon.com")
        db.add(demo_user)
        db.commit()
        db.refresh(demo_user)

    # 商品を投入
    count = 0
    for p in DEMO_PRODUCTS:
        product = Product(
            title=p["title"],
            description=p["description"],
            price=p["price"],
            category=p["category"],
            image_url=p["image_url"],
            status=ProductStatus.available,
            seller_id=demo_user.id,
        )
        db.add(product)
        count += 1

    db.commit()
    return {"message": f"{count}件の商品を投入しました", "seller_id": demo_user.id}
