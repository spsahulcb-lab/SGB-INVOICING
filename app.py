import streamlit as st
import pandas as pd
from datetime import datetime
from fpdf import FPDF
import json
import io
import google.generativeai as genai
from PIL import Image, ImageDraw

# ==========================================
# 1. PAGE CONFIG & STYLING (ORANGE-WHITE THEME)
# ==========================================
st.set_page_config(
    page_title="Pharma ERP System", 
    layout="wide", 
    page_icon="💊",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
    .stApp {
        background-color: #FFFFFF;
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    }
    header[data-testid="stHeader"] {
        background: linear-gradient(90deg, #FF6F00, #FF8F00) !important;
    }
    section[data-testid="stSidebar"] {
        background-color: #FFF3E0 !important;
        border-right: 2px solid #FFE0B2;
    }
    .stButton>button, div[data-baseweb="button"] {
        width: 100% !important;
        background: #FF6F00 !important;
        color: white !important;
        font-weight: bold !important;
        border-radius: 8px !important;
        border: none !important;
    }
    .stButton>button:hover {
        background: #E65100 !important;
    }
    div[data-testid="stMetric"] {
        background-color: #FFFFFF !important;
        padding: 15px !important;
        border-radius: 10px !important;
        border-left: 6px solid #FF6F00 !important;
        box-shadow: 0px 2px 8px rgba(0,0,0,0.05) !important;
    }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 2. SUPABASE DATABASE CONNECTION
# ==========================================
conn = st.connection("supabase", type="sql")

def load_db_table(table_name):
    try:
        return conn.query(f"SELECT * FROM {table_name};", ttl=0)
    except Exception:
        return pd.DataFrame()

def execute_db_query(query, params=None):
    with conn.session as session:
        session.execute(query, params)
        session.commit()

# ==========================================
# 3. HELPER & CALCULATION FUNCTIONS
# ==========================================
def safe_calculate_bill(df):
    calc_df = df.copy()
    num_cols = ["MRP", "QTY", "BONUS", "RATE", "DIS %", "Gst%"]
    for c in num_cols:
        if c in calc_df.columns:
            calc_df[c] = pd.to_numeric(calc_df[c], errors="coerce").fillna(0.0)
        else:
            calc_df[c] = 5.0 if c == "Gst%" else 0.0

    calc_df["Gross"] = calc_df["QTY"] * calc_df["RATE"]
    calc_df["Disc_Amt"] = (calc_df["Gross"] * calc_df["DIS %"]) / 100.0
    calc_df["Taxable"] = calc_df["Gross"] - calc_df["Disc_Amt"]
    calc_df["GST_Amt"] = (calc_df["Taxable"] * calc_df["Gst%"]) / 100.0
    calc_df["AMOUNT"] = (calc_df["Taxable"] + calc_df["GST_Amt"]).round(2)
    return calc_df

def generate_pdf_invoice(party, inv_no, cart_items, total_amt, salesman):
    pdf = FPDF()
    pdf.add_page()
    
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(190, 10, "PHARMA ERP INVOICE", ln=True, align='C')
    pdf.set_font("Arial", '', 10)
    pdf.cell(190, 5, "Sales & Billing Receipt", ln=True, align='C')
    pdf.line(10, 28, 200, 28)
    pdf.ln(10)
    
    pdf.set_font("Arial", 'B', 10)
    pdf.cell(100, 6, f"Invoice No: {inv_no}", ln=False)
    pdf.cell(90, 6, f"Date: {datetime.now().strftime('%Y-%m-%d')}", ln=True)
    pdf.cell(100, 6, f"Party Name: {party}", ln=False)
    pdf.cell(90, 6, f"Salesman: {salesman}", ln=True)
    pdf.ln(6)
    
    pdf.set_fill_color(255, 224, 178)
    pdf.cell(80, 8, "Product Name", border=1, fill=True)
    pdf.cell(30, 8, "Qty", border=1, align='C', fill=True)
    pdf.cell(40, 8, "Rate (₹)", border=1, align='R', fill=True)
    pdf.cell(40, 8, "Amount (₹)", border=1, align='R', fill=True)
    pdf.ln()
    
    pdf.set_font("Arial", '', 10)
    for item in cart_items:
        pdf.cell(80, 7, str(item.get('PRODUCT', '')), border=1)
        pdf.cell(30, 7, str(item.get('QTY', 0)), border=1, align='C')
        pdf.cell(40, 7, f"{float(item.get('RATE', 0)):.2f}", border=1, align='R')
        pdf.cell(40, 7, f"{float(item.get('AMOUNT', 0)):.2f}", border=1, align='R')
        pdf.ln()
        
    pdf.set_font("Arial", 'B', 11)
    pdf.cell(150, 8, "Total Payable Amount:", border=1, align='R')
    pdf.cell(40, 8, f"INR {total_amt:.2f}", border=1, align='R')
    
    return bytes(pdf.output())

# AI Bill Scanner Config
if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

def process_bill_with_ai(image):
    model = genai.GenerativeModel('gemini-3.5-flash')
    prompt = """Extract invoice details from image in JSON format matching this structure:
    {"party_name": "...", "inv_no": "...", "items": [{"HSN": "3004", "PRODUCT": "...", "QTY": 0.0, "BONUS": 0.0, "RATE": 0.0, "DIS %": 0.0, "Gst%": 5.0, "BATCH": "...", "EXP": "04-28", "MRP": 0.0}]}"""
    response = model.generate_content([prompt, image])
    clean_json = response.text.replace("```json", "").replace("
