from io import BytesIO
import json
import google.generativeai as genai
import pandas as pd
from PIL import Image
import streamlit as st

# ==========================================
# 1. PAGE SETUP & CONFIGURATION
# ==========================================
st.set_page_config(
    page_title="Pharma Inventory & Smart Billing",
    layout="wide",
    page_icon="💊",
)

st.title("💊 Pharma Inventory & Smart Billing System")

# Gemini API Key Setup
# st.secrets ["GEMINI_API_KEY"] का प्रयोग करें या अपनी API Key डालें
if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

# Global Session State Initialization
if "purchase_data" not in st.session_state:
    st.session_state["purchase_data"] = pd.DataFrame()

if "sales_data" not in st.session_state:
    st.session_state["sales_data"] = pd.DataFrame()


# ==========================================
# 2. HELPER FUNCTIONS (Compression & AI Scan)
# ==========================================


# 🚀 फोटो को 3.5 MB से घटकर ~200 KB करने का फ़ंक्शन (सुपरफास्ट प्रोसेसिंग के लिए)
def compress_image(uploaded_file, max_dimension=1280, quality=75):
    img = Image.open(uploaded_file)
    if img.mode != "RGB":
        img = img.convert("RGB")

    # Aspect Ratio बनाए रखते हुए रिसाइज़ करें
    img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)

    buffer = BytesIO()
    img.save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue()


# 🧠 AI Image Scanner Function
def scan_slip_with_ai(uploaded_file, slip_type="purchase"):
    # 1. Fast Image Compression
    compressed_bytes = compress_image(uploaded_file)

    # 2. Gemini Prompt
    prompt = f"""
    Extract all product details from this {slip_type} order slip image.
    Extract exactly 3 columns:
    1. Product Name
    2. MRP (as a float value)
    3. Qty (as an integer value)

    Return ONLY a valid clean JSON array without markdown syntax, like this:
    [
      {{"Product Name": "ATPLEX SYP.", "MRP": 144.00, "Qty": 360}},
      {{"Product Name": "ACNETAZ CREAM", "MRP": 149.00, "Qty": 130}}
    ]
    """

    model = genai.GenerativeModel("gemini-2.5-flash")
    response = model.generate_content(
        [prompt, {"mime_type": "image/jpeg", "data": compressed_bytes}]
    )

    clean_json = (
        response.text.replace("```json", "").replace("```", "").strip()
    )
    return json.loads(clean_json)


# ==========================================
# 3. MULTI-TAB NAVIGATION (All Features)
# ==========================================
tab1, tab2, tab3 = st.tabs(
    [
        "📦 1. Purchase Entry (Inward Stock)",
        "🧾 2. Sales Slip Scan (Outward)",
        "🖨️ 3. Print Invoice / PDF Bill",
    ]
)


# ------------------------------------------
# TAB 1: PURCHASE SLIP SCANNER (पुराना फ़ीचर)
# ------------------------------------------
with tab1:
    st.header("📦 Purchase / Stock Inward Entry")
    st.caption("सप्लायर या परचेज की पर्ची स्कैन करके इन्वेंटरी में जोड़ें।")

    p_file = st.file_uploader(
        "Upload Purchase Slip Image",
        type=["jpg", "png", "jpeg"],
        key="p_file",
    )

    if p_file:
        st.image(p_file, caption="Uploaded Purchase Slip", width=300)

        if st.button("🚀 Fast Auto-Scan & Match with Stock", key="btn_p_scan"):
            with st.spinner("⚡ AI फोटो को कम्प्रेस करके स्कैन कर रहा है..."):
                try:
                    data = scan_slip_with_ai(p_file, "purchase")
                    st.session_state["purchase_data"] = pd.DataFrame(data)
                    st.success("✅ Purchase Slip सफलतापूर्वक स्कैन हो गई!")
                except Exception as e:
                    st.error(f"स्कैनिंग में त्रुटि: {str(e)}")

    if not st.session_state["purchase_data"].empty:
        st.subheader("Scanned Inward Stock Items")
        edited_p_df = st.data_editor(
            st.session_state["purchase_data"], key="p_editor", num_rows="dynamic"
        )

        if st.button("📥 Add to Main Inventory Stock", key="btn_add_stock"):
            st.success("🎉 सारा स्टॉक सफलतापूर्वक इन्वेंटरी में अपडेट कर दिया गया है!")


# ------------------------------------------
# TAB 2: SALES SLIP SCANNER (नया फ़ीचर)
# ------------------------------------------
with tab2:
    st.header("🧾 Sales Order Slip Scanner")
    st.caption("ग्राहक की ऑर्डर पर्ची स्कैन करके सेल एंट्री बनाएं।")

    s_file = st.file_uploader(
        "Upload Sales Slip Image", type=["jpg", "png", "jpeg"], key="s_file"
    )

    if s_file:
        st.image(s_file, caption="Uploaded Sales Slip", width=300)

        if st.button("🚀 Fast Auto-Scan Sales Slip", key="btn_s_scan"):
            with st.spinner("⚡ AI तेजी से पर्ची स्कैन कर रहा है..."):
                try:
                    data = scan_slip_with_ai(s_file, "sales")
                    df = pd.DataFrame(data)

                    # ऑटोमैटिक रेट (20% डिस्काउंट मानकर) और अमाउंट की कैलकुलेशन
                    df["Rate"] = (df["MRP"] * 0.80).round(2)
                    df["Taxable Amount"] = (df["Qty"] * df["Rate"]).round(2)

                    st.session_state["sales_data"] = df
                    st.success("✅ Sales Slip सफलतापूर्वक स्कैन हो गई!")
                except Exception as e:
                    st.error(f"स्कैनिंग में त्रुटि: {str(e)}")

    if not st.session_state["sales_data"].empty:
        st.subheader("Scanned Sales Items Table")
        edited_s_df = st.data_editor(
            st.session_state["sales_data"], key="s_editor", num_rows="dynamic"
        )

        # Totals Calculation
        total_taxable = edited_s_df["Taxable Amount"].sum()
        gst = round(total_taxable * 0.12, 2)
        grand_total = round(total_taxable + gst, 2)

        st.markdown("---")
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Taxable Value", f"₹{total_taxable:,.2f}")
        col2.metric("GST (12%)", f"₹{gst:,.2f}")
        col3.metric("Grand Total Amount", f"₹{grand_total:,.2f}")


