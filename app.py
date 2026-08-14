from io import BytesIO
import json
import google.generativeai as genai
import pandas as pd
from PIL import Image
import streamlit as st
from streamlit_gsheets import GSheetsConnection

# ==========================================
# 0. PAGE CONFIGURATION
# ==========================================
st.set_page_config(
    page_title="Pharma ERP - Permanent Cloud Data",
    layout="wide",
    page_icon="💊",
)

st.title("💊 Pharma ERP - Smart Invoicing & Permanent Cloud Database")

# ==========================================
# 1. PERMANENT GOOGLE SHEETS ENGINE
# ==========================================
conn = st.connection("gsheets", type=GSheetsConnection)


def load_cloud_table(worksheet_name, default_df):
    """Fetch data from Google Sheets; fallback to default if empty or error."""
    try:
        df = conn.read(worksheet=worksheet_name, ttl="0s")
        if df is not None and not df.empty:
            return df
        return default_df
    except Exception:
        return default_df


def save_cloud_table(df, worksheet_name):
    """Save dataframe permanently to Google Sheets."""
    try:
        conn.update(worksheet=worksheet_name, data=df)
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Cloud Save Error in {worksheet_name}: {e}")


# ==========================================
# 2. GEMINI AI CONFIGURATION
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
                "GST %": 5.0,  # Default 5.0% GST
            }
        ]
    )


# Temporary draft session state
if "purchase_data" not in st.session_state:
    st.session_state["purchase_data"] = get_empty_invoice_df()

if "sales_data" not in st.session_state:
    st.session_state["sales_data"] = get_empty_invoice_df()

if "scanned_p_party" not in st.session_state:
    st.session_state["scanned_p_party"] = ""

if "scanned_s_party" not in st.session_state:
    st.session_state["scanned_s_party"] = ""

# Load Master Tables directly from Google Sheets
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

default_ledger = pd.DataFrame(
    columns=[
        "Date",
        "Party Name",
        "Voucher Type",
        "Ref No",
        "Debit (Dr)",
        "Credit (Cr)",
        "Remarks",
    ]
)

default_history = pd.DataFrame(
    columns=[
        "Date",
        "Party Name",
        "Invoice No",
        "Product Name",
        "MRP",
        "Qty",
        "Free Deal",
        "Rate",
        "Disc %",
        "GST %",
        "Total Qty (Billed+Free)",
        "Gross Amt",
        "Disc Amt",
        "Taxable Value",
        "GST Amt",
        "Net Line Amount",
    ]
)

if "party_master" not in st.session_state:
    st.session_state["party_master"] = load_cloud_table(
        "party_master", default_party
    )

if "ledger_transactions" not in st.session_state:
    st.session_state["ledger_transactions"] = load_cloud_table(
        "ledger_transactions", default_ledger
    )

if "purchase_history" not in st.session_state:
    st.session_state["purchase_history"] = load_cloud_table(
        "purchase_history", default_history
    )

if "sales_history" not in st.session_state:
    st.session_state["sales_history"] = load_cloud_table(
        "sales_history", default_history
    )


# ==========================================
# 3. AI SCANNER ENGINE
# ==========================================
def compress_image(uploaded_file, max_dimension=1280, quality=75):
    img = Image.open(uploaded_file)
    if img.mode != "RGB":
        img = img.convert("RGB")
    img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
    buffer = BytesIO()
    img.save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue()


def get_active_vision_models():
    try:
        active_models = []
        for m in genai.list_models():
            if "generateContent" in m.supported_generation_methods:
                model_name = m.name.replace("models/", "")
                active_models.append(model_name)

        flash_models = [
            m
            for m in active_models
            if "flash" in m.lower() and "experimental" not in m.lower()
        ]
        other_models = [
            m
            for m in active_models
            if "flash" not in m.lower() and "experimental" not in m.lower()
        ]
        combined = flash_models + other_models
        return combined if combined else ["gemini-1.5-flash", "gemini-2.5-flash"]
    except Exception:
        return ["gemini-1.5-flash", "gemini-2.5-flash"]


