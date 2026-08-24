import sqlite3
import urllib.parse
import json
import io
import pandas as pd
import streamlit as st
import google.generativeai as genai
from PIL import Image, ImageDraw

# ==========================================
# 1. LOCAL SQLITE DATABASE SETUP WITH MIGRATION
# ==========================================
DB_FILE = "pharma_erp.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS sales_history 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, party_name TEXT, inv_no TEXT, salesman TEXT, date TEXT, product TEXT, hsn TEXT, batch TEXT, exp TEXT, mrp REAL, qty REAL, bonus REAL, rate REAL, disc_per REAL, gst_per REAL, net_amt REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS purchase_history 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, party_name TEXT, inv_no TEXT, salesman TEXT, date TEXT, product TEXT, hsn TEXT, batch TEXT, exp TEXT, mrp REAL, qty REAL, bonus REAL, rate REAL, disc_per REAL, gst_per REAL, net_amt REAL)''')
    
    for table in ["sales_history", "purchase_history"]:
        c.execute(f"PRAGMA table_info({table})")
        existing_cols = [col[1] for col in c.fetchall()]
        required_cols = {
            "salesman": "TEXT", "hsn": "TEXT", "batch": "TEXT", "exp": "TEXT", 
            "mrp": "REAL", "bonus": "REAL", "rate": "REAL", "disc_per": "REAL", 
            "gst_per": "REAL", "net_amt": "REAL"
        }
        for col_name, col_type in required_cols.items():
            if col_name not in existing_cols:
                try:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}")
                except Exception:
                    pass

    conn.commit()
    conn.close()

init_db()

# USER LOGIN DATABASE / DICTIONARY
USERS_DB = {
    "manager": {"password": "admin123", "role": "Manager", "name": "Manager"},
    "rahul": {"password": "rahul123", "role": "Sales Executive", "name": "Rahul"},
    "satya": {"password": "satya123", "role": "Sales Executive", "name": "Satya"},
    "sales1": {"password": "sales123", "role": "Sales Executive", "name": "Salesman 1"},
    "sales2": {"password": "sales223", "role": "Sales Executive", "name": "Salesman 2"},
}

def get_existing_customers():
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT DISTINCT party_name FROM sales_history", conn)
    conn.close()
    cust_list = df["party_name"].dropna().tolist() if not df.empty else []
    return sorted(list(set(cust_list + ["DR.S.V.SINGH", "SHREE RAM MEDICAL STORE", "MEDICARE PHARMA"])))

def get_existing_suppliers():
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT DISTINCT party_name FROM purchase_history", conn)
    conn.close()
    sup_list = df["party_name"].dropna().tolist() if not df.empty else []
    return sorted(list(set(sup_list + ["MEDICARE PHARMA", "LCB PHARMA", "SGB PHARMA", "SUN PHARMA"])))

def get_available_batch_products():
    conn = sqlite3.connect(DB_FILE)
    p_df = pd.read_sql_query("SELECT DISTINCT product, hsn, batch, exp, mrp, rate, gst_per FROM purchase_history", conn)
    s_df = pd.read_sql_query("SELECT DISTINCT product, hsn, batch, exp, mrp, rate, gst_per FROM sales_history", conn)
    conn.close()
    
    df = pd.concat([p_df, s_df]).drop_duplicates(subset=["product", "batch"])
    
    batch_map = {}
    options_list = [""]
    
    if not df.empty:
        for _, row in df.iterrows():
            p_name = str(row["product"]).strip().upper() if row["product"] else ""
            batch = str(row["batch"]).strip() if row["batch"] else ""
            mrp = float(row["mrp"]) if row["mrp"] else 0.0
            hsn = str(row["hsn"]).strip() if row["hsn"] else "3004"
            exp = str(row["exp"]).strip() if row["exp"] else ""
            rate = float(row["rate"]) if row["rate"] else 0.0
            gst = float(row["gst_per"]) if ("gst_per" in row and row["gst_per"]) else 5.0
            
            if p_name:
                display_label = f"{p_name} | BATCH: {batch} | MRP: Rs.{mrp}" if batch else p_name
                options_list.append(display_label)
                batch_map[display_label] = {
                    "product_name": p_name, "hsn": hsn, "batch": batch, "exp": exp, "mrp": mrp, "rate": rate, "gst": gst
                }

    defaults = [
        {"product_name": "GASMIT-DSR CAPS 1x10", "hsn": "3004", "batch": "WEB/05/063D", "exp": "04-28", "mrp": 109.00, "rate": 80.25, "gst": 5.0},
        {"product_name": "PANEC-P TAB 1x10", "hsn": "3004", "batch": "D6DT031", "exp": "03-28", "mrp": 56.00, "rate": 44.80, "gst": 12.0},
        {"product_name": "ALOBYD-SP TAB", "hsn": "3004", "batch": "AB-102", "exp": "12-27", "mrp": 95.00, "rate": 72.38, "gst": 18.0}
    ]
    for item in defaults:
        label = f"{item['product_name']} | BATCH: {item['batch']} | MRP: Rs.{item['mrp']}"
        if label not in options_list:
            options_list.append(label)
            batch_map[label] = item
            
    return sorted(options_list), batch_map

