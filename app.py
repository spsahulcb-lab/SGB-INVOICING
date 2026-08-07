# ----------------------------------------------------
# 2. AI PHOTO SCANNER (SAFE & FAST)
# ----------------------------------------------------
elif menu == "📸 AI Photo Scanner":
    st.subheader("📸 Scan Handwritten Slip with Smart Master Matching")
    uploaded_file = st.file_uploader("Upload Handwritten Slip Photo", type=['jpg', 'jpeg', 'png'])

    if uploaded_file:
        st.image(uploaded_file, caption="Uploaded Slip", width=350)
        
        if st.button("🚀 Auto-Scan & Match with Stock"):
            if not gemini_api_key or gemini_api_key.strip() == "":
                st.error("❌ GEMINI_API_KEY Streamlit Secrets me nahi mili! Kripya new key dalein.")
            else:
                try:
                    current_stock = get_stock()
                    master_products = current_stock["Product Name"].tolist()
                    master_list_str = ", ".join(master_products)

                    prompt = f"""Extract product details from this pharmaceutical bill/slip image.
MASTER PRODUCT LIST FOR MATCHING CLUES: [{master_list_str}]

INSTRUCTIONS:
1. Match handwritten names with MASTER PRODUCT LIST if spelling is close.
2. Return ONLY valid JSON array:
[
  {{"Product Name": "ITEM NAME", "HSN": "3004", "Batch": "B01", "Expiry": "2027-12", "Qty": 10, "Free Qty": 0, "MRP": 100.0, "Discount %": 0, "GST %": 12}}
]"""

                    raw_text = None
                    with st.spinner("🔍 AI Reading slip... Please wait..."):
                        genai.configure(api_key=gemini_api_key)
                        
                        # Fallback try between flash models
                        image = Image.open(uploaded_file)
                        image.thumbnail((1024, 1024))
                        
                        try:
                            model = genai.GenerativeModel("gemini-2.0-flash")
                            response = model.generate_content([prompt, image])
                            raw_text = response.text.strip()
                        except Exception:
                            # Fallback model if 2.0 has rate limits
                            model = genai.GenerativeModel("gemini-1.5-flash")
                            response = model.generate_content([prompt, image])
                            raw_text = response.text.strip()

                    if raw_text:
                        cleaned = raw_text.replace("```json", "").replace("```", "").strip()
                        json_match = re.search(r'\[.*\]', cleaned, re.DOTALL)
                        target_str = json_match.group(0) if json_match else cleaned
                        
                        parsed_data = None
                        try:
                            parsed_data = json.loads(target_str)
                        except Exception:
                            try:
                                parsed_data = ast.literal_eval(target_str)
                            except Exception:
                                pass
                        
                        if parsed_data and isinstance(parsed_data, list):
                            st.session_state['scanned_items'] = parsed_data
                            st.success("✅ Bill Scanned Successfully!")
                            st.rerun()
                        else:
                            st.error("Data read ho gaya par JSON parse nahi hua. Raw response:")
                            st.code(raw_text)

                except Exception as err:
                    st.error(f"❌ Scan Error (Key Quota or Network Issue): {err}")
                    st.info("💡 Solution: AI Studio se NEW Project bana kar nayi API Key Streamlit Secrets me dalein.")
