import json
from io import BytesIO
import google.generativeai as genai
import pandas as pd
from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
import streamlit as st
from streamlit_gsheets import GSheetsConnection

# ==========================================
# 1. PAGE SETUP & THEME STYLING
# ==========================================
st.set_page_config(
    page_title="Pharma ERP - Smart Invoicing & Management",
    layout="wide",
    page_icon="💊",
)

st.markdown(
    """
    <style>
    .stApp { background-color: #FAFAFA; }
    header[data-testid="stHeader"] { background-color: #FF6600 !important; }
    .stButton>button {
        background-color: #FF6600 !important;
        color: white !important;
        border-radius: 6px !important;
        border: none !important;
        font-weight: bold !important;
    }
    .stButton>button:hover { background-color: #E05500 !important; }
    .stTabs [aria-selected="true"] {
        background-color: #FF6600 !important;
        color: white !important;
    }
    </style>
""",
    unsafe_allow_html=True,
)

# ==========================================
# 2. CLOUD DATABASE & AI GEMINI SETUP
# ==========================================
conn = st.connection("gsheets", type=GSheetsConnection)

if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])


def load_cloud_table(worksheet_name, default_df):
    try:
        df = conn.read(worksheet=worksheet_name, ttl="0s")
        return df if not df.empty else default_df
    except Exception:
        return default_df


def save_cloud_table(df, worksheet_name):
    try:
        conn.update(worksheet=worksheet_name, data=df)
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Cloud Save Error: {e}")


# ==========================================
# MULTI-MODEL DYNAMIC FALLBACK OCR ENGINE
# ==========================================
def scan_bill_with_gemini(uploaded_file):
    prompt = """
    Extract medicine items from this invoice or prescription photo into a clean JSON list.
    Each item must strictly follow these keys:
    "Product Name" (str), "MRP" (float), "Qty" (int), "Free Deal" (int), "Rate" (float), "Disc %" (float), "GST %" (float).
    If GST % is not explicitly visible or mentioned, default "GST %" to 5.0.
    Output ONLY valid JSON array without any markdown formatting or extra text.
    """
    try:
        image = Image.open(uploaded_file)
        candidate_models = []

        # API Key ke zariye active models fetch karna
        try:
            for m in genai.list_models():
                if "generateContent" in m.supported_generation_methods:
                    clean_name = m.name.replace("models/", "")
                    candidate_models.append(clean_name)
        except Exception:
            pass

        # Fallback candidate models
        fallback_list = ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.0-flash"]
        for fb in fallback_list:
            if fb not in candidate_models:
                candidate_models.append(fb)

        last_err = None
        for model_id in candidate_models:
            try:
                model = genai.GenerativeModel(model_id)
                response = model.generate_content([prompt, image])
                clean_json = (
                    response.text.strip()
                    .replace("```json", "")
                    .replace("```", "")
                    .strip()
                )
                parsed_data = json.loads(clean_json)
                df_extracted = pd.DataFrame(parsed_data)

                if "GST %" not in df_extracted.columns:
                    df_extracted["GST %"] = 5.0
                else:
                    df_extracted["GST %"] = df_extracted["GST %"].apply(
                        lambda x: 5.0 if pd.isna(x) or float(x) == 0 else float(x)
                    )
                return df_extracted
            except Exception as e:
                last_err = e
                continue

        st.error(f"AI Scan Error: {last_err}")
        return None
    except Exception as err:
        st.error(f"File Loading Error: {err}")
        return None


# ==========================================
# 3. HELPER FUNCTIONS: PDF & MATH ENGINE
# ==========================================
def safe_calculate_bill(df):
    calc_df = df.copy()
    cols = ["MRP", "Qty", "Free Deal", "Rate", "Disc %", "GST %"]
    for c in cols:
        if c in calc_df.columns:
            calc_df[c] = pd.to_numeric(calc_df[c], errors="coerce").fillna(0.0)
        else:
            calc_df[c] = 5.0 if c == "GST %" else 0.0

    calc_df["Gross"] = calc_df["Qty"] * calc_df["Rate"]
    calc_df["Disc_Amt"] = (calc_df["Gross"] * calc_df["Disc %"]) / 100.0
    calc_df["Taxable"] = calc_df["Gross"] - calc_df["Disc_Amt"]
    calc_df["GST_Amt"] = (calc_df["Taxable"] * calc_df["GST %"]) / 100.0
    calc_df["Net_Amt"] = (calc_df["Taxable"] + calc_df["GST_Amt"]).round(2)
    return calc_df


