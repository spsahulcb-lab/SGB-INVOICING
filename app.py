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
    page_title="Pharma ERP - Marg & Tally Style Billing",
    layout="wide",
    page_icon="💊",
)

st.title("💊 Pharma ERP - Marg & Tally Style Smart Invoicing")

# Gemini API Key Setup
if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

# Initialize Session Dataframes with Marg/Tally Pharma Columns
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
                "GST %": 12.0,
            }
        ]
    )

if "purchase_data" not in st.session_state:
    st.session_state["purchase_data"] = get_empty_invoice_df()

if "sales_data" not in st.session_state:
    st.session_state["sales_data"] = get_empty_invoice_df()

if "scanned_p_party" not in st.session_state:
    st.session_state["scanned_p_party"] = ""

if "scanned_s_party" not in st.session_state:
    st.session_state["scanned_s_party"] = ""

# Party Master
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

# Transaction Log (Ledger)
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
    st.session_state["purchase_history"] = pd.DataFrame()

if "sales_history" not in st.session_state:
    st.session_state["sales_history"] = pd.DataFrame()


# ==========================================
# 2. AI SCANNER ENGINE
# ==========================================
def compress_image(uploaded_file, max_dimension=1280, quality=75):
    img = Image.open(uploaded_file)
    if img.mode != "RGB":
        img = img.convert("RGB")
    img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
    buffer = BytesIO()
    img.save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue()


def scan_slip_with_party_ai(uploaded_file, slip_type="sales"):
    compressed_bytes = compress_image(uploaded_file)

    prompt = f"""
    Extract billing details from this {slip_type} invoice/slip image.
    Include:
    1. Party Name (Store/Customer/Supplier name at the top).
    2. Items list with columns:
       - "Product Name"
       - "MRP" (float)
       - "Qty" (int - billed quantity)
       - "Free Deal" (int - free/scheme quantity, default 0)
       - "Rate" (float - selling/purchase unit rate)
       - "Disc %" (float - discount percentage, default 0.0)
       - "GST %" (float - 5, 12, or 18, default 12.0)

    Return ONLY a valid JSON object without markdown fences, like:
    {{
      "Party Name": "SHREE RAM MEDICAL STORE",
      "Items": [
        {{"Product Name": "ATPLEX SYP.", "MRP": 144.00, "Qty": 10, "Free Deal": 1, "Rate": 100.00, "Disc %": 5.0, "GST %": 12.0}}
      ]
    }}
    """
    model = genai.GenerativeModel("gemini-1.5-flash")
    response = model.generate_content(
        [prompt, {"mime_type": "image/jpeg", "data": compressed_bytes}]
    )
    clean_json = (
        response.text.replace("```json", "").replace("```", "").strip()
    )
    return json.loads(clean_json)


# ==========================================
# 3. BILL CALCULATOR ENGINE (MARG/TALLY MATH)
# ==========================================
def calculate_pharma_bill(df):
    df_calc = df.copy()
    numeric_cols = ["MRP", "Qty", "Free Deal", "Rate", "Disc %", "GST %"]
    for col in numeric_cols:
        if col in df_calc.columns:
            df_calc[col] = (
                pd.to_numeric(df_calc[col], errors="coerce").fillna(0)
            )

    # Marg/Tally Calculations
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
# 4. TABS SETUP
# ==========================================
tab1, tab2, tab3, tab4, tab5 = st.tabs(
    [
        "🧾 1. Sales Invoice (Marg/Tally Style)",
        "📦 2. Purchase Invoice (Inward)",
        "📒 3. Party Ledger Statement",
        "📊 4. Live Stock Inventory",
        "⚙️ 5. Party Master & Voucher Entry",
    ]
)


