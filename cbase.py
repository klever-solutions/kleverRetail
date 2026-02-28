import os
import sqlite3
import json
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

# ============================================================
# FILE PATHS & CLOUD CONFIG
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "openpos.db")
CLOUD_CONFIG_FILE = os.path.join(BASE_DIR, "cloud_config.json")


def load_cloud_config():
    if not os.path.exists(CLOUD_CONFIG_FILE):
        return {
            "cloud_url": "",
            "store_code": "",
            "branch_name": "",
            "sync_mode": "local"  # local / cloud / hybrid
        }
    try:
        with open(CLOUD_CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {
            "cloud_url": "",
            "store_code": "",
            "branch_name": "",
            "sync_mode": "local"
        }


def save_cloud_config(cfg):
    with open(CLOUD_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4)


# ============================================================
# DATABASE
# ============================================================

class Database:
    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH)
        self.cur = self.conn.cursor()
        self._init_schema()

    def _init_schema(self):
        self.cur.execute("""
            CREATE TABLE IF NOT EXISTS staff(
                username TEXT PRIMARY KEY,
                password TEXT,
                role TEXT,
                name TEXT,
                theme TEXT DEFAULT 'light'
            )
        """)
        self.cur.execute("""
            CREATE TABLE IF NOT EXISTS items(
                code TEXT PRIMARY KEY,
                name TEXT,
                price REAL,
                stock INTEGER
            )
        """)
        self.cur.execute("""
            CREATE TABLE IF NOT EXISTS transactions(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                total REAL,
                staff TEXT,
                discount REAL DEFAULT 0
            )
        """)
        self.cur.execute("""
            CREATE TABLE IF NOT EXISTS transaction_items(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER,
                name TEXT,
                price REAL,
                qty INTEGER
            )
        """)

        self.cur.execute("SELECT COUNT(*) FROM staff")
        if self.cur.fetchone()[0] == 0:
            self.cur.execute(
                "INSERT INTO staff VALUES('admin','1234','manager','Admin','light')"
            )
            self.cur.executemany(
                "INSERT INTO items VALUES(?,?,?,?)",
                [
                    ("1001", "Milk", 1.20, 50),
                    ("1002", "Bread", 0.80, 40),
                    ("1003", "Eggs", 2.00, 30),
                ]
            )
        self.conn.commit()

    def get_all_items(self):
        self.cur.execute("SELECT code,name,price,stock FROM items")
        return self.cur.fetchall()

    def add_item(self, code, name, price, stock):
        self.cur.execute("INSERT INTO items VALUES(?,?,?,?)", (code, name, price, stock))
        self.conn.commit()

    def remove_item(self, code):
        self.cur.execute("DELETE FROM items WHERE code=?", (code,))
        self.conn.commit()

    def check_password(self, username, password):
        self.cur.execute(
            "SELECT 1 FROM staff WHERE username=? AND password=?",
            (username, password)
        )
        return self.cur.fetchone() is not None

    def update_password(self, username, new_pw):
        self.cur.execute(
            "UPDATE staff SET password=? WHERE username=?",
            (new_pw, username)
        )
        self.conn.commit()

    def update_theme(self, username, theme):
        self.cur.execute(
            "UPDATE staff SET theme=? WHERE username=?",
            (theme, username)
        )
        self.conn.commit()

    def get_theme(self, username):
        self.cur.execute("SELECT theme FROM staff WHERE username=?", (username,))
        row = self.cur.fetchone()
        return row[0] if row else "light"

    def save_order(self, items, total, staff, discount):
        import datetime
        self.cur.execute(
            "INSERT INTO transactions(timestamp,total,staff,discount) VALUES(?,?,?,?)",
            (datetime.datetime.now().isoformat(), total, staff, discount)
        )
        oid = self.cur.lastrowid
        for it in items:
            self.cur.execute(
                "INSERT INTO transaction_items(order_id,name,price,qty) VALUES(?,?,?,?)",
                (oid, it["name"], it["price"], it["qty"])
            )
        self.conn.commit()
        return oid

    def get_all_orders(self):
        self.cur.execute(
            "SELECT id,timestamp,total,staff,discount FROM transactions ORDER BY id DESC"
        )
        return self.cur.fetchall()

    def get_order_items(self, oid):
        self.cur.execute(
            "SELECT name,price,qty FROM transaction_items WHERE order_id=?",
            (oid,)
        )
        return self.cur.fetchall()

    def search(self, q):
        q = f"%{q}%"
        result = {"items": [], "staff": [], "orders": []}

        self.cur.execute(
            "SELECT code,name,price FROM items WHERE code LIKE ? OR name LIKE ?",
            (q, q)
        )
        result["items"] = self.cur.fetchall()

        self.cur.execute(
            "SELECT username,name,role FROM staff WHERE username LIKE ? OR name LIKE ?",
            (q, q)
        )
        result["staff"] = self.cur.fetchall()

        self.cur.execute(
            "SELECT id,timestamp,total,staff,discount FROM transactions "
            "WHERE staff LIKE ? OR CAST(id AS TEXT) LIKE ?",
            (q, q)
        )
        result["orders"] = self.cur.fetchall()

        return result