def generate_pdf_invoice(party_name, inv_no, date_str, items_df, grand_total):
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=30,
        leftMargin=30,
        topMargin=30,
        bottomMargin=30,
    )
    elements = []
    styles = getSampleStyleSheet()

    elements.append(
        Paragraph(
            "<b><font size=16 color='#FF6600'>PHARMA DISTRIBUTORS - INVOICE</font></b>",
            styles["Normal"],
        )
    )
    elements.append(Spacer(1, 10))

    meta_text = f"""
    <b>Invoice No:</b> {inv_no} | <b>Date:</b> {date_str}<br/>
    <b>Customer/Party:</b> {party_name}
    """
    elements.append(Paragraph(meta_text, styles["Normal"]))
    elements.append(Spacer(1, 15))

    table_data = [
        ["Product Name", "MRP", "Qty", "Free", "Rate", "Disc %", "GST %", "Net Total"]
    ]
    for _, r in items_df.iterrows():
        table_data.append(
            [
                str(r.get("Product Name", "")),
                f"{r.get('MRP', 0):.2f}",
                str(int(r.get("Qty", 0))),
                str(int(r.get("Free Deal", 0))),
                f"{r.get('Rate', 0):.2f}",
                f"{r.get('Disc %', 0):.1f}%",
                f"{r.get('GST %', 5.0):.1f}%",
                f"₹{r.get('Net_Amt', 0):,.2f}",
            ]
        )

    t = Table(table_data, colWidths=[150, 45, 35, 35, 50, 45, 45, 75])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#FF6600")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ]
        )
    )
    elements.append(t)
    elements.append(Spacer(1, 15))

    elements.append(
        Paragraph(
            f"<b><font size=12 color='#000000'>Grand Total Payable: ₹{grand_total:,.2f}</font></b>",
            styles["Normal"],
        )
    )

    doc.build(elements)
    buffer.seek(0)
    return buffer.getvalue()


# ==========================================
# 4. INITIALIZATION & SESSION STATE
# ==========================================
def get_empty_df():
    return pd.DataFrame(
        [
            {
                "Product Name": "",
                "MRP": 0.0,
                "Qty": 0,
                "Free Deal": 0,
                "Rate": 0.0,
                "Disc %": 0.0,
                "GST %": 5.0,
            }
        ]
    )


if "sales_data" not in st.session_state:
    st.session_state["sales_data"] = get_empty_df()

if "purchase_data" not in st.session_state:
    st.session_state["purchase_data"] = get_empty_df()

default_party = pd.DataFrame(
    [
        {
            "Party Name": "SHREE RAM MEDICAL STORE",
            "Type": "Customer",
            "Mobile": "9876543210",
        },
        {
            "Party Name": "MEDICARE PHARMA DISTRIBUTORS",
            "Type": "Supplier",
            "Mobile": "9876543211",
        },
    ]
)

party_df = load_cloud_table("party_master", default_party)
sales_hist_df = load_cloud_table("sales_history", pd.DataFrame())
purchase_hist_df = load_cloud_table("purchase_history", pd.DataFrame())

st.sidebar.image("https://img.icons8.com/color/96/pill.png", width=50)
st.sidebar.title("💊 Pharma ERP Menu")

user_role = st.sidebar.radio("👤 Choose Role:", ["Sales Executive", "Manager"])
user_name = st.sidebar.text_input("✍️ Enter Your Name:", value="Rahul")

pwd = ""
if user_role == "Manager":
    pwd = st.sidebar.text_input("🔐 Manager PIN:", type="password")

