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
# PAGE CONFIG & STYLING
# ==========================================
st.set_page_config(page_title="SGB / LCB Pharma Wholesale ERP", layout="wide", initial_sidebar_state="expanded")

st.markdown(
    """
    
    """,
    unsafe_allow_html=True
)

# ==========================================
# DATABASE SETUP
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
    
    c.execute("INSERT OR IGNORE INTO users VALUES ('manager', 'admin123', 'Manager', 'Manager')")
    c.execute("INSERT OR IGNORE INTO users VALUES ('satya', 'satya123', 'Satya Sahu', 'Sales Executive')")
    conn.commit()
    conn.close()

init_local_db()

@st.cache_resource
def get_supabase_client():
    if "SUPABASE_URL" in st.secrets and "SUPABASE_KEY" in st.secrets:
        try:
            return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
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

def sync_entire_master_products(edited_df):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM master_products")
    records = []
    for _, r in edited_df.iterrows():
        p_name = str(r.get("product_name", "")).strip()
        if p_name and p_name.lower() != "nan":
            pack = str(r.get("pack", "00"))
            mrp = float(r.get("mrp", 0.0))
            tax = float(r.get("tax", 5.0))
            rate = float(r.get("rate", 0.0))
            c.execute("INSERT INTO master_products (product_name, pack, mrp, rate, tax) VALUES (?, ?, ?, ?, ?)", (p_name, pack, mrp, rate, tax))
            records.append({"product_name": p_name, "pack": pack, "mrp": mrp, "rate": rate, "tax": tax})
    conn.commit()
    conn.close()
    if supabase:
        try:
            supabase.table("master_products").delete().neq("id", -1).execute()
            if records: supabase.table("master_products").insert(records).execute()
        except Exception: pass

