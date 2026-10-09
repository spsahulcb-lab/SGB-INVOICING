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
elif active_tab == "🤖 AI Smart Scan & Billing":
    st.markdown("AI Scanner & Wholesale Billing", unsafe_allow_html=True)

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

st.markdown("---")

st.subheader("📝 Wholesale Bill Meta Info (Fully Editable)")
f1, f2, f3 = st.columns(3)

existing_parties = get_existing_parties()
with f1:
    party_mode = st.radio("Party Input Mode:", ["Select Saved Party", "Type New Party"], horizontal=True)
    if party_mode == "Select Saved Party" and existing_parties:
        sel_saved_party = st.selectbox("Select Party / Medical Store", existing_parties)
        party_name = st.text_input("Or Edit Party Name", value=sel_saved_party)
    else:
        party_name = st.text_input("Party / Supplier / Medical Store Name", value="Sharma Medical Hall")
        
with f2: inv_no = st.text_input("Invoice No", value=f"INV-{int(datetime.now().timestamp())}")
with f3: gst_no = st.text_input("Party GSTIN", value="09AAAAA0000A1Z5")

st.markdown("##### ➕ Manual Item Addition (Multiple Batch & MRP Support)")

# Product selection for manual add
sel_prod = st.selectbox("Select Product", MASTER_LIST, index=0)

# Fetch all previous purchase history for this product to get multiple batches & MRPs
df_pur_hist = load_transaction_data("purchase")
prod_batches = []
if sel_prod != "00" and not df_pur_hist.empty and 'product' in df_pur_hist.columns:
    p_history = df_pur_hist[df_pur_hist['product'] == sel_prod]
    for _, row in p_history.iterrows():
        b = str(row.get('batch', '00'))
        e = str(row.get('expiry', '00'))
        m = clean_float(row.get('mrp', 0))
        r = clean_float(row.get('rate', 0))
        combo_label = f"Batch: {b} | Exp: {e} | MRP: ₹{m} | Rate: ₹{r}"
        if combo_label not in [x['label'] for x in prod_batches]:
            prod_batches.append({
                "label": combo_label,
                "batch": b,
                "expiry": e,
                "mrp": m,
                "rate": r
            })

# Fallback to master product if no purchase history exists
def_pack = "10x10"
def_mrp = 0.0
def_rate = 0.0
if sel_prod != "00" and not MASTER_DF.empty:
    m_match = MASTER_DF[MASTER_DF["product_name"] == sel_prod]
    if not m_match.empty:
        def_pack = str(m_match["pack"].values[0])
        def_mrp = float(m_match["mrp"].values[0])
        def_rate = float(m_match["rate"].values[0])

selected_batch_info = None
if prod_batches:
    selected_batch_label = st.selectbox("🔄 Select Batch & MRP Option (Recent Default)", [x["label"] for x in prod_batches])
    selected_batch_info = next((x for x in prod_batches if x["label"] == selected_batch_label), None)

# Billing Mode Options Restored!
rate_mode = st.radio("Select Billing Mode:", ["NET RATE Mode (0% GST)", "Gross Rate Mode (With GST)"], horizontal=True)

if rate_mode == "NET RATE Mode (0% GST)":
    with st.form("net_billing_form", clear_on_submit=False):
   r1_c1, r1_c2, r1_c3 = st.columns(3)
with r1_c1: s_qty = st.number_input("Qty", min_value=1, value=1)
with r1_c2: m_pack = st.text_input("Pack", value=def_pack)
with r1_c3: s_mrp = st.number_input("MRP (₹)", min_value=0.0, value=selected_batch_info["mrp"] if selected_batch_info else def_mrp)

        r2_c1, r2_c2 = st.columns(2)
        with r2_c1: m_batch = st.text_input("Batch", value=selected_batch_info["batch"] if selected_batch_info else "00")
        with r2_c2: m_exp = st.text_input("Expiry", value=selected_batch_info["expiry"] if selected_batch_info else "00")
        
        s_disc_pct = st.number_input("Discount %", min_value=0.0, max_value=100.0, value=0.0)
        
        submitted_net = st.form_submit_button("➕ Add Net Item to Bill")
        
        if submitted_net and sel_prod != "00":
            calc_net_rate = round(s_mrp * (1 - (s_disc_pct / 100.0)), 2)
            amt = float(s_qty) * calc_net_rate
            st.session_state["scanned_cart"].append({
                "PRODUCT": sel_prod, "PACK": m_pack, "BATCH": m_batch, "EXPIRY": m_exp,
                "QTY": float(s_qty), "DEAL/FREE": "00", "MRP": float(s_mrp),
                "DISC (%)": float(s_disc_pct), "DISC (₹)": 0.0,
                "RATE": calc_net_rate, "GST": 0.0, "AMOUNT": round(amt, 2)
            })
            st.rerun()
else:
    with st.form("gross_billing_form", clear_on_submit=False):
        
r1_c1, r1_c2, r1_c3, r1_c4 = st.columns(4)
with r1_c1: s_qty = st.number_input("Qty", min_value=1, value=1)
with r1_c2: m_pack = st.text_input("Pack", value=def_pack)
with r1_c3: s_mrp = st.number_input("MRP (₹)", min_value=0.0, value=selected_batch_info["mrp"] if selected_batch_info else def_mrp)
with r1_c4: s_gst_rate = st.number_input("GST (%)", min_value=0.0, value=5.0, step=1.0)

        r2_c1, r2_c2, r2_c3 = st.columns(3)
        with r2_c1: m_batch = st.text_input("Batch", value=selected_batch_info["batch"] if selected_batch_info else "00")
        with r2_c2: m_exp = st.text_input("Expiry", value=selected_batch_info["expiry"] if selected_batch_info else "00")
        with r2_c3: s_deal = st.text_input("Deal", value="00")
        
        s_disc_pct = st.number_input("Disc (%)", min_value=0.0, max_value=100.0, value=0.0)
        
        submitted_gross = st.form_submit_button("➕ Add Gross Item to Bill")
        

        if submitted_gross and sel_prod != "00":
            if s_disc_pct > 0:
                calc_rate = round(s_mrp * (1 - (s_disc_pct / 100.0)), 2)
            else:
                base_rate = selected_batch_info["rate"] if selected_batch_info and selected_batch_info["rate"] > 0 else def_rate
                calc_rate = base_rate if base_rate > 0 else round((s_mrp * 80.0) / (100.0 + s_gst_rate), 2)
            
            amt = float(s_qty) * calc_rate
            st.session_state["scanned_cart"].append({
                "PRODUCT": sel_prod, "PACK": m_pack, "BATCH": m_batch, "EXPIRY": m_exp,
                "QTY": float(s_qty), "DEAL/FREE": s_deal, "MRP": float(s_mrp),
                "DISC (%)": float(s_disc_pct), "DISC (₹)": 0.0,
                "RATE": calc_rate, "GST": float(s_gst_rate), "AMOUNT": round(amt, 2)
            })
            st.rerun()

