import sqlite3
import pandas as pd
import streamlit as st
from datetime import datetime, date, timedelta
from fpdf import FPDF
import urllib.parse
import json
import re
import difflib
import google.generativeai as genai
from PIL import Image
from supabase import create_client, Client

# ==========================================
# PAGE CONFIG & STYLING (ORANGE THEME)
# ==========================================
st.set_page_config(page_title="SGB / LCB Pharma Wholesale ERP", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
    <style>
    .stApp { background-color: #FFF9F5; }
    .main-header { font-size: 26px; font-weight: bold; color: #E65100; text-align: center; margin-bottom: 20px; }
    .stButton>button { width: 100%; border-radius: 8px; font-weight: bold; background-color: #FB8C00; color: white; border: none; }
    .stButton>button:hover { background-color: #EF6C00; color: white; }
    .ai-box { background-color: #FFF3E0; padding: 18px; border-radius: 10px; border-left: 6px solid #F57C00; margin-bottom: 20px; }
    [data-testid="stSidebar"] { background-color: #FFF0E6; }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# HYBRID DATABASE SETUP (SUPABASE + LOCAL SQLITE)
# ==========================================
DB_FILE = "pharma_erp.db"

def init_local_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS sales 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, invoice TEXT, party TEXT, product TEXT, pack TEXT, batch TEXT, expiry TEXT, qty REAL, free_qty TEXT, mrp REAL, disc_pct REAL, disc_rs REAL, rate REAL, gst REAL, amount REAL, created_at TEXT, sr_username TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS purchase 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, invoice TEXT, party TEXT, product TEXT, pack TEXT, batch TEXT, expiry TEXT, qty REAL, free_qty TEXT, mrp REAL, disc_pct REAL, disc_rs REAL, rate REAL, gst REAL, amount REAL, created_at TEXT, sr_username TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (username TEXT PRIMARY KEY, password TEXT, name TEXT, role TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS master_products 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, product_name TEXT UNIQUE, pack TEXT, mrp REAL, rate REAL, tax REAL)''')
    
    for tbl in ["sales", "purchase"]:
        for col, dtype in [("sr_username", "TEXT"), ("batch", "TEXT"), ("expiry", "TEXT"), ("pack", "TEXT"), ("free_qty", "TEXT"), ("disc_pct", "REAL"), ("disc_rs", "REAL")]:
            try: c.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {dtype}")
            except Exception: pass
            
    for col, dtype in [("pack", "TEXT"), ("mrp", "REAL"), ("rate", "REAL"), ("tax", "REAL")]:
        try: c.execute(f"ALTER TABLE master_products ADD COLUMN {col} {dtype}")
        except Exception: pass
    
    c.execute("INSERT OR IGNORE INTO users VALUES ('manager', 'admin123', 'Manager', 'Manager')")
    c.execute("INSERT OR IGNORE INTO users VALUES ('satya', 'satya123', 'Satya Sahu', 'Sales Executive')")
    
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

def sync_entire_master_products(edited_df):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM master_products")
    
    records = []
    for _, r in edited_df.iterrows():
        p_name = str(r.get("product_name", "")).strip()
        if p_name and p_name.lower() != "nan":
            pack = str(r.get("pack", "00"))
            mrp = clean_float(r.get("mrp"), 0.0)
            tax = clean_float(r.get("tax"), 5.0)
            rate = clean_float(r.get("rate"), round((mrp * 80.0) / (100.0 + tax), 2))
            
            c.execute("INSERT INTO master_products (product_name, pack, mrp, rate, tax) VALUES (?, ?, ?, ?, ?)",
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

def save_transaction_data(table_name, items, invoice, party, sr_username):
    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    records = []
    for row in items:
        records.append({
            "invoice": invoice,
            "party": party,
            "product": row.get('PRODUCT', ''),
            "pack": row.get('PACK', '00'),
            "batch": str(row.get('BATCH', '00')),
            "expiry": str(row.get('EXPIRY', '00')),
            "qty": float(row.get('QTY', 0)),
            "free_qty": str(row.get('DEAL/FREE', '00')),
            "mrp": float(row.get('MRP', 0)),
            "disc_pct": float(row.get('DISC (%)', 0)),
            "disc_rs": float(row.get('DISC (₹)', 0)),
            "rate": float(row.get('RATE', 0)),
            "gst": float(row.get('GST', 5.0)),
            "amount": float(row.get('AMOUNT', 0)),
            "created_at": today,
            "sr_username": sr_username
        })
    
    if supabase:
        try: supabase.table(table_name).insert(records).execute()
        except Exception: pass
    
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    for r in records:
        c.execute(f'''INSERT INTO {table_name} (invoice, party, product, pack, batch, expiry, qty, free_qty, mrp, disc_pct, disc_rs, rate, gst, amount, created_at, sr_username)
                      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                  (r["invoice"], r["party"], r["product"], r["pack"], r["batch"], r["expiry"], r["qty"], r["free_qty"], r["mrp"], r["disc_pct"], r["disc_rs"], r["rate"], r["gst"], r["amount"], r["created_at"], r["sr_username"]))
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

def filter_by_date_range(df, start_date, end_date, date_col='created_at'):
    if df.empty or date_col not in df.columns:
        return df
    temp_dates = pd.to_datetime(df[date_col], errors='coerce').dt.date
    s_date = start_date if isinstance(start_date, date) else pd.to_datetime(start_date).date()
    e_date = end_date if isinstance(end_date, date) else pd.to_datetime(end_date).date()
    return df[(temp_dates >= s_date) & (temp_dates <= e_date)]

def get_existing_parties():
    sales_df = load_transaction_data("sales")
    pur_df = load_transaction_data("purchase")
    p1 = sales_df['party'].dropna().unique().tolist() if not sales_df.empty else []
    p2 = pur_df['party'].dropna().unique().tolist() if not pur_df.empty else []
    return sorted(list(set(p1 + p2)))

def get_latest_batch_expiry(product_name):
    df_pur = load_transaction_data("purchase")
    if not df_pur.empty and 'product' in df_pur.columns:
        prod_pur = df_pur[df_pur['product'] == product_name]
        if not prod_pur.empty:
            latest_row = prod_pur.iloc[0]
            batch = str(latest_row.get('batch', '00'))
            expiry = str(latest_row.get('expiry', '00'))
            return batch if batch and batch != 'nan' else '00', expiry if expiry and expiry != 'nan' else '00'
    return '00', '00'

# ==========================================
# GEMINI AI SETUP
# ==========================================
if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

def process_bill_with_gemini(uploaded_file, text_input, master_df):
    try:
        model = genai.GenerativeModel('gemini-3.5-flash-lite')
        master_list = master_df["product_name"].tolist() if not master_df.empty else []
        
        prompt = f"""
        You are a pharma ERP assistant. Extract ALL medicine line items accurately from this invoice/order slip including Batch and Expiry Date.
        Master Reference Product List: {", ".join(master_list)}

        Output ONLY a raw valid JSON array. No preamble, no markdown tags (do NOT wrap in ```json).
        JSON format:
        [
          {{"PRODUCT": "Item Name", "PACK": "00", "BATCH": "00", "EXPIRY": "00", "QTY": 0, "DEAL": "00", "MRP": 0.0, "DISC_PCT": 0.0, "DISC_RS": 0.0, "RATE": 0.0, "GST": 5.0}}
        ]
        """
        if uploaded_file:
            img = Image.open(uploaded_file)
            response = model.generate_content([prompt, img])
        else:
            response = model.generate_content([prompt, text_input])
            
        clean_txt = response.text.replace("```json", "").replace("```", "").strip()
        json_match = re.search(r'\[.*\]', clean_txt, re.DOTALL)
        if json_match:
            clean_txt = json_match.group(0)
            
        data = json.loads(clean_txt)
        
        cleaned_data = []
        for item in data:
            raw_prod = str(item.get("PRODUCT", "")).strip()
            corrected_prod = auto_correct_brand(raw_prod, master_list)
            m_match = master_df[master_df["product_name"] == corrected_prod] if not master_df.empty else pd.DataFrame()
            
            pack = str(item.get("PACK", "")) or (m_match["pack"].values[0] if not m_match.empty else "00")
            batch = str(item.get("BATCH", "00"))
            expiry = str(item.get("EXPIRY", "00"))
            qty = clean_float(item.get("QTY"), default=0.0)
            deal = str(item.get("DEAL", "00"))
            
            mrp = clean_float(item.get("MRP"), default=0.0)
            if mrp == 0.0 and not m_match.empty:
                mrp = clean_float(m_match["mrp"].values[0])

            disc_pct = clean_float(item.get("DISC_PCT"), default=0.0)
            disc_rs = clean_float(item.get("DISC_RS"), default=0.0)

            gst = clean_float(item.get("GST"), default=5.0)
            rate = clean_float(item.get("RATE"), default=0.0)
            
            if rate == 0.0 and mrp > 0:
                if disc_pct > 0:
                    rate = round(mrp * (1 - (disc_pct / 100.0)), 2)
                else:
                    rate = round((mrp * 80.0) / (100.0 + gst), 2)
                
            eff_rate = rate - disc_rs
            if disc_pct > 0 and disc_rs == 0:
                eff_rate = rate * (1 - (disc_pct / 100.0))
                
            amt = qty * eff_rate
            
            cleaned_data.append({
                "PRODUCT": corrected_prod,
                "PACK": pack,
                "BATCH": batch,
                "EXPIRY": expiry,
                "QTY": qty,
                "DEAL/FREE": deal,
                "MRP": mrp,
                "DISC (%)": disc_pct,
                "DISC (₹)": disc_rs,
                "RATE": round(rate, 2),
                "GST": gst,
                "AMOUNT": round(amt, 2)
            })
        return cleaned_data
    except Exception as e:
        st.error(f"AI Extraction Error: {e}")
        return []

# ==========================================
# PDF GENERATOR
# ==========================================
def generate_pdf_invoice(party, inv, gst_no, cart_data, total_mrp, bill_disc, sub_total, gst_val, net_val):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", 'B', 16)
    pdf.cell(190, 10, "SGB / LCB PHARMA WHOLESALE INVOICE", new_x="LMARGIN", new_y="NEXT", align='C')
    pdf.set_font("Helvetica", '', 10)
    pdf.cell(190, 6, f"Party: {party} | GSTIN: {gst_no}", new_x="LMARGIN", new_y="NEXT", align='C')
    pdf.cell(190, 6, f"Invoice No: {inv} | Date: {datetime.now().strftime('%d-%m-%Y')}", new_x="LMARGIN", new_y="NEXT", align='C')
    pdf.ln(5)
    
    pdf.set_font("Helvetica", 'B', 8)
    pdf.cell(35, 7, "Product", 1)
    pdf.cell(12, 7, "Pack", 1)
    pdf.cell(15, 7, "Batch", 1)
    pdf.cell(12, 7, "Exp", 1)
    pdf.cell(12, 7, "Qty", 1)
    pdf.cell(12, 7, "Deal", 1)
    pdf.cell(18, 7, "MRP (Rs)", 1)
    pdf.cell(16, 7, "Disc(%)", 1)
    pdf.cell(18, 7, "Rate (Rs)", 1)
    pdf.cell(20, 7, "Amount", 1)
    pdf.ln()
    
    pdf.set_font("Helvetica", '', 8)
    for row in cart_data:
        pdf.cell(35, 6, str(row['PRODUCT'])[:18], 1)
        pdf.cell(12, 6, str(row.get('PACK', '00'))[:6], 1)
        pdf.cell(15, 6, str(row.get('BATCH', '00'))[:8], 1)
        pdf.cell(12, 6, str(row.get('EXPIRY', '00'))[:6], 1)
        pdf.cell(12, 6, str(row['QTY']), 1)
        pdf.cell(12, 6, str(row.get('DEAL/FREE', '')), 1)
        pdf.cell(18, 6, f"{float(row['MRP']):.2f}", 1)
        pdf.cell(16, 6, f"{float(row.get('DISC (%)', 0)):.1f}%", 1)
        pdf.cell(18, 6, f"{float(row['RATE']):.2f}", 1)
        pdf.cell(20, 6, f"{float(row['AMOUNT']):.2f}", 1)
        pdf.ln()
        
    pdf.ln(4)
    pdf.set_font("Helvetica", 'B', 10)
    pdf.cell(190, 6, f"Sub Total: Rs. {sub_total:,.2f}", new_x="LMARGIN", new_y="NEXT", align='R')
    pdf.cell(190, 6, f"Extra Bill Discount: Rs. {bill_disc:,.2f}", new_x="LMARGIN", new_y="NEXT", align='R')
    pdf.cell(190, 6, f"GST Tax: Rs. {gst_val:,.2f}", new_x="LMARGIN", new_y="NEXT", align='R')
    pdf.cell(190, 6, f"Grand Total: Rs. {net_val:,.2f}", new_x="LMARGIN", new_y="NEXT", align='R')
    
    return bytes(pdf.output())

if "logged_in" not in st.session_state: st.session_state["logged_in"] = False
if "scanned_cart" not in st.session_state: st.session_state["scanned_cart"] = []

USERS_DB = load_all_users()
MASTER_DF = load_master_products()
MASTER_LIST = ["00"] + (MASTER_DF["product_name"].tolist() if not MASTER_DF.empty else [])

if not st.session_state["logged_in"]:
    st.markdown("<h2 class='main-header'>🍊 SGB / LCB Pharma Wholesale ERP</h2>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        username_input = st.text_input("Username").strip().lower()
        password_input = st.text_input("Password", type="password")
        if st.button("🚀 Secure Login"):
            if username_input in USERS_DB and USERS_DB[username_input]["password"] == password_input:
                st.session_state["logged_in"] = True
                st.session_state["logged_user"] = USERS_DB[username_input]
                st.session_state["username"] = username_input
                st.rerun()
            else: st.error("❌ Invalid Username or Password")
    st.stop()

logged_user = st.session_state["logged_user"]
is_manager = logged_user["role"] == "Manager"

st.sidebar.title(f"🍊 {logged_user['name']}")
st.sidebar.caption(f"Role: {logged_user['role']}")

nav_options = [
    "🤖 AI Smart Scan & Billing",
    "📦 Sales History",
    "📥 Purchase History (Stock In)",
    "🏭 Live Stock & Quantity-Value Summary"
]

if is_manager:
    nav_options.append("👥 User Management (Admin)")
    nav_options.append("🏷️ Manage Master Products")

active_tab = st.sidebar.radio("Navigation", nav_options)

if st.sidebar.button("🚪 Logout"):
    st.session_state["logged_in"] = False
    st.session_state["scanned_cart"] = []
    st.rerun()

# ==========================================
# 1. AI SMART SCAN & BILLING
# ==========================================
if active_tab == "🤖 AI Smart Scan & Billing":
    st.markdown("<h2 style='color: #E65100;'>🤖 AI Scanner & Wholesale Billing</h2>", unsafe_allow_html=True)
    
    c1, c2 = st.columns(2)
    with c1: uploaded_img = st.file_uploader("📷 Upload Invoice / Order Slip", type=["jpg", "png", "jpeg"])
    with c2: raw_text = st.text_area("✍️ Or Paste Text Invoice Data")
        
    if st.button("✨ Auto-Extract via Gemini AI"):
        if uploaded_img or raw_text:
            with st.spinner("Scanning Document & Auto-Detecting Products..."):
                items = process_bill_with_gemini(uploaded_img, raw_text, MASTER_DF)
                if items:
                    st.session_state["scanned_cart"].extend(items)
                    st.success(f"✅ Successfully Extracted {len(items)} Items!")
                    st.rerun()
                else:
                    st.error("❌ Could not extract items.")
        else: st.warning("Please upload a slip image or paste text.")

    st.markd