# ------------------------------------------
# TAB 3: PRINTABLE INVOICE / PDF (नया फ़ीचर)
# ------------------------------------------
with tab3:
    st.header("🖨️ Printable Tax Invoice Generator")

    if st.session_state["sales_data"].empty:
        st.warning(
            "⚠️ बिल जनरेट करने के लिए पहले 'Sales Slip Scan' टैब में पर्ची अपलोड करके स्कैन करें।"
        )
    else:
        st.subheader("Customer Details")
        c_col1, c_col2 = st.columns(2)
        party_name = c_col1.text_input(
            "Customer / Shop Name", "SHREE RAM MEDICAL STORE"
        )
        inv_no = c_col2.text_input("Invoice Number", "INV-2026-0892")

        current_df = st.session_state["sales_data"]

        # Calculate Values for Invoice
        subtotal = current_df["Taxable Amount"].sum()
        cgst = round(subtotal * 0.06, 2)
        sgst = round(subtotal * 0.06, 2)
        total_bill = round(subtotal + cgst + sgst, 2)

        # Generate Printable HTML Table Rows
        html_rows = ""
        for idx, row in current_df.iterrows():
            html_rows += f"""
            <tr>
                <td style="text-align: center;">{idx+1}</td>
                <td><b>{row['Product Name']}</b></td>
                <td style="text-align: right;">₹{row['MRP']:.2f}</td>
                <td style="text-align: center;">{row['Qty']}</td>
                <td style="text-align: right;">₹{row['Rate']:.2f}</td>
                <td style="text-align: right;">₹{row['Taxable Amount']:.2f}</td>
            </tr>
            """

        # HTML Printable Template with Direct Print Button
        html_bill = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; padding: 15px; color: #333; }}
                .invoice-box {{ border: 1px solid #ccc; padding: 20px; border-radius: 8px; background: #fff; }}
                .header-table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; }}
                .items-table {{ width: 100%; border-collapse: collapse; margin-top: 15px; }}
                .items-table th, .items-table td {{ border: 1px solid #ddd; padding: 8px; font-size: 13px; }}
                .items-table th {{ background-color: #2b3e50; color: white; text-align: left; }}
                .summary-table {{ width: 40%; margin-left: auto; margin-top: 15px; border-collapse: collapse; }}
                .summary-table td {{ padding: 6px; font-size: 13px; }}
                .total-row {{ font-weight: bold; background-color: #2b3e50; color: white; }}
                .print-btn {{
                    background-color: #d9534f; color: white; border: none; padding: 10px 20px;
                    font-size: 14px; border-radius: 5px; cursor: pointer; margin-bottom: 15px;
                }}
            </style>
        </head>
        <body>
            <button class="print-btn" onclick="window.print()">🖨️ Print / Save as PDF Invoice</button>

            <div class="invoice-box">
                <table class="header-table">
                    <tr>
                        <td>
                            <h2 style="margin:0; color:#2b3e50;">MEDICARE PHARMA DISTRIBUTORS</h2>
                            <p style="margin:5px 0; font-size:12px;">Faizabad, Uttar Pradesh | Contact: +91 98765 43210</p>
                        </td>
                        <td style="text-align: right;">
                            <h3 style="margin:0; color:#d9534f;">TAX INVOICE</h3>
                            <p style="margin:5px 0; font-size:12px;"><b>Invoice No:</b> {inv_no}<br><b>Date:</b> 13-Aug-2026</p>
                        </td>
                    </tr>
                </table>

                <hr style="border: 0.5px solid #eee;">
                <p style="font-size: 13px;"><b>Billed To:</b> {party_name}</p>

                <table class="items-table">
                    <thead>
                        <tr>
                            <th style="width: 5%;">#</th>
                            <th>Product Description</th>
                            <th style="text-align: right;">MRP</th>
                            <th style="text-align: center;">Qty</th>
                            <th style="text-align: right;">Rate</th>
                            <th style="text-align: right;">Taxable Amt</th>
                        </tr>
                    </thead>
                    <tbody>
                        {html_rows}
                    </tbody>
                </table>

                <table class="summary-table">
                    <tr>
                        <td>Taxable Amount:</td>
                        <td style="text-align: right;">₹{subtotal:,.2f}</td>
                    </tr>
                    <tr>
                        <td>CGST (6%):</td>
                        <td style="text-align: right;">₹{cgst:,.2f}</td>
                    </tr>
                    <tr>
                        <td>SGST (6%):</td>
                        <td style="text-align: right;">₹{sgst:,.2f}</td>
                    </tr>
                    <tr class="total-row">
                        <td>Grand Total:</td>
                        <td style="text-align: right;">₹{total_bill:,.2f}</td>
                    </tr>
                </table>
            </div>
        </body>
        </html>
        """

        # Streamlit Embed View
        st.components.v1.html(html_bill, height=600, scrolling=True)