def save_sales_to_db(items_df, party, inv_no, salesman):
    conn = sqlite3.connect(DB_FILE)
    date_str = pd.Timestamp.now().strftime("%Y-%m-%d")
    for _, r in items_df.iterrows():
        p_name = str(r.get("PRODUCT", "")).strip().upper()
        p_qty = float(r.get("QTY", 0))
        if p_name and p_qty > 0:
            conn.execute("""INSERT INTO sales_history 
                (party_name, inv_no, salesman, date, product, hsn, batch, exp, mrp, qty, bonus, rate, disc_per, gst_per, net_amt) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (party, inv_no, salesman, date_str, p_name, str(r.get("HSN", "")), str(r.get("BATCH", "")), str(r.get("EXP", "")),
                 float(r.get("MRP", 0)), p_qty, float(r.get("BONUS", 0)), float(r.get("RATE", 0)), 
                 float(r.get("DIS %", 0)), float(r.get("Gst%", 5)), float(r.get("AMOUNT", 0))))
    conn.commit()
    conn.close()

def save_purchase_to_db(items_df, party, inv_no, salesman="System"):
    conn = sqlite3.connect(DB_FILE)
    date_str = pd.Timestamp.now().strftime("%Y-%m-%d")
    for _, r in items_df.iterrows():
        p_name = str(r.get("PRODUCT", "")).strip().upper()
        p_qty = float(r.get("QTY", 0))
        if p_name and p_qty > 0:
            conn.execute("""INSERT INTO purchase_history 
                (party_name, inv_no, salesman, date, product, hsn, batch, exp, mrp, qty, bonus, rate, disc_per, gst_per, net_amt) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (party, inv_no, salesman, date_str, p_name, str(r.get("HSN", "")), str(r.get("BATCH", "")), str(r.get("EXP", "")),
                 float(r.get("MRP", 0)), p_qty, float(r.get("BONUS", 0)), float(r.get("RATE", 0)), 
                 float(r.get("DIS %", 0)), float(r.get("Gst%", 5)), float(r.get("AMOUNT", 0))))
    conn.commit()
    conn.close()

def load_db_table(table_name):
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query(f"SELECT * FROM {table_name}", conn)
    conn.close()
    return df

def calculate_live_stock():
    p_df = load_db_table("purchase_history")
    s_df = load_db_table("sales_history")
    
    if p_df.empty and s_df.empty:
        return pd.DataFrame(columns=["Product Name", "Batch", "Purchased Qty", "Sold Qty", "Available Stock"])

    if not p_df.empty:
        p_df["qty"] = pd.to_numeric(p_df["qty"], errors="coerce").fillna(0)
        p_df["product"] = p_df["product"].astype(str).str.strip().str.upper()
        p_df["batch"] = p_df["batch"].astype(str).str.strip()
        p_tot = p_df.groupby(["product", "batch"])["qty"].sum().reset_index(name="Purchased Qty")
    else:
        p_tot = pd.DataFrame(columns=["product", "batch", "Purchased Qty"])

    if not s_df.empty:
        s_df["qty"] = pd.to_numeric(s_df["qty"], errors="coerce").fillna(0)
        s_df["product"] = s_df["product"].astype(str).str.strip().str.upper()
        s_df["batch"] = s_df["batch"].astype(str).str.strip()
        s_tot = s_df.groupby(["product", "batch"])["qty"].sum().reset_index(name="Sold Qty")
    else:
        s_tot = pd.DataFrame(columns=["product", "batch", "Sold Qty"])

    stock_df = pd.merge(p_tot, s_tot, on=["product", "batch"], how="outer").fillna(0)
    stock_df["Available Stock"] = stock_df["Purchased Qty"] - stock_df["Sold Qty"]
    
    stock_df.rename(columns={"product": "Product Name", "batch": "Batch"}, inplace=True)
    return stock_df

def safe_calculate_bill(df):
    calc_df = df.copy()
    num_cols = ["MRP", "QTY", "BONUS", "RATE", "DIS %", "Gst%"]
    for c in num_cols:
        if c in calc_df.columns:
            calc_df[c] = pd.to_numeric(calc_df[c], errors="coerce").fillna(0.0)
        else:
            calc_df[c] = 5.0 if c == "Gst%" else 0.0

    calc_df["Gross"] = calc_df["QTY"] * calc_df["RATE"]
    calc_df["Disc_Amt"] = (calc_df["Gross"] * calc_df["DIS %"]) / 100.0
    calc_df["Taxable"] = calc_df["Gross"] - calc_df["Disc_Amt"]
    calc_df["GST_Amt"] = (calc_df["Taxable"] * calc_df["Gst%"]) / 100.0
    calc_df["AMOUNT"] = (calc_df["Taxable"] + calc_df["GST_Amt"]).round(2)
    return calc_df

