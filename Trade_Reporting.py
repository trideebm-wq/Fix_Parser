import streamlit as st
import pandas as pd
import re
from datetime import datetime
from sqlalchemy import create_engine, text

# -----------------------------------------------------------------------------
# 1. DATABASE CONNECTION
# -----------------------------------------------------------------------------
# Update with your PostgreSQL credentials or use streamlit secrets
DB_URL = "postgresql://postgres:Tcon$$1234@localhost:5432/hkma_reporting_db"

@st.cache_resource
def get_db_engine():
    """Caches the database engine connection to reuse across sessions."""
    return create_engine(DB_URL)

engine = get_db_engine()

# -----------------------------------------------------------------------------
# 2. HKMA VALIDATION ENGINE
# -----------------------------------------------------------------------------
def validate_hkma_trade(row):
    """Validates a single trade row against basic HKMA reporting rules."""
    errors = []
    
    # Rule 1: UTI Format (Must be alphanumeric, typically up to 52 chars)
    if pd.isna(row.get('uti')) or not re.match(r'^[A-Z0-9]{1,52}$', str(row['uti']).upper()):
        errors.append({"field": "uti", "message": "UTI must be alphanumeric and up to 52 characters."})
        
    # Rule 2: LEI Formats (Must be exactly 20 characters alphanumeric)
    for lei_field in ['reporting_party_lei', 'counterparty_lei']:
        lei_val = str(row.get(lei_field, ''))
        if pd.isna(row.get(lei_field)) or not re.match(r'^[A-Z0-9]{20}$', lei_val.upper()):
            errors.append({"field": lei_field, "message": f"{lei_field.replace('_', ' ').title()} must be a valid 20-character LEI."})
            
    # Rule 3: Maturity Date must be after Effective Date
    try:
        eff_date = pd.to_datetime(row.get('effective_date'))
        mat_date = pd.to_datetime(row.get('maturity_date'))
        if eff_date >= mat_date:
            errors.append({"field": "maturity_date", "message": "Maturity date must be strictly after the effective date."})
    except Exception:
        errors.append({"field": "dates", "message": "Invalid date formats provided."})
        
    # Rule 4: Notional Amount must be positive
    if pd.isna(row.get('notional_amount')) or float(row['notional_amount']) <= 0:
        errors.append({"field": "notional_amount", "message": "Notional amount must be greater than zero."})

    return errors

# -----------------------------------------------------------------------------
# 3. STREAMLIT UI & DASHBOARD
# -----------------------------------------------------------------------------
st.set_page_config(page_title="HKMA Trade Reporting Prototype", layout="wide")
st.title("🏦 HKMA Trade Reporting & Validation Portal")
st.markdown("Prototype application to ingest OTC derivatives, execute regulatory validation, and report to HKMA.")

# Sidebar for actions
st.sidebar.header("Navigation & Actions")
app_mode = st.sidebar.radio("Go to", ["Dashboard & Reports", "Ingest Raw Data"])

