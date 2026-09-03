import streamlit as st
import pandas as pd
from datetime import datetime
from fpdf import FPDF

# ==========================================
# PAGE CONFIG & STYLING
# ==========================================
st.set_page_config(page_title="SGB / LCB Pharma ERP", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
    <style>
    .main-header { font-size: 26px; font-weight: bold; color: #1E88E5; text-align: center; margin-bottom: 20px; }
    .stButton>button { width: 100%; border-radius: 5px; font-weight: bold; }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# HARDCODED MASTER PRODUCTS CATALOG
# ==========================================
DEFAULT_PRODUCTS = [
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
# DATABASE CONNECTION (SUPABASE)
# ==========================================
try:
    conn = st.connection("supabase", type="sql")
except Exception:
    conn = None

def load_db_table(table_name):
    if conn:
        try:
            return conn.query(f"SELECT * FROM {table_name};", ttl=0)
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()

def execute_db_query(query, params=None):
    if conn:
        try:
            with conn.session as session:
                session.execute(query, params)
                session.commit()
        except Exception:
            pass

# ==========================================
# PDF GENERATOR FUNCTION
# ==========================================
def generate_pdf_invoice(party, inv_no, cart_items, total_amt, salesman):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(190, 10, "SGB / LCB PHARMA INVOICE", ln=True, align='C')
    pdf.set_font("Arial", '', 10)
    pdf.cell(190, 5, "Sales & Billing Receipt", ln=True, align='C')
    pdf.line(10, 28, 200, 28)
    pdf.ln(10)
    
    pdf.set_font("Arial", 'B', 10)
    pdf.cell(100, 6, f"Invoice No: {inv_no}", ln=False)
    pdf.cell(90, 6, f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}", ln=True)
    pdf.cell(100, 6, f"Party Name: {party}", ln=False)
    pdf.cell(90, 6, f"Salesman: {salesman}", ln=True)
    pdf.ln(6)
    
    pdf.set_fill_color(230, 230, 230)
    pdf.cell(80, 8, "Product Name", border=1, fill=True)
    pdf.cell(30, 8, "Qty", border=1, align='C', fill=True)
    pdf.cell(40, 8, "Rate (INR)", border=1, align='R', fill=True)
    pdf.cell(40, 8, "Amount (INR)", border=1, align='R', fill=True)
    pdf.ln()
    
    pdf.set_font("Arial", '', 10)
    for item in cart_items:
        pdf.cell(80, 7, str(item['PRODUCT']), border=1)
        pdf.cell(30, 7, str(item['QTY']), border=1, align='C')
        pdf.cell(40, 7, f"{item['RATE']:.2f}", border=1, align='R')
        pdf.cell(40, 7, f"{item['AMOUNT']:.2f}", border=1, align='R')
        pdf.ln()
        
    pdf.set_font("Arial", 'B', 11)
    pdf.cell(150, 8, "Total Payable Amount:", border=1, align='R')
    pdf.cell(40, 8, f"INR {total_amt:.2f}", border=1, align='R')
    return bytes(pdf.output())

# ==========================================
# AUTHENTICATION & LOGIN
# ==========================================
USERS_DB = {
    "manager": {"password": "admin123", "role": "Manager", "name": "Manager"},
    "rahul": {"password": "rahul123", "role": "Sales Executive", "name": "Rahul"},
    "satya": {"password": "satya123", "role": "Sales Executive", "name": "Satya"}
}

if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
    st.session_state["logged_user"] = None
if "sales_cart" not in st.session_state:
    st.session_state["sales_cart"] = []

if not st.session_state["logged_in"]:
    st.markdown("<h2 class='main-header'>🏢 SGB / LCB Pharma ERP</h2>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        username_input = st.text_input("Username").strip().lower()
        password_input = st.text_input("Password", type="password")
        if st.button("🚀 Login"):
            if username_input in USERS_DB and USERS_DB[username_input]["password"] == password_input:
                st.session_state["logged_in"] = True
                st.session_state["logged_user"] = USERS_DB[username_input]
                st.rerun()
            else:
                st.error("❌ Invalid Credentials")
    st.stop()

logged_user = st.session_state["logged_user"]
logged_user_name = logged_user["name"]
user_role = logged_user["role"]

st.sidebar.title(f"👤 {logged_user_name}")
st.sidebar.caption(f"Role: {user_role}")
active_tab = st.sidebar.radio("Navigation", [
    "📦 Billing & Sales",
    "🏭 Inventory & Stock",
    "📊 Reports & Statements"
])

if st.sidebar.button("🚪 Logout"):
    st.session_state["logged_in"] = False
    st.session_state["logged_user"] = None
    st.rerun()

# ==========================================
# MODULE 1: BILLING & SALES
# ==========================================
if active_tab == "📦 Billing & Sales":
    st.markdown("<h2 style='color: #1E88E5;'>📦 Sales & Billing Entry</h2>", unsafe_allow_html=True)
    
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        s_party = st.text_input("Party / Customer Name")
    with col_b:
        s_inv_no = st.text_input("Invoice No", value=f"INV-{int(datetime.now().timestamp())}")
    with col_c:
        if user_role == "Manager":
            s_salesman = st.selectbox("Assign Salesman", [v["name"] for k, v in USERS_DB.items() if v["role"] != "Manager"])
        else:
            s_salesman = logged_user_name
            st.text_input("Salesman", value=logged_user_name, disabled=True)

    st.markdown("---")
    st.subheader("🛒 Add Items to Cart")
    
    stock_df = load_db_table("products")
    if not stock_df.empty and "product_name" in stock_df.columns:
        product_list = stock_df["product_name"].tolist()
    else:
        product_list = DEFAULT_PRODUCTS
    
    p_col1, p_col2, p_col3, p_col4 = st.columns([3, 1, 1, 1])
    with p_col1:
        selected_prod = st.selectbox("Select Product", product_list)
    with p_col2:
        prod_qty = st.number_input("Qty", min_value=1, value=1)
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

    if st.session_state["sales_cart"]:
        cart_df = pd.DataFrame(st.session_state["sales_cart"])
        st.dataframe(cart_df, use_container_width=True)
        total_bill = cart_df["AMOUNT"].sum()
        st.markdown(f"### 💰 **Total Amount: ₹ {total_bill:,.2f}**")

        c_col1, c_col2, c_col3 = st.columns(3)
        with c_col1:
            if st.button("💾 Save Bill to Supabase"):
                if not s_party.strip():
                    st.error("⚠️ Please enter Party Name")
                else:
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
                    st.success("✅ Saved to Central Database!")
                    st.session_state["sales_cart"] = []
                    st.rerun()
        with c_col2:
            pdf_data = generate_pdf_invoice(s_party, s_inv_no, st.session_state["sales_cart"], total_bill, s_salesman)
            st.download_button(
                label="📄 Download PDF Invoice",
                data=pdf_data,
                file_name=f"{s_inv_no}.pdf",
                mime="application/pdf"
            )
        with c_col3:
            if st.button("🗑️ Clear Cart"):
                st.session_state["sales_cart"] = []
                st.rerun()

# ==========================================
# MODULE 2: INVENTORY & STOCK
# ==========================================
elif active_tab == "🏭 Inventory & Stock":
    st.markdown("<h2 style='color: #2E7D32;'>🏭 Inventory Management</h2>", unsafe_allow_html=True)
    stock_df = load_db_table("products")
    if not stock_df.empty:
        st.dataframe(stock_df, use_container_width=True)
    else:
        st.dataframe(pd.DataFrame({"Product Name": DEFAULT_PRODUCTS}), use_container_width=True)

# ==========================================
# MODULE 3: REPORTS & STATEMENTS
# ==========================================
elif active_tab == "📊 Reports & Statements":
    st.markdown("<h2 style='color: #E65100;'>📊 Reports & Sales History</h2>", unsafe_allow_html=True)
    sales_df = load_db_table("sales_history")
    if sales_df.empty:
        st.info("No sales history recorded yet.")
    else:
        st.dataframe(sales_df, use_container_width=True)
