import os
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import stripe
from pathlib import Path
from dotenv import load_dotenv

# ここを変える
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR / ".env")

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "change-me")

# --- Stripe セットアップ ---
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
if not STRIPE_SECRET_KEY:
    raise RuntimeError("STRIPE_SECRET_KEY が未設定です（.envまたは環境変数で設定）")
stripe.api_key = STRIPE_SECRET_KEY

# 仮の商品データ（あとでDBに差し替え可）
PRODUCTS = [
    {"id": 1, "name": "T-Shirt", "price_cents": 2500, "image_url": "https://via.placeholder.com/300x200?text=T-Shirt", "stripe_price_id": None},
    {"id": 2, "name": "Mug",    "price_cents": 1200, "image_url": "https://via.placeholder.com/300x200?text=Mug",    "stripe_price_id": None},
    {"id": 3, "name": "Cap",    "price_cents": 1800, "image_url": "https://via.placeholder.com/300x200?text=Cap",    "stripe_price_id": None},
]

def get_product(pid: int):
    return next((p for p in PRODUCTS if p["id"] == pid), None)

def cart_dict():
    session.setdefault("cart", {})  # {"1": 2, ...}
    return session["cart"]

def cart_count():
    return sum(int(q) for q in cart_dict().values())

@app.context_processor
def inject_cart_count():
    return {"cart_count": cart_count()}

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/products")
def products():
    return render_template("products.html", products=PRODUCTS)

@app.post("/add-to-cart/<int:pid>")
def add_to_cart(pid):
    qty = int(request.form.get("qty", 1))
    prod = get_product(pid)
    if not prod or qty <= 0:
        flash("商品が見つからないか、数量が不正です。")
        return redirect(url_for("products"))
    c = cart_dict()
    key = str(pid)
    c[key] = int(c.get(key, 0)) + qty
    session.modified = True
    flash(f"{prod['name']} を {qty} 個カートに追加しました。")
    return redirect(url_for("cart_view"))

@app.route("/cart")
def cart_view():
    c = cart_dict()
    ids = [int(k) for k in c.keys()]
    items, total = [], 0
    for pid in ids:
        p = get_product(pid)
        if not p:
            continue
        qty = int(c[str(pid)])
        subtotal = p["price_cents"] * qty
        total += subtotal
        items.append({"product": p, "qty": qty, "subtotal": subtotal})
    return render_template("cart.html", lines=items, total=total)

@app.post("/cart/update/<int:pid>")
def cart_update(pid):
    qty = max(0, int(request.form.get("qty", 1)))
    c = cart_dict()
    key = str(pid)
    if qty == 0:
        c.pop(key, None)
    else:
        c[key] = qty
    session.modified = True
    return redirect(url_for("cart_view"))

@app.post("/cart/clear")
def cart_clear():
    session["cart"] = {}
    session.modified = True
    return redirect(url_for("cart_view"))

# --- ここから Stripe Checkout 本実装 ---

@app.post("/checkout")
def checkout():
    """セッション内カートから Stripe Checkout セッションを作成してリダイレクト。"""
    c = cart_dict()
    if not c:
        flash("カートが空です。")
        return redirect(url_for("cart_view"))

    # line_items を構築
    ids = [int(k) for k in c.keys()]
    products = [get_product(pid) for pid in ids if get_product(pid)]
    line_items = []
    for p in products:
        qty = int(c[str(p["id"])])
        if p.get("stripe_price_id"):
            line_items.append({"price": p["stripe_price_id"], "quantity": qty})
        else:
            # Price を事前作成していない場合は即席の price_data でOK（テスト用）
            line_items.append({
                "price_data": {
                    "currency": "jpy",
                    "product_data": {"name": p["name"]},
                    "unit_amount": p["price_cents"],
                },
                "quantity": qty,
            })

    session_obj = stripe.checkout.Session.create(
        mode="payment",
        line_items=line_items,
        success_url=url_for("success", _external=True) + "?session_id={CHECKOUT_SESSION_ID}",
        cancel_url=url_for("cancel", _external=True),
        # 顧客メールの収集も可能（任意）
        customer_email=None,
        # 決済手段はStripe側で最適化（Apple Pay/Google Pay等も自動）
    )

    # フロントから 303 リダイレクト
    return redirect(session_obj.url, code=303)

@app.get("/success")
def success():
    # （任意）セッションIDから支払い情報を読みたい場合
    session_id = request.args.get("session_id")
    return render_template("success.html", session_id=session_id)

@app.get("/cancel")
def cancel():
    return render_template("cancel.html")

@app.post("/webhook")
def webhook():
    """Stripe Webhook 受信。checkout.session.completed を検証→注文確定処理を行う。"""
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get("Stripe-Signature", "")
    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=STRIPE_WEBHOOK_SECRET,
        )
    except stripe.error.SignatureVerificationError:
        return "invalid signature", 400
    except Exception:
        return "bad request", 400

    # 代表的なイベント: checkout.session.completed
    if event["type"] == "checkout.session.completed":
        session_obj = event["data"]["object"]
        # ここで注文確定処理を行う（DBなら Order を確定、在庫引当、メール送信など）
        # MVP ではログ代わりに print。実運用は永続化/非同期キューへ投げる。
        print("[Order Confirmed]", {
            "session_id": session_obj.get("id"),
            "amount_total": session_obj.get("amount_total"),
            "currency": session_obj.get("currency"),
            "customer_email": session_obj.get("customer_details", {}).get("email"),
            "payment_status": session_obj.get("payment_status"),
        })
        # 注意：セッションのカートはブラウザごとなので、Webhook側では触れない（サーバ側でDBに保存して結びつけるのが正道）

    return jsonify({"status": "ok"})
    
if __name__ == "__main__":
    app.run(debug=True, port=5000, use_reloader=False)