import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime
import pytz
import plotly.express as px
import io
import gspread
import time
import requests
import re
from google.oauth2.service_account import Credentials
from fugle_marketdata import RestClient

# --- 1. 網頁全域設定 (必須放在最上方) ---
st.set_page_config(page_title="台股個股/ETF查詢 Ez開發", page_icon="🔍", layout="wide")
tw_tz = pytz.timezone('Asia/Taipei')

# --- 0. 雲端資料庫連線與帳號邏輯 ---
@st.cache_resource
def init_connection():
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds_dict = st.secrets["gcp_service_account"].to_dict()
    
    if "private_key" in creds_dict:
        pk = creds_dict["private_key"]
        pk = pk.replace("\\n", "\n").replace('"', '')
        creds_dict["private_key"] = pk
    
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    client = gspread.authorize(creds)
    return client

try:
    conn = init_connection()
    sh = conn.open("streamlit_db")
    
    try:
        user_sheet = sh.worksheet("users")
    except:
        user_sheet = sh.add_worksheet(title="users", rows="100", cols="2")
        user_sheet.append_row(["username", "password"])
        user_sheet.append_row(["admin", "8888"])
    
    try:
        portfolio_sheet = sh.worksheet("portfolios")
    except:
        portfolio_sheet = sh.add_worksheet(title="portfolios", rows="1000", cols="2")
        portfolio_sheet.append_row(["username", "data_json"])
        
except Exception as e:
    st.error(f"❌ 雲端資料庫連線失敗：{e}")
    st.stop()

def get_cloud_users():
    records = user_sheet.get_all_records()
    return {str(row['username']).strip(): str(row['password']).strip() for row in records}

def load_portfolio_from_cloud(username):
    try:
        cell = portfolio_sheet.find(username)
        if cell:
            json_data = portfolio_sheet.cell(cell.row, 2).value
            return pd.read_json(io.StringIO(json_data))
    except Exception:
        pass
    return pd.DataFrame([{"代碼": "", "張數": None} for _ in range(20)])

def save_portfolio_to_cloud(username, df):
    clean_df = df.dropna(subset=['代碼']).copy() if '代碼' in df.columns else df
    json_data = clean_df.to_json(orient='records', date_format='iso')
    try:
        cell = portfolio_sheet.find(username)
        if cell:
            portfolio_sheet.update_cell(cell.row, 2, json_data)
        else:
            portfolio_sheet.append_row([username, json_data])
        return True
    except Exception as e:
        st.error(f"⚠️ 雲端儲存失敗: {e}")
        return False

# --- 初始化應用程式狀態 ---
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'current_user' not in st.session_state:
    st.session_state.current_user = None
if 'portfolio' not in st.session_state:
    st.session_state.portfolio = None
if 'page' not in st.session_state:
    st.session_state.page = "welcome"  
if 'data' not in st.session_state: 
    st.session_state.data = None

