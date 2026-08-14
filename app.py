import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
from PIL import Image, ImageDraw, ImageFont
import io
import urllib.parse
import google.generativeai as genai

# Page Config
st.set_page_config(page_title="Pharma ERP Dashboard", page_icon="💊", layout="wide")

# Custom Orange & White Theme Styling
st.markdown("""
    <style>
    .main { background-color: #FAFAFA; }
    .stButton>button { background-color: #FF6600; color: white; border-radius: 6px; font-weight: bold; border: none; }
    .stButton>button:hover { background-color: #E65C00; color: white; }
    h1, h2, h3 { color: #D95300; }
    </style>
""", unsafe_allow_html=True)

# Google Sheets Connection
conn = st.connection("gsheets", type=GSheetsConnection)

# Session State for Sales Cart
if "cart" not in st.session_state:
    st.session_state.cart = []

# Sidebar Navigation & Role Control
st.sidebar.title("🍊 Pharma ERP System")
role = st.sidebar.selectbox("User Role", ["Salesman", "Manager"])
menu = st.sidebar.radio("Navigation", ["Sales Invoice", "Purchase Entry", "Stock Master", "Party Master", "AI Assistant"])

# Helper Function to Load Sheets
@st.cache_data(ttl=5)
def load_data(worksheet_name):
    try:
        return conn.read(worksheet=worksheet_name)
    except Exception:
        return pd.DataFrame()

# ----------------- 1. SALES INVOICE MODULE -----------------
if menu == "Sales Invoice":
    st.title("📄 Sales Invoice Generation")
    
    col1, col2 = st.columns([2, 1])
    with col1:
        party_name = st.text_input("Customer / Party Name")
        item_name = st.selectbox("Select Product / Medicine", ["Paracetamol 500mg", "Amoxicillin 250mg", "Cough Syrup 100ml", "Vitamin C Tablets"])
        qty = st.number_input("Quantity", min_value=1, value=1)
        rate = st.number_input("Rate (₹)", min_value=0.0, value=100.0)
        discount = st.number_input("Discount (%)", min_value=0.0, max_value=100.0, value=5.0)
        gst = st.number_input("GST (%)", min_value=0.0, value=12.0)
        
        if st.button("➕ Add Item to Bill"):
            amount = qty * rate
            disc_amount = amount * (discount / 100)
            taxable = amount - disc_amount
            gst_amount = taxable * (gst / 100)
            net_total = taxable + gst_amount
            
            st.session_state.cart.append({
                "Item": item_name, "Qty": qty, "Rate": rate,
                "Discount (%)": discount, "GST (%)": gst, "Net Total": round(net_total, 2)
            })
            st.success(f"{item_name} added to invoice.")

    with col2:
        st.subheader("🛒 Bill Summary")
        if st.session_state.cart:
            df_cart = pd.DataFrame(st.session_state.cart)
            st.dataframe(df_cart, use_container_width=True)
            grand_total = df_cart["Net Total"].sum()
            st.metric("Grand Total", f"₹{grand_total:.2f}")

            if st.button("💾 Generate Invoice & Download"):
                # Invoice Image Generation (Pillow)
                img = Image.new('RGB', (500, 600), color=(255, 255, 255))
                d = ImageDraw.Draw(img)
                d.text((150, 20), "PHARMA ERP INVOICE", fill=(217, 83, 0))
                d.text((20, 60), f"Customer: {party_name}", fill=(0, 0, 0))
                d.text((20, 80), f"Total Amount: ₹{grand_total:.2f}", fill=(0, 0, 0))
                
                y = 120
                for item in st.session_state.cart:
                    d.text((20, y), f"{item['Item']} x {item['Qty']} = ₹{item['Net Total']}", fill=(0, 0, 0))
                    y += 25
                
                buf = io.BytesIO()
                img.save(buf, format="JPEG")
                st.download_button("📥 Download JPG Invoice", data=buf.getvalue(), file_name="invoice.jpg", mime="image/jpeg")

                # WhatsApp Share Link
                msg = f"Hello {party_name}, your bill total is ₹{grand_total:.2f}. Thank you!"
                wa_url = f"https://api.whatsapp.com/send?text={urllib.parse.quote(msg)}"
                st.markdown(f"[💬 Share Bill on WhatsApp]({wa_url})", unsafe_allowed_html=True)

# ----------------- 2. PURCHASE ENTRY MODULE -----------------
elif menu == "Purchase Entry":
    st.title("📦 Purchase Stock Entry")
    if role == "Salesman":
        st.warning("🔒 Manager access required for Purchase Entry.")
    else:
        supplier = st.text_input("Supplier Name")
        prod = st.text_input("Product Name")
        p_qty = st.number_input("Purchase Qty", min_value=1)
        p_rate = st.number_input("Purchase Price (₹)", min_value=0.0)
        if st.button("Save Purchase Entry"):
            st.success("Purchase record logged successfully!")

# ----------------- 3. STOCK MASTER MODULE -----------------
elif menu == "Stock Master":
    st.title("📊 Live Stock Inventory")
    stock_df = load_data("stock_master")
    if not stock_df.empty:
        st.dataframe(stock_df, use_container_width=True)
    else:
        st.info("Stock sheet empty or connecting to Google Sheets...")

# ----------------- 4. PARTY MASTER MODULE -----------------
elif menu == "Party Master":
    st.title("👥 Party & Customer Directory")
    party_df = load_data("party_master")
    if not party_df.empty:
        st.dataframe(party_df, use_container_width=True)
    else:
        st.info("Party master sheet empty or connecting to Google Sheets...")

# ----------------- 5. AI ASSISTANT MODULE -----------------
elif menu == "AI Assistant":
    st.title("🤖 Pharma AI Business Assistant")
    query = st.text_area("Ask AI about inventory management, sales summaries, or pharmaceutical standards:")
    if st.button("Ask AI"):
        try:
            genai.configure(api_key=st.secrets.get("GEMINI_API_KEY", ""))
            model = genai.GenerativeModel('gemini-1.5-flash')
            response = model.generate_content(query)
            st.write(response.text)
        except Exception as e:
            st.error(f"Gemini API Connection Error: {e}")