# ------------------------------------------
# TAB 1: SALES INVOICE (MARG / TALLY STYLE)
# ------------------------------------------
with tab1:
    st.header("🧾 Marg / Tally Style Pharma Sales Invoice")

    col_s1, col_s2 = st.columns([1, 1])

    with col_s1:
        st.subheader("📷 Auto-Scan Bill Slip (Optional)")
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
        st.subheader("✍️ Header Details (Editable)")
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
    st.subheader(
        "📝 Product-wise Rates, Deals & Discounts Table (Direct Editing)"
    )

    # Dynamic Editor for Pharma Billing Table
    edited_s_df = st.data_editor(
        st.session_state["sales_data"],
        key="s_table_editor",
        num_rows="dynamic",
        use_container_width=True,
    )

    # Process Dynamic Math
    calc_s_df = calculate_pharma_bill(edited_s_df)

    # Detailed Invoice Summary (Marg/Tally Style)
    tot_gross = calc_s_df["Gross Amt"].sum()
    tot_disc = calc_s_df["Disc Amt"].sum()
    tot_taxable = calc_s_df["Taxable Value"].sum()
    tot_gst = calc_s_df["GST Amt"].sum()
    grand_total = calc_s_df["Net Line Amount"].sum()

    st.markdown("#### 📊 Invoice Summary")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Gross Total", f"₹{tot_gross:,.2f}")
    c2.metric("Total Discount (-)", f"₹{tot_disc:,.2f}")
    c3.metric("Taxable Value", f"₹{tot_taxable:,.2f}")
    c4.metric("Grand Total (Inc. GST)", f"₹{grand_total:,.2f}")

    if st.button("💾 Save Sales Invoice & Post to Ledger", key="btn_save_sales_final"):
        if not final_s_party.strip():
            st.error("⚠️ कृपया पार्टी का नाम अवश्य लिखें!")
        else:
            valid_df = calc_s_df[
                calc_s_df["Product Name"].astype(str).str.strip() != ""
            ].copy()
            valid_df["Party Name"] = final_s_party
            valid_df["Invoice No"] = s_inv_no
            valid_df["Date"] = pd.Timestamp.now().strftime("%Y-%m-%d")

            # Save to Stock Sales History
            st.session_state["sales_history"] = pd.concat(
                [st.session_state["sales_history"], valid_df], ignore_index=True
            )

            # Post Debit to Ledger
            new_ledger = {
                "Date": pd.Timestamp.now().strftime("%Y-%m-%d"),
                "Party Name": final_s_party,
                "Voucher Type": "Sales Invoice",
                "Ref No": s_inv_no,
                "Debit (Dr)": float(grand_total),
                "Credit (Cr)": 0.0,
                "Remarks": f"Pharma Sales Invoice #{s_inv_no}",
            }
            st.session_state["ledger_transactions"] = pd.concat(
                [
                    st.session_state["ledger_transactions"],
                    pd.DataFrame([new_ledger]),
                ],
                ignore_index=True,
            )

            # Reset state
            st.session_state["sales_data"] = get_empty_invoice_df()
            st.session_state["scanned_s_party"] = ""
            st.success(
                f"🎉 सेल बिल सेव हो गया और {final_s_party} के लेजर में ₹{grand_total:,.2f} Debit हो गया!"
            )