if st.session_state["scanned_cart"]:
    st.markdown("---")
    st.subheader("🛒 Current Bill Items (Fully Editable Table)")
    st.info("💡 Ab aap table ke andar **Product Name**, **MRP**, **Batch**, **Expiry**, **Qty**, aur **Rate** ko direct click karke change/edit kar sakte hain!")
    
    cart_df = pd.DataFrame(st.session_state["scanned_cart"])
    
    edited_df = st.data_editor(
        cart_df, 
        key="cart_editor", 
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "PRODUCT": st.column_config.TextColumn("PRODUCT", help="Click to edit product name"),
            "MRP": st.column_config.NumberColumn("MRP", format="₹ %.2f"),
            "RATE": st.column_config.NumberColumn("RATE", format="₹ %.2f"),
            "AMOUNT": st.column_config.NumberColumn("AMOUNT", format="₹ %.2f"),
        }
    )
    
    # Auto-recalculate amount if Qty or Rate changes in editor
    for idx, row in edited_df.iterrows():
        q = clean_float(row.get('QTY', 0))
        rt = clean_float(row.get('RATE', 0))
        edited_df.loc[idx, 'AMOUNT'] = round(q * rt, 2)

    st.session_state["scanned_cart"] = edited_df.to_dict('records')
    
    o_col1, o_col2 = st.columns([2, 1])
    with o_col2:
        extra_bill_disc = st.number_input("🎁 Extra Overall Bill Discount (₹)", min_value=0.0, value=0.0)
    
    if not edited_df.empty:
        sub_total = float(edited_df["AMOUNT"].sum())
        total_mrp_sum = float((edited_df["MRP"] * edited_df["QTY"]).sum())
        gst_val = sum([row["AMOUNT"] * (row["GST"] / 100.0) for _, row in edited_df.iterrows()])
        net_val = (sub_total - extra_bill_disc) + gst_val
    else:
        sub_total = total_mrp_sum = gst_val = net_val = 0.0
    
    st.markdown(f"""
🏷️ Total MRP: ₹ {total_mrp_sum:,.2f} | 🎁 Overall Extra Disc: ₹ {extra_bill_disc:,.2f}
💰 Sub Total: ₹ {sub_total:,.2f} | GST Tax: ₹ {gst_val:,.2f} | Grand Total: ₹ {net_val:,.2f}
""", unsafe_allow_html=True)

    save_col1, save_col2, save_col3, save_col4, save_col5 = st.columns(5)
    
elif active_tab == "🤖 AI Smart Scan & Billing":
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

    st.markdown("---")
    
    st.subheader("📝 Wholesale Bill Meta Info (Fully Editable)")
    f1, f2, f3 = st.columns(3)
    
    existing_parties = get_existing_parties()
    with f1:
        party_mode = st.radio("Party Input Mode:", ["Select Saved Party", "Type New Party"], horizontal=True)
        if party_mode == "Select Saved Party" and existing_parties:
            sel_saved_party = st.selectbox("Select Party / Medical Store", existing_parties)
            party_name = st.text_input("Or Edit Party Name", value=sel_saved_party)
        else:
            party_name = st.text_input("Party / Supplier / Medical Store Name", value="Sharma Medical Hall")
            
    with f2: inv_no = st.text_input("Invoice No", value=f"INV-{int(datetime.now().timestamp())}")
    with f3: gst_no = st.text_input("Party GSTIN", value="09AAAAA0000A1Z5")

    st.markdown("##### ➕ Manual Item Addition (Multiple Batch & MRP Support)")
    
    sel_prod = st.selectbox("Select Product", MASTER_LIST, index=0)
    
    df_pur_hist = load_transaction_data("purchase")
    prod_batches = []
    if sel_prod != "00" and not df_pur_hist.empty and 'product' in df_pur_hist.columns:
        p_history = df_pur_hist[df_pur_hist['product'] == sel_prod]
        for _, row in p_history.iterrows():
            b = str(row.get('batch', '00'))
            e = str(row.get('expiry', '00'))
            m = clean_float(row.get('mrp', 0))
            r = clean_float(row.get('rate', 0))
            combo_label = f"Batch: {b} | Exp: {e} | MRP: ₹{m} | Rate: ₹{r}"
            if combo_label not in [x['label'] for x in prod_batches]:
                prod_batches.append({
                    "label": combo_label,
                    "batch": b,
                    "expiry": e,
                    "mrp": m,
                    "rate": r
                })

    def_pack = "10x10"
    def_mrp = 0.0
    def_rate = 0.0
    if sel_prod != "00" and not MASTER_DF.empty:
        m_match = MASTER_DF[MASTER_DF["product_name"] == sel_prod]
        if not m_match.empty:
            def_pack = str(m_match["pack"].values[0])
            def_mrp = float(m_match["mrp"].values[0])
            def_rate = float(m_match["rate"].values[0])

    selected_batch_info = None
    if prod_batches:
        selected_batch_label = st.selectbox("🔄 Select Batch & MRP Option (Recent Default)", [x["label"] for x in prod_batches])
        selected_batch_info = next((x for x in prod_batches if x["label"] == selected_batch_label), None)

    rate_mode = st.radio("Select Billing Mode:", ["NET RATE Mode (0% GST)", "Gross Rate Mode (With GST)"], horizontal=True)

    if rate_mode == "NET RATE Mode (0% GST)":
        with st.form("net_billing_form", clear_on_submit=False):
            st.markdown("<div class='compact-form'>", unsafe_allow_html=True)
            r1_c1, r1_c2, r1_c3 = st.columns(3)
            with r1_c1: s_qty = st.number_input("Qty", min_value=1, value=1)
            with r1_c2: m_pack = st.text_input("Pack", value=def_pack)
            with r1_c3: s_mrp = st.number_input("MRP (₹)", min_value=0.0, value=selected_batch_info["mrp"] if selected_batch_info else def_mrp)

            r2_c1, r2_c2 = st.columns(2)
            with r2_c1: m_batch = st.text_input("Batch", value=selected_batch_info["batch"] if selected_batch_info else "00")
            with r2_c2: m_exp = st.text_input("Expiry", value=selected_batch_info["expiry"] if selected_batch_info else "00")
            
            s_disc_pct = st.number_input("Discount %", min_value=0.0, max_value=100.0, value=0.0)
            
            submitted_net = st.form_submit_button("➕ Add Net Item to Bill")
            st.markdown("</div>", unsafe_allow_html=True)

            if submitted_net and sel_prod != "00":
                calc_net_rate = round(s_mrp * (1 - (s_disc_pct / 100.0)), 2)
                amt = float(s_qty) * calc_net_rate
