import streamlit as st
import pandas as pd
from datetime import datetime
from fpdf import FPDF

# Page Configuration
st.set_page_config(page_title="SGB / LCB Pharma ERP", layout="wide")

st.title("🏢 SGB / LCB Pharma ERP")

# Session State Initializations
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
if "cart" not in st.session_state:
    st.session_state["cart"] = []

# Supabase Connection Helper
try:
    conn = st.connection("supabase", type="sql")
except Exception:
    conn = None

def run_query(query, params=None):
    if conn:
        try:
            with conn.session as session:
                session.execute(query, params)
                session.commit()
        except Exception:
            pass

def fetch_data(table_name):
    if conn:
        try:
            return conn.query(f"SELECT * FROM {table_name};", ttl=0)
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()

# Login Management
if not st.session_state["logged_in"]:
    st.subheader("🔑 User Login")
    user = st.text_input("Username").strip().lower()
    pwd = st.text_input("Password", type="password")
    
    if st.button("Login"):
        if (user == "admin" and pwd == "admin123") or (user == "rahul" and pwd == "rahul123") or (user == "satya" and pwd == "satya123"):
            st.session_state["logged_in"] = True
            st.session_state["username"] = user
            st.rerun()
        else:
            st.error("गलत युजरनेम या पासवर्ड")
    st.stop()

# Sidebar Navigation
st.sidebar.write(f"Logged in as: **{st.session_state.get('username', 'User')}**")
menu = st.sidebar.radio("Navigation", ["📦 Sales & Billing", "🏭 Inventory / Stock", "📊 Sales Reports"])

if st.sidebar.button("Logout"):
    st.session_state["logged_in"] = False
    st.rerun()

# 1. SALES & BILLING MODULE
if menu == "📦 Sales & Billing":
    st.header("📦 Sales & Billing Entry")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        party = st.text_input("Party / Customer Name")
    with col2:
        inv_no = st.text_input("Invoice No", value=f"INV-{int(datetime.now().timestamp())}")
    with col3:
        salesman = st.text_input("Salesman", value=st.session_state.get('username', 'Salesman'))

    st.subheader("🛒 Add Items")

    products = ["ATPLEX Syrup", "Duty Beauty MINUS 16 Cream", "Duty Beauty Soap", "Kabja Band", "Cartibot", "Virload", "Womensa", "Punchaliv-DS", "Ureta", "Brainenza", "Cutpiles", "Acnetaz", "Dermapari"]
    
    p1, p2, p3, p4 = st.columns([3, 1, 1, 1])
    with p1:
        p_name = st.selectbox("Select Product", products)
    with p2:
        qty = st.number_input("Qty", min_value=1, value=1)
    with p3:
        rate = st.number_input("Rate (₹)", min_value=0.0, value=120.0)
    with p4:
        st.write("")
        st.write("")
        if st.button("Add Item"):
            st.session_state["cart"].append({
                "Product": p_name,
                "Qty": qty,
                "Rate": rate,
                "Total": qty * rate
            })
            st.rerun()

    if st.session_state["cart"]:
        df_cart = pd.DataFrame(st.session_state["cart"])
        st.table(df_cart)
        total_val = df_cart["Total"].sum()
        st.markdown(f"### **Total Amount: ₹ {total_val:,.2f}**")
        
        c1, c2 = st.columns(2)
        with c1:
            if st.button("💾 Save Bill"):
                if party:
                    for item in st.session_state["cart"]:
                        q = "INSERT INTO sales_history (invoice_no, party_name, product_name, qty, rate, total_amount, salesman, sale_date) VALUES (:inv, :party, :prod, :qty, :rate, :tot, :sm, NOW());"
                        run_query(q, {"inv": inv_no, "party": party, "prod": item["Product"], "qty": item["Qty"], "rate": item["Rate"], "tot": item["Total"], "sm": salesman})
                    st.success("Bill Saved!")
                    st.session_state["cart"] = []
                    st.rerun()
                else:
                    st.warning("Please enter Party Name")
        with c2:
            if st.button("🗑️ Clear"):
                st.session_state["cart"] = []
                st.rerun()

# 2. INVENTORY MODULE
elif menu == "🏭 Inventory / Stock":
    st.header("🏭 Live Stock")
    inv_df = fetch_data("products")
    if not inv_df.empty:
        st.dataframe(inv_df)
    else:
        st.info("No Stock Data found in Supabase table 'products'.")

# 3. REPORTS MODULE
elif menu == "📊 Sales Reports":
    st.header("📊 Sales History")
    rep_df = fetch_data("sales_history")
    if not rep_df.empty:
        st.dataframe(rep_df)
    else:
        st.info("No Sales Data found in Supabase table 'sales_history'.")
