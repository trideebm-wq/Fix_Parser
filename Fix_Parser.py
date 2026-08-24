import streamlit as st
import pandas as pd
import json

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
    "6": "AvgPx", "790": "AllocReportID", "70": "AllocID", "78": "NoAllocs",
    "79": "AllocAccount", "80": "AllocQty"
}

MSG_TYPES = {
    "0": "Heartbeat", "1": "Test Request", "2": "Resend Request", 
    "3": "Reject", "4": "Sequence Reset", "5": "Logout", 
    "8": "Execution Report", "D": "New Order Single", "9": "Order Cancel Reject",
    "G": "Order Cancel/Replace Request", "F": "Order Cancel Request", 
    "J": "Allocation Instruction", "W": "Market Data Snapshot"
}

SIDE_TYPES = {"1": "BUY / TAKE", "2": "SELL / GIVE"}

# Pre-packaged Mock Scenarios
SCENARIOS = {
    "1. Clean STP Pass": "8=FIX.4.4|9=145|35=8|49=CLSA_SG|56=CITI_HK|34=101|52=20260824-10:00:00|11=CLORD12345|37=ORD98765|17=EXEC001|150=2|39=2|55=USD/HKD|54=1|38=5000000|44=7.8020|15=HKD|",
    "2. FX Block Trade (Valid Allocations)": "8=FIX.4.4|9=210|35=J|49=BLACKROCK_NY|56=HSBC_HK|34=882|52=20260824-11:15:00|790=REP99182|55=EUR/USD|54=1|38=10000000|15=USD|78=3|79=FUND_APAC_A|80=5000000|79=FUND_EM_B|80=3000000|79=FUND_GLO_C|80=2000000|",
    "3. FX Block Trade (ALLOCATION MISMATCH BREAK)": "8=FIX.4.4|9=210|35=J|49=PIMCO_LN|56=CITI_SG|34=883|52=20260824-11:18:22|790=REP99183|55=GBP/USD|54=2|38=15000000|15=USD|78=2|79=SUB_ACC_01|80=8000000|79=SUB_ACC_02|80=6000000|",
    "4. Front Office Validation Break (Missing Price)": "8=FIX.4.4|9=120|35=D|49=HSBC_HK|56=UBS_SG|34=402|52=20260824-10:15:30|11=CLORD55555|55=USD/JPY|54=2|38=2500000|40=2|15=JPY|60=20260824-10:15:29|"
}

# -----------------------------------------------------------------------------
# CORE PARSING ENGINE
# -----------------------------------------------------------------------------
def parse_fix_to_structured_data(fix_string: str):
    """Parses raw FIX string into standard tag-value dictionary and handles repeating allocation groups."""
    normalized = fix_string.replace(" ", "|").replace("^A", "|").replace(";", "|")
    pairs = [p for p in normalized.split("|") if "=" in p]
    
    flat_tags = {}
    allocations = []
    
    current_alloc_acc = None
    
    for pair in pairs:
        tag, val = pair.split("=", 1)
        tag, val = tag.strip(), val.strip()
        
        # Look for repeating FX allocation blocks (Tags 79 & 80)
        if tag == "79":
            current_alloc_acc = val
        elif tag == "80" and current_alloc_acc:
            allocations.append({"Allocation Account": current_alloc_acc, "Allocated Volume": float(val)})
            current_alloc_acc = None
        else:
            flat_tags[tag] = val
            
    return flat_tags, allocations