# ==========================================
# 5. MODULE NAVIGATION & UI
# ==========================================
tabs_list = [
    "🧾 Sales Invoice",
    "📦 Purchase Entry",
    "📊 Live Stock Inventory",
]
if user_role == "Manager":
    tabs_list.append("👑 Manager Monitoring")

active_tab = st.selectbox("📌 Select Module:", tabs_list)

# ------------------------------------------
# TAB 1: SALES INVOICE
# ------------------------------------------
if active_tab == "🧾 Sales Invoice":
    st.header("🧾 New Sales Bill & PDF Generator")

    c1, c2 = st.columns(2)
    with c1:
        cust_list = (
            party_df[party_df["Type"] == "Customer"]["Party Name"].tolist()
            if not party_df.empty
            else ["Cash"]
        )
        s_party = st.selectbox("🏬 Customer / Party Name", cust_list)
    with c2:
        s_inv_no = st.text_input(
            "📄 Invoice No.", f"INV-{pd.Timestamp.now().strftime('%d%H%M')}"
        )

    with st.expander("📷 AI Scan Invoice / Prescription Photo", expanded=False):
        uploaded_sales_img = st.file_uploader(
            "Upload Sales Bill or Prescription Image",
            type=["jpg", "jpeg", "png"],
            key="sales_img",
        )
        if uploaded_sales_img is not None:
            st.image(uploaded_sales_img, caption="Uploaded Document", width=250)
            if st.button("Auto Scan & Fill Table"):
                with st.spinner("Fast AI Bill Scanning..."):
                    extracted_df = scan_bill_with_gemini(uploaded_sales_img)
                    if extracted_df is not None and not extracted_df.empty:
                        st.session_state["sales_data"] = extracted_df
                        st.success("✅ Items scanned & populated with 5% GST!")
                        st.rerun()

    st.subheader("📦 Invoice Line Items (Default GST: 5%)")
    edited_sales = st.data_editor(
        st.session_state["sales_data"], num_rows="dynamic", use_container_width=True
    )

    calc_sales_df = safe_calculate_bill(edited_sales)
    grand_total = calc_sales_df["Net_Amt"].sum()

    st.markdown(f"### 💰 Grand Total Value: **₹{grand_total:,.2f}**")

    col_btn1, col_btn2 = st.columns(2)

    with col_btn1:
        if st.button("💾 Save Bill to Cloud"):
            try:
                valid_items = calc_sales_df[
                    calc_sales_df["Product Name"].astype(str).str.strip() != ""
                ].copy()
                valid_items["Party Name"] = s_party
                valid_items["Invoice No"] = s_inv_no
                valid_items["Salesman"] = user_name
                valid_items["Date"] = pd.Timestamp.now().strftime("%Y-%m-%d")

                updated_history = pd.concat(
                    [sales_hist_df, valid_items], ignore_index=True
                )
                save_cloud_table(updated_history, "sales_history")
                st.success("🎉 Bill saved to Google Sheets!")
            except Exception as e:
                st.error(f"Save Error: {e}")

    with col_btn2:
        valid_items_pdf = calc_sales_df[
            calc_sales_df["Product Name"].astype(str).str.strip() != ""
        ].copy()

        if not valid_items_pdf.empty:
            pdf_bytes = generate_pdf_invoice(
                s_party,
                s_inv_no,
                pd.Timestamp.now().strftime("%Y-%m-%d"),
                valid_items_pdf,
                grand_total,
            )

            st.download_button(
                label="📄 Download PDF Invoice",
                data=pdf_bytes,
                file_name=f"{s_inv_no}_{s_party}.pdf",
                mime="application/pdf",
            )

            msg_text = f"नमस्कार {s_party}, आपका फार्मा बिल #{s_inv_no} तैयार है। कुल राशि: ₹{grand_total:,.2f}। धन्यवाद!"
            wa_url = f"https://api.whatsapp.com/send?text={msg_text}"
            st.markdown(
                f"[📲 Share Bill on WhatsApp]({wa_url})", unsafe_allow_html=True
            )

