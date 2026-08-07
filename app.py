import streamlit as st
import pandas as pd
import os
import json
import re
import ast
import io
import google.generativeai as genai
from PIL import Image
from datetime import datetime

st.set_page_config(page_title="Pharma Stock & Billing App", layout="wide")

# Database Files
STOCK_FILE = "master_stock_inventory.csv"
SALES_FILE = "sales_history.csv"

# Initialize Master Stock
if not os.path.exists(STOCK_FILE):
    df_init = pd.DataFrame({
        "Product Name": ["WOMENSA SYRUP", "PANCHALIV SYRUP", "ALOBYD-P", "AGEXPRO PWD", "B-RICH TAB"],
        "HSN Code": ["3004", "3004", "3004", "3004", "3004"],
        "Batch No": ["BT101", "BT102", "BT103", "BT104", "BT105"],
        "Expiry Date": ["2027-12", "2027-10", "2028-01", "2027-08", "2028-05"],
        "MRP (₹)": [128.00, 144.00, 56.00, 249.00, 92.00],
        "GST %": [12, 12, 12, 12, 12],
        "Available Stock": [100, 100, 100, 100, 100]
    })
    df_init.to_csv(STOCK_FILE, index=False)

def get_stock():
    return pd.read_csv(STOCK_FILE)

def save_stock(df):
    df.to_csv(STOCK_FILE, index=False)

def record_sale(product_name, batch, qty, free_qty, mrp, disc_pct, gst_pct):
    taxable_val = (qty * mrp) * (1 - disc_pct / 100.0)
    gst_amt = taxable_val * (gst_pct / 100.0)
    net_amount = taxable_val + gst_amt
    
    new_sale = pd.DataFrame([{
        "Date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "Product Name": product_name,
        "Batch No": batch,
        "Qty Sold": qty,
        "Free Qty": free_qty,
        "MRP (₹)": mrp,
        "Discount %": disc_pct,
        "GST %": gst_pct,
        "Net Amount (₹)": round(net_amount, 2)
    }])
    if os.path.exists(SALES_FILE):
        sales_df = pd.read_csv(SALES_FILE)
        sales_df = pd.concat([sales_df, new_sale], ignore_index=True)
    else:
        sales_df = new_sale
    sales_df.to_csv(SALES_FILE, index=False)

st.title("💊 LCB Pharma - Smart AI Billing & Stock System")

# API Key from Streamlit Secrets
gemini_api_key = st.secrets.get("GEMINI_API_KEY", "")

menu = st.sidebar.radio("Navigation Menu", [
    "📦 Stock Inventory", 
    "📸 AI Photo Scanner", 
    "🛍️ Purchase Entry (Manual)", 
    "🧾 Sales Billing (Sell Items)"
])

# ----------------------------------------------------
# 1. STOCK INVENTORY
# ----------------------------------------------------
if menu == "📦 Stock Inventory":
    st.subheader("📋 Master Stock Register")
    stock_df = get_stock()
    st.dataframe(stock_df, use_container_width=True)