def generate_bill_jpg(inv_no, party_name, salesman, items_df, total_amount):
    img_w, img_h = 800, 1000
    img = Image.new('RGB', (img_w, img_h), color='#FFFFFF')
    draw = ImageDraw.Draw(img)
    
    draw.rectangle([(0, 0), (800, 90)], fill='#FF6F00')
    draw.text((20, 25), "PHARMA ERP - INVOICE", fill='#FFFFFF')
    
    y = 110
    draw.text((20, y), f"Invoice No: {inv_no}", fill='#000000')
    draw.text((400, y), f"Date: {pd.Timestamp.now().strftime('%Y-%m-%d')}", fill='#000000')
    y += 25
    draw.text((20, y), f"Party Name: {party_name}", fill='#000000')
    draw.text((400, y), f"Salesman: {salesman}", fill='#000000')
    y += 35
    
    draw.rectangle([(20, y), (780, y+30)], fill='#FFE0B2')
    draw.text((30, y+5), "Product", fill='#E65100')
    draw.text((300, y+5), "Batch", fill='#E65100')
    draw.text((420, y+5), "Qty", fill='#E65100')
    draw.text((500, y+5), "Rate", fill='#E65100')
    draw.text((600, y+5), "Dis%", fill='#E65100')
    draw.text((680, y+5), "Amount", fill='#E65100')
    
    y += 35
    for idx, row in items_df.iterrows():
        p_name = str(row.get("PRODUCT", ""))[:25]
        if not p_name: continue
        draw.text((30, y), p_name, fill='#000000')
        draw.text((300, y), str(row.get("BATCH", "")), fill='#000000')
        draw.text((420, y), str(row.get("QTY", 0)), fill='#000000')
        draw.text((500, y), f"Rs.{row.get('RATE', 0)}", fill='#000000')
        draw.text((600, y), f"{row.get('DIS %', 0)}%", fill='#000000')
        draw.text((680, y), f"Rs.{row.get('AMOUNT', 0)}", fill='#000000')
        y += 25
        if y > 850: break
        
    draw.line([(20, y+10), (780, y+10)], fill='#FF6F00', width=2)
    y += 20
    draw.text((500, y), "NET PAYABLE:", fill='#E65100')
    draw.text((650, y), f"Rs.{total_amount:,.2f}", fill='#E65100')
    
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG")
    return buffer.getvalue()

# ==========================================
# 2. APP CONFIG & ORANGE-WHITE THEME (CSS)
# ==========================================
st.set_page_config(
    page_title="Pharma ERP - Sales System", 
    layout="wide", 
    page_icon="💊"
)

st.markdown("""
    <style>
    .stApp {
        background-color: #FFFFFF;
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    }
    header[data-testid="stHeader"] {
        background: linear-gradient(90deg, #FF6F00, #FF8F00) !important;
    }
    section[data-testid="stSidebar"] {
        background-color: #FFF3E0 !important;
        border-right: 2px solid #FFE0B2;
    }
    .stButton>button, div[data-baseweb="button"] {
        width: 100% !important;
        background: #FF6F00 !important;
        color: white !important;
        font-weight: bold !important;
        border-radius: 8px !important;
        border: none !important;
    }
    .stButton>button:hover {
        background: #E65100 !important;
    }
    div[data-testid="stMetric"] {
        background-color: #FFFFFF !important;
        padding: 15px !important;
        border-radius: 10px !important;
        border-left: 6px solid #FF6F00 !important;
        box-shadow: 0px 2px 8px rgba(0,0,0,0.05) !important;
    }
    a[href*="whatsapp.com"] {
        display: block;
        text-align: center;
        background-color: #25D366 !important;
        color: white !important;
        font-weight: bold;
        padding: 10px;
        border-radius: 8px;
        text-decoration: none;
    }
    </style>
""", unsafe_allow_html=True)

if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

def process_bill_with_ai(image):
    model = genai.GenerativeModel('gemini-3.5-flash')
    prompt = """Extract invoice details from image in JSON format matching this structure:
    {"party_name": "...", "inv_no": "...", "items": [{"HSN": "3004", "PRODUCT": "...", "QTY": 0.0, "BONUS": 0.0, "RATE": 0.0, "DIS %": 0.0, "Gst%": 5.0, "BATCH": "...", "EXP": "04-28", "MRP": 0.0}]}"""
    response = model.generate_content([prompt, image])
    clean_json = response.text.replace("```json", "").replace("```", "").strip()
    return json.loads(clean_json)

# ==========================================
# 3. LOGIN & AUTHENTICATION MODULE
# ==========================================
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
    st.session_state["user_info"] = None