def scan_slip_with_party_ai(uploaded_file, slip_type="sales"):
    compressed_bytes = compress_image(uploaded_file)
    prompt = f"""
    Extract billing details from this {slip_type} invoice/slip image.
    Include:
    1. Party Name
    2. Items list: "Product Name", "MRP", "Qty", "Free Deal", "Rate", "Disc %", "GST %" (default 5.0)

    Return ONLY JSON:
    {{
      "Party Name": "STORE NAME",
      "Items": [
        {{"Product Name": "ITEM", "MRP": 100.0, "Qty": 10, "Free Deal": 0, "Rate": 80.0, "Disc %": 0.0, "GST %": 5.0}}
      ]
    }}
    """
    available_models = get_active_vision_models()
    response = None
    last_error = None

    for model_name in available_models:
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(
                [prompt, {"mime_type": "image/jpeg", "data": compressed_bytes}]
            )
            if response and response.text:
                break
        except Exception as e:
            last_error = e
            continue

    if not response or not response.text:
        raise Exception(f"Scanning failed: {last_error}")

    clean_json = (
        response.text.replace("```json", "").replace("```", "").strip()
    )
    return json.loads(clean_json)


# ==========================================
# 4. CALCULATOR ENGINE
# ==========================================
def calculate_pharma_bill(df, is_sales=False):
    df_calc = df.copy()
    numeric_cols = ["MRP", "Qty", "Free Deal", "Rate", "Disc %", "GST %"]
    for col in numeric_cols:
        if col in df_calc.columns:
            df_calc[col] = pd.to_numeric(df_calc[col], errors="coerce").fillna(0)

    # Auto-fetch MRP, Rate & GST from historical purchases for Sales
    if is_sales and not st.session_state["purchase_history"].empty:
        p_history = st.session_state["purchase_history"]
        if "Product Name" in p_history.columns:
            stock_lookup = (
                p_history.groupby("Product Name")
                .last()[["MRP", "Rate", "GST %"]]
                .to_dict("index")
            )

            for idx, row in df_calc.iterrows():
                p_name = str(row["Product Name"]).strip()
                if p_name in stock_lookup:
                    matched = stock_lookup[p_name]
                    if float(row["MRP"]) == 0.0 and "MRP" in matched:
                        df_calc.at[idx, "MRP"] = float(matched["MRP"])
                    if float(row["Rate"]) == 0.0 and "Rate" in matched:
                        df_calc.at[idx, "Rate"] = float(matched["Rate"])
                    if float(row["GST %"]) == 0.0 and "GST %" in matched:
                        df_calc.at[idx, "GST %"] = float(matched["GST %"])

    df_calc["Total Qty (Billed+Free)"] = df_calc["Qty"] + df_calc["Free Deal"]
    df_calc["Gross Amt"] = df_calc["Qty"] * df_calc["Rate"]
    df_calc["Disc Amt"] = (df_calc["Gross Amt"] * df_calc["Disc %"]) / 100.0
    df_calc["Taxable Value"] = df_calc["Gross Amt"] - df_calc["Disc Amt"]
    df_calc["GST Amt"] = (df_calc["Taxable Value"] * df_calc["GST %"]) / 100.0
    df_calc["Net Line Amount"] = (
        df_calc["Taxable Value"] + df_calc["GST Amt"]
    ).round(2)

    return df_calc


# ==========================================
# 5. TABS INTERFACE
# ==========================================
tab1, tab2, tab3, tab4, tab5 = st.tabs(
    [
        "📦 1. Purchase Invoice",
        "🧾 2. Sales Invoice",
        "📒 3. Party Ledger",
        "📊 4. Live Stock Inventory",
        "⚙️ 5. Party Master & Vouchers",
    ]
)

