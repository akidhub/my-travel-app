# --- 版本：v35 (iPhone 記帳特化、新增帳目總覽、換匯紀錄與 Google Sheet 匯出版) ---

import streamlit as st
import pandas as pd
import pdfplumber
import re
import pytesseract
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener
import datetime
import html

# --- 註冊 HEIC 解碼器 ---
register_heif_opener()

# --- 網頁配置 ---
st.set_page_config(page_title="旅遊隨身夥伴", layout="centered", initial_sidebar_state="collapsed")

# 🚀 自定義 CSS 
st.markdown("""
    <style>
    .main { background-color: transparent; }
    .stButton>button { width: 100%; border-radius: 10px; height: 3em; background-color: #007bff; color: white; }
    .stDownloadButton>button { width: 100%; border-radius: 10px; height: 3em; background-color: #28a745; color: white; border: none; font-weight: bold; }
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

AIRPORT_DB = {
    "TAOYUAN": "台北桃園 (TPE)", "TAIPEI": "台北桃園 (TPE)", "TPE": "台北桃園 (TPE)",
    "TSA": "台北松山 (TSA)", "SONGSHAN": "台北松山 (TSA)",
    "KAOHSIUNG": "高雄 (KHH)", "KHH": "高雄 (KHH)",
    "BANGKOK": "曼谷 (BKK)", "SUVARNABHUMI": "曼谷 (BKK)", "BKK": "曼谷 (BKK)",
    "DONMUEANG": "曼谷廊曼 (DMK)", "DMK": "曼谷廊曼 (DMK)",
    "TOKYO": "東京 (NRT/HND)", "NARITA": "東京成田 (NRT)", "NRT": "東京成田 (NRT)",
    "HANEDA": "東京羽田 (HND)", "HND": "東京羽田 (HND)",
    "OSAKA": "大阪關西 (KIX)", "KANSAI": "大阪關西 (KIX)", "KIX": "大阪關西 (KIX)"
}

if "debug_logs" not in st.session_state: st.session_state.debug_logs = []
def add_log(msg): st.session_state.debug_logs.append(msg)

# --- 全域旅程設定 ---
if "trip_start_date" not in st.session_state: st.session_state.trip_start_date = datetime.date.today()
if "trip_end_date" not in st.session_state: st.session_state.trip_end_date = datetime.date.today() + datetime.timedelta(days=12)

def get_trip_days(): return max(1, (st.session_state.trip_end_date - st.session_state.trip_start_date).days + 1)
def get_date_of_day(day_idx): return st.session_state.trip_start_date + datetime.timedelta(days=day_idx-1)
def get_day_label(day_idx):
    current_date = get_date_of_day(day_idx)
    weekdays = ["一", "二", "三", "四", "五", "六", "日"]
    return f"第 {day_idx} 天 ({current_date.strftime('%m/%d')} 星期{weekdays[current_date.weekday()]})"

# --- 資料庫初始化 ---
if "itinerary" not in st.session_state: st.session_state.itinerary = pd.DataFrame(columns=["天數", "時間", "目的地", "交通方式", "備註"])
if "hotels" not in st.session_state: st.session_state.hotels = pd.DataFrame(columns=["飯店名稱", "訂房平台", "入住日", "退房日", "地址", "檔案名稱", "檔案資料"])
if "flights" not in st.session_state: st.session_state.flights = pd.DataFrame(columns=["航空公司", "航班號碼", "出發地", "抵達地", "起飛時間", "降落時間", "日期", "檔案名稱", "檔案資料"])

# 🚀 升級版記帳資料庫
expected_expense_cols = ["消費日期", "付款方式", "項目", "金額", "幣別", "備註"]
if "expenses" not in st.session_state: 
    st.session_state.expenses = pd.DataFrame(columns=expected_expense_cols)
else:
    # 幫舊資料補上新欄位以防報錯
    for col in expected_expense_cols:
        if col not in st.session_state.expenses.columns: st.session_state.expenses[col] = ""

# 🚀 新增換匯資料庫
if "exchanges" not in st.session_state: 
    st.session_state.exchanges = pd.DataFrame(columns=["日期", "換入幣別", "換出金額", "換出幣別", "獲得金額", "匯率"])

# --- 機票與住宿解析引擎 (保留先前版本) ---
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
            if max(img.size) > max_size:
                ratio = max_size / max(img.size)
                img = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.Resampling.LANCZOS)
            text = pytesseract.image_to_string(img, lang='eng+chi_tra')
        except: pass

    info = {"airline": "未偵測", "flight_no": "未偵測", "dep_air": "未偵測", "arr_air": "未偵測", "dep_time": "00:00", "arr_time": "00:00", "flight_date": None}
    if not text: return info
    text_upper = text.upper()
    if "CHINA AIRLINES" in text_upper or "中華航空" in text: info["airline"] = "中華航空"
    elif "VIETJET" in text_upper: info["airline"] = "泰越捷"
    elif "LION" in text_upper: info["airline"] = "泰獅航"
    
    flight_cands = re.findall(r"\b([A-Z0-9]{2}\s?\d{2,4})\b", text_upper)
    valid_flights = [f.replace("C1", "CI") for f in flight_cands if not f.startswith("20")]
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
    month_map = {"JAN":1, "FEB":2, "MAR":3, "APR":4, "MAY":5, "JUN":6, "JUL":7, "AUG":8, "SEP":9, "OCT":10, "NOV":11, "DEC":12}
    for match in re.findall(r"(0[1-9]|[12]\d|3[01])\s*[-/]?\s*(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\s*[-/]?\s*(20[2-3]\d)", text_upper):
        try: parsed_dates.append(datetime.date(int(match[2]), month_map[match[1]], int(match[0])))
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
    if len(cities) >= 2: info["dep_air"], info["arr_air"] = cities[0], cities[1]
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
        raw_html = file.getvalue().decode('utf-8', errors='ignore')
        raw_html = html.unescape(raw_html)
        clean_text = re.sub(r'<style.*?>.*?</style>', ' ', raw_html, flags=re.DOTALL | re.IGNORECASE)
        clean_text = re.sub(r'<script.*?>.*?</script>', ' ', clean_text, flags=re.DOTALL | re.IGNORECASE)
        clean_text = re.sub(r'<[^>]+>', ' ', clean_text)
        text = re.sub(r'\s+', ' ', clean_text)
    else:
        try:
            img = ImageOps.exif_transpose(Image.open(file)).convert("RGB")
            max_size = 1500
            if max(img.size) > max_size:
                ratio = max_size / max(img.size)
                img = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.Resampling.LANCZOS)
            text = pytesseract.image_to_string(img, lang='eng+tha+chi_tra')
        except: pass

    if not text: return info
    text_upper = text.upper()
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    if "AGODA" in text_upper: info["platform"] = "Agoda"
    elif "BOOKING.COM" in text_upper or "BOOKING" in text_upper: info["platform"] = "Booking.com"
    elif "AIRBNB" in text_upper: info["platform"] = "Airbnb"
    elif "TRIP.COM" in text_upper: info["platform"] = "Trip.com"
    elif "EXPEDIA" in text_upper: info["platform"] = "Expedia"
    elif "易遊網" in text_upper or "EZTRAVEL" in text_upper: info["platform"] = "ezTravel 易遊網"

    dp_patterns = [
        r"(20[2-3]\d)\s*[-/.]\s*(0?[1-9]|1[0-2])\s*[-/.]\s*(0?[1-9]|[12]\d|3[01])",
        r"(20[2-3]\d)\s*年\s*(0?[1-9]|1[0-2])\s*月\s*(0?[1-9]|[12]\d|3[01])\s*日",
        r"(0?[1-9]|[12]\d|3[01])\s*[-/]?\s*(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\s*[-/]?\s*(20[2-3]\d)",
        r"(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\s+(0?[1-9]|[12]\d|3[01])\s*,\s*(20[2-3]\d)"
    ]
    month_map = {"JAN":1, "FEB":2, "MAR":3, "APR":4, "MAY":5, "JUN":6, "JUL":7, "AUG":8, "SEP":9, "OCT":10, "NOV":11, "DEC":12}
    found_dates = []
    
    def check_date_role(start_idx):
        prefix = text_upper[max(0, start_idx-60) : start_idx]
        is_in = any(kw in prefix for kw in ["入住日期", "入住", "ARRIVAL", "CHECK IN", "CHECK-IN", "IN-DATE"])
        is_out = any(kw in prefix for kw in ["退房日期", "退房", "DEPARTURE", "CHECK OUT", "CHECK-OUT", "OUT-DATE"])
        return is_in, is_out

    for p_idx, dp in enumerate(dp_patterns):
        for m in re.finditer(dp, text_upper):
            try:
                if p_idx in [0, 1]: d = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                elif p_idx == 2: d = datetime.date(int(m.group(3)), month_map[m.group(2)], int(m.group(1)))
                elif p_idx == 3: d = datetime.date(int(m.group(3)), month_map[m.group(1)], int(m.group(2)))
                is_in, is_out = check_date_role(m.start())
                found_dates.append((d, is_in, is_out))
            except: pass

    in_date_cand = [d for d, i, o in found_dates if i]
    out_date_cand = [d for d, i, o in found_dates if o]
    if in_date_cand and out_date_cand:
        info["in_date"] = min(in_date_cand)
        info["out_date"] = max(out_date_cand)
    elif found_dates:
        all_dates = sorted(list(set([d for d, i, o in found_dates])))
        if len(all_dates) >= 2:
            info["in_date"] = all_dates[-2]
            info["out_date"] = all_dates[-1]

    for line in lines:
        upper_line = line.upper()
        if not info["address"]:
            if any(kw in upper_line for kw in ["地址:", "ADDRESS:", "地址：", "ADDRESS "]):
                parts = re.split(r'(?:地址|ADDRESS)\s*[:：]?\s*', line, flags=re.IGNORECASE)
                val = parts[-1].strip()
                if len(val) > 5: info["address"] = val
        if not info["hotel_name"]:
            if any(kw in upper_line for kw in ["住宿名稱:", "PROPERTY:", "HOTEL NAME:", "飯店名稱:", "飯店名稱 "]):
                parts = re.split(r'(?:住宿名稱|PROPERTY|HOTEL NAME|飯店名稱)\s*[:：]?\s*', line, flags=re.IGNORECASE)
                val = parts[-1].strip()
                if len(val) > 2: info["hotel_name"] = val

    if info["platform"] == "Agoda" and (not info["address"] or not info["hotel_name"]):
        for i, line in enumerate(lines):
            if re.match(r'^\+?\+?\d{8,}', line.replace(" ", "")):
                if not info["address"] and i >= 1:
                    info["address"] = lines[i-1]
                    if i >= 2 and not any(kw in lines[i-2].upper() for kw in ["PROPERTY", "NAME", "名稱", "TAIWAN", "CLIENT"]):
                        info["address"] = lines[i-2] + " " + info["address"]
                if not info["hotel_name"] and i >= 3:
                     cands = [lines[i-2], lines[i-3]] if i>=3 else [lines[i-2]]
                     info["hotel_name"] = max(cands, key=len)
                break

    if info["platform"] == "ezTravel 易遊網" or "易遊網" in text:
         if not info["hotel_name"]:
             m_h = re.search(r'飯店名稱\s*([^\n\s]+.*?)(?=飯店地址|入住日期|退房日期|$)', text)
             if m_h: info["hotel_name"] = m_h.group(1).strip()
         if not info["address"]:
             m_a = re.search(r'飯店地址\s*([^\n\s]+.*?)(?=電話|入住日期|退房日期|$)', text)
             if m_a: info["address"] = m_a.group(1).strip()
    return info

def extract_receipt_info(image_file):
    try:
        img = ImageOps.exif_transpose(Image.open(image_file)).convert("RGB")
        max_size = 1500
        if max(img.size) > max_size:
            ratio = max_size / max(img.size)
            img = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.Resampling.LANCZOS)
        text = pytesseract.image_to_string(img, lang='eng+tha+chi_tra')
        info = {"total_amount": 0.0, "currency": "THB", "raw_text": text}
        if re.search(r'(TWD|NTD|NT\$|台幣)', text, re.IGNORECASE): info["currency"] = "TWD"
        elif re.search(r'(JPY|¥)', text, re.IGNORECASE): info["currency"] = "JPY"
        elif re.search(r'(USD|\$)', text, re.IGNORECASE): info["currency"] = "USD"
            
        lines = text.split('\n')
        amounts = []
        keywords = ["TOTAL", "AMOUNT", "NET", "ยอดรวม", "รวมเงิน", "สุทธิ", "總計", "合計"]
        exclude = ["point", "คะแนน", "member", "สมาชิก", "change", "เงินทอน", "cash", "tel", "โทร", "phone", "vat", "tax", "統編"]

        for line in lines:
            clean = line.replace("'", ".").replace(" ", "")
            nums = re.findall(r'\d{1,6}(?:\.\d{1,2})?', clean)
            if nums and any(kw.lower() in line.lower() for kw in keywords):
                try:
                    val = float(nums[-1].replace(',', ''))
                    if 1.0 < val < 500000.0:
                        info["total_amount"] = val
                        return info
                except: pass

        for line in lines:
            if any(ex in line.lower() for ex in exclude): continue
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
tab1, tab2, tab3, tab4, tab5 = st.tabs(["🕒 航班", "📅 行程", "🏨 住宿", "💰 記帳", "📊 帳目總覽"])

# === Tab 1: 機票 ===
with tab1:
    st.subheader("✈️ 航班管理與記錄")
    uploaded_file = st.file_uploader("點擊或拖入機票 PDF 或 手機截圖", type=["pdf", "jpg", "jpeg", "png", "heic", "heif"])
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
        st.markdown("##### 📝 確認與修改航班資訊")
        col_air, col_fl = st.columns(2)
        t_airline = col_air.text_input("航空公司", value=st.session_state.flight_data["airline"])
        t_flight_no = col_fl.text_input("航班號碼", value=st.session_state.flight_data["flight_no"])
        dep = st.text_input("🛫 出發地點", value=st.session_state.flight_data["dep_air"])
        arr = st.text_input("🛬 抵達地點", value=st.session_state.flight_data["arr_air"])
        col_t1, col_t2 = st.columns(2)
        t_dep = col_t1.text_input("起飛時間", value=st.session_state.flight_data["dep_time"])
        t_arr = col_t2.text_input("降落時間", value=st.session_state.flight_data["arr_time"])

    st.divider()
    st.markdown("### 🗓️ 航班日期與行程設定")
    user_flight_date = st.date_input("這班飛機的日期是？", value=st.session_state.flight_data["flight_date"])
    flight_role = st.radio("此航班在旅程中的角色：", ["🛫 這是去程 (設為第 1 天)", "🛬 這是回程 (設為最後一天)", "🔄 這是中間行程"])
    custom_day_idx = 1
    if "中間" in flight_role: custom_day_idx = st.selectbox("選擇加入至", options=range(1, get_trip_days() + 1), format_func=get_day_label)

    if st.button("✨ 儲存航班並加入行程"):
        if "去程" in flight_role:
            st.session_state.trip_start_date = user_flight_date
            if st.session_state.trip_end_date < st.session_state.trip_start_date: st.session_state.trip_end_date = st.session_state.trip_start_date
            target_day_idx = 1
        elif "回程" in flight_role:
            st.session_state.trip_end_date = user_flight_date
            if st.session_state.trip_start_date > st.session_state.trip_end_date: st.session_state.trip_start_date = st.session_state.trip_end_date
            target_day_idx = get_trip_days()
        else: target_day_idx = custom_day_idx

        new_entry = pd.DataFrame([{"天數": target_day_idx, "時間": t_dep, "目的地": dep, "交通方式": "✈️ 飛機", "備註": f"搭乘 {t_airline} {t_flight_no} 飛往 {arr}"}])
        st.session_state.itinerary = pd.concat([st.session_state.itinerary, new_entry], ignore_index=True)
        
        file_name = uploaded_file.name if uploaded_file else None
        file_data = uploaded_file.getvalue() if uploaded_file else None
        new_flight = pd.DataFrame([{"航空公司": t_airline, "航班號碼": t_flight_no, "出發地": dep, "抵達地": arr, "起飛時間": t_dep, "降落時間": t_arr, "日期": user_flight_date, "檔案名稱": file_name, "檔案資料": file_data}])
        st.session_state.flights = pd.concat([st.session_state.flights, new_flight], ignore_index=True)
        st.session_state.last_scanned_flight = None
        st.toast("航班已成功加入並儲存憑證！", icon="✅")

    st.divider()
    st.markdown("### 🎫 已儲存航班清單")
    if st.session_state.flights.empty: st.info("尚無航班紀錄。")
    else:
        for idx, row in st.session_state.flights.iterrows():
            st.markdown(f"""
            <div class="booking-card">
                <div class="dest-text">✈️ {row['航空公司']} {row['航班號碼']}</div>
                <div class="detail-text">📅 日期: {row['日期']} ｜ ⏰ 時間: {row['起飛時間']} - {row['降落時間']}</div>
                <div class="detail-text">📍 航線: {row['出發地']} ➔ {row['抵達地']}</div>
            </div>
            """, unsafe_allow_html=True)
            btn_col1, btn_col2 = st.columns([1, 2])
            with btn_col1:
                if st.button("🗑️ 刪除", key=f"del_f_{idx}"):
                    st.session_state.flights = st.session_state.flights.drop(idx).reset_index(drop=True)
                    st.rerun()
            with btn_col2:
                if pd.notna(row['檔案名稱']) and row['檔案名稱']:
                    st.download_button(label=f"📄 下載憑證 ({row['檔案名稱'][:10]}...)", data=row['檔案資料'], file_name=row['檔案名稱'], key=f"dl_f_{idx}")

# === Tab 2: 行程 ===
with tab2:
    selected_day_idx = st.selectbox("📅 請選擇要檢視的天數", options=range(1, get_trip_days() + 1), format_func=get_day_label)
    current_date = get_date_of_day(selected_day_idx)
    st.markdown(f"### {get_day_label(selected_day_idx)} 行程")
    day_data = st.session_state.itinerary[st.session_state.itinerary["天數"] == selected_day_idx].sort_values(by="時間")
    if day_data.empty: st.info("⛱️ 這天還沒有安排行程喔！請從下方新增。")
    else:
        for idx, row in day_data.iterrows():
            st.markdown(f"<div class='itinerary-card'><div class='time-text'>{row['時間']}</div><div class='dest-text'>📍 {row['目的地']}</div><div class='detail-text'>{row['交通方式']} ｜ 📝 {row['備註']}</div></div>", unsafe_allow_html=True)
            if st.button("🗑️ 刪除", key=f"del_{idx}"):
                st.session_state.itinerary = st.session_state.itinerary.drop(idx).reset_index(drop=True)
                st.rerun()
                
    st.markdown("<br>", unsafe_allow_html=True)
    today_hotels = st.session_state.hotels[(st.session_state.hotels["入住日"] <= current_date) & (st.session_state.hotels["退房日"] > current_date)]
    if not today_hotels.empty:
        st.markdown("#### 🌙 今晚住宿")
        for _, hotel in today_hotels.iterrows():
            plat_badge = f"<span class='platform-badge'>{hotel['訂房平台']}</span>" if hotel['訂房平台'] else ""
            st.markdown(f"<div class='hotel-card'><div class='dest-text'>🏨 {hotel['飯店名稱']} {plat_badge}</div><div class='detail-text'>📍 地址：{hotel['地址']}</div><div class='detail-text'>📅 期間：{hotel['入住日'].strftime('%m/%d')} ~ {hotel['退房日'].strftime('%m/%d')}</div></div>", unsafe_allow_html=True)

    st.divider()
    with st.expander(f"➕ 新增行程至此日", expanded=False):
        with st.form(key=f"form_{selected_day_idx}"):
            col_time, col_dest = st.columns(2)
            t_time = col_time.time_input("設定時間", value=datetime.time(9, 0)) 
            t_dest = col_dest.text_input("目的地 (如: 淺草寺)")
            t_trans = st.selectbox("交通方式", ["🚶 步行", "🚇 地鐵 / 捷運", "🚌 公車", "🚕 計程車 / Grab", "🚗 自駕 / 包車", "✈️ 飛機"])
            t_note = st.text_input("備註 (如: 車程約15分)")
            if st.form_submit_button("✅ 確認新增") and t_dest:
                new_item = pd.DataFrame([{"天數": selected_day_idx, "時間": t_time.strftime("%H:%M"), "目的地": t_dest, "交通方式": t_trans, "備註": t_note}])
                st.session_state.itinerary = pd.concat([st.session_state.itinerary, new_item], ignore_index=True)
                st.rerun()

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
    
    with st.expander("📝 確認或手動輸入住宿資訊", expanded=True):
        with st.form("hotel_form"):
            h_name = st.text_input("飯店名稱*", value=st.session_state.temp_hotel.get("hotel_name", ""))
            h_platform = st.text_input("訂房平台", value=st.session_state.temp_hotel.get("platform", ""), placeholder="如: Agoda, Booking.com")
            col_in, col_out = st.columns(2)
            h_in = col_in.date_input("入住日期", value=st.session_state.temp_hotel.get("in_date", st.session_state.trip_start_date))
            h_out = col_out.date_input("退房日期", value=st.session_state.temp_hotel.get("out_date", st.session_state.trip_start_date + datetime.timedelta(days=1)))
            h_addr = st.text_input("飯店地址或備註", value=st.session_state.temp_hotel.get("address", ""))
            
            if st.form_submit_button("💾 儲存飯店並綁定憑證"):
                if h_name:
                    if h_out <= h_in: st.error("⚠️ 退房日期必須晚於入住日期喔！")
                    else:
                        file_name = h_file.name if h_file else None
                        file_data = h_file.getvalue() if h_file else None
                        new_hotel = pd.DataFrame([{"飯店名稱": h_name, "訂房平台": h_platform, "入住日": h_in, "退房日": h_out, "地址": h_addr, "檔案名稱": file_name, "檔案資料": file_data}])
                        st.session_state.hotels = pd.concat([st.session_state.hotels, new_hotel], ignore_index=True)
                        st.session_state.temp_hotel = {"hotel_name": "", "platform": "", "in_date": st.session_state.trip_start_date, "out_date": st.session_state.trip_start_date + datetime.timedelta(days=1), "address": ""}
                        st.session_state.last_scanned_hotel_file = None
                        st.success(f"已儲存：{h_name}！")
                        st.rerun()
                else: st.error("請輸入飯店名稱！")
                    
    st.markdown("### 🛏️ 已預訂飯店清單")
    if st.session_state.hotels.empty: st.info("尚無住宿紀錄。")
    else:
        for idx, row in st.session_state.hotels.iterrows():
            plat_badge = f"<span class='platform-badge'>{row['訂房平台']}</span>" if pd.notna(row['訂房平台']) and row['訂房平台'] else ""
            st.markdown(f"<div class='booking-card'><div class='dest-text'>🏨 {row['飯店名稱']} {plat_badge}</div><div class='detail-text'>📅 入住: {row['入住日']} ｜ 退房: {row['退房日']}</div><div class='detail-text'>📍 {row['地址']}</div></div>", unsafe_allow_html=True)
            btn_col1, btn_col2 = st.columns([1, 2])
            with btn_col1:
                if st.button("🗑️ 刪除", key=f"del_h_{idx}"):
                    st.session_state.hotels = st.session_state.hotels.drop(idx).reset_index(drop=True)
                    st.rerun()
            with btn_col2:
                if pd.notna(row['檔案名稱']) and row['檔案名稱']:
                    st.download_button(label=f"📄 下載憑證 ({row['檔案名稱'][:10]}...)", data=row['檔案資料'], file_name=row['檔案名稱'], key=f"dl_h_{idx}")

# === Tab 4: 記帳 (🚀 iPhone 特化介面) ===
with tab4:
    st.subheader("💵 隨身記帳助手")
    
    # 頂部：日期選擇器 (預設為今天，可手動更改)
    expense_date = st.date_input("📅 消費日期", value=datetime.date.today())
    
    if "current_receipt_name" not in st.session_state: st.session_state.current_receipt_name = None
    if "receipt_data" not in st.session_state: st.session_state.receipt_data = {"total_amount": 0.0, "currency": "THB"}
    
    # 手機友善的上傳器 (在 iOS 會自動彈出相機與圖庫選項)
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
    
    # 📱 黃金兩欄式排版 (適合 iPhone 直式觀看)
    with st.form("expense_form"):
        col_pay, col_cat = st.columns(2)
        e_pay = col_pay.selectbox("💳 付款方式", ["現金", "刷卡", "LINE Pay", "其他"])
        e_cat = col_cat.selectbox("🏷️ 項目", ["飲食", "交通", "購物", "娛樂", "住宿", "機票", "其他"])
        
        col_amt, col_cur = st.columns(2)
        e_amt = col_amt.number_input("💰 金額", value=rd.get("total_amount", 0.0), step=10.0)
        
        # 設定幣別預設值
        cur_list = ["THB (泰銖)", "TWD (台幣)", "USD (美金)", "JPY (日圓)"]
        default_cur_idx = 0
        if "TWD" in rd.get("currency", ""): default_cur_idx = 1
        e_cur = col_cur.selectbox("💵 幣別", cur_list, index=default_cur_idx)
        
        e_note = st.text_input("📝 備註 (如：午餐打拋豬、買伴手禮)")
        
        if st.form_submit_button("💾 儲存這筆消費"):
            if e_amt > 0:
                new_expense = pd.DataFrame([{
                    "消費日期": expense_date, 
                    "付款方式": e_pay, 
                    "項目": e_cat, 
                    "金額": e_amt, 
                    "幣別": e_cur.split(" ")[0], # 只存 THB/TWD 等代碼
                    "備註": e_note
                }])
                st.session_state.expenses = pd.concat([st.session_state.expenses, new_expense], ignore_index=True)
                st.toast("消費已記錄！可至「帳目總覽」查看。", icon="✅")
                # 清空暫存收據
                st.session_state.current_receipt_name = None
                st.session_state.receipt_data = {"total_amount": 0.0, "currency": "THB"}
            else:
                st.error("請輸入大於 0 的金額喔！")

# === Tab 5: 帳目總覽 (🚀 全新開發) ===
with tab5:
    # 📥 最上方的匯出按鈕 (轉為帶有 BOM 的 CSV 以完美支援 Google Sheet)
    csv_data = st.session_state.expenses.to_csv(index=False).encode('utf-8-sig')
    st.download_button(
        label="📥 匯出所有花費至 Google Sheet (CSV)",
        data=csv_data,
        file_name=f"travel_expenses_{datetime.date.today()}.csv",
        mime='text/csv'
    )
    
    st.markdown("---")
    
    # 💱 換匯紀錄區塊 (設計於此，方便記帳時對照)
    st.subheader("💱 換匯小幫手")
    with st.expander("➕ 新增一筆換錢紀錄", expanded=False):
        with st.form("exchange_form"):
            col_ex1, col_ex2 = st.columns(2)
            ex_date = col_ex1.date_input("換匯日期", value=datetime.date.today())
            ex_from_cur = col_ex2.selectbox("我拿出的幣別", ["TWD (新台幣)", "USD (美金)"])
            
            col_ex3, col_ex4 = st.columns(2)
            ex_from_amt = col_ex3.number_input("拿出金額", min_value=0, step=1000)
            ex_to_amt = col_ex4.number_input("換到泰銖 (THB)", min_value=0, step=1000)
            
            if st.form_submit_button("💾 儲存換匯紀錄"):
                if ex_from_amt > 0 and ex_to_amt > 0:
                    rate = ex_to_amt / ex_from_amt
                    new_ex = pd.DataFrame([{
                        "日期": ex_date, 
                        "換入幣別": "THB", 
                        "換出金額": ex_from_amt, 
                        "換出幣別": ex_from_cur.split(" ")[0],
                        "獲得金額": ex_to_amt, 
                        "匯率": round(rate, 4)
                    }])
                    st.session_state.exchanges = pd.concat([st.session_state.exchanges, new_ex], ignore_index=True)
                    st.success(f"已記錄！匯率約為 1 {ex_from_cur.split(' ')[0]} = {round(rate, 4)} THB")
                    st.rerun()
                else:
                    st.error("請輸入正確金額")
                    
    if not st.session_state.exchanges.empty:
        for idx, row in st.session_state.exchanges.iterrows():
            st.markdown(f"""
            <div class="exchange-card">
                <strong>{row['日期']} 換錢紀錄</strong><br>
                付出 {row['換出金額']} {row['換出幣別']} ➔ 得到 <b>{row['獲得金額']} THB</b> <br>
                <small>📝 匯率: {row['匯率']}</small>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("---")
    
    # 📊 總覽統計表
    st.subheader("📊 花費總覽與明細")
    if st.session_state.expenses.empty:
        st.info("目前還沒有任何花費紀錄喔！快去「記帳」頁面新增吧。")
    else:
        # 簡單分類統計 (計算各幣別總和)
        summary = st.session_state.expenses.groupby("幣別")["金額"].sum().reset_index()
        cols = st.columns(len(summary))
        for i, row in summary.iterrows():
            cols[i].metric(label=f"總花費 ({row['幣別']})", value=f"{row['金額']:,.0f}")
            
        st.markdown("<br>", unsafe_allow_html=True)
        # 顯示可編輯的 Data Editor，順序依據你要求的完美格式
        st.data_editor(
            st.session_state.expenses, 
            column_order=["消費日期", "付款方式", "項目", "金額", "幣別", "備註"],
            num_rows="dynamic", 
            use_container_width=True
        )