if not st.session_state["logged_in"]:
    st.markdown("<br><br>", unsafe_allow_html=True)
    c_loc1, c_loc2, c_loc3 = st.columns([1, 2, 1])
    with c_loc2:
        st.markdown("<h2 style='text-align: center; color: #E65100;'>🔐 Pharma ERP Portal Login</h2>", unsafe_allow_html=True)
        username_inp = st.text_input("👤 Username:").strip().lower()
        password_inp = st.text_input("🔑 Password:", type="password").strip()
        
        if st.button("🚀 Login"):
            if username_inp in USERS_DB and USERS_DB[username_inp]["password"] == password_inp:
                st.session_state["logged_in"] = True
                st.session_state["user_info"] = USERS_DB[username_inp]
                st.success(f"Welcome {USERS_DB[username_inp]['name']}!")
                st.rerun()
            else:
                st.error("❌ Invalid Username or Password")
        
        st.info("💡 **Default Logins:**\n- **Manager:** manager / admin123\n- **Sales Executives:** rahul / rahul123, satya / satya123, sales1 / sales123")
    st.stop()

# LOGGED IN USER CONTEXT
logged_user = st.session_state["user_info"]
user_role = logged_user["role"]
logged_user_name = logged_user["name"]

# SIDEBAR MENU & USER INFO
st.sidebar.markdown(f"### 👤 Welcome, **{logged_user_name}**")
st.sidebar.caption(f"Role: {user_role}")

if st.sidebar.button("🚪 Logout"):
    st.session_state["logged_in"] = False
    st.session_state["user_info"] = None
    st.rerun()

st.sidebar.markdown("---")

# NAVIGATION MODULES
menu_options = [
    "🧾 Sales Invoice (Format)", 
    "📷 AI Bill Scanner", 
    "📦 Purchase Entry", 
    "📦 Live Stock Inventory", 
    "📊 Reports & Statements"
]

if user_role == "Manager":
    menu_options.append("📈 Manager Salesman Dashboard")

active_tab = st.sidebar.radio("📌 Select Module:", menu_options)