# ============================================================
# INVENTORY + TRANSACTION
# ============================================================

class Inventory:
    def __init__(self):
        self.db = Database()

    def get_item(self, code):
        self.db.cur.execute("SELECT name,price FROM items WHERE code=?", (code,))
        row = self.db.cur.fetchone()
        if row:
            return {"name": row[0], "price": row[1]}
        return None


class Transaction:
    def __init__(self):
        self.items = []
        self.total = 0.0
        self.discount = 0.0

    def add_item(self, item):
        for i in self.items:
            if i["name"] == item["name"]:
                i["qty"] += 1
                return self._recalc()
        self.items.append({"name": item["name"], "price": item["price"], "qty": 1})
        self._recalc()

    def take_item(self, name):
        for i in list(self.items):
            if i["name"] == name:
                i["qty"] -= 1
                if i["qty"] <= 0:
                    self.items.remove(i)
                return self._recalc()

    def highlight_up(self, idx):
        if idx <= 0:
            return idx
        self.items[idx - 1], self.items[idx] = self.items[idx], self.items[idx - 1]
        return idx - 1

    def highlight_down(self, idx):
        if idx >= len(self.items) - 1:
            return idx
        self.items[idx + 1], self.items[idx] = self.items[idx], self.items[idx + 1]
        return idx + 1

    def apply_discount(self, amount):
        self.discount = max(0, amount)
        self._recalc()

    def clear(self):
        self.items.clear()
        self.total = 0
        self.discount = 0

    def _recalc(self):
        subtotal = sum(i["price"] * i["qty"] for i in self.items)
        self.total = max(0, subtotal - self.discount)


# ============================================================
# LOGIN WINDOW
# ============================================================

class LoginWindow:
    def __init__(self, root):
        self.root = root
        self.db = Database()

        frame = ttk.Frame(root, padding=30)
        frame.pack(expand=True)

        ttk.Label(frame, text="kleverRetail 1.7.1", font=("Segoe UI", 26, "bold")).pack(pady=10)
        ttk.Label(frame, text="Staff Login", font=("Segoe UI", 18)).pack(pady=10)

        ttk.Label(frame, text="Username").pack(anchor="w")
        self.u = ttk.Entry(frame, font=("Segoe UI", 12))
        self.u.pack(fill="x", pady=5)

        ttk.Label(frame, text="Password").pack(anchor="w")
        self.p = ttk.Entry(frame, show="*", font=("Segoe UI", 12))
        self.p.pack(fill="x", pady=10)

        ttk.Button(frame, text="Login", command=self.login).pack(ipadx=20, ipady=5)

        self.u.focus_set()
        root.bind("<Return>", lambda e: self.login())

    def login(self):
        username = self.u.get().strip()
        password = self.p.get().strip()

        if self.db.check_password(username, password):
            theme = self.db.get_theme(username)
            staff = {
                "username": username,
                "name": username,
                "role": "staff",
                "theme": theme
            }
            for w in self.root.winfo_children():
                w.destroy()
            POSWindow(self.root, staff)
        else:
            messagebox.showerror("Error", "Invalid login")


