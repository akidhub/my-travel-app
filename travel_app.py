# --- 版本：v43 (換匯記錄全動態編輯版) ---

import streamlit as st
import pandas as pd
import pdfplumber
import re
import pytesseract
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener
import datetime
import html
from streamlit_gsheets import GSheetsConnection

# --- 註冊 HEIC 解碼器 ---
register_heif_opener()

# --- 網頁配置 ---
st.set_page_config(page_title="旅遊隨身夥伴", layout="centered", initial_sidebar_state="collapsed")

# 🚀 自定義 CSS 
st.markdown("""
    <style>
    .main { background-color: transparent; }
    .stButton>button { width: 100%; border-radius: 10px; height: 3em; background-color: #007bff; color: white; }
    .stExpander { border: none !important; box-shadow: none !important; }
    div[data-testid="stMetricValue"] { font-size: 1.8rem; color: #007bff; }
    
    .itinerary-card { background-color: #ffffff; padding: 15px; border-radius: 10px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); margin-bottom: 10px; border-left: 5px solid #007bff; color: #333333; }
    .hotel-card { background-color: #fff3cd; padding: 15px; border-radius: 10px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); margin-bottom: 10px; border-left: 5px solid #ffc107; color: #333333; }
    .booking-card { background-color: #ffffff; padding: 15px; border-radius: 10px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); margin-bottom: 10px; border-left: 5px solid #17a2b8; color: #333333; }
    .exchange-card { background-color: #e2f0d9; padding: 15px; border-radius: 10px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); margin-bottom: 10px; border-left: 5px solid #28a745; color: #333333; }
    
    .time-text { color: #007bff; font-weight: bold; font-size: 1.1rem; }
    .dest-text { font-size: 1.2rem; font-weight: bold; margin-bottom: 5px; color: #212529; }
    .detail-text { color: #495057; font-size: 0.9rem; margin-bottom: 3px; }
    .platform-badge { background-color: #17a2b8; color: white; padding: 2px 6px; border-radius: 5px; font-size: 0.8rem; vertical-align: middle; margin-left: 5px; }
    </style>
    """, unsafe_allow_html=True)

st.title("✈️ 旅遊紀錄夥伴")

# 🚀 Google Sheets 連線設定
SHEET_URL = "https://docs.google.com/spreadsheets/d/1rjD0pOEltqRsv_NrcqQ9FKX_R2oe7IY3nJ0HHj57oI0/edit"
conn = st.connection("gsheets", type=GSheetsConnection)

# --- 側邊欄：手動強制同步按鈕 ---
with st.sidebar:
    st.markdown("### ☁️ 雲端同步狀態")
    st.success("🟢 已連線至 Google Sheets")
    if st.button("🔄 強制重新載入雲端資料"):
        st.cache_data.clear()
        st.rerun()

# --- 雲端資料庫讀寫模組 ---
@st.cache_data(ttl=10)
def load_data_from_gs(worksheet_name, cols):
    try:
        df = conn.read(spreadsheet=SHEET_URL, worksheet=worksheet_name) 
        if df.empty and len(df.columns) == 0:
            return pd.DataFrame(columns=cols)
        return df.dropna(how="all")
    except Exception as e:
        return pd.DataFrame(columns=cols)

def save_data_to_gs(worksheet_name, df):
    df_upload = df.copy()
    for col in df_upload.columns:
        if pd.api.types.is_datetime64_any_dtype(df_upload[col]) or pd.api.types.is_object_dtype(df_upload[col]):
            df_upload[col] = df_upload[col].astype(str)
    conn.update(spreadsheet=SHEET_URL, worksheet=worksheet_name, data=df_upload)

# --- 全域資料庫初始化 (加入 reset_index 防止索引錯亂) ---
expected_itinerary_cols = ["天數", "時間", "目的地", "交通方式", "備註"]
expected_hotel_cols = ["飯店名稱", "訂房平台", "入住日", "退房日", "地址"] 
expected_flight_cols = ["航空公司", "航班號碼", "出發地", "抵達地", "起飛時間", "降落時間", "日期"] 
expected_expense_cols = ["消費日期", "付款方式", "項目", "金額", "幣別", "備註"]
expected_exchange_cols = ["日期", "換入幣別", "換出金額", "換出幣別", "獲得金額", "匯率"]