if rate_mode == "NET RATE Mode (0% GST)":
    with st.form("net_billing_form", clear_on_submit=False):
   r1_c1, r1_c2, r1_c3 = st.columns(3)
with r1_c1: s_qty = st.number_input("Qty", min_value=1, value=1)
with r1_c2: m_pack = st.text_input("Pack", value=def_pack)
with r1_c3: s_mrp = st.number_input("MRP (₹)", min_value=0.0, value=selected_batch_info["mrp"] if selected_batch_info else def_mrp)

        r2_c1, r2_c2 = st.columns(2)
        with r2_c1: m_batch = st.text_input("Batch", value=selected_batch_info["batch"] if selected_batch_info else "00")
        with r2_c2: m_exp = st.text_input("Expiry", value=selected_batch_info["expiry"] if selected_batch_info else "00")
        
        s_disc_pct = st.number_input("Discount %", min_value=0.0, max_value=100.0, value=0.0)
        
        submitted_net = st.form_submit_button("➕ Add Net Item to Bill")
        
        if submitted_net and sel_prod != "00":
            calc_net_rate = round(s_mrp * (1 - (s_disc_pct / 100.0)), 2)
            amt = float(s_qty) * calc_net_rate
            st.session_state["scanned_cart"].append({
                "PRODUCT": sel_prod, "PACK": m_pack, "BATCH": m_batch, "EXPIRY": m_exp,
                "QTY": float(s_qty), "DEAL/FREE": "00", "MRP": float(s_mrp),
                "DISC (%)": float(s_disc_pct), "DISC (₹)": 0.0,
                "RATE": calc_net_rate, "GST": 0.0, "AMOUNT": round(amt, 2)
            })
            st.rerun()
else:
    with st.form("gross_billing_form", clear_on_submit=False):
        
r1_c1, r1_c2, r1_c3, r1_c4 = st.columns(4)
with r1_c1: s_qty = st.number_input("Qty", min_value=1, value=1)
with r1_c2: m_pack = st.text_input("Pack", value=def_pack)
with r1_c3: s_mrp = st.number_input("MRP (₹)", min_value=0.0, value=selected_batch_info["mrp"] if selected_batch_info else def_mrp)
with r1_c4: s_gst_rate = st.number_input("GST (%)", min_value=0.0, value=5.0, step=1.0)

        r2_c1, r2_c2, r2_c3 = st.columns(3)
        with r2_c1: m_batch = st.text_input("Batch", value=selected_batch_info["batch"] if selected_batch_info else "00")
        with r2_c2: m_exp = st.text_input("Expiry", value=selected_batch_info["expiry"] if selected_batch_info else "00")
        with r2_c3: s_deal = st.text_input("Deal", value="00")
        
        s_disc_pct = st.number_input("Disc (%)", min_value=0.0, max_value=100.0, value=0.0)
        
        submitted_gross = st.form_submit_button("➕ Add Gross Item to Bill")
        

        if submitted_gross and sel_prod != "00":
            if s_disc_pct > 0:
                calc_rate = round(s_mrp * (1 - (s_disc_pct / 100.0)), 2)
            else:
                base_rate = selected_batch_info["rate"] if selected_batch_info and selected_batch_info["rate"] > 0 else def_rate
                calc_rate = base_rate if base_rate > 0 else round((s_mrp * 80.0) / (100.0 + s_gst_rate), 2)
            
            amt = float(s_qty) * calc_rate
            st.session_state["scanned_cart"].append({
                "PRODUCT": sel_prod, "PACK": m_pack, "BATCH": m_batch, "EXPIRY": m_exp,
                "QTY": float(s_qty), "DEAL/FREE": s_deal, "MRP": float(s_mrp),
                "DISC (%)": float(s_disc_pct), "DISC (₹)": 0.0,
                "RATE": calc_rate, "GST": float(s_gst_rate), "AMOUNT": round(amt, 2)
            })
            st.rerun()

