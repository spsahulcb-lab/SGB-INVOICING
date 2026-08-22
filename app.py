import sqlite3
import urllib.parse
import json
from PIL import Image
import pandas as pd
import streamlit as st
import google.generativeai as genai

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
    p_df = pd.read_sql_query("SELECT DISTINCT product, hsn, batch, exp, mrp, rate FROM purchase_history", conn)
    s_df = pd.read_sql_query("SELECT DISTINCT product, hsn, batch, exp, mrp, rate FROM sales_history", conn)
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
            
            if p_name:
                display_label = f"{p_name} | BATCH: {batch} | MRP: ₹{mrp}" if batch else p_name
                options_list.append(display_label)
                batch_map[display_label] = {
                    "product_name": p_name, "hsn": hsn, "batch": batch, "exp": exp, "mrp": mrp, "rate": rate
                }

    defaults = [
        {"product_name": "GASMIT-DSR CAPS 1x10", "hsn": "3004", "batch": "WEB/05/063D", "exp": "04-28", "mrp": 109.00, "rate": 80.25},
        {"product_name": "PANEC-P TAB 1x10", "hsn": "3004", "batch": "D6DT031", "exp": "03-28", "mrp": 56.00, "rate": 44.80},
        {"product_name": "ALOBYD-SP TAB", "hsn": "3004", "batch": "AB-102", "exp": "12-27", "mrp": 95.00, "rate": 72.38}
    ]
    for item in defaults:
        label = f"{item['product_name']} | BATCH: {item['batch']} | MRP: ₹{item['mrp']}"
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