if "data_loaded" not in st.session_state:
    with st.spinner("☁️ 正在與 Google 表單同步資料..."):
        st.session_state.itinerary = load_data_from_gs("行程", expected_itinerary_cols).reset_index(drop=True)
        st.session_state.hotels = load_data_from_gs("住宿", expected_hotel_cols).reset_index(drop=True)
        st.session_state.flights = load_data_from_gs("航班", expected_flight_cols).reset_index(drop=True)
        st.session_state.expenses = load_data_from_gs("記帳", expected_expense_cols).reset_index(drop=True)
        st.session_state.exchanges = load_data_from_gs("換匯", expected_exchange_cols).reset_index(drop=True)
        st.session_state.data_loaded = True

# --- 機場與全域設定 ---
AIRPORT_DB = {
    "TAOYUAN": "台北桃園 (TPE)", "TPE": "台北桃園 (TPE)", "TSA": "台北松山 (TSA)",
    "KHH": "高雄 (KHH)", "BKK": "曼谷 (BKK)", "DMK": "曼谷廊曼 (DMK)",
    "NRT": "東京成田 (NRT)", "HND": "東京羽田 (HND)", "KIX": "大阪關西 (KIX)"
}

if "trip_start_date" not in st.session_state: st.session_state.trip_start_date = datetime.date.today()
if "trip_end_date" not in st.session_state: st.session_state.trip_end_date = datetime.date.today() + datetime.timedelta(days=12)

if "flights" in st.session_state and not st.session_state.flights.empty:
    try:
        f_dates = pd.to_datetime(st.session_state.flights["日期"], errors="coerce").dt.date.dropna()
        if not f_dates.empty:
            st.session_state.trip_start_date = f_dates.min()
            if f_dates.max() > f_dates.min():
                st.session_state.trip_end_date = f_dates.max()
    except: pass

def get_trip_days(): return max(1, (st.session_state.trip_end_date - st.session_state.trip_start_date).days + 1)
def get_date_of_day(day_idx): return st.session_state.trip_start_date + datetime.timedelta(days=int(day_idx)-1)
def get_day_label(day_idx):
    current_date = get_date_of_day(day_idx)
    weekdays = ["一", "二", "三", "四", "五", "六", "日"]
    return f"第 {day_idx} 天 ({current_date.strftime('%m/%d')} 星期{weekdays[current_date.weekday()]})"

# --- AI 解析引擎 ---
def extract_ticket_info(file):
    text = ""
    file_name_lower = file.name.lower()
    if file_name_lower.endswith('.pdf'):
        with pdfplumber.open(file) as pdf:
            for page in pdf.pages[:2]: 
                extracted = page.extract_text(layout=True)
                if not extracted: extracted = page.extract_text()
                text += (extracted or "") + "\n"
    else:
        try:
            img = ImageOps.exif_transpose(Image.open(file)).convert("RGB")
            max_size = 1500
            if max(img.size) > max_size: img = img.resize((int(img.width * (max_size/max(img.size))), int(img.height * (max_size/max(img.size)))), Image.Resampling.LANCZOS)
            text = pytesseract.image_to_string(img, lang='eng+chi_tra')
        except: pass

    info = {"airline": "未偵測", "flight_no": "未偵測", "dep_air": "未偵測", "arr_air": "未偵測", "dep_time": "00:00", "arr_time": "00:00", "flight_date": None}
    if not text: return info
    
    text_upper = text.upper() 
    
    dept_term = re.search(r"(TPE|TAOYUAN|KHH|KAOHSIUNG)[\s\S]{0,50}?(TERMINAL\s*\d)", text_upper)
    if dept_term:
        if "TPE" in dept_term.group(1) or "TAOYUAN" in dept_term.group(1): info["dep_air"] = f"桃園機場 (TPE) {dept_term.group(2)}"
        elif "KHH" in dept_term.group(1) or "KAOHSIUNG" in dept_term.group(1): info["dep_air"] = f"高雄機場 (KHH) {dept_term.group(2)}"

    arr_term = re.search(r"(DMK|DONMUEANG|BKK|SUVARNABHUMI)[\s\S]{0,50}?(TERMINAL\s*\d)", text_upper)
    if arr_term:
        if "DMK" in arr_term.group(1) or "DONMUEANG" in arr_term.group(1): info["arr_air"] = f"曼谷廊曼 (DMK) {arr_term.group(2)}"
        elif "BKK" in arr_term.group(1) or "SUVARNABHUMI" in arr_term.group(1): info["arr_air"] = f"曼谷蘇凡納布 (BKK) {arr_term.group(2)}"
            
    if "CHINA AIRLINES" in text_upper or "中華航空" in text: info["airline"] = "中華航空"
    elif "VIETJET" in text_upper: info["airline"] = "泰越捷"
    elif "LION" in text_upper: info["airline"] = "泰獅航"
    
    valid_flights = [f.replace("C1", "CI") for f in re.findall(r"\b([A-Z0-9]{2}\s?\d{2,4})\b", text_upper) if not f.startswith("20")]
    if valid_flights:
        pref = "CI" if "CHINA" in info["airline"].upper() else ("VZ" if "VIETJET" in info["airline"].upper() else "SL" if "LION" in info["airline"].upper() else "")
        matched = [f for f in valid_flights if f.startswith(pref)]
        info["flight_no"] = matched[0] if matched else valid_flights[0]

    times = re.findall(r"\b\d{2}:\d{2}\b", text)
    if len(times) >= 2: info["dep_time"], info["arr_time"] = times[0], times[1]

    parsed_dates = []
    for match in re.findall(r"(20[2-3]\d)[-/](0[1-9]|1[0-2])[-/](0[1-9]|[12]\d|3[01])", text_upper):
        try: parsed_dates.append(datetime.date(int(match[0]), int(match[1]), int(match[2])))
        except: pass
        
    month_map = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6, "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}
    for match in re.findall(r"(0?[1-9]|[12]\d|3[01])[-/]([A-Z]{3})[-/](20[2-3]\d)", text_upper):
        try:
            m_num = month_map.get(match[1])
            if m_num: parsed_dates.append(datetime.date(int(match[2]), m_num, int(match[0])))
        except: pass

    if parsed_dates: info["flight_date"] = max(parsed_dates)

    search_area = text_upper.replace("BANGKOK DONMUEANG", "DONMUEANG")
    found = []
    for key, val in AIRPORT_DB.items():
        for match in re.finditer(r'\b' + re.escape(key) + r'\b', search_area): found.append((match.start(), val))
    found.sort()
    cities = []
    for p, city in found:
        if not cities or cities[-1] != city: cities.append(city)
        
    if len(cities) >= 2: 
        if info["dep_air"] == "未偵測": info["dep_air"] = cities[0]
        if info["arr_air"] == "未偵測": info["arr_air"] = cities[1]
        
    return info, text

