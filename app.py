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
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, invoice TEXT, party TEXT, product TEXT, qty REAL, mrp REAL, discount REAL, rate REAL, gst REAL, amount REAL, created_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS purchase 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, invoice TEXT, party TEXT, product TEXT, qty REAL, mrp REAL, discount REAL, rate REAL, gst REAL, amount REAL, created_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (username TEXT PRIMARY KEY, password TEXT, name TEXT, role TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS master_products 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, product_name TEXT UNIQUE)''')
    
    # Default Users
    c.execute("INSERT OR IGNORE INTO users VALUES ('manager', 'admin123', 'Manager', 'Manager')")
    c.execute("INSERT OR IGNORE INTO users VALUES ('satya', 'satya123', 'Satya Sahu', 'Sales Executive')")
    
    # Default Master Products
    defaults = [
        "ATPLEX Syrup", "Duty Beauty MINUS 16 Cream", "Duty Beauty Glutathione Soap",
        "Duty Beauty Facewash", "Kabja Band", "Cartibot", "Virload", "Womensa Syrup",
        "Panchaliv Syrup", "Alobyd-P", "Ureta", "Brainenza", "Cutpiles", "Acnetaz", "Dermapari"
    ]
    for p in defaults:
        c.execute("INSERT OR IGNORE INTO master_products (product_name) VALUES (?)", (p,))
        
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
            res = supabase.table("master_products").select("product_name").execute()
            if res.data:
                return [row["product_name"] for row in res.data]
        except Exception:
            pass
            
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT product_name FROM master_products ORDER BY product_name ASC")
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

def add_master_product(product_name):
    p_clean = product_name.strip()
    if not p_clean: return
    if supabase:
        try:
            supabase.table("master_products").insert({"product_name": p_clean}).execute()
        except Exception: pass
            
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO master_products (product_name) VALUES (?)", (p_clean,))
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

def bulk_upload_master_products(product_list):
    records = [{"product_name": p.strip()} for p in product_list if p.strip()]
    if supabase:
        try:
            supabase.table("master_products").insert(records).execute()
        except Exception: pass
            
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    for item in records:
        c.execute("INSERT OR IGNORE INTO master_products (product_name) VALUES (?)", (item["product_name"],))
    conn.commit()
    conn.close()

def auto_correct_brand(scanned_name, master_list):
    if not scanned_name or scanned_name == "Unknown":
        return "Unknown"
    matches = difflib.get_close_matches(scanned_name, master_list, n=1, cutoff=0.5)
    return matches[0] if matches else scanned_name

# Transaction Data Handling
def save_transaction_data(table_name, items, invoice, party):
    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    records = []
    for row in items:
        records.append({
            "invoice": invoice,
            "party": party,
            "product": row.get('PRODUCT', ''),
            "qty": float(row.get('QTY', 0)),
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
        except Exception:
            pass
    
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    for r in records:
        c.execute(f'''INSERT INTO {table_name} (invoice, party, product, qty, mrp, discount, rate, gst, amount, created_at)
                      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                  (r["invoice"], r["party"], r["product"], r["qty"], r["mrp"], r["discount"], r["rate"], r["gst"], r["amount"], r["created_at"]))
    conn.commit()
    conn.close()
    return saved_cloud

def load_transaction_data(table_name):
    if supabase:
        try:
            res = supabase.table(table_name).select("*").order("id", desc=True).execute()
            if res.data:
                return pd.DataFrame(res.data)
        except Exception:
            pass
            
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
        except Exception:
            pass
            
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT username, password, name, role FROM users")
    rows = c.fetchall()
    conn.close()
    return {r[0]: {"password": r[1], "name": r[2], "role": r[3]} for r in rows}

def save_new_user(username, password, name, role):
    if supabase:
        try:
            supabase.table("users").insert({"username": username, "password": password, "name": name, "role": role}).execute()
        except Exception:
            pass
            
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO users VALUES (?, ?, ?, ?)", (username, password, name, role))
    conn.commit()
    conn.close()

def delete_user_db(username):
    if supabase:
        try:
            supabase.table("users").delete().eq("username", username).execute()
        except Exception:
            pass
            
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