# ------------------------------------------
# TAB 1: PURCHASE INVOICE
# ------------------------------------------
with tab1:
    st.header("📦 Purchase Invoice (Inward Entry)")
    col_p1, col_p2 = st.columns([1, 1])

    with col_p1:
        p_file = st.file_uploader(
            "Upload Purchase Slip Image",
            type=["jpg", "png", "jpeg"],
            key="p_file",
        )
        if p_file:
            st.image(p_file, caption="Uploaded Slip", width=180)
            if st.button("🚀 Auto-Scan Purchase Bill", key="btn_p_scan"):
                with st.spinner("⚡ AI स्कैनिंग चल रही है..."):
                    try:
                        res = scan_slip_with_party_ai(p_file, "purchase")
                        st.session_state["purchase_data"] = pd.DataFrame(
                            res.get("Items", [])
                        )
                        st.session_state["scanned_p_party"] = res.get(
                            "Party Name", ""
                        )
                        st.success("✅ स्कैन पूरा हो गया!")
                    except Exception as e:
                        st.error(f"स्कैन त्रुटि: {str(e)}")

    with col_p2:
        p_suppliers = st.session_state["party_master"][
            st.session_state["party_master"]["Type"] == "Supplier"
        ]["Party Name"].tolist()
        default_s = (
            st.session_state["scanned_p_party"]
            if st.session_state["scanned_p_party"]
            else (
                p_suppliers[0]
                if p_suppliers
                else "MEDICARE PHARMA DISTRIBUTORS"
            )
        )

        final_p_party = st.text_input(
            "✏️ Party / Supplier Name", value=default_s, key="txt_p_party"
        )
        p_inv_no = st.text_input(
            "✏️ Bill No.", "PUR-2026-001", key="txt_p_inv"
        )

    st.markdown("---")
    edited_p_df = st.data_editor(
        st.session_state["purchase_data"],
        key="p_table_editor",
        num_rows="dynamic",
        use_container_width=True,
    )

    calc_p_df = calculate_pharma_bill(edited_p_df, is_sales=False)
    p_grand_total = calc_p_df["Net Line Amount"].sum()
    st.info(f"💰 Total Purchase Amount Payable: ₹{p_grand_total:,.2f}")

    if st.button("📥 Save Purchase Invoice", key="btn_save_pur_final"):
        if not final_p_party.strip():
            st.error("⚠️ कृपया सप्लायर का नाम दर्ज करें!")
        else:
            valid_p = calc_p_df[
                calc_p_df["Product Name"].astype(str).str.strip() != ""
            ].copy()
            valid_p["Party Name"] = final_p_party
            valid_p["Invoice No"] = p_inv_no
            valid_p["Date"] = pd.Timestamp.now().strftime("%Y-%m-%d")

            # Save to Google Sheets
            st.session_state["purchase_history"] = pd.concat(
                [st.session_state["purchase_history"], valid_p],
                ignore_index=True,
            )
            save_cloud_table(
                st.session_state["purchase_history"], "purchase_history"
            )

            # Update Ledger
            new_ledger = {
                "Date": pd.Timestamp.now().strftime("%Y-%m-%d"),
                "Party Name": final_p_party,
                "Voucher Type": "Purchase Invoice",
                "Ref No": p_inv_no,
                "Debit (Dr)": 0.0,
                "Credit (Cr)": float(p_grand_total),
                "Remarks": f"Purchase Bill #{p_inv_no}",
            }
            st.session_state["ledger_transactions"] = pd.concat(
                [
                    st.session_state["ledger_transactions"],
                    pd.DataFrame([new_ledger]),
                ],
                ignore_index=True,
            )
            save_cloud_table(
                st.session_state["ledger_transactions"], "ledger_transactions"
            )

            st.session_state["purchase_data"] = get_empty_invoice_df()
            st.session_state["scanned_p_party"] = ""
            st.success("🎉 परचेज बिल Google Sheet में सुरक्षित सेव हो गया!")