# ------------------------------------------
# MODULE 1: SALES INVOICE
# ------------------------------------------
if active_tab == "🧾 Sales Invoice (Format)":
    st.markdown("<h2 style='color: #E65100;'>🧾 New Sales Invoice</h2>", unsafe_allow_html=True)

    customers = get_existing_customers()
    batch_options, batch_map = get_available_batch_products()

    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        s_party = st.selectbox("Billed To (Type to filter):", options=["+ Add New Customer"] + customers)
        if s_party == "+ Add New Customer":
            s_party = st.text_input("Enter New Customer Name:", "DR.S.V.SINGH")
    with c2:
        s_inv_no = st.text_input("NO. / Invoice No.", f"{pd.Timestamp.now().strftime('%H%M%S')}")
    with c3:
        if user_role == "Manager":
            salesman_options = ["Rahul", "Satya", "Salesman 1", "Salesman 2"]
            s_salesman = st.selectbox("Select Salesman:", options=salesman_options)
        else:
            s_salesman = logged_user_name
            st.text_input("Salesman Name:", value=s_salesman, disabled=True)

    if "sales_cart" not in st.session_state:
        st.session_state["sales_cart"] = []

    st.markdown("---")
    st.markdown("<h4 style='color: #FF6F00;'>⚡ Quick Item Selector</h4>", unsafe_allow_html=True)

    net_rate_on = st.checkbox("⚡ Net Rate (Auto Discount 4.76% / 15.26%)", value=False)

    selected_prod_label = st.selectbox("🔍 Search & Select Product [Batch | MRP]:", options=batch_options)
    selected_details = batch_map.get(selected_prod_label, {})

    col_inputs = st.columns([1, 1, 1, 1, 1])
    with col_inputs[0]:
        input_qty = st.number_input("QTY (मात्रा)", min_value=0.0, value=10.0, step=1.0)
    with col_inputs[1]:
        input_bonus = st.number_input("Deal / Bonus", min_value=0.0, value=0.0, step=1.0)
    with col_inputs[2]:
        default_rate = float(selected_details.get("rate", 0.0))
        input_rate = st.number_input("Rate (दर)", min_value=0.0, value=default_rate, step=1.0)
    with col_inputs[3]:
        current_gst = float(selected_details.get("gst", 5.0))
        if net_rate_on:
            auto_dis_val = 4.76 if current_gst == 5.0 else (15.26 if current_gst == 18.0 else 10.71)
            input_disc = st.number_input("DIS % (छूट)", value=auto_dis_val, disabled=True)
        else:
            input_disc = st.number_input("DIS % (छूट)", min_value=0.0, value=0.0, step=0.5)
    with col_inputs[4]:
        st.write(" ")
        st.write(" ")
        add_btn = st.button("➕ Add Item")

    if add_btn:
        if selected_prod_label and input_qty > 0:
            st.session_state["sales_cart"].append({
                "HSN": selected_details.get("hsn", "3004"),
                "PRODUCT": selected_details.get("product_name", ""),
                "QTY": input_qty,
                "BONUS": input_bonus,
                "RATE": input_rate,
                "DIS %": input_disc,
                "Gst%": selected_details.get("gst", 5.0),
                "BATCH": selected_details.get("batch", ""),
                "EXP": selected_details.get("exp", ""),
                "MRP": selected_details.get("mrp", 0.0)
            })
            st.success(f"Added {selected_details.get('product_name')}")
            st.rerun()

    st.markdown("### 📝 Invoice Items Table")

    if not st.session_state["sales_cart"]:
        cart_df = pd.DataFrame([{
            "HSN": "3004", "PRODUCT": "", "QTY": 0.0, "BONUS": 0.0, "RATE": 0.0, "DIS %": 0.0, "Gst%": 5.0, "BATCH": "", "EXP": "", "MRP": 0.0
        }])
    else:
        cart_df = pd.DataFrame(st.session_state["sales_cart"])

    edited_sales = st.data_editor(cart_df, num_rows="dynamic", use_container_width=True, key="sales_data_editor")
    st.session_state["sales_cart"] = edited_sales.to_dict("records")
    
    calc_sales_df = safe_calculate_bill(edited_sales)
    
    total_amount = calc_sales_df["AMOUNT"].sum()
    total_disc = calc_sales_df["Disc_Amt"].sum()
    total_gst = calc_sales_df["GST_Amt"].sum()

    st.markdown("---")
    col_tot1, col_tot2, col_tot3 = st.columns(3)
    col_tot1.metric("Total Disc", f"₹{total_disc:,.2f}")
    col_tot2.metric("GST Amount", f"₹{total_gst:,.2f}")
    col_tot3.metric("NET PAYABLE", f"₹{total_amount:,.2f}")

    st.write(" ")
    col_btn1, col_btn2 = st.columns([3, 1])
    with col_btn1:
        if st.button("💾 Save Bill"):
            valid_items = calc_sales_df[(calc_sales_df["PRODUCT"].astype(str).str.strip() != "") & (calc_sales_df["QTY"] > 0)].copy()
            if not valid_items.empty:
                save_sales_to_db(valid_items, s_party, s_inv_no, s_salesman)
                st.success("✅ Sales Bill Saved Successfully!")
                st.session_state["sales_cart"] = []
                st.rerun()
            else:
                st.warning("कृपया QTY दर्ज करें।")

    with col_btn2:
        if st.button("🗑️ Clear Table"):
            st.session_state["sales_cart"] = []
            st.rerun()

    st.markdown("---")
    st.markdown("<h4 style='color: #FF6F00;'>📄 Bill JPG Actions & Sharing</h4>", unsafe_allow_html=True)
    b_view, b_down, b_wa = st.columns(3)

    valid_items = calc_sales_df[(calc_sales_df["PRODUCT"].astype(str).str.strip() != "") & (calc_sales_df["QTY"] > 0)].copy()
    jpg_bytes = generate_bill_jpg(s_inv_no, s_party, s_salesman, valid_items, total_amount)

    with b_view:
        if st.button("👁️ View JPG Bill Preview", use_container_width=True):
            st.image(jpg_bytes, caption=f"Bill Preview #{s_inv_no}", use_container_width=True)

    with b_down:
        st.download_button(
            label="📥 Download Bill JPG",
            data=jpg_bytes,
            file_name=f"Invoice_{s_inv_no}.jpg",
            mime="image/jpeg",
            use_container_width=True
        )

    with b_wa:
        wa_text = f"📄 *INVOICE DETAILS*\n"
        wa_text += f"-------------------------\n"
        wa_text += f"Inv No: *{s_inv_no}*\n"
        wa_text += f"Customer: *{s_party}*\n"
        wa_text += f"Salesman: *{s_salesman}*\n"
        wa_text += f"-------------------------\n"
        wa_text += f"*ITEMS:*\n"
        
        for _, r in valid_items.iterrows():
            wa_text += f"• {r.get('PRODUCT')} | Qty: {r.get('QTY')} | Rate: Rs.{r.get('RATE')} | Amt: Rs.{r.get('AMOUNT')}\n"
            
        wa_text += f"-------------------------\n"
        wa_text += f"GST Total: Rs.{total_gst:,.2f}\n"
        wa_text += f"Discount Total: Rs.{total_disc:,.2f}\n"
        wa_text += f"💰 *NET PAYABLE: Rs.{total_amount:,.2f}*\n"
        wa_text += f"-------------------------\n"
        wa_text += f"Thank you for your business!"

        wa_url = f"https://api.whatsapp.com/send?text={urllib.parse.quote(wa_text)}"
        st.markdown(f"<a href='{wa_url}' target='_blank'>📲 Share Full Bill on WhatsApp</a>", unsafe_allow_html=True)