def validate_trade_flows(fields: dict, allocs: list) -> list:
    """Business Analyst Rule Engine mapping industry cross-validation rules."""
    exceptions = []
    msg_type = fields.get("35")
    
    if not msg_type:
        exceptions.append("CRITICAL: Missing MsgType (Tag 35)")
        return exceptions

    # Rule 1: Limit Order Check
    if fields.get("40") == "2" and not fields.get("44"):
        exceptions.append("BUSINESS RULE: Order Type is 'Limit' (Tag 40=2) but explicit Price (Tag 44) is missing.")

    # Rule 2: Dynamic Currency Pair Integrity
    symbol = fields.get("55", "")
    currency = fields.get("15", "")
    if "/" in symbol and currency:
        base_ccy, terms_ccy = symbol.split("/", 1)
        if currency != terms_ccy:
            exceptions.append(f"STATIC DATA BREAK: FX Cross '{symbol}' settles in '{terms_ccy}', but execution currency is set to '{currency}'.")

    # Rule 3: Repeating Block Allocation Engine (Tag 78, 79, 80 validation)
    if msg_type == "J" or len(allocs) > 0:
        total_block_qty = float(fields.get("38", 0))
        declared_num_allocs = int(fields.get("78", 0))
        actual_num_allocs = len(allocs)
        sum_allocated_qty = sum(item["Allocated Volume"] for item in allocs)
        
        if declared_num_allocs != actual_num_allocs:
            exceptions.append(f"REPEATING GROUP ERROR: Tag 78 declares {declared_num_allocs} allocations, but processed exactly {actual_num_allocs} details.")
            
        if total_block_qty != sum_allocated_qty:
            variance = total_block_qty - sum_allocated_qty
            exceptions.append(f"ALLOCATION BALANCING BREAK: Block OrderQty ({total_block_qty:,.0f}) does not match Sum of Sub-Allocations ({sum_allocated_qty:,.0f}). Out of balance by: {variance:,.0f}.")
            
    return exceptions

# -----------------------------------------------------------------------------
# USER INTERFACE LAYOUT
# -----------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="FIX FX Block Allocation Engine")

st.title("📟 Front-to-Back FIX Protocol Parsing & FX Block Allocation Engine")
st.markdown("""
**Author:** Trideeb Mukherjee — Senior Project Manager & Business Analyst (22 Years Exp Banking & FICC IT)  
*This modular sandbox parses raw infrastructure logs, maps repeating allocation matrices, and highlights mid-office exceptions.*
""")

# Dashboard Input Section
col_left, col_right = st.columns([1.2, 1])

with col_left:
    st.subheader("📥 Input Layer: Raw FX Fix Log")
    scenario_selection = st.selectbox("Inject Pre-Configured Capital Market Scenarios:", options=list(SCENARIOS.keys()))
    
    raw_fix_input = st.text_area(
        "Raw String Stream Console (Supports SOH, pipe '|', or semicolon ';'):",
        value=SCENARIOS[scenario_selection],
        height=140
    )

with col_right:
    st.subheader("🎯 Operations Room: Exception Desk")
    if raw_fix_input:
        dict_fields, list_allocations = parse_fix_to_structured_data(raw_fix_input)
        engine_alerts = validate_trade_flows(dict_fields, list_allocations)
        
        if not engine_alerts:
            st.success("✅ **STP PROCESSING PASS:** No clearing breaks detected. Message cleared for straight-through-processing downstream.")
        else:
            for alert in engine_alerts:
                st.error(f"🚨 {alert}")
    else:
        st.info("Awaiting input data stream to run validation rules.")

# Visual Blocks for Allocations if present
if raw_fix_input and list_allocations:
    st.markdown("---")
    st.subheader("📊 Dynamic FX Allocation Component Matrix")
    st.markdown(f"**Parent Block Total Volume (Tag 38):** `{float(dict_fields.get('38', 0)):,.2f} {dict_fields.get('15','')}`")
    
    col_metric1, col_metric2 = st.columns(2)
    sum_vol = sum(x["Allocated Volume"] for x in list_allocations)
    target_vol = float(dict_fields.get('38', 0))
    
    col_metric1.metric("Sum of Allocated Entities", f"{sum_vol:,.2f}")
    col_metric2.metric("Unallocated Balance Variance", f"{(target_vol - sum_vol):,.2f}", delta=f"{(target_vol - sum_vol):,.2f}", delta_color="inverse")
    
    st.dataframe(pd.DataFrame(list_allocations), use_container_width=True, hide_index=True)

# Human Readable Mapping
if raw_fix_input and dict_fields:
    st.markdown("---")
    st.subheader("🔍 Metadata Discovery & Technical Tag Mapping")
    
    ui_table_data = []
    for tag, val in dict_fields.items():
        tag_desc = FIX_DICTIONARY.get(tag, "Custom / Sub-Schema Field")
        translated_val = val
        if tag == "35": translated_val = f"{val} ({MSG_TYPES.get(val, 'Unknown')})"
        elif tag == "54": translated_val = f"{val} ({SIDE_TYPES.get(val, 'Unknown')})"
            
        ui_table_data.append({"FIX Tag": tag, "Protocol Definition": tag_desc, "Raw Value": val, "Business Interpretation": translated_val})
        
    st.dataframe(pd.DataFrame(ui_table_data), use_container_width=True, hide_index=True)
