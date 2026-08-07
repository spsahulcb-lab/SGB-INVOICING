import streamlit as st
import pandas as pd
import os
import json
import re
import ast
import google.generativeai as genai
from PIL import Image
from datetime import datetime

st.set_page_config(page_title="LCB Pharma - Manager & Salesman System", layout="wide")

# Database Files
USERS_FILE = "users_db.csv"
STOCK_FILE = "master_stock_inventory.csv"
SALES_FILE = "sales_history.csv"
PURCHASE_FILE = "purchase_history.csv"
LEDGER_FILE = "party_ledger_history.csv"

# ----------------------------------------------------
# INITIALIZE DATABASES
# ----------------------------------------------------
if not os.path.exists(USERS_FILE):
    df_users = pd.DataFrame([
        {"Username": "manager", "Password": "manager123", "Name": "Satya Prakash (Manager)", "Role": "Manager"},
        {"Username": "sales1", "Password": "sales123", "Name": "Salesman 1", "Role": "Salesman"}
    ])
    df_users.to_csv(USERS_FILE, index=False)

if not os.path.exists(STOCK_FILE):
    df_init = pd.DataFrame({
        "Product Name": ["WOMENSA SYRUP", "PANCHALIV SYRUP", "ALOBYD-P", "AGEXPRO PWD", "B-RICH TAB"],
        "HSN Code": ["3004", "3004", "3004", "3004", "3004"],
        "Batch No": ["BT101", "BT102", "BT103", "BT104", "BT105"],
        "Expiry Date": ["2027-12", "2027-10", "2028-01", "2027-08", "2028-05"],
        "MRP (₹)": [128.00, 144.00, 56.00, 249.00, 92.00],
        "GST %": [12, 12, 12, 12, 12],
        "Available Stock": [100, 100, 100, 100, 100]
    })
    df_init.to_csv(STOCK_FILE, index=False)

def get_stock():
    return pd.read_csv(STOCK_FILE)

def save_stock(df):
    df.to_csv(STOCK_FILE, index=False)

def get_users():
    return pd.read_csv(USERS_FILE)

def record_sale(date_str, inv_no, est_no, party_name, product_name, batch, qty, free_qty, mrp, disc_pct, gst_pct, created_by):
    taxable_val = (qty * mrp) * (1 - disc_pct / 100.0)
    gst_amt = taxable_val * (gst_pct / 100.0)
    net_amount = taxable_val + gst_amt
    
    new_sale = pd.DataFrame([{
        "Date": date_str,
        "Inv No": inv_no,
        "Est No": est_no,
        "Party": party_name.upper(),
        "Product Name": product_name,
        "Batch No": batch,
        "Qty Sold": qty,
        "Free Qty": free_qty,
        "Taxable Amount": round(taxable_val, 2),
        "Tax Amount": round(gst_amt, 2),
        "Net Amount": round(net_amount, 2),
        "Created By": created_by
    }])
    if os.path.exists(SALES_FILE):
        sales_df = pd.read_csv(SALES_FILE)
        sales_df = pd.concat([sales_df, new_sale], ignore_index=True)
    else:
        sales_df = new_sale
    sales_df.to_csv(SALES_FILE, index=False)
    record_ledger(party_name, "SALE", inv_no, f"Cash Sale Est No:{est_no}", net_amount, 0.0, created_by)

def record_purchase(date_str, bill_no, party_name, product_name, batch, exp_date, qty, free_qty, mrp, disc_amt, othr_adj, gst_pct, created_by):
    net_val = (qty * mrp) - disc_amt + othr_adj
    new_pur = pd.DataFrame([{
        "Date": date_str,
        "Bill No": bill_no.upper(),
        "Party": party_name.upper(),
        "Product Name": product_name,
        "Batch No": batch,
        "Expiry Date": exp_date,
        "Qty": qty,
        "Free Qty": free_qty,
        "Disc Amt": disc_amt,
        "Bill Amnt": round(net_val, 2),
        "Created By": created_by
    }])
    if os.path.exists(PURCHASE_FILE):
        pur_df = pd.read_csv(PURCHASE_FILE)
        pur_df = pd.concat([pur_df, new_pur], ignore_index=True)
    else:
        pur_df = new_pur
    pur_df.to_csv(PURCHASE_FILE, index=False)

def record_ledger(party_name, trans_type, inv_no, narration, dr_amnt, cr_amnt, created_by):
    new_entry = pd.DataFrame([{
        "Date": datetime.now().strftime("%d/%m/%Y"),
        "Party": party_name.upper(),
        "Trans Type": trans_type,
        "Inv No": inv_no,
        "Narration": narration,
        "Dr Amnt": round(dr_amnt, 2),
        "Cr Amnt": round(cr_amnt, 2),
        "Created By": created_by
    }])
    if os.path.exists(LEDGER_FILE):
        leg_df = pd.read_csv(LEDGER_FILE)
        leg_df = pd.concat([leg_df, new_entry], ignore_index=True)
    else:
        leg_df = new_entry
    leg_df.to_csv(LEDGER_FILE, index=False)