# ------------------------------------------
# MODULE 2: AI BILL SCANNER
# ------------------------------------------
elif active_tab == "📷 AI Bill Scanner":
    st.markdown("<h2 style='color: #E65100;'>📷 AI Bill Photo Scanner</h2>", unsafe_allow_html=True)

    uploaded_file = st.file_uploader("Upload Invoice Photo", type=["jpg", "jpeg", "png"])
    if uploaded_file is not None:
        img = Image.open(uploaded_file)
        st.image(img, caption="Uploaded Invoice", use_container_width=True)
        
        if st.button("✨ Scan Bill with AI"):
            with st.spinner("AI पर्ची स्कैन कर रहा है..."):
                try:
                    data = process_bill_with_ai(img)
                    st.session_state["scanned_data"] = data
                    st.success("✅ स्कैन पूरा हुआ!")
                except Exception as e:
                    st.error(f"स्कैन एरर: {e}")

    if "scanned_data" in st.session_state:
        sc_data = st.session_state["scanned_data"]
        
        party_name = st.text_input("🏬 Customer / Supplier Name", value=sc_data.get("party_name", "DR.S.V.SINGH"))
        inv_no = st.text_input("📄 Invoice / Bill No.", value=sc_data.get("inv_no", f"{pd.Timestamp.now().strftime('%H%M%S')}"))

        if "items" in sc_data and sc_data["items"]:
            df_scanned = pd.DataFrame(sc_data["items"])
            calc_scanned_df = safe_calculate_bill(df_scanned)
            grand_total = calc_scanned_df["AMOUNT"].sum()

            st.subheader("Extracted Bill Items")
            edited_scanned = st.data_editor(calc_scanned_df, num_rows="dynamic", use_container_width=True)

            st.markdown(f"### 💰 NET PAYABLE: **₹{grand_total:,.2f}**")

            col1, col2 = st.columns(2)
            with col1:
                if st.button("📥 Save as Purchase Stock"):
                    valid_scanned = edited_scanned[(edited_scanned["PRODUCT"].astype(str).str.strip() != "") & (edited_scanned["QTY"] > 0)].copy()
                    if not valid_scanned.empty:
                        save_purchase_to_db(valid_scanned, party_name, inv_no, logged_user_name)
                        st.success("🎉 पर्ची Purchase History में सेव हो गई!")
                        del st.session_state["scanned_data"]
                        st.rerun()

            with col2:
                if st.button("🧾 Save as Sales Bill"):
                    valid_scanned = edited_scanned[(edited_scanned["PRODUCT"].astype(str).str.strip() != "") & (edited_scanned["QTY"] > 0)].copy()
                    if not valid_scanned.empty:
                        save_sales_to_db(valid_scanned, party_name, inv_no, logged_user_name)
                        st.success("🎉 पर्ची Sales Bill में दर्ज हो गई!")
                        del st.session_state["scanned_data"]
                        st.rerun()

# ------------------------------------------
# MODULE 3: PURCHASE ENTRY
# ------------------------------------------
elif active_tab == "📦 Purchase Entry":
    st.markdown("<h2 style='color: #E65100;'>📦 Purchase Inward Entry</h2>", unsafe_allow_html=True)

    suppliers = get_existing_suppliers()

    c1, c2 = st.columns([2, 1])
    with c1:
        p_party = st.selectbox("Supplier Name:", options=["+ Add New Supplier"] + suppliers)
        if p_party == "+ Add New Supplier":
            p_party = st.text_input("Enter New Supplier Name:", "MEDICARE PHARMA")
    with c2:
        p_inv_no = st.text_input("Bill No.", "PUR-101")

    if "purchase_data" not in st.session_state:
        st.session_state["purchase_data"] = pd.DataFrame([{
            "HSN": "3004", "PRODUCT": "", "QTY": 0.0, "BONUS": 0.0, "RATE": 0.0, "DIS %": 0.0, "Gst%": 5.0, "BATCH": "", "EXP": "", "MRP": 0.0
        }])

    st.write("### 📝 Purchase Items Table")

    p_df = st.data_editor(st.session_state["purchase_data"], num_rows="dynamic", use_container_width=True)
    st.session_state["purchase_data"] = p_df
    
    calc_p_df = safe_calculate_bill(p_df)

    st.markdown("---")
    tot_p_amt = calc_p_df["AMOUNT"].sum()
    st.metric("TOTAL PURCHASE VALUE", f"₹{tot_p_amt:,.2f}")

    c_p1, c_p2 = st.columns([3, 1])
    with c_p1:
        if st.button("📥 Save Purchase Stock"):
            valid_p = calc_p_df[(calc_p_df["PRODUCT"].astype(str).str.strip() != "") & (calc_p_df["QTY"] > 0)].copy()
            if not valid_p.empty:
                save_purchase_to_db(valid_p, p_party, p_inv_no, logged_user_name)
                st.success("✅ Purchase Stock Saved Successfully!")
                st.session_state["purchase_data"] = pd.DataFrame([{
                    "HSN": "3004", "PRODUCT": "", "QTY": 0.0, "BONUS": 0.0, "RATE": 0.0, "DIS %": 0.0, "Gst%": 5.0, "BATCH": "", "EXP": "", "MRP": 0.0
                }])
                st.rerun()
            else:
                st.warning("कृपया कम से कम एक उत्पाद चुनें और QTY दर्ज करें।")

    with c_p2:
        if st.button("🗑️ Reset Table"):
            st.session_state["purchase_data"] = pd.DataFrame([{
                "HSN": "3004", "PRODUCT": "", "QTY": 0.0, "BONUS": 0.0, "RATE": 0.0, "DIS %": 0.0, "Gst%": 5.0, "BATCH": "", "EXP": "", "MRP": 0.0
            }])
            st.rerun()

