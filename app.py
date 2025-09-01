from flask import Flask, render_template, request, redirect, url_for, session, flash

app = Flask(__name__)
app.config["SECRET_KEY"] = "change-me"

PRODUCTS = [
    {"id": 1, "name": "T-Shirt", "price_cents": 2500, "image_url": "https://via.placeholder.com/300x200?text=T-Shirt"},
    {"id": 2, "name": "Mug",    "price_cents": 1200, "image_url": "https://via.placeholder.com/300x200?text=Mug"},
    {"id": 3, "name": "Cap",    "price_cents": 1800, "image_url": "https://via.placeholder.com/300x200?text=Cap"},
]

def get_product(pid: int):
    return next((p for p in PRODUCTS if p["id"] == pid), None)

def cart_dict():
    session.setdefault("cart", {})
    return session["cart"]

def cart_count():
    c = cart_dict()
    return sum(int(qty) for qty in c.values())

@app.context_processor
def inject_count():
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
        if not p:  # 商品が消えていた場合はスキップ
            continue
        qty = int(c[str(pid)])
        subtotal = p["price_cents"] * qty
        total += subtotal
        items.append({"product": p, "qty": qty, "subtotal": subtotal})
    return render_template("cart.html", lines=items, total=total)

@app.post("/cart/update/<int:pid>")
def cart_update(pid):
    """数量更新（0 なら削除）。"""
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

@app.post("/checkout")
def checkout():
    """ダミー。実際は Stripe Checkout を作成してリダイレクト。"""
    if not cart_dict():
        flash("カートが空です。")
        return redirect(url_for("cart_view"))
    flash("（ダミー）チェックアウトへ進みます。Stripe連携は後で足す。")
    return redirect(url_for("cart_view"))

if __name__ == "__main__":
    app.run(debug=True, port=5000)