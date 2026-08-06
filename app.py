# ----------------------------------------------------
# 2. AI PHOTO SCANNER (AUTO DETECT WORKING MODEL)
# ----------------------------------------------------
elif menu == "📸 AI Photo Scanner":
    st.subheader("📸 Scan Handwritten Bill with Free AI")
    uploaded_file = st.file_uploader("Upload Handwritten Slip Photo", type=['jpg', 'jpeg', 'png'])

    if uploaded_file:
        st.image(uploaded_file, caption="Uploaded Slip", width=350)
        
        if st.button("🚀 Auto-Scan Bill"):
            prompt = """Extract product details from this pharmaceutical bill/slip image.
Return ONLY valid JSON in this exact structure with double quotes:
[{"Product Name": "ITEM", "HSN": "3004", "Batch": "B01", "Expiry": "2027-12", "Qty": 10, "Free Qty": 0, "MRP": 100.0, "Discount %": 0, "GST %": 12}]"""

            raw_text = None

            # 1. ATTEMPT: GOOGLE GEMINI (Try latest 2.0 and 1.5 models)
            if gemini_api_key:
                with st.spinner("🔍 Trying Google Gemini AI..."):
                    genai.configure(api_key=gemini_api_key)
                    for gem_model in ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"]:
                        try:
                            model = genai.GenerativeModel(gem_model)
                            image = Image.open(uploaded_file)
                            image.thumbnail((1024, 1024))
                            response = model.generate_content([prompt, image])
                            raw_text = response.text.strip()
                            if raw_text:
                                st.info(f"🤖 Scanned with Google Gemini (`{gem_model}`)!")
                                break
                        except Exception:
                            continue

            # 2. FALLBACK: GROQ FREE VISION (Try standard active Vision endpoints)
            if not raw_text and groq_api_key and HAS_GROQ:
                st.warning("⚠️ Gemini Limit reached. Switching to Groq AI...")
                with st.spinner("🧠 Scanning with Groq Vision..."):
                    try:
                        client = Groq(api_key=groq_api_key)
                        bytes_data = uploaded_file.getvalue()
                        base64_image = base64.b64encode(bytes_data).decode('utf-8')
                        
                        # Groq Vision Model Name Fallbacks
                        groq_models = [
                            "llama-3.2-11b-vision-instruct", 
                            "llama-3.2-11b-instruct",
                            "meta-llama/llama-3.2-11b-vision-instruct"
                        ]
                        
                        for g_model in groq_models:
                            try:
                                response = client.chat.completions.create(
                                    model=g_model,
                                    messages=[{
                                        "role": "user",
                                        "content": [
                                            {"type": "text", "text": prompt},
                                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                                        ]
                                    }],
                                    max_tokens=1000
                                )
                                raw_text = response.choices[0].message.content.strip()
                                if raw_text:
                                    st.info(f"🤖 Scanned with Groq (`{g_model}`)!")
                                    break
                            except Exception:
                                continue
                    except Exception as e:
                        st.error(f"Groq Connection Error: {e}")

            # PARSE JSON OUTPUT
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
                    st.success("✅ AI Scan Successful!")
                else:
                    st.error("Data parse nahi ho saka. Raw Output:")
                    st.code(raw_text)