# ------------------------------------------
# MODULE 4: LIVE STOCK INVENTORY
# ------------------------------------------
elif active_tab == "📦 Live Stock Inventory":
    st.markdown("<h2 style='color: #E65100;'>📦 Live Stock Inventory Balance</h2>", unsafe_allow_html=True)
    stock_df = calculate_live_stock()
    
    if stock_df.empty:
        st.info("अभी कोई स्टॉक डेटा उपलब्ध नहीं है।")
    else:
        neg_items = stock_df[stock_df["Available Stock"] < 0]
        if not neg_items.empty:
            st.warning(f"⚠️ ध्यान दें: {len(neg_items)} आइटम माइनस (-) स्टॉक में हैं।")

        st.dataframe(stock_df, use_container_width=True)

# ------------------------------------------
# MODULE 5: REPORTS & STATEMENTS
# ------------------------------------------
elif active_tab == "📊 Reports & Statements":
    st.markdown("<h2 style='color: #E65100;'>📊 Statements & Reports</h2>", unsafe_allow_html=True)
    
    s_df = load_db_table("sales_history")
    
    # FILTER FOR SALESMAN ROLE (CAN ONLY SEE THEIR OWN SALES)
    if user_role != "Manager" and not s_df.empty:
        s_df = s_df[s_df["salesman"] == logged_user_name]

    tab_sales, tab_purchase, tab_delete = st.tabs(["📈 Sales Statement", "🛒 Purchase Statement", "🗑️ View / Delete Invoices"])

    with tab_sales:
        st.subheader("🧾 Sales Summary Statement")
        
        if s_df.empty:
            st.info("कोई सेल रिकॉर्ड उपलब्ध नहीं है।")
        else:
            col_f1, col_f2 = st.columns(2)
            with col_f1:
                s_customers = ["ALL Customers"] + sorted(s_df["party_name"].unique().tolist())
                selected_cust = st.selectbox("👤 Filter Sales by Customer:", options=s_customers, key="sales_cust_filter")
            with col_f2:
                if user_role == "Manager":
                    s_salesmen = ["ALL Salesmen"] + sorted(s_df["salesman"].unique().tolist())
                    selected_salesman_filt = st.selectbox("👨‍💼 Filter Sales by Salesman:", options=s_salesmen, key="sales_sman_filter")
                else:
                    selected_salesman_filt = logged_user_name

            filtered_sales = s_df.copy()
            if selected_cust != "ALL Customers":
                filtered_sales = filtered_sales[filtered_sales["party_name"] == selected_cust]
            if user_role == "Manager" and selected_salesman_filt != "ALL Salesmen":
                filtered_sales = filtered_sales[filtered_sales["salesman"] == selected_salesman_filt]

            sales_summary = filtered_sales.groupby(["inv_no", "date", "party_name", "salesman"]).agg(
                Sales_Value=("net_amt", "sum"),
                Total_Items=("product", "count")
            ).reset_index()

            sales_summary.rename(columns={
                "inv_no": "Sales Invoice No",
                "date": "Date",
                "party_name": "Party Name",
                "salesman": "Salesman",
                "Sales_Value": "Sales Value (₹)",
                "Total_Items": "Total Items"
            }, inplace=True)

            m1, m2 = st.columns(2)
            m1.metric("Total Invoices", len(sales_summary))
            m2.metric("Total Sales Value", f"₹{sales_summary['Sales Value (₹)'].sum():,.2f}")

            st.dataframe(sales_summary, use_container_width=True)

            st.markdown("---")
            if st.checkbox("🔍 Show Full Detailed Sales Log"):
                st.dataframe(filtered_sales, use_container_width=True)

    with tab_purchase:
        st.subheader("🛒 Purchase Summary Statement")
        p_df = load_db_table("purchase_history")

        if p_df.empty:
            st.info("कोई पर्चेज़ रिकॉर्ड उपलब्ध नहीं है।")
        else:
            p_suppliers = ["ALL Suppliers"] + sorted(p_df["party_name"].unique().tolist())
            selected_sup = st.selectbox("🏬 Filter Purchase by Supplier:", options=p_suppliers, key="purchase_sup_filter")

            filtered_purchase = p_df if selected_sup == "ALL Suppliers" else p_df[p_df["party_name"] == selected_sup]

            purchase_summary = filtered_purchase.groupby(["inv_no", "date", "party_name"]).agg(
                Purchase_Value=("net_amt", "sum"),
                Total_Items=("product", "count")
            ).reset_index()

            purchase_summary.rename(columns={
                "inv_no": "Purchase Invoice No",
                "date": "Date",
                "party_name": "Supplier / Party Name",
                "Purchase_Value": "Purchase Value (₹)",
                "Total_Items": "Total Items"
            }, inplace=True)

            pm1, pm2 = st.columns(2)
            pm1.metric("Total Bills", len(purchase_summary))
            pm2.metric("Total Purchase Value", f"₹{purchase_summary['Purchase Value (₹)'].sum():,.2f}")

            st.dataframe(purchase_summary, use_container_width=True)

            st.markdown("---")
            if st.checkbox("🔍 Show Full Detailed Purchase Log"):
                st.dataframe(filtered_purchase, use_container_width=True)

    with tab_delete:
        st.subheader("🗑️ Database Invoice Deletion Control")
        if user_role == "Manager":
            del_target = st.radio("Select Database Table to Delete From:", ["Sales History", "Purchase History"], horizontal=True)
            conn = sqlite3.connect(DB_FILE)
            
            if del_target == "Sales History":
                s_del_df = pd.read_sql_query("SELECT DISTINCT inv_no FROM sales_history", conn)
                s_invoices = s_del_df["inv_no"].tolist() if not s_del_df.empty else []
                if s_invoices:
                    inv_to_del = st.selectbox("Select Sales Invoice to Delete:", options=s_invoices)
                    if st.button("❌ Permanently Delete Selected Sales Bill"):
                        conn.execute("DELETE FROM sales_history WHERE inv_no = ?", (inv_to_del,))
                        conn.commit()
                        st.success(f"Invoice {inv_to_del} deleted successfully!")
                        st.rerun()
                else:
                    st.info("No Sales Invoices found in Database.")
            else:
                p_del_df = pd.read_sql_query("SELECT DISTINCT inv_no FROM purchase_history", conn)
                p_invoices = p_del_df["inv_no"].tolist() if not p_del_df.empty else []
                if p_invoices:
                    pur_to_del = st.selectbox("Select Purchase Bill to Delete:", options=p_invoices)
                    if st.button("❌ Permanently Delete Selected Purchase Bill"):
                        conn.execute("DELETE FROM purchase_history WHERE inv_no = ?", (pur_to_del,))
                        conn.commit()
                        st.success(f"Purchase Bill {pur_to_del} deleted successfully!")
                        st.rerun()
                else:
                    st.info("No Purchase Records found in Database.")
            conn.close()
        else:
            st.warning("🔒 केवल Manager भूमिका में ही बिल डिलीट करने की अनुमति है।")