# ------------------------------------------
# TAB 2: SALES INVOICE
# ------------------------------------------
with tab2:
    st.header("🧾 Sales Invoice (Marg/Tally Style)")
    col_s1, col_s2 = st.columns([1, 1])

    with col_s1:
        s_file = st.file_uploader(
            "Upload Sales Slip Image", type=["jpg", "png", "jpeg"], key="s_file"
        )
        if s_file:
            st.image(s_file, caption="Uploaded Slip", width=180)
            if st.button("🚀 Auto-Scan Sales Bill", key="btn_s_scan"):
                with st.spinner("⚡ AI स्कैनिंग चल रही है..."):
                    try:
                        res = scan_slip_with_party_ai(s_file, "sales")
                        st.session_state["sales_data"] = pd.DataFrame(
                            res.get("Items", [])
                        )
                        st.session_state["scanned_s_party"] = res.get(
                            "Party Name", ""
                        )
                        st.success("✅ स्कैनिंग पूरी हो गई!")
                    except Exception as e:
                        st.error(f"स्कैन त्रुटि: {str(e)}")

    with col_s2:
        p_customers = st.session_state["party_master"][
            st.session_state["party_master"]["Type"] == "Customer"
        ]["Party Name"].tolist()
        default_c = (
            st.session_state["scanned_s_party"]
            if st.session_state["scanned_s_party"]
            else (
                p_customers[0]
                if p_customers
                else "SHREE RAM MEDICAL STORE"
            )
        )

        final_s_party = st.text_input(
            "✏️ Party / Customer Name", value=default_c, key="txt_s_party"
        )
        s_inv_no = st.text_input(
            "✏️ Invoice No.", "INV-2026-001", key="txt_s_inv"
        )

    st.markdown("---")
    edited_s_df = st.data_editor(
        st.session_state["sales_data"],
        key="s_table_editor",
        num_rows="dynamic",
        use_container_width=True,
    )

    calc_s_df = calculate_pharma_bill(edited_s_df, is_sales=True)

    tot_gross = calc_s_df["Gross Amt"].sum()
    tot_disc = calc_s_df["Disc Amt"].sum()
    tot_taxable = calc_s_df["Taxable Value"].sum()
    tot_gst = calc_s_df["GST Amt"].sum()
    grand_total = calc_s_df["Net Line Amount"].sum()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Gross Total", f"₹{tot_gross:,.2f}")
    c2.metric("Total Discount (-)", f"₹{tot_disc:,.2f}")
    c3.metric("Taxable Value", f"₹{tot_taxable:,.2f}")
    c4.metric("Grand Total (Inc. GST)", f"₹{grand_total:,.2f}")

    if st.button("💾 Save Sales Invoice", key="btn_save_sales_final"):
        if not final_s_party.strip():
            st.error("⚠️ कृपया पार्टी का नाम अवश्य लिखें!")
        else:
            valid_df = calc_s_df[
                calc_s_df["Product Name"].astype(str).str.strip() != ""
            ].copy()
            valid_df["Party Name"] = final_s_party
            valid_df["Invoice No"] = s_inv_no
            valid_df["Date"] = pd.Timestamp.now().strftime("%Y-%m-%d")

            # Save to Google Sheets
            st.session_state["sales_history"] = pd.concat(
                [st.session_state["sales_history"], valid_df], ignore_index=True
            )
            save_cloud_table(
                st.session_state["sales_history"], "sales_history"
            )

            # Update Ledger
            new_ledger = {
                "Date": pd.Timestamp.now().strftime("%Y-%m-%d"),
                "Party Name": final_s_party,
                "Voucher Type": "Sales Invoice",
                "Ref No": s_inv_no,
                "Debit (Dr)": float(grand_total),
                "Credit (Cr)": 0.0,
                "Remarks": f"Sales Bill #{s_inv_no}",
            }
            st.session_state["ledger_transactions"] = pd.concat(
                [
                    st.session_state["ledger_transactions"],
                    pd.DataFrame([new_ledger]),
                ],
                ignore_index=True,
            )
            save_cloud_table(
                st.session_state["ledger_transactions"], "ledger_transactions"
            )

            st.session_state["sales_data"] = get_empty_invoice_df()
            st.session_state["scanned_s_party"] = ""
            st.success("🎉 सेल बिल Google Sheet में सुरक्षित सेव हो गया!")


# ------------------------------------------
# TAB 3: PARTY LEDGER
# ------------------------------------------
with tab3:
    st.header("📒 Party Ledger Statement")

    edited_global_ledger = st.data_editor(
        st.session_state["ledger_transactions"],
        key="global_ledger_edit",
        num_rows="dynamic",
        use_container_width=True,
    )
    if not edited_global_ledger.equals(st.session_state["ledger_transactions"]):
        st.session_state["ledger_transactions"] = edited_global_ledger
        save_cloud_table(edited_global_ledger, "ledger_transactions")

    all_parties = st.session_state["party_master"]["Party Name"].tolist()
    if all_parties:
        selected_party = st.selectbox(
            "Select Party to View Specific Ledger", all_parties
        )
        party_tx = edited_global_ledger[
            edited_global_ledger["Party Name"] == selected_party
        ].copy()

        if not party_tx.empty:
            dr = (
                pd.to_numeric(party_tx["Debit (Dr)"], errors="coerce")
                .fillna(0)
                .sum()
            )
            cr = (
                pd.to_numeric(party_tx["Credit (Cr)"], errors="coerce")
                .fillna(0)
                .sum()
            )
            bal = dr - cr

            col1, col2, col3 = st.columns(3)
            col1.metric("Total Sales/Debit", f"₹{dr:,.2f}")
            col2.metric("Total Payments/Credit", f"₹{cr:,.2f}")
            col3.metric(
                "Closing Balance",
                f"₹{abs(bal):,.2f} {'Dr (पाना है)' if bal > 0 else 'Cr (देना बाकी है)' if bal < 0 else 'Cleared'}",
            )

            st.dataframe(party_tx, use_container_width=True)