if st.session_state["scanned_cart"]:
    st.markdown("---")
    st.subheader("🛒 Current Bill Items (Fully Editable Table)")
    st.info("💡 Ab aap table ke andar **Product Name**, **MRP**, **Batch**, **Expiry**, **Qty**, aur **Rate** ko direct click karke change/edit kar sakte hain!")
    
    cart_df = pd.DataFrame(st.session_state["scanned_cart"])
    
    edited_df = st.data_editor(
        cart_df, 
        key="cart_editor", 
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "PRODUCT": st.column_config.TextColumn("PRODUCT", help="Click to edit product name"),
            "MRP": st.column_config.NumberColumn("MRP", format="₹ %.2f"),
            "RATE": st.column_config.NumberColumn("RATE", format="₹ %.2f"),
            "AMOUNT": st.column_config.NumberColumn("AMOUNT", format="₹ %.2f"),
        }
    )
    
    # Auto-recalculate amount if Qty or Rate changes in editor
    for idx, row in edited_df.iterrows():
        q = clean_float(row.get('QTY', 0))
        rt = clean_float(row.get('RATE', 0))
        edited_df.loc[idx, 'AMOUNT'] = round(q * rt, 2)

    st.session_state["scanned_cart"] = edited_df.to_dict('records')
    
    o_col1, o_col2 = st.columns([2, 1])
    with o_col2:
        extra_bill_disc = st.number_input("🎁 Extra Overall Bill Discount (₹)", min_value=0.0, value=0.0)
    
    if not edited_df.empty:
        sub_total = float(edited_df["AMOUNT"].sum())
        total_mrp_sum = float((edited_df["MRP"] * edited_df["QTY"]).sum())
        gst_val = sum([row["AMOUNT"] * (row["GST"] / 100.0) for _, row in edited_df.iterrows()])
        net_val = (sub_total - extra_bill_disc) + gst_val
    else:
        sub_total = total_mrp_sum = gst_val = net_val = 0.0
    
    st.markdown(f"""
🏷️ Total MRP: ₹ {total_mrp_sum:,.2f} | 🎁 Overall Extra Disc: ₹ {extra_bill_disc:,.2f}
💰 Sub Total: ₹ {sub_total:,.2f} | GST Tax: ₹ {gst_val:,.2f} | Grand Total: ₹ {net_val:,.2f}
""", unsafe_allow_html=True)

    save_col1, save_col2, save_col3, save_col4, save_col5 = st.columns(5)
    
elif active_tab == "🤖 AI Smart Scan & Billing":
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

    st.markdown("---")
    
    st.subheader("📝 Wholesale Bill Meta Info (Fully Editable)")
    f1, f2, f3 = st.columns(3)
    
    existing_parties = get_existing_parties()
    with f1:
        party_mode = st.radio("Party Input Mode:", ["Select Saved Party", "Type New Party"], horizontal=True)
        if party_mode == "Select Saved Party" and existing_parties:
            sel_saved_party = st.selectbox("Select Party / Medical Store", existing_parties)
            party_name = st.text_input("Or Edit Party Name", value=sel_saved_party)
        else:
            party_name = st.text_input("Party / Supplier / Medical Store Name", value="Sharma Medical Hall")
            
    with f2: inv_no = st.text_input("Invoice No", value=f"INV-{int(datetime.now().timestamp())}")
    with f3: gst_no = st.text_input("Party GSTIN", value="09AAAAA0000A1Z5")

    st.markdown("##### ➕ Manual Item Addition (Multiple Batch & MRP Support)")
    
    sel_prod = st.selectbox("Select Product", MASTER_LIST, index=0)
    
    df_pur_hist = load_transaction_data("purchase")
    prod_batches = []
    if sel_prod != "00" and not df_pur_hist.empty and 'product' in df_pur_hist.columns:
        p_history = df_pur_hist[df_pur_hist['product'] == sel_prod]
        for _, row in p_history.iterrows():
            b = str(row.get('batch', '00'))
            e = str(row.get('expiry', '00'))
            m = clean_float(row.get('mrp', 0))
            r = clean_float(row.get('rate', 0))
            combo_label = f"Batch: {b} | Exp: {e} | MRP: ₹{m} | Rate: ₹{r}"
            if combo_label not in [x['label'] for x in prod_batches]:
                prod_batches.append({
                    "label": combo_label,
                    "batch": b,
                    "expiry": e,
                    "mrp": m,
                    "rate": r
                })

    def_pack = "10x10"
    def_mrp = 0.0
    def_rate = 0.0
    if sel_prod != "00" and not MASTER_DF.empty:
        m_match = MASTER_DF[MASTER_DF["product_name"] == sel_prod]
        if not m_match.empty:
            def_pack = str(m_match["pack"].values[0])
            def_mrp = float(m_match["mrp"].values[0])
            def_rate = float(m_match["rate"].values[0])

    selected_batch_info = None
    if prod_batches:
        selected_batch_label = st.selectbox("🔄 Select Batch & MRP Option (Recent Default)", [x["label"] for x in prod_batches])
        selected_batch_info = next((x for x in prod_batches if x["label"] == selected_batch_label), None)

    rate_mode = st.radio("Select Billing Mode:", ["NET RATE Mode (0% GST)", "Gross Rate Mode (With GST)"], horizontal=True)

    if rate_mode == "NET RATE Mode (0% GST)":
        with st.form("net_billing_form", clear_on_submit=False):
            st.markdown("<div class='compact-form'>", unsafe_allow_html=True)
            r1_c1, r1_c2, r1_c3 = st.columns(3)
            with r1_c1: s_qty = st.number_input("Qty", min_value=1, value=1)
            with r1_c2: m_pack = st.text_input("Pack", value=def_pack)
            with r1_c3: s_mrp = st.number_input("MRP (₹)", min_value=0.0, value=selected_batch_info["mrp"] if selected_batch_info else def_mrp)

            r2_c1, r2_c2 = st.columns(2)
            with r2_c1: m_batch = st.text_input("Batch", value=selected_batch_info["batch"] if selected_batch_info else "00")
            with r2_c2: m_exp = st.text_input("Expiry", value=selected_batch_info["expiry"] if selected_batch_info else "00")
            
            s_disc_p