# ------------------------------------------
# MODULE 6: MANAGER SALESMAN DASHBOARD (NEW)
# ------------------------------------------
elif active_tab == "📈 Manager Salesman Dashboard":
    st.markdown("<h2 style='color: #E65100;'>📈 Salesman-Wise Performance & Reports Dashboard</h2>", unsafe_allow_html=True)
    
    s_df = load_db_table("sales_history")
    
    if s_df.empty:
        st.info("कोई सेल्स डेटा उपलब्ध नहीं है।")
    else:
        # Salesman Filter
        salesman_list = ["All Salesmen"] + sorted(s_df["salesman"].dropna().unique().tolist())
        selected_sm = st.selectbox("👨‍💼 Select Salesman to Analyze:", options=salesman_list)

        if selected_sm != "All Salesmen":
            filtered_df = s_df[s_df["salesman"] == selected_sm]
        else:
            filtered_df = s_df.copy()

        # Analytics Top Row Metrics
        total_sales_val = filtered_df["net_amt"].sum()
        total_bills_cnt = filtered_df["inv_no"].nunique()
        total_qty_sold = filtered_df["qty"].sum()

        m_col1, m_col2, m_col3 = st.columns(3)
        m_col1.metric("💰 Total Sales Amount", f"₹{total_sales_val:,.2f}")
        m_col2.metric("🧾 Total Bills Generated", total_bills_cnt)
        m_col3.metric("📦 Total Units Sold", f"{total_qty_sold:,.0f}")

        st.markdown("---")

        # Sales Comparison Chart across Salesmen
        st.subheader("📊 Salesman Comparison (Total Sales Value)")
        sm_summary = s_df.groupby("salesman")["net_amt"].sum().reset_index()
        sm_summary.columns = ["Salesman", "Total Sales (₹)"]
        
        st.bar_chart(sm_summary, x="Salesman", y="Total Sales (₹)")

        # Incentive / Commission Calculator Feature for Manager
        st.markdown("---")
        st.subheader("💸 Commission / Incentive Pay-out Calculator")
        comm_col1, comm_col2 = st.columns([1, 2])
        
        with comm_col1:
            comm_rate = st.number_input("Set Commission Rate (%)", min_value=0.0, max_value=50.0, value=2.0, step=0.5)
            calc_comm_amt = (total_sales_val * comm_rate) / 100.0
            st.metric(f"Commission Payable to {selected_sm}", f"₹{calc_comm_amt:,.2f}")

        with comm_col2:
            st.markdown("#### 📋 Breakdown Table")
            if not filtered_df.empty:
                detailed_sm_df = filtered_df.groupby(["inv_no", "date", "party_name"]).agg(
                    Bill_Amount=("net_amt", "sum")
                ).reset_index()
                detailed_sm_df["Commission (₹)"] = (detailed_sm_df["Bill_Amount"] * comm_rate) / 100.0
                st.dataframe(detailed_sm_df, use_container_width=True)
