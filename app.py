import base64
from io import BytesIO
import json
import google.generativeai as genai
import pandas as pd
from PIL import Image, ImageDraw, ImageFont
import streamlit as st
from streamlit_gsheets import GSheetsConnection

# ==========================================
# 1. PAGE SETUP & ORANGE-WHITE THEME
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
# 2. CLOUD DATABASE CONNECTION (Google Sheets)
# ==========================================
conn = st.connection("gsheets", type=GSheetsConnection)


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
# 3. MATH ENGINE & JPG INVOICE GENERATOR
# ==========================================
def safe_calculate_bill(df):
    """TypeError और स्ट्रिंग एरर फिक्स करने वाला मैथ इंजन"""
    calc_df = df.copy()
    cols = ["MRP", "Qty", "Free Deal", "Rate", "Disc %", "GST %"]
    for c in cols:
        if c in calc_df.columns:
            calc_df[c] = pd.to_numeric(calc_df[c], errors="coerce").fillna(0.0)

    calc_df["Gross"] = calc_df["Qty"] * calc_df["Rate"]
    calc_df["Disc_Amt"] = (calc_df["Gross"] * calc_df["Disc %"]) / 100.0
    calc_df["Taxable"] = calc_df["Gross"] - calc_df["Disc_Amt"]
    calc_df["GST_Amt"] = (calc_df["Taxable"] * calc_df["GST %"]) / 100.0
    calc_df["Net_Amt"] = (calc_df["Taxable"] + calc_df["GST_Amt"]).round(2)
    return calc_df


def generate_jpg_invoice(party_name, inv_no, date_str, items_df, grand_total):
    """Pillow लाइब्रेरी की मदद से बिल की HD JPG फोटो जनरेट करता है"""
    width, height = 800, 1000
    img = Image.new("RGB", (width, height), color="white")
    draw = ImageDraw.Draw(img)

    # 1. Header (Orange Banner)
    draw.rectangle([(0, 0), (width, 90)], fill="#FF6600")
    draw.text(
        (30, 30),
        "PHARMA DISTRIBUTORS - INVOICE",
        fill="white",
        font_size=26,
    )

    # 2. Invoice Metadata
    draw.text((30, 110), f"Invoice No: {inv_no}", fill="#333333", font_size=18)
    draw.text((450, 110), f"Date: {date_str}", fill="#333333", font_size=18)
    draw.text(
        (30, 145), f"Customer: {party_name}", fill="#333333", font_size=18
    )

    # 3. Table Headers
    draw.rectangle([(30, 190), (770, 230)], fill="#FF6600")
    draw.text((40, 202), "Product Name", fill="white", font_size=16)
    draw.text((320, 202), "Qty", fill="white", font_size=16)
    draw.text((410, 202), "Rate", fill="white", font_size=16)
    draw.text((510, 202), "GST %", fill="white", font_size=16)
    draw.text((640, 202), "Net Total (₹)", fill="white", font_size=16)

    # 4. Items Rows
    y_pos = 250
    for _, r in items_df.iterrows():
        p_name = str(r.get("Product Name", ""))[:22]
        qty = str(int(r.get("Qty", 0)))
        rate = f"₹{r.get('Rate', 0):.2f}"
        gst = f"{r.get('GST %', 0):.1f}%"
        net_amt = f"₹{r.get('Net_Amt', 0):,.2f}"

        draw.text((40, y_pos), p_name, fill="#1E1E1E", font_size=15)
        draw.text((320, y_pos), qty, fill="#1E1E1E", font_size=15)
        draw.text((410, y_pos), rate, fill="#1E1E1E", font_size=15)
        draw.text((510, y_pos), gst, fill="#1E1E1E", font_size=15)
        draw.text((640, y_pos), net_amt, fill="#1E1E1E", font_size=15)

        y_pos += 30
        draw.line([(30, y_pos), (770, y_pos)], fill="#E0E0E0", width=1)
        y_pos += 10

    # 5. Grand Total Section
    y_pos += 20
    draw.rectangle(
        [(30, y_pos), (770, y_pos + 50)], fill="#FFF3EB", outline="#FF6600"
    )
    draw.text(
        (50, y_pos + 14),
        f"Grand Total Payable: ₹{grand_total:,.2f}",
        fill="#FF6600",
        font_size=20,
    )

    # Output Bytes
    buffer = BytesIO()
    img.save(buffer, format="JPEG", quality=95)
    buffer.seek(0)
    return buffer.getvalue()


# ==========================================
# 4. INITIALIZATION & SIDEBAR
# ==========================================
if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])


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

# Master Tables
default_party = pd.DataFrame(
    [
        {"Party Name": "SHREE RAM MEDICAL STORE", "Type": "Customer", "Mobile": "9876543210"},
        {"Party Name": "MEDICARE PHARMA DISTRIBUTORS", "Type": "Supplier", "Mobile": "9876543211"},
    ]
)

party_df = load_cloud_table("party_master", default_party)
sales_hist_df = load_cloud_table("sales_history", pd.DataFrame())
purchase_hist_df = load_cloud_table("purchase_history", pd.DataFrame())

# Sidebar Menu
st.sidebar.image("https://img.icons8.com/color/96/pill.png", width=50)
st.sidebar.title("💊 Pharma ERP Menu")

user_role = st.sidebar.radio("👤 Choose Role:", ["Sales Executive", "Manager"])
user_name = st.sidebar.text_input("✍️ Enter Your Name:", value="Rahul")

pwd = ""
if user_role == "Manager":
    pwd = st.sidebar.text_input("🔐 Manager PIN:", type="password")

# Module Navigation
tabs_list = [
    "🧾 Sales Invoice",
    "📦 Purchase Entry",
    "📊 Live Stock Inventory",
]
if user_role == "Manager":
    tabs_list.append("👑 Manager Monitoring")