# ----------------------------------------------------
# 2. AI PHOTO SCANNER (WITH MASTER LIST MATCHING)
# ----------------------------------------------------
elif menu == "📸 AI Photo Scanner":
    st.subheader("📸 Scan Handwritten Slip with Smart Master Matching")
    uploaded_file = st.file_uploader("Upload Handwritten Slip Photo", type=['jpg', 'jpeg', 'png'])

    if uploaded_file:
        st.image(uploaded_file, caption="Uploaded Slip", width=350)
        
        if st.button("🚀 Auto-Scan & Match with Stock"):
            if not gemini_api_key or gemini_api_key.strip() == "":
                st.error("❌ GEMINI_API_KEY nahi mili! Streamlit Secrets check karein.")
            else:
                try:
                    current_stock = get_stock()
                    master_products = current_stock["Product Name"].tolist()
                    master_list_str = ", ".join(master_products)

                    prompt = f"""Extract product details from this pharmaceutical bill/slip image.
MASTER PRODUCT LIST FOR MATCHING CLUES: [{master_list_str}]

INSTRUCTIONS:
1. Match handwritten names with MASTER PRODUCT LIST if spelling is close.
2. Return ONLY valid JSON array:
[
  {{"Product Name": "ITEM NAME", "HSN": "3004", "Batch": "B01", "Expiry": "2027-12", "Qty": 10, "Free Qty": 0, "MRP": 100.0, "Discount %": 0, "GST %": 12}}
]"""

                    raw_text = None
                    with st.spinner("🔍 AI Reading slip... Please wait..."):
                        genai.configure(api_key=gemini_api_key)
                        image = Image.open(uploaded_file)
                        image.thumbnail((1024, 1024))
                        
                        try:
                            model = genai.GenerativeModel("gemini-2.0-flash")
                            response = model.generate_content([prompt, image])
                            raw_text = response.text.strip()
                        except Exception:
                            model = genai.GenerativeModel("gemini-1.5-flash")
                            response = model.generate_content([prompt, image])
                            raw_text = response.text.strip()

                    if raw_text:
                        cleaned = raw_text.replace("```json", "").replace("```", "").strip()
                        json_match = re.search(r'\[.*\]', cleaned, re.DOTALL)
                        target_str = json_match.group(0) if json_match else cleaned
                        
                        parsed_data = None
                        try:
                            parsed_data = json.loads(target_str)
                        except Exception:
                            try:
                                parsed_data = ast.literal_eval(target_str)
                            except Exception:
                                pass
                        
                        if parsed_data and isinstance(parsed_data, list):
                            st.session_state['scanned_items'] = parsed_data
                            st.success("✅ Bill Scanned Successfully!")
                            st.rerun()
                        else:
                            st.error("Data parse nahi ho saka. Raw output:")
                            st.code(raw_text)

                except Exception as err:
                    st.error(f"❌ Scan Error: {err}")

    # Display Scanned Table, Download Options & Save Buttons
    if 'scanned_items' in st.session_state:
        st.write("### 🔍 Scanned & Matched Bill Items")
        scanned_df = pd.DataFrame(st.session_state['scanned_items'])
        
        edited_df = st.data_editor(scanned_df, use_container_width=True, num_rows="dynamic")

        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            edited_df.to_excel(writer, index=False, sheet_name='Scanned_Bill')
        excel_data = buffer.getvalue()

        st.download_button(
            label="📊 Download Bill as Excel (.xlsx)",
            data=excel_data,
            file_name=f"Scanned_Bill_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

        st.write("---")
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("📥 Add to Stock Inventory (Purchase)"):
                current_stock = get_stock()
                items_to_save = edited_df.to_dict(orient="records")
                
                for item in items_to_save:
                    p_name = str(item.get('Product Name', '')).strip().upper()
                    p_hsn = str(item.get('HSN', '3004')).strip()
                    p_batch = str(item.get('Batch', 'N/A')).strip().upper()
                    p_exp = str(item.get('Expiry', 'N/A')).strip()
                    p_qty = int(item.get('Qty', 0)) + int(item.get('Free Qty', 0))
                    p_mrp = float(item.get('MRP', 0))
                    p_gst = float(item.get('GST %', 12))
                    
                    mask = (current_stock['Product Name'].str.strip().str.upper() == p_name) & (current_stock['Batch No'].str.strip().str.upper() == p_batch)
                    if mask.any():
                        current_stock.loc[mask, 'Available Stock'] += p_qty
                        current_stock.loc[mask, 'MRP (₹)'] = p_mrp
                    else:
                        new_row = pd.DataFrame([{
                            "Product Name": p_name,
                            "HSN Code": p_hsn,
                            "Batch No": p_batch,
                            "Expiry Date": p_exp,
                            "MRP (₹)": p_mrp,
                            "GST %": p_gst,
                            "Available Stock": p_qty
                        }])
                        current_stock = pd.concat([current_stock, new_row], ignore_index=True)
                
                save_stock(current_stock)
                st.balloons()
                st.success("🎉 Added to Stock Register!")
                del st.session_state['scanned_items']
                st.rerun()

        with col2:
            if st.button("🧾 Deduct from Stock (Sales Entry)"):
                current_stock = get_stock()
                items_to_save = edited_df.to_dict(orient="records")
                
                for item in items_to_save:
                    p_name = str(item.get('Product Name', '')).strip().upper()
                    p_batch = str(item.get('Batch', 'N/A')).strip().upper()
                    p_qty = int(item.get('Qty', 0))
                    p_free = int(item.get('Free Qty', 0))
                    p_mrp = float(item.get('MRP', 0))
                    p_disc = float(item.get('Discount %', 0))
                    p_gst = float(item.get('GST %', 12))
                    
                    total_deduct = p_qty + p_free
                    mask = current_stock['Product Name'].str.strip().str.upper() == p_name
                    
                    if mask.any():
                        current_stock.loc[mask, 'Available Stock'] -= total_deduct
                        record_sale(p_name, p_batch, p_qty, p_free, p_mrp, p_disc, p_gst)
                
                save_stock(current_stock)
                st.balloons()
                st.success("🎉 Sales Entry recorded & Stock deducted successfully!")
                del st.session_state['scanned_items']
                st.rerun()

# ----------------------------------------------------
# 3. MANUAL PURCHASE ENTRY
# ----------------------------------------------------
elif menu == "🛍️ Purchase Entry (Manual)":
    st.subheader("➕ Manual Purchase / Inward Entry")
    current_stock = get_stock()
    
    with st.form("manual_purchase_form"):
        col1, col2, col3 = st.columns(3)
        with col1:
            prod_name = st.text_input("Product Name").upper()
            hsn_code = st.text_input("HSN Code", value="3004")
            batch_no = st.text_input("Batch No.", value="BT001").upper()
        with col2:
            expiry_date = st.text_input("Expiry Date (MM/YY or YYYY-MM)", value="2027-12")
            mrp = st.number_input("MRP (₹)", min_value=0.0, step=1.0)
            gst_pct = st.number_input("GST %", min_value=0.0, value=12.0, step=1.0)
        with col3:
            billed_qty = st.number_input("Billed Quantity", min_value=1, step=1)
            free_qty = st.number_input("Free / Bonus Qty", min_value=0, step=1)
            disc_pct = st.number_input("Purchase Discount %", min_value=0.0, value=0.0, step=0.5)
            
        submit = st.form_submit_button("➕ Save Stock & Update Inventory")
        
        if submit and prod_name:
            total_qty = billed_qty + free_qty
            mask = (current_stock['Product Name'].str.strip().str.upper() == prod_name) & (current_stock['Batch No'].str.strip().str.upper() == batch_no)
            
            if mask.any():
                current_stock.loc[mask, 'Available Stock'] += total_qty
                current_stock.loc[mask, 'MRP (₹)'] = mrp
                current_stock.loc[mask, 'Expiry Date'] = expiry_date
            else:
                new_row = pd.DataFrame([{
                    "Product Name": prod_name,
                    "HSN Code": hsn_code,
                    "Batch No": batch_no,
                    "Expiry Date": expiry_date,
                    "MRP (₹)": mrp,
                    "GST %": gst_pct,
                    "Available Stock": total_qty
                }])
                current_stock = pd.concat([current_stock, new_row], ignore_index=True)
            
            save_stock(current_stock)
            st.success(f"✅ Added {total_qty} units of {prod_name} to Stock!")

# ----------------------------------------------------
# 4. MANUAL SALES BILLING
# ----------------------------------------------------
elif menu == "🧾 Sales Billing (Sell Items)":
    st.subheader("🧾 Sales Counter / Outward Billing")
    current_stock = get_stock()
    
    if current_stock.empty:
        st.warning("Stock inventory is empty.")
    else:
        prod_list = current_stock['Product Name'].unique().tolist()
        
        col1, col2 = st.columns(2)
        with col1:
            selected_prod = st.selectbox("Select Product", prod_list)
            
        batches = current_stock[current_stock['Product Name'] == selected_prod]['Batch No'].tolist()
        
        with col2:
            selected_batch = st.selectbox("Select Batch No.", batches)
            
        if selected_prod and selected_batch:
            item_data = current_stock[(current_stock['Product Name'] == selected_prod) & (current_stock['Batch No'] == selected_batch)].iloc[0]
            
            avail_qty = item_data['Available Stock']
            item_mrp = item_data['MRP (₹)']
            item_hsn = item_data.get('HSN Code', '3004')
            item_exp = item_data.get('Expiry Date', 'N/A')
            item_gst = item_data.get('GST %', 12.0)
            
            st.info(f"📌 **Batch:** {selected_batch} | **Expiry:** {item_exp} | **HSN:** {item_hsn} | **MRP:** ₹{item_mrp} | **Avail Stock:** {avail_qty} units")
            
            c1, c2, c3 = st.columns(3)
            with c1:
                sell_qty = st.number_input("Qty to Sell", min_value=1, max_value=int(avail_qty) if avail_qty > 0 else 1, step=1)
            with c2:
                free_given = st.number_input("Free Qty Given", min_value=0, step=1)
            with c3:
                discount_given = st.number_input("Discount %", min_value=0.0, max_value=100.0, value=0.0, step=0.5)
            
            gross = sell_qty * item_mrp
            taxable = gross * (1 - discount_given / 100.0)
            gst_val = taxable * (item_gst / 100.0)
            net_val = taxable + gst_val
            
            st.write(f"💰 **Net Billing Amount (Incl. GST):** ₹{net_val:,.2f}")
            
            if st.button("🏷️ Print & Deduct Stock"):
                total_deduct = sell_qty + free_given
                if avail_qty < total_deduct:
                    st.error("Insufficient Stock!")
                else:
                    mask = (current_stock['Product Name'] == selected_prod) & (current_stock['Batch No'] == selected_batch)
                    current_stock.loc[mask, 'Available Stock'] -= total_deduct
                    save_stock(current_stock)
                    
                    record_sale(selected_prod, selected_batch, sell_qty, free_given, item_mrp, discount_given, item_gst)
                    st.balloons()
                    st.success(f"✅ Sale Recorded! Deducted {total_deduct} units.")
                    st.rerun()

    st.write("---")
    st.subheader("📊 Sales Register & Billing History")
    if os.path.exists(SALES_FILE):
        sales_df = pd.read_csv(SALES_FILE)
        st.dataframe(sales_df, use_container_width=True)
        st.metric("Total Net Sales Value", f"₹{sales_df['Net Amount (₹)'].sum():,.2f}")