def extract_hotel_receipt(file):
    text = ""
    info = {"hotel_name": "", "platform": "", "in_date": st.session_state.trip_start_date, "out_date": st.session_state.trip_start_date + datetime.timedelta(days=1), "address": ""}
    file_name_lower = file.name.lower()
    if file_name_lower.endswith('.pdf'):
        with pdfplumber.open(file) as pdf:
            for page in pdf.pages[:2]:
                extracted = page.extract_text(layout=True)
                if not extracted: extracted = page.extract_text()
                text += (extracted or "") + "\n"
    elif file_name_lower.endswith(('.html', '.htm')):
        raw_html = html.unescape(file.getvalue().decode('utf-8', errors='ignore'))
        clean_text = re.sub(r'<[^>]+>', ' ', re.sub(r'<script.*?>.*?</script>', ' ', re.sub(r'<style.*?>.*?</style>', ' ', raw_html, flags=re.DOTALL | re.IGNORECASE), flags=re.DOTALL | re.IGNORECASE))
        text = re.sub(r'\s+', ' ', clean_text)
    else:
        try:
            img = ImageOps.exif_transpose(Image.open(file)).convert("RGB")
            max_size = 1500
            if max(img.size) > max_size: img = img.resize((int(img.width * (max_size/max(img.size))), int(img.height * (max_size/max(img.size)))), Image.Resampling.LANCZOS)
            text = pytesseract.image_to_string(img, lang='eng+tha+chi_tra')
        except: pass

    if not text: return info
    text_upper = text.upper()
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    if "AGODA" in text_upper: info["platform"] = "Agoda"
    elif "BOOKING" in text_upper: info["platform"] = "Booking.com"
    elif "EZTRAVEL" in text_upper or "易遊網" in text_upper: info["platform"] = "ezTravel 易遊網"

    found_dates = []
    for m in re.finditer(r"(20[2-3]\d)[-/](0?[1-9]|1[0-2])[-/](0?[1-9]|[12]\d|3[01])", text_upper):
        try: found_dates.append(datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except: pass
    if found_dates:
        all_dates = sorted(list(set(found_dates)))
        if len(all_dates) >= 2:
            info["in_date"], info["out_date"] = all_dates[-2], all_dates[-1]

    for line in lines:
        if not info["address"] and any(kw in line.upper() for kw in ["地址:", "ADDRESS:"]):
            info["address"] = re.split(r'(?:地址|ADDRESS)\s*[:：]?\s*', line, flags=re.IGNORECASE)[-1].strip()
        if not info["hotel_name"] and any(kw in line.upper() for kw in ["住宿名稱:", "PROPERTY:", "飯店名稱:"]):
            info["hotel_name"] = re.split(r'(?:住宿名稱|PROPERTY|飯店名稱)\s*[:：]?\s*', line, flags=re.IGNORECASE)[-1].strip()
    return info

def extract_receipt_info(image_file):
    try:
        img = ImageOps.exif_transpose(Image.open(image_file)).convert("RGB")
        max_size = 1500
        if max(img.size) > max_size: img = img.resize((int(img.width * (max_size/max(img.size))), int(img.height * (max_size/max(img.size)))), Image.Resampling.LANCZOS)
        text = pytesseract.image_to_string(img, lang='eng+tha+chi_tra')
        info = {"total_amount": 0.0, "currency": "THB"}
        if re.search(r'(TWD|NTD|台幣)', text, re.IGNORECASE): info["currency"] = "TWD"
            
        amounts = []
        for line in text.split('\n'):
            clean = line.replace("'", ".").replace(" ", "")
            nums = re.findall(r'\d{1,6}(?:\.\d{1,2})?', clean)
            if nums:
                try:
                    val = float(nums[-1].replace(',', ''))
                    if 1.0 < val < 500000.0: amounts.append(val)
                except: pass
        if amounts: info["total_amount"] = max(amounts)
        return info
    except: return None

# --- UI 介面設計 ---
tab1, tab2, tab3, tab4, tab5 = st.tabs(["🕒 航班", "📅 行程", "🏨 住宿", "💰 記帳", "📊 總覽"])

# === Tab 1: 機票 ===
with tab1:
    st.subheader("✈️ 航班管理與記錄")
    uploaded_file = st.file_uploader("點擊或拖入機票 PDF 或 手機截圖", type=["pdf", "jpg", "jpeg", "png", "heic", "heif"])
    
    if uploaded_file is not None:
        if "last_uploaded_filename" not in st.session_state or st.session_state.last_uploaded_filename != uploaded_file.name:
            st.session_state.last_uploaded_filename = uploaded_file.name
            st.session_state.flight_data = {"airline": "未偵測", "flight_no": "未偵測", "dep_air": "未偵測", "arr_air": "未偵測", "dep_time": "00:00", "arr_time": "00:00", "flight_date": datetime.date.today()}
            st.session_state.last_scanned_flight = None
            
    if "flight_data" not in st.session_state: st.session_state.flight_data = {"airline": "未偵測", "flight_no": "未偵測", "dep_air": "未偵測", "arr_air": "未偵測", "dep_time": "00:00", "arr_time": "00:00", "flight_date": datetime.date.today()}
    if "last_scanned_flight" not in st.session_state: st.session_state.last_scanned_flight = None
        
    if uploaded_file and st.session_state.last_scanned_flight != uploaded_file.name:
        with st.spinner('AI 正在精準解析航班資訊...'):
            data, _ = extract_ticket_info(uploaded_file)
            if data["flight_date"] is None: data["flight_date"] = datetime.date.today()
            st.session_state.flight_data = data
            st.session_state.last_scanned_flight = uploaded_file.name
        st.success("機票解析完成！請確認或修改下方資訊：")
        st.rerun()
        
    with st.container():
        col_air, col_fl = st.columns(2)
        t_airline = col_air.text_input("航空公司", value=st.session_state.flight_data["airline"])
        t_flight_no = col_fl.text_input("航班號碼", value=st.session_state.flight_data["flight_no"])
        dep = st.text_input("🛫 出發地點", value=st.session_state.flight_data["dep_air"])
        arr = st.text_input("🛬 抵達地點", value=st.session_state.flight_data["arr_air"])
        col_t1, col_t2 = st.columns(2)
        t_dep = col_t1.text_input("起飛時間", value=st.session_state.flight_data["dep_time"])
        t_arr = col_t2.text_input("降落時間", value=st.session_state.flight_data["arr_time"])

    st.divider()
    user_flight_date = st.date_input("這班飛機的日期是？", value=st.session_state.flight_data["flight_date"])
    flight_role = st.radio("此航班在旅程中的角色：", ["🛫 去程 (設為第 1 天)", "🛬 回程 (設為最後一天)", "🔄 中間行程"])
    custom_day_idx = 1
    if "中間" in flight_role: custom_day_idx = st.selectbox("選擇加入至", options=range(1, get_trip_days() + 1), format_func=get_day_label)

    if st.button("☁️ 儲存航班並同步至雲端", key="btn_save_flight"):
        target_day_idx = 1 if "去程" in flight_role else (get_trip_days() if "回程" in flight_role else custom_day_idx)
        new_entry = pd.DataFrame([{"天數": target_day_idx, "時間": t_dep, "目的地": dep, "交通方式": "✈️ 飛機", "備註": f"{t_airline} {t_flight_no} 飛往 {arr}"}])
        st.session_state.itinerary = pd.concat([st.session_state.itinerary, new_entry], ignore_index=True)
        save_data_to_gs("行程", st.session_state.itinerary)
        
        new_flight = pd.DataFrame([{"航空公司": t_airline, "航班號碼": t_flight_no, "出發地": dep, "抵達地": arr, "起飛時間": t_dep, "降落時間": t_arr, "日期": user_flight_date}])
        st.session_state.flights = pd.concat([st.session_state.flights, new_flight], ignore_index=True)
        save_data_to_gs("航班", st.session_state.flights)
        
        st.session_state.last_scanned_flight = None
        st.toast("航班已同步至 Google Sheets！", icon="✅")
        st.rerun()

    st.divider()
    st.markdown("### 🎫 雲端航班清單")
    if st.session_state.flights.empty: st.info("尚無航班紀錄。")
    else:
        for idx, row in st.session_state.flights.iterrows():
            st.markdown(f"<div class='booking-card'><div class='dest-text'>✈️ {row['航空公司']} {row['航班號碼']}</div><div class='detail-text'>📅 日期: {row['日期']} ｜ ⏰ 時間: {row['起飛時間']} - {row['降落時間']}</div><div class='detail-text'>📍 航線: {row['出發地']} ➔ {row['抵達地']}</div></div>", unsafe_allow_html=True)
            if st.button("🗑️ 刪除", key=f"del_flight_row_{idx}"):
                st.session_state.flights = st.session_state.flights.drop(idx).reset_index(drop=True)
                save_data_to_gs("航班", st.session_state.flights)
                st.rerun()

# === Tab 2: 行程 ===
with tab2:
    if not st.session_state.itinerary.empty:
        st.session_state.itinerary["天數"] = pd.to_numeric(st.session_state.itinerary["天數"], errors='coerce').fillna(0).astype(int)
        max_day = max(get_trip_days(), int(st.session_state.itinerary["天數"].max()))
    else:
        max_day = get_trip_days()

    if "selected_day_idx" not in st.session_state:
        st.session_state.selected_day_idx = 1
        
    if st.session_state.selected_day_idx > max_day:
        st.session_state.selected_day_idx = max_day

    col_prev, col_day, col_next = st.columns([1, 2, 1])
    with col_prev:
        if st.button("◀ 上一天", use_container_width=True, key="btn_prev_day"):
            if st.session_state.selected_day_idx > 1:
                st.session_state.selected_day_idx -= 1
                st.rerun()
    with col_day:
        st.markdown(f"<div style='text-align: center; font-size: 1.1rem; padding-top: 5px; color: #007bff;'><b>{get_day_label(st.session_state.selected_day_idx)}</b></div>", unsafe_allow_html=True)
    with col_next:
        if st.button("下一天 ▶", use_container_width=True, key="btn_next_day"):
            if st.session_state.selected_day_idx < max_day:
                st.session_state.selected_day_idx += 1
                st.rerun()

    selected_day_idx = st.session_state.selected_day_idx
    current_date = get_date_of_day(selected_day_idx)
    current_date_str = current_date.strftime("%Y-%m-%d")
    
    st.divider()
    
    if "flights" in st.session_state and not st.session_state.flights.empty:
        day_flights = st.session_state.flights[st.session_state.flights["日期"].astype(str).str.contains(current_date_str, na=False)]
        for _, flight in day_flights.iterrows():
            st.info(f"✈️ **今日航班**：{flight.get('航空公司', '')} {flight.get('航班號碼', '')} | {flight.get('起飛時間', '')} 從 {flight.get('出發地', '')} ➔ {flight.get('抵達地', '')}")

    if "hotels" in st.session_state and not st.session_state.hotels.empty:
        for _, hotel in st.session_state.hotels.iterrows():
            try:
                out_date_str = str(hotel.get('退房日', ''))
                if out_date_str.startswith(current_date_str):
                    st.warning(f"🛎️ **今日退房 (Check-out)**：{hotel.get('飯店名稱', '')} | 記得確認退房時間喔！")
            except: pass

    if not st.session_state.itinerary.empty:
        day_data = st.session_state.itinerary[st.session_state.itinerary["天數"] == selected_day_idx].copy()
        if not day_data.empty:
            day_data = day_data.sort_values(by="時間")
    else:
        day_data = pd.DataFrame()

    if day_data.empty: 
        st.info("⛱️ 這天還沒有安排行程喔！請從下方新增。")
    else:
        for idx, row in day_data.iterrows():
            st.markdown(f"<div class='itinerary-card'><div class='time-text'>{row['時間']}</div><div class='dest-text'>📍 {row['目的地']}</div><div class='detail-text'>{row['交通方式']} ｜ 📝 {row['備註']}</div></div>", unsafe_allow_html=True)
            if st.button("🗑️ 刪除", key=f"del_itinerary_row_{idx}"):
                st.session_state.itinerary = st.session_state.itinerary.drop(idx).reset_index(drop=True)
                save_data_to_gs("行程", st.session_state.itinerary)
                st.rerun()
                
    with st.expander(f"➕ 新增行程至此日", expanded=False):
        with st.form(key=f"form_add_itinerary_{selected_day_idx}"):
            col_time, col_dest = st.columns(2)
            t_time = col_time.time_input("設定時間", value=datetime.time(9, 0)) 
            t_dest = col_dest.text_input("目的地 (如: 淺草寺)")
            t_trans = st.selectbox("交通方式", ["🚶 步行", "🚇 地鐵 / 捷運", "🚌 公車", "🚕 計程車 / Grab", "🚗 自駕 / 包車", "✈️ 飛機"])
            t_note = st.text_input("備註 (如: 車程約15分)")
            if st.form_submit_button("☁️ 同步新增至雲端") and t_dest:
                new_item = pd.DataFrame([{"天數": selected_day_idx, "時間": t_time.strftime("%H:%M"), "目的地": t_dest, "交通方式": t_trans, "備註": t_note}])
                st.session_state.itinerary = pd.concat([st.session_state.itinerary, new_item], ignore_index=True)
                save_data_to_gs("行程", st.session_state.itinerary)
                st.rerun()

    st.divider()
    st.markdown("#### 🌙 當晚住宿")
    stay_found = False
    if "hotels" in st.session_state and not st.session_state.hotels.empty:
        for _, hotel in st.session_state.hotels.iterrows():
            try:
                in_date_str = str(hotel.get('入住日', ''))
                out_date_str = str(hotel.get('退房日', ''))
                if in_date_str and out_date_str:
                    in_date = pd.to_datetime(in_date_str).date()
                    out_date = pd.to_datetime(out_date_str).date()
                    if in_date <= current_date < out_date:
                        plat_str = f" | 📍 平台：{hotel.get('訂房平台', '')}" if hotel.get('訂房平台', '') else ""
                        st.markdown(f"<div class='hotel-card'>🏨 <b>{hotel.get('飯店名稱', '')}</b> {plat_str} <br><small>地址：{hotel.get('地址', '無')}</small></div>", unsafe_allow_html=True)
                        stay_found = True
            except: pass
    if not stay_found:
        st.write("這天晚上還沒有登記住宿喔！")

# === Tab 3: 住宿管理 ===
with tab3:
    st.subheader("🏨 住宿管理與紀錄")
    if "temp_hotel" not in st.session_state: st.session_state.temp_hotel = {"hotel_name": "", "platform": "", "in_date": st.session_state.trip_start_date, "out_date": st.session_state.trip_start_date + datetime.timedelta(days=1), "address": ""}
    if "last_scanned_hotel_file" not in st.session_state: st.session_state.last_scanned_hotel_file = None

    h_file = st.file_uploader("📎 上傳訂房憑證 (支援 PDF, HTML 或 手機截圖)", type=["pdf", "jpg", "jpeg", "png", "html", "htm", "heic", "heif"])
    if h_file and st.session_state.last_scanned_hotel_file != h_file.name:
        with st.spinner("AI 正在深度解析住宿憑證..."):
            st.session_state.temp_hotel.update(extract_hotel_receipt(h_file))
            st.session_state.last_scanned_hotel_file = h_file.name
            st.rerun() 
    
    with st.expander("📝 確認或手動新增住宿資訊", expanded=True):
        with st.form("hotel_form"):
            h_name = st.text_input("飯店名稱*", value=st.session_state.temp_hotel.get("hotel_name", ""))
            h_platform = st.text_input("訂房平台", value=st.session_state.temp_hotel.get("platform", ""), placeholder="如: Agoda, Booking.com")
            col_in, col_out = st.columns(2)
            try:
                h_in_val = datetime.datetime.strptime(str(st.session_state.temp_hotel.get("in_date", st.session_state.trip_start_date)), "%Y-%m-%d").date()
                h_out_val = datetime.datetime.strptime(str(st.session_state.temp_hotel.get("out_date", st.session_state.trip_start_date + datetime.timedelta(days=1))), "%Y-%m-%d").date()
            except:
                h_in_val = st.session_state.trip_start_date
                h_out_val = st.session_state.trip_start_date + datetime.timedelta(days=1)
                
            h_in = col_in.date_input("入住日期", value=h_in_val)
            h_out = col_out.date_input("退房日期", value=h_out_val)
            h_addr = st.text_input("飯店地址或備註", value=st.session_state.temp_hotel.get("address", ""))
            
            if st.form_submit_button("☁️ 儲存並同步至雲端"):
                if h_name:
                    if h_out <= h_in: st.error("⚠️ 退房日期必須晚於入住日期喔！")
                    else:
                        new_hotel = pd.DataFrame([{"飯店名稱": h_name, "訂房平台": h_platform, "入住日": h_in, "退房日": h_out, "地址": h_addr}])
                        st.session_state.hotels = pd.concat([st.session_state.hotels, new_hotel], ignore_index=True)
                        save_data_to_gs("住宿", st.session_state.hotels)
                        st.session_state.temp_hotel = {"hotel_name": "", "platform": "", "in_date": st.session_state.trip_start_date, "out_date": st.session_state.trip_start_date + datetime.timedelta(days=1), "address": ""}
                        st.session_state.last_scanned_hotel_file = None
                        st.success(f"已同步：{h_name}！")
                        st.rerun()
                else: st.error("請輸入飯店名稱！")
                    
    st.markdown("### 🛏️ 雲端住宿清單與編輯")
    if st.session_state.hotels.empty: st.info("尚無住宿紀錄。")
    else:
        st.markdown("<small>提示：您可以直接在下方表格內雙擊欄位來修改資料，甚至勾選左側核取方塊來刪除整列資料。完成後記得按下「💾 儲存修改」。</small>", unsafe_allow_html=True)
        edited_hotels = st.data_editor(st.session_state.hotels, column_order=["飯店名稱", "訂房平台", "入住日", "退房日", "地址"], num_rows="dynamic", use_container_width=True, key="hotel_editor")
        if st.button("💾 將住宿表格的修改同步至雲端", key="btn_sync_hotels"):
            st.session_state.hotels = edited_hotels
            save_data_to_gs("住宿", st.session_state.hotels)
            st.success("住宿資料已成功修改並同步至 Google 表單！")
            st.rerun()

# === Tab 4: 記帳 ===
with tab4:
    st.subheader("💵 雲端記帳助手")
    expense_date = st.date_input("📅 消費日期", value=datetime.date.today())
    if "current_receipt_name" not in st.session_state: st.session_state.current_receipt_name = None
    if "receipt_data" not in st.session_state: st.session_state.receipt_data = {"total_amount": 0.0, "currency": "THB"}
    
    receipt_file = st.file_uploader("📷 拍照或從圖庫選擇收據 (AI 自動辨識金額)", type=["jpg", "jpeg", "png", "heic", "heif"])
    if receipt_file:
        display_img = ImageOps.exif_transpose(Image.open(receipt_file)).convert("RGB")
        st.image(display_img, caption="目前收據", use_container_width=True)
        if st.session_state.current_receipt_name != receipt_file.name:
            with st.spinner('AI 正在尋找消費總額...'):
                extracted = extract_receipt_info(receipt_file)
                if extracted: st.session_state.receipt_data = extracted
                st.session_state.current_receipt_name = receipt_file.name
                
    rd = st.session_state.receipt_data
    with st.form("expense_form"):
        col_pay, col_cat = st.columns(2)
        e_pay = col_pay.selectbox("💳 付款方式", ["現金", "刷卡", "LINE Pay", "其他"])
        e_cat = col_cat.selectbox("🏷️ 項目", ["飲食", "交通", "購物", "娛樂", "住宿", "機票", "其他"])
        
        col_amt, col_cur = st.columns(2)
        e_amt = col_amt.number_input("💰 金額", value=rd.get("total_amount", 0.0), step=10.0)
        cur_list = ["THB (泰銖)", "TWD (台幣)", "USD (美金)", "JPY (日圓)"]
        default_cur_idx = 0 if "THB" in rd.get("currency", "THB") else 1
        e_cur = col_cur.selectbox("💵 幣別", cur_list, index=default_cur_idx)
        e_note = st.text_input("📝 備註 (如：午餐打拋豬、買伴手禮)")
        
        if st.form_submit_button("☁️ 儲存並同步至 Google 表單"):
            if e_amt > 0:
                new_expense = pd.DataFrame([{"消費日期": expense_date, "付款方式": e_pay, "項目": e_cat, "金額": e_amt, "幣別": e_cur.split(" ")[0], "備註": e_note}])
                st.session_state.expenses = pd.concat([st.session_state.expenses, new_expense], ignore_index=True)
                save_data_to_gs("記帳", st.session_state.expenses)
                st.toast("消費已同步！可至「總覽」查看。", icon="✅")
                st.session_state.current_receipt_name = None
                st.session_state.receipt_data = {"total_amount": 0.0, "currency": "THB"}
            else:
                st.error("請輸入大於 0 的金額喔！")

# === Tab 5: 帳目總覽 ===
with tab5:
    st.markdown("### 💱 雲端換匯小幫手")
    with st.expander("➕ 新增一筆換錢紀錄", expanded=False):
        with st.form("exchange_form"):
            col_ex1, col_ex2 = st.columns(2)
            ex_date = col_ex1.date_input("換匯日期", value=datetime.date.today())
            ex_from_cur = col_ex2.selectbox("我拿出的幣別", ["TWD (新台幣)", "USD (美金)"])
            col_ex3, col_ex4 = st.columns(2)
            ex_from_amt = col_ex3.number_input("拿出金額", min_value=0, step=1000)
            ex_to_amt = col_ex4.number_input("換到泰銖 (THB)", min_value=0, step=1000)
            
            if st.form_submit_button("☁️ 同步換匯紀錄"):
                if ex_from_amt > 0 and ex_to_amt > 0:
                    rate = ex_to_amt / ex_from_amt
                    new_ex = pd.DataFrame([{"日期": ex_date, "換入幣別": "THB", "換出金額": ex_from_amt, "換出幣別": ex_from_cur.split(" ")[0], "獲得金額": ex_to_amt, "匯率": round(rate, 4)}])
                    st.session_state.exchanges = pd.concat([st.session_state.exchanges, new_ex], ignore_index=True)
                    save_data_to_gs("換匯", st.session_state.exchanges)
                    st.success(f"已記錄！匯率約為 1 {ex_from_cur.split(' ')[0]} = {round(rate, 4)} THB")
                    st.rerun()
                else:
                    st.error("請輸入正確金額")
                    
    # 💡 [新增] 換匯記錄改為與記帳相同的互動式表格
    st.markdown("#### 🔄 雲端換匯清單與編輯")
    if st.session_state.exchanges.empty:
        st.info("尚無換匯紀錄。")
    else:
        st.markdown("<small>提示：雙擊下方表格來修改資料，或勾選最左側的核取方塊來刪除整列紀錄。完成後記得點擊「儲存換匯修改」。</small>", unsafe_allow_html=True)
        edited_exchanges = st.data_editor(st.session_state.exchanges, column_order=["日期", "換入幣別", "換出金額", "換出幣別", "獲得金額", "匯率"], num_rows="dynamic", use_container_width=True, key="exchange_editor")
        if st.button("💾 將換匯表格的修改同步至雲端", key="btn_sync_exchanges"):
            st.session_state.exchanges = edited_exchanges
            save_data_to_gs("換匯", st.session_state.exchanges)
            st.success("換匯資料已成功修改並同步至 Google 表單！")
            st.rerun()

    st.markdown("---")
    st.markdown("### 📊 花費雲端總覽")
    if st.session_state.expenses.empty:
        st.info("目前還沒有任何花費紀錄喔！快去「記帳」頁面新增吧。")
    else:
        st.session_state.expenses['金額'] = pd.to_numeric(st.session_state.expenses['金額'], errors='coerce').fillna(0)
        summary = st.session_state.expenses.groupby("幣別")["金額"].sum().reset_index()
        cols = st.columns(len(summary))
        for i, row in summary.iterrows():
            cols[i].metric(label=f"總花費 ({row['幣別']})", value=f"{row['金額']:,.0f}")
            
        st.markdown("<br>", unsafe_allow_html=True)
        edited_expenses = st.data_editor(st.session_state.expenses, column_order=["消費日期", "付款方式", "項目", "金額", "幣別", "備註"], num_rows="dynamic", use_container_width=True, key="expense_editor")
        if st.button("💾 將記帳表格的修改同步至雲端", key="btn_sync_expenses"):
            st.session_state.expenses = edited_expenses
            save_data_to_gs("記帳", st.session_state.expenses)
            st.success("總覽表修改已成功同步至 Google 表單！")
            st.rerun()