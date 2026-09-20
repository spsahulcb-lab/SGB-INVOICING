elif active_tab == "🏷️ Manage Master Products":
    st.markdown("<h2 style='color: #E65100;'>🏷️ Manage Master Products List</h2>", unsafe_allow_html=True)
    
    m_col1, m_col2 = st.columns([1, 1])
    
    with m_col1:
        st.markdown("### ➕ Add Single Product")
        single_p = st.text_input("Product Name (e.g. Brainenza Syrup)")
        if st.button("➕ Add Product to Master"):
            if single_p:
                add_master_product(single_p)
                st.success(f"✅ Product '{single_p}' added successfully!")
                st.rerun()
                
        st.markdown("---")
        st.markdown("### 📂 Upload New Product List (CSV / Excel)")
        file_up = st.file_uploader("Upload CSV or Excel File", type=["csv", "xlsx", "xls"])
        if file_up:
            try:
                # Handle .xls, .xlsx, and .csv
                if file_up.name.endswith('.csv'):
                    df_up = pd.read_csv(file_up)
                else:
                    try:
                        df_up = pd.read_excel(file_up)
                    except Exception:
                        df_up = pd.read_excel(file_up, engine='xlrd')
                
                # Check if header is in row 2 or 3 (like title present on top)
                if 'Product' not in df_up.columns and not any("product" in str(c).lower() for c in df_up.columns):
                    file_up.seek(0)
                    if file_up.name.endswith('.csv'):
                        df_up = pd.read_csv(file_up, skiprows=2)
                    else:
                        df_up = pd.read_excel(file_up, skiprows=2)
                    
                st.write("Preview of uploaded list:")
                st.dataframe(df_up.head(), use_container_width=True)
                
                # Auto-select 'Product' column if present
                prod_cols = [c for c in df_up.columns if "product" in str(c).lower()]
                default_idx = df_up.columns.get_loc(prod_cols[0]) if prod_cols else 0
                
                col_name = st.selectbox("Select Column containing Product Names", df_up.columns, index=default_idx)
                
                if st.button("🚀 Upload & Add to Master List"):
                    plist = df_up[col_name].dropna().astype(str).tolist()
                    bulk_upload_master_products(plist)
                    st.success(f"✅ Successfully added {len(plist)} products to Master List!")
                    st.rerun()
            except Exception as ex:
                st.error(f"Error reading file: {ex}. Try saving the file as .xlsx or .csv format.")

    with m_col2:
        st.markdown("### 📋 Current Master Products")
        m_list = load_master_products()
        st.dataframe(pd.DataFrame({"Product Name": m_list}), use_container_width=True)
        
        st.markdown("---")
        st.markdown("##### 🗑️ Remove Product")
        del_p = st.selectbox("Select Product to Delete", m_list if m_list else ["None"])
        if st.button("❌ Delete Product"):
            if del_p != "None":
                delete_master_product(del_p)
                st.success(f"Product '{del_p}' deleted.")
                st.rerun()
