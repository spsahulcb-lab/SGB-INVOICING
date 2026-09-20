import streamlit as st
import pandas as pd
from datetime import datetime
from fpdf import FPDF
import urllib.parse
import json
import sqlite3
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
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, invoice TEXT, party TEXT, product TEXT, pack TEXT, qty REAL, free_qty TEXT, mrp REAL, discount REAL, rate REAL, gst REAL, amount REAL, created_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS purchase 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, invoice TEXT, party TEXT, product TEXT, pack TEXT, qty REAL, free_qty TEXT, mrp REAL, discount REAL, rate REAL, gst REAL, amount REAL, created_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (username TEXT PRIMARY KEY, password TEXT, name TEXT, role TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS master_products 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, product_name TEXT UNIQUE, pack TEXT, mrp REAL, rate REAL, tax REAL)''')
    
    # Default Users
    c.execute("INSERT OR IGNORE INTO users VALUES ('manager', 'admin123', 'Manager', 'Manager')")
    c.execute("INSERT OR IGNORE INTO users VALUES ('satya', 'satya123', 'Satya Sahu', 'Sales Executive')")
    
    # Default Master Products
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
        c.execute("INSERT OR IGNORE INTO master_products (product_name, pack, mrp, rate, tax) VALUES (?, ?, ?, ?, ?)", p)
        
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
        except Exception:
            return None
    return None

supabase = get_supabase_client()

# Dynamic Master Products Loader
def load_master_products():
    if supabase:
        try:
            res = supabase.table("master_products").select("*").execute()
            if res.data:
                return pd.DataFrame(res.data)
        except Exception:
            pass
            
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM master_products ORDER BY product_name ASC", conn)
    conn.close()
    return df

def add_master_product(product_name, pack, mrp, rate, tax):
    p_clean = product_name.strip()
    if not p_clean: return
    if supabase:
        try:
            supabase.table("master_products").insert({"product_name": p_clean, "pack": pack, "mrp": mrp, "rate": rate, "tax": tax}).execute()
        except Exception: pass
            
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO master_products (product_name, pack, mrp, rate, tax) VALUES (?, ?, ?, ?, ?)", (p_clean, pack, mrp, rate, tax))
    conn.commit()
    conn.close()

def delete_master_product(product_name):
    if supabase:
        try:
            supabase.table("master_products").delete().eq("product_name", product_name).execute()
        except Exception: pass
            
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM master_products WHERE product_name=?", (product_name,))
    conn.commit()
    conn.close()

def bulk_upload_master_products(records):
    if supabase:
        try:
            supabase.table("master_products").insert(records).execute()
        except Exception: pass
            
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    for item in records:
        c.execute("INSERT OR REPLACE INTO master_products (product_name, pack, mrp, rate, tax) VALUES (?, ?, ?, ?, ?)", 
                  (item["product_name"], item.get("pack", ""), item.get("mrp", 0.0), item.get("rate", 0.0), item.get("tax", 12.0)))
    conn.commit()
    conn.close()

def auto_correct_brand(scanned_name, master_list):
    """If product is not in master list or match ratio is low, return scanned_name as-is"""
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
            "discount": float(row.get('DISCOUNT (%)', 0)),
            "rate": float(row.get('RATE', 0)),
            "gst": float(row.get('GST', 12)),
            "amount": float(row.get('AMOUNT', 0)),
            "created_at": today
        })
    
    saved_cloud = False
    if supabase:
        try:
            supabase.table(table_name).insert(records).execute()
            saved_cloud = True
        except Exception: pass
    
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    for r in records:
        c.execute(f'''INSERT INTO {table_name} (invoice, party, product, pack, qty, free_qty, mrp, discount, rate, gst, amount, created_at)
                      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                  (r["invoice"], r["party"], r["product"], r["pack"], r["qty"], r["free_qty"], r["mrp"], r["discount"], r["rate"], r["gst"], r["amount"], r["created_at"]))
    conn.commit()
    conn.close()
    return saved_cloud

def load_transaction_data(table_name):
    if supabase:
        try:
            res = supabase.table(table_name).select("*").order("id", desc=True).execute()
            if res.data:
                return pd.DataFrame(res.data)
        except Exception: pass
            
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query(f"SELECT * FROM {table_name} ORDER BY id DESC", conn)
    conn.close()
    return df