def process_bill_with_gemini(uploaded_file, text_input, master_list):
    try:
        model = genai.GenerativeModel('gemini-3.5-flash-lite')
        
        prompt = f"""
        Extract medicine invoice details from image or text for pharma wholesale ERP.
        Master Products Reference: {", ".join(master_list)}
        Extract items with Qty, Rate, MRP, GST, and Discount.
        Return ONLY a clean JSON array of objects without Markdown formatting:
        [
          {{"PRODUCT": "Womensa Syrup", "QTY": 20, "MRP": 198.0, "DISCOUNT": 0.0, "RATE": 120.0, "GST": 12}}
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
            raw_prod = str(item.get("PRODUCT", "Unknown"))
            corrected_prod = auto_correct_brand(raw_prod, master_list)
            
            try: qty = float(item.get("QTY", 1) or 1)
            except: qty = 1.0
            
            try: mrp = float(item.get("MRP", 0.0) or 0.0)
            except: mrp = 0.0

            try: rate = float(item.get("RATE", 0.0) or 0.0)
            except: rate = 0.0
            
            try: gst = float(item.get("GST", 12) or 12)
            except: gst = 12.0
            
            try: disc = float(item.get("DISCOUNT", 0.0) or 0.0)
            except: disc = 0.0
            
            # Rate Calculation logic when rate is missing
            if rate == 0.0 and mrp > 0:
                if gst == 18.0:
                    rate = round((mrp * 80.0) / 118.0, 2)
                else:
                    rate = round((mrp * 80.0) / 105.0, 2)
                    
            if disc > 0:
                effective_rate = rate * (1 - (disc / 100.0))
            else:
                effective_rate = rate
                
            amt = qty * effective_rate
            
            cleaned_data.append({
                "PRODUCT": corrected_prod,
                "QTY": qty,
                "MRP": mrp,
                "DISCOUNT (%)": disc,
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
    
    pdf.set_font("Helvetica", 'B', 9)
    pdf.cell(60, 7, "Product", 1)
    pdf.cell(20, 7, "Qty", 1)
    pdf.cell(25, 7, "MRP (Rs)", 1)
    pdf.cell(25, 7, "Disc (%)", 1)
    pdf.cell(25, 7, "Rate (Rs)", 1)
    pdf.cell(35, 7, "Amount (Rs)", 1)
    pdf.ln()
    
    pdf.set_font("Helvetica", '', 9)
    for row in cart_data:
        pdf.cell(60, 6, str(row['PRODUCT'])[:28], 1)
        pdf.cell(20, 6, str(row['QTY']), 1)
        pdf.cell(25, 6, f"{float(row['MRP']):.2f}", 1)
        pdf.cell(25, 6, f"{float(row.get('DISCOUNT (%)', 0)):.1f}%", 1)
        pdf.cell(25, 6, f"{float(row['RATE']):.2f}", 1)
        pdf.cell(35, 6, f"{float(row['AMOUNT']):.2f}", 1)
        pdf.ln()
        
    pdf.ln(4)
    pdf.set_font("Helvetica", 'B', 10)
    pdf.cell(190, 6, f"Total MRP: Rs. {total_mrp:,.2f}", new_x="LMARGIN", new_y="NEXT", align='R')
    pdf.cell(190, 6, f"Total Discount: Rs. {total_disc:,.2f}", new_x="LMARGIN", new_y="NEXT", align='R')
    pdf.cell(190, 6, f"Sub Total: Rs. {sub_total:,.2f}", new_x="LMARGIN", new_y="NEXT", align='R')
    pdf.cell(190, 6, f"GST (12%): Rs. {gst_val:,.2f}", new_x="LMARGIN", new_y="NEXT", align='R')
    pdf.cell(190, 6, f"Grand Total: Rs. {net_val:,.2f}", new_x="LMARGIN", new_y="NEXT", align='R')
    
    return bytes(pdf.output())

if "logged_in" not in st.session_state: st.session_state["logged_in"] = False
if "scanned_cart" not in st.session_state: st.session_state["scanned_cart"] = []

USERS_DB = load_all_users()
MASTER_PRODUCTS = load_master_products()

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
            with st.spinner("Fast Scanning & Auto-Correcting Brand Names..."):
                items = process_bill_with_gemini(uploaded_img, raw_text, MASTER_PRODUCTS)
                if items:
                    st.session_state["scanned_cart"].extend(items)
                    st.success("✅ Fast Scan Completed with Master Matching!")
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
    p1, p2, p3, p4, p5 = st.columns([2, 1, 1, 1, 1])
    with p1: 
        sel_prod = st.selectbox("Product", MASTER_PRODUCTS if MASTER_PRODUCTS else ["Select Product"])
    with p2: 
        s_qty = st.number_input("Qty", min_value=1, value=10)
    with p3: 
        s_mrp = st.number_input("MRP (₹)", min_value=0.0, value=150.0)
    with p4: 
        s_disc = st.number_input("Discount (%)", min_value=0.0, max_value=100.0, value=20.0)
    with p5:
        calc_rate = round(s_mrp * (1 - (s_disc / 100.0)), 2)
        st.write(f"**Net Rate:** ₹{calc_rate}")
        if st.button("➕ Add Item"):
            amt = float(s_qty) * calc_rate
            st.session_state["scanned_cart"].append({
                "PRODUCT": sel_prod, "QTY": float(s_qty), "MRP": float(s_mrp),
                "DISCOUNT (%)": float(s_disc), "RATE": calc_rate, "GST": 12.0, "AMOUNT": round(amt, 2)
            })
            st.rerun()

    # Display Cart
    if st.session_state["scanned_cart"]:
        st.markdown("---")
        st.subheader("🛒 Scanned / Current Bill Items")
        
        # Calculate row-wise & Delete single row handling
        updated_cart = []
        total_mrp_sum = 0.0
        total_disc_val = 0.0
        
        for idx, item in enumerate(st.session_state["scanned_cart"]):
            col_a, col_b = st.columns([10, 1])
            with col_b:
                if st.button("🗑️", key=f"del_{idx}"):
                    st.session_state["scanned_cart"].pop(idx)
                    st.rerun()
            with col_a:
                try: qty = float(item.get("QTY", 1))
                except: qty = 1.0
                try: mrp = float(item.get("MRP", 0))
                except: mrp = 0.0
                try: disc = float(item.get("DISCOUNT (%)", 0))
                except: disc = 0.0
                try: rate = float(item.get("RATE", 0))
                except: rate = 0.0
                
                if rate == 0.0 and mrp > 0:
                    rate = round(mrp * (1 - (disc / 100.0)), 2)
                    
                eff_rate = rate * (1 - (disc / 100.0)) if disc > 0 else rate
                amt = qty * eff_rate
                
                item["QTY"] = qty
                item["MRP"] = mrp
                item["DISCOUNT (%)"] = disc
                item["RATE"] = round(rate, 2)
                item["AMOUNT"] = round(amt, 2)
                
                total_mrp_sum += mrp * qty
                total_disc_val += (mrp * qty) - amt if mrp > 0 else 0.0
                updated_cart.append(item)

        cart_df = pd.DataFrame(updated_cart)
        edited_df = st.data_editor(cart_df, key="cart_editor", disabled=["AMOUNT"], use_container_width=True)
        st.session_state["scanned_cart"] = edited_df.to_dict('records')
        
        sub_total = float(edited_df["AMOUNT"].sum())
        gst_val = sub_total * 0.12
        net_val = sub_total + gst_val
        
        st.markdown(f"""
            <div style='background-color:#FFF3E0; padding:15px; border-radius:10px; border-left:5px solid #EF6C00;'>
                <h4 style='color:#E65100; margin:0;'>🏷️ Total MRP: ₹ {total_mrp_sum:,.2f} | 🎁 Discount Shell: ₹ {total_disc_val:,.2f}</h4>
                <h3 style='color:#D84315; margin-top:5px;'>💰 Sub Total: ₹ {sub_total:,.2f} | GST (12%): ₹ {gst_val:,.2f} | Grand Total: ₹ {net_val:,.2f}</h3>
            </div>
        """, unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)
        
        save_col1, save_col2, save_col3, save_col4, save_col5 = st.columns(5)
        
        with save_col1:
            if st.button("📤 Save SALES"):
                saved_cloud = save_transaction_data("sales", st.session_state["scanned_cart"], inv_no, party_name)
                st.success("✅ Saved to Sales Database!")
                st.session_state["scanned_cart"] = []
                st.rerun()

        with save_col2:
            if st.button("📥 Save PURCHASE"):
                saved_cloud = save_transaction_data("purchase", st.session_state["scanned_cart"], inv_no, party_name)
                st.success("✅ Saved to Purchase Database!")
                st.session_state["scanned_cart"] = []
                st.rerun()

        with save_col3:
            try:
                pdf_bytes = generate_pdf_invoice(party_name, inv_no, gst_no, st.session_state["scanned_cart"], total_mrp_sum, total_disc_val, sub_total, gst_val, net_val)
                st.download_button(label="📄 Download PDF", data=pdf_bytes, file_name=f"{inv_no}.pdf", mime="application/pdf")
            except Exception as pdf_err:
                st.error(f"PDF Error: {pdf_err}")

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
    st.dataframe(df_pur[['product', 'qty', 'mrp', 'rate', 'created_at']], use_container_width=True) if not df_pur.empty else st.info("No Stock data available.")

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
        single_p = st.text_input("Product Name (e.g. Brainenza Syrup)")
        if st.button("➕ Add Product to Master"):
            if single_p:
                add_master_product(single_p)
                st.success(f"✅ Product '{single_p}' added successfully!")
                st.rerun()
                
        st.markdown("---")
        st.markdown("### 📂 Upload New Product List (CSV / Excel)")
        file_up = st.file_uploader("Upload CSV or Excel File", type=["csv", "xlsx"])
        if file_up:
            try:
                if file_up.name.endswith('.csv'):
                    df_up = pd.read_csv(file_up)
                else:
                    df_up = pd.read_excel(file_up)
                    
                st.write("Preview of uploaded list:")
                st.dataframe(df_up.head(), use_container_width=True)
                col_name = st.selectbox("Select Column containing Product Names", df_up.columns)
                
                if st.button("🚀 Upload & Replace / Add to Master List"):
                    plist = df_up[col_name].dropna().astype(str).tolist()
                    bulk_upload_master_products(plist)
                    st.success(f"✅ Successfully added {len(plist)} products to Master List!")
                    st.rerun()
            except Exception as ex:
                st.error(f"Error reading file: {ex}")

    with m_col2:
        st.markdown("### 📋 Current Master Products")
        m_list = load_master_products()
        st.dataframe(pd.DataFrame({"Product Name": m_list}), use_container_width=True)
        
        st.markdown("---")
        st.markdown("##### 🗑️ Remove Product")
        del_p = st.selectbox("Select Product to Delete", m_list)
        if st.button("❌ Delete Product"):
            delete_master_product(del_p)
            st.success(f"Product '{del_p}' deleted.")
            st.rerun()