# --- 登入介面邏輯 ---
def login_ui():
    st.markdown("""
        <div style="max-width: 400px; margin: 40px auto 20px auto; padding: 25px; background-color: #f8f9fa; border-radius: 15px; border: 1px solid #dee2e6; box-shadow: 0 4px 12px rgba(0,0,0,0.1); text-align: center;">
            <h2 style="margin: 0; color: #1f1f1f; font-size: 24px;">🚀 台股個股/ETF查詢</h2>
            <p style="color: #666; margin-top: 8px; margin-bottom: 0; font-size: 14px;">Ez開發 - 投資助手系統</p>
        </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        user_db = get_cloud_users()
        tab1, tab2 = st.tabs(["🔑 帳號登入", "📝 新用戶註冊"])

        with tab1:
            u_id = st.text_input("帳號名稱", key="l_user", placeholder="請輸入帳號")
            u_pw = st.text_input("存取密碼", type="password", key="l_pw", placeholder="請輸入密碼")
            
            if st.button("確認登入", use_container_width=True, type="primary"):
                if user_db.get(u_id) == u_pw:
                    st.session_state.logged_in = True
                    st.session_state.current_user = u_id
                    st.session_state.portfolio = load_portfolio_from_cloud(u_id)
                    st.session_state.page = "welcome"  
                    st.success("登入成功！")
                    st.rerun()
                else:
                    st.error("❌ 帳號或密碼不正確")

        with tab2:
            st.info("註冊資料將儲存於雲端，重啟系統不會遺失。")
            new_u = st.text_input("設定帳號", key="r_user")
            new_p = st.text_input("設定密碼", type="password", key="r_pw")
            confirm_p = st.text_input("確認密碼", type="password", key="r_confirm")
            
            if st.button("提交註冊", use_container_width=True):
                if new_u in user_db:
                    st.warning("⚠️ 帳號已存在")
                elif new_p != confirm_p:
                    st.error("❌ 密碼不一致")
                elif len(new_u) < 2 or len(new_p) < 4:
                    st.error("❌ 長度不足 (帳號需2字元, 密碼需4字元)")
                else:
                    user_sheet.append_row([new_u, new_p])
                    default_df = pd.DataFrame([{"代碼": "", "張數": None} for _ in range(20)])
                    save_portfolio_to_cloud(new_u, default_df)
                    st.success("✅ 註冊成功！請切換至登入分頁。")
                
    st.markdown('</div>', unsafe_allow_html=True)

def load_watchlist_from_cloud():
    try:
        ws = sh.worksheet("watchlist")
        all_records = ws.get_all_records()
        for row in all_records:
            if row.get('username') == st.session_state.current_user:
                raw_codes = str(row.get('codes', "")).replace("'", "").strip()
                if raw_codes:
                    valid_codes = [c.strip() for c in raw_codes.split(',') if 0 < len(c.strip()) < 10]
                    return valid_codes
        return []
    except Exception as e:
        st.error(f"讀取失敗: {e}")
    return []

def save_watchlist_to_cloud(codes_list):
    try:
        ws = sh.worksheet("watchlist")
        cell = ws.find(st.session_state.current_user)
        codes_str = "'" + ",".join([str(c).strip() for c in codes_list])
        
        if cell:
            ws.update(range_name=f"B{cell.row}", values=[[codes_str]])
        else:
            ws.append_row([st.session_state.current_user, codes_str])
    except Exception as e:
        st.error(f"雲端儲存失敗: {e}")

if not st.session_state.logged_in:
    login_ui()
    st.stop()

# --- 自定義 CSS ---
st.markdown("""
    <style>
    .stButton>button { width: 100%; border-radius: 12px; font-weight: bold; border: 1px solid rgba(128, 128, 128, 0.3); height: 3.5em; }
    .metric-val { font-family: 'Consolas'; font-size: 3.5rem; font-weight: bold; line-height: 1.1; }
    .highlight-val { font-size: 2.5rem; font-family: 'Consolas'; font-weight: bold; color: var(--text-color) !important; }
    .stTextInput>div>div>input, .stNumberInput>div>div>input { border-radius: 8px !important; }
    .feature-card { background-color: var(--secondary-background-color); padding: 30px; border-radius: 20px; border: 1px solid rgba(128, 128, 128, 0.2); box-shadow: 0 4px 15px rgba(0,0,0,0.05); text-align: center; transition: all 0.3s ease; margin-bottom: 20px; }
    .feature-card:hover { transform: translateY(-5px); box-shadow: 0 8px 25px rgba(0,0,0,0.15); border-color: var(--primary-color); }
    .feature-title { font-size: 1.5rem; font-weight: bold; color: var(--text-color); margin-bottom: 10px; }
    .feature-desc { color: var(--text-color); opacity: 0.7; font-size: 1rem; }
    .calc-box, .plan-box, .pk-card { background-color: var(--secondary-background-color); padding: 20px; border-radius: 15px; border: 1px solid rgba(128, 128, 128, 0.3); margin-top: 10px; color: var(--text-color); }
    .styled-table { width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 1.1rem; }
    .styled-table th { background-color: var(--secondary-background-color); color: var(--text-color); text-align: left; padding: 12px; border-bottom: 2px solid var(--text-color); }
    .styled-table td { padding: 12px; border-bottom: 1px solid rgba(128, 128, 128, 0.3); color: var(--text-color) !important; }
    
    /* 專門將關注清單第四欄的刪除按鈕縮小並往上對齊 (排除首頁的主要按鈕) */
    div[data-testid="stColumn"]:nth-child(4) button[kind="secondary"],
    div[data-testid="column"]:nth-child(4) button[kind="secondary"] {
        height: auto !important;
        min-height: 32px !important;
        width: max-content !important;
        padding: 0px 16px !important;
        margin-top: -12px !important;
        margin-left: auto !important;
        margin-right: auto !important;
    }
    </style>
    """, unsafe_allow_html=True)

# --- Fugle API 初始化 ---
FUGLE_TOKEN = "YzJjNmM3ODAtZjE1Ny00NzhiLWFjOTUtMDUwZjc2ZWJhYTI1IGRjYTE0ODk3LTRjYTUtNDg5Yi05MjAwLWZmYzNmNzFmNmYwNg=="
client = RestClient(api_key=FUGLE_TOKEN)

# ==========================================
# 🚀 終極數據引擎 1：報價與總量 (強制 Fugle 備援，解決卡死)
# ==========================================
def get_stock_info(symbol):
    clean_symbol = str(symbol).strip().upper().replace('.TW', '').replace('.TWO', '')
    try:
        data = client.stock.intraday.quote(symbol=clean_symbol)
        if not data: return None
        price = float(data.get('lastPrice') or data.get('closePrice') or data.get('previousClose') or 0.0)
        vol = float(data.get('total', {}).get('tradeVolume', 0))
        if 0 < vol < 500000: vol = vol * 1000 
            
        return {
            "name": data.get('name', clean_symbol),
            "price": price,
            "change": float(data.get('change', 0.0)),
            "pct": float(data.get('changePercent', 0.0)),
            "high": float(data.get('highPrice') or price),
            "low": float(data.get('lowPrice') or price),
            "open": float(data.get('openPrice') or price),
            "vol": int(vol),
            "full_ticker": clean_symbol,
            "hist": None, "dividends": None
        }
    except Exception:
        return None

# ==========================================
# 🚀 終極數據引擎 2：配息與日期去重複 (三引擎備援架構)
# ==========================================
def fetch_dividend_history_super(symbol):
    clean_s = str(symbol).strip().upper().replace('.TW', '').replace('.TWO', '')
    div_list = []
    
    # --- 引擎 1：FinMind API (速度最快，但 ETF 資料庫有時不齊全) ---
    fm_token = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2Vyc2lkIjp6ZW5vaWLCJlbWFpbCI6ImVhc29uOTMxMDExQGdtYWlsLmNvbSJ9.ApZobjnh5PCRDtXb8rj6a3Y10h1GUGS0EYKHXkTEvKw"
    try:
        res = requests.get("https://api.finminddata.com/v4/data", params={"dataset": "TaiwanStockDividend", "data_id": clean_s, "token": fm_token}, timeout=5)
        data = res.json()
        if data.get("msg") == "success" and data.get("data"):
            for item in data["data"]:
                if float(item.get('cash_dividend', 0)) > 0:
                    div_list.append({'date': item['ex_dividend_date'], 'amount': float(item['cash_dividend'])})
            if div_list: return sorted(div_list, key=lambda x: x['date'], reverse=True)
    except: pass

    # --- 引擎 2：Yahoo 國際版 API (超強備援，專治一般股與主流 ETF，破除封鎖) ---
    headers_y = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"}
    for suffix in ['.TW', '.TWO']:
        try:
            y_url = f"https://query2.finance.yahoo.com/v8/finance/chart/{clean_s}{suffix}?interval=1d&events=div&range=5y"
            res = requests.get(y_url, headers=headers_y, timeout=5)
            if res.status_code == 200:
                events = res.json().get('chart', {}).get('result', [{}])[0].get('events', {}).get('dividends', {})
                if events:
                    for val in events.values():
                        dt = datetime.fromtimestamp(val['date']).strftime('%Y-%m-%d')
                        div_list.append({'date': dt, 'amount': float(val['amount'])})
                    if div_list: break # 只要 .TW 或 .TWO 其中一個抓到就跳出
        except: pass
        
    if div_list: return sorted(div_list, key=lambda x: x['date'], reverse=True)

    # --- 引擎 3：HiStock 爬蟲 (專治債券 ETF，如 00937B) ---
    headers_h = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Referer": "https://histock.tw/"}
    h_urls = [f"https://histock.tw/stock/etfdividend.aspx?no={clean_s}", f"https://histock.tw/stock/financial.aspx?no={clean_s}&t=2"]
    for url in h_urls:
        try:
            r = requests.get(url, headers=headers_h, timeout=5)
            if r.status_code == 200:
                matches = re.findall(r'(\d{4}/\d{1,2}/\d{1,2}).*?(\d+\.\d+)', r.text, re.DOTALL)
                for m_date, m_val in matches: div_list.append({'date': m_date.replace('/', '-'), 'amount': float(m_val)})
                if div_list: break
        except: pass
        
    # --- 最終處理：去重複與排序 ---
    if div_list:
        unique_divs = {}
        for d in div_list:
            if d['date'] not in unique_divs or d['amount'] > unique_divs[d['date']]:
                unique_divs[d['date']] = d['amount']
        final_list = [{'date': k, 'amount': v} for k, v in unique_divs.items()]
        return sorted(final_list, key=lambda x: x['date'], reverse=True)
        
    return []
# --- ETF 資料處理主函數 (精準天數頻率算法) ---
@st.cache_data(ttl=3600) 
def get_safe_data_etf(symbol):
    info = get_stock_info(symbol)
    if not info or info["price"] <= 0:
        return {"success": False, "msg": f"找不到代號 {symbol} 或目前無報價"}
    
    raw_divs = [0.0] * 4
    multiplier = 1
    freq_label = "年"
    
    try:
        data_list = fetch_dividend_history_super(symbol)
        
        if data_list:
            # 1. 先計算配息頻率與平均間隔天數
            if len(data_list) >= 2:
                check_len = min(5, len(data_list))
                dates = [datetime.strptime(d['date'], "%Y-%m-%d") for d in data_list[:check_len]]
                days_diffs = [(dates[i] - dates[i+1]).days for i in range(len(dates)-1)]
                avg_days = sum(days_diffs) / len(days_diffs)
            else:
                avg_days = 365 # 預設年配
                
            if avg_days <= 45: 
                multiplier, freq_label = 12, "月"
            elif avg_days <= 110: 
                multiplier, freq_label = 4, "季"
            elif avg_days <= 200: 
                multiplier, freq_label = 2, "半年"
            else: 
                multiplier, freq_label = 1, "年"

            # 2. 判斷是否有停發/漏發 (用現在時間與最後一次配息時間對比)
            last_date = datetime.strptime(data_list[0]['date'], "%Y-%m-%d")
            days_since_last = (datetime.now() - last_date).days
            
            expected_days = 365 / multiplier
            # 寬限期：給予一定的延遲宣告空間 (年配多給100天，其他給60天)
            grace_period = 100 if multiplier == 1 else 60 
            
            missed_count = 0
            # 如果距離上次配息已經超過「預期間隔 + 寬限期」，代表最近有停發
            if days_since_last > (expected_days + grace_period):
                missed_count = int(days_since_last / expected_days)
            
            # 3. 填入 raw_divs，有停發的期數在前面補 0，舊資料往後推
            for i in range(min(4, len(data_list) + missed_count)):
                if i < missed_count:
                    raw_divs[i] = 0.0 # 停發的期數補 0
                elif (i - missed_count) < len(data_list):
                    raw_divs[i] = data_list[i - missed_count]['amount'] 
                
    except Exception as e:
        print(f"配息分析失敗: {e}")

    return {
        "success": True, 
        "name": info["name"],
        "price": info["price"],
        "change": info["change"], 
        "pct": info["pct"], 
        "high": info["high"],
        "low": info["low"], 
        "open": info["open"], 
        "vol": info["vol"],
        "raw_divs": raw_divs,       
        "multiplier": multiplier,
        "freq_label": freq_label,
        "last_date": datetime.now(tw_tz).strftime('%Y-%m-%d'), 
        "full_ticker": info["full_ticker"]
    }

def get_dividend_calendar(symbol):
    """抓取單一股票的除息日與發放日預估"""
    clean_symbol = str(symbol).strip().upper().replace('.TW', '').replace('.TWO', '')
    data_list = fetch_dividend_history_super(symbol)
    
    if data_list:
        latest = data_list[0]
        amount = latest['amount']
        ex_date_str = latest['date']
        try:
            ex_dt = datetime.strptime(ex_date_str, "%Y-%m-%d")
            pay_date = (ex_dt + pd.DateOffset(days=28)).strftime('%Y-%m-%d')
            return {
                "symbol": clean_symbol,
                "ex_date": ex_date_str,
                "pay_date": pay_date,
                "amount": amount,
                "success": True
            }
        except: pass
        
    return {"success": False}

def generate_user_calendar():
    if st.session_state.portfolio is None: return None
    portfolio_df = st.session_state.portfolio
    valid_assets = portfolio_df.dropna(subset=["代碼", "張數"])
    valid_assets = valid_assets[valid_assets["代碼"].astype(str).str.strip() != ""]
    if valid_assets.empty:
        st.warning("⚠️ 您的投資組合目前是空的。")
        return None

    calendar_list = []
    today_date = datetime.now(tw_tz).date()
    progress_bar = st.progress(0)
    
    for i, (index, row) in enumerate(valid_assets.iterrows()):
        code = str(row["代碼"]).strip().upper()
        lots = float(row["張數"])
        div_info = get_dividend_calendar(code)
        if div_info["success"]:
            pay_date_obj = datetime.strptime(div_info["pay_date"], '%Y-%m-%d').date()
            if pay_date_obj >= today_date:
                total_pay = div_info["amount"] * lots * 1000
                calendar_list.append({
                    "股票名稱": code,
                    "預計除息日": div_info["ex_date"],
                    "預計發放日 (預估)": div_info["pay_date"],
                    "每股配息": f"${div_info['amount']:.2f}",
                    "預估入帳金額": int(total_pay)
                })
        progress_bar.progress((i + 1) / len(valid_assets))
    progress_bar.empty()
    result_df = pd.DataFrame(calendar_list)
    if result_df.empty: return None
    return result_df

def go_to(page_name):
    st.session_state.page = page_name
    st.rerun()

with st.sidebar:
    st.write(f"👤 當前使用者: **{st.session_state.current_user}**")
    if st.button("⭐ 我的關注清單", use_container_width=True): go_to("watchlist")
    if st.button("🚀 台股查詢", use_container_width=True): go_to("home")
    st.markdown("""<hr style="margin: 10px 0; border-color: #444;">""", unsafe_allow_html=True)
    
    if st.button("🚪 登出系統", use_container_width=True):
        st.session_state.logged_in = False
        st.rerun()
        
    st.markdown("<br><br>", unsafe_allow_html=True) # 產生一點空白往下推
    st.caption("⚠️ 本系統數據僅供參考，不構成投資建議，投資人請審慎評估風險並自負盈虧。")

if st.session_state.page == "welcome":
    st.markdown("<br><br><br><h3 style='text-align: center; color: #555;'>👈 請從左側選單選擇功能</h3>", unsafe_allow_html=True)

elif st.session_state.page == "home":
    st.markdown("<h3 style='color: #333;'>請選擇功能進入：</h3>", unsafe_allow_html=True)
    st.divider()
    col_a, col_b, col_c, col_d = st.columns(4)
    with col_a:
        st.markdown('<div class="feature-card"><div class="feature-title">📈 個股分析</div><div class="feature-desc">個股查詢與估價</div></div>', unsafe_allow_html=True)
        if st.button("進入個股分析", use_container_width=True, type="primary"): go_to("stock_query")
    with col_b:
        st.markdown('<div class="feature-card"><div class="feature-title">📊 ETF 分析</div><div class="feature-desc">ETF 試算與規劃</div></div>', unsafe_allow_html=True)
        if st.button("進入 ETF 分析", use_container_width=True, type="primary"): go_to("etf_query")
    with col_c:
        st.markdown('<div class="feature-card"><div class="feature-title">⚔️ ETF 對比</div><div class="feature-desc">ETF 對比工具</div></div>', unsafe_allow_html=True)
        if st.button("進入對比工具", use_container_width=True, type="primary"): go_to("pk_tool")
    with col_d:
        st.markdown('<div class="feature-card"><div class="feature-title">💼 我的資產</div><div class="feature-desc">個人投資組合</div></div>', unsafe_allow_html=True)
        if st.button("進入我的資產", use_container_width=True, type="primary"): go_to("portfolio")

elif st.session_state.page == "stock_query":
    if st.button("⬅️ 返回工具箱"): go_to("home")
    st.title("🔍 台股自動估價系統 (個股)")
    main_col, side_col = st.columns([8, 4])
    with main_col:
        # 1. 股票代碼輸入框
        stock_code = st.text_input("請輸入台股代碼 (例如: 2330)")
        
        # 2. ✨ 把 EPS 和 本益比的輸入框搬到這裡 (在 if 的外面) ✨
        col_eps, col_pe = st.columns(2)
        with col_eps: eps = st.number_input("輸入該股 EPS (4季累積)", min_value=0.01, step=0.1, value=10.0)
        with col_pe: pe_target = st.number_input("自訂參考本益比 (PE)", value=15.0, step=0.1)

        st.divider() # 加一條分隔線讓畫面比較好看

        # 3. 有輸入代碼時，才開始抓資料跟計算
        if stock_code:
            info = get_stock_info(stock_code)
            if info:
                current_price = info['price']
                st.markdown(f"## {info['name']}")
                st.markdown(f"<div class='date-text'>資料日期：{datetime.now(tw_tz).strftime('%Y-%m-%d')}</div>", unsafe_allow_html=True)
                
                cp1, cp2 = st.columns([2, 1])
                with cp1:
                    color = "#ff4b4b" if info['change'] > 0 else "#00ff00" if info['change'] < 0 else "#FFFFFF"
                    st.markdown(f"<div class='metric-val' style='color:{color}'>{current_price:.2f}</div>", unsafe_allow_html=True)
                    st.markdown(f"<span style='color:{color}; font-weight:bold; font-size:1.5rem;'>{info['change']:+.2f} ({info['pct']:+.2f}%)</span>", unsafe_allow_html=True)
                with cp2:
                    st.caption("今日行情細節")
                    st.write(f"最高: {info['high']:.2f} / 最低: {info['low']:.2f}")
                    st.write(f"開盤: {info['open']:.2f} / 總量: {int(info['vol']/1000):,} 張")
                
                # 這裡就不用再放輸入框了，直接進行計算
                if current_price > 0:
                    fair_price = eps * pe_target
                    st.subheader("📊 換算結果")
                    st.markdown(f"<div class='calc-box'>合理價參考：<span class='highlight-val'>{fair_price:.2f}</span></div>", unsafe_allow_html=True)
                    if current_price <= fair_price: 
                        st.success(f"✅ 目前股價 {current_price:.2f} 低於目標參考價")
                    else: 
                        st.warning(f"⚠️ 目前股價 {current_price:.2f} 已超過目標參考價")
        

    with side_col:
        st.write("### 📖 說明")
        st.caption("1. 輸入股票代碼。")
        st.caption("2. 輸入股票4季累積EPS。")
        st.caption("3. 輸入個股本益比。")
        st.divider()
        st.info("計算公式：EPS × 自訂本益比 = 參考價")

elif st.session_state.page == "etf_query":
    if st.button("⬅️ 返回工具箱"): go_to("home")
    st.title("📈 ETF 專用 ")
    
    main_col, side_col = st.columns([8, 4])
    with main_col:
        st.markdown("### 🔍 查詢設定 <span style='font-size: 1rem; color: #aaa; font-weight: normal;'>(最新配息日要等到入資料庫才能抓到)</span>", unsafe_allow_html=True)
        input_c1, input_c2 = st.columns([3, 1])
 
        with input_c1:
            symbol_input = st.text_input("ETF 代號", placeholder="例如: 00919").strip().upper()
        with input_c2:
            st.write("")
            st.write("")
            if st.button("開始計算", type="primary"):
                if symbol_input:
                    with st.spinner('抓取數據中...'):
                        st.session_state.data = get_safe_data_etf(symbol_input)

        if st.session_state.data:
            if st.session_state.data.get("success"):
                d = st.session_state.data
                m_color = "#ff4b4b" if d['change'] >= 0 else "#00ff00"
                st.markdown(f"## {d['name']} <small style='font-size:1rem; color:#aaa;'>(偵測為{d['freq_label']}配息)</small>", unsafe_allow_html=True)
                st.markdown(f"<div class='date-text'>資料日期：{d.get('last_date')}</div>", unsafe_allow_html=True)
                
                info_c1, info_c2 = st.columns([2, 1])
                with info_c1:
                    st.markdown(f"<div class='metric-val' style='color:{m_color}'>{d['price']:.2f}</div>", unsafe_allow_html=True)
                    st.markdown(f"<span style='color:{m_color}; font-weight:bold; font-size:1.5rem;'>{d['change']:+.2f} ({d['pct']:+.2f}%)</span>", unsafe_allow_html=True)
        
                with info_c2:
                    st.caption("今日行情細節")
                    st.write(f"最高: {d['high']:.2f} / 最低: {d['low']:.2f}")
                    st.write(f"開盤: {d['open']:.2f} / 總量: {int(d['vol']/1000):,} 張")

                st.divider()
                st.subheader("📑 歷史配息參考")
                
                # --- 新增這段配息頻率選擇器 ---
                freq_map = {"月配": 12, "季配": 4, "半年配": 2, "年配": 1}
                sys_freq_name = f"{d['freq_label']}配" if f"{d['freq_label']}配" in freq_map else "年配"
                sys_index = list(freq_map.keys()).index(sys_freq_name)
                
                user_freq = st.selectbox("🔄 自訂/修正配息頻率：", list(freq_map.keys()), index=sys_index)
                
                d['multiplier'] = freq_map[user_freq]
                d['freq_label'] = user_freq.replace("配", "")
                # ------------------------------
            
                e_cols = st.columns(4)
                d1 = e_cols[0].number_input("最新", value=float(d["raw_divs"][0]), format="%.3f")
                d2 = e_cols[1].number_input("前一", value=float(d["raw_divs"][1]), format="%.3f")
                d3 = e_cols[2].number_input("前二", value=float(d["raw_divs"][2]), format="%.3f")
                d4 = e_cols[3].number_input("前三", value=float(d["raw_divs"][3]), format="%.3f")
                
                # 根據不同配息頻率，取用正確的期數來計算年配息
                if d['multiplier'] == 1:
                    # 年配：只取最新 1 期
                    avg_annual = round(d1, 4)
                elif d['multiplier'] == 2:
                    # 半年配：取最新 2 期加總
                    avg_annual = round(d1 + d2, 4)
                elif d['multiplier'] == 4:
                    # 季配：取 4 期加總
                    avg_annual = round(d1 + d2 + d3 + d4, 4)
                else:
                    # 月配或其他：用4格平均推算全年
                    avg_annual = round((sum([d1, d2, d3, d4]) / 4) * d['multiplier'], 4)
                
                real_yield = (avg_annual / d['price']) * 100 if d['price'] > 0 else 0
                
                stat_c1, stat_c2 = st.columns(2)
                with stat_c1:
                    st.caption(f"預估年配息 (系統以{d['freq_label']}配計算)")
                    st.markdown(f"<div class='highlight-val'>{avg_annual:.2f}</div>", unsafe_allow_html=True)
                with stat_c2:
                    st.caption("實質殖利率")
                    st.markdown(f"<div class='highlight-val'>{real_yield:.2f}%</div>", unsafe_allow_html=True)

                st.divider()
                st.subheader("📊 估值位階參考")
                p_cheap, p_fair, p_high = avg_annual/0.10 if avg_annual>0 else 0, avg_annual/0.07 if avg_annual>0 else 0, avg_annual/0.05 if avg_annual>0 else 0
                rec = "💎 便宜買入" if d['price'] <= p_cheap and p_cheap > 0 else "✅ 合理持有" if d['price'] <= p_fair and p_fair > 0 else "❌ 昂貴不建議"
                st.markdown(f"<div class='calc-box'>系統建議：<b>{rec}</b></div>", unsafe_allow_html=True)

                p_cheap_val = f"{p_cheap:.2f}"
                p_fair_val = f"{p_fair:.2f}"
                p_high_val = f"{p_high:.2f}"
                
                table_html = f"""
                <table class="styled-table">
                    <thead><tr><th>估值位階</th><th>建議價格參考</th></tr></thead>
                    <tbody>
                        <tr><td>便宜價 (10%)</td><td>{p_cheap_val} 以下</td></tr>
                        <tr><td>合理價 (7%)</td><td>{p_cheap_val} ~ {p_fair_val}</td></tr>
                        <tr><td>昂貴價 (5%)</td><td>高於 {p_high_val}</td></tr>
                    </tbody>
                </table>
                """
                st.markdown(table_html, unsafe_allow_html=True)

                st.divider()
                st.subheader("💰 持有張數試算 (含稅費)")
                ratio_54c = st.slider("54C 股利佔比 (%)", 0, 100, 40)
                calc_c1, calc_c2 = st.columns([1, 2])
                with calc_c1: hold_lots = st.number_input("持有張數", min_value=0, value=10, step=1)
                with calc_c2:
                    total_shares = hold_lots * 1000
                    total_raw = total_shares * d1
                    
                    div_54c_part = total_raw * (ratio_54c/100)
                    nhi_amt = div_54c_part * 0.0211 if div_54c_part >= 20000 else 0
                    net_per_period = total_raw - nhi_amt
                    
                val_invest_total = f"{(total_shares * d['price'] * 1.001425):,.0f}"
                val_raw_div = f"{total_raw:,.0f}"
                val_nhi_deduct = f"{nhi_amt:,.0f}"
                val_net_amt = f"{net_per_period:,.0f}"
                val_annual_net_amt = f"{(net_per_period * d['multiplier']):,.0f}"

                st.markdown(f"""
                <div class="calc-box">
                    預估總投入: {val_invest_total} 元<br>
                    每{d['freq_label']}總配息: {val_raw_div} 元<br>
                    <span style="color: #d9534f;">└ 二代健保扣費: -{val_nhi_deduct} 元</span><br>
                    <b>每{d['freq_label']}實領金額: {val_net_amt} 元</b><br>
                    <hr style="border: 0.5px solid #dee2e6;">
                    一年累計實領: {val_annual_net_amt} 元
                </div>
                """, unsafe_allow_html=True)

                st.divider()
                st.subheader("🔮 存股未來財富試算")
                with st.container():
                    # 第一排：改成 4 個欄位，讓數字輸入框有絕對寬敞的空間
                    f_col0, f_col1, f_col2, f_col3 = st.columns(4)
                    with f_col0: custom_initial = st.number_input("初始投入總金額 (元)", min_value=0, value=3000000, step=100000)
                    with f_col1: custom_monthly = st.number_input("每月預計投入 (元)", min_value=0, value=0, step=1000)
                    with f_col2: custom_withdraw = st.number_input("每月預計領出 (元)", min_value=0, value=0, step=1000)
                    with f_col3: custom_yield = st.number_input("自訂年化殖利率 (%)", value=float(f"{real_yield:.2f}"), step=0.1)
                    
                    # 第二排：將拉桿獨立放一行，長度拉滿更好滑動
                    st.write("") # 加一點點小留白讓視覺不擁擠
                    custom_years = st.slider("目標投入年數", 1, 40, 10)
                    
                    r = (custom_yield / 100) / 12
                    n = custom_years * 12
                    
                    # 每月實際進入本金的錢 = 投入 - 領出
                    net_monthly = custom_monthly - custom_withdraw
                    
                    if r > 0:
                        fv = custom_initial * ((1 + r)**n) + net_monthly * (((1 + r)**n - 1) / r) * (1 + r)
                    else:
                        fv = custom_initial + (net_monthly * n)
                    
                    # 避免領太多扣到變負債 (最低就是帳戶歸零)
                    fv = max(0, fv)
                    
                    total_invested = custom_initial + (custom_monthly * n)
                    total_withdrawn = custom_withdraw * n
                    
                    val_fv = f"{fv:,.0f}"
                    val_total_invested = f"{total_invested:,.0f}"
                    val_total_withdrawn = f"{total_withdrawn:,.0f}"
                    
                    if total_invested > 0:
                        growth_ratio = (fv + total_withdrawn) / total_invested
                    else:
                        growth_ratio = 0
                    val_growth_ratio = f"{growth_ratio:.2f}"
                    val_monthly_passive = f"{(fv * (custom_yield / 100)) / 12:,.0f}"

                    st.markdown(f"""
                    <div class="calc-box" style="border: 2px solid #dee2e6; padding: 25px; background-color: #f8f9fa;">
                        <div style="font-size: 3.2rem; font-weight: bold; color: #1f1f1f;">$ {val_fv} <small style="font-size: 1.2rem;">元</small></div>
                        <hr style="border: 0.5px solid #dee2e6;">
                        <p style="font-size: 1rem; color: #333; line-height: 1.8;">
                            累積投入本金: <b>{val_total_invested}</b> 元 | 
                            期間累計領出: <b style="color: #d9534f;">{val_total_withdrawn}</b> 元 | 
                            整體資產成長: <b>{val_growth_ratio}</b> 倍<br>
                            <span style="color: #28a745; font-weight: bold;">期滿後每月預計被動收入 (不扣本金): {val_monthly_passive} 元</span>
                        </p>
                    </div>
                    """, unsafe_allow_html=True)
            else:
                st.error(f"❌ 查詢失敗：{st.session_state.data.get('msg')}")

    with side_col:
        st.write("### 📖 說明")
        st.caption("1. 輸入代號後點擊開始計算。")
        st.caption("2. 手動輸入配息即可試算。")
        st.divider()
        st.success("系統正常運行中")

elif st.session_state.page == "pk_tool":
    if st.button("⬅️ 返回工具箱"): go_to("home")
    st.title("⚔️ ETF 對比工具")
    
    col_in1, col_in2 = st.columns(2)
    with col_in1: code1 = st.text_input("輸入代碼 A", value="00919").strip().upper()
    with col_in2: code2 = st.text_input("輸入代碼 B", value="00918").strip().upper()
    
    if st.button("開始對比"):
        with st.spinner("抓取對比數據中..."):
            r1 = get_safe_data_etf(code1)
            r2 = get_safe_data_etf(code2)
            
            if r1["success"] and r2["success"]:
                st.divider()
                c1, c2 = st.columns(2)
                analysis = []
                for r in [r1, r2]:
                    # 取得四期的配息資料
                    d1, d2, d3, d4 = r["raw_divs"][0], r["raw_divs"][1], r["raw_divs"][2], r["raw_divs"][3]
                    
                    # 根據不同配息頻率，取用正確的期數來計算年配息
                    if r['multiplier'] == 1:
                        # 年配：只取最新 1 期
                        avg_annual = round(d1, 4)
                    elif r['multiplier'] == 2:
                        # 半年配：取最新 2 期加總
                        avg_annual = round(d1 + d2, 4)
                    elif r['multiplier'] == 4:
                        # 季配：取 4 期加總
                        avg_annual = round(d1 + d2 + d3 + d4, 4)
                    else:
                        # 月配或其他：用 4 格平均推算全年
                        avg_annual = round((sum(r["raw_divs"]) / 4) * r["multiplier"], 4)
                    
                    real_yield = (avg_annual / r['price']) * 100 if r['price'] > 0 else 0
                    analysis.append({"annual_div": avg_annual, "yield": real_yield})

                for i, r in enumerate([r1, r2]):
                    with [c1, c2][i]:
                        color = "#ff4b4b" if r['change'] > 0 else "#00ff00"
                        st.markdown(f"""
                        <div class="pk-card">
                            <h3>{r['name']}</h3>
                            <h2 style="color:{color}">{r['price']:.2f}</h2>
                            <p>{r['change']:+.2f} ({r['pct']:+.2f}%)</p>
                        </div>
                        """, unsafe_allow_html=True)
                
                df = pd.DataFrame({
                    "指標項目": ["目前價格", "當前漲幅", "配息頻率", "預估年配息", "實質殖利率"],
                    f"{code1}": [f"{r1['price']:.2f}", f"{r1['pct']:.2f}%", r1['freq_label'], f"{analysis[0]['annual_div']:.2f}", f"{analysis[0]['yield']:.2f}%"],
                    f"{code2}": [f"{r2['price']:.2f}", f"{r2['pct']:.2f}%", r2['freq_label'], f"{analysis[1]['annual_div']:.2f}", f"{analysis[1]['yield']:.2f}%"]
                })
                st.table(df)
            else:
                st.error("查無資料，請確認代碼是否輸入正確。")

elif st.session_state.page == "portfolio":
    if st.button("⬅️ 返回工具箱"): go_to("home")
    st.title(f"💼 {st.session_state.current_user} 的投資組合")
    
    with st.expander("📥 匯入投資清單 (CSV)"):
        uploaded_file = st.file_uploader("選擇 CSV 檔案", type="csv")
        if uploaded_file:
            import_df = pd.read_csv(uploaded_file)
            if "代碼" in import_df.columns and "張數" in import_df.columns:
                new_data = import_df[["代碼", "張數"]].copy()
                if len(new_data) < 20:
                    padding = pd.DataFrame([{"代碼": "", "張數": None} for _ in range(20 - len(new_data))])
                    new_data = pd.concat([new_data, padding], ignore_index=True)
                st.session_state.portfolio = new_data
                st.success("CSV 已載入編輯器，請檢查後點擊下方儲存。")
            else:
                st.error("CSV 格式錯誤！需包含『代碼』與『張數』兩個欄位。")

    st.markdown("### 📝 編輯投資清單")
    if st.session_state.portfolio is None or len(st.session_state.portfolio) == 0:
        st.session_state.portfolio = pd.DataFrame([{"代碼": "", "張數": None} for _ in range(20)])
    
    edited_df = st.data_editor(st.session_state.portfolio, num_rows="dynamic", use_container_width=True)

    if st.button("💾 儲存變更至資料庫", type="primary"):
        st.session_state.portfolio = edited_df
        if save_portfolio_to_cloud(st.session_state.current_user, edited_df):
            st.success("✅ 投資組合已成功同步至資料庫")

    st.divider()
    st.markdown("### 📊 資產市值與配置分析")
    
    col_cost1, col_cost2 = st.columns([1, 2])
    with col_cost1:
        total_cost_input = st.number_input("💵 請輸入總成本 (自行填寫)", min_value=0.0, value=0.0, step=10000.0)

    valid_df = edited_df.dropna(subset=["代碼", "張數"])
    valid_df = valid_df[valid_df["代碼"].astype(str).str.strip() != ""]
    
    if not valid_df.empty:
        if st.button("開始計算當前市值", type="primary"):
            results = []
            total_market_val = 0
            total_annual_div = 0
            with st.spinner("同步市場最新價格中..."):
                for index, row in valid_df.iterrows():
                    try:
                        code = str(row["代碼"]).strip().upper()
                        shares = float(row["張數"]) * 1000
                        if code:
                            data = get_safe_data_etf(code)
                            if data["success"]:
                                m_val = data["price"] * shares
                                
                                # --- 這裡更新為精準的配息計算邏輯 ---
                                d1, d2, d3, d4 = data["raw_divs"][0], data["raw_divs"][1], data["raw_divs"][2], data["raw_divs"][3]
                                if data['multiplier'] == 1:
                                    avg_annual = d1
                                elif data['multiplier'] == 2:
                                    avg_annual = d1 + d2
                                elif data['multiplier'] == 4:
                                    avg_annual = d1 + d2 + d3 + d4
                                else:
                                    avg_annual = (sum(data["raw_divs"]) / 4) * data["multiplier"]
                                
                                ann_div = avg_annual * shares
                                # ---------------------------------
                                
                                results.append({
                                    "名稱": data["name"], "代碼": code, "現價": data["price"],
                                    "持有價值": m_val, "預估年領股息": ann_div
                                })
                                total_market_val += m_val
                                total_annual_div += ann_div
                    except: continue

            if results:
                res_df = pd.DataFrame(results)
                
                return_amt = total_market_val - total_cost_input
                return_pct = (return_amt / total_cost_input * 100) if total_cost_input > 0 else 0
                
                ret_color = "#ff4b4b" if return_amt > 0 else "#00ff00" if return_amt < 0 else "#ffffff"
                circle_pct = min(abs(return_pct), 100)
                
                dashboard_html = f"""
                <div style="display: flex; flex-wrap: wrap; align-items: center; justify-content: space-around; background-color: #1e1e28; padding: 25px; border-radius: 15px; border: 1px solid #444; margin-bottom: 20px;">
                    <div style="position: relative; width: 160px; height: 160px; border-radius: 50%; background: conic-gradient({ret_color} {circle_pct}%, #2b2b36 0); display: flex; align-items: center; justify-content: center; box-shadow: 0 0 15px rgba(0,0,0,0.3);">
                        <div style="position: absolute; width: 125px; height: 125px; background-color: #1e1e28; border-radius: 50%; display: flex; flex-direction: column; align-items: center; justify-content: center;">
                            <span style="color: #aaa; font-size: 16px;">股票報酬</span>
                            <span style="color: {ret_color}; font-size: 22px; font-weight: bold;">{return_pct:+.2f}%</span>
                        </div>
                    </div>
                    <div style="min-width: 280px; margin-top: 10px;">
                        <div style="display: flex; justify-content: space-between; border-bottom: 1px solid #444; padding-bottom: 8px; margin-bottom: 8px;">
                            <span style="color: #ccc; font-size: 18px;">總成本：</span>
                            <span style="color: #fff; font-size: 22px; font-weight: bold; font-family: 'Consolas';">{total_cost_input:,.0f}</span>
                        </div>
                        <div style="display: flex; justify-content: space-between; border-bottom: 1px solid #444; padding-bottom: 8px; margin-bottom: 15px;">
                            <span style="color: #ccc; font-size: 18px;">股票市值：</span>
                            <span style="color: #fff; font-size: 22px; font-weight: bold; font-family: 'Consolas';">{total_market_val:,.0f}</span>
                        </div>
                        <div style="display: flex; justify-content: space-between;">
                            <span style="color: #ccc; font-size: 18px;">總報酬：</span>
                            <span style="color: {ret_color}; font-size: 26px; font-weight: bold; font-family: 'Consolas';">{return_amt:+,.0f}</span>
                        </div>
                        <div style="text-align: right; margin-top: 5px;">
                            <span style="color: #888; font-size: 13px;">(無加上手續費用)</span>
                        </div>
                    </div>
                </div>
                """
                st.markdown(dashboard_html, unsafe_allow_html=True)
                
                m1, m2 = st.columns(2)
                m1.metric("預估年領股息", f"${total_annual_div:,.0f}")
                avg_yield = (total_annual_div / total_market_val * 100) if total_market_val > 0 else 0
                m2.metric("組合平均殖利率", f"{avg_yield:.2f}%")
                
                col_chart, col_table = st.columns([1, 1])
                with col_chart:
                    fig = px.pie(res_df, values='持有價值', names='名稱', 
                                 title="資產配置分佈圖", color_discrete_sequence=px.colors.qualitative.Pastel)
                    fig.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font_color="white")
                    st.plotly_chart(fig, use_container_width=True)
                with col_table:
                    st.write("#### 詳細數據")
                    st.dataframe(res_df, use_container_width=True)

        st.divider()
        st.subheader("📅 自動化領息排程月曆")
        st.info("系統將根據您上方的持股清單，自動追蹤最新的除息紀錄並預估入帳時間。")
        
        if st.button("🚀 生成我的專屬領息月曆", use_container_width=True, type="primary"):
            cal_df = generate_user_calendar()
            
            if cal_df is not None and not cal_df.empty:
                cal_df = cal_df.sort_values(by="預計發放日 (預估)")
                st.markdown("#### 📥 預計入帳時間表")
                st.dataframe(cal_df, use_container_width=True, hide_index=True)
                
                total_incoming = cal_df["預估入帳金額"].sum()
                st.success(f"💰 這一波領息預計總入帳： **${total_incoming:,.0f}** 元")
                st.caption("※ 註：發放日為系統根據台股慣例（除息後約28天）自動推算，實際請以各公司公告為準。")
                st.caption("※ 註：最新的配息日可能會晚些時間抓取網站沒更新那麼快")
    else:
        st.info("請先在上方表格輸入股票代碼與持有張數。")

elif st.session_state.page == "watchlist":
    st.title("⭐ 我的關注清單")

    if 'watchlist_data' not in st.session_state:
        try:
            st.session_state.watchlist_data = load_watchlist_from_cloud()
        except:
            st.session_state.watchlist_data = []

    with st.form("add_stock_form", clear_on_submit=True):
        st.write("### ➕ 新增追蹤標的")
        new_code = st.text_input("輸入台股代碼", placeholder="例如: 2330").strip().upper()
        submit_button = st.form_submit_button("確認加入", use_container_width=True)
        
        if submit_button and new_code:
            clean_code = new_code.replace('.TW', '').replace('.TWO', '')
            if clean_code not in st.session_state.watchlist_data:
                info = get_stock_info(clean_code)
                if info:
                    st.session_state.watchlist_data.append(clean_code)
                    save_watchlist_to_cloud(st.session_state.watchlist_data)
                    st.success(f"✅ {clean_code} 加入成功！")
                    st.rerun()
                else:
                    st.error("❌ 找不到代碼")

    st.divider()

    @st.fragment(run_every=120)
    def refresh_watchlist_view():
        if st.session_state.watchlist_data:
            now_tw = datetime.now(tw_tz).strftime('%H:%M:%S')
            st.caption(f"⏱️ 行情自動刷新中... ({now_tw})")
            
            for code in st.session_state.watchlist_data:
                item = get_stock_info(code)
                if item:
                    c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
                    color = "#ff4b4b" if item['change'] > 0 else "#00ff00"
                    c1.markdown(f"**{item['name']}** <span style='color:#aaa; font-size:0.9em;'>({item['full_ticker']})</span>", unsafe_allow_html=True)
                    c2.markdown(f"<span style='color:{color}; font-size:1.3rem; font-weight:bold;'>{item['price']:.2f}</span>", unsafe_allow_html=True)
                    c3.markdown(f"<span style='color:{color};'>{item['change']:+.2f} ({item['pct']:+.2f}%)</span>", unsafe_allow_html=True)
                    
                    if c4.button("刪除", key=f"del_{item['full_ticker']}"):
                        try:
                            st.session_state.watchlist_data.remove(item['full_ticker'])
                        except ValueError:
                            pass
                        save_watchlist_to_cloud(st.session_state.watchlist_data)
                        st.rerun()
                    st.markdown("<hr style='margin-top: -15px; margin-bottom: 10px; border: none; border-top: 1px solid rgba(128, 128, 128, 0.3);'>", unsafe_allow_html=True)
        else:
            st.info("清單空空如也，請在上方新增標的。")


    refresh_watchlist_view()
