import streamlit as st
import pandas as pd
import sqlite3

# --- Database Setup ---
def get_connection():
    conn = sqlite3.connect("products.db", check_same_thread=False)
    return conn

def create_table():
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS master_products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT UNIQUE,
            pack TEXT,
            mrp REAL,
            rate REAL,
            gst REAL
        )
    ''')
    conn.commit()
    conn.close()

create_table()

# --- Functions ---
def load_products():
    conn = get_connection()
    df = pd.read_sql("SELECT * FROM master_products", conn)
    conn.close()
    return df

def save_all_products(df):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM master_products")  # Clear and rewrite for sync
    for _, row in df.iterrows():
        c.execute('''
            INSERT INTO master_products (product_name, pack, mrp, rate, gst)
            VALUES (?, ?, ?, ?, ?)
        ''', (row['product_name'], row['pack'], row['mrp'], row['rate'], row['gst']))
    conn.commit()
    conn.close()

def delete_single_product(prod_name):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM master_products WHERE product_name = ?", (prod_name,))
    conn.commit()
    conn.close()

# --- Rate Calculation Formula ---
def calculate_rate(mrp, gst_rate):
    if mrp is None or mrp <= 0:
        return 0.0
    # Formula: Rate = (MRP * 80) / (100 + GST)
    return round((mrp * 80.0) / (100.0 + gst_rate), 2)

# --- UI Layout ---
st.title("🏷️ Manage Master Products List")

col_left, col_right = st.columns([1, 1])

with col_left:
    st.subheader("➕ Add Single Product")
    
    prod_name = st.text_input("Product Name")
    
    # Default Pack Size = 1x10
    pack_size = st.text_input("Pack Size", value="1x10")
    
    # Default GST Rate = 5.0%
    gst_val = st.number_input("Tax / GST (%)", value=5.0, step=1.0)
    
    mrp_val = st.number_input("MRP (₹)", value=100.00, step=5.0)
    
    # Dynamic Auto-calculated Rate
    calc_rate = calculate_rate(mrp_val, gst_val)
    rate_val = st.number_input("Rate (₹) [Auto-calculated]", value=calc_rate, step=1.0)
    
    if st.button("➕ Add Product to Master"):
        if prod_name.strip():
            conn = get_connection()
            c = conn.cursor()
            try:
                c.execute('''
                    INSERT INTO master_products (product_name, pack, mrp, rate, gst)
                    VALUES (?, ?, ?, ?, ?)
                ''', (prod_name.strip(), pack_size, mrp_val, rate_val, gst_val))
                conn.commit()
                st.success(f"'{prod_name}' successfully added!")
            except sqlite3.IntegrityError:
                st.error("Ye product pehle se exists karta hai!")
            finally:
                conn.close()
            st.rerun()
        else:
            st.warning("Kripya Product Name darj karein.")

with col_right:
    st.subheader("📝 Editable Master Products Database")
    st.info("💡 Tip: Changes karne ke baad 'Save Database Changes' par click karein.")
    
    df_products = load_products()
    
    if not df_products.empty:
        # Display editable dataframe
        edited_df = st.data_editor(
            df_products[['product_name', 'pack', 'mrp', 'rate', 'gst']],
            num_rows="dynamic",
            key="product_editor",
            use_container_width=True
        )
        
        if st.button("💾 Save Database Changes", type="primary"):
            save_all_products(edited_df)
            st.success("Database successfully update ho gaya hai!")
            st.rerun()
    else:
        st.write("Koi product uplabdha nahi hai.")

    st.markdown("---")
    
    # Dedicated Delete Section for Permanent Removal
    st.subheader("🗑️ Remove Product via Selectbox")
    df_current = load_products()
    if not df_current.empty:
        prod_to_delete = st.selectbox("Select Product to Delete", df_current['product_name'].tolist())
        if st.button("❌ Delete Selected Product"):
            delete_single_product(prod_to_delete)
            st.success(f"'{prod_to_delete}' database se permanently delete ho gaya hai!")
            st.rerun()
