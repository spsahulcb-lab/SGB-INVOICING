import io
import json
import pandas as pd
import streamlit as st
import google.generativeai as genai

st.title("💊 Sales Invoice & Order Scanner")

# 1. Image Upload
uploaded_file = st.file_uploader(
    "Sales Slip / Order Slip Upload Karein", type=["jpg", "png", "jpeg"]
)

if uploaded_file:
    st.image(uploaded_file, caption="Uploaded Sales Slip", width=350)

    if st.button("🚀 Auto-Scan Sales Slip"):
        with st.spinner("AI पर्ची स्कैन कर रहा है..."):
            # Prepare image for Gemini API
            image_data = uploaded_file.getvalue()

            prompt = """
            Extract all sales product details from this slip image.
            Extract 3 fields for each item:
            1. Product Name
            2. MRP (float)
            3. Qty (integer)

            Return ONLY a valid JSON array like this:
            [
              {"Product Name": "ATPLEX SYP.", "MRP": 144.00, "Qty": 360},
              {"Product Name": "ACNETAZ CREAM", "MRP": 149.00, "Qty": 130}
            ]
            """

            model = genai.GenerativeModel("gemini-2.5-flash")
            response = model.generate_content(
                [
                    prompt,
                    {
                        "mime_type": uploaded_file.type,
                        "data": image_data,
                    },
                ]
            )

            # JSON Parsing
            data = json.loads(
                response.text.replace("```json", "").replace("```", "").strip()
            )
            df = pd.DataFrame(data)

            # Calculate Amount
            df["Rate"] = (df["MRP"] * 0.80).round(2)  # Example: 20% Discount
            df["Taxable Amount"] = (df["Qty"] * df["Rate"]).round(2)

            st.session_state["sales_data"] = df
            st.success("✅ Sales Slip Safaltapurvak Scan Ho Gayi!")

# 2. Display Table & Printable Bill Generator
if "sales_data" in st.session_state:
    df = st.session_state["sales_data"]

    st.subheader("📋 Scanned Sales Items")
    edited_df = st.data_editor(df, num_rows="dynamic")

    total_amount = edited_df["Taxable Amount"].sum()
    gst_amount = round(total_amount * 0.12, 2)
    grand_total = round(total_amount + gst_amount, 2)

    st.markdown(
        f"### **Total Amount:** ₹{total_amount:,.2f} | **GST (12%):** ₹{gst_amount:,.2f} | **Grand Total:** ₹{grand_total:,.2f}"
    )