# ------------------------------------------
# TAB 2: PURCHASE INVOICE (INWARD)
# ------------------------------------------
with tab2:
    st.header("📦 Marg / Tally Style Purchase Invoice")

    col_p1, col_p2 = st.columns([1, 1])

    with col_p1:
        st.subheader("📷 Auto-Scan Purchase Bill")
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
        st.subheader("✍️ Supplier Details (Editable)")
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
    st.subheader("📝 Products, Deals & Rate Entries")

    edited_p_df = st.data_editor(
        st.session_state["purchase_data"],
        key="p_table_editor",
        num_rows="dynamic",
        use_container_width=True,
    )

    calc_p_df = calculate_pharma_bill(edited_p_df)

    p_grand_total = calc_p_df["Net Line Amount"].sum()
    st.info(f"💰 Total Purchase Amount Payable: ₹{p_grand_total:,.2f}")

    if st.button("📥 Save Purchase Invoice & Post to Ledger", key="btn_save_pur_final"):
        if not final_p_party.strip():
            st.error("⚠️ कृपया सप्लायर का नाम दर्ज करें!")
        else:
            valid_p = calc_p_df[
                calc_p_df["Product Name"].astype(str).str.strip() != ""
            ].copy()
            valid_p["Party Name"] = final_p_party

            st.session_state["purchase_history"] = pd.concat(
                [st.session_state["purchase_history"], valid_p],
                ignore_index=True,
            )

            new_ledger = {
                "Date": pd.Timestamp.now().strftime("%Y-%m-%d"),
                "Party Name": final_p_party,
                "Voucher Type": "Purchase Invoice",
                "Ref No": p_inv_no,
                "Debit (Dr)": 0.0,
                "Credit (Cr)": float(p_grand_total),
                "Remarks": f"Pharma Purchase Invoice #{p_inv_no}",
            }
            st.session_state["ledger_transactions"] = pd.concat(
                [
                    st.session_state["ledger_transactions"],
                    pd.DataFrame([new_ledger]),
                ],
                ignore_index=True,
            )

            st.session_state["purchase_data"] = get_empty_invoice_df()
            st.session_state["scanned_p_party"] = ""
            st.success("🎉 परचेज बिल सेव हो गया और सप्लायर लेजर में Credit हो गया!")


# ------------------------------------------
# TAB 3: EDITABLE PARTY LEDGER STATEMENT
# ------------------------------------------
with tab3:
    st.header("📒 Party Ledger Statement (Fully Editable)")

    st.subheader("✏️ Master Transaction Journal (Edit Any Past Record)")
    edited_global_ledger = st.data_editor(
        st.session_state["ledger_transactions"],
        key="global_ledger_edit",
        num_rows="dynamic",
        use_container_width=True,
    )
    st.session_state["ledger_transactions"] = edited_global_ledger

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
                f"₹{abs(bal):,.2f} {'Dr (बकाया पाना है)' if bal > 0 else 'Cr (देना बाकी है)' if bal < 0 else 'Cleared'}",
            )

            st.dataframe(party_tx, use_container_width=True)


# ------------------------------------------
# TAB 4: LIVE STOCK INVENTORY
# ------------------------------------------
with tab4:
    st.header("📊 Stock Inventory (Including Free Scheme Deals)")

    p_hist = st.session_state["purchase_history"]
    s_hist = st.session_state["sales_history"]

    if p_hist.empty:
        st.info("स्टॉक में कोई आइटम उपलब्ध नहीं है।")
    else:
        p_summary = (
            p_hist.groupby("Product Name")["Total Qty (Billed+Free)"]
            .sum()
            .reset_index()
            .rename(columns={"Total Qty (Billed+Free)": "Purchased Qty"})
        )

        if not s_hist.empty:
            s_summary = (
                s_hist.groupby("Product Name")["Total Qty (Billed+Free)"]
                .sum()
                .reset_index()
                .rename(columns={"Total Qty (Billed+Free)": "Sold Qty"})
            )
            merged = pd.merge(
                p_summary, s_summary, on="Product Name", how="left"
            ).fillna(0)
        else:
            merged = p_summary.copy()
            merged["Sold Qty"] = 0

        merged["Current Stock Qty"] = merged["Purchased Qty"] - merged["Sold Qty"]
        st.dataframe(merged, use_container_width=True)


# ------------------------------------------
# TAB 5: PARTY MASTER & VOUCHER ENTRY
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
                st.success(f"✅ Party '{new_name}' मास्टर में जुड़ गई!")

    with col_m2:
        st.subheader("💳 Voucher Entry (Payment / Receipt)")
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
                st.success("✅ वाउचर लेजर में अपडेट हो गया!")

    st.markdown("---")
    st.subheader("👥 Editable Party Master List")
    edited_party_master = st.data_editor(
        st.session_state["party_master"],
        key="party_master_editor",
        num_rows="dynamic",
        use_container_width=True,
    )
    st.session_state["party_master"] = edited_party_master
