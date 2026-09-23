import streamlit as st
import pandas as pd
from datetime import datetime
from fpdf import FPDF
import urllib.parse
import json
import sqlite3
import re
import difflib
import google.generativeai as genai
from PIL import Image
from supabase import create_client, Client

# ==========================================
# PAGE CONFIG & STYLING (ORANGE THEME)
# ==========================================
st.set_page_config(
    page_title="SGB / LCB Pharma Wholesale ERP",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    
""", unsafe_allow_html=True)

# ==========================================
# HYBRID DATABASE SETUP (SUPABASE + LOCAL SQLITE)
# ==========================================
DB_FILE = "pharma_erp.db"

def init_local_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS sales 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, invoice TEXT, party TEXT, product TEXT, pack TEXT, qty REAL, free_qty TEXT, mrp REAL, disc_pct REAL, disc_rs REAL, rate REAL, gst REAL, amount REAL, created_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS purchase 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, invoice TEXT, party TEXT, product TEXT, pack TEXT, qty REAL, free_qty TEXT, mrp REAL, disc_pct REAL, disc_rs REAL, rate REAL, gst REAL, amount REAL, created_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (username TEXT PRIMARY KEY, password TEXT, name TEXT, role TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS master_products 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, product_name TEXT UNIQUE, pack TEXT, mrp REAL, rate REAL, tax REAL)''')
    
    for tbl in ["sales", "purchase"]:
        for col, dtype in [("pack", "TEXT"), ("free_qty", "TEXT"), ("disc_pct", "REAL"), ("disc_rs", "REAL")]:
            try: c.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {dtype}")
            except Exception: pass
            
    for col, dtype in [("pack", "TEXT"), ("mrp", "REAL"), ("rate", "REAL"), ("tax", "REAL")]:
        try: c.execute(f"ALTER TABLE master_products ADD COLUMN {col} {dtype}")
        except Exception: pass
    
    c.execute("INSERT OR IGNORE INTO users VALUES ('manager', 'admin123', 'Manager', 'Manager')")
    c.execute("INSERT OR IGNORE INTO users VALUES ('satya', 'satya123', 'Satya Sahu', 'Sales Executive')")
    
    defaults = [
        ("ATPLEX Syrup", "200ml", 145.0, 75.0, 12.0),
        ("Duty Beauty MINUS 16 Cream", "50gm", 450.0, 220.0, 18.0),
        ("Duty Beauty Glutathione Soap", "75gm", 195.0, 95.0, 18.0),
        ("Duty Beauty Facewash", "100ml", 220.0, 110.0, 18.0),
        ("Kabja Band", "100gm", 120.0, 60.0, 12.0),
        ("Cartibot", "1x10", 350.0, 180.0, 12.0),
        ("Virload", "1x10", 280.0, 140.0, 12.0),
        ("Womensa Syrup", "200ml", 160.0, 80.0, 12.0),
        ("Panchaliv Syrup", "200ml", 135.0, 68.0, 12.0),
        ("Alobyd-P", "1x10", 95.0, 45.0, 12.0)
    ]
    for p in defaults:
        try: c.execute("INSERT OR IGNORE INTO master_products (product_name, pack, mrp, rate, tax) VALUES (?, ?, ?, ?, ?)", p)
        except Exception: pass
        
    conn.commit()
    conn.close()

init_local_db()

@st.cache_resource
def get_supabase_client():
    if "SUPABASE_URL" in st.secrets and "SUPABASE_KEY" in st.secrets:
        try:
            url = st.secrets["SUPABASE_URL"]
            key = st.secrets["SUPABASE_KEY"]
            if "supabase.co" in url:
                return create_client(url, key)
        except Exception: return None
    return None

supabase = get_supabase_client()

def load_master_products():
    if supabase:
        try:
            res = supabase.table("master_products").select("*").execute()
            if res.data: return pd.DataFrame(res.data)
        except Exception: pass
            
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM master_products ORDER BY product_name ASC", conn)
    conn.close()
    return df

def add_master_product(product_name, pack, mrp, rate, tax):
    p_clean = product_name.strip()
    if not p_clean: return
    if supabase:
        try: supabase.table("master_products").insert({"product_name": p_clean, "pack": pack, "mrp": mrp, "rate": rate, "tax": tax}).execute()
        except Exception: pass
            
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO master_products (product_name, pack, mrp, rate, tax) VALUES (?, ?, ?, ?, ?)", (p_clean, pack, mrp, rate, tax))
    conn.commit()
    conn.close()

def delete_master_product(product_name):
    if supabase:
        try: supabase.table("master_products").delete().eq("product_name", product_name).execute()
        except Exception: pass
            
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM master_products WHERE product_name=?", (product_name,))
    conn.commit()
    conn.close()

def bulk_upload_master_products(records):
    if supabase:
        try: supabase.table("master_products").insert(records).execute()
        except Exception: pass
            
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    for item in records:
        c.execute("INSERT OR REPLACE INTO master_products (product_name, pack, mrp, rate, tax) VALUES (?, ?, ?, ?, ?)", 
                  (item["product_name"], item.get("pack", ""), item.get("mrp", 0.0), item.get("rate", 0.0), item.get("tax", 12.0)))
    conn.commit()
    conn.close()

def sync_entire_master_products(edited_df):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM master_products")
    
    records = []
    for _, r in edited_df.iterrows():
        p_name = str(r.get("product_name", "")).strip()
        if p_name and p_name.lower() != "nan":
            pack = str(r.get("pack", ""))
            mrp = clean_float(r.get("mrp"), 0.0)
            rate = clean_float(r.get("rate"), 0.0)
            tax = clean_float(r.get("tax"), 12.0)
            
            c.execute("INSERT OR REPLACE INTO master_products (product_name, pack, mrp, rate, tax) VALUES (?, ?, ?, ?, ?)",
                      (p_name, pack, mrp, rate, tax))
            records.append({"product_name": p_name, "pack": pack, "mrp": mrp, "rate": rate, "tax": tax})
            
    conn.commit()
    conn.close()
    
    if supabase:
        try:
            supabase.table("master_products").delete().neq("id", -1).execute()
            if records:
                supabase.table("master_products").insert(records).execute()
        except Exception: pass

def auto_correct_brand(scanned_name, master_list):
    if not scanned_name or str(scanned_name).strip() == "":
        return "Unknown Item"
    matches = difflib.get_close_matches(scanned_name, master_list, n=1, cutoff=0.65)
    return matches[0] if matches else scanned_name.strip()

def save_transaction_data(table_name, items, invoice, party):
    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    records = []
    for row in items:
        records.append({
            "invoice": invoice,
            "party": party,
            "product": row.get('PRODUCT', ''),
            "pack": row.get('PACK', ''),
            "qty": float(row.get('QTY', 0)),
            "free_qty": str(row.get('DEAL/FREE', '')),
            "mrp": float(row.get('MRP', 0)),
            "disc_pct": float(row.get('DISC (%)', 0)),
            "disc_rs": float(row.get('DISC (₹)', 0)),
            "rate": float(row.get('RATE', 0)),
            "gst": float(row.get('GST', 0)),
            "amount": float(row.get('AMOUNT', 0)),
            "created_at": today
        })
    
    if supabase:
        try: supabase.table(table_name).insert(records).execute()
        except Exception: pass
    
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    for r in records:
        c.execute(f'''INSERT INTO {table_name} (invoice, party, product, pack, qty, free_qty, mrp, disc_pct, disc_rs, rate, gst, amount, created_at)
                      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                  (r["invoice"], r["party"], r["product"], r["pack"], r["qty"], r["free_qty"], r["mrp"], r["disc_pct"], r["disc_rs"], r["rate"], r["gst"], r["amount"], r["created_at"]))
    conn.commit()
    conn.close()

def load_transaction_data(table_name):
    if supabase:
        try:
            res = supabase.table(table_name).select("*").order("id", desc=True).execute()
            if res.data: return pd.DataFrame(res.data)
        except Exception: pass
            
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query(f"SELECT * FROM {table_name} ORDER BY id DESC", conn)
    conn.close()
    return df

def load_all_users():
    if supabase:
        try:
            res = supabase.table("users").select("*").execute()
            if res.data: return {row["username"]: {"password": row["password"], "name": row["name"], "role": row["role"]} for row in res.data}
        except Exception: pass
            
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT username, password, name, role FROM users")
    rows = c.fetchall()
    conn.close()
    return {r[0]: {"password": r[1], "name": r[2], "role": r[3]} for r in rows}

def save_new_user(username, password, name, role):
    if supabase:
        try: supabase.table("users").insert({"username": username, "password": password, "name": name, "role": role}).execute()
        except Exception: pass
            
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO users VALUES (?, ?, ?, ?)", (username, password, name, role))
    conn.commit()
    conn.close()

def delete_user_db(username):
    if supabase:
        try: supabase.table("users").delete().eq("username", username).execute()
        except Exception: pass
            
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM users WHERE username=?", (username,))
    conn.commit()
    conn.close()

def clean_float(val, default=0.0):
    if pd.isnull(val) or val is None:
        return default
    val_str = str(val).strip()
    match = re.search(r"[-+]?\d*\.\d+|\d+", val_str)
    if match:
        try: return float(match.group())
        except ValueError: return default
    return default

# ==========================================
# GEMINI AI SETUP
# ==========================================
if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

def process_bill_with_gemini(uploaded_file, text_input, master_df):
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        master_list = master_df["product_name"].tolist() if not master_df.empty else []
        
        prompt = f"""
        You are a pharma ERP assistant. Extract ALL medicine line items accurately from this invoice/order slip.
        Master Reference Product List: {", ".join(master_list)}

        Output ONLY a raw valid JSON array. No preamble, no markdown tags.
        JSON format:
        [
          {{"PRODUCT": "Item Name", "PACK": "10x10", "QTY": 10, "DEAL": "10+2", "MRP": 100.0, "DISC_PCT": 0.0, "DISC_RS": 0.0, "RATE": 50.0, "GST": 12.0}}
        ]
        """
        if uploaded_file:
            img = Image.open(uploaded_file)
            response = model.generate_content([prompt, img])
        else:
            response = model.generate_content([prompt, text_input])
            
        clean_txt = response.text.replace("```json", "").replace("```", "").strip()
        json_match = re.search(r'
