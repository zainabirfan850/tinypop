"""
TinyPop - Inventory & Point of Sale app for an accessories shop.
Only uses the Python standard library (tkinter + sqlite3).

Run:  python tinypop_app.py
"""

import csv
import sqlite3
import tkinter as tk
from datetime import datetime
from tkinter import ttk, messagebox, filedialog

DB_FILE = "tinypop.db"
CURRENCY = "Rs"          # change to "$", "£", etc.
LOW_STOCK_LEVEL = 5      # items at or below this are highlighted
CATEGORIES = ["Hair Accessories", "Jewelry", "Phone Accessories",
              "Bags", "Keychains", "Stickers", "Other"]
PINK = "#ff5fa2"


# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------
class Database:
    def __init__(self, path=DB_FILE):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.create_tables()

    def create_tables(self):
        self.conn.executescript("""
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
        self.conn.commit()

    # ---- products
    def products(self, search=""):
        like = f"%{search.strip()}%"
        return self.conn.execute(
            "SELECT * FROM products WHERE name LIKE ? OR category LIKE ? ORDER BY name",
            (like, like)).fetchall()

    def product(self, pid):
        return self.conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()

    def add_product(self, name, category, price, cost, stock):
        self.conn.execute(
            "INSERT INTO products (name, category, price, cost, stock) VALUES (?,?,?,?,?)",
            (name, category, price, cost, stock))
        self.conn.commit()

    def update_product(self, pid, name, category, price, cost, stock):
        self.conn.execute(
            "UPDATE products SET name=?, category=?, price=?, cost=?, stock=? WHERE id=?",
            (name, category, price, cost, stock, pid))
        self.conn.commit()

    def delete_product(self, pid):
        self.conn.execute("DELETE FROM products WHERE id=?", (pid,))
        self.conn.commit()

    # ---- sales
    def record_sale(self, cart, customer=""):
        """cart: {product_id: qty}. Returns (sale_id, lines, total)."""
        lines, total, profit = [], 0.0, 0.0
        for pid, qty in cart.items():
            p = self.product(pid)
            if p is None or p["stock"] < qty:
                raise ValueError(f"Not enough stock for '{p['name'] if p else pid}'.")
            lines.append((p["name"], qty, p["price"]))
            total += p["price"] * qty
            profit += (p["price"] - p["cost"]) * qty

        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO sales (created_at, customer, total, profit) VALUES (?,?,?,?)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), customer, total, profit))
        sale_id = cur.lastrowid
        for (name, qty, price), pid in zip(lines, cart.keys()):
            cur.execute(
                "INSERT INTO sale_items (sale_id, product_name, qty, price) VALUES (?,?,?,?)",
                (sale_id, name, qty, price))
            cur.execute("UPDATE products SET stock = stock - ? WHERE id=?", (qty, pid))
        self.conn.commit()
        return sale_id, lines, total

    def sales(self):
        return self.conn.execute("SELECT * FROM sales ORDER BY id DESC").fetchall()

    def sale_items(self, sale_id):
        return self.conn.execute(
            "SELECT * FROM sale_items WHERE sale_id=?", (sale_id,)).fetchall()

    def summary(self):
        today = datetime.now().strftime("%Y-%m-%d")
        q = self.conn.execute
        today_row = q("SELECT COALESCE(SUM(total),0) t, COALESCE(SUM(profit),0) p, COUNT(*) c "
                      "FROM sales WHERE created_at LIKE ?", (today + "%",)).fetchone()
        all_row = q("SELECT COALESCE(SUM(total),0) t, COALESCE(SUM(profit),0) p FROM sales").fetchone()
        low = q("SELECT COUNT(*) c FROM products WHERE stock <= ?", (LOW_STOCK_LEVEL,)).fetchone()["c"]
        return dict(today_total=today_row["t"], today_profit=today_row["p"],
                    today_orders=today_row["c"], all_total=all_row["t"],
                    all_profit=all_row["p"], low_stock=low)


def money(x):
    return f"{CURRENCY} {x:,.0f}" if float(x).is_integer() else f"{CURRENCY} {x:,.2f}"


# --------------------------------------------------------------------------
# App
# --------------------------------------------------------------------------
class TinyPopApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("TinyPop - Shop Manager")
        self.geometry("1100x680")
        self.minsize(950, 600)
        self.db = Database()
        self.cart = {}                 # product_id -> qty
        self.selected_product = None   # id being edited

        self.style_app()
        self.build_header()

        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.sell_tab = ttk.Frame(self.tabs)
        self.products_tab = ttk.Frame(self.tabs)
        self.history_tab = ttk.Frame(self.tabs)
        self.tabs.add(self.sell_tab, text="  🛍  Sell  ")
        self.tabs.add(self.products_tab, text="  📦  Products  ")
        self.tabs.add(self.history_tab, text="  📈  Sales & Reports  ")

        self.build_sell_tab()
        self.build_products_tab()
        self.build_history_tab()
        self.tabs.bind("<<NotebookTabChanged>>", lambda e: self.refresh_all())
        self.refresh_all()

    # ---------------------------------------------------------------- style
    def style_app(self):
        s = ttk.Style(self)
        try:
            s.theme_use("clam")
        except tk.TclError:
            pass
        s.configure("Treeview", rowheight=26, font=("Segoe UI", 10))
        s.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
        s.configure("Accent.TButton", font=("Segoe UI", 11, "bold"),
                    background=PINK, foreground="white")
        s.map("Accent.TButton", background=[("active", "#e84a8e")])
        s.configure("TNotebook.Tab", padding=(12, 6), font=("Segoe UI", 10, "bold"))

    def build_header(self):
        bar = tk.Frame(self, bg=PINK)
        bar.pack(fill="x")
        tk.Label(bar, text="✨ TinyPop", bg=PINK, fg="white",
                 font=("Segoe UI", 20, "bold")).pack(side="left", padx=15, pady=8)
        tk.Label(bar, text="cute accessories, tiny prices", bg=PINK, fg="white",
                 font=("Segoe UI", 10, "italic")).pack(side="left")
        self.clock = tk.Label(bar, bg=PINK, fg="white", font=("Segoe UI", 10))
        self.clock.pack(side="right", padx=15)
        self.tick()

    def tick(self):
        self.clock.config(text=datetime.now().strftime("%a %d %b %Y  %H:%M"))
        self.after(30000, self.tick)

    # ------------------------------------------------------------ SELL TAB
    def build_sell_tab(self):
        left = ttk.LabelFrame(self.sell_tab, text="Products (double-click to add)")
        left.pack(side="left", fill="both", expand=True, padx=8, pady=8)

        top = ttk.Frame(left)
        top.pack(fill="x", padx=6, pady=6)
        ttk.Label(top, text="Search:").pack(side="left")
        self.sell_search = tk.StringVar()
        self.sell_search.trace_add("write", lambda *a: self.refresh_sell_list())
        ttk.Entry(top, textvariable=self.sell_search).pack(side="left", fill="x", expand=True, padx=6)

        cols = ("name", "category", "price", "stock")
        self.sell_tree = ttk.Treeview(left, columns=cols, show="headings", selectmode="browse")
        for c, w in zip(cols, (220, 130, 80, 60)):
            self.sell_tree.heading(c, text=c.title())
            self.sell_tree.column(c, width=w, anchor="w" if c in ("name", "category") else "e")
        self.sell_tree.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.sell_tree.bind("<Double-1>", lambda e: self.add_to_cart())
        self.sell_tree.tag_configure("low", foreground="#c0392b")
        self.sell_tree.tag_configure("out", foreground="#999999")

        qrow = ttk.Frame(left)
        qrow.pack(fill="x", padx=6, pady=(0, 8))
        ttk.Label(qrow, text="Qty:").pack(side="left")
        self.qty_var = tk.IntVar(value=1)
        ttk.Spinbox(qrow, from_=1, to=999, width=5, textvariable=self.qty_var).pack(side="left", padx=6)
        ttk.Button(qrow, text="Add to cart ➜", command=self.add_to_cart).pack(side="left")

        right = ttk.LabelFrame(self.sell_tab, text="Cart")
        right.pack(side="right", fill="both", padx=8, pady=8)

        ccols = ("name", "qty", "price", "line")
        self.cart_tree = ttk.Treeview(right, columns=ccols, show="headings", height=12)
        for c, w, t in zip(ccols, (170, 40, 70, 80), ("Item", "Qty", "Price", "Total")):
            self.cart_tree.heading(c, text=t)
            self.cart_tree.column(c, width=w, anchor="w" if c == "name" else "e")
        self.cart_tree.pack(fill="both", expand=True, padx=6, pady=6)

        btns = ttk.Frame(right)
        btns.pack(fill="x", padx=6)
        ttk.Button(btns, text="− 1", width=5, command=lambda: self.change_cart(-1)).pack(side="left")
        ttk.Button(btns, text="+ 1", width=5, command=lambda: self.change_cart(1)).pack(side="left", padx=4)
        ttk.Button(btns, text="Remove", command=self.remove_from_cart).pack(side="left")
        ttk.Button(btns, text="Clear", command=self.clear_cart).pack(side="left", padx=4)

        crow = ttk.Frame(right)
        crow.pack(fill="x", padx=6, pady=8)
        ttk.Label(crow, text="Customer (optional):").pack(side="left")
        self.customer_var = tk.StringVar()
        ttk.Entry(crow, textvariable=self.customer_var).pack(side="left", fill="x", expand=True, padx=6)

        self.total_label = tk.Label(right, text="Total: " + money(0),
                                    font=("Segoe UI", 18, "bold"), fg=PINK)
        self.total_label.pack(pady=4)
        ttk.Button(right, text="💖  Checkout", style="Accent.TButton",
                   command=self.checkout).pack(fill="x", padx=6, pady=(0, 10), ipady=6)

    def refresh_sell_list(self):
        self.sell_tree.delete(*self.sell_tree.get_children())
        for p in self.db.products(self.sell_search.get()):
            tag = "out" if p["stock"] <= 0 else ("low" if p["stock"] <= LOW_STOCK_LEVEL else "")
            self.sell_tree.insert("", "end", iid=str(p["id"]),
                                  values=(p["name"], p["category"], money(p["price"]), p["stock"]),
                                  tags=(tag,))

    def add_to_cart(self):
        sel = self.sell_tree.selection()
        if not sel:
            messagebox.showinfo("TinyPop", "Select a product first.")
            return
        try:
            qty = int(self.qty_var.get())
            if qty < 1:
                raise ValueError
        except (ValueError, tk.TclError):
            messagebox.showwarning("TinyPop", "Quantity must be a positive whole number.")
            return
        pid = int(sel[0])
        p = self.db.product(pid)
        new_qty = self.cart.get(pid, 0) + qty
        if new_qty > p["stock"]:
            messagebox.showwarning("Out of stock", f"Only {p['stock']} of '{p['name']}' in stock.")
            return
        self.cart[pid] = new_qty
        self.refresh_cart()

    def selected_cart_id(self):
        sel = self.cart_tree.selection()
        return int(sel[0]) if sel else None

    def change_cart(self, delta):
        pid = self.selected_cart_id()
        if pid is None:
            return
        p = self.db.product(pid)
        new_qty = self.cart[pid] + delta
        if new_qty <= 0:
            del self.cart[pid]
        elif new_qty > p["stock"]:
            messagebox.showwarning("Out of stock", f"Only {p['stock']} in stock.")
            return
        else:
            self.cart[pid] = new_qty
        self.refresh_cart(select=pid if pid in self.cart else None)

    def remove_from_cart(self):
        pid = self.selected_cart_id()
        if pid is not None:
            self.cart.pop(pid, None)
            self.refresh_cart()

    def clear_cart(self):
        self.cart.clear()
        self.refresh_cart()

    def refresh_cart(self, select=None):
        self.cart_tree.delete(*self.cart_tree.get_children())
        total = 0
        for pid, qty in self.cart.items():
            p = self.db.product(pid)
            line = p["price"] * qty
            total += line
            self.cart_tree.insert("", "end", iid=str(pid),
                                  values=(p["name"], qty, money(p["price"]), money(line)))
        if select is not None:
            self.cart_tree.selection_set(str(select))
        self.total_label.config(text="Total: " + money(total))

    def checkout(self):
        if not self.cart:
            messagebox.showinfo("TinyPop", "The cart is empty.")
            return
        try:
            sale_id, lines, total = self.db.record_sale(self.cart, self.customer_var.get().strip())
        except ValueError as e:
            messagebox.showerror("Cannot complete sale", str(e))
            return
        receipt = self.make_receipt(sale_id, lines, total, self.customer_var.get().strip())
        self.cart.clear()
        self.customer_var.set("")
        self.refresh_all()
        self.show_receipt(receipt)

    @staticmethod
    def make_receipt(sale_id, lines, total, customer):
        w = 38
        out = ["TinyPop".center(w), "cute accessories, tiny prices".center(w), "-" * w,
               f"Receipt #{sale_id}",
               datetime.now().strftime("%d %b %Y  %H:%M")]
        if customer:
            out.append(f"Customer: {customer}")
        out.append("-" * w)
        for name, qty, price in lines:
            out.append(name[:w])
            out.append(f"   {qty} x {money(price)}".ljust(w - 14) + money(qty * price).rjust(14))
        out += ["-" * w, "TOTAL".ljust(w - 14) + money(total).rjust(14), "-" * w,
                "Thank you for shopping!".center(w)]
        return "\n".join(out)

    def show_receipt(self, text):
        win = tk.Toplevel(self)
        win.title("Receipt")
        win.geometry("360x460")
        box = tk.Text(win, font=("Courier New", 10), wrap="none")
        box.insert("1.0", text)
        box.config(state="disabled")
        box.pack(fill="both", expand=True, padx=8, pady=8)

        def save():
            path = filedialog.asksaveasfilename(defaultextension=".txt",
                                                filetypes=[("Text file", "*.txt")])
            if path:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
        ttk.Button(win, text="Save receipt", command=save).pack(pady=(0, 8))

    # -------------------------------------------------------- PRODUCTS TAB
    def build_products_tab(self):
        form = ttk.LabelFrame(self.products_tab, text="Product details")
        form.pack(fill="x", padx=8, pady=8)

        self.f_name = tk.StringVar()
        self.f_cat = tk.StringVar(value=CATEGORIES[0])
        self.f_price = tk.StringVar()
        self.f_cost = tk.StringVar()
        self.f_stock = tk.StringVar()

        fields = [("Name", self.f_name, None), ("Category", self.f_cat, CATEGORIES),
                  (f"Price ({CURRENCY})", self.f_price, None),
                  (f"Cost ({CURRENCY})", self.f_cost, None), ("Stock", self.f_stock, None)]
        for i, (label, var, choices) in enumerate(fields):
            ttk.Label(form, text=label).grid(row=0, column=i, sticky="w", padx=6, pady=(6, 0))
            if choices:
                w = ttk.Combobox(form, textvariable=var, values=choices, width=18)
            else:
                w = ttk.Entry(form, textvariable=var, width=22 if label == "Name" else 12)
            w.grid(row=1, column=i, padx=6, pady=(0, 8), sticky="w")

        btns = ttk.Frame(form)
        btns.grid(row=2, column=0, columnspan=5, sticky="w", padx=6, pady=(0, 8))
        ttk.Button(btns, text="➕ Add", command=self.add_product).pack(side="left")
        ttk.Button(btns, text="💾 Update", command=self.update_product).pack(side="left", padx=6)
        ttk.Button(btns, text="🗑 Delete", command=self.delete_product).pack(side="left")
        ttk.Button(btns, text="Clear form", command=self.clear_form).pack(side="left", padx=6)
        ttk.Button(btns, text="⬇ Export CSV", command=self.export_products).pack(side="left", padx=6)

        srow = ttk.Frame(self.products_tab)
        srow.pack(fill="x", padx=8)
        ttk.Label(srow, text="Search:").pack(side="left")
        self.prod_search = tk.StringVar()
        self.prod_search.trace_add("write", lambda *a: self.refresh_products())
        ttk.Entry(srow, textvariable=self.prod_search, width=30).pack(side="left", padx=6)
        ttk.Label(srow, text=f"(red = stock ≤ {LOW_STOCK_LEVEL})", foreground="#c0392b").pack(side="left")

        cols = ("id", "name", "category", "price", "cost", "stock")
        self.prod_tree = ttk.Treeview(self.products_tab, columns=cols, show="headings")
        widths = (40, 260, 150, 90, 90, 70)
        for c, w in zip(cols, widths):
            self.prod_tree.heading(c, text=c.title())
            self.prod_tree.column(c, width=w, anchor="w" if c in ("name", "category") else "e")
        self.prod_tree.pack(fill="both", expand=True, padx=8, pady=8)
        self.prod_tree.tag_configure("low", foreground="#c0392b")
        self.prod_tree.bind("<<TreeviewSelect>>", self.on_product_select)

    def read_form(self):
        name = self.f_name.get().strip()
        if not name:
            raise ValueError("Please enter a product name.")
        try:
            price = float(self.f_price.get())
            cost = float(self.f_cost.get() or 0)
            stock = int(self.f_stock.get() or 0)
        except ValueError:
            raise ValueError("Price and cost must be numbers, and stock a whole number.")
        if price < 0 or cost < 0 or stock < 0:
            raise ValueError("Values cannot be negative.")
        return name, self.f_cat.get().strip() or "Other", price, cost, stock

    def add_product(self):
        try:
            self.db.add_product(*self.read_form())
        except ValueError as e:
            messagebox.showwarning("TinyPop", str(e))
            return
        self.clear_form()
        self.refresh_all()

    def update_product(self):
        if self.selected_product is None:
            messagebox.showinfo("TinyPop", "Select a product from the list to update.")
            return
        try:
            self.db.update_product(self.selected_product, *self.read_form())
        except ValueError as e:
            messagebox.showwarning("TinyPop", str(e))
            return
        self.clear_form()
        self.refresh_all()

    def delete_product(self):
        if self.selected_product is None:
            messagebox.showinfo("TinyPop", "Select a product from the list to delete.")
            return
        if messagebox.askyesno("Delete", "Delete this product? Past sales are kept."):
            self.cart.pop(self.selected_product, None)
            self.db.delete_product(self.selected_product)
            self.clear_form()
            self.refresh_all()

    def clear_form(self):
        self.selected_product = None
        for v in (self.f_name, self.f_price, self.f_cost, self.f_stock):
            v.set("")
        self.f_cat.set(CATEGORIES[0])
        self.prod_tree.selection_remove(self.prod_tree.selection())

    def on_product_select(self, _event):
        sel = self.prod_tree.selection()
        if not sel:
            return
        p = self.db.product(int(sel[0]))
        if p is None:
            return
        self.selected_product = p["id"]
        self.f_name.set(p["name"])
        self.f_cat.set(p["category"])
        self.f_price.set(p["price"])
        self.f_cost.set(p["cost"])
        self.f_stock.set(p["stock"])

    def refresh_products(self):
        self.prod_tree.delete(*self.prod_tree.get_children())
        for p in self.db.products(self.prod_search.get()):
            tag = "low" if p["stock"] <= LOW_STOCK_LEVEL else ""
            self.prod_tree.insert("", "end", iid=str(p["id"]), tags=(tag,),
                                  values=(p["id"], p["name"], p["category"],
                                          money(p["price"]), money(p["cost"]), p["stock"]))

    def export_products(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv",
                                            filetypes=[("CSV file", "*.csv")],
                                            initialfile="tinypop_products.csv")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["id", "name", "category", "price", "cost", "stock"])
            for p in self.db.products():
                w.writerow([p["id"], p["name"], p["category"], p["price"], p["cost"], p["stock"]])
        messagebox.showinfo("TinyPop", "Products exported.")

    # --------------------------------------------------------- HISTORY TAB
    def build_history_tab(self):
        cards = ttk.Frame(self.history_tab)
        cards.pack(fill="x", padx=8, pady=8)
        self.card_vars = {}
        for key, title in (("today_total", "Today's sales"), ("today_orders", "Orders today"),
                           ("today_profit", "Today's profit"), ("all_total", "All-time sales"),
                           ("all_profit", "All-time profit"), ("low_stock", "Low-stock items")):
            f = tk.Frame(cards, bg="#fff0f6", highlightbackground=PINK, highlightthickness=1)
            f.pack(side="left", expand=True, fill="x", padx=4)
            tk.Label(f, text=title, bg="#fff0f6", font=("Segoe UI", 9)).pack(pady=(6, 0))
            var = tk.StringVar(value="-")
            tk.Label(f, textvariable=var, bg="#fff0f6", fg=PINK,
                     font=("Segoe UI", 14, "bold")).pack(pady=(0, 6))
            self.card_vars[key] = var

        paned = ttk.PanedWindow(self.history_tab, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        lf = ttk.LabelFrame(paned, text="Sales")
        cols = ("id", "date", "customer", "total", "profit")
        self.sales_tree = ttk.Treeview(lf, columns=cols, show="headings")
        for c, w in zip(cols, (50, 150, 120, 90, 90)):
            self.sales_tree.heading(c, text=c.title())
            self.sales_tree.column(c, width=w, anchor="w" if c in ("date", "customer") else "e")
        self.sales_tree.pack(fill="both", expand=True, padx=6, pady=6)
        self.sales_tree.bind("<<TreeviewSelect>>", self.on_sale_select)
        paned.add(lf, weight=3)

        rf = ttk.LabelFrame(paned, text="Items in selected sale")
        icols = ("name", "qty", "price")
        self.items_tree = ttk.Treeview(rf, columns=icols, show="headings")
        for c, w in zip(icols, (180, 50, 80)):
            self.items_tree.heading(c, text=c.title())
            self.items_tree.column(c, width=w, anchor="w" if c == "name" else "e")
        self.items_tree.pack(fill="both", expand=True, padx=6, pady=6)
        paned.add(rf, weight=2)

        ttk.Button(self.history_tab, text="⬇ Export sales to CSV",
                   command=self.export_sales).pack(anchor="e", padx=8, pady=(0, 8))

    def refresh_history(self):
        s = self.db.summary()
        self.card_vars["today_total"].set(money(s["today_total"]))
        self.card_vars["today_orders"].set(str(s["today_orders"]))
        self.card_vars["today_profit"].set(money(s["today_profit"]))
        self.card_vars["all_total"].set(money(s["all_total"]))
        self.card_vars["all_profit"].set(money(s["all_profit"]))
        self.card_vars["low_stock"].set(str(s["low_stock"]))

        self.sales_tree.delete(*self.sales_tree.get_children())
        self.items_tree.delete(*self.items_tree.get_children())
        for r in self.db.sales():
            self.sales_tree.insert("", "end", iid=str(r["id"]),
                                   values=(r["id"], r["created_at"], r["customer"] or "-",
                                           money(r["total"]), money(r["profit"])))

    def on_sale_select(self, _event):
        sel = self.sales_tree.selection()
        self.items_tree.delete(*self.items_tree.get_children())
        if sel:
            for it in self.db.sale_items(int(sel[0])):
                self.items_tree.insert("", "end",
                                       values=(it["product_name"], it["qty"], money(it["price"])))

    def export_sales(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv",
                                            filetypes=[("CSV file", "*.csv")],
                                            initialfile="tinypop_sales.csv")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["sale_id", "date", "customer", "item", "qty", "price", "sale_total", "sale_profit"])
            for s in self.db.sales():
                for it in self.db.sale_items(s["id"]):
                    w.writerow([s["id"], s["created_at"], s["customer"], it["product_name"],
                                it["qty"], it["price"], s["total"], s["profit"]])
        messagebox.showinfo("TinyPop", "Sales exported.")

    # ---------------------------------------------------------------- misc
    def refresh_all(self):
        # drop any cart items whose product no longer exists
        for pid in list(self.cart):
            if self.db.product(pid) is None:
                del self.cart[pid]
        self.refresh_sell_list()
        self.refresh_cart()
        self.refresh_products()
        self.refresh_history()


if __name__ == "__main__":
    TinyPopApp().mainloop()