def load_all_users():
    if supabase:
        try:
            res = supabase.table("users").select("*").execute()
            if res.data:
                return {row["username"]: {"password": row["password"], "name": row["name"], "role": row["role"]} for row in res.data}
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
        Extract ALL medicine items accurately from image/text for pharma wholesale ERP.
        Read each line item as written in the bill. Do NOT duplicate or force names.
        Master Product List Reference: {", ".join(master_list)}
        Return ONLY a clean JSON array of objects without Markdown formatting:
        [
          {{"PRODUCT": "Item Name", "PACK": "10x10", "QTY": 10, "DEAL": "10+2", "MRP": 100.0, "RATE": 50.0, "GST": 12}}
        ]
        """
        if uploaded_file:
            img = Image.open(uploaded_file)
            response = model.generate_content([prompt, img])
        else:
            response = model.generate_content([prompt, text_input])
            
        clean_txt = response.text.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean_txt)
        
        cleaned_data = []
        for item in data:
            raw_prod = str(item.get("PRODUCT", "")).strip()
            corrected_prod = auto_correct_brand(raw_prod, master_list)
            
            # Match master details if exact match
            m_match = master_df[master_df["product_name"] == corrected_prod] if not master_df.empty else pd.DataFrame()
            
            pack = str(item.get("PACK", "")) or (m_match["pack"].values[0] if not m_match.empty else "")
            
            try: qty = float(item.get("QTY", 1) or 1)
            except: qty = 1.0
            
            deal = str(item.get("DEAL", "NA"))
            
            try: mrp = float(item.get("MRP", 0.0) or 0.0) or (float(m_match["mrp"].values[0]) if not m_match.empty else 0.0)
            except: mrp = 0.0

            try: rate = float(item.get("RATE", 0.0) or 0.0) or (float(m_match["rate"].values[0]) if not m_match.empty else 0.0)
            except: rate = 0.0
            
            try: gst = float(item.get("GST", 12) or 12)
            except: gst = 12.0
            
            if rate == 0.0 and mrp > 0:
                rate = round((mrp * 80.0) / 118.0, 2) if gst == 18.0 else round((mrp * 80.0) / 105.0, 2)
                
            amt = qty * rate
            
            cleaned_data.append({
                "PRODUCT": corrected_prod,
                "PACK": pack,
                "QTY": qty,
                "DEAL/FREE": deal,
                "MRP": mrp,
                "DISCOUNT (%)": 0.0,
                "RATE": rate,
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
def generate_pdf_invoice(party, inv, gst_no, cart_data, total_mrp, total_disc, sub_total, gst_val, net_val):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", 'B', 16)
    pdf.cell(190, 10, "SGB / LCB PHARMA WHOLESALE INVOICE", new_x="LMARGIN", new_y="NEXT", align='C')
    pdf.set_font("Helvetica", '', 10)
    pdf.cell(190, 6, f"Party: {party} | GSTIN: {gst_no}", new_x="LMARGIN", new_y="NEXT", align='C')
    pdf.cell(190, 6, f"Invoice No: {inv} | Date: {datetime.now().strftime('%d-%m-%Y')}", new_x="LMARGIN", new_y="NEXT", align='C')
    pdf.ln(5)
    
    pdf.set_font("Helvetica", 'B', 8)
    pdf.cell(50, 7, "Product", 1)
    pdf.cell(20, 7, "Pack", 1)
    pdf.cell(15, 7, "Qty", 1)
    pdf.cell(20, 7, "Deal", 1)
    pdf.cell(20, 7, "MRP (Rs)", 1)
    pdf.cell(20, 7, "Rate (Rs)", 1)
    pdf.cell(45, 7, "Amount (Rs)", 1)
    pdf.ln()
    
    pdf.set_font("Helvetica", '', 8)
    for row in cart_data:
        pdf.cell(50, 6, str(row['PRODUCT'])[:24], 1)
        pdf.cell(20, 6, str(row.get('PACK', ''))[:10], 1)
        pdf.cell(15, 6, str(row['QTY']), 1)
        pdf.cell(20, 6, str(row.get('DEAL/FREE', '')), 1)
        pdf.cell(20, 6, f"{float(row['MRP']):.2f}", 1)
        pdf.cell(20, 6, f"{float(row['RATE']):.2f}", 1)
        pdf.cell(45, 6, f"{float(row['AMOUNT']):.2f}", 1)
        pdf.ln()
        
    pdf.ln(4)
    pdf.set_font("Helvetica", 'B', 10)
    pdf.cell(190, 6, f"Sub Total: Rs. {sub_total:,.2f}", new_x="LMARGIN", new_y="NEXT", align='R')
    pdf.cell(190, 6, f"GST Tax: Rs. {gst_val:,.2f}", new_x="LMARGIN", new_y="NEXT", align='R')
    pdf.cell(190, 6, f"Grand Total: Rs. {net_val:,.2f}", new_x="LMARGIN", new_y="NEXT", align='R')
    
    return bytes(pdf.output())

if "logged_in" not in st.session_state: st.session_state["logged_in"] = False
if "scanned_cart" not in st.session_state: st.session_state["scanned_cart"] = []

USERS_DB = load_all_users()
MASTER_DF = load_master_products()
MASTER_LIST = MASTER_DF["product_name"].tolist() if not MASTER_DF.empty else []

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
            else:
                st.error("❌ Invalid Username or Password")
    st.stop()

logged_user = st.session_state["logged_user"]
st.sidebar.title(f"🍊 {logged_user['name']}")
st.sidebar.caption(f"Role: {logged_user['role']}")

nav_options = [
    "🤖 AI Smart Scan & Billing",
    "📦 Sales History",
    "📥 Purchase History (Stock In)",
    "🏭 Batch Stock & Expiry Alert"
]

if logged_user["role"] == "Manager":
    nav_options.append("👥 User Management (Admin)")
    nav_options.append("🏷️ Manage Master Products")

active_tab = st.sidebar.radio("Navigation", nav_options)

if st.sidebar.button("🚪 Logout"):
    st.session_state["logged_in"] = False
    st.session_state["scanned_cart"] = []
    st.rerun()

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
                    st.success("✅ Fast Scan Completed!")
                    st.rerun()
        else:
            st.warning("Please upload a slip image or paste text.")

    st.markdown("---")
    
    st.subheader("📝 Wholesale Bill Meta Info")
    f1, f2, f3 = st.columns(3)
    with f1: party_name = st.text_input("Party / Supplier / Medical Store Name", value="Sharma Medical Hall")
    with f2: inv_no = st.text_input("Invoice No", value=f"INV-{int(datetime.now().timestamp())}")
    with f3: gst_no = st.text_input("Party GSTIN", value="09AAAAA0000A1Z5")

    st.markdown("##### ➕ Manual Item Addition")
    p1, p2, p3, p4, p5, p6, p7 = st.columns([2, 1, 1, 1, 1, 1, 1])
    with p1: sel_prod = st.selectbox("Product", MASTER_LIST if MASTER_LIST else ["Select Product"])
    with p2: m_pack = st.text_input("Pack", value="10x10")
    with p3: s_qty = st.number_input("Qty", min_value=1, value=10)
    with p4: s_deal = st.text_input("Deal/Free", value="NA")
    with p5: s_mrp = st.number_input("MRP (₹)", min_value=0.0, value=150.0)
    with p6: s_disc = st.number_input("Disc (%)", min_value=0.0, max_value=100.0, value=20.0)
    with p7:
        calc_rate = round(s_mrp * (1 - (s_disc / 100.0)), 2)
        st.write(f"**Rate:** ₹{calc_rate}")
        if st.button("➕ Add"):
            amt = float(s_qty) * calc_rate
            st.session_state["scanned_cart"].append({
                "PRODUCT": sel_prod, "PACK": m_pack, "QTY": float(s_qty), "DEAL/FREE": s_deal,
                "MRP": float(s_mrp), "DISCOUNT (%)": float(s_disc), "RATE": calc_rate, "GST": 12.0, "AMOUNT": round(amt, 2)
            })
            st.rerun()

    if st.session_state["scanned_cart"]:
        st.markdown("---")
        st.subheader("🛒 Current Bill Items")
        
        cart_df = pd.DataFrame(st.session_state["scanned_cart"])
        
        edited_df = st.data_editor(
            cart_df, 
            key="cart_editor", 
            num_rows="dynamic",
            disabled=["AMOUNT"], 
            use_container_width=True
        )
        
        st.session_state["scanned_cart"] = edited_df.to_dict('records')
        
        if not edited_df.empty:
            sub_total = float(edited_df["AMOUNT"].sum())
            total_mrp_sum = float((edited_df["MRP"] * edited_df["QTY"]).sum())
            total_disc_val = total_mrp_sum - sub_total if total_mrp_sum > 0 else 0.0
            gst_val = sub_total * 0.12
            net_val = sub_total + gst_val
        else:
            sub_total = total_mrp_sum = total_disc_val = gst_val = net_val = 0.0
        
        st.markdown(f"""
            <div style='background-color:#FFF3E0; padding:15px; border-radius:10px; border-left:5px solid #EF6C00;'>
                <h4 style='color:#E65100; margin:0;'>🏷️ Total MRP: ₹ {total_mrp_sum:,.2f} | 🎁 Discount Shell: ₹ {total_disc_val:,.2f}</h4>
                <h3 style='color:#D84315; margin-top:5px;'>💰 Sub Total: ₹ {sub_total:,.2f} | GST Tax: ₹ {gst_val:,.2f} | Grand Total: ₹ {net_val:,.2f}</h3>
            </div>
        """, unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)
        
        save_col1, save_col2, save_col3, save_col4, save_col5 = st.columns(5)
        
        with save_col1:
            if st.button("📤 Save SALES"):
                save_transaction_data("sales", st.session_state["scanned_cart"], inv_no, party_name)
                st.success("✅ Saved to Sales Database!")
                st.session_state["scanned_cart"] = []
                st.rerun()

        with save_col2:
            if st.button("📥 Save PURCHASE"):
                save_transaction_data("purchase", st.session_state["scanned_cart"], inv_no, party_name)
                st.success("✅ Saved to Purchase Database!")
                st.session_state["scanned_cart"] = []
                st.rerun()

        with save_col3:
            try:
                pdf_bytes = generate_pdf_invoice(party_name, inv_no, gst_no, st.session_state["scanned_cart"], total_mrp_sum, total_disc_val, sub_total, gst_val, net_val)
                st.download_button(label="📄 Download PDF", data=pdf_bytes, file_name=f"{inv_no}.pdf", mime="application/pdf")
            except Exception as pdf_err: st.error(f"PDF Error: {pdf_err}")

        with save_col4:
            msg = f"🧾 *INVOICE*\n*Party:* {party_name}\n*Total:* ₹{net_val:,.2f}\n"
            for row in st.session_state["scanned_cart"]:
                msg += f"• {row['PRODUCT']} - {row['QTY']} Qty @ ₹{row['RATE']}\n"
            wa_url = f"https://api.whatsapp.com/send?text={urllib.parse.quote(msg)}"
            st.markdown(f'<a href="{wa_url}" target="_blank"><button style="background-color:#25D366; color:white; font-weight:bold; height:38px; border-radius:8px; border:none; width:100%;">📲 WhatsApp</button></a>', unsafe_allow_html=True)

        with save_col5:
            if st.button("🗑️ Clear Entire List"):
                st.session_state["scanned_cart"] = []
                st.rerun()

elif active_tab == "📦 Sales History":
    st.markdown("<h2 style='color: #E65100;'>📦 Wholesale Sales Register</h2>", unsafe_allow_html=True)
    df_sales = load_transaction_data("sales")
    st.dataframe(df_sales, use_container_width=True) if not df_sales.empty else st.info("No Sales records found.")

elif active_tab == "📥 Purchase History (Stock In)":
    st.markdown("<h2 style='color: #E65100;'>📥 Supplier Purchase Register</h2>", unsafe_allow_html=True)
    df_purchase = load_transaction_data("purchase")
    st.dataframe(df_purchase, use_container_width=True) if not df_purchase.empty else st.info("No Purchase records found.")

elif active_tab == "🏭 Batch Stock & Expiry Alert":
    st.markdown("<h2 style='color: #E65100;'>🏭 Live Stock Overview</h2>", unsafe_allow_html=True)
    df_pur = load_transaction_data("purchase")
    st.dataframe(df_pur[['product', 'pack', 'qty', 'free_qty', 'mrp', 'rate', 'created_at']], use_container_width=True) if not df_pur.empty else st.info("No Stock data available.")

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

elif active_tab == "🏷️ Manage Master Products":
    st.markdown("<h2 style='color: #E65100;'>🏷️ Manage Master Products List</h2>", unsafe_allow_html=True)
    
    m_col1, m_col2 = st.columns([1, 1])
    
    with m_col1:
        st.markdown("### ➕ Add Single Product")
        p_name = st.text_input("Product Name")
        p_pack = st.text_input("Pack Size", value="10x10")
        p_mrp = st.number_input("MRP (₹)", value=100.0)
        p_rate = st.number_input("Rate (₹)", value=50.0)
        p_tax = st.number_input("Tax / GST (%)", value=12.0)
        
        if st.button("➕ Add Product to Master"):
            if p_name:
                add_master_product(p_name, p_pack, p_mrp, p_rate, p_tax)
                st.success(f"✅ Product '{p_name}' added!")
                st.rerun()
                
        st.markdown("---")
        st.markdown("### 📂 Upload Product List (CSV / Excel)")
        file_up = st.file_uploader("Upload Price List File", type=["csv", "xlsx", "xls"])
        if file_up:
            try:
                if file_up.name.endswith('.csv'): df_up = pd.read_csv(file_up)
                else:
                    try: df_up = pd.read_excel(file_up)
                    except: df_up = pd.read_excel(file_up, engine='xlrd')
                
                if not any("product" in str(c).lower() for c in df_up.columns):
                    file_up.seek(0)
                    df_up = pd.read_csv(file_up, skiprows=2) if file_up.name.endswith('.csv') else pd.read_excel(file_up, skiprows=2)
                    
                st.write("Preview of detected columns:")
                st.dataframe(df_up.head(), use_container_width=True)
                
                cols = df_up.columns.tolist()
                c_prod = st.selectbox("Product Column", cols, index=[i for i, c in enumerate(cols) if "product" in str(c).lower()][0] if any("product" in str(c).lower() for c in cols) else 0)
                c_pack = st.selectbox("Pack Column", ["None"] + cols, index=[i+1 for i, c in enumerate(cols) if "pack" in str(c).lower()][0] if any("pack" in str(c).lower() for c in cols) else 0)
                c_mrp = st.selectbox("MRP Column", ["None"] + cols, index=[i+1 for i, c in enumerate(cols) if "mrp" in str(c).lower()][0] if any("mrp" in str(c).lower() for c in cols) else 0)
                c_rate = st.selectbox("Rate Column", ["None"] + cols, index=[i+1 for i, c in enumerate(cols) if "rate" in str(c).lower()][0] if any("rate" in str(c).lower() for c in cols) else 0)
                c_tax = st.selectbox("Tax Column", ["None"] + cols, index=[i+1 for i, c in enumerate(cols) if "tax" in str(c).lower() or "gst" in str(c).lower()][0] if any("tax" in str(c).lower() or "gst" in str(c).lower() for c in cols) else 0)
                
                if st.button("🚀 Import Master List"):
                    records = []
                    for _, r in df_up.iterrows():
                        p_val = str(r[c_prod]).strip()
                        if p_val and p_val.lower() != 'nan':
                            records.append({
                                "product_name": p_val,
                                "pack": str(r[c_pack]) if c_pack != "None" else "",
                                "mrp": float(r[c_mrp]) if c_mrp != "None" and pd.notnull(r[c_mrp]) else 0.0,
                                "rate": float(r[c_rate]) if c_rate != "None" and pd.notnull(r[c_rate]) else 0.0,
                                "tax": float(r[c_tax]) if c_tax != "None" and pd.notnull(r[c_tax]) else 12.0
                            })
                    bulk_upload_master_products(records)
                    st.success(f"✅ Successfully imported {len(records)} products!")
                    st.rerun()
            except Exception as ex:
                st.error(f"Error reading file: {ex}")

    with m_col2:
        st.markdown("### 📋 Master Products Database")
        m_df = load_master_products()
        st.dataframe(m_df, use_container_width=True)
        
        st.markdown("---")
        st.markdown("##### 🗑️ Remove Product")
        p_del_list = m_df["product_name"].tolist() if not m_df.empty else ["None"]
        del_p = st.selectbox("Select Product to Delete", p_del_list)
        if st.button("❌ Delete Product"):
            if del_p != "None":
                delete_master_product(del_p)
                st.success(f"Product '{del_p}' deleted.")
                st.rerun()
