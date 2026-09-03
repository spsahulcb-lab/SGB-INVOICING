import streamlit as st
import pandas as pd
from datetime import datetime

# ==========================================
# PAGE CONFIG & STYLING
# ==========================================
st.set_page_config(page_title="Pharma ERP System", layout="wide", initial_sidebar_state="expanded")

# Custom CSS for UI Enhancement
st.markdown("""
    <style>
    .main-header { font-size: 26px; font-weight: bold; color: #1E88E5; text-align: center; margin-bottom: 20px; }
    .card { background-color: #f8f9fa; padding: 15px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
    .stButton>button { width: 100%; border-radius: 5px; font-weight: bold; }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# SUPABASE DATABASE CONNECTION
# ==========================================
# Streamlit secrets.toml se credentials automatially fetch honge
conn = st.connection("supabase", type="sql")

def load_db_table(table_name):
    """Supabase Table se Live Data fetch karne ke liye"""
    try:
        return conn.query(f"SELECT * FROM {table_name};", ttl=0)
    except Exception as e:
        return pd.DataFrame()

def execute_db_query(query, params=None):
    """Supabase me Data Insert / Update karne ke liye"""
    with conn.session as session:
        session.execute(query, params)
        session.commit()

# ==========================================
# USER AUTHENTICATION & DATABASE SETUP
# ==========================================
USERS_DB = {
    "manager": {"password": "admin123", "role": "Manager", "name": "Manager"},
    "rahul": {"password": "rahul123", "role": "Sales Executive", "name": "Rahul"},
    "satya": {"password": "satya123", "role": "Sales Executive", "name": "Satya"},
    "sales1": {"password": "sales123", "role": "Sales Executive", "name": "Sales1"}
}

if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
    st.session_state["logged_user"] = None
if "sales_cart" not in st.session_state:
    st.session_state["sales_cart"] = []

# ==========================================
# LOGIN SCREEN
# ==========================================
if not st.session_state["logged_in"]:
    st.markdown("<h2 class='main-header'>🏢 Pharma ERP Management System</h2>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.subheader("🔑 System Login")
        username_input = st.text_input("Username").strip().lower()
        password_input = st.text_input("Password", type="password")
        
        if st.button("🚀 Login"):
            if username_input in USERS_DB and USERS_DB[username_input]["password"] == password_input:
                st.session_state["logged_in"] = True
                st.session_state["logged_user"] = USERS_DB[username_input]
                st.success(f"Welcome {USERS_DB[username_input]['name']}!")
                st.rerun()
            else:
                st.error("❌ Invalid Username or Password")
    st.stop()

# Current User Info
logged_user = st.session_state["logged_user"]
logged_user_name = logged_user["name"]
user_role = logged_user["role"]

# Sidebar Navigation
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
        # Strictly Assign Salesman
        if user_role == "Manager":
            s_salesman = st.selectbox("Assign Salesman", [v["name"] for k, v in USERS_DB.items() if v["role"] != "Manager"])
        else:
            s_salesman = logged_user_name
            st.text_input("Salesman", value=logged_user_name, disabled=True)

    st.markdown("---")
    st.subheader("🛒 Add Items to Cart")
    
    # Load Products from Supabase
    stock_df = load_db_table("products")
    product_list = stock_df["product_name"].tolist() if not stock_df.empty else ["ATPLEX Syrup", "Duty Beauty Cream", "Kabja Band"]
    
    p_col1, p_col2, p_col3, p_col4 = st.columns([3, 1, 1, 1])
    with p_col1:
        selected_prod = st.selectbox("Select Product", product_list)
    with p_col2:
        prod_qty = st.number_input("Qty", min_value=1, value=1)
    with p_col3:
        prod_rate = st.number_input("Rate (₹)", min_value=0.0, value=100.0)
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

    # Cart Table
    if st.session_state["sales_cart"]:
        cart_df = pd.DataFrame(st.session_state["sales_cart"])
        st.dataframe(cart_df, use_container_width=True)
        total_bill = cart_df["AMOUNT"].sum()
        st.markdown(f"### 💰 **Total Amount: ₹ {total_bill:,.2f}**")

        if st.button("💾 Save Bill to Supabase"):
            if not s_party.strip():
                st.error("⚠️ Please enter Party Name")
            else:
                for _, row in cart_df.iterrows():
                    query = """
                        INSERT INTO sales_history (invoice_no, party_name, product_name, qty, rate, total_amount, salesman, sale_date)
                        VALUES (:inv, :party, :prod, :qty, :rate, :amount, :salesman, NOW());
                    """
                    params = {
                        "inv": s_inv_no,
                        "party": s_party,
                        "prod": row["PRODUCT"],
                        "qty": row["QTY"],
                        "rate": row["RATE"],
                        "amount": row["AMOUNT"],
                        "salesman": s_salesman
                    }
                    execute_db_query(query, params)
                
                st.success("✅ Sales Bill Saved Successfully in Supabase!")
                st.session_state["sales_cart"] = []
                st.rerun()

# ==========================================
# MODULE 2: INVENTORY & STOCK
# ==========================================
elif active_tab == "🏭 Inventory & Stock":
    st.markdown("<h2 style='color: #2E7D32;'>🏭 Inventory Management</h2>", unsafe_allow_html=True)
    
    st.subheader("📌 Current Product Stock")
    stock_df = load_db_table("products")
    if not stock_df.empty:
        st.dataframe(stock_df, use_container_width=True)
    else:
        st.info("No stock data available in Supabase.")

    if user_role == "Manager":
        st.markdown("---")
        st.subheader("➕ Add New Product")
        with st.form("add_product_form"):
            new_prod_name = st.text_input("Product Name")
            new_prod_stock = st.number_input("Initial Stock", min_value=0, value=100)
            new_prod_price = st.number_input("Base Price (₹)", min_value=0.0, value=50.0)
            submit_prod = st.form_submit_button("Add Product")

            if submit_prod and new_prod_name.strip():
                query = """
                    INSERT INTO products (product_name, stock, price)
                    VALUES (:pname, :pstock, :pprice);
                """
                execute_db_query(query, {"pname": new_prod_name, "pstock": new_prod_stock, "pprice": new_prod_price})
                st.success(f"Product '{new_prod_name}' added successfully!")
                st.rerun()

# ==========================================
# MODULE 3: REPORTS & STATEMENTS
# ==========================================
elif active_tab == "📊 Reports & Statements":
    st.markdown("<h2 style='color: #E65100;'>📊 Sales Reports & History</h2>", unsafe_allow_html=True)
    
    sales_df = load_db_table("sales_history")

    if sales_df.empty:
        st.info("No sales records found.")
    else:
        # Filter Logic based on Role
        if user_role != "Manager":
            # Exact Case-Insensitive Filter for Salesmen
            sales_df["salesman_clean"] = sales_df["salesman"].astype(str).str.strip().str.lower()
            current_user_clean = str(logged_user_name).strip().lower()
            sales_df = sales_df[sales_df["salesman_clean"] == current_user_clean]
            sales_df = sales_df.drop(columns=["salesman_clean"])

        st.markdown(f"**Showing Records for:** `{logged_user_name}`" if user_role != "Manager" else "**Showing All Records (Manager Access)**")
        st.dataframe(sales_df, use_container_width=True)

        # Summary Metrics
        if not sales_df.empty:
            st.markdown("---")
            m1, m2, m3 = st.columns(3)
            m1.metric("Total Bills", len(sales_df["invoice_no"].unique()))
            m2.metric("Total Quantity Sold", int(sales_df["qty"].sum()))
            m3.metric("Total Revenue", f"₹ {sales_df['total_amount'].sum():,.2f}")
