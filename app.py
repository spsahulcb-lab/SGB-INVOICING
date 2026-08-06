import streamlit as st
import pandas as pd
import os
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

st.title("💊 LCB Pharma - Sales, Purchase & Stock App")

# Secrets se automatic API key lene ka code
api_key = st.secrets.get("GEMINI_API_KEY", "")

menu = st.sidebar.radio("Navigation Menu", ["📦 Stock Inventory", "📸 AI Photo Scanner", "🛍️ Purchase Entry", "🧾 Sales Billing"])

if menu == "📦 Stock Inventory":
    st.subheader("Current Stock Register")
    st.dataframe(get_stock(), use_container_width=True)

elif menu == "📸 AI Photo Scanner":
    st.subheader("Scan Handwritten Bill with Gemini AI")
    uploaded_file = st.file_uploader("Upload Handwritten Slip Photo", type=['jpg', 'jpeg', 'png'])
    
    if uploaded_file:
        st.image(uploaded_file, caption="Uploaded Slip", width=350)
        
        if st.button("🚀 Process Slip & Update Stock"):
            if not api_key:
                st.error("API Key nahi mili! Streamlit Secrets me GEMINI_API_KEY save karein.")
            else:
                try:
                    genai.configure(api_key=api_key)
                    image = Image.open(uploaded_file)
                    prompt = "Extract product names, quantities, and MRPs from this slip as JSON format: [{'Product Name': '...', 'Qty': 0, 'MRP': 0}]"
                    
                    # 🔍 Google API se dynamically saare live/active models nikalo
                    available_models = []
                    for m in genai.list_models():
                        if 'generateContent' in m.supported_generation_methods:
                            available_models.append(m.name)
                    
                    if not available_models:
                        st.error("Aapki API Key par koi active model nahi mila. Google AI Studio se nayi key generate karein.")
                    else:
                        success = False
                        last_err = ""
                        
                        # Live models me se jo bhi pehla work kare usse scan run karo
                        for model_name in available_models:
                            try:
                                model = genai.GenerativeModel(model_name)
                                response = model.generate_content([prompt, image])
                                st.success(f"✅ Scan Complete! (Used Model: {model_name})")
                                st.write(response.text)
                                success = True
                                break
                            except Exception as e:
                                last_err = str(e)
                                continue
                        
                        if not success:
                            st.error(f"Scan failed on available models. Last Error: {last_err}")
                        
                except Exception as e:
                    st.error(f"Error: {e}")