# ------------------------------------------
# TAB 2: PURCHASE ENTRY
# ------------------------------------------
elif active_tab == "📦 Purchase Entry":
    st.header("📦 Purchase Inward Entry")
    supp_list = (
        party_df[party_df["Type"] == "Supplier"]["Party Name"].tolist()
        if not party_df.empty
        else ["Default Supplier"]
    )
    p_party = st.selectbox("🏭 Supplier Name", supp_list)
    p_inv_no = st.text_input("📄 Bill No.", "PUR-101")

    with st.expander("📷 AI Scan Purchase Bill Photo", expanded=False):
        uploaded_pur_img = st.file_uploader(
            "Upload Purchase Invoice Image",
            type=["jpg", "jpeg", "png"],
            key="pur_img",
        )
        if uploaded_pur_img is not None:
            st.image(uploaded_pur_img, caption="Purchase Bill Image", width=250)
            if st.button("🔍 Scan Purchase Invoice"):
                with st.spinner("Fast AI Processing..."):
                    extracted_p_df = scan_bill_with_gemini(uploaded_pur_img)
                    if extracted_p_df is not None and not extracted_p_df.empty:
                        st.session_state["purchase_data"] = extracted_p_df
                        st.success("✅ Purchase items populated with 5% GST!")
                        st.rerun()

    p_df = st.data_editor(
        st.session_state["purchase_data"],
        key="p_grid",
        num_rows="dynamic",
        use_container_width=True,
    )
    calc_p_df = safe_calculate_bill(p_df)

    if st.button("📥 Save Purchase Stock"):
        valid_p = calc_p_df[
            calc_p_df["Product Name"].astype(str).str.strip() != ""
        ].copy()
        valid_p["Party Name"] = p_party
        valid_p["Invoice No"] = p_inv_no
        valid_p["Date"] = pd.Timestamp.now().strftime("%Y-%m-%d")

        updated_pur = pd.concat([purchase_hist_df, valid_p], ignore_index=True)
        save_cloud_table(updated_pur, "purchase_history")
        st.success("✅ Purchase stock updated successfully!")

# ------------------------------------------
# TAB 3: LIVE STOCK INVENTORY
# ------------------------------------------
elif active_tab == "📊 Live Stock Inventory":
    st.header("📊 Stock Inventory Balance")

    p_hist = purchase_hist_df if not purchase_hist_df.empty else pd.DataFrame()
    s_hist = sales_hist_df if not sales_hist_df.empty else pd.DataFrame()

    if p_hist.empty and s_hist.empty:
        st.info("No stock data available in database.")
    else:
        p_tot = (
            p_hist.groupby("Product Name")["Qty"].sum().reset_index(name="Purchased")
            if not p_hist.empty and "Product Name" in p_hist.columns
            else pd.DataFrame(columns=["Product Name", "Purchased"])
        )
        s_tot = (
            s_hist.groupby("Product Name")["Qty"].sum().reset_index(name="Sold")
            if not s_hist.empty and "Product Name" in s_hist.columns
            else pd.DataFrame(columns=["Product Name", "Sold"])
        )

        stock_df = pd.merge(p_tot, s_tot, on="Product Name", how="outer").fillna(0)
        stock_df["Available Stock"] = stock_df["Purchased"] - stock_df["Sold"]
        st.dataframe(stock_df, use_container_width=True)

# ------------------------------------------
# TAB 4: MANAGER MONITORING
# ------------------------------------------
elif active_tab == "👑 Manager Monitoring" and user_role == "Manager":
    if pwd == "1234":
        st.header("👑 Manager Realtime Monitoring Console")

        if not sales_hist_df.empty and "Salesman" in sales_hist_df.columns:
            st.subheader("📊 Salesman Leaderboard & Total Sales")
            summary = (
                sales_hist_df.groupby("Salesman")["Net_Amt"]
                .sum()
                .reset_index(name="Total Sales (₹)")
            )
            st.dataframe(summary, use_container_width=True)
            st.bar_chart(summary.set_index("Salesman"))

            st.subheader("📁 Complete Compiled Sales Log")
            st.dataframe(sales_hist_df, use_container_width=True)
        else:
            st.info("No sales records available for monitoring yet.")
    else:
        st.warning("Please enter the correct Manager PIN (1234).")