# ==========================================
# 2. SALES HISTORY
# ==========================================
elif active_tab == "📦 Sales History":
    st.markdown("<h2 style='color: #E65100;'>📦 Wholesale Sales Register</h2>", unsafe_allow_html=True)
    
    df_sales = load_transaction_data("sales")
    
    if not df_sales.empty:
        st.markdown("##### 📅 Date Range Filter")
        d_col1, d_col2 = st.columns(2)
        with d_col1: start_d = st.date_input("Start Date", value=date.today() - timedelta(days=30), key="sal_start")
        with d_col2: end_d = st.date_input("End Date", value=date.today(), key="sal_end")
        
        df_sales = filter_by_date_range(df_sales, start_d, end_d)
        
        if is_manager:
            st.info("👑 **Manager Controls**: Review team cumulative sales or filter by Sales Executive.")
            sr_options = ["All Sales Team (Cumulative)"] + sorted([s for s in df_sales['sr_username'].dropna().unique()])
            sel_sr = st.selectbox("👤 Select Sales Executive / Team View:", sr_options)
            if sel_sr != "All Sales Team (Cumulative)":
                df_sales = df_sales[df_sales['sr_username'] == sel_sr]
        else:
            df_sales = df_sales[df_sales['sr_username'] == st.session_state['username']]

        parties_list = ["All Parties"] + sorted([p for p in df_sales['party'].unique() if p])
        selected_party = st.selectbox("🏬 Select Party to View Statement:", parties_list)
        
        filtered_df = df_sales if selected_party == "All Parties" else df_sales[df_sales['party'] == selected_party]
            
        total_sales_amt = filtered_df['amount'].sum() if 'amount' in filtered_df.columns else 0.0
        total_invoices = filtered_df['invoice'].nunique() if 'invoice' in filtered_df.columns else 0
        
        c1, c2 = st.columns(2)
        with c1: st.metric("📄 Total Invoices", total_invoices)
        with c2: st.metric("💰 Total Sales Amount", f"₹ {total_sales_amt:,.2f}")
            
        st.markdown("---")
        
        invoices_list = ["None (Summary View)"] + sorted(filtered_df['invoice'].unique().tolist(), reverse=True)
        selected_inv = st.selectbox("🔍 Select Particular Invoice / Bill to View Details:", invoices_list)
        
        if selected_inv != "None (Summary View)":
            inv_df = filtered_df[filtered_df['invoice'] == selected_inv]
            p_name = inv_df['party'].iloc[0] if not inv_df.empty else selected_party
            inv_date = inv_df['created_at'].iloc[0] if 'created_at' in inv_df.columns and not inv_df.empty else ""
            
            st.markdown(f"""
                <div style='background-color:#FFF3E0; padding:15px; border-radius:10px; border-left:5px solid #EF6C00; margin-bottom:15px;'>
                    <h3 style='color:#E65100; margin:0;'>🧾 Invoice No: {selected_inv}</h3>
                    <p style='margin:5px 0 0 0; color:#333;'><b>Party:</b> {p_name} | <b>Date/Time:</b> {inv_date}</p>
                </div>
            """, unsafe_allow_html=True)
            
            display_cols = [c for c in ['product', 'pack', 'batch', 'expiry', 'qty', 'free_qty', 'mrp', 'rate', 'gst', 'amount', 'sr_username'] if c in inv_df.columns]
            st.dataframe(inv_df[display_cols], use_container_width=True)
            
            inv_subtotal = inv_df['amount'].sum() if 'amount' in inv_df.columns else 0.0
            st.markdown(f"#### **Grand Total for {selected_inv}: ₹ {inv_subtotal:,.2f}**")
        else:
            st.subheader(f"📋 Sales Summary Statement ({selected_party})")
            display_cols = [c for c in ['invoice', 'created_at', 'party', 'product', 'pack', 'batch', 'expiry', 'qty', 'rate', 'amount', 'sr_username'] if c in filtered_df.columns]
            st.dataframe(filtered_df[display_cols], use_container_width=True)
    else:
        st.info("No Sales records found in selected range.")

# ==========================================
# 3. PURCHASE HISTORY
# ==========================================
elif active_tab == "📥 Purchase History (Stock In)":
    st.markdown("<h2 style='color: #E65100;'>📥 Supplier Purchase Register</h2>", unsafe_allow_html=True)
    
    df_purchase = load_transaction_data("purchase")
    
    if not df_purchase.empty:
        st.markdown("##### 📅 Date Range Filter")
        d_col1, d_col2 = st.columns(2)
        with d_col1: start_d = st.date_input("Start Date", value=date.today() - timedelta(days=30), key="pur_start")
        with d_col2: end_d = st.date_input("End Date", value=date.today(), key="pur_end")
        
        df_purchase = filter_by_date_range(df_purchase, start_d, end_d)
        
        if is_manager:
            st.info("👑 **Manager Controls**: Review team cumulative purchases or filter by Sales Executive.")
            sr_options = ["All Sales Team (Cumulative)"] + sorted([s for s in df_purchase['sr_username'].dropna().unique()])
            sel_sr = st.selectbox("👤 Select Sales Executive / Team View:", sr_options)
            if sel_sr != "All Sales Team (Cumulative)":
                df_purchase = df_purchase[df_purchase['sr_username'] == sel_sr]
        else:
            df_purchase = df_purchase[df_purchase['sr_username'] == st.session_state['username']]

        parties_list = ["All Suppliers/Parties"] + sorted([p for p in df_purchase['party'].unique() if p])
        selected_party = st.selectbox("🏬 Select Supplier / Party to View Purchase Statement:", parties_list)
        
        filtered_df = df_purchase if selected_party == "All Suppliers/Parties" else df_purchase[df_purchase['party'] == selected_party]
            
        total_pur_amt = filtered_df['amount'].sum() if 'amount' in filtered_df.columns else 0.0
        total_invoices = filtered_df['invoice'].nunique() if 'invoice' in filtered_df.columns else 0
        
        c1, c2 = st.columns(2)
        with c1: st.metric("📄 Total Purchase Invoices", total_invoices)
        with c2: st.metric("💰 Total Purchase Amount", f"₹ {total_pur_amt:,.2f}")
            
        st.markdown("---")
        
        invoices_list = ["None (Summary View)"] + sorted(filtered_df['invoice'].unique().tolist(), reverse=True)
        selected_inv = st.selectbox("🔍 Select Particular Purchase Invoice / Bill to View Details:", invoices_list)
        
        if selected_inv != "None (Summary View)":
            inv_df = filtered_df[filtered_df['invoice'] == selected_inv]
            p_name = inv_df['party'].iloc[0] if not inv_df.empty else selected_party
            inv_date = inv_df['created_at'].iloc[0] if 'created_at' in inv_df.columns and not inv_df.empty else ""
            
            st.markdown(f"""
                <div style='background-color:#FFF3E0; padding:15px; border-radius:10px; border-left:5px solid #EF6C00; margin-bottom:15px;'>
                    <h3 style='color:#E65100; margin:0;'>🧾 Purchase Invoice No: {selected_inv}</h3>
                    <p style='margin:5px 0 0 0; color:#333;'><b>Supplier/Party:</b> {p_name} | <b>Date/Time:</b> {inv_date}</p>
                </div>
            """, unsafe_allow_html=True)
            
            display_cols = [c for c in ['product', 'pack', 'batch', 'expiry', 'qty', 'free_qty', 'mrp', 'rate', 'gst', 'amount', 'sr_username'] if c in inv_df.columns]
            st.dataframe(inv_df[display_cols], use_container_width=True)
            
            inv_subtotal = inv_df['amount'].sum() if 'amount' in inv_df.columns else 0.0
            st.markdown(f"#### **Grand Total for Purchase Bill ({selected_inv}): ₹ {inv_subtotal:,.2f}**")
        else:
            st.subheader(f"📋 Purchase Summary Statement ({selected_party})")
            display_cols = [c for c in ['invoice', 'created_at', 'party', 'product', 'pack', 'batch', 'expiry', 'qty', 'rate', 'amount', 'sr_username'] if c in filtered_df.columns]
            st.dataframe(filtered_df[display_cols], use_container_width=True)
    else:
        st.info("No Purchase records found in selected range.")

