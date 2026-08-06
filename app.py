import streamlit as st
import pandas as pd
import os

st.set_page_config(page_title="Pharma Stock & Billing App", layout="wide")

# File path for inventory database
STOCK_FILE = "master_stock_inventory.csv"

# Load or Initialize Stock Database
if not os.path.exists(STOCK_FILE):
    df_init = pd.DataFrame({
        "Product Name": ["AGEXPRO PWD", "ALOBYD-SP", "AMTEGUM SYP", "B-RICH TAB", "LIVENZY SYP", "LYMORUS"],
        "MRP (₹)": [249.00, 95.00, 82.50, 92.00, 169.00, 136.53],
        "Available Stock": [100, 150, 80, 200, 120, 90]
    })
    df_init.to_csv(STOCK_FILE, index=False)

def get_stock():
    return pd.read_csv(STOCK_FILE)

def update_stock(product_name, qty_change):
    df = get_stock()
    if product_name in df['Product Name'].values:
        df.loc[df['Product Name'] == product_name, 'Available Stock'] += qty_change
        df.to_csv(STOCK_FILE, index=False)

# App Navigation Menu
st.title("💊 LCB Pharma - Sales, Purchase & Stock App")
menu = st.sidebar.radio("Navigation Menu", ["📦 Stock Inventory", "🛍️ Purchase Entry (Stock IN)", "🧾 Sales Billing (Stock OUT)", "📸 AI Photo Scanner"])

# 1. STOCK INVENTORY VIEW
if menu == "📦 Stock Inventory":
    st.subheader("Current Stock Register")
    df_stock = get_stock()
    st.dataframe(df_stock, use_container_width=True)

# 2. PURCHASE ENTRY
elif menu == "🛍️ Purchase Entry (Stock IN)":
    st.subheader("Add Purchase / Stock Inward")
    df_stock = get_stock()
    selected_prod = st.selectbox("Select Product", df_stock['Product Name'])
    purch_qty = st.number_input("Purchase Quantity", min_value=1, value=10)
    
    if st.button("Add Stock"):
        update_stock(selected_prod, purch_qty)
        st.success(f"Successfully added {purch_qty} units to {selected_prod}!")

# 3. SALES BILLING
elif menu == "🧾 Sales Billing (Stock OUT)":
    st.subheader("Generate Sales Bill & Deduct Stock")
    df_stock = get_stock()
    party_name = st.text_input("Party / Customer Name", "Ayansh M/S")
    selected_prod = st.selectbox("Select Product to Sell", df_stock['Product Name'])
    sale_qty = st.number_input("Sale Quantity", min_value=1, value=5)
    discount = st.slider("Discount (%)", 0, 50, 40)
    
    if st.button("Generate Bill & Deduct Stock"):
        update_stock(selected_prod, -sale_qty)
        st.success(f"Bill created for {party_name}! {sale_qty} units deducted from {selected_prod}.")

# 4. AI PHOTO SCANNER
elif menu == "📸 AI Photo Scanner":
    st.subheader("Scan Handwritten Bill with Gemini AI")
    uploaded_file = st.file_uploader("Upload Handwritten Slip Photo", type=['jpg', 'jpeg', 'png'])
    if uploaded_file:
        st.image(uploaded_file, caption="Uploaded Slip", width=300)
        st.info("AI Reading slip and matching with Master Price List...")
