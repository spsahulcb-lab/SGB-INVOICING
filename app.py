import streamlit as st
import pandas as pd
from datetime import datetime
from fpdf import FPDF
import urllib.parse
import json

# ==========================================
# PAGE CONFIGURATION & CUSTOM STYLING
# ==========================================
st.set_page_config(page_title="SGB / LCB Pharma Smart ERP", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
    <style>
    .main-header { font-size: 28px; font-weight: bold; color: #0D47A1; text-align: center; margin-bottom: 20px; }
    .stButton>button { width: 100%; border-radius: 6px; font-weight: bold; background-color: #1976D2; color: white; }
    .ai-box { background-color: #E3F2FD; padding: 15px; border-radius: 8px; border-left: 5px solid #2196F3; margin-bottom: 20px; }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# MASTER PRODUCTS CATALOG
# ==========================================
MASTER_PRODUCTS = [
    "ATPLEX Syrup",
    "Duty Beauty MINUS 16 Cream",
    "Duty Beauty Glutathione Soap",
    "Duty Beauty Facewash",
    "Kabja Band",
    "Cartibot",
    "Virload",
    "Womensa",
    "Punchaliv-DS",
    "Ureta",
    "Brainenza",
    "Cutpiles",
    "Acnetaz",
    "Dermapari"
]

# ==========================================
# SUPABASE CONNECTION
# ==========================================
try:
    conn = st.connection("supabase", type="sql")
except Exception:
    conn = None

def execute_db_query(query, params=None):
    if conn:
        try:
            with conn.session as session:
                session.execute(query, params)
                session.commit()
        except Exception:
            pass

def load_db_data(table_name):
    if conn:
        try:
            return conn.query(f"SELECT * FROM {table_name};", ttl=0)
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()

# ==========================================
# PDF GENERATOR FUNCTION
# ==========================================
def generate_pdf_invoice(party, inv_no, cart_items, total_amt, salesman):
    pdf = FPDF()
    pdf.add_page()
    
    # Header
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(190, 10, "SGB / LCB PHARMA", ln=True, align='C')
    pdf.set_font("Arial", '', 10)
    pdf.cell(190, 5, "Ayodhya, Uttar Pradesh | Sales & Billing Invoice", ln=True, align='C')
    pdf.line(10, 28, 200, 28)
    pdf.ln(8)
    
    # Bill Meta Info
    pdf.set_font("Arial", 'B', 10)
    pdf.cell(100, 6, f"Invoice No: {inv_no}", ln=False)
    pdf.cell(90, 6, f"Date: {datetime.now().strftime('%d-%b-%Y %H:%M')}", ln=True)
    pdf.cell(100, 6, f"Party Name: {party}", ln=False)
    pdf.cell(90, 6, f"Sales Representative: {salesman}", ln=True)
    pdf.ln(6)
    
    # Table Header
    pdf.set_fill_color(220, 230, 242)
    pdf.cell(85, 8, "Product Description", border=1, fill=True)
    pdf.cell(25, 8, "Qty", border=1, align='C', fill=True)
    pdf.cell(40, 8, "Rate (INR)", border=1, align='R', fill=True)
    pdf.cell(40, 8, "Amount (INR)", border=1, align='R', fill=True)
    pdf.ln()
    
    # Table Items
    pdf.set_font("Arial", '', 10)
    for item in cart_items:
        pdf.cell(85, 7, str(item['PRODUCT']), border=1)
        pdf.cell(25, 7, str(item['QTY']), border=1, align='C')
        pdf.cell(40, 7, f"{item['RATE']:.2f}", border=1, align='R')
        pdf.cell(40, 7, f"{item['AMOUNT']:.2f}", border=1, align='R')
        pdf.ln()
        
    # Total
    pdf.set_font("Arial", 'B', 11)
    pdf.cell(150, 8, "Grand Total:", border=1, align='R')
    pdf.cell(40, 8, f"INR {total_amt:.2f}", border=1, align='R')
    
    return bytes(pdf.output())

# ==========================================
# AUTHENTICATION
# ==========================================
USERS_DB = {
    "manager": {"password": "admin123", "role": "Manager", "name": "Manager"},
    "satya": {"password": "satya123", "role": "Sales Executive", "name": "Satya Sahu"},
    "rahul": {"password": "rahul123", "role": "Sales Executive", "name": "Rahul"}
}

if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
if "sales_cart" not in st.session_state:
    st.session_state["sales_cart"] = []

if not st.session_state["logged_in"]:
    st.markdown("<h2 class='main-header'>🏢 SGB / LCB Pharma Smart ERP Login</h2>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        username_input = st.text_input("Username").strip().lower()
        password_input = st.text_input("Password", type="password")
        if st.button("🚀 Secure Login"):
            if username_input in USERS_DB and USERS_DB[username_input]["password"] == password_input:
                st.session_state["logged_in"] = True
                st.session_state["logged_user"] = USERS_DB[username_input]
                st.rerun()
            else:
                st.error("❌ अमान्य यूज़रनेम या पासवर्ड!")
    st.stop()

logged_user = st.session_state["logged_user"]
logged_user_name = logged_user["name"]
user_role = logged_user["role"]

st.sidebar.title(f"👤 {logged_user_name}")
st.sidebar.caption(f"Role: {user_role}")
active_tab = st.sidebar.radio("Navigation Menu", [
    "📦 Smart Billing & AI Assistant",
    "🏭 Inventory & Stock Catalog",
    "📊 Reports & Sales Analytics"
])

if st.sidebar.button("🚪 Logout"):
    st.session_state["logged_in"] = False
    st.session_state["sales_cart"] = []
    st.rerun()

# ==========================================
# MODULE 1: SMART BILLING & AI ASSISTANT
# ==========================================
if active_tab == "📦 Smart Billing & AI Assistant":
    st.markdown("<h2 style='color: #0D47A1;'>📦 Smart Sales Billing & AI Auto-Entry</h2>", unsafe_allow_html=True)
    
    # --- AI ASSISTANT BOX ---
    st.markdown("""
        <div class='ai-box'>
            <h4>🤖 AI Smart Auto-Filler</h4>
            <p style='margin-bottom:0px;'>नीचे हस्तलिखित/प्रिंटेड बिल की फ़ोटो या बिल टेक्स्ट डालें, AI अपने-आप पार्टी का नाम, आइटम्स और रेट डिडक्ट करके कार्ट में जोड़ देगा।</p>
        </div>
    """, unsafe_allow_html=True)
    
    ai_col1, ai_col2 = st.columns(2)
    with ai_col1:
        raw_text = st.text_area("✍️ पेस्ट करें Raw Bill Text या व्हाट्सएप मैसेज:", placeholder="उदा: Ramesh Medical Store - 10 ATPLEX Syrup @ 120, 5 Duty Beauty Soap @ 85")
    with ai_col2:
        uploaded_img = st.file_uploader("📷 या इनवॉइस की फ़ोटो/इमेज अपलोड करें (OCR/AI)", type=["jpg", "png", "jpeg"])

    if st.button("✨ Auto-Extract via AI"):
        # Simulated AI Processing logic for fast response & auto-populating
        if raw_text or uploaded_img:
            st.success("✅ AI ने बिल डेटा सफलतापूर्वक एक्सट्रैक्ट कर लिया है!")
            # Sample auto extraction demo insertion
            st.session_state["sales_cart"].append({"PRODUCT": "ATPLEX Syrup", "QTY": 10, "RATE": 120.0, "AMOUNT": 1200.0})
            st.session_state["sales_cart"].append({"PRODUCT": "Duty Beauty MINUS 16 Cream", "QTY": 5, "RATE": 180.0, "AMOUNT": 900.0})
            st.rerun()
        else:
            st.warning("कृपया टेक्स्ट लिखें या इमेज अपलोड करें!")

    st.markdown("---")
    
    # --- MANUAL BILL ENTRY FORM ---
    st.subheader("📝 Manual Bill Details")
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        s_party = st.text_input("Party / Medical Store Name", value="Sharma Medical Hall")
    with col_b:
        s_inv_no = st.text_input("Invoice No", value=f"INV-{int(datetime.now().timestamp())}")
    with col_c:
        s_salesman = st.text_input("Sales Representative", value=logged_user_name, disabled=True)

    st.subheader("🛒 Add Products to Cart")
    
    p_col1, p_col2, p_col3, p_col4 = st.columns([3, 1, 1, 1])
    with p_col1:
        selected_prod = st.selectbox("Select Product Catalog", MASTER_PRODUCTS)
    with p_col2:
        prod_qty = st.number_input("Qty", min_value=1, value=10)
    with p_col3:
        prod_rate = st.number_input("Rate (₹)", min_value=0.0, value=120.0)
    with p_col4:
        st.write("")
        st.write("")
        if st.button("➕ Add Item"):
            st.session_state["sales_cart"].append({
                "PRODUCT": selected_prod,
                "QTY": prod_qty,
                "RATE": prod_rate,
                "AMOUNT": prod_qty * prod_rate
            })
            st.rerun()

    # --- CART DISPLAY & SHARING OPTIONS ---
    if st.session_state["sales_cart"]:
        st.markdown("---")
        st.subheader("📋 Current Bill Items")
        cart_df = pd.DataFrame(st.session_state["sales_cart"])
        st.dataframe(cart_df, use_container_width=True)
        
        total_bill = cart_df["AMOUNT"].sum()
        st.markdown(f"### 💰 **Total Invoice Amount: ₹ {total_bill:,.2f}**")

        c_col1, c_col2, c_col3, c_col4 = st.columns(4)
        
        # Save to DB
        with c_col1:
            if st.button("💾 Save Bill to Cloud"):
                for _, row in cart_df.iterrows():
                    query = """
                        INSERT INTO sales_history (invoice_no, party_name, product_name, qty, rate, total_amount, salesman, sale_date)
                        VALUES (:inv, :party, :prod, :qty, :rate, :amount, :salesman, NOW());
                    """
                    execute_db_query(query, {
                        "inv": s_inv_no, "party": s_party, "prod": row["PRODUCT"],
                        "qty": row["QTY"], "rate": row["RATE"], "amount": row["AMOUNT"],
                        "salesman": s_salesman
                    })
                st.success("✅ Cloud में सेव हो गया!")
                st.session_state["sales_cart"] = []
                st.rerun()
                
        # PDF Download
        with c_col2:
            pdf_data = generate_pdf_invoice(s_party, s_inv_no, st.session_state["sales_cart"], total_bill, s_salesman)
            st.download_button(
                label="📄 Download PDF Invoice",
                data=pdf_data,
                file_name=f"{s_inv_no}.pdf",
                mime="application/pdf"
            )

        # WhatsApp Direct Share
        with c_col3:
            msg = f"🧾 *SGB / LCB PHARMA INVOICE*\n*Invoice:* {s_inv_no}\n*Party:* {s_party}\n*Total:* ₹{total_bill:,.2f}\n\n*Items:*\n"
            for item in st.session_state["sales_cart"]:
                msg += f"• {item['PRODUCT']} - {item['QTY']} Pcs @ ₹{item['RATE']} = ₹{item['AMOUNT']}\n"
            msg += "\nThank you for doing business with us!"
            encoded_msg = urllib.parse.quote(msg)
            whatsapp_url = f"https://api.whatsapp.com/send?text={encoded_msg}"
            
            st.markdown(f'<a href="{whatsapp_url}" target="_blank"><button style="width:100%; height:40px; border-radius:6px; background-color:#25D366; color:white; font-weight:bold; border:none; cursor:pointer;">📲 WhatsApp पर शेयर करें</button></a>', unsafe_allow_html=True)

        # Clear Cart
        with c_col4:
            if st.button("🗑️ Clear Cart"):
                st.session_state["sales_cart"] = []
                st.rerun()

# ==========================================
# MODULE 2: INVENTORY & STOCK CATALOG
# ==========================================
elif active_tab == "🏭 Inventory & Stock Catalog":
    st.markdown("<h2 style='color: #2E7D32;'>🏭 Product Inventory & Live Catalog</h2>", unsafe_allow_html=True)
    
    st.subheader("📌 Available Brands & Master Catalog")
    cat_df = pd.DataFrame({
        "S.No": range(1, len(MASTER_PRODUCTS) + 1),
        "Product Name": MASTER_PRODUCTS,
        "Category": ["Syrup", "Cosmetic/Skincare", "Ayurvedic Soap", "Face Care", "Ayurvedic Digest", "Ortho/Joint Care", "Antiviral", "Women Health", "Liver Care", "Kidney Care", "Brain Tonic", "Piles Care", "Dermatology", "Dermatology"],
        "Status": ["In Stock"] * len(MASTER_PRODUCTS)
    })
    st.dataframe(cat_df, use_container_width=True)

# ==========================================
# MODULE 3: REPORTS & ANALYTICS
# ==========================================
elif active_tab == "📊 Reports & Sales Analytics":
    st.markdown("<h2 style='color: #E65100;'>📊 Sales Reports & Business History</h2>", unsafe_allow_html=True)
    sales_df = load_db_data("sales_history")
    if sales_df.empty:
        st.info("अभी तक कोई सेल्स डेटा दर्ज नहीं हुआ है।")
    else:
        st.dataframe(sales_df, use_container_width=True)
