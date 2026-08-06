import streamlit as st
import pandas as pd
import os
import json
import re
import google.generativeai as genai
from PIL import Image

st.set_page_config(page_title="Pharma Stock & Billing App", layout="wide")

# Database File
STOCK_FILE = "master_stock_inventory.csv"

if not os.path.exists(STOCK_FILE):
    df_init = pd.DataFrame({
        "Product Name": ["WOMENSA SYRUP", "PANCHALIV SYRUP", "ALOBYD-P", "AGEXPRO PWD", "B-RICH TAB"],
        "MRP (₹)": [128.00, 144.00, 56.00, 249.00, 92.00],
        "Available Stock": [100, 100, 100, 100, 100]
    })
    df_init.to_csv(STOCK_FILE, index=False)

def get_stock():
    return pd.read_csv(STOCK_FILE)

def save_stock(df):
    df.to_csv(STOCK_FILE, index=False)

st.title("💊 LCB Pharma - Sales, Purchase & Stock App")

api_key = st.secrets.get("GEMINI_API_KEY", "")

menu = st.sidebar.radio("Navigation Menu", ["📦 Stock Inventory", "📸 AI Photo Scanner", "🛍️ Purchase Entry", "🧾 Sales Billing"])

# 1. STOCK INVENTORY
if menu == "📦 Stock Inventory":
    st.subheader("📋 Current Stock Register")
    st.dataframe(get_stock(), use_container_width=True)

# 2. AI PHOTO SCANNER
elif menu == "📸 AI Photo Scanner":
    st.subheader("📸 Scan Handwritten Bill with Gemini AI")
    uploaded_file = st.file_uploader("Upload Handwritten Slip Photo", type=['jpg', 'jpeg', 'png'])
    
    if uploaded_file:
        st.image(uploaded_file, caption="Uploaded Slip", width=350)
        
        if st.button("🚀 Process Slip with AI"):
            if not api_key:
                st.error("API Key nahi mili! Streamlit Secrets check karein.")
            else:
                try:
                    genai.configure(api_key=api_key)
                    image = Image.open(uploaded_file)
                    prompt = "Extract product names, quantities, and MRPs from this slip as strict JSON array: [{'Product Name': '...', 'Qty': 0, 'MRP': 0}]"
                    
                    available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
                    
                    success = False
                    raw_text = ""
                    
                    for model_name in available_models:
                        try:
                            model = genai.GenerativeModel(model_name)
                            response = model.generate_content([prompt, image])
                            raw_text = response.text
                            success = True
                            st.session_state['last_used_model'] = model_name
                            break
                        except Exception:
                            continue
                    
                    if success:
                        # Clean JSON from response text
                        json_match = re.search(r'\[.*\]', raw_text, re.DOTALL)
                        if json_match:
                            parsed_data = json.loads(json_match.group(0))
                            st.session_state['scanned_items'] = parsed_data
                            st.success("✅ AI Scan Successful!")
                        else:
                            st.error("JSON parse nahi ho paya. Rescan karein.")
                    else:
                        st.error("Scan failed on all models.")
                except Exception as e:
                    st.error(f"Error: {e}")

    # Display Scanned Table & Save Button
    if 'scanned_items' in st.session_state:
        st.write("### 🔍 Scanned Bill Items")
        scanned_df = pd.DataFrame(st.session_state['scanned_items'])
        st.dataframe(scanned_df, use_container_width=True)
        
        if st.button("📥 Direct Save / Update to Stock Inventory"):
            current_stock = get_stock()
            
            for item in st.session_state['scanned_items']:
                p_name = str(item.get('Product Name', '')).strip().upper()
                p_qty = int(item.get('Qty', 0))
                p_mrp = float(item.get('MRP', 0))
                
                # Check if product exists in current stock
                mask = current_stock['Product Name'].str.strip().str.upper() == p_name
                if mask.any():
                    current_stock.loc[mask, 'Available Stock'] += p_qty
                    current_stock.loc[mask, 'MRP (₹)'] = p_mrp
                else:
                    new_row = pd.DataFrame([{"Product Name": p_name, "MRP (₹)": p_mrp, "Available Stock": p_qty}])
                    current_stock = pd.concat([current_stock, new_row], ignore_index=True)
            
            save_stock(current_stock)
            st.balloons()
            st.success("🎉 Stock successfully updated into Inventory Register!")
            del st.session_state['scanned_items']

# 3. MANUAL PURCHASE ENTRY
elif menu == "🛍️ Purchase Entry":
    st.subheader("➕ Manual Purchase / Stock Entry")
    
    current_stock = get_stock()
    
    with st.form("manual_entry_form"):
        prod_name = st.text_input("Product Name").upper()
        mrp = st.number_input("MRP (₹)", min_value=0.0, step=1.0)
        qty = st.number_input("Quantity Received", min_value=1, step=1)
        
        submit = st.form_submit_button(" Add to Stock")
        
        if submit and prod_name:
            mask = current_stock['Product Name'].str.strip().str.upper() == prod_name
            if mask.any():
                current_stock.loc[mask, 'Available Stock'] += qty
                current_stock.loc[mask, 'MRP (₹)'] = mrp
            else:
                new_row = pd.DataFrame([{"Product Name": prod_name, "MRP (₹)": mrp, "Available Stock": qty}])
                current_stock = pd.concat([current_stock, new_row], ignore_index=True)
            
            save_stock(current_stock)
            st.success(f"✅ Added {qty} units of {prod_name} to Stock!")