active_tab = st.selectbox("📌 Select Module:", tabs_list)

# ==========================================
# MODULE 1: SALES INVOICE & JPG / WHATSAPP SHARE
# ==========================================
if active_tab == "🧾 Sales Invoice":
    st.header("🧾 New Sales Invoice (JPG & WhatsApp Direct)")

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

    st.subheader("📦 Invoice Line Items")
    edited_sales = st.data_editor(
        st.session_state["sales_data"], num_rows="dynamic", use_container_width=True
    )

    # Safe Calculations
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

                updated_history = pd.concat([sales_hist_df, valid_items], ignore_index=True)
                save_cloud_table(updated_history, "sales_history")
                st.success("🎉 बिल सफलतापूर्वक Google Sheets पर सेव हो गया!")
            except Exception as e:
                st.error(f"Save Error: {e}")

    with col_btn2:
        # JPG Generation & Share
        valid_items_jpg = calc_sales_df[
            calc_sales_df["Product Name"].astype(str).str.strip() != ""
        ].copy()

        if not valid_items_jpg.empty:
            jpg_bytes = generate_jpg_invoice(
                s_party,
                s_inv_no,
                pd.Timestamp.now().strftime("%Y-%m-%d"),
                valid_items_jpg,
                grand_total,
            )

            # JPG Image Download Button
            st.download_button(
                label="🖼️ Download JPG Bill Image",
                data=jpg_bytes,
                file_name=f"{s_inv_no}_{s_party}.jpg",
                mime="image/jpeg",
            )

            # WhatsApp Direct Share Link
            msg_text = f"नमस्कार {s_party}, आपका बिल #{s_inv_no} तैयार है। कुल राशि: ₹{grand_total:,.2f}। धन्यवाद!"
            wa_url = f"https://api.whatsapp.com/send?text={msg_text}"
            st.markdown(f"[📲 WhatsApp पर बिल टेक्स्ट शेयर करें]({wa_url})", unsafe_allow_html=True)

            # Live Invoice Image Preview
            st.image(jpg_bytes, caption="🖼️ Generated JPG Bill Preview", width=420)

# ==========================================
# MODULE 2: PURCHASE ENTRY
# ==========================================
elif active_tab == "📦 Purchase Entry":
    st.header("📦 Purchase Inward Entry")
    supp_list = (
        party_df[party_df["Type"] == "Supplier"]["Party Name"].tolist()
        if not party_df.empty
        else ["Default Supplier"]
    )
    p_party = st.selectbox("🏭 Supplier Name", supp_list)
    p_inv_no = st.text_input("📄 Purchase Bill No.", "PUR-101")

    p_df = st.data_editor(get_empty_df(), key="p_grid", num_rows="dynamic")
    calc_p_df = safe_calculate_bill(p_df)

    if st.button("📥 Save Purchase Stock"):
        valid_p = calc_p_df[calc_p_df["Product Name"].astype(str).str.strip() != ""].copy()
        valid_p["Party Name"] = p_party
        valid_p["Invoice No"] = p_inv_no
        valid_p["Date"] = pd.Timestamp.now().strftime("%Y-%m-%d")

        updated_pur = pd.concat([purchase_hist_df, valid_p], ignore_index=True)
        save_cloud_table(updated_pur, "purchase_history")
        st.success("✅ परचेज स्टॉक Google Sheets पर अपडेट हो गया!")

# ==========================================
# MODULE 3: LIVE STOCK INVENTORY
# ==========================================
elif active_tab == "📊 Live Stock Inventory":
    st.header("📊 Live Stock Inventory Balance")

    p_hist = purchase_hist_df if not purchase_hist_df.empty else pd.DataFrame()
    s_hist = sales_hist_df if not sales_hist_df.empty else pd.DataFrame()

    if p_hist.empty and s_hist.empty:
        st.info("डेटाबेस में अभी कोई स्टॉक रिकॉर्ड नहीं मिला।")
    else:
        p_tot = (
            p_hist.groupby("Product Name")["Qty"].sum().reset_index(name="Purchased")
            if not p_hist.empty
            else pd.DataFrame(columns=["Product Name", "Purchased"])
        )
        s_tot = (
            s_hist.groupby("Product Name")["Qty"].sum().reset_index(name="Sold")
            if not s_hist.empty
            else pd.DataFrame(columns=["Product Name", "Sold"])
        )

        stock_df = pd.merge(p_tot, s_tot, on="Product Name", how="outer").fillna(0)
        stock_df["Available Stock"] = stock_df["Purchased"] - stock_df["Sold"]
        st.dataframe(stock_df, use_container_width=True)

# ==========================================
# MODULE 4: MANAGER MONITORING DASHBOARD
# ==========================================
elif active_tab == "👑 Manager Monitoring" and user_role == "Manager":
    if pwd == "1234":
        st.header("👑 Manager Realtime Monitoring Console")

        if not sales_hist_df.empty and "Salesman" in sales_hist_df.columns:
            st.subheader("📊 Salesman Leaderboard & Performance")
            summary = (
                sales_hist_df.groupby("Salesman")["Net_Amt"]
                .sum()
                .reset_index(name="Total Sales (₹)")
            )
            st.dataframe(summary, use_container_width=True)
            st.bar_chart(summary.set_index("Salesman"))

            st.subheader("📁 Complete Compiled Sales History Log")
            st.dataframe(sales_hist_df, use_container_width=True)
        else:
            st.info("निगरानी के लिए अभी कोई बिक्री रिकॉर्ड उपलब्ध नहीं है।")
    else:
        st.warning("कृपया सही मैनेजर पिन (1234) दर्ज करें।")