# ==========================================
# 2. APP CONFIG & ORANGE-WHITE THEME (CSS)
# ==========================================
st.set_page_config(
    page_title="Pharma ERP - Orange Theme", 
    layout="wide", 
    page_icon="💊",
    initial_sidebar_state="collapsed"
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
        font-size: 16px !important;
        padding: 10px 16px !important;
        border-radius: 8px !important;
        border: none !important;
        box-shadow: 0 4px 6px rgba(255, 111, 0, 0.2);
    }
    .stButton>button:hover {
        background: #E65100 !important;
    }

    div[data-testid="stMetric"] {
        background-color: #FFFFFF !important;
        padding: 15px !important;
        border-radius: 10px !important;
        border: 1px solid #FFE0B2 !important;
        border-left: 6px solid #FF6F00 !important;
        box-shadow: 0px 2px 8px rgba(0,0,0,0.05) !important;
    }
    
    div[data-testid="stMetricLabel"] {
        color: #E65100 !important;
        font-weight: bold;
    }

    input:focus, select:focus {
        border-color: #FF6F00 !important;
        box-shadow: 0 0 5px rgba(255, 111, 0, 0.5) !important;
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
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
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
# 3. SIDEBAR NAVIGATION
# ==========================================
st.sidebar.title("💊 Pharma ERP Menu")
user_role = st.sidebar.radio("👤 Choose Role:", ["Sales Executive", "Manager"])
user_name = st.sidebar.text_input("✍️ Enter Your Name:", value="Rahul")

active_tab = st.selectbox("📌 Select Module:", [
    "🧾 Sales Invoice (Format)", 
    "📷 AI Bill Scanner", 
    "📦 Purchase Entry", 
    "📦 Live Stock Inventory", 
    "📊 Reports & Statements"
])

# ------------------------------------------
# MODULE 1: SALES INVOICE
# ------------------------------------------
if active_tab == "🧾 Sales Invoice (Format)":
    st.markdown("<h2 style='color: #E65100;'>🧾 New Sales Invoice</h2>", unsafe_allow_html=True)

    customers = get_existing_customers()
    batch_options, batch_map = get_available_batch_products()

    c1, c2 = st.columns([2, 1])
    with c1:
        s_party = st.selectbox("Billed To (Type to filter):", options=["+ Add New Customer"] + customers)
        if s_party == "+ Add New Customer":
            s_party = st.text_input("Enter New Customer Name:", "DR.S.V.SINGH")
    with c2:
        s_inv_no = st.text_input("NO. / Invoice No.", f"{pd.Timestamp.now().strftime('%H%M%S')}")

    if "sales_cart" not in st.session_state:
        st.session_state["sales_cart"] = []

    st.markdown("---")
    st.markdown("<h4 style='color: #FF6F00;'>⚡ Quick Item Selector</h4>", unsafe_allow_html=True)

    with st.form(key="add_item_form", clear_on_submit=False):
        selected_prod_label = st.selectbox("🔍 Search & Select Product [Batch | MRP]:", options=batch_options)
        selected_details = batch_map.get(selected_prod_label, {})

        col_inputs = st.columns([1, 1, 1, 1])
        with col_inputs[0]:
            input_qty = st.number_input("QTY (मात्रा)", min_value=0.0, value=10.0, step=1.0)
        with col_inputs[1]:
            input_bonus = st.number_input("Deal / Bonus", min_value=0.0, value=0.0, step=1.0)
        with col_inputs[2]:
            input_disc = st.number_input("DIS % (छूट)", min_value=0.0, value=0.0, step=0.5)
        with col_inputs[3]:
            st.write(" ")
            st.write(" ")
            submit_button = st.form_submit_button(label="➕ Add Item (Press Enter)")

        if submit_button:
            if selected_prod_label and input_qty > 0:
                st.session_state["sales_cart"].append({
                    "HSN": selected_details.get("hsn", "3004"),
                    "PRODUCT": selected_details.get("product_name", ""),
                    "QTY": input_qty,
                    "BONUS": input_bonus,
                    "RATE": selected_details.get("rate", 0.0),
                    "DIS %": input_disc,
                    "Gst%": 5.0,
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

    # num_rows="dynamic" allows row deletion via checkbox/selection
    edited_sales = st.data_editor(cart_df, num_rows="dynamic", use_container_width=True, key="sales_data_editor")
    
    # Sync edited data back to cart
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
    col_btn1, col_btn2, col_btn3 = st.columns([2, 2, 1])
    with col_btn1:
        if st.button("💾 Save Bill"):
            valid_items = calc_sales_df[(calc_sales_df["PRODUCT"].astype(str).str.strip() != "") & (calc_sales_df["QTY"] > 0)].copy()
            if not valid_items.empty:
                save_sales_to_db(valid_items, s_party, s_inv_no, user_name)
                st.success("✅ Sales Bill Saved Successfully!")
                st.session_state["sales_cart"] = []
                st.rerun()
            else:
                st.warning("कृपया QTY दर्ज करें।")

    with col_btn2:
        raw_msg = f"नमस्कार {s_party},\n\nआपका बिल नंबर *{s_inv_no}* तैयार है।\nNET PAYABLE Amount: *₹{total_amount:,.2f}*।\n\nधन्यवाद!"
        wa_url = f"https://api.whatsapp.com/send?text={urllib.parse.quote(raw_msg)}"
        st.markdown(f"<a href='{wa_url}' target='_blank'>📲 WhatsApp Par Bheje</a>", unsafe_allow_html=True)

    with col_btn3:
        if st.button("🗑️ Clear Table"):
            st.session_state["sales_cart"] = []
            st.rerun()

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
                        save_purchase_to_db(valid_scanned, party_name, inv_no, user_name)
                        st.success("🎉 पर्ची Purchase History में सेव हो गई!")
                        del st.session_state["scanned_data"]
                        st.rerun()

            with col2:
                if st.button("🧾 Save as Sales Bill"):
                    valid_scanned = edited_scanned[(edited_scanned["PRODUCT"].astype(str).str.strip() != "") & (edited_scanned["QTY"] > 0)].copy()
                    if not valid_scanned.empty:
                        save_sales_to_db(valid_scanned, party_name, inv_no, user_name)
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
                save_purchase_to_db(valid_p, p_party, p_inv_no, user_name)
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
    
    tab_sales, tab_purchase = st.tabs(["📈 Sales Statement", "🛒 Purchase Statement"])

    with tab_sales:
        st.subheader("🧾 Sales Summary Statement")
        s_df = load_db_table("sales_history")
        
        if s_df.empty:
            st.info("कोई सेल रिकॉर्ड उपलब्ध नहीं है।")
        else:
            s_customers = ["ALL Customers"] + sorted(s_df["party_name"].unique().tolist())
            selected_cust = st.selectbox("👤 Filter Sales by Customer:", options=s_customers, key="sales_cust_filter")

            filtered_sales = s_df if selected_cust == "ALL Customers" else s_df[s_df["party_name"] == selected_cust]

            sales_summary = filtered_sales.groupby(["inv_no", "date", "party_name"]).agg(
                Sales_Value=("net_amt", "sum"),
                Total_Items=("product", "count")
            ).reset_index()

            sales_summary.rename(columns={
                "inv_no": "Sales Invoice No",
                "date": "Date",
                "party_name": "Party Name",
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