# ------------------------------------------
# TAB 4: LIVE STOCK INVENTORY
# ------------------------------------------
with tab4:
    st.header("📊 Live Stock Inventory")

    p_hist = st.session_state["purchase_history"]
    s_hist = st.session_state["sales_history"]

    if p_hist.empty and s_hist.empty:
        st.info("स्टॉक में अभी कोई डाटा उपलब्ध नहीं है।")
    else:
        p_summary = pd.DataFrame()
        s_summary = pd.DataFrame()

        if not p_hist.empty and "Product Name" in p_hist.columns:
            p_summary = (
                p_hist.groupby("Product Name")["Total Qty (Billed+Free)"]
                .sum()
                .reset_index()
                .rename(columns={"Total Qty (Billed+Free)": "Purchased Qty"})
            )

        if not s_hist.empty and "Product Name" in s_hist.columns:
            s_summary = (
                s_hist.groupby("Product Name")["Total Qty (Billed+Free)"]
                .sum()
                .reset_index()
                .rename(columns={"Total Qty (Billed+Free)": "Sold Qty"})
            )

        if not p_summary.empty and not s_summary.empty:
            merged = pd.merge(
                p_summary, s_summary, on="Product Name", how="outer"
            ).fillna(0)
        elif not p_summary.empty:
            merged = p_summary.copy()
            merged["Sold Qty"] = 0
        elif not s_summary.empty:
            merged = s_summary.copy()
            merged["Purchased Qty"] = 0
        else:
            merged = pd.DataFrame()

        if not merged.empty:
            merged["Current Stock Qty"] = (
                merged["Purchased Qty"] - merged["Sold Qty"]
            )
            st.dataframe(merged, use_container_width=True)


# ------------------------------------------
# TAB 5: PARTY MASTER & VOUCHERS
# ------------------------------------------
with tab5:
    st.header("⚙️ Master Setup & Payment/Receipt Entries")
    col_m1, col_m2 = st.columns(2)

    with col_m1:
        st.subheader("➕ Add New Party")
        with st.form("party_form"):
            new_name = st.text_input("Party Name")
            new_type = st.selectbox("Type", ["Customer", "Supplier"])
            new_city = st.text_input("City", "Faizabad")
            new_gstin = st.text_input("GSTIN", "N/A")
            if st.form_submit_button("Save Party") and new_name:
                new_p = pd.DataFrame(
                    [
                        {
                            "Party Name": new_name,
                            "Type": new_type,
                            "City": new_city,
                            "GSTIN": new_gstin,
                        }
                    ]
                )
                st.session_state["party_master"] = pd.concat(
                    [st.session_state["party_master"], new_p], ignore_index=True
                )
                save_cloud_table(
                    st.session_state["party_master"], "party_master"
                )
                st.success(f"✅ Party '{new_name}' Google Sheet में जुड़ गई!")

    with col_m2:
        st.subheader("💳 Voucher Entry")
        with st.form("voucher_form"):
            v_party = st.selectbox(
                "Party Name",
                st.session_state["party_master"]["Party Name"].tolist(),
            )
            v_type = st.selectbox(
                "Voucher Type",
                [
                    "Receipt (पैसा प्राप्त हुआ - Cr)",
                    "Payment (भुगतान किया - Dr)",
                ],
            )
            v_amount = st.number_input("Amount (₹)", min_value=0.0, step=100.0)
            v_ref = st.text_input("Ref / Cheque / UPI No.")

            if st.form_submit_button("Post Voucher") and v_amount > 0:
                is_receipt = "Receipt" in v_type
                v_entry = {
                    "Date": pd.Timestamp.now().strftime("%Y-%m-%d"),
                    "Party Name": v_party,
                    "Voucher Type": "Receipt" if is_receipt else "Payment",
                    "Ref No": v_ref,
                    "Debit (Dr)": 0.0 if is_receipt else float(v_amount),
                    "Credit (Cr)": float(v_amount) if is_receipt else 0.0,
                    "Remarks": f"Payment Voucher Ref: {v_ref}",
                }
                st.session_state["ledger_transactions"] = pd.concat(
                    [
                        st.session_state["ledger_transactions"],
                        pd.DataFrame([v_entry]),
                    ],
                    ignore_index=True,
                )
                save_cloud_table(
                    st.session_state["ledger_transactions"], "ledger_transactions"
                )
                st.success("✅ वाउचर Google Sheet लेजर में सेव हो गया!")

    st.markdown("---")
    st.subheader("👥 Party Master List")
    edited_party_master = st.data_editor(
        st.session_state["party_master"],
        key="party_master_editor",
        num_rows="dynamic",
        use_container_width=True,
    )
    if not edited_party_master.equals(st.session_state["party_master"]):
        st.session_state["party_master"] = edited_party_master
        save_cloud_table(edited_party_master, "party_master")
