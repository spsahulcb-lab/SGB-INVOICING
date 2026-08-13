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
    page_title="Pharma ERP & Ledger System",
    layout="wide",
    page_icon="💊",
)

st.title("💊 Pharma ERP - Inventory & Tally/Marg Style Ledger")

# Gemini API Key Setup
if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

# Initialize Global Session States for Permanent Log Memory & Ledger
if "purchase_data" not in st.session_state:
    st.session_state["purchase_data"] = pd.DataFrame()

if "sales_data" not in st.session_state:
    st.session_state["sales_data"] = pd.DataFrame()

# Party Master List
if "party_master" not in st.session_state:
    st.session_state["party_master"] = pd.DataFrame(
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

# Transaction Log (Journal/Ledger Register)
if "ledger_transactions" not in st.session_state:
    st.session_state["ledger_transactions"] = pd.DataFrame(
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

# Stock Records
if "purchase_history" not in st.session_state:
    st.session_state["purchase_history"] = pd.DataFrame(
        columns=["Party Name", "Product Name", "MRP", "Qty"]
    )

if "sales_history" not in st.session_state:
    st.session_state["sales_history"] = pd.DataFrame(
        columns=["Party Name", "Product Name", "MRP", "Qty", "Rate", "Taxable Amount"]
    )


# ==========================================
# 2. DYNAMIC MODEL SCANNER & COMPRESSION
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


def scan_slip_with_ai(uploaded_file, slip_type="purchase"):
    compressed_bytes = compress_image(uploaded_file)
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
        raise Exception(
            f"स्कैन पूरा नहीं हो सका। कृपया API Key जांचें। (Error: {last_error})"
        )

    clean_json = (
        response.text.replace("```json", "").replace("```", "").strip()
    )
    return json.loads(clean_json)


# ==========================================
# 3. NAVIGATION (Tally / Marg Style Tabs)
# ==========================================
tab1, tab2, tab3, tab4, tab5 = st.tabs(
    [
        "📦 1. Purchase Entry (Inward)",
        "🧾 2. Sales Slip Scan (Outward)",
        "📒 3. Party Ledger & Statement (Tally/Marg)",
        "📊 4. Stock Inventory",
        "⚙️ 5. Party Master & Payment Entry",
    ]
)


# ------------------------------------------
# TAB 1: PURCHASE ENTRY WITH LEDGER
# ------------------------------------------
with tab1:
    st.header("📦 Purchase / Stock Inward Entry")

    p_suppliers = st.session_state["party_master"][
        st.session_state["party_master"]["Type"] == "Supplier"
    ]["Party Name"].tolist()
    selected_supplier = st.selectbox(
        "Select Supplier / Party",
        p_suppliers
        if p_suppliers
        else ["MEDICARE PHARMA DISTRIBUTORS"],
    )
    p_inv_no = st.text_input("Purchase Bill/Invoice No.", "PUR-8841")

    p_file = st.file_uploader(
        "Upload Purchase Slip Image",
        type=["jpg", "png", "jpeg"],
        key="p_file",
    )

    if p_file:
        st.image(p_file, caption="Uploaded Purchase Slip", width=300)

        if st.button("🚀 Fast Auto-Scan & Match with Stock", key="btn_p_scan"):
            with st.spinner("⚡ AI स्कैन कर रहा है..."):
                try:
                    data = scan_slip_with_ai(p_file, "purchase")
                    st.session_state["purchase_data"] = pd.DataFrame(data)
                    st.success("✅ Purchase Slip स्कैन हो गई!")
                except Exception as e:
                    st.error(f"स्कैनिंग में त्रुटि: {str(e)}")

    if not st.session_state["purchase_data"].empty:
        st.subheader("Scanned Items")
        edited_p_df = st.data_editor(
            st.session_state["purchase_data"], key="p_editor", num_rows="dynamic"
        )

        total_p_amount = (edited_p_df["MRP"] * edited_p_df["Qty"]).sum()
        st.info(f"Total Purchase Amount: ₹{total_p_amount:,.2f}")

        if st.button("📥 Save Purchase Entry & Post to Ledger", key="btn_add_stock"):
            # Stock Record Update
            edited_p_df["Party Name"] = selected_supplier
            st.session_state["purchase_history"] = pd.concat(
                [st.session_state["purchase_history"], edited_p_df],
                ignore_index=True,
            )

            # Ledger Credit Post
            new_ledger_entry = {
                "Date": pd.Timestamp.now().strftime("%Y-%m-%d"),
                "Party Name": selected_supplier,
                "Voucher Type": "Purchase",
                "Ref No": p_inv_no,
                "Debit (Dr)": 0.0,
                "Credit (Cr)": float(total_p_amount),
                "Remarks": f"Stock Purchase Bill #{p_inv_no}",
            }
            st.session_state["ledger_transactions"] = pd.concat(
                [
                    st.session_state["ledger_transactions"],
                    pd.DataFrame([new_ledger_entry]),
                ],
                ignore_index=True,
            )

            st.session_state["purchase_data"] = pd.DataFrame()
            st.success(
                "🎉 Purchase Record और Supplier Ledger में जमा (Credit) हो गया!"
            )


# ------------------------------------------
# TAB 2: SALES ENTRY WITH LEDGER
# ------------------------------------------
with tab2:
    st.header("🧾 Sales Order Slip Scanner")

    p_customers = st.session_state["party_master"][
        st.session_state["party_master"]["Type"] == "Customer"
    ]["Party Name"].tolist()
    selected_customer = st.selectbox(
        "Select Customer / Shop Name",
        p_customers if p_customers else ["SHREE RAM MEDICAL STORE"],
    )
    s_inv_no = st.text_input("Sales Invoice No.", "INV-2026-0892")

    s_file = st.file_uploader(
        "Upload Sales Slip Image", type=["jpg", "png", "jpeg"], key="s_file"
    )

    if s_file:
        st.image(s_file, caption="Uploaded Sales Slip", width=300)

        if st.button("🚀 Fast Auto-Scan Sales Slip", key="btn_s_scan"):
            with st.spinner("⚡ AI स्कैन कर रहा है..."):
                try:
                    data = scan_slip_with_ai(s_file, "sales")
                    df = pd.DataFrame(data)
                    df["Rate"] = (df["MRP"] * 0.80).round(2)
                    df["Taxable Amount"] = (df["Qty"] * df["Rate"]).round(2)
                    st.session_state["sales_data"] = df
                    st.success("✅ Sales Slip स्कैन हो गई!")
                except Exception as e:
                    st.error(f"स्कैनिंग में त्रुटि: {str(e)}")

    if not st.session_state["sales_data"].empty:
        st.subheader("Scanned Sales Items Table")
        edited_s_df = st.data_editor(
            st.session_state["sales_data"], key="s_editor", num_rows="dynamic"
        )

        total_taxable = edited_s_df["Taxable Amount"].sum()
        gst = round(total_taxable * 0.12, 2)
        grand_total = round(total_taxable + gst, 2)

        st.metric("Grand Total Bill Amount", f"₹{grand_total:,.2f}")

        if st.button("💾 Save Sales Entry & Post to Ledger", key="btn_save_sales"):
            # Stock Record Update
            edited_s_df["Party Name"] = selected_customer
            st.session_state["sales_history"] = pd.concat(
                [st.session_state["sales_history"], edited_s_df],
                ignore_index=True,
            )

            # Ledger Debit Post
            new_ledger_entry = {
                "Date": pd.Timestamp.now().strftime("%Y-%m-%d"),
                "Party Name": selected_customer,
                "Voucher Type": "Sales",
                "Ref No": s_inv_no,
                "Debit (Dr)": float(grand_total),
                "Credit (Cr)": 0.0,
                "Remarks": f"Tax Invoice Bill #{s_inv_no}",
            }
            st.session_state["ledger_transactions"] = pd.concat(
                [
                    st.session_state["ledger_transactions"],
                    pd.DataFrame([new_ledger_entry]),
                ],
                ignore_index=True,
            )

            st.success(
                "✅ Sales Entry सेव हो गई और Customer Ledger में नामे (Debit) हो गया!"
            )


# ------------------------------------------
# TAB 3: TALLY / MARG STYLE PARTY LEDGER STATEMENT
# ------------------------------------------
with tab3:
    st.header("📒 Tally / Marg Style Party Ledger Statement")
    st.caption("किसी भी ग्राहक या सप्लायर का पूरा खाता (Ledger) और बकाया देखें।")

    all_parties = st.session_state["party_master"]["Party Name"].tolist()

    if not all_parties:
        st.info("कोई पार्टी मौजूद नहीं है।")
    else:
        selected_party_ledger = st.selectbox(
            "Select Party to View Ledger Statement", all_parties
        )

        tx_df = st.session_state["ledger_transactions"]
        party_tx = tx_df[
            tx_df["Party Name"] == selected_party_ledger
        ].copy()

        if party_tx.empty:
            st.warning("इस पार्टी का कोई लेनदेन रिकॉर्ड नहीं मिला।")
        else:
            # Running Balance Calculation
            party_tx["Debit (Dr)"] = party_tx["Debit (Dr)"].astype(float)
            party_tx["Credit (Cr)"] = party_tx["Credit (Cr)"].astype(float)
            party_tx["Balance"] = (
                party_tx["Debit (Dr)"] - party_tx["Credit (Cr)"]
            ).cumsum()

            tot_dr = party_tx["Debit (Dr)"].sum()
            tot_cr = party_tx["Credit (Cr)"].sum()
            closing_bal = tot_dr - tot_cr

            col1, col2, col3 = st.columns(3)
            col1.metric("Total Debit (Dr)", f"₹{tot_dr:,.2f}")
            col2.metric("Total Credit (Cr)", f"₹{tot_cr:,.2f}")

            if closing_bal > 0:
                col3.metric(
                    "Closing Balance",
                    f"₹{abs(closing_bal):,.2f} Dr (बकाया लेना है)",
                )
            elif closing_bal < 0:
                col3.metric(
                    "Closing Balance",
                    f"₹{abs(closing_bal):,.2f} Cr (बकाया देना है)",
                )
            else:
                col3.metric("Closing Balance", "₹0.00 (حساب बराबर)")

            st.subheader(f"Ledger Statement for: {selected_party_ledger}")
            st.dataframe(party_tx, use_container_width=True)

            st.download_button(
                label=f"📥 Download {selected_party_ledger} Ledger CSV",
                data=party_tx.to_csv(index=False),
                file_name=f"{selected_party_ledger}_ledger.csv",
                mime="text/csv",
            )


# ------------------------------------------
# TAB 4: STOCK INVENTORY
# ------------------------------------------
with tab4:
    st.header("📊 Live Stock Inventory")

    p_hist = st.session_state["purchase_history"]
    s_hist = st.session_state["sales_history"]

    if p_hist.empty:
        st.info("अभी तक कोई स्टॉक एंट्री नहीं है।")
    else:
        p_summary = (
            p_hist.groupby("Product Name")["Qty"].sum().reset_index()
        )
        p_summary.rename(columns={"Qty": "Total Purchased Qty"}, inplace=True)

        if not s_hist.empty:
            s_summary = (
                s_hist.groupby("Product Name")["Qty"].sum().reset_index()
            )
            s_summary.rename(columns={"Qty": "Total Sold Qty"}, inplace=True)
            merged = pd.merge(
                p_summary, s_summary, on="Product Name", how="left"
            ).fillna(0)
        else:
            merged = p_summary.copy()
            merged["Total Sold Qty"] = 0

        merged["Available Stock Qty"] = (
            merged["Total Purchased Qty"] - merged["Total Sold Qty"]
        )
        st.dataframe(merged, use_container_width=True)


# ------------------------------------------
# TAB 5: PARTY MASTER & PAYMENT/RECEIPT ENTRY
# ------------------------------------------
with tab5:
    st.header("⚙️ Master & Voucher Entry")

    col_m1, col_m2 = st.columns(2)

    # 1. Add New Party Master
    with col_m1:
        st.subheader("➕ Add New Party (Customer/Supplier)")
        with st.form("party_form"):
            new_name = st.text_input("Party Name")
            new_type = st.selectbox("Party Type", ["Customer", "Supplier"])
            new_city = st.text_input("City")
            new_gstin = st.text_input("GSTIN")
            submit_party = st.form_submit_button("Save Party Master")

            if submit_party and new_name:
                new_party = pd.DataFrame(
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
                    [st.session_state["party_master"], new_party],
                    ignore_index=True,
                )
                st.success(f"✅ Party '{new_name}' मास्टर में जुड़ गई!")

    # 2. Payment / Receipt Voucher Entry
    with col_m2:
        st.subheader("💳 Payment / Receipt Entry")
        with st.form("voucher_form"):
            v_party = st.selectbox(
                "Party Name",
                st.session_state["party_master"]["Party Name"].tolist(),
            )
            v_type = st.selectbox(
                "Voucher Type",
                [
                    "Receipt (पैसा मिला - Cr Party)",
                    "Payment (भुगतान किया - Dr Party)",
                ],
            )
            v_amount = st.number_input(
                "Amount (₹)", min_value=0.0, step=100.0
            )
            v_ref = st.text_input("Ref / Cheque / UPI No.")
            submit_voucher = st.form_submit_button("Post Voucher Entry")

            if submit_voucher and v_amount > 0:
                is_receipt = "Receipt" in v_type
                dr = 0.0 if is_receipt else float(v_amount)
                cr = float(v_amount) if is_receipt else 0.0

                v_entry = {
                    "Date": pd.Timestamp.now().strftime("%Y-%m-%d"),
                    "Party Name": v_party,
                    "Voucher Type": "Receipt" if is_receipt else "Payment",
                    "Ref No": v_ref,
                    "Debit (Dr)": dr,
                    "Credit (Cr)": cr,
                    "Remarks": f"Cash/Bank Transaction Ref: {v_ref}",
                }
                st.session_state["ledger_transactions"] = pd.concat(
                    [
                        st.session_state["ledger_transactions"],
                        pd.DataFrame([v_entry]),
                    ],
                    ignore_index=True,
                )
                st.success("✅ वाउचर एंट्री लेजर में सफलतापूर्वक अपडेट हो गई!")

    st.markdown("---")
    st.subheader("👥 All Registered Parties List")
    st.dataframe(st.session_state["party_master"], use_container_width=True)
