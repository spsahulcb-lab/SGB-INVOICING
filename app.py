from io import BytesIO
import json
import google.generativeai as genai
import pandas as pd
from PIL import Image
import streamlit as st
from streamlit_gsheets import GSheetsConnection

# ==========================================
# 0. PAGE CONFIGURATION & ORANGE-WHITE THEME
# ==========================================
st.set_page_config(
    page_title="Pharma ERP - Sales & Management Hub",
    layout="wide",
    page_icon="💊",
)

# Custom Orange & White Styling Injection
st.markdown(
    """
    <style>
    /* Main Background & Text */
    .stApp {
        background-color: #FAFAFA;
        color: #1E1E1E;
    }
    
    /* Header Bar / Accent */
    header[data-testid="stHeader"] {
        background-color: #FF6600 !important;
    }
    
    /* Custom Card Style */
    .metric-card {
        background-color: #FFFFFF;
        border-left: 5px solid #FF6600;
        padding: 15px;
        border-radius: 8px;
        box-shadow: 0 2px 5px rgba(0,0,0,0.05);
        margin-bottom: 10px;
    }
    
    /* Buttons Customization */
    .stButton>button {
        background-color: #FF6600 !important;
        color: white !important;
        border-radius: 6px !important;
        border: none !important;
        font-weight: bold !important;
        transition: 0.3s;
    }
    .stButton>button:hover {
        background-color: #E05500 !important;
        box-shadow: 0 4px 8px rgba(255, 102, 0, 0.3);
    }

    /* Tab Styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        background-color: #FFFFFF;
        border-radius: 6px 6px 0px 0px;
        padding: 8px 16px;
        color: #444444;
    }
    .stTabs [aria-selected="true"] {
        background-color: #FF6600 !important;
        color: white !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ==========================================
# 1. PERMANENT CLOUD DB ENGINE
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
# 2. AI & SESSION INITIALIZATION
# ==========================================
if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])


def get_empty_invoice_df():
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


# Session Buffers
if "sales_data" not in st.session_state:
    st.session_state["sales_data"] = get_empty_invoice_df()

if "scanned_s_party" not in st.session_state:
    st.session_state["scanned_s_party"] = ""

# Master Defaults
default_salesmen = pd.DataFrame(
    [
        {
            "Salesman ID": "SM101",
            "Name": "Rahul Verma",
            "Mobile": "9876543210",
            "Target (₹)": 500000,
        },
        {
            "Salesman ID": "SM102",
            "Name": "Amit Sharma",
            "Mobile": "9876543211",
            "Target (₹)": 400000,
        },
    ]
)

default_party = pd.DataFrame(
    [
        {
            "Party Name": "SHREE RAM MEDICAL STORE",
            "Type": "Customer",
            "City": "Faizabad",
            "GSTIN": "09AAAAA0000A1Z5",
        },
        {
            "Party Name": "MEDICARE PHARMA DISTRIBUTORS",
            "Type": "Supplier",
            "City": "Lucknow",
            "GSTIN": "09BBBBB1111B1Z2",
        },
    ]
)

# Persistent Data Loading
salesmen_df = load_cloud_table("salesmen_master", default_salesmen)
party_df = load_cloud_table("party_master", default_party)
sales_hist_df = load_cloud_table("sales_history", pd.DataFrame())
ledger_df = load_cloud_table("ledger_transactions", pd.DataFrame())

# ==========================================
# 3. SIDEBAR: ROLE & USER LOGIN
# ==========================================
st.sidebar.image(
    "https://img.icons8.com/color/96/pill.png", width=60
)
st.sidebar.title("💊 Pharma ERP System")

user_role = st.sidebar.radio(
    "👤 Select Your Role (अपना रोल चुनें):",
    ["Sales Executive (सेल्समैन)", "Manager / Owner (मैनेजर)"],
)

current_salesman = "Admin"
if user_role == "Sales Executive (सेल्समैन)":
    salesman_list = salesmen_df["Name"].tolist() if not salesmen_df.empty else ["Default Salesman"]
    current_salesman = st.sidebar.selectbox("🔑 Select Your Name (अपना नाम चुनें):", salesman_list)
    st.sidebar.info(f"Logged as: **{current_salesman}**")
else:
    admin_password = st.sidebar.text_input("🔐 Manager PIN / Password:", type="password")
    if admin_password != "1234":  # आप पासवर्ड बदल सकते हैं
        st.sidebar.warning("मैनेजर पैनल एक्सेस करने के लिए सही पिन (1234) दर्ज करें।")

# ==========================================
# 4. CACHED AI SCANNER ENGINE
# ==========================================
@st.cache_data(ttl=3600)
def get_cached_working_models():
    try:
        active_models = []
        for m in genai.list_models():
            if "generateContent" in m.supported_generation_methods:
                active_models.append(m.name.replace("models/", ""))
        flash_models = [m for m in active_models if "flash" in m.lower()]
        return flash_models if flash_models else ["gemini-1.5-flash"]
    except Exception:
        return ["gemini-1.5-flash"]


def scan_slip_ai(uploaded_file):
    prompt = """
    Extract handwritten pharma invoice items into JSON format with keys:
    "Party Name" and "Items" array containing "Product Name", "MRP", "Qty", "Free Deal", "Rate", "Disc %", "GST %".
    """
    models = get_cached_working_models()
    for m in models:
        try:
            res = genai.GenerativeModel(m).generate_content(
                [prompt, {"mime_type": uploaded_file.type, "data": uploaded_file.getvalue()}]
            )
            if res and res.text:
                clean = res.text.replace("```json", "").replace("```", "").strip()
                return json.loads(clean)
        except Exception:
            continue
    return {}

# ==========================================
# 5. APP INTERFACE BASED ON ROLE
# ==========================================

# ------------------------------------------
# OPTION A: SALES EXECUTIVE APP VIEW
# ------------------------------------------
if user_role == "Sales Executive (सेल्समैन)":
    st.markdown(f"### 🍊 Sales Dashboard — Welcome, **{current_salesman}**")

    st_tab1, st_tab2 = st.tabs(["📝 New Sales Invoice (नया बिल बनाएं)", "📊 My Daily Sales (मेरी बिक्री)"])

    with st_tab1:
        c1, c2 = st.columns([1, 1])
        with c1:
            s_file = st.file_uploader("📷 Upload Slip Image (optional)", type=["jpg", "png", "jpeg"])
            if s_file and st.button("🚀 Auto-Scan Bill"):
                with st.spinner("Scanning..."):
                    parsed = scan_slip_ai(s_file)
                    if parsed:
                        st.session_state["sales_data"] = pd.DataFrame(parsed.get("Items", []))
                        st.session_state["scanned_s_party"] = parsed.get("Party Name", "")
                        st.success("✅ Scanning Done!")

        with c2:
            cust_list = party_df[party_df["Type"] == "Customer"]["Party Name"].tolist() if not party_df.empty else []
            s_party = st.selectbox("🏬 Select Party/Customer", cust_list if cust_list else ["Cash"])
            inv_no = st.text_input("📄 Invoice No.", f"INV-{pd.Timestamp.now().strftime('%d%m%H%M')}")

        st.subheader("📦 Invoice Items Grid")
        edited_s = st.data_editor(st.session_state["sales_data"], num_rows="dynamic", use_container_width=True)

        # Calculation Engine
        edited_s["Gross"] = edited_s["Qty"] * edited_s["Rate"]
        edited_s["Net Amt"] = edited_s["Gross"] - (edited_s["Gross"] * edited_s["Disc %"] / 100)
        edited_s["Total Inc Tax"] = edited_s["Net Amt"] * (1 + edited_s["GST %"] / 100)
        tot_bill_val = edited_s["Total Inc Tax"].sum()

        st.markdown(f"#### 💰 Total Invoice Value: **₹{tot_bill_val:,.2f}**")

        if st.button("💾 Save Bill & Send to Manager"):
            valid_df = edited_s[edited_s["Product Name"].astype(str).str.strip() != ""].copy()
            valid_df["Party Name"] = s_party
            valid_df["Invoice No"] = inv_no
            valid_df["Date"] = pd.Timestamp.now().strftime("%Y-%m-%d")
            valid_df["Salesman"] = current_salesman

            updated_sales = pd.concat([sales_hist_df, valid_df], ignore_index=True)
            save_cloud_table(updated_sales, "sales_history")

            # Post to Ledger
            new_ledger = {
                "Date": pd.Timestamp.now().strftime("%Y-%m-%d"),
                "Party Name": s_party,
                "Voucher Type": "Sales Invoice",
                "Ref No": inv_no,
                "Debit (Dr)": float(tot_bill_val),
                "Credit (Cr)": 0.0,
                "Salesman": current_salesman,
                "Remarks": f"Bill generated by {current_salesman}",
            }
            updated_ledger = pd.concat([ledger_df, pd.DataFrame([new_ledger])], ignore_index=True)
            save_cloud_table(updated_ledger, "ledger_transactions")

            st.session_state["sales_data"] = get_empty_invoice_df()
            st.success("🎉 बिल सफलतापूर्वक सेव हो गया और मास्टर ऐप पर सिंक हो गया!")

    with st_tab2:
        st.subheader(f"📈 Today's Performance for {current_salesman}")
        if not sales_hist_df.empty and "Salesman" in sales_hist_df.columns:
            my_sales = sales_hist_df[sales_hist_df["Salesman"] == current_salesman]
            st.metric("Total Bills Generated", len(my_sales["Invoice No"].unique()) if not my_sales.empty else 0)
            st.dataframe(my_sales, use_container_width=True)
        else:
            st.info("अभी तक कोई बिक्री दर्ज नहीं की गई है।")

# ------------------------------------------
# OPTION B: MANAGER MASTER APP VIEW
# ------------------------------------------
else:
    if admin_password == "1234":
        st.markdown("### 👑 Manager Master Console — Realtime Multi-Salesman Overview")

        m_tab1, m_tab2, m_tab3 = st.tabs(
            [
                "📊 All Salesmen Performance (लीडरबोर्ड)",
                "📁 Compiled Billing Records (समेकित बिल)",
                "👥 Manage Team (सेल्समैन जोड़ें)",
            ]
        )

        with m_tab1:
            st.subheader("🏆 Salesmen Live Leaderboard")

            if not sales_hist_df.empty and "Salesman" in sales_hist_df.columns:
                perf_df = (
                    sales_hist_df.groupby("Salesman")
                    .agg(
                        Total_Sales=("Total Inc Tax", "sum"),
                        Total_Orders=("Invoice No", "nunique"),
                    )
                    .reset_index()
                )

                col_a, col_b = st.columns([1, 2])
                with col_a:
                    st.dataframe(perf_df, use_container_width=True)
                with col_b:
                    st.bar_chart(perf_df, x="Salesman", y="Total_Sales")
            else:
                st.info("डेटाबेस में अभी कोई सेल रिकॉर्ड नहीं है।")

        with m_tab2:
            st.subheader("🔍 Consolidated Bills Filter & Download")

            col_f1, col_f2 = st.columns(2)
            with col_f1:
                selected_sm = st.selectbox(
                    "Filter by Salesman:",
                    ["All Salesmen"] + (salesmen_df["Name"].tolist() if not salesmen_df.empty else []),
                )

            filtered_df = sales_hist_df.copy()
            if selected_sm != "All Salesmen" and not filtered_df.empty and "Salesman" in filtered_df.columns:
                filtered_df = filtered_df[filtered_df["Salesman"] == selected_sm]

            st.dataframe(filtered_df, use_container_width=True)

            if not filtered_df.empty:
                csv = filtered_df.to_csv(index=False).encode("utf-8")
                st.download_button(
                    "📥 Download Consolidated Excel/CSV Report",
                    data=csv,
                    file_name="Master_Sales_Report.csv",
                    mime="text/csv",
                )

        with m_tab3:
            st.subheader("➕ Add / Manage Sales Executives")

            with st.form("add_sm_form"):
                sm_id = st.text_input("Salesman ID", f"SM{len(salesmen_df)+101}")
                sm_name = st.text_input("Salesman Name")
                sm_mob = st.text_input("Mobile No.")
                sm_target = st.number_input("Monthly Target (₹)", value=500000)

                if st.form_submit_button("Save Salesman") and sm_name:
                    new_sm = pd.DataFrame(
                        [
                            {
                                "Salesman ID": sm_id,
                                "Name": sm_name,
                                "Mobile": sm_mob,
                                "Target (₹)": sm_target,
                            }
                        ]
                    )
                    updated_sm_master = pd.concat([salesmen_df, new_sm], ignore_index=True)
                    save_cloud_table(updated_sm_master, "salesmen_master")
                    st.success(f"✅ सेल्समैन '{sm_name}' टीम में जुड़ गया!")

            st.dataframe(salesmen_df, use_container_width=True)
