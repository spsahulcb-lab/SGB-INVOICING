import streamlit as st
import pandas as pd
from datetime import datetime
from fpdf import FPDF
import urllib.parse
import json
import google.generativeai as genai
from PIL import Image

# ==========================================
# PAGE CONFIG & ORANGE THEME STYLING
# ==========================================
st.set_page_config(page_title="Pharma ERP - Wholesale & AI Billing", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
    <style>
    .stApp { background-color: #FFF9F5; }
    .main-header { font-size: 26px; font-weight: bold; color: #E65100; text-align: center; margin-bottom: 20px; }
    .stButton>button { width: 100%; border-radius: 8px; font-weight: bold; background-color: #FB8C00; color: white; border: none; }
    .stButton>button:hover { background-color: #EF6C00; color: white; }
    .ai-box { background-color: #FFF3E0; padding: 18px; border-radius: 10px; border-left: 6px solid #F57C00; margin-bottom: 20px; }
    [data-testid="stSidebar"] { background-color: #FFF0E6; }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# GEMINI AI SETUP
# ==========================================
if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

def process_bill_with_gemini(uploaded_file, text_input):
    try:
        model = genai.GenerativeModel('gemini-3.5-flash-lite')
        
        prompt = """
        Extract medicine invoice details from image or text for pharma wholesale ERP.
        Extract items with Batch, Expiry, Qty, Rate, MRP, and GST.
        Return ONLY a clean JSON array of objects without Markdown formatting:
        [
          {"PRODUCT": "Womensa Syrup", "BATCH": "B123", "EXP": "12/27", "QTY": 20, "RATE": 120.0, "MRP": 198.0, "GST": 12, "AMOUNT": 2400.0}
        ]
        """
        if uploaded_file:
            img = Image.open(uploaded_file)
            response = model.generate_content([prompt, img])
        else:
            response = model.generate_content([prompt, text_input])
            
        clean_txt = response.text.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean_txt)
        
        cleaned_data = []
        for item in data:
            try:
                qty = float(item.get("QTY", 1) or 1)
            except:
                qty = 1.0
            try:
                rate = float(item.get("RATE", 0.0) or 0.0)
            except:
                rate = 0.0
            
            amt = qty * rate
            cleaned_data.append({
                "PRODUCT": str(item.get("PRODUCT", "Unknown")),
                "BATCH": str(item.get("BATCH", "N/A")),
                "EXP": str(item.get("EXP", "N/A")),
                "QTY": qty,
                "RATE": rate,
                "MRP": float(item.get("MRP", rate * 1.5) or rate * 1.5),
                "GST": float(item.get("GST", 12) or 12),
                "AMOUNT": amt
            })
        return cleaned_data
    except Exception as e:
        st.error(f"AI Extraction Error: {e}")
        return []

# ==========================================
# FIXED PDF GENERATOR FUNCTION
# ==========================================
def generate_pdf_invoice(party, inv, gst, cart_data, total, gst_val, net_val):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", 'B', 16)
    pdf.cell(190, 10, "SGB / LCB PHARMA WHOLESALE INVOICE", new_x="LMARGIN", new_y="NEXT", align='C')
    pdf.set_font("Helvetica", '', 10)
    pdf.cell(190, 6, f"Party: {party} | GSTIN: {gst}", new_x="LMARGIN", new_y="NEXT", align='C')
    pdf.cell(190, 6, f"Invoice No: {inv} | Date: {datetime.now().strftime('%d-%m-%Y')}", new_x="LMARGIN", new_y="NEXT", align='C')
    pdf.ln(5)
    
    # Table Header
    pdf.set_font("Helvetica", 'B', 9)
    pdf.cell(60, 7, "Product", 1)
    pdf.cell(25, 7, "Batch", 1)
    pdf.cell(20, 7, "Exp", 1)
    pdf.cell(20, 7, "Qty", 1)
    pdf.cell(25, 7, "Rate (Rs)", 1)
    pdf.cell(40, 7, "Amount (Rs)", 1)
    pdf.ln()
    
    # Rows
    pdf.set_font("Helvetica", '', 9)
    for row in cart_data:
        pdf.cell(60, 6, str(row['PRODUCT'])[:28], 1)
        pdf.cell(25, 6, str(row.get('BATCH', 'N/A')), 1)
        pdf.cell(20, 6, str(row.get('EXP', 'N/A')), 1)
        pdf.cell(20, 6, str(row['QTY']), 1)
        pdf.cell(25, 6, f"{float(row['RATE']):.2f}", 1)
        pdf.cell(40, 6, f"{float(row['AMOUNT']):.2f}", 1)
        pdf.ln()
        
    pdf.ln(4)
    pdf.set_font("Helvetica", 'B', 10)
    pdf.cell(190, 6, f"Sub Total: Rs. {total:,.2f}", new_x="LMARGIN", new_y="NEXT", align='R')
    pdf.cell(190, 6, f"GST (12%): Rs. {gst_val:,.2f}", new_x="LMARGIN", new_y="NEXT", align='R')
    pdf.cell(190, 6, f"Grand Total: Rs. {net_val:,.2f}", new_x="LMARGIN", new_y="NEXT", align='R')
    
    # Fixed FPDF2 output generation (returns bytes directly)
    return bytes(pdf.output())

# Master & State Config
MASTER_PRODUCTS = [
    "ATPLEX Syrup", "Duty Beauty MINUS 16 Cream", "Duty Beauty Glutathione Soap",
    "Duty Beauty Facewash", "Kabja Band", "Cartibot", "Virload", "Womensa Syrup",
    "Panchaliv Syrup", "Alobyd-P", "Ureta", "Brainenza", "Cutpiles", "Acnetaz", "Dermapari"
]

USERS_DB = {
    "manager": {"password": "admin123", "role": "Manager", "name": "Manager"},
    "satya": {"password": "satya123", "role": "Sales Executive", "name": "Satya Sahu"}
}

if "logged_in" not in st.session_state: st.session_state["logged_in"] = False
if "scanned_cart" not in st.session_state: st.session_state["scanned_cart"] = []
if "sales_db" not in st.session_state: st.session_state["sales_db"] = []
if "purchase_db" not in st.session_state: st.session_state["purchase_db"] = []

# Login Guard
if not st.session_state["logged_in"]:
    st.markdown("<h2 class='main-header'>🍊 SGB / LCB Pharma Wholesale ERP</h2>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        username_input = st.text_input("Username").strip().lower()
        password_input = st.text_input("Password", type="password")
        if st.button("🚀 Secure Login"):
            if username_input in USERS_DB and USERS_DB[username_input]["password"] == password_input:
                st.session_state["logged_in"] = True
                st.session_state["logged_user"] = USERS_DB[username_input]
                st.rerun()
            else:
                st.error("❌ Invalid Username or Password")
    st.stop()

# Sidebar Navigation
logged_user = st.session_state["logged_user"]
st.sidebar.title(f"🍊 {logged_user['name']}")
st.sidebar.caption(f"Role: {logged_user['role']}")

active_tab = st.sidebar.radio("Navigation", [
    "🤖 AI Smart Scan & Billing",
    "📦 Sales History",
    "📥 Purchase History (Stock In)",
    "🏭 Batch Stock & Expiry Alert"
])

if st.sidebar.button("🚪 Logout"):
    st.session_state["logged_in"] = False
    st.session_state["scanned_cart"] = []
    st.rerun()

# AI Billing Section
if active_tab == "🤖 AI Smart Scan & Billing":
    st.markdown("<h2 style='color: #E65100;'>🤖 AI Scanner & Wholesale Billing</h2>", unsafe_allow_html=True)
    
    st.markdown("""
        <div class='ai-box'>
            <h3 style='color: #E65100; margin-top:0;'>📷 AI Bill Scanner</h3>
            <p>Upload handwritten slip or printed invoice image to auto-extract items.</p>
        </div>
    """, unsafe_allow_html=True)
    
    c1, c2 = st.columns(2)
    with c1:
        uploaded_img = st.file_uploader("📷 Upload Invoice / Order Slip", type=["jpg", "png", "jpeg"])
    with c2:
        raw_text = st.text_area("✍️ Or Paste Text Invoice Data")
        
    if st.button("✨ Auto-Extract via Gemini AI"):
        if uploaded_img or raw_text:
            with st.spinner("AI scan kar raha hai..."):
                items = process_bill_with_gemini(uploaded_img, raw_text)
                if items:
                    st.session_state["scanned_cart"].extend(items)
                    st.success("✅ AI Scan Completed!")
                    st.rerun()
        else:
            st.warning("Please upload a slip image or paste text.")

    st.markdown("---")
    
    st.subheader("📝 Wholesale Bill Meta Info")
    f1, f2, f3 = st.columns(3)
    with f1:
        party_name = st.text_input("Party / Supplier / Medical Store Name", value="Sharma Medical Hall")
    with f2:
        inv_no = st.text_input("Invoice No", value=f"INV-{int(datetime.now().timestamp())}")
    with f3:
        gst_no = st.text_input("Party GSTIN", value="09AAAAA0000A1Z5")

    st.markdown("##### ➕ Manual Item Addition")
    p1, p2, p3, p4, p5, p6 = st.columns([2, 1, 1, 1, 1, 1])
    with p1:
        sel_prod = st.selectbox("Product", MASTER_PRODUCTS)
    with p2:
        batch_num = st.text_input("Batch No", value="BT-102")
    with p3:
        exp_date = st.text_input("Expiry", value="08/27")
    with p4:
        s_qty = st.number_input("Qty", min_value=1, value=10)
    with p5:
        s_rate = st.number_input("Rate (₹)", min_value=0.0, value=120.0)
    with p6:
        st.write("")
        st.write("")
        if st.button("➕ Add"):
            st.session_state["scanned_cart"].append({
                "PRODUCT": sel_prod, "BATCH": batch_num, "EXP": exp_date,
                "QTY": float(s_qty), "RATE": float(s_rate), "MRP": float(s_rate * 1.5), "GST": 12.0, "AMOUNT": float(s_qty * s_rate)
            })
            st.rerun()

    # Display Cart & Correct Totals
    if st.session_state["scanned_cart"]:
        st.markdown("---")
        st.subheader("🛒 Scanned / Current Bill Items")
        
        # Ensure values are float for sums
        for item in st.session_state["scanned_cart"]:
            try:
                item["QTY"] = float(item.get("QTY", 0))
            except:
                item["QTY"] = 0.0
            try:
                item["RATE"] = float(item.get("RATE", 0))
            except:
                item["RATE"] = 0.0
            item["AMOUNT"] = item["QTY"] * item["RATE"]
            
        cart_df = pd.DataFrame(st.session_state["scanned_cart"])
        st.dataframe(cart_df, use_container_width=True)
        
        total_val = float(cart_df["AMOUNT"].sum())
        gst_val = total_val * 0.12
        net_val = total_val + gst_val
        
        st.markdown(f"<h3 style='color:#E65100;'>💰 Sub Total: ₹ {total_val:,.2f} | GST (12%): ₹ {gst_val:,.2f} | Grand Total: ₹ {net_val:,.2f}</h3>", unsafe_allow_html=True)
        
        # Action Buttons
        save_col1, save_col2, save_col3, save_col4, save_col5 = st.columns(5)
        
        with save_col1:
            if st.button("📤 Save SALES"):
                for row in st.session_state["scanned_cart"]:
                    r = dict(row)
                    r.update({"INVOICE": inv_no, "PARTY": party_name, "TYPE": "SALES", "DATE": datetime.now().strftime("%Y-%m-%d")})
                    st.session_state["sales_db"].append(r)
                st.success("Saved to Sales!")
                st.session_state["scanned_cart"] = []
                st.rerun()

        with save_col2:
            if st.button("📥 Save PURCHASE"):
                for row in st.session_state["scanned_cart"]:
                    r = dict(row)
                    r.update({"INVOICE": inv_no, "PARTY": party_name, "TYPE": "PURCHASE", "DATE": datetime.now().strftime("%Y-%m-%d")})
                    st.session_state["purchase_db"].append(r)
                st.success("Saved to Purchase!")
                st.session_state["scanned_cart"] = []
                st.rerun()

        with save_col3:
            try:
                pdf_bytes = generate_pdf_invoice(party_name, inv_no, gst_no, st.session_state["scanned_cart"], total_val, gst_val, net_val)
                st.download_button(
                    label="📄 Download PDF",
                    data=pdf_bytes,
                    file_name=f"{inv_no}.pdf",
                    mime="application/pdf"
                )
            except Exception as pdf_err:
                st.error(f"PDF Generation Error: {pdf_err}")

        with save_col4:
            msg = f"🧾 *INVOICE*\n*Party:* {party_name}\n*Total:* ₹{net_val:,.2f}\n"
            for row in st.session_state["scanned_cart"]:
                msg += f"• {row['PRODUCT']} - {row['QTY']} Qty @ ₹{row['RATE']}\n"
            wa_url = f"https://api.whatsapp.com/send?text={urllib.parse.quote(msg)}"
            st.markdown(f'<a href="{wa_url}" target="_blank"><button style="background-color:#25D366; color:white; font-weight:bold; height:38px; border-radius:8px; border:none; width:100%;">📲 WhatsApp</button></a>', unsafe_allow_html=True)

        with save_col5:
            if st.button("🗑️ Clear List"):
                st.session_state["scanned_cart"] = []
                st.rerun()

# History Registers
elif active_tab == "📦 Sales History":
    st.markdown("<h2 style='color: #E65100;'>📦 Wholesale Sales Register</h2>", unsafe_allow_html=True)
    if st.session_state["sales_db"]:
        st.dataframe(pd.DataFrame(st.session_state["sales_db"]), use_container_width=True)
    else:
        st.info("No Sales records found.")

elif active_tab == "📥 Purchase History (Stock In)":
    st.markdown("<h2 style='color: #E65100;'>📥 Supplier Purchase Register</h2>", unsafe_allow_html=True)
    if st.session_state["purchase_db"]:
        st.dataframe(pd.DataFrame(st.session_state["purchase_db"]), use_container_width=True)
    else:
        st.info("No Purchase records found.")

elif active_tab == "🏭 Batch Stock & Expiry Alert":
    st.markdown("<h2 style='color: #E65100;'>🏭 Live Batch-Wise Stock & Expiry</h2>", unsafe_allow_html=True)
    sample_stock = [
        {"PRODUCT": "ATPLEX Syrup", "BATCH": "B998", "EXP": "10/26", "STOCK QTY": 150, "MRP": 180.0},
        {"PRODUCT": "Womensa Syrup", "BATCH": "B882", "EXP": "04/26", "STOCK QTY": 80, "MRP": 198.0}
    ]
    st.dataframe(pd.DataFrame(sample_stock), use_container_width=True)