def save_transaction_data(table_name, items, invoice, party, sr_username):
    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    records = []
    for row in items:
        records.append({
            "invoice": invoice, "party": party, "product": row.get('PRODUCT', ''),
            "pack": row.get('PACK', '00'), "batch": str(row.get('BATCH', '00')),
            "expiry": str(row.get('EXPIRY', '00')), "qty": float(row.get('QTY', 0)),
            "free_qty": str(row.get('DEAL/FREE', '00')), "mrp": float(row.get('MRP', 0)),
            "disc_pct": float(row.get('DISC (%)', 0)), "disc_rs": float(row.get('DISC (₹)', 0)),
            "rate": float(row.get('RATE', 0)), "gst": float(row.get('GST', 5.0)),
            "amount": float(row.get('AMOUNT', 0)), "created_at": today, "sr_username": sr_username
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

def get_existing_parties():
    sales_df = load_transaction_data("sales")
    pur_df = load_transaction_data("purchase")
    p1 = sales_df['party'].dropna().unique().tolist() if not sales_df.empty else []
    p2 = pur_df['party'].dropna().unique().tolist() if not pur_df.empty else []
    return sorted(list(set(p1 + p2)))

if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

def process_bill_with_gemini(uploaded_file, text_input, master_df):
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        master_list = master_df["product_name"].tolist() if not master_df.empty else []
        prompt = f"""
        Extract Party Name and ALL medicine items with Batch, Expiry, Qty, MRP, Rate, GST.
        Master Products: {", ".join(master_list)}
        Output ONLY a raw valid JSON object without markdown:
        {{"PARTY": "Name", "ITEMS": [{{"PRODUCT": "Item", "PACK": "00", "BATCH": "00", "EXPIRY": "00", "QTY": 0, "DEAL": "00", "MRP": 0.0, "DISC_PCT": 0.0, "DISC_RS": 0.0, "RATE": 0.0, "GST": 5.0}}]}}
        """
        if uploaded_file:
            response = model.generate_content([prompt, Image.open(uploaded_file)])
        else:
            response = model.generate_content([prompt, text_input])
            
        clean_txt = response.text.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(re.search(r'\{.*\}', clean_txt, re.DOTALL).group(0))
        return str(parsed.get("PARTY", "00")), parsed.get("ITEMS", [])
    except Exception as e:
        st.error(f"AI Error: {e}")
        return "00", []

def generate_pdf_invoice(party, inv, gst_no, cart_data, sub_total, gst_val, net_val):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", 'B', 16)
    pdf.cell(190, 10, "SGB / LCB PHARMA WHOLESALE INVOICE", new_x="LMARGIN", new_y="NEXT", align='C')
    pdf.set_font("Helvetica", '', 10)
    pdf.cell(190, 6, f"Party: {party} | GSTIN: {gst_no}", new_x="LMARGIN", new_y="NEXT", align='C')
    pdf.cell(190, 6, f"Invoice No: {inv} | Date: {datetime.now().strftime('%d-%m-%Y')}", new_x="LMARGIN", new_y="NEXT", align='C')
    pdf.ln(5)
    
    pdf.set_font("Helvetica", 'B', 8)
    pdf.cell(40, 7, "Product", 1)
    pdf.cell(15, 7, "Pack", 1)
    pdf.cell(20, 7, "Batch", 1)
    pdf.cell(15, 7, "Exp", 1)
    pdf.cell(15, 7, "Qty", 1)
    pdf.cell(20, 7, "MRP", 1)
    pdf.cell(20, 7, "Rate", 1)
    pdf.cell(15, 7, "GST%", 1)
    pdf.cell(30, 7, "Amount", 1)
    pdf.ln()
    
    pdf.set_font("Helvetica", '', 8)
    for row in cart_data:
        pdf.cell(40, 6, str(row['PRODUCT'])[:20], 1)
        pdf.cell(15, 6, str(row.get('PACK', '00')), 1)
        pdf.cell(20, 6, str(row.get('BATCH', '00')), 1)
        pdf.cell(15, 6, str(row.get('EXPIRY', '00')), 1)
        pdf.cell(15, 6, str(row['QTY']), 1)
        pdf.cell(20, 6, f"{float(row['MRP']):.2f}", 1)
        pdf.cell(20, 6, f"{float(row['RATE']):.2f}", 1)
        pdf.cell(15, 6, f"{float(row.get('GST', 5))}%", 1)
        pdf.cell(30, 6, f"{float(row['AMOUNT']):.2f}", 1)
        pdf.ln()
        
    pdf.ln(4)
    pdf.set_font("Helvetica", 'B', 10)
    pdf.cell(190, 6, f"Sub Total: Rs. {sub_total:,.2f}", new_x="LMARGIN", new_y="NEXT", align='R')
    pdf.cell(190, 6, f"GST Tax: Rs. {gst_val:,.2f}", new_x="LMARGIN", new_y="NEXT", align='R')
    pdf.cell(190, 6, f"Grand Total: Rs. {net_val:,.2f}", new_x="LMARGIN", new_y="NEXT", align='R')
    return bytes(pdf.output())
# ==========================================
# MAIN APP FLOW
# ==========================================
if "logged_in" not in st.session_state: st.session_state["logged_in"] = False
if "scanned_cart" not in st.session_state: st.session_state["scanned_cart"] = []
if "extracted_party_name" not in st.session_state: st.session_state["extracted_party_name"] = "00"

USERS_DB = load_all_users()
MASTER_DF = load_master_products()

if not st.session_state["logged_in"]:
    st.markdown("
# ==========================================
# MAIN APP FLOW
# ==========================================
if "logged_in" not in st.session_state: st.session_state["logged_in"] = False
if "scanned_cart" not in st.session_state: st.session_state["scanned_cart"] = []
if "extracted_party_name" not in st.session_state: st.session_state["extracted_party_name"] = "00"

USERS_DB = load_all_users()
MASTER_DF = load_master_products()

if not st.session_state["logged_in"]:
    st.markdown("<h2 style='text-align: center; color: #E65100;'>SGB / LCB Pharma Wholesale ERP</h2>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        u_in = st.text_input("Username").strip().lower()
        p_in = st.text_input("Password", type="password")
        if st.button("Secure Login"):
            if u_in in USERS_DB and USERS_DB[u_in]["password"] == p_in:
                st.session_state["logged_in"] = True
                st.session_state["logged_user"] = USERS_DB[u_in]
                st.session_state["username"] = u_in
                st.rerun()
            else: st.error("Invalid Username or Password")
    st.stop()

logged_user = st.session_state["logged_user"]
is_manager = logged_user["role"] == "Manager"

st.sidebar.title(logged_user['name'])
st.sidebar.caption(f"Role: {logged_user['role']}")

nav_options = [
    "AI Smart Scan & Billing",
    "Sales History",
    "Purchase History (Stock In)",
    "Live Stock Summary"
]
if is_manager:
    nav_options.append("User Management")
    nav_options.append("Manage Master Products")

active_tab = st.sidebar.radio("Navigation", nav_options)

if st.sidebar.button("Logout"):
    st.session_state["logged_in"] = False
    st.session_state["scanned_cart"] = []
    st.rerun()

# 1. AI SCANNER & BILLING
if active_tab == "AI Smart Scan & Billing":
    st.markdown("<h2 style='color: #E65100;'>AI Scanner & Wholesale Billing</h2>", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1: up_img = st.file_uploader("Upload Invoice / Order Slip", type=["jpg", "png", "jpeg"])
    with c2: raw_txt = st.text_area("Or Paste Text Data")
        
    if st.button("Auto-Extract via Gemini AI"):
        if up_img or raw_txt:
            with st.spinner("Processing..."):
                party, items = process_bill_with_gemini(up_img, raw_txt, MASTER_DF)
                st.session_state["extracted_party_name"] = party
                st.session_state["scanned_cart"] = items
                st.rerun()
        else: st.warning("Please upload an image or enter text.")

    if st.session_state["scanned_cart"]:
        st.markdown("---")
        st.subheader("Current Billing Cart")
        
        c_p1, c_p2, c_p3 = st.columns([2, 2, 1])
        with c_p1: party_name = st.selectbox("Party Name", options=list(set([st.session_state["extracted_party_name"]] + get_existing_parties() + ["Cash Sales"])))
        with c_p2: invoice_no = st.text_input("Invoice Number", value=f"INV-{datetime.now().strftime('%Y%m%d%H%M')}")
        with c_p3: gstin_no = st.text_input("GSTIN", value="27AAAAA0000A1Z5")

        cart_df = pd.DataFrame(st.session_state["scanned_cart"])
        edited_cart = st.data_editor(cart_df, num_rows="dynamic", use_container_width=True)
        
        sub_total, gst_val = 0.0, 0.0
        updated_items = []
        for _, row in edited_cart.iterrows():
            qty = float(row.get("QTY", 0))
            rate = float(row.get("RATE", 0))
            gst_pct = float(row.get("GST", 5))
            amt = qty * rate
            sub_total += amt
            gst_val += amt * (gst_pct / 100.0)
            
            r_dict = row.to_dict()
            r_dict["AMOUNT"] = round(amt, 2)
            updated_items.append(r_dict)

        net_val = sub_total + gst_val
        st.markdown(f"### Sub Total: Rs.{sub_total:,.2f} | GST: Rs.{gst_val:,.2f} | Grand Total: Rs.{net_val:,.2f}")

        b1, b2, b3 = st.columns(3)
        with b1:
            if st.button("Save as Sale"):
                save_transaction_data("sales", updated_items, invoice_no, party_name, st.session_state["username"])
                st.success("Sale saved!")
        with b2:
            if st.button("Save as Purchase"):
                save_transaction_data("purchase", updated_items, invoice_no, party_name, st.session_state["username"])
                for itm in updated_items: add_master_product(itm["PRODUCT"], itm["PACK"], itm["MRP"], itm["RATE"], itm["GST"])
                st.success("Purchase saved!")
        with b3:
            if st.button("Download PDF"):
                pdf_bytes = generate_pdf_invoice(party_name, invoice_no, gstin_no, updated_items, sub_total, gst_val, net_val)
                st.download_button("Click to Download PDF", data=pdf_bytes, file_name=f"{invoice_no}.pdf", mime="application/pdf")

# 2. SALES HISTORY
elif active_tab == "Sales History":
    st.markdown("<h2 style='color: #E65100;'>Sales History</h2>", unsafe_allow_html=True)
    df = load_transaction_data("sales")
    if not df.empty:
        st.dataframe(df, use_container_width=True)
    else:
        st.info("No records found.")

# 3. PURCHASE HISTORY
elif active_tab == "Purchase History (Stock In)":
    st.markdown("<h2 style='color: #E65100;'>Purchase History</h2>", unsafe_allow_html=True)
    df = load_transaction_data("purchase")
    if not df.empty:
        st.dataframe(df, use_container_width=True)
    else:
        st.info("No records found.")

# 4. LIVE STOCK SUMMARY
elif active_tab == "Live Stock Summary":
    st.markdown("<h2 style='color: #E65100;'>Live Stock Summary</h2>", unsafe_allow_html=True)
    df = load_master_products()
    if not df.empty:
        st.dataframe(df, use_container_width=True)
    else:
        st.info("Master list is empty.")

# 5. USER MANAGEMENT
elif active_tab == "User Management" and is_manager:
    st.markdown("<h2 style='color: #E65100;'>User Management</h2>", unsafe_allow_html=True)
    users_data = load_all_users()
    if users_data:
        st.dataframe(pd.DataFrame([{"username": k, **v} for k, v in users_data.items()]), use_container_width=True)
    else:
        st.info("No users found.")

# 6. MANAGE MASTER PRODUCTS
elif active_tab == "Manage Master Products" and is_manager:
    st.markdown("<h2 style='color: #E65100;'>Manage Master Products</h2>", unsafe_allow_html=True)
    edited_master = st.data_editor(load_master_products(), num_rows="dynamic", use_container_width=True)
    if st.button("Save Master Changes"):
        sync_entire_master_products(edited_master)
        st.success("Master products updated successfully!")