# --- MODE 1: INGEST RAW DATA ---
if app_mode == "Ingest Raw Data":
    st.header("📥 Data Ingestion Panel")
    st.write("Upload a CSV file or paste raw CSV format text to simulate trade ingestion.")
    
    # Template download helper
    template_data = {
        "uti": ["UTI1234567890123456789012345678901234567890123456789012"],
        "trade_id_source": ["SYS-001"],
        "asset_class": ["INTEREST_RATE"],
        "product_type": ["Vanilla Swap"],
        "reporting_party_lei": ["XYZREPORTINGPARTY1234"],
        "counterparty_lei": ["INVALID_LEI_SHORT"],
        "notional_amount": [5000000.00],
        "currency": ["HKD"],
        "price_rate": [0.035],
        "execution_timestamp": ["2026-02-25 10:00:00+08"],
        "effective_date": ["2026-02-26"],
        "maturity_date": ["2025-02-26"] # deliberate error: maturity before effective
    }
    
    st.download_button(
        label="📥 Download Template CSV",
        data=pd.DataFrame(template_data).to_csv(index=False),
        file_name="hkma_trade_template.csv",
        mime="text/csv"
    )

    uploaded_file = st.file_uploader("Choose a CSV file containing trades", type="csv")
    
    if uploaded_file is not None:
        raw_df = pd.read_csv(uploaded_file)
        st.subheader("Preview Ingested Data")
        st.dataframe(raw_df)
        
        if st.button("🚀 Run HKMA Validation & Save to Database"):
            success_count = 0
            fail_count = 0
            
            with engine.begin() as conn:
                for idx, row in raw_df.iterrows():
                    # Check validation errors
                    errors = validate_hkma_trade(row)
                    status = "FAILED" if errors else "VALIDATED"
                    
                    # Insert trade
                    trade_query = text("""
                        INSERT INTO trades (uti, trade_id_source, asset_class, product_type, reporting_party_lei, counterparty_lei, notional_amount, currency, price_rate, execution_timestamp, effective_date, maturity_date)
                        VALUES (:uti, :trade_id_source, :asset_class, :product_type, :reporting_party_lei, :counterparty_lei, :notional_amount, :currency, :price_rate, :execution_timestamp, :effective_date, :maturity_date)
                        ON CONFLICT (uti) DO UPDATE SET updated_at = CURRENT_TIMESTAMP
                        RETURNING id;
                    """)
                    
                    try:
                        result = conn.execute(trade_query, {
                            "uti": row['uti'], "trade_id_source": row['trade_id_source'], "asset_class": row['asset_class'],
                            "product_type": row['product_type'], "reporting_party_lei": row['reporting_party_lei'],
                            "counterparty_lei": row['counterparty_lei'], "notional_amount": row['notional_amount'],
                            "currency": row['currency'], "price_rate": row.get('price_rate'),
                            "execution_timestamp": row['execution_timestamp'], "effective_date": row['effective_date'],
                            "maturity_date": row['maturity_date']
                        })
                        trade_id = result.fetchone()[0]
                        
                        # Clear old errors if re-uploading
                        conn.execute(text("DELETE FROM validation_errors WHERE trade_id = :trade_id"), {"trade_id": trade_id})
                        
                        if errors:
                            fail_count += 1
                            for err in errors:
                                conn.execute(text("""
                                    INSERT INTO validation_errors (trade_id, field_name, error_message)
                                    VALUES (:trade_id, :field_name, :error_message)
                                """), {"trade_id": trade_id, "field_name": err['field'], "error_message": err['message']})
                        else:
                            success_count += 1
                            
                        # Insert initial reporting log state
                        conn.execute(text("""
                            INSERT INTO reporting_logs (trade_id, status) VALUES (:trade_id, :status)
                            ON CONFLICT DO NOTHING;
                        """), {"trade_id": trade_id, "status": status})
                        
                    except Exception as e:
                        st.error(f"Database error on row {idx}: {e}")
                        
            st.success(f"Processing Complete! Passed validation: {success_count} trades. Failed validation: {fail_count} trades.")

# --- MODE 2: DASHBOARD & REPORTS ---
else:
    st.header("📊 Compliance Reporting Dashboard")
    
    # Fetch overview numbers from DB
    with engine.connect() as conn:
        total_trades = conn.execute(text("SELECT COUNT(*) FROM trades")).scalar()
        failed_trades = conn.execute(text("SELECT COUNT(DISTINCT trade_id) FROM validation_errors")).scalar()
        passed_trades = total_trades - failed_trades
        
        # Pull detailed reporting overview
        report_df = pd.read_sql(text("""
            SELECT t.id, t.uti, t.asset_class, t.notional_amount, t.currency, rl.status,
                   COALESCE(string_agg(ve.error_message, ' | '), 'No Errors') as validation_messages
            FROM trades t
            LEFT JOIN reporting_logs rl ON t.id = rl.trade_id
            LEFT JOIN validation_errors ve ON t.id = ve.trade_id
            GROUP BY t.id, rl.status;
        """), conn)

    # Top KPI Metrics Cards
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Ingested", total_trades)
    col2.metric("Passed Validation", passed_trades, delta=f"{passed_trades} Clean" if total_trades else "0")
    col3.metric("Validation Errors", failed_trades, delta=f"-{failed_trades} Blocked" if failed_trades else "0", delta_color="inverse")
    
    compliance_rate = (passed_trades / total_trades * 100) if total_trades else 100
    col4.metric("Compliance Rate", f"{compliance_rate:.1f}%")

    st.markdown("---")
    
    # Filtering visual reports
    st.subheader("📋 Core Trade Status Logs")
    status_filter = st.multiselect("Filter by Status", options=["VALIDATED", "FAILED", "PENDING", "REPORTED"], default=["VALIDATED", "FAILED"])
    
    if not report_df.empty:
        filtered_df = report_df[report_df['status'].isin(status_filter)]
        st.dataframe(filtered_df, use_container_width=True)
        
        # Submit to simulated HKMA API Action
        st.subheader("⚡ Action Center")
        if st.button("Submit Clean Trades to HKMA TR"):
            validated_trade_ids = report_df[report_df['status'] == 'VALIDATED']['id'].tolist()
            if not validated_trade_ids:
                st.warning("No clean 'VALIDATED' trades ready for submission.")
            else:
                with engine.begin() as conn:
                    for t_id in validated_trade_ids: