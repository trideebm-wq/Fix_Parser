
import streamlit as st
import pandas as pd
import datetime

# -----------------------------------------------------------------------------
# CONSTANTS & DICTIONARIES
# -----------------------------------------------------------------------------
FIX_DICTIONARY = {
    "8": "BeginString", "9": "BodyLength", "35": "MsgType", "49": "SenderCompID",
    "56": "TargetCompID", "34": "MsgSeqNum", "52": "SendingTime", "11": "ClOrdID",
    "21": "HandlInst", "55": "Symbol", "54": "Side", "38": "OrderQty", 
    "40": "OrdType", "44": "Price", "59": "TimeInForce", "60": "TransactTime",
    "15": "Currency", "22": "IDSource", "48": "SecurityID", "1": "Account",
    "150": "ExecType", "39": "OrdStatus", "37": "OrderID", "17": "ExecID",
    "32": "LastShares", "31": "LastPx", "151": "LeavesQty", "14": "CumQty",
    "6": "AvgPx", "790": "AllocReportID", "70": "AllocID", "78": "NoAllocs"
}

MSG_TYPES = {
    "0": "Heartbeat", "1": "Test Request", "2": "Resend Request", 
    "3": "Reject", "4": "Sequence Reset", "5": "Logout", 
    "8": "Execution Report", "D": "New Order Single", "9": "Order Cancel Reject",
    "G": "Order Cancel/Replace Request", "F": "Order Cancel Request", "J": "Allocation Instruction"
}

SIDE_TYPES = {"1": "BUY", "2": "SELL", "3": "BUY PROFILE", "4": "SELL SHORT"}
ORD_STATUS_TYPES = {"0": "New", "1": "Partially Filled", "2": "Filled", "8": "Rejected"}

MOCK_RAW_STRINGS = [
    # Clean trade
    "8=FIX.4.4 9=145 35=8 49=CLSA_SG 56=CITI_HK 34=101 52=20260821-10:00:00 11=CLORD12345 37=ORD98765 17=EXEC001 150=2 39=2 55=0005.HK 54=1 38=50000 44=65.50 32=50000 31=65.50 151=0 14=50000 6=65.50 15=HKD ",
    # Exception: Missing Price on Limit Order
    "8=FIX.4.4 9=120 35=D 49=HSBC_HK 56=UBS_SG 34=402 52=20260821-10:15:30 11=CLORD55555 55=700.HK 54=2 38=10000 40=2 15=HKD 60=20260821-10:15:29 ",
    # Exception: Currency / Symbol Mismatch (US T-Bill in EUR)
    "8=FIX.4.4 9=135 35=8 49=BEAR_STEARNS 56=CITI_SG 34=789 52=20260821-10:20:12 11=CLORD999 37=ORD111 17=EXEC002 150=0 39=0 55=US912828ZS88 54=1 38=1000000 44=98.25 15=EUR ",
    # Exception: Quantity Mismatch (CumQty + LeavesQty != OrderQty)
    "8=FIX.4.4 9=150 35=8 49=CLSA_SG 56=HSBC_HK 34=102 52=20260821-10:22:00 11=CLORD12346 37=ORD98766 17=EXEC003 150=1 39=1 55=9988.HK 54=1 38=20000 44=92.10 32=5000 31=92.10 151=10000 14=5000 6=92.10 15=HKD "
]

# -----------------------------------------------------------------------------
# HELPER FUNCTIONS
# -----------------------------------------------------------------------------
def parse_fix_to_dict(fix_string: str) -> dict:
    """Parses raw FIX string using SOH delimiter (standardized to pipe or visual block)."""
    # Standardize common delimiters to a common split token
    normalized = fix_string.replace(" ", "|").replace("^A", "|").replace(";", "|")
    pairs = [p for p in normalized.split("|") if "=" in p]
    
    parsed = {}
    for pair in pairs:
        tag, val = pair.split("=", 1)
        parsed[tag.strip()] = val.strip()
    return parsed

def run_exception_engine(parsed_fields: dict) -> list:
    """Business Analyst Rule Engine mapping industry validation criteria."""
    exceptions = []
    
    # Rule 1: Message Type Check
    msg_type = parsed_fields.get("35")
    if not msg_type:
        exceptions.append("CRITICAL: Missing MsgType (Tag 35)")
        return exceptions

    # Rule 2: Limit Order missing explicit price
    ord_type = parsed_fields.get("40")
    if ord_type == "2" and not parsed_fields.get("44"):
        exceptions.append("BUSINESS RULE: Order Type is 'Limit' (Tag 40=2) but Price (Tag 44) is missing.")

    # Rule 3: Static Data Cross-Validation (Symbol & Currency Logic)
    symbol = parsed_fields.get("55", "")
    currency = parsed_fields.get("15", "")
    if ".HK" in symbol and currency != "HKD":
        exceptions.append(f"STATIC DATA BREAK: Asset '{symbol}' implies Hong Kong market, but Settlement Currency is '{currency}'.")
    if symbol.startswith("US") and len(symbol) == 12 and currency not in ["USD", ""]:
        exceptions.append(f"STATIC DATA BREAK: CUSIP/ISIN '{symbol}' implies US Market Treasury/Fixed Income, but Currency is '{currency}'.")

    # Rule 4: Post-Trade State Machine Check (Execution Reports Lifecycle)
    if msg_type == "8":
        order_qty = pd.to_numeric(parsed_fields.get("38", 0), errors='coerce')
        cum_qty = pd.to_numeric(parsed_fields.get("14", 0), errors='coerce')
        leaves_qty = pd.to_numeric(parsed_fields.get("151", 0), errors='coerce')
        
        if (cum_qty + leaves_qty) != order_qty:
            exceptions.append(f"POST-TRADE BREAK: Mathematical mismatch. OrderQty ({order_qty}) != CumQty ({cum_qty}) + LeavesQty ({leaves_qty}).")

    return exceptions

# -----------------------------------------------------------------------------
# APPLICATION UI LAYOUT
# -----------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="FIX Protocol Exception Engine")

st.title("📟 Front-to-Back FIX Protocol Parsing & Exception Engine")
st.markdown("""
**Author:** Trideeb Mukherjee — Senior Project Manager & Business Analyst (22 Years Exp Banking & FICC IT)  
*This proof-of-concept simulates middle-office validations across Trade Capture, DMA Execution, and Clearing flows.*
""")

col_left, col_right = st.columns([1, 1])

with col_left:
    st.subheader("📥 Input Layer: Raw FIX Stream")
    
    # Load Quick Mock Samples
    sample_choice = st.selectbox(
        "Select a Pre-configured Production Scenario:",
        options=["-- Direct User Custom Input --", "1. STP Execution Report (Clean Pass)", "2. New Order Single (Front Office Validation Break)", "3. FICC Treasury Booking (Currency Mismatch)", "4. Clearing & Settlement Flow (Post-Trade State Break)"]
    )
    
    default_text = ""
    if "1." in sample_choice: default_text = MOCK_RAW_STRINGS[0]
    elif "2." in sample_choice: default_text = MOCK_RAW_STRINGS[1]
    elif "3." in sample_choice: default_text = MOCK_RAW_STRINGS[2]
    elif "4." in sample_choice: default_text = MOCK_RAW_STRINGS[3]

    raw_fix_input = st.text_area(
        "Paste Raw FIX String here (Supports SOH, pipe '|', or semicolon ';' separators):",
        value=default_text,
        placeholder="8=FIX.4.4|9=120|35=D|...",
        height=180
    )

with col_right:
    st.subheader("🎯 Operations Room: Exception Desk")
    if raw_fix_input:
        dict_fields = parse_fix_to_dict(raw_fix_input)
        engine_alerts = run_exception_engine(dict_fields)
        
        if not engine_alerts:
            st.success("✅ **STP PASS:** No systemic exceptions detected. Message ready for straight-through downstream clearing.")
        else:
            for alert in engine_alerts:
                if "CRITICAL" in alert or "BREAK" in alert:
                    st.error(f"🚨 {alert}")
                else:
                    st.warning(f"⚠️ {alert}")
    else:
        st.info("Awaiting input data stream to run validation rules.")

# Detailed Parsing Workspace
if raw_fix_input and dict_fields:
    st.markdown("---")
    st.subheader("🔍 Metadata Discovery & Human-Readable Mapping")
    
    # Transpose parsed fields for a structured ledger table
    ui_table_data = []
    for tag, val in dict_fields.items():
        tag_desc = FIX_DICTIONARY.get(tag, "Custom / Vendor Specific Tag")
        
        # Add rich human context definitions
        translated_val = val
        if tag == "35": translated_val = f"{val} ({MSG_TYPES.get(val, 'Unknown')})"
        elif tag == "54": translated_val = f"{val} ({SIDE_TYPES.get(val, 'Unknown')})"
        elif tag == "39": translated_val = f"{val} ({ORD_STATUS_TYPES.get(val, 'Unknown')})"
            
        ui_table_data.append({"FIX Tag": tag, "Protocol Definition": tag_desc, "Raw Component": val, "Interpreted Meaning": translated_val})
        
    df_resolved = pd.DataFrame(ui_table_data)
    st.dataframe(df_resolved, use_container_width=True, hide_index=True)
