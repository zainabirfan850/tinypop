"""
TinyPop - Inventory & Point of Sale (Streamlit version)

Run locally:   streamlit run streamlit_app.py
Deploy:        push to GitHub, then create the app on share.streamlit.io
"""

import hmac
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

# ----------------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------------
DB_FILE = "tinypop.db"
CURRENCY = "Rs"            # change to "$", "£", etc.
LOW_STOCK_LEVEL = 5        # items at or below this count as "low stock"
TIMEZONE = "Asia/Karachi"  # the server runs in UTC, so we set the shop's time zone
CATEGORIES = ["Hair Accessories", "Jewelry", "Phone Accessories",
              "Bags", "Keychains", "Stickers", "Other"]

SAMPLE_PRODUCTS = [
    ("Pearl Hair Clip", "Hair Accessories", 350, 150, 25),
    ("Scrunchie Set (3 pcs)", "Hair Accessories", 450, 200, 18),
    ("Butterfly Necklace", "Jewelry", 800, 350, 12),
    ("Mini Hoop Earrings", "Jewelry", 600, 250, 20),
    ("Cute Phone Charm", "Phone Accessories", 300, 100, 30),
    ("Mini Tote Bag", "Bags", 1200, 600, 8),
    ("Bear Keychain", "Keychains", 250, 90, 40),
    ("Sticker Pack", "Stickers", 150, 40, 60),
]

st.set_page_config(page_title="TinyPop", page_icon="✨", layout="wide")


# ----------------------------------------------------------------------------
# Database helpers
# ----------------------------------------------------------------------------
def now():
    return datetime.now(ZoneInfo(TIMEZONE))


def conn():
    c = sqlite3.connect(DB_FILE)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    return c


def init_db():
    c = conn()
    try:
        with c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    category TEXT,
                    price REAL NOT NULL,
                    cost REAL NOT NULL DEFAULT 0,
                    stock INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS sales (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    customer TEXT,
                    total REAL NOT NULL,
                    profit REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sale_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sale_id INTEGER NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
                    product_name TEXT NOT NULL,
                    qty INTEGER NOT NULL,
                    price REAL NOT NULL
                );
            """)
    finally:
        c.close()


def query(sql, params=()):
    c = conn()
    try:
        return [dict(r) for r in c.execute(sql, params).fetchall()]
    finally:
        c.close()


def query_df(sql, params=()):
    c = conn()
    try:
        return pd.read_sql_query(sql, c, params=params)
    finally:
        c.close()


def execute(sql, params=()):
    c = conn()
    try:
        with c:
            c.execute(sql, params)
    finally:
        c.close()


def get_product(pid):
    rows = query("SELECT * FROM products WHERE id=?", (pid,))
    return rows[0] if rows else None


def money(x):
    x = float(x)
    return f"{CURRENCY} {x:,.0f}" if x.is_integer() else f"{CURRENCY} {x:,.2f}"


def flash(msg):
    st.session_state["flash"] = msg


# ----------------------------------------------------------------------------
# Sales logic
# ----------------------------------------------------------------------------
def make_receipt(sale_id, when, lines, total, customer):
    w = 38
    out = ["TinyPop".center(w), "cute accessories, tiny prices".center(w), "-" * w,
           f"Receipt #{sale_id}", when]
    if customer:
        out.append(f"Customer: {customer}")
    out.append("-" * w)
    for name, qty, price in lines:
        out.append(name[:w])
        out.append(f"   {qty} x {money(price)}".ljust(w - 14) + money(qty * price).rjust(14))
    out += ["-" * w, "TOTAL".ljust(w - 14) + money(total).rjust(14), "-" * w,
            "Thank you for shopping!".center(w)]
    return "\n".join(out)


def record_sale(cart, customer=""):
    """Saves the sale, reduces stock, returns receipt text. Raises ValueError if stock is short."""
    stamp = now()
    c = conn()
    try:
        with c:  # one transaction: any error rolls everything back
            lines, total, profit = [], 0.0, 0.0
            for pid, qty in cart.items():
                p = c.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
                if p is None:
                    raise ValueError("A product in the cart no longer exists.")
                if p["stock"] < qty:
                    raise ValueError(f"Not enough stock for '{p['name']}' (only {p['stock']} left).")
                lines.append((pid, p["name"], qty, p["price"]))
                total += p["price"] * qty
                profit += (p["price"] - p["cost"]) * qty

            cur = c.execute(
                "INSERT INTO sales (created_at, customer, total, profit) VALUES (?,?,?,?)",
                (stamp.strftime("%Y-%m-%d %H:%M:%S"), customer, total, profit))
            sale_id = cur.lastrowid
            for pid, name, qty, price in lines:
                c.execute("INSERT INTO sale_items (sale_id, product_name, qty, price) VALUES (?,?,?,?)",
                          (sale_id, name, qty, price))
                c.execute("UPDATE products SET stock = stock - ? WHERE id=?", (qty, pid))
    finally:
        c.close()
    return make_receipt(sale_id, stamp.strftime("%d %b %Y  %H:%M"),
                        [(n, q, p) for _, n, q, p in lines], total, customer)


def do_checkout():
    """Button callback (runs before the page redraws, so it can reset widgets)."""
    try:
        receipt = record_sale(st.session_state.cart,
                              st.session_state.get("customer", "").strip())
    except ValueError as e:
        st.session_state["checkout_error"] = str(e)
        return
    st.session_state.cart = {}
    st.session_state["customer"] = ""
    st.session_state["last_receipt"] = receipt


# ----------------------------------------------------------------------------
# Optional password gate (add  app_password = "..."  in Streamlit secrets)
# ----------------------------------------------------------------------------
def get_password():
    try:
        return str(st.secrets["app_password"])
    except Exception:
        return None


def check_password():
    expected = get_password()
    if expected is None:
        return True  # no password configured
    if st.session_state.get("authed"):
        return True
    st.title("✨ TinyPop")
    entered = st.text_input("Password", type="password")
    if st.button("Log in", type="primary"):
        if hmac.compare_digest(str(entered), expected):
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("Wrong password.")
    return False


# ----------------------------------------------------------------------------
# Pages
# ----------------------------------------------------------------------------
def page_sell():
    left, right = st.columns([3, 2], gap="large")
    cart = st.session_state.cart

    with left:
        st.subheader("🛍 Products")
        search = st.text_input("Search", placeholder="Search by name or category", key="sell_search")
        like = f"%{search.strip()}%"
        prods = query("SELECT * FROM products WHERE (name LIKE ? OR category LIKE ?) "
                      "AND stock > 0 ORDER BY name", (like, like))
        if not prods:
            st.info("No products in stock match. Add products on the **Products** page.")
        else:
            labels = {p["id"]: f"{p['name']} — {money(p['price'])} ({p['stock']} left)" for p in prods}
            c1, c2, c3 = st.columns([4, 1, 1])
            pid = c1.selectbox("Product", list(labels), format_func=labels.get)
            qty = c2.number_input("Qty", min_value=1, max_value=999, value=1, step=1)
            c3.write("")
            c3.write("")
            if c3.button("Add ➜", type="primary"):
                p = get_product(pid)
                new_qty = cart.get(pid, 0) + int(qty)
                if new_qty > p["stock"]:
                    st.warning(f"Only {p['stock']} of '{p['name']}' in stock.")
                else:
                    cart[pid] = new_qty
                    st.rerun()

            df = pd.DataFrame(prods)[["name", "category", "price", "stock"]]
            df.columns = ["Name", "Category", "Price", "Stock"]
            st.dataframe(df, hide_index=True)

    with right:
        st.subheader("🛒 Cart")

        if "last_receipt" in st.session_state:
            st.success("Sale completed! 💖")
            st.code(st.session_state["last_receipt"], language=None)
            d1, d2 = st.columns(2)
            d1.download_button("Download receipt", st.session_state["last_receipt"],
                               file_name="receipt.txt")
            if d2.button("New sale"):
                del st.session_state["last_receipt"]
                st.rerun()
            st.divider()

        if "checkout_error" in st.session_state:
            st.error(st.session_state.pop("checkout_error"))

        total = 0.0
        if not cart:
            st.caption("The cart is empty.")
        for pid, qty in list(cart.items()):
            p = get_product(pid)
            if p is None:
                del cart[pid]
                continue
            line = p["price"] * qty
            total += line
            c1, c2, c3, c4 = st.columns([5, 1, 1, 1])
            c1.markdown(f"**{p['name']}**  \n{qty} × {money(p['price'])} = {money(line)}")
            if c2.button("➖", key=f"dec_{pid}"):
                if qty <= 1:
                    del cart[pid]
                else:
                    cart[pid] = qty - 1
                st.rerun()
            if c3.button("➕", key=f"inc_{pid}"):
                if qty + 1 > p["stock"]:
                    st.warning(f"Only {p['stock']} in stock.")
                else:
                    cart[pid] = qty + 1
                    st.rerun()
            if c4.button("🗑", key=f"rm_{pid}"):
                del cart[pid]
                st.rerun()

        st.markdown(f"### Total: {money(total)}")
        st.text_input("Customer (optional)", key="customer")
        st.button("💖 Checkout", type="primary", disabled=not cart, on_click=do_checkout)


def page_products():
    st.subheader("📦 Products")
    tab_all, tab_add, tab_edit = st.tabs(["All products", "Add new", "Edit / delete"])

    with tab_all:
        search = st.text_input("Search", placeholder="Search by name or category", key="prod_search")
        like = f"%{search.strip()}%"
        df = query_df("SELECT id, name, category, price, cost, stock FROM products "
                      "WHERE name LIKE ? OR category LIKE ? ORDER BY name", (like, like))
        if df.empty and not search.strip():
            st.info("No products yet. Add your first one, or load a few examples to try the app.")
            if st.button("Load sample products"):
                c = conn()
                try:
                    with c:
                        c.executemany("INSERT INTO products (name, category, price, cost, stock) "
                                      "VALUES (?,?,?,?,?)", SAMPLE_PRODUCTS)
                finally:
                    c.close()
                flash("Sample products added.")
                st.rerun()
        else:
            df["status"] = df["stock"].apply(
                lambda s: "❌ Out" if s <= 0 else ("⚠️ Low" if s <= LOW_STOCK_LEVEL else "OK"))
            df.columns = ["ID", "Name", "Category", "Price", "Cost", "Stock", "Status"]
            st.dataframe(df, hide_index=True)
            st.download_button("⬇ Export products (CSV)", df.to_csv(index=False),
                               file_name="tinypop_products.csv", mime="text/csv")

    with tab_add:
        with st.form("add_form", clear_on_submit=True):
            name = st.text_input("Name")
            category = st.selectbox("Category", CATEGORIES)
            c1, c2, c3 = st.columns(3)
            price = c1.number_input(f"Selling price ({CURRENCY})", min_value=0.0, step=1.0)
            cost = c2.number_input(f"Cost price ({CURRENCY})", min_value=0.0, step=1.0)
            stock = c3.number_input("Stock", min_value=0, step=1)
            if st.form_submit_button("➕ Add product", type="primary"):
                if not name.strip():
                    st.warning("Please enter a product name.")
                else:
                    execute("INSERT INTO products (name, category, price, cost, stock) VALUES (?,?,?,?,?)",
                            (name.strip(), category, price, cost, int(stock)))
                    st.success(f"Added '{name.strip()}'.")

    with tab_edit:
        rows = query("SELECT id, name FROM products ORDER BY name")
        if not rows:
            st.info("Nothing to edit yet.")
            return
        names = {r["id"]: r["name"] for r in rows}
        pid = st.selectbox("Choose a product", list(names), format_func=names.get)
        p = get_product(pid)
        current_cat = p["category"] or "Other"
        cats = CATEGORIES + ([current_cat] if current_cat not in CATEGORIES else [])

        with st.form(f"edit_form_{pid}"):
            name = st.text_input("Name", value=p["name"])
            category = st.selectbox("Category", cats, index=cats.index(current_cat))
            c1, c2, c3 = st.columns(3)
            price = c1.number_input(f"Selling price ({CURRENCY})", min_value=0.0,
                                    value=float(p["price"]), step=1.0)
            cost = c2.number_input(f"Cost price ({CURRENCY})", min_value=0.0,
                                   value=float(p["cost"]), step=1.0)
            stock = c3.number_input("Stock", min_value=0, value=int(p["stock"]), step=1)
            if st.form_submit_button("💾 Save changes", type="primary"):
                if not name.strip():
                    st.warning("Name cannot be empty.")
                else:
                    execute("UPDATE products SET name=?, category=?, price=?, cost=?, stock=? WHERE id=?",
                            (name.strip(), category, price, cost, int(stock), pid))
                    flash(f"Saved '{name.strip()}'.")
                    st.rerun()

        st.divider()
        confirm = st.checkbox("I want to delete this product (past sales are kept)",
                              key=f"confirm_del_{pid}")
        if st.button("🗑 Delete product", disabled=not confirm, key=f"del_{pid}"):
            execute("DELETE FROM products WHERE id=?", (pid,))
            st.session_state.cart.pop(pid, None)
            flash("Product deleted.")
            st.rerun()


def page_reports():
    st.subheader("📈 Sales & Reports")
    today = now().strftime("%Y-%m-%d")

    t = query("SELECT COALESCE(SUM(total),0) t, COALESCE(SUM(profit),0) p, COUNT(*) c "
              "FROM sales WHERE created_at LIKE ?", (today + "%",))[0]
    a = query("SELECT COALESCE(SUM(total),0) t, COALESCE(SUM(profit),0) p, COUNT(*) c FROM sales")[0]
    low = query("SELECT COUNT(*) c FROM products WHERE stock <= ?", (LOW_STOCK_LEVEL,))[0]["c"]

    m1, m2, m3 = st.columns(3)
    m1.metric("Today's sales", money(t["t"]))
    m2.metric("Orders today", t["c"])
    m3.metric("Today's profit", money(t["p"]))
    m4, m5, m6 = st.columns(3)
    m4.metric("All-time sales", money(a["t"]))
    m5.metric("All-time profit", money(a["p"]))
    m6.metric("Low-stock items", low)

    st.divider()
    left, right = st.columns(2, gap="large")

    with left:
        st.markdown("**Daily sales (last 30 days)**")
        daily = query_df("SELECT substr(created_at,1,10) AS day, SUM(total) AS sales "
                         "FROM sales GROUP BY day ORDER BY day DESC LIMIT 30")
        if daily.empty:
            st.caption("No sales yet.")
        else:
            st.bar_chart(daily.sort_values("day").set_index("day")["sales"])

    with right:
        st.markdown("**Top sellers**")
        top = query_df("SELECT product_name AS Product, SUM(qty) AS Sold, "
                       "SUM(qty*price) AS Revenue FROM sale_items "
                       "GROUP BY product_name ORDER BY Sold DESC LIMIT 10")
        if top.empty:
            st.caption("No sales yet.")
        else:
            st.dataframe(top, hide_index=True)

    lowdf = query_df("SELECT name AS Name, category AS Category, stock AS Stock FROM products "
                     "WHERE stock <= ? ORDER BY stock", (LOW_STOCK_LEVEL,))
    if not lowdf.empty:
        st.markdown(f"**⚠️ Low stock (≤ {LOW_STOCK_LEVEL})**")
        st.dataframe(lowdf, hide_index=True)

    st.divider()
    st.markdown("**Sales history**")
    sales = query_df("SELECT id AS ID, created_at AS Date, customer AS Customer, "
                     "total AS Total, profit AS Profit FROM sales ORDER BY id DESC")
    if sales.empty:
        st.caption("No sales recorded yet.")
        return
    st.dataframe(sales, hide_index=True)

    labels = {int(r.ID): f"#{r.ID} — {r.Date} — {money(r.Total)}" for r in sales.itertuples()}
    sid = st.selectbox("View items in a sale", list(labels), format_func=labels.get)
    items = query_df("SELECT product_name AS Item, qty AS Qty, price AS Price "
                     "FROM sale_items WHERE sale_id=?", (sid,))
    st.dataframe(items, hide_index=True)

    export = query_df("SELECT s.id AS sale_id, s.created_at AS date, s.customer, i.product_name AS item, "
                      "i.qty, i.price, s.total AS sale_total, s.profit AS sale_profit "
                      "FROM sales s JOIN sale_items i ON i.sale_id = s.id ORDER BY s.id DESC")
    st.download_button("⬇ Export all sales (CSV)", export.to_csv(index=False),
                       file_name="tinypop_sales.csv", mime="text/csv")


def page_backup():
    st.subheader("💾 Backup & Restore")
    st.warning(
        "On Streamlit Community Cloud, files are **not permanent**: the database is reset whenever "
        "the app restarts, redeploys, or wakes up after sleeping. Download a backup regularly "
        "(and after busy days) and restore it here when needed."
    )

    if os.path.exists(DB_FILE):
        with open(DB_FILE, "rb") as f:
            data = f.read()
        st.download_button("⬇ Download full backup (.db)", data,
                           file_name=f"tinypop_backup_{now().strftime('%Y-%m-%d')}.db",
                           mime="application/octet-stream", type="primary")

    st.divider()
    st.markdown("**Restore from a backup**")
    up = st.file_uploader("Upload a TinyPop backup (.db)", type=["db", "sqlite", "sqlite3"])
    if up is not None:
        st.caption("Restoring replaces all current products and sales.")
        if st.button("Restore this backup"):
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
            tmp.write(up.getvalue())
            tmp.close()
            try:
                t = sqlite3.connect(tmp.name)
                tables = {r[0] for r in t.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                t.close()
                if not {"products", "sales", "sale_items"} <= tables:
                    raise ValueError("This doesn't look like a TinyPop backup.")
                shutil.copyfile(tmp.name, DB_FILE)
                st.session_state.cart = {}
                flash("Backup restored.")
                st.rerun()
            except Exception as e:
                st.error(f"Could not restore: {e}")
            finally:
                os.remove(tmp.name)


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
if not check_password():
    st.stop()

init_db()
if "cart" not in st.session_state:
    st.session_state.cart = {}

st.title("✨ TinyPop")
st.caption("cute accessories, tiny prices")

with st.sidebar:
    page = st.radio("Menu", ["🛍 Sell", "📦 Products", "📈 Sales & Reports", "💾 Backup"])
    low_count = query("SELECT COUNT(*) c FROM products WHERE stock <= ?", (LOW_STOCK_LEVEL,))[0]["c"]
    if low_count:
        st.warning(f"⚠️ {low_count} item(s) low on stock")
    st.caption(now().strftime("%a %d %b %Y, %H:%M"))
    if get_password() is not None and st.button("Log out"):
        st.session_state["authed"] = False
        st.rerun()

if "flash" in st.session_state:
    st.success(st.session_state.pop("flash"))

if page.endswith("Sell"):
    page_sell()
elif page.endswith("Products"):
    page_products()
elif page.endswith("Reports"):
    page_reports()
else:
    page_backup()