# ==========================================
# 4. LIVE STOCK & QUANTITY-VALUE SUMMARY
# ==========================================
elif active_tab == "🏭 Live Stock & Quantity-Value Summary":
    st.markdown("<h2 style='color: #E65100;'>🏭 Live Stock & Quantity-Value Summary</h2>", unsafe_allow_html=True)
    
    df_pur = load_transaction_data("purchase")
    df_sal = load_transaction_data("sales")
    
    st.markdown("##### 📅 Select Summary Date Range")
    d_col1, d_col2 = st.columns(2)
    with d_col1: start_d = st.date_input("Start Date", value=date.today() - timedelta(days=30), key="stk_start")
    with d_col2: end_d = st.date_input("End Date", value=date.today(), key="stk_end")
    
    df_pur = filter_by_date_range(df_pur, start_d, end_d)
    df_sal = filter_by_date_range(df_sal, start_d, end_d)
    
    if is_manager:
        st.info("📊 **Manager Review Dashboard**: Viewing merged stock and sales value across Sales Representatives.")
        view_mode = st.radio("Stock Summary View Mode:", ["Merged Cumulative Product Stock", "Batch-Wise Inventory", "SR-Wise Individual Stock Summary"], horizontal=True)
        
        # 1. MERGED CUMULATIVE PRODUCT STOCK
        if view_mode == "Merged Cumulative Product Stock":
            if not df_pur.empty or not df_sal.empty:
                pur_grp = df_pur.groupby('product').agg(
                    Purchase_Qty=('qty', 'sum'),
                    Purchase_Value=('amount', 'sum')
                ).reset_index() if not df_pur.empty else pd.DataFrame(columns=['product', 'Purchase_Qty', 'Purchase_Value'])
                
                sal_grp = df_sal.groupby('product').agg(
                    Sales_Qty=('qty', 'sum'),
                    Sales_Value=('amount', 'sum')
                ).reset_index() if not df_sal.empty else pd.DataFrame(columns=['product', 'Sales_Qty', 'Sales_Value'])
                
                merged = pd.merge(pur_grp, sal_grp, on='product', how='outer').fillna(0)
                merged['Net Stock Qty'] = merged['Purchase_Qty'] - merged['Sales_Qty']
                
                merged['Avg Purchase Rate'] = merged.apply(lambda r: (r['Purchase_Value'] / r['Purchase_Qty']) if r['Purchase_Qty'] > 0 else 0, axis=1)
                merged['Net Stock Value (₹)'] = merged['Net Stock Qty'] * merged['Avg Purchase Rate']
                
                tot_p_qty = merged['Purchase_Qty'].sum()
                tot_p_val = merged['Purchase_Value'].sum()
                tot_s_qty = merged['Sales_Qty'].sum()
                tot_s_val = merged['Sales_Value'].sum()
                tot_n_qty = merged['Net Stock Qty'].sum()
                tot_n_val = merged['Net Stock Value (₹)'].sum()
                
                display_df = merged[['product', 'Purchase_Qty', 'Purchase_Value', 'Sales_Qty', 'Sales_Value', 'Net Stock Qty', 'Net Stock Value (₹)']].copy()
                display_df.columns = ['Product', 'Total Purchase Qty', 'Total Purchase Value (₹)', 'Total Sales Qty', 'Total Sales Value (₹)', 'Net Stock Qty', 'Net Stock Value (₹)']
                
                display_df['Total Purchase Value (₹)'] = display_df['Total Purchase Value (₹)'].map('₹ {:,.2f}'.format)
                display_df['Total Sales Value (₹)'] = display_df['Total Sales Value (₹)'].map('₹ {:,.2f}'.format)
                display_df['Net Stock Value (₹)'] = display_df['Net Stock Value (₹)'].map('₹ {:,.2f}'.format)
                
                st.dataframe(display_df, use_container_width=True)
                
                st.markdown("---")
                st.markdown("### 📊 Grand Total Summary")
                t1, t2, t3 = st.columns(3)
                t1.metric("📦 Total Purchase (Qty & Value)", f"{tot_p_qty:,.0f} Qty", f"₹ {tot_p_val:,.2f}")
                t2.metric("🛍️ Total Sales (Qty & Value)", f"{tot_s_qty:,.0f} Qty", f"₹ {tot_s_val:,.2f}")
                t3.metric("🏷️ Net Stock (Qty & Value)", f"{tot_n_qty:,.0f} Qty", f"₹ {tot_n_val:,.2f}")
            else:
                st.info("No stock data available in selected date range.")
        
        # 2. BATCH-WISE INVENTORY
        elif view_mode == "Batch-Wise Inventory":
            if not df_pur.empty:
                cols_to_show = [c for c in ['product', 'pack', 'batch', 'expiry', 'qty', 'rate', 'amount', 'created_at', 'sr_username'] if c in df_pur.columns]
                st.dataframe(df_pur[cols_to_show], use_container_width=True)
            else: 
                st.info("No batch stock data available in selected date range.")
            
        # 3. SR-WISE INDIVIDUAL STOCK SUMMARY
        else:
            all_srs = set()
            if not df_pur.empty and 'sr_username' in df_pur.columns:
                all_srs.update(df_pur['sr_username'].dropna().unique())
            if not df_sal.empty and 'sr_username' in df_sal.columns:
                all_srs.update(df_sal['sr_username'].dropna().unique())
                
            sr_list = sorted(list(all_srs))
            
            if sr_list:
                selected_sr = st.selectbox("👤 Select Sales Representative:", sr_list)
                
                sr_pur = df_pur[df_pur['sr_username'] == selected_sr] if not df_pur.empty and 'sr_username' in df_pur.columns else pd.DataFrame()
                sr_sal = df_sal[df_sal['sr_username'] == selected_sr] if not df_sal.empty and 'sr_username' in df_sal.columns else pd.DataFrame()
                
                if not sr_pur.empty or not sr_sal.empty:
                    p_grp = sr_pur.groupby('product').agg(
                        Purchase_Qty=('qty', 'sum'),
                        Purchase_Value=('amount', 'sum')
                    ).reset_index() if not sr_pur.empty else pd.DataFrame(columns=['product', 'Purchase_Qty', 'Purchase_Value'])
                    
                    s_grp = sr_sal.groupby('product').agg(
                        Sales_Qty=('qty', 'sum'),
                        Sales_Value=('amount', 'sum')
                    ).reset_index() if not sr_sal.empty else pd.DataFrame(columns=['product', 'Sales_Qty', 'Sales_Value'])
                    
                    sr_merged = pd.merge(p_grp, s_grp, on='product', how='outer').fillna(0)
                    sr_merged['Net Stock Qty'] = sr_merged['Purchase_Qty'] - sr_merged['Sales_Qty']
                    
                    sr_merged['Avg Rate'] = sr_merged.apply(lambda r: (r['Purchase_Value'] / r['Purchase_Qty']) if r['Purchase_Qty'] > 0 else 0, axis=1)
                    sr_merged['Net Stock Value (₹)'] = sr_merged['Net Stock Qty'] * sr_merged['Avg Rate']
                    
                    sr_tp_qty = sr_merged['Purchase_Qty'].sum()
                    sr_tp_val = sr_merged['Purchase_Value'].sum()
                    sr_ts_qty = sr_merged['Sales_Qty'].sum()
                    sr_ts_val = sr_merged['Sales_Value'].sum()
                    sr_tn_qty = sr_merged['Net Stock Qty'].sum()
                    sr_tn_val = sr_merged['Net Stock Value (₹)'].sum()
                    
                    sr_display = sr_merged[['product', 'Purchase_Qty', 'Purchase_Value', 'Sales_Qty', 'Sales_Value', 'Net Stock Qty', 'Net Stock Value (₹)']].copy()
                    sr_display.columns = ['Product', 'Purchased Qty', 'Purchase Value (₹)', 'Sold Qty', 'Sales Value (₹)', 'Net Stock Qty', 'Net Stock Value (₹)']
                    
                    sr_display['Purchase Value (₹)'] = sr_display['Purchase Value (₹)'].map('₹ {:,.2f}'.format)
                    sr_display['Sales Value (₹)'] = sr_display['Sales Value (₹)'].map('₹ {:,.2f}'.format)
                    sr_display['Net Stock Value (₹)'] = sr_display['Net Stock Value (₹)'].map('₹ {:,.2f}'.format)
                    
                    st.subheader(f"📋 Product Summary for {selected_sr}")
                    st.dataframe(sr_display, use_container_width=True)
                    
                    st.markdown("---")
                    st.markdown(f"### 📊 Total Summary for {selected_sr}")
                    t1, t2, t3 = st.columns(3)
                    t1.metric("📦 Purchase (Qty & Value)", f"{sr_tp_qty:,.0f} Qty", f"₹ {sr_tp_val:,.2f}")
                    t2.metric("🛍️ Sales (Qty & Value)", f"{sr_ts_qty:,.0f} Qty", f"₹ {sr_ts_val:,.2f}")
                    t3.metric("🏷️ Net Stock (Qty & Value)", f"{sr_tn_qty:,.0f} Qty", f"₹ {sr_tn_val:,.2f}")
                else:
                    st.info(f"No records found for Sales Executive '{selected_sr}' in selected range.")
            else:
                st.info("No Sales Representative data available.")
            
    else:
        # SALES EXECUTIVE SELF VIEW
        sr_user = st.session_state['username']
        sr_pur = df_pur[df_pur['sr_username'] == sr_user] if not df_pur.empty and 'sr_username' in df_pur.columns else pd.DataFrame()
        sr_sal = df_sal[df_sal['sr_username'] == sr_user] if not df_sal.empty and 'sr_username' in df_sal.columns else pd.DataFrame()
        
        if not sr_pur.empty or not sr_sal.empty:
            p_grp = sr_pur.groupby('product').agg(
                Purchase_Qty=('qty', 'sum'),
                Purchase_Value=('amount', 'sum')
            ).reset_index() if not sr_pur.empty else pd.DataFrame(columns=['product', 'Purchase_Qty', 'Purchase_Value'])
            
            s_grp = sr_sal.groupby('product').agg(
                Sales_Qty=('qty', 'sum'),
                Sales_Value=('amount', 'sum')
            ).reset_index() if not sr_sal.empty else pd.DataFrame(columns=['product', 'Sales_Qty', 'Sales_Value'])
            
            sr_merged = pd.merge(p_grp, s_grp, on='product', how='outer').fillna(0)
            sr_merged['Net Stock Qty'] = sr_merged['Purchase_Qty'] - sr_merged['Sales_Qty']
            sr_merged['Avg Rate'] = sr_merged.apply(lambda r: (r['Purchase_Value'] / r['Purchase_Qty']) if r['Purchase_Qty'] > 0 else 0, axis=1)
            sr_merged['Net Stock Value (₹)'] = sr_merged['Net Stock Qty'] * sr_merged['Avg Rate']
            
            sr_tp_qty = sr_merged['Purchase_Qty'].sum()
            sr_tp_val = sr_merged['Purchase_Value'].sum()
            sr_ts_qty = sr_merged['Sales_Qty'].sum()
            sr_ts_val = sr_merged['Sales_Value'].sum()
            sr_tn_qty = sr_merged['Net Stock Qty'].sum()
            sr_tn_val = sr_merged['Net Stock Value (₹)'].sum()
            
            sr_display = sr_merged[['product', 'Purchase_Qty', 'Purchase_Value', 'Sales_Qty', 'Sales_Value', 'Net Stock Qty', 'Net Stock Value (₹)']].copy()
            sr_display.columns = ['Product', 'Purchased Qty', 'Purchase Value (₹)', 'Sold Qty', 'Sales Value (₹)', 'Net Stock Qty', 'Net Stock Value (₹)']
            
            st.dataframe(sr_display, use_container_width=True)
            
            st.markdown("---")
            st.markdown("### 📊 Your Total Summary")
            t1, t2, t3 = st.columns(3)
            t1.metric("📦 Purchase (Qty & Value)", f"{sr_tp_qty:,.0f} Qty", f"₹ {sr_tp_val:,.2f}")
            t2.metric("🛍️ Sales (Qty & Value)", f"{sr_ts_qty:,.0f} Qty", f"₹ {sr_ts_val:,.2f}")
            t3.metric("🏷️ Net Stock (Qty & Value)", f"{sr_tn_qty:,.0f} Qty", f"₹ {sr_tn_val:,.2f}")
        else:
            st.info("No Stock data available for your ID in selected range.")