# ----------------------------------------------------
# AUTHENTICATION SESSION
# ----------------------------------------------------
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False
    st.session_state["user_info"] = None

# LOGIN PAGE
if not st.session_state["authenticated"]:
    st.markdown("<h2 style='text-align: center;'>🔒 LCB Pharma - Login Portal</h2>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        with st.form("login_form"):
            username_input = st.text_input("👤 Username")
            password_input = st.text_input("🔑 Password", type="password")
            submit_login = st.form_submit_button("🚀 Login")
            
            if submit_login:
                users_df = get_users()
                user_match = users_df[(users_df["Username"].str.lower() == username_input.strip().lower()) & 
                                      (users_df["Password"] == password_input)]
                if not user_match.empty:
                    st.session_state["authenticated"] = True
                    st.session_state["user_info"] = user_match.iloc[0].to_dict()
                    st.success("✅ Login Successful!")
                    st.rerun()
                else:
                    st.error("❌ Galat Username ya Password!")
    st.stop()

# ----------------------------------------------------
# MAIN APPLICATION (AFTER LOGIN)
# ----------------------------------------------------
current_user = st.session_state["user_info"]

# Sidebar Profile & Navigation
st.sidebar.title("🏢 LCB PHARMA")
st.sidebar.markdown(f"👤 **User:** `{current_user['Name']}`")
st.sidebar.markdown(f"⚙️ **Role:** `{current_user['Role']}`")

if st.sidebar.button("🚪 Logout"):
    st.session_state["authenticated"] = False
    st.session_state["user_info"] = None
    st.rerun()

st.sidebar.write("---")

# Common Menu options for BOTH Salesman and Manager (All entries allowed)
menu_options = [
    "📦 Stock Inventory", 
    "📸 AI Photo Scanner", 
    "🛍️ Purchase Entry (Manual)", 
    "🧾 Sales Billing (Sell Items)",
    "📊 Bill wise Sale Statement",
    "🛒 Bill wise Purchase Statement",
    "📖 Party Ledger Bill Wise",
    "🏢 Sale Statement Party Wise"
]

# Manager extra menu
if current_user["Role"] == "Manager":
    menu_options.append("👥 Manage Salesmen")

menu = st.sidebar.radio("Navigation Menu", menu_options)
gemini_api_key = st.secrets.get("GEMINI_API_KEY", "")

# 1. STOCK INVENTORY
if menu == "📦 Stock Inventory":
    st.subheader("📋 Master Stock Register")
    st.dataframe(get_stock(), use_container_width=True)

# 2. AI PHOTO SCANNER
elif menu == "📸 AI Photo Scanner":
    st.subheader("📸 Scan Handwritten Slip with AI")
    uploaded_file = st.file_uploader("Upload Handwritten Slip Photo", type=['jpg', 'jpeg', 'png'])

    if uploaded_file:
        st.image(uploaded_file, caption="Uploaded Slip", width=350)
        
        if st.button("🚀 Auto-Scan & Match with Stock"):
            if not gemini_api_key:
                st.error("❌ GEMINI_API_KEY Secret missing!")
            else:
                try:
                    current_stock = get_stock()
                    master_list_str = ", ".join(current_stock["Product Name"].tolist())

                    prompt = f"""Extract product details from this pharma bill image.
MASTER LIST: [{master_list_str}]
Return ONLY valid JSON array:
[
  {{"Product Name": "ITEM NAME", "HSN": "3004", "Batch": "B01", "Expiry": "2027-12", "Qty": 10, "Free Qty": 0, "MRP": 100.0, "Discount %": 0, "GST %": 12}}
]"""

                    genai.configure(api_key=gemini_api_key)
                    all_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
                    flash_models = [m for m in all_models if 'flash' in m.lower()]
                    models_to_try = list(dict.fromkeys(flash_models + all_models))
                    
                    image = Image.open(uploaded_file)
                    image.thumbnail((1024, 1024))
                    
                    raw_text = ""
                    for m_name in models_to_try:
                        try:
                            model = genai.GenerativeModel(m_name)
                            response = model.generate_content([prompt, image])
                            if response.text:
                                raw_text = response.text.strip()
                                break
                        except Exception:
                            continue

                    if raw_text:
                        cleaned = raw_text.replace("```json", "").replace("```", "").strip()
                        json_match = re.search(r'\[.*\]', cleaned, re.DOTALL)
                        target_str = json_match.group(0) if json_match else cleaned
                        st.session_state['scanned_items'] = json.loads(target_str)
                        st.success("✅ Bill Scanned Successfully!")
                        st.rerun()

                except Exception as err:
                    st.error(f"❌ Scan Error: {err}")

    if 'scanned_items' in st.session_state:
        st.write("### 🔍 Scanned Items")
        scanned_df = pd.DataFrame(st.session_state['scanned_items'])
        edited_df = st.data_editor(scanned_df, use_container_width=True, num_rows="dynamic")

        if st.button("📥 Add to Stock Inventory"):
            current_stock = get_stock()
            for item in edited_df.to_dict(orient="records"):
                p_name = str(item.get('Product Name', '')).strip().upper()
                p_batch = str(item.get('Batch', 'BT001')).strip().upper()
                p_qty = int(item.get('Qty', 0)) + int(item.get('Free Qty', 0))
                
                mask = (current_stock['Product Name'].str.strip().str.upper() == p_name) & (current_stock['Batch No'].str.strip().str.upper() == p_batch)
                if mask.any():
                    current_stock.loc[mask, 'Available Stock'] += p_qty
                else:
                    new_row = pd.DataFrame([{
                        "Product Name": p_name, "HSN Code": "3004", "Batch No": p_batch,
                        "Expiry Date": "2027-12", "MRP (₹)": float(item.get('MRP', 100)),
                        "GST %": 12, "Available Stock": p_qty
                    }])
                    current_stock = pd.concat([current_stock, new_row], ignore_index=True)
            save_stock(current_stock)
            st.success("🎉 Added to Inventory!")
            del st.session_state['scanned_items']
            st.rerun()

# 3. MANUAL PURCHASE
elif menu == "🛍️ Purchase Entry (Manual)":
    st.subheader("➕ Purchase Entry")
    with st.form("manual_purchase_form"):
        col1, col2, col3 = st.columns(3)
        with col1:
            bill_no = st.text_input("Bill No", value="B0001")
            party_name = st.text_input("Party / Supplier Name", value="INDIAN SURGICAL AND MEDICINES")
            prod_name = st.text_input("Product Name").upper()
        with col2:
            batch_no = st.text_input("Batch No.", value="BT101").upper()
            expiry_date = st.text_input("Expiry Date", value="2027-12")
            mrp = st.number_input("MRP (₹)", min_value=0.0)
        with col3:
            qty = st.number_input("Quantity", min_value=1, step=1)
            free_qty = st.number_input("Free Qty", min_value=0, step=1)
            disc_amt = st.number_input("Discount Amount (₹)", min_value=0.0)
            
        if st.form_submit_button("➕ Save Purchase"):
            if prod_name and party_name:
                date_today = datetime.now().strftime("%d/%m/%Y")
                record_purchase(date_today, bill_no, party_name, prod_name, batch_no, expiry_date, qty, free_qty, mrp, disc_amt, 0.0, 12.0, current_user['Username'])
                
                stock_df = get_stock()
                mask = (stock_df['Product Name'].str.upper() == prod_name) & (stock_df['Batch No'].str.upper() == batch_no)
                if mask.any():
                    stock_df.loc[mask, 'Available Stock'] += (qty + free_qty)
                else:
                    new_row = pd.DataFrame([{
                        "Product Name": prod_name, "HSN Code": "3004", "Batch No": batch_no,
                        "Expiry Date": expiry_date, "MRP (₹)": mrp, "GST %": 12, "Available Stock": (qty + free_qty)
                    }])
                    stock_df = pd.concat([stock_df, new_row], ignore_index=True)
                save_stock(stock_df)
                st.success("✅ Purchase Saved & Stock Updated!")

# 4. MANUAL SALES
elif menu == "🧾 Sales Billing (Sell Items)":
    st.subheader("🧾 Outward Sales Entry")
    stock_df = get_stock()
    if not stock_df.empty:
        prod = st.selectbox("Select Product", stock_df['Product Name'].unique())
        batches = stock_df[stock_df['Product Name'] == prod]['Batch No'].tolist()
        batch = st.selectbox("Select Batch", batches)
        
        c1, c2, c3 = st.columns(3)
        inv_no = c1.text_input("Invoice No", value="001")
        est_no = c2.text_input("Est No", value="001")
        party = c3.text_input("Party Name", value="HIND MEDICAL STORE")
        
        q1, q2 = st.columns(2)
        sell_qty = q1.number_input("Qty", min_value=1, step=1)
        free_qty = q2.number_input("Free Qty", min_value=0, step=1)
        
        if st.button("🏷️ Record Sale"):
            item_data = stock_df[(stock_df['Product Name'] == prod) & (stock_df['Batch No'] == batch)].iloc[0]
            date_today = datetime.now().strftime("%d/%m/%Y")
            record_sale(date_today, inv_no, est_no, party, prod, batch, sell_qty, free_qty, item_data['MRP (₹)'], 0.0, item_data['GST %'], current_user['Username'])
            
            mask = (stock_df['Product Name'] == prod) & (stock_df['Batch No'] == batch)
            stock_df.loc[mask, 'Available Stock'] -= (sell_qty + free_qty)
            save_stock(stock_df)
            st.success("✅ Sale Recorded Successfully!")

# 5. BILL WISE SALE STATEMENT
elif menu == "📊 Bill wise Sale Statement":
    st.subheader("📊 Bill wise Sale Statement")
    if os.path.exists(SALES_FILE):
        sales_df = pd.read_csv(SALES_FILE)
        st.dataframe(sales_df, use_container_width=True)
    else:
        st.info("No Sale Records Available.")

# 6. BILL WISE PURCHASE STATEMENT
elif menu == "🛒 Bill wise Purchase Statement":
    st.subheader("🛒 Bill wise Purchase Statement")
    if os.path.exists(PURCHASE_FILE):
        pur_df = pd.read_csv(PURCHASE_FILE)
        st.dataframe(pur_df, use_container_width=True)
    else:
        st.info("No Purchase Records Available.")

# 7. PARTY LEDGER BILL WISE
elif menu == "📖 Party Ledger Bill Wise":
    st.subheader("📖 Party Ledger Bill Wise")
    if os.path.exists(LEDGER_FILE):
        leg_df = pd.read_csv(LEDGER_FILE)
        parties = leg_df['Party'].unique().tolist()
        selected_party = st.selectbox("Select Party Name", parties)
        
        party_data = leg_df[leg_df['Party'] == selected_party].copy()
        party_data['Balance'] = (party_data['Dr Amnt'] - party_data['Cr Amnt']).cumsum()
        
        st.dataframe(party_data[['Date', 'Trans Type', 'Inv No', 'Narration', 'Dr Amnt', 'Cr Amnt', 'Balance', 'Created By']], use_container_width=True)
        
        st.write("---")
        st.write("### 💵 Add Payment / Receipt")
        with st.form("receipt_form"):
            c1, c2, c3 = st.columns(3)
            rec_inv = c1.text_input("Inv/Ref No", value="028")
            rec_amt = c2.number_input("Received Amount (Cr)", min_value=0.0)
            rec_narration = c3.text_input("Narration", value="Cash Received")
            
            if st.form_submit_button("➕ Save Receipt"):
                record_ledger(selected_party, "RECIEPT", rec_inv, rec_narration, 0.0, rec_amt, current_user['Username'])
                st.success("✅ Payment Recorded!")
                st.rerun()

# 8. SALE STATEMENT PARTY WISE
elif menu == "🏢 Sale Statement Party Wise":
    st.subheader("🏢 Sale Statement Party Wise")
    if os.path.exists(SALES_FILE):
        sales_df = pd.read_csv(SALES_FILE)
        parties = sales_df['Party'].unique().tolist()
        selected_parties = st.multiselect("Select Party Name", parties, default=parties)
        
        if selected_parties:
            filtered_df = sales_df[sales_df['Party'].isin(selected_parties)]
            grouped_df = filtered_df.groupby("Party").agg({
                "Qty Sold": "sum",
                "Taxable Amount": "sum",
                "Tax Amount": "sum",
                "Net Amount": "sum"
            }).reset_index()
            
            st.dataframe(grouped_df, use_container_width=True)
            st.metric("Total Net Sales Value", f"₹{grouped_df['Net Amount'].sum():,.2f}")

# 9. MANAGE SALESMEN (MANAGER ONLY)
elif menu == "👥 Manage Salesmen":
    st.subheader("👥 Manager Panel: Add & View Salesmen")
    users_df = get_users()
    st.dataframe(users_df[["Username", "Name", "Role"]], use_container_width=True)
    
    st.write("---")
    st.write("### ➕ Add New Salesman")
    with st.form("add_salesman_form"):
        u1, u2 = st.columns(2)
        new_username = u1.text_input("Salesman Username (e.g. sales2, rahul)").strip().lower()
        new_name = u2.text_input("Salesman Full Name")
        p1, p2 = st.columns(2)
        new_password = p1.text_input("Password", type="password")
        
        if st.form_submit_button("➕ Create Salesman Account"):
            if new_username and new_password and new_name:
                if new_username in users_df["Username"].str.lower().values:
                    st.error("❌ Yeh Username pehle से मौजूद है!")
                else:
                    new_user_df = pd.DataFrame([{"Username": new_username, "Password": new_password, "Name": new_name, "Role": "Salesman"}])
                    updated_users = pd.concat([users_df, new_user_df], ignore_index=True)
                    updated_users.to_csv(USERS_FILE, index=False)
                    st.success(f"✅ Salesman Account '{new_name}' Created Successfully!")
                    st.rerun()