# ============================================================
# TOPBAR + SIDEBAR
# ============================================================

class TopBar:
    def __init__(self, root, on_search, on_account):
        self.on_search = on_search
        self.on_account = on_account

        frame = ttk.Frame(root, padding=10)
        frame.pack(fill="x")

        ttk.Label(frame, text="kleverRetail 1.7.1", font=("Segoe UI", 18, "bold")).pack(side="left")

        self.search = ttk.Entry(frame, width=40)
        self.search.pack(side="left", padx=20)
        self.search.bind("<Return>", lambda e: self._do_search())

        ttk.Button(frame, text="Account", command=self.on_account).pack(side="right")

    def _do_search(self):
        q = self.search.get().strip()
        if q:
            self.on_search(q)


class SideBar:
    def __init__(self, root, on_nav):
        frame = ttk.Frame(root, padding=10)
        frame.pack(side="left", fill="y")

        for name in ("Checkout", "Items", "Orders", "Account", "Cloud Connect"):
            ttk.Button(frame, text=name, width=20,
                       command=lambda n=name: on_nav(n)).pack(pady=5)


# ============================================================
# CHECKOUT PAGE
# ============================================================

class CheckoutPage:
    def __init__(self, parent, staff, on_lock):
        self.db = Database()
        self.inv = Inventory()
        self.tx = Transaction()
        self.staff = staff
        self.on_lock = on_lock

        frame = ttk.Frame(parent, padding=10)
        frame.pack(fill="both", expand=True)

        top = ttk.Frame(frame)
        top.pack(fill="x")

        ttk.Label(top, text="Checkout", font=("Segoe UI", 18, "bold")).pack(side="left")

        self.entry = ttk.Entry(top, font=("Segoe UI", 14))
        self.entry.pack(side="left", padx=10)
        self.entry.bind("<Return>", lambda e: self.add_item())

        ttk.Button(top, text="Add", command=self.add_item).pack(side="left")

        main = ttk.Frame(frame)
        main.pack(fill="both", expand=True, pady=10)

        self.tree = ttk.Treeview(
            main,
            columns=("name", "price", "qty", "line"),
            show="headings",
            height=15
        )
        for col, text in (
            ("name", "Item"),
            ("price", "Price"),
            ("qty", "Qty"),
            ("line", "Line Total"),
        ):
            self.tree.heading(col, text=text)
            self.tree.column(col, anchor="center", width=150)
        self.tree.pack(side="left", fill="both", expand=True)

        btns = ttk.Frame(main)
        btns.pack(side="right", fill="y", padx=10)

        def b(text, cmd):
            ttk.Button(btns, text=text, command=cmd).pack(fill="x", pady=3, ipady=4)

        b("Highlight Up", self.highlight_up)
        b("Highlight Down", self.highlight_down)
        b("Add 1", self.add_one)
        b("Take 1", self.take_one)
        ttk.Separator(btns).pack(fill="x", pady=5)
        b("Apply Discount", self.apply_discount)
        b("No Sale", self.no_sale)
        ttk.Separator(btns).pack(fill="x", pady=5)
        b("Finish Order", self.finish_order)
        b("Print Receipt", self.print_receipt)
        ttk.Separator(btns).pack(fill="x", pady=5)
        b("Lock Screen", self.lock_screen)

        bottom = ttk.Frame(frame)
        bottom.pack(fill="x")

        self.total_label = ttk.Label(bottom, text="Total: £0.00", font=("Segoe UI", 18, "bold"))
        self.total_label.pack(side="right")

        self.entry.focus_set()

    def refresh(self):
        for r in self.tree.get_children():
            self.tree.delete(r)
        for it in self.tx.items:
            line = it["price"] * it["qty"]
            self.tree.insert("", "end",
                             values=(it["name"], f"£{it['price']:.2f}", it["qty"], f"£{line:.2f}"))
        self.total_label.config(text=f"Total: £{self.tx.total:.2f}")

    def add_item(self):
        code = self.entry.get().strip()
        if not code:
            return
        item = self.inv.get_item(code)
        if not item:
            messagebox.showerror("Error", f"Item {code} not found.")
            return
        self.tx.add_item(item)
        self.entry.delete(0, "end")
        self.refresh()

    def selected_index(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return self.tree.index(sel[0])

    def highlight_up(self):
        idx = self.selected_index()
        if idx is None:
            return
        new = self.tx.highlight_up(idx)
        self.refresh()
        self.tree.selection_set(self.tree.get_children()[new])

    def highlight_down(self):
        idx = self.selected_index()
        if idx is None:
            return
        new = self.tx.highlight_down(idx)
        self.refresh()
        self.tree.selection_set(self.tree.get_children()[new])

    def add_one(self):
        idx = self.selected_index()
        if idx is None:
            return
        it = self.tx.items[idx]
        self.tx.add_item({"name": it["name"], "price": it["price"]})
        self.refresh()

    def take_one(self):
        idx = self.selected_index()
        if idx is None:
            return
        name = self.tx.items[idx]["name"]
        self.tx.take_item(name)
        self.refresh()

    def apply_discount(self):
        amount = simpledialog.askfloat("Discount", "Enter discount (£):")
        if amount is None:
            return
        self.tx.apply_discount(amount)
        self.refresh()

    def no_sale(self):
        if messagebox.askyesno("No Sale", "Clear transaction?"):
            self.tx.clear()
            self.refresh()

    def finish_order(self):
        if not self.tx.items:
            messagebox.showwarning("Empty", "No items.")
            return
        oid = self.db.save_order(self.tx.items, self.tx.total, self.staff["username"], self.tx.discount)
        messagebox.showinfo("Saved", f"Order #{oid} saved.")
        self.tx.clear()
        self.refresh()

    def print_receipt(self):
        messagebox.showinfo("Print", "Receipt printed (simulated).")

    def lock_screen(self):
        if messagebox.askyesno("Lock", "Lock screen?"):
            for w in self.root.winfo_children():
                w.destroy()
            LoginWindow(self.root)


# ============================================================
# ITEMS TAB
# ============================================================

class ItemsTab:
    def __init__(self, parent):
        self.db = Database()

        frame = ttk.Frame(parent, padding=10)
        frame.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(
            frame,
            columns=("code", "name", "price", "stock"),
            show="headings",
            height=15
        )
        for col in ("code", "name", "price", "stock"):
            self.tree.heading(col, text=col.capitalize())
            self.tree.column(col, anchor="center", width=150)
        self.tree.pack(fill="both", expand=True)

        form = ttk.Frame(frame)
        form.pack(pady=10)

        labels = ("Code", "Name", "Price", "Stock")
        self.entries = {}

        for i, label in enumerate(labels):
            ttk.Label(form, text=label).grid(row=0, column=i)
            e = ttk.Entry(form, width=15)
            e.grid(row=1, column=i, padx=5)
            self.entries[label.lower()] = e

        ttk.Button(form, text="Add Item", command=self.add_item).grid(row=1, column=4, padx=10)
        ttk.Button(form, text="Remove Selected", command=self.remove_item).grid(row=1, column=5, padx=10)

        self.refresh()

    def refresh(self):
        for r in self.tree.get_children():
            self.tree.delete(r)
        for it in self.db.get_all_items():
            code, name, price, stock = it
            self.tree.insert("", "end", values=(code, name, f"£{price:.2f}", stock))

    def add_item(self):
        try:
            code = self.entries["code"].get().strip()
            name = self.entries["name"].get().strip()
            price = float(self.entries["price"].get())
            stock = int(self.entries["stock"].get())
            if not code or not name:
                raise ValueError("Code and name required.")
            self.db.add_item(code, name, price, stock)
            self.refresh()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def remove_item(self):
        sel = self.tree.selection()
        if not sel:
            return
        code = self.tree.item(sel[0])["values"][0]
        self.db.remove_item(code)
        self.refresh()


# ============================================================
# ORDERS TAB
# ============================================================

class OrdersTab:
    def __init__(self, parent):
        self.db = Database()

        frame = ttk.Frame(parent, padding=10)
        frame.pack(fill="both", expand=True)

        top = ttk.Frame(frame)
        top.pack(fill="x")

        ttk.Label(top, text="Orders", font=("Segoe UI", 18, "bold")).pack(side="left")
        ttk.Button(top, text="Refresh", command=self.refresh).pack(side="right")

        self.orders_tree = ttk.Treeview(
            frame,
            columns=("id", "timestamp", "total", "staff", "discount"),
            show="headings",
            height=12
        )
        for col, text in (
            ("id", "ID"),
            ("timestamp", "Time"),
            ("total", "Total"),
            ("staff", "Staff"),
            ("discount", "Discount"),
        ):
            self.orders_tree.heading(col, text=text)
            self.orders_tree.column(col, anchor="center", width=120)
        self.orders_tree.pack(fill="both", expand=True, pady=(10, 5))

        self.items_tree = ttk.Treeview(
            frame,
            columns=("name", "price", "qty"),
            show="headings",
            height=8
        )
        for col, text in (
            ("name", "Item"),
            ("price", "Price"),
            ("qty", "Qty"),
        ):
            self.items_tree.heading(col, text=text)
            self.items_tree.column(col, anchor="center", width=150)
        self.items_tree.pack(fill="both", expand=True)

        self.orders_tree.bind("<<TreeviewSelect>>", self.show_items)
        self.refresh()

    def refresh(self):
        for r in self.orders_tree.get_children():
            self.orders_tree.delete(r)
        for oid, ts, total, staff, disc in self.db.get_all_orders():
            self.orders_tree.insert(
                "", "end",
                values=(oid, ts, f"£{total:.2f}", staff, f"£{disc:.2f}")
            )

    def show_items(self, event=None):
        for r in self.items_tree.get_children():
            self.items_tree.delete(r)
        sel = self.orders_tree.selection()
        if not sel:
            return
        oid = self.orders_tree.item(sel[0])["values"][0]
        for name, price, qty in self.db.get_order_items(oid):
            self.items_tree.insert(
                "", "end",
                values=(name, f"£{price:.2f}", qty)
            )


# ============================================================
# ACCOUNT TAB
# ============================================================

class AccountTab:
    def __init__(self, parent, staff, on_theme_change=None):
        self.db = Database()
        self.staff = staff
        self.on_theme_change = on_theme_change

        frame = ttk.Frame(parent, padding=20)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Account", font=("Segoe UI", 20, "bold")).pack(pady=(0, 10))
        ttk.Label(frame, text=f"Name: {staff['name']}").pack(anchor="w")
        ttk.Label(frame, text=f"Username: {staff['username']}").pack(anchor="w")
        ttk.Label(frame, text=f"Role: {staff['role']}").pack(anchor="w")

        ttk.Separator(frame).pack(fill="x", pady=15)

        ttk.Label(frame, text="Change Password", font=("Segoe UI", 14, "bold")).pack(anchor="w")

        pw_frame = ttk.Frame(frame)
        pw_frame.pack(pady=5, fill="x")

        labels = ("Old Password", "New Password", "Confirm New")
        self.pw_entries = []
        for i, label in enumerate(labels):
            ttk.Label(pw_frame, text=label).grid(row=i, column=0, sticky="w", pady=2)
            e = ttk.Entry(pw_frame, show="*")
            e.grid(row=i, column=1, sticky="ew", pady=2, padx=5)
            self.pw_entries.append(e)
        pw_frame.columnconfigure(1, weight=1)

        ttk.Button(frame, text="Update Password", command=self.update_password).pack(pady=10)

        ttk.Separator(frame).pack(fill="x", pady=15)

        ttk.Label(frame, text="Theme", font=("Segoe UI", 14, "bold")).pack(anchor="w")

        self.theme_var = tk.StringVar(value=staff.get("theme", "light"))
        self.theme_combo = ttk.Combobox(
            frame,
            textvariable=self.theme_var,
            values=["light", "dark"],
            state="readonly"
        )
        self.theme_combo.pack(anchor="w", pady=5)
        ttk.Button(frame, text="Save Theme", command=self.save_theme).pack(anchor="w", pady=5)

    def update_password(self):
        old, new, conf = [e.get() for e in self.pw_entries]
        if new != conf:
            messagebox.showerror("Error", "New passwords do not match.")
            return
        if not self.db.check_password(self.staff["username"], old):
            messagebox.showerror("Error", "Old password incorrect.")
            return
        self.db.update_password(self.staff["username"], new)
        messagebox.showinfo("Success", "Password updated.")

    def save_theme(self):
        theme = self.theme_var.get()
        self.db.update_theme(self.staff["username"], theme)
        if self.on_theme_change:
            self.on_theme_change(theme)
        messagebox.showinfo("Success", "Theme saved.")


# ============================================================
# CLOUD CONNECT TAB
# ============================================================

class CloudConnectTab:
    def __init__(self, parent):
        self.cfg = load_cloud_config()

        frame = ttk.Frame(parent, padding=20)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Cloud Connect", font=("Segoe UI", 20, "bold")).pack(pady=(0, 10))

        ttk.Label(frame, text="Cloud API URL").pack(anchor="w")
        self.url_entry = ttk.Entry(frame)
        self.url_entry.insert(0, self.cfg.get("cloud_url", ""))
        self.url_entry.pack(fill="x", pady=5)

        ttk.Label(frame, text="Store Code").pack(anchor="w")
        self.store_entry = ttk.Entry(frame)
        self.store_entry.insert(0, self.cfg.get("store_code", ""))
        self.store_entry.pack(fill="x", pady=5)

        ttk.Label(frame, text="Branch Name").pack(anchor="w")
        self.branch_entry = ttk.Entry(frame)
        self.branch_entry.insert(0, self.cfg.get("branch_name", ""))
        self.branch_entry.pack(fill="x", pady=5)

        ttk.Label(frame, text="Sync Mode").pack(anchor="w")
        self.sync_var = tk.StringVar(value=self.cfg.get("sync_mode", "local"))
        self.sync_combo = ttk.Combobox(
            frame,
            textvariable=self.sync_var,
            values=["local", "cloud", "hybrid"],
            state="readonly"
        )
        self.sync_combo.pack(fill="x", pady=5)

        ttk.Button(frame, text="Save Settings", command=self.save).pack(pady=10)

        info = (
            "local  – use only local SQLite\n"
            "cloud  – prefer cloud API (when implemented)\n"
            "hybrid – local with optional cloud sync"
        )
        ttk.Label(frame, text=info, justify="left").pack(anchor="w", pady=5)

    def save(self):
        cfg = {
            "cloud_url": self.url_entry.get().strip(),
            "store_code": self.store_entry.get().strip(),
            "branch_name": self.branch_entry.get().strip(),
            "sync_mode": self.sync_var.get()
        }
        save_cloud_config(cfg)
        messagebox.showinfo("Saved", "Cloud settings updated.")


# ============================================================
# POS WINDOW
# ============================================================

class POSWindow:
    def __init__(self, root, staff):
        self.root = root
        self.staff = staff
        self.db = Database()

        self.style = ttk.Style()
        self.apply_theme(staff.get("theme", "light"))

        self.topbar = TopBar(root, self.do_search, self.open_account)
        self.sidebar = SideBar(root, self.navigate)

        self.content = ttk.Frame(root)
        self.content.pack(side="right", fill="both", expand=True)

        self.current_page = None
        self.navigate("Checkout")

    def clear_content(self):
        for w in self.content.winfo_children():
            w.destroy()

    def navigate(self, name):
        self.clear_content()
        if name == "Checkout":
            self.current_page = CheckoutPage(self.content, self.staff, self.lock_screen)
        elif name == "Items":
            self.current_page = ItemsTab(self.content)
        elif name == "Orders":
            self.current_page = OrdersTab(self.content)
        elif name == "Account":
            self.current_page = AccountTab(self.content, self.staff, on_theme_change=self.apply_theme)
        elif name == "Cloud Connect":
            self.current_page = CloudConnectTab(self.content)

    def open_account(self):
        self.navigate("Account")

    def lock_screen(self):
        for w in self.root.winfo_children():
            w.destroy()
        LoginWindow(self.root)

    def apply_theme(self, theme_name):
        if theme_name == "dark":
            theme = {
                "root": {"bg": "#202124"},
                "TFrame": {"background": "#202124"},
                "TLabel": {"background": "#202124", "foreground": "#ffffff"},
                "TButton": {"background": "#3c4043", "foreground": "#ffffff"},
                "Treeview": {"background": "#303134", "foreground": "#ffffff", "fieldbackground": "#303134"},
            }
        else:
            theme = {
                "root": {"bg": "#f5f5f5"},
                "TFrame": {"background": "#f5f5f5"},
                "TLabel": {"background": "#f5f5f5", "foreground": "#000000"},
                "TButton": {"background": "#e0e0e0", "foreground": "#000000"},
                "Treeview": {"background": "#ffffff", "foreground": "#000000", "fieldbackground": "#ffffff"},
            }

        self.style.theme_use("clam")
        for widget_class, options in theme.items():
            if widget_class == "root":
                self.root.configure(**options)
            elif widget_class == "Treeview":
                self.style.configure("Treeview", **options)
            else:
                self.style.configure(widget_class, **options)

    def do_search(self, query):
        results = self.db.search(query)
        win = tk.Toplevel(self.root)
        win.title(f"Search: {query}")
        win.geometry("900x550")

        nb = ttk.Notebook(win)
        nb.pack(fill="both", expand=True)

        items_frame = ttk.Frame(nb, padding=10)
        nb.add(items_frame, text="Items")
        items_tree = ttk.Treeview(
            items_frame,
            columns=("code", "name", "price"),
            show="headings"
        )
        for col, text in (("code", "Code"), ("name", "Name"), ("price", "Price")):
            items_tree.heading(col, text=text)
            items_tree.column(col, anchor="center", width=150)
        items_tree.pack(fill="both", expand=True)
        for code, name, price in results["items"]:
            items_tree.insert("", "end", values=(code, name, f"£{price:.2f}"))

        staff_frame = ttk.Frame(nb, padding=10)
        nb.add(staff_frame, text="Staff")
        staff_tree = ttk.Treeview(
            staff_frame,
            columns=("username", "name", "role"),
            show="headings"
        )
        for col, text in (("username", "Username"), ("name", "Name"), ("role", "Role")):
            staff_tree.heading(col, text=text)
            staff_tree.column(col, anchor="center", width=150)
        staff_tree.pack(fill="both", expand=True)
        for username, name, role in results["staff"]:
            staff_tree.insert("", "end", values=(username, name, role))

        orders_frame = ttk.Frame(nb, padding=10)
        nb.add(orders_frame, text="Orders")
        orders_tree = ttk.Treeview(
            orders_frame,
            columns=("id", "timestamp", "total", "staff", "discount"),
            show="headings"
        )
        for col, text in (
            ("id", "ID"),
            ("timestamp", "Time"),
            ("total", "Total"),
            ("staff", "Staff"),
            ("discount", "Discount"),
        ):
            orders_tree.heading(col, text=text)
            orders_tree.column(col, anchor="center", width=140)
        orders_tree.pack(fill="both", expand=True)
        for oid, ts, total, staff, disc in results["orders"]:
            orders_tree.insert(
                "", "end",
                values=(oid, ts, f"£{total:.2f}", staff, f"£{disc:.2f}")
            )


# ============================================================
# MAIN ENTRY
# ============================================================

def main():
    root = tk.Tk()
    root.title("kleverRetail 1.7.1 (cbase)")
    root.geometry("1200x750")
    root.minsize(1000, 650)
    LoginWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