# ==========================================
# 5. USER MANAGEMENT (ADMIN)
# ==========================================
elif active_tab == "👥 User Management (Admin)":
    st.markdown("<h2 style='color: #E65100;'>👥 Sales Team & User Management</h2>", unsafe_allow_html=True)
    u_col1, u_col2 = st.columns([1, 1])
    with u_col1:
        st.markdown("### ➕ Add New Team Member")
        new_username = st.text_input("User ID").strip().lower()
        new_password = st.text_input("Password", type="password")
        new_name = st.text_input("Full Name")
        new_role = st.selectbox("Role", ["Sales Executive", "Area Business Manager", "Manager"])
        if st.button("👤 Create User Account"):
            if new_username and new_password and new_name:
                save_new_user(new_username, new_password, new_name, new_role)
                st.success(f"✅ User '{new_name}' created!")
                st.rerun()
    with u_col2:
        st.markdown("### 📋 Active User Accounts")
        current_users = load_all_users()
        users_df = pd.DataFrame([{"Username": k, "Name": v["name"], "Role": v["role"]} for k, v in current_users.items()])
        st.dataframe(users_df, use_container_width=True)
        st.markdown("---")
        del_username = st.selectbox("Select User to Remove", [u for u in current_users.keys() if u != "manager"])
        if st.button("❌ Delete Selected User"):
            delete_user_db(del_username)
            st.success(f"User '{del_username}' removed.")
            st.rerun()

# ==========================================
# 6. MANAGE MASTER PRODUCTS
# ==========================================
elif active_tab == "🏷️ Manage Master Products":
    st.markdown("<h2 style='color: #E65100;'>🏷️ Manage Master Products List</h2>", unsafe_allow_html=True)
    
    m_col1, m_col2 = st.columns([1, 1])
    
    with m_col1:
        st.markdown("### ➕ Add Single Product")
        p_name = st.text_input("Product Name")
        p_pack = st.text_input("Pack Size", value="00")
        p_tax = st.number_input("Tax / GST (%)", value=5.0, step=1.0)
        p_mrp = st.number_input("MRP (₹)", value=0.0)
        
        calc_auto_rate = round((p_mrp * 80.0) / (100.0 + p_tax), 2)
        p_rate = st.number_input("Rate (₹)", value=calc_auto_rate)
        
        if st.button("➕ Add Product to Master"):
            if p_name:
                add_master_product(p_name, p_pack, p_mrp, p_rate, p_tax)
                st.success(f"✅ Product '{p_name}' added!")
                st.rerun()

    with m_col2:
        st.markdown("### 📋 Editable Master Products Database")
        st.info("💡 **Tips:** Edit any cell and click 'Save Database Changes' to update.")
        
        m_df = load_master_products()
        display_df = m_df[["product_name", "pack", "mrp", "rate", "tax"]] if not m_df.empty else pd.DataFrame(columns=["product_name", "pack", "mrp", "rate", "tax"])
        
        edited_master_df = st.data_editor(
            display_df,
            key="master_db_editor",
            num_rows="dynamic",
            use_container_width=True
        )
        
        if st.button("💾 Save Database Changes"):
            sync_entire_master_products(edited_master_df)
            st.success("✅ Master Database successfully updated!")
            st.rerun()
            
        st.markdown("---")
        st.markdown("##### 🗑️ Remove Product via Selectbox")
        p_del_list = m_df["product_name"].tolist() if not m_df.empty else ["None"]
        del_p = st.selectbox("Select Product to Delete", p_del_list)
        if st.button("❌ Delete Product"):
            if del_p != "None":
                delete_master_product(del_p)
                st.success(f"Product '{del_p}' permanently deleted from database.")
                st.rerun()
