import streamlit as st
import pandas as pd
import openai
import yfinance as yf
import requests
import altair as alt
import plotly.graph_objects as go
from io import StringIO
import time
from datetime import datetime, date, timedelta
import urllib.parse
from streamlit_gsheets import GSheetsConnection 
import extra_streamlit_components as stx

# 1. 쿠키 매니저 및 새로고침 방어 로직 (최상단 배치)
cookie_manager = stx.CookieManager()

# 마법의 0.1초 딜레이
time.sleep(0.1) 

saved_email = cookie_manager.get("user_email")

# 로그인 안 된 상태인데, 쿠키(방문증)가 발견되었다면? -> 몰래 로그인 복구!
if saved_email and not st.session_state.get('logged_in', False):
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        df = conn.read(worksheet="Users", ttl=0) 
        
        if not df.empty and 'Email' in df.columns and saved_email in df['Email'].values:
            user_idx = df.index[df['Email'] == saved_email].tolist()[0]
            
            st.session_state.logged_in = True
            st.session_state.user_email = saved_email
            st.session_state.user_name = df.at[user_idx, 'Name']
            st.session_state.remaining_calls = int(df.at[user_idx, 'Remaining_Calls'])
            st.session_state.plan = df.at[user_idx, 'Plan']
            
            st.rerun()
        else:
            cookie_manager.delete("user_email")
    except Exception as e:
        pass

# -----------------------------------------------------------------------------
# 0. 구글 OAuth 설정 & 세션 초기화
# -----------------------------------------------------------------------------
GOOGLE_CLIENT_ID = st.secrets.get("google_client_id", "")
GOOGLE_CLIENT_SECRET = st.secrets.get("google_client_secret", "")
GOOGLE_REDIRECT_URI = st.secrets.get("google_redirect_uri", "https://marketlogic.co.kr")

if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False

def get_google_login_url():
    auth_url = "https://accounts.google.com/o/oauth2/v2/auth"
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "prompt": "select_account"
    }
    return f"{auth_url}?{urllib.parse.urlencode(params)}"

# -----------------------------------------------------------------------------
# 1. 페이지 설정 및 CSS
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Market Logic", 
    page_icon=None, 
    layout="wide", 
    initial_sidebar_state="auto"
)

st.markdown("""
    <style>
    @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');
    html, body, .stApp { font-family: 'Pretendard', sans-serif !important; background-color: #f5f7f9; }
    .section-header { font-size: 20px; font-weight: 700; color: #111827; margin-top: 30px; margin-bottom: 15px; border-left: 4px solid #111827; padding-left: 10px; }
    div[data-testid="stVerticalBlockBorderWrapper"] { background-color: #ffffff; border: 1px solid #e5e7eb; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); padding: 20px; margin-bottom: 15px; }
    div.d-day-container { background-color: #1e293b; color: white; padding: 30px; border-radius: 16px; text-align: center; margin-bottom: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
    .d-day-title { font-size: 16px; color: #94a3b8; margin-bottom: 10px; letter-spacing: 1px; text-transform: uppercase; }
    .d-day-count { font-size: 56px; font-weight: 800; color: #ffffff; line-height: 1.1; margin: 10px 0; }
    .d-day-date { font-size: 18px; color: #cbd5e1; margin-top: 10px; }
    .ai-box { background-color: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 20px; height: 100%; }
    .ai-title { font-weight: 700; font-size: 16px; margin-bottom: 10px; color: #166534; border-bottom: 1px solid #bbf7d0; padding-bottom: 5px; }
    .ai-text { font-size: 14px; line-height: 1.7; color: #14532d; word-break: keep-all; }
    .info-box { background-color: #eff6ff; border: 1px solid #bfdbfe; border-radius: 8px; padding: 15px; color: #1e3a8a; font-size: 14px; line-height: 1.6; margin-bottom: 20px; }
    .warning-box { background-color: #fefce8; border: 1px solid #fde047; border-radius: 8px; padding: 15px; color: #854d0e; font-size: 14px; line-height: 1.6; margin-bottom: 20px; }
    .footer-disclaimer { text-align: center; color: #9ca3af; font-size: 13px; padding: 20px 0; margin-top: 40px; border-top: 1px solid #e5e7eb; line-height: 1.6; }
    </style>
    """, unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 구글 로그인 리디렉션 처리
# -----------------------------------------------------------------------------
query_params = st.query_params
if "code" in query_params and not st.session_state.logged_in:
    code = query_params["code"]
    token_url = "https://oauth2.googleapis.com/token"
    token_data = {
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "grant_type": "authorization_code"
    }
    res = requests.post(token_url, data=token_data)
    if res.status_code == 200:
        access_token = res.json().get("access_token")
        user_info_url = "https://www.googleapis.com/oauth2/v1/userinfo"
        user_res = requests.get(user_info_url, headers={"Authorization": f"Bearer {access_token}"})

        if user_res.status_code == 200:
            user_info = user_res.json()
            user_email = user_info.get("email")
            user_name = user_info.get("name")
            st.session_state.logged_in = True
            st.session_state.user_email = user_email
            st.session_state.user_name = user_name
            cookie_manager.set("user_email", user_email, max_age=30*24*60*60)
            
            conn = st.connection("gsheets", type=GSheetsConnection)
            df = conn.read(worksheet="Users", ttl=0) 
            today_str = date.today().strftime('%Y-%m-%d')
            
            if df.empty or 'Email' not in df.columns:
                df = pd.DataFrame(columns=['Email', 'Name', 'Plan', 'Remaining_Calls', 'Last_Free_Date'])
                
            if user_email in df['Email'].values:
                user_idx = df.index[df['Email'] == user_email].tolist()[0]
                plan = df.at[user_idx, 'Plan']
                calls = int(df.at[user_idx, 'Remaining_Calls'])
                last_free = str(df.at[user_idx, 'Last_Free_Date'])
                
                if last_free != today_str:
                    if calls < 1:  
                        calls = 1
                    df.at[user_idx, 'Remaining_Calls'] = calls
                    df.at[user_idx, 'Last_Free_Date'] = today_str
                    conn.update(worksheet="Users", data=df) 
            else:
                plan = "Free"
                calls = 1
                last_free = today_str
                new_row = pd.DataFrame([{'Email': user_email, 'Name': user_name, 'Plan': plan, 'Remaining_Calls': calls, 'Last_Free_Date': last_free}])
                df = pd.concat([df, new_row], ignore_index=True)
                conn.update(worksheet="Users", data=df) 
                
            st.session_state.remaining_calls = calls
            st.session_state.plan = plan
            st.query_params.clear()

# -----------------------------------------------------------------------------
# 2. 사이드바
# -----------------------------------------------------------------------------
with st.sidebar:
    st.title("Market Logic")
    
    if st.session_state.logged_in:
        user_name = st.session_state.get('user_name', '회원')
        rem_calls = st.session_state.get('remaining_calls', 0)
        st.markdown(f"👤 **{user_name}** 님")
        
        user_plan = st.session_state.get('plan', 'Free')
        if user_plan == 'Pro' or int(rem_calls) > 100:
            st.info("⚡ 잔여 분석 횟수: **♾️ 무제한 (Pro)**")
        else:
            st.info(f"⚡ 잔여 분석 횟수: **{rem_calls} / 100회**")
            
        if st.button("로그아웃", use_container_width=True):
            cookie_manager.delete("user_email") 
            st.session_state.clear()
            time.sleep(0.5) 
            st.rerun()
        
        st.markdown("---")
        
        if st.session_state.get('plan', 'Free') == 'Free':
            st.markdown("""
            <div style='background-color:#fffbeb; border:1px solid #fde68a; border-radius:10px; padding:15px; margin-bottom:15px; box-shadow: 0 2px 4px rgba(0,0,0,0.05);'>
                <div style='font-size:15px; font-weight:800; color:#b45309; margin-bottom:8px;'>👑 Pro 멤버십 업그레이드</div>
                <div style='font-size:13px; color:#92400e; line-height:1.5; margin-bottom:0px; word-break:keep-all;'>
                    무제한 AI 펀드매니저 분석과<br>VIP 시크릿 탭을 열어보세요! (월 9,900원)
                </div>
            </div>
            """, unsafe_allow_html=True)
            st.link_button("💸 간편 송금하기 (모바일 카카오페이)", "https://qr.kakaopay.com/Ej7mwSX0V135606469", use_container_width=True)
            st.link_button("📝 무통장 입금 확인 및 승인 요청", "https://forms.google.com", type="primary", use_container_width=True)
        else:
            st.success("👑 Pro 멤버십 이용 중")
    else:
        st.warning("로그인 후 AI 분석 기능을 이용하세요.")
        st.link_button("Google 로그인", get_google_login_url(), type="primary", use_container_width=True)
        
    st.markdown("---")
    menu = st.radio("메뉴 선택", ["주가 지수", "투자 지표", "시장 심리", "시장 지도", "주요 일정", "🔒 VIP 포트폴리오"], index=0)
    st.markdown("---")
    st.subheader("설정 (Settings)")
    if "openai_api_key" in st.secrets:
        api_key = st.secrets["openai_api_key"]
        st.success("✅ AI 연결됨")
    else:
        api_key = st.text_input("OpenAI API Key", type="password")
        
    if st.button("🔄 서버 캐시 초기화 (관리자용)"):
        st.cache_data.clear() 
        keys_to_clear = ["vip_report", "dash_us", "dash_kr", "dash_cash", "dash_risk"]
        for key in keys_to_clear:
            if key in st.session_state:
                del st.session_state[key]
        st.rerun() 

# -----------------------------------------------------------------------------
# 3. 데이터 엔진
# -----------------------------------------------------------------------------
@st.cache_data(ttl=3600)
def get_yahoo_data(ticker, period="10y"):
    try:
        data = yf.Ticker(ticker).history(period=period) 
        if len(data) < 2 and ticker == "^DJI":
            data = yf.Ticker("DIA").history(period=period)
        if len(data) > 1:
            curr = data['Close'].iloc[-1]
            prev = data['Close'].iloc[-2]
            change = curr - prev
            pct_change = (change / prev) * 100
            chart_df = data[['Close']].reset_index()
            chart_df.columns = ['Date', 'Value']
            chart_df['Date'] = chart_df['Date'].dt.tz_localize(None)
            return curr, change, pct_change, chart_df
    except: pass
    return None, None, None, None

@st.cache_data(ttl=3600)
def get_fred_data(series_id, calculation_type='raw'):
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    headers = {'User-Agent': 'Mozilla/5.0'}
    for _ in range(3):
        try:
            r = requests.get(url, headers=headers, timeout=5)
            if r.status_code == 200 and not r.text.strip().startswith("<"):
                df = pd.read_csv(StringIO(r.text))
                date_col = next((c for c in df.columns if 'date' in c.lower()), None)
                if not date_col: continue
                df = df.rename(columns={date_col: 'Date'})
                df['Date'] = pd.to_datetime(df['Date'])
                df = df.set_index('Date').sort_index()
                if calculation_type == 'yoy': df['Value'] = df.iloc[:, 0].pct_change(12) * 100
                elif calculation_type == 'diff': df['Value'] = df.iloc[:, 0].diff()
                else: df['Value'] = df.iloc[:, 0]
                df = df.dropna()
                curr = df['Value'].iloc[-1]
                prev = df['Value'].iloc[-2]
                change = curr - prev
                return curr, change, 0, df.reset_index()
        except: time.sleep(1); continue
    return None, None, None, None

def get_interest_rate_hybrid():
    res = get_yahoo_data("^TNX")
    if res[0] is not None: return res
    return get_fred_data("DGS10", "raw")

def calculate_rsi(data, window=14):
    if data is None or len(data) < window: return None
    delta = data['Value'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1]

# -----------------------------------------------------------------------------
# 4. 시각화 컴포넌트
# -----------------------------------------------------------------------------

# 🚦 1. 신호등 로직 추가
def get_traffic_light_status(topic, val1, val2=None):
    try:
        if topic == "금융 시장": 
            if val1 >= 4.5 or val2 >= 1400: return "위험"
            elif val1 >= 4.0 or val2 >= 1350: return "경계"
            else: return "안정"
        elif topic == "물가 지표": 
            if val1 >= 4.0 or val2 >= 4.0: return "위험"
            elif val1 >= 3.0 or val2 >= 3.0: return "경계"
            else: return "안정"
        elif topic == "고용 지표": 
            if val2 >= 5.0: return "위험"
            elif val2 >= 4.0: return "경계"
            else: return "안정"
        elif topic == "VIX": 
            if val1 >= 30: return "위험"
            elif val1 >= 20: return "경계"
            else: return "안정"
        elif topic == "RSI": 
            if val1 >= 70 or val1 <= 30: return "위험"
            elif val1 >= 60 or val1 <= 40: return "경계"
            else: return "안정"
        elif topic == "종합": 
            if val1 >= 30 or val2 >= 70 or val2 <= 30: return "위험"
            elif val1 >= 20 or val2 >= 60 or val2 <= 40: return "경계"
            else: return "안정"
    except: pass
    return "안정"

# 🚦 2. 3구 발광 신호등 UI 추가
def draw_traffic_light_card(title, status):
    c_red, c_yel, c_grn = "#ef4444", "#f59e0b", "#22c55e"
    op_r, glow_r = ("1", f"0 0 10px {c_red}") if status == "위험" else ("0.2", "none")
    op_y, glow_y = ("1", f"0 0 10px {c_yel}") if status == "경계" else ("0.2", "none")
    op_g, glow_g = ("1", f"0 0 10px {c_grn}") if status == "안정" else ("0.2", "none")
    
    if status == "위험": bg_c, border_c, txt_c = "#fef2f2", "#fca5a5", "#dc2626"
    elif status == "경계": bg_c, border_c, txt_c = "#fffbeb", "#fcd34d", "#d97706"
    else: bg_c, border_c, txt_c = "#f0fdf4", "#86efac", "#16a34a"
    
    st.markdown(f"""
    <div style='background-color:{bg_c}; border:1px solid {border_c}; border-radius:12px; padding:12px; margin-bottom:15px; display:flex; flex-direction:column; align-items:center; box-shadow: 0 2px 4px rgba(0,0,0,0.05);'>
        <div style='font-size:13px; color:#4b5563; margin-bottom:10px; font-weight:700;'>{title}</div>
        <div style='display:flex; gap:8px; margin-bottom:8px; background-color:#374151; padding:6px 14px; border-radius:30px; border:2px solid #1f2937;'>
            <div style='width:18px; height:18px; border-radius:50%; background-color:{c_red}; opacity:{op_r}; box-shadow:{glow_r};'></div>
            <div style='width:18px; height:18px; border-radius:50%; background-color:{c_yel}; opacity:{op_y}; box-shadow:{glow_y};'></div>
            <div style='width:18px; height:18px; border-radius:50%; background-color:{c_grn}; opacity:{op_g}; box-shadow:{glow_g};'></div>
        </div>
        <div style='font-size:14px; font-weight:800; color:{txt_c};'>{status}</div>
    </div>
    """, unsafe_allow_html=True)

indicator_meta = {
    "다우존스": {"source": "Yahoo Finance", "unit": "포인트"},
    "S&P 500": {"source": "Yahoo Finance", "unit": "포인트"},
    "나스닥 100": {"source": "Yahoo Finance", "unit": "포인트"},
    "코스피": {"source": "Yahoo Finance", "unit": "포인트"},
    "코스닥": {"source": "Yahoo Finance", "unit": "포인트"},
    "미국 10년물 금리": {"source": "FRED", "unit": "%"},
    "원/달러 환율": {"source": "Yahoo Finance", "unit": "원"},
    "헤드라인 CPI": {"source": "FRED", "unit": "%"},
    "근원(Core) CPI": {"source": "FRED", "unit": "%"},
    "비농업 고용 지수": {"source": "FRED", "unit": "k"},
    "실업률": {"source": "FRED", "unit": "%"},
    "공포 지수 (VIX)": {"source": "Yahoo Finance", "unit": "포인트"},
    "RSI (S&P 500)": {"source": "Yahoo Finance", "unit": "지수"},
    "RSI (코스피)": {"source": "Yahoo Finance", "unit": "지수"}
}

def filter_data_by_period(df, period):
    if df is None or df.empty: return df
    end_date = df['Date'].max()
    if period == "1개월": start = end_date - timedelta(days=30)
    elif period == "3개월": start = end_date - timedelta(days=90)
    elif period == "6개월": start = end_date - timedelta(days=180)
    elif period == "1년": start = end_date - timedelta(days=365)
    elif period == "3년": start = end_date - timedelta(days=365*3)
    elif period == "5년": start = end_date - timedelta(days=365*5)
    elif period == "전체": start = df['Date'].min()
    else: start = end_date - timedelta(days=365)
    return df[df['Date'] >= start]

def create_chart(data, color, period="1년", height=180):
    if data is None or data.empty: return st.error("데이터 없음")
    if period in ["1개월", "3개월", "6개월"]:
        x_format = '%m/%d'; tick_cnt = 5
    else:
        x_format = '%y.%m'; tick_cnt = 6
    chart = alt.Chart(data).mark_line(color=color, strokeWidth=2).encode(
        x=alt.X('Date:T', axis=alt.Axis(format=x_format, title=None, grid=False, tickCount=tick_cnt)),
        y=alt.Y('Value:Q', scale=alt.Scale(zero=False), axis=alt.Axis(title=None)),
        tooltip=['Date:T', alt.Tooltip('Value', format=',.2f')]
    ).properties(height=height).interactive()
    return st.altair_chart(chart, use_container_width=True)

def styled_metric(label, value, change, pct_change, unit="", up_color="#ef4444", down_color="#3b82f6"):
    if value is None: 
        st.metric(label, "-")
        return
    if change > 0: color, bg_color, arrow, sign = up_color, f"{up_color}15", "▲", "+"
    elif change < 0: color, bg_color, arrow, sign = down_color, f"{down_color}15", "▼", ""
    else: color, bg_color, arrow, sign = "#6b7280", "#f3f4f6", "-", ""
    
    st.markdown(f"""
    <div style="display: flex; flex-direction: column;">
        <div style="font-size: 13px; font-weight: 600; color: #6b7280; margin-bottom: 4px;">{label}</div>
        <div style="font-size: 26px; font-weight: 800; color: #111827; white-space: nowrap;">
            {value:,.2f}<span style="font-size: 16px; color: #9ca3af; margin-left: 2px;">{unit}</span>
        </div>
        <div style="margin-top: 6px;">
            <span style="font-size: 12px; font-weight: 700; color: {color}; background-color: {bg_color}; padding: 3px 6px; border-radius: 4px; display: inline-block;">
                {arrow} {sign}{change:,.2f} ({sign}{pct_change:.2f}%)
            </span>
        </div>
    </div>
    """, unsafe_allow_html=True)

def draw_chart_unit(label, val, chg, pct, data, color, periods, default_idx, key, up_c, down_c, unit="", use_columns=True):
    with st.container(border=True):
        # 💡 마법의 CSS: 버튼 줄바꿈 방지 + 버튼 우측 정렬(flex-end) + 맨 끝에서 살짝 띄우기(padding-right)
        st.markdown("""
        <style>
        div[data-testid="stVerticalBlockBorderWrapper"] { padding: 20px 25px !important; }
        div[role="radiogroup"] { 
            flex-wrap: wrap !important; /* 💡 nowrap을 wrap으로 변경하여 좁을 때 줄바꿈 허용! */
            gap: 5px 8px !important; /* 💡 줄이 바뀌었을 때 위아래 간격(5px)을 추가로 줌 */
            justify-content: flex-end !important; /* 버튼 우측 밀기 */
            padding-right: 8px !important; /* 너무 끝에 붙지 않게 살짝 띄움 */
        }
        div[role="radiogroup"] label { white-space: nowrap !important; margin-right: 5px !important; }
        div[role="radiogroup"] p { font-size: 13px !important; }
        </style>
        """, unsafe_allow_html=True)

        if use_columns:
            c1, c2 = st.columns([1.5, 1.5])
            with c1: styled_metric(label, val, chg, pct, unit, up_c, down_c)
            with c2: 
                st.markdown('<div style="height: 10px;"></div>', unsafe_allow_html=True)
                selected_period = st.radio("기간", periods, index=default_idx, key=key, horizontal=True, label_visibility="collapsed")
        else:
            # 💡 미국 3대 지수도 위아래로 쌓지 않고 무조건 가로(좌-우) 1줄 배치로 양식 통일! (비율만 1.2 : 1.8로 맞춰줌)
            c1, c2 = st.columns([1.2, 1.8])
            with c1: styled_metric(label, val, chg, pct, unit, up_c, down_c)
            with c2: 
                st.markdown('<div style="height: 10px;"></div>', unsafe_allow_html=True)
                selected_period = st.radio("기간", periods, index=default_idx, key=key, horizontal=True, label_visibility="collapsed")
        
        meta = indicator_meta.get(label) 
        if meta:
            today_str = datetime.now().strftime("%Y-%m-%d")
            # 💡 메타데이터가 기간 버튼 밑, 차트 위로 겹침 없이 한 줄로 쫙 펴집니다!
            st.markdown(f"<div style='text-align: right; font-size: 11px; color: #9ca3af; margin-top: 15px; margin-bottom: 10px; white-space: nowrap;'>출처: {meta['source']} &nbsp;|&nbsp; 기준일: {today_str} &nbsp;|&nbsp; 단위: {meta['unit']}</div>", unsafe_allow_html=True)
        else:
            st.markdown('<div style="margin-top: 15px;"></div>', unsafe_allow_html=True)
            
        filtered_data = filter_data_by_period(data, selected_period)
        create_chart(filtered_data, color, period=selected_period, height=120)

def draw_gauge_chart(title, value, min_val, max_val, thresholds, inverse=False):
    steps = []
    bar_color = "black"
    if "공포" in title: 
        steps = [{'range': [0, 20], 'color': "#dcfce7"}, {'range': [20, 30], 'color': "#fef9c3"}, {'range': [30, 100], 'color': "#fee2e2"}]
        if value < 20: bar_color = "#16a34a"
        elif value < 30: bar_color = "#ca8a04"
        else: bar_color = "#dc2626"
    elif "RSI" in title:
        steps = [{'range': [0, 30], 'color': "#dcfce7"}, {'range': [30, 70], 'color': "#f3f4f6"}, {'range': [70, 100], 'color': "#fee2e2"}]
        if value < 30: bar_color = "#16a34a"
        elif value > 70: bar_color = "#dc2626"
        else: bar_color = "#4b5563"
        
    meta = indicator_meta.get(title)
    if meta:
        today_str = datetime.now().strftime("%Y-%m-%d")
        st.markdown(f"<div style='position: relative; width: 100%; height: 0px; z-index: 99; pointer-events: none;'><div style='position: absolute; top: -5px; right: 0px; text-align: right; font-size: 11px; color: #9ca3af; white-space: nowrap;'>출처: {meta['source']} &nbsp;|&nbsp; 기준일: {today_str} &nbsp;|&nbsp; 단위: {meta['unit']}</div></div>", unsafe_allow_html=True)
        
    fig = go.Figure(go.Indicator(
        mode = "gauge+number", value = value,
        title = {'text': title, 'font': {'size': 18, 'color': "#374151"}},
        gauge = {'axis': {'range': [min_val, max_val]}, 'bar': {'color': bar_color}, 'steps': steps}
    ))
    fig.update_layout(height=250, margin=dict(l=20, r=20, t=50, b=20), paper_bgcolor='rgba(0,0,0,0)', font={'family': "Pretendard"})
    st.plotly_chart(fig, use_container_width=True)

# -----------------------------------------------------------------------------
# 5. AI 분석 엔진
# -----------------------------------------------------------------------------
def deduct_user_call():
    """DB(구글 시트)에서 사용자의 횟수를 1회 차감하는 함수"""
    conn = st.connection("gsheets", type=GSheetsConnection)
    df = conn.read(worksheet="Users", ttl=0)
    user_email = st.session_state.user_email
    if user_email in df['Email'].values:
        user_idx = df.index[df['Email'] == user_email].tolist()[0]
        current_calls = int(df.at[user_idx, 'Remaining_Calls'])
        if current_calls > 0:
            df.at[user_idx, 'Remaining_Calls'] = current_calls - 1
            conn.update(worksheet="Users", data=df)
            
def analyze_market_ai(topic, data_summary):
    if not api_key: return "API Key 필요", "설정 탭에서 API Key를 입력해주세요."
    client = openai.OpenAI(api_key=api_key)
    
    prompt = f"""당신은 월스트리트 탑클래스 펀드매니저입니다.
주제: {topic}
데이터: {data_summary}

[중요 지침]
1. 이모지(아이콘)와 볼드체(**)를 절대 사용하지 마세요. 오직 텍스트만 사용하세요.
2. 각 항목은 정확히 2문장으로만 아주 간결하게 작성하세요.
3. 아래의 대괄호 '[목차명]'을 반드시 그대로 출력하세요.
4. 모든 문장은 VIP 고객에게 브리핑하듯 반드시 친절하고 전문적인 존댓말(~입니다, ~습니다 )로 작성하세요.

[핵심 요약]
전체 상황과 투자자가 취해야 할 포지션을 딱 2문장으로 요약하세요.

[지표의 숨은 의미]
이 데이터의 의미를 일상적인 비유(체온계 등)를 들어 2문장으로 설명하세요.

[펀드매니저의 시장 해석]
현재 숫자가 주식/금리/환율에 보내는 신호를 2문장으로 분석하세요.

[주식 투자 실전 활용법]
피해야 할 섹터와 유망한 자산을 2문장으로 구체적으로 짚어주세요.

[미래 전략 제안]
앞으로 1~3개월 시나리오와 당장 취해야 할 행동을 2문장으로 제안하세요.
"""
    try:
        resp = client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": prompt}])
        return "AI 펀드매니저 리포트", resp.choices[0].message.content
    except Exception as e: return "오류 발생", str(e)
        
def draw_section_with_ai(title, chart1, chart2, key_suffix, ai_topic, ai_data):
    st.markdown(f"<div class='section-header'>{title}</div>", unsafe_allow_html=True)
    col_main, col_ai = st.columns([3, 1])
    with col_main:
        c1, c2 = st.columns(2)
        with c1: draw_chart_unit(chart1['l'], chart1['v'], chart1['c'], chart1['p'], chart1['d'], chart1['col'], chart1['prd'], 0, f"{key_suffix}_1", chart1['uc'], chart1['dc'], chart1['u'], True)
        with c2: draw_chart_unit(chart2['l'], chart2['v'], chart2['c'], chart2['p'], chart2['d'], chart2['col'], chart2['prd'], 0, f"{key_suffix}_2", chart2['uc'], chart2['dc'], chart2['u'], True)
    
    with col_ai:
        # 🚦 신호등 표시
        status = get_traffic_light_status(ai_topic, chart1['v'], chart2['v'] if chart2 else None)
        draw_traffic_light_card(f"{ai_topic} 신호등", status)
        
        if st.session_state.logged_in:
            is_analyzed = f"ai_res_{key_suffix}" in st.session_state
            btn_text = "✅ 분석 완료" if is_analyzed else f"{ai_topic} 분석"
            
            if st.button(btn_text, key=f"btn_{key_suffix}", type="primary", disabled=is_analyzed, use_container_width=True):
                if st.session_state.remaining_calls > 0:
                    with st.spinner("AI 펀드매니저가 데이터를 분석 중입니다."):
                        t_text, content = analyze_market_ai(ai_topic, ai_data)
                        
                        for emoji in ['💡', '🔍', '🎯', '🚀', '📌', '👔', '✅']:
                            content = content.replace(emoji, '')
                            
                        st.session_state.remaining_calls -= 1
                        deduct_user_call()
                        st.session_state[f"ai_res_{key_suffix}"] = (t_text, content)
                    st.rerun() 
                else: st.error("⚠️ 현재 유료 멤버십 결제 시스템을 준비 중입니다.")
            
            if is_analyzed:
                t_text, content = st.session_state[f"ai_res_{key_suffix}"]
                if '[지표의 숨은 의미]' in content:
                    summary_part = content.split('[지표의 숨은 의미]')[0]
                    summary = summary_part.replace('[핵심 요약]', '').strip()
                else:
                    summary = content[:100] + "..."
                
                st.markdown(f"<div style='background-color:#eff6ff; padding:20px 25px; border-radius:12px; border-left:5px solid #3b82f6; margin-top:10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); display:flex; flex-direction:column; justify-content:space-between;'><div style='margin-bottom:12px;'><div style='font-size:17px; color:#1d4ed8; font-weight:800; margin-bottom:10px;'>펀드매니저 핵심 요약</div><div style='font-size:16px; font-weight:700; color:#1e3a8a; line-height:1.6; word-break:keep-all;'>{summary}</div></div><div style='margin-top:12px; padding-top:12px; border-top:1px dashed #bfdbfe; font-size:13px; color:#1e40af; text-align:center; font-weight:700; line-height:1.5;'>시장 국면에 따른 신규 진입 유망 산업 정보는<br><span style='color:#ea580c; font-size:14px;'>[🔒 VIP 포트폴리오]</span>에서 상세히 제공됩니다.</div></div>", unsafe_allow_html=True)
        else:
            # 멤버십 안내 지우고 로그인 버튼만 유지
            st.link_button("AI 펀드매니저 연결", get_google_login_url(), type="primary", use_container_width=True)
            
    if st.session_state.logged_in and f"ai_res_{key_suffix}" in st.session_state:
        t_text, content = st.session_state[f"ai_res_{key_suffix}"]
        
        if '[지표의 숨은 의미]' in content:
            detail_raw = "[지표의 숨은 의미]" + content.split('[지표의 숨은 의미]')[1]
        else:
            detail_raw = content
            
        detail_html = detail_raw.replace('[지표의 숨은 의미]', "<div style='font-size:22px; font-weight:800; color:#065f46; margin-top:10px; margin-bottom:10px;'>지표의 숨은 의미</div>")
        detail_html = detail_html.replace('[펀드매니저의 시장 해석]', "<div style='font-size:22px; font-weight:800; color:#065f46; margin-top:25px; margin-bottom:10px;'>펀드매니저의 시장 해석</div>")
        detail_html = detail_html.replace('[주식 투자 실전 활용법]', "<div style='font-size:22px; font-weight:800; color:#065f46; margin-top:25px; margin-bottom:10px;'>주식 투자 실전 활용법</div>")
        detail_html = detail_html.replace('[미래 전략 제안]', "<div style='font-size:22px; font-weight:800; color:#065f46; margin-top:25px; margin-bottom:10px;'>미래 전략 제안</div>")
        
        st.markdown(f"""
        <div style='background-color:#f0fdf4; border:1px solid #bbf7d0; border-radius:12px; padding:25px; margin-top:20px; box-shadow: 0 4px 6px rgba(0,0,0,0.05);'>
            <h3 style='color:#14532d; font-size:24px; font-weight:900; margin-top:0; margin-bottom:25px; border-bottom:2px solid #bbf7d0; padding-bottom:15px;'>{t_text} (상세)</h3>
            <div style='font-size:20px; line-height:1.7; color:#14532d; word-break:keep-all;'>{detail_html}</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<hr>", unsafe_allow_html=True)
    
# -----------------------------------------------------------------------------
# 6. 메인 페이지 로직 (데이터 즉시 노출)
# -----------------------------------------------------------------------------
if menu == "주가 지수":
    st.title("글로벌 시장 지수")
    
    from datetime import datetime
    current_time = datetime.now().strftime("%Y년 %m월 %d일 %H:%M 기준")
    st.caption(f"⏱️ 실시간 데이터 업데이트: **{current_time}**")
    
    with st.spinner("데이터 로딩 중..."):
        dow_v, dow_c, dow_p, dow_d = get_yahoo_data("^DJI")
        sp_v, sp_c, sp_p, sp_d = get_yahoo_data("^GSPC")
        nas_v, nas_c, nas_p, nas_d = get_yahoo_data("^IXIC")
        kospi_v, kospi_c, kospi_p, kospi_d = get_yahoo_data("^KS11")
        kosdaq_v, kosdaq_c, kosdaq_p, kosdaq_d = get_yahoo_data("^KQ11")

    st.markdown("<div class='section-header'>미국 3대 지수 (US Market)</div>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1: draw_chart_unit("다우존스", dow_v, dow_c, dow_p, dow_d, "#10b981", ["1개월", "3개월", "1년", "전체"], 0, "dow", "#10b981", "#ef4444", "", False)
    with c2: draw_chart_unit("S&P 500", sp_v, sp_c, sp_p, sp_d, "#10b981", ["1개월", "3개월", "1년", "전체"], 0, "sp500", "#10b981", "#ef4444", "", False)
    with c3: draw_chart_unit("나스닥 100", nas_v, nas_c, nas_p, nas_d, "#10b981", ["1개월", "3개월", "1년", "전체"], 0, "nasdaq", "#10b981", "#ef4444", "", False)
    
    st.markdown("<div class='section-header'>국내 증시 (KR Market)</div>", unsafe_allow_html=True)
    c4, c5 = st.columns(2)
    with c4: draw_chart_unit("코스피", kospi_v, kospi_c, kospi_p, kospi_d, "#ef4444", ["1개월", "3개월", "6개월", "1년"], 0, "kospi", "#ef4444", "#3b82f6", "", True)
    with c5: draw_chart_unit("코스닥", kosdaq_v, kosdaq_c, kosdaq_p, kosdaq_d, "#ef4444", ["1개월", "3개월", "6개월", "1년"], 0, "kosdaq", "#ef4444", "#3b82f6", "", True)

elif menu == "투자 지표":
    st.title("투자 지표 (Economic Indicators)")
    with st.spinner('로딩 중...'):
        rate_val, rate_chg, rate_pct, rate_data = get_interest_rate_hybrid()
        exch_val, exch_chg, exch_pct, exch_data = get_yahoo_data("KRW=X", "10y")
        cpi_val, cpi_chg, cpi_pct, cpi_data = get_fred_data("CPIAUCSL", "yoy")
        core_val, core_chg, core_pct, core_data = get_fred_data("CPILFESL", "yoy")
        job_val, job_chg, job_pct, job_data = get_fred_data("PAYEMS", "diff")
        unemp_val, unemp_chg, unemp_pct, unemp_data = get_fred_data("UNRATE", "raw")

    draw_section_with_ai("금융 시장 (금리 & 환율)", {'l': "미국 10년물 금리", 'v': rate_val, 'c': rate_chg, 'p': rate_pct, 'd': rate_data, 'col': "#f59e0b", 'prd': ["1개월", "3개월", "1년"], 'idx': 0, 'uc': "#f59e0b", 'dc': "#3b82f6", 'u': "%"}, {'l': "원/달러 환율", 'v': exch_val, 'c': exch_chg, 'p': exch_pct, 'd': exch_data, 'col': "#10b981", 'prd': ["1개월", "3개월", "1년"], 'idx': 0, 'uc': "#10b981", 'dc': "#3b82f6", 'u': "원"}, "finance", "금융 시장", f"금리: {rate_val}%, 환율: {exch_val}원")
    draw_section_with_ai("물가 지표 (인플레이션)", {'l': "헤드라인 CPI", 'v': cpi_val, 'c': cpi_chg, 'p': cpi_pct, 'd': cpi_data, 'col': "#ef4444", 'prd': ["6개월", "1년", "3년"], 'idx': 0, 'uc': "#ef4444", 'dc': "#3b82f6", 'u': "%"}, {'l': "근원(Core) CPI", 'v': core_val, 'c': core_chg, 'p': core_pct, 'd': core_data, 'col': "#ef4444", 'prd': ["6개월", "1년", "3년"], 'idx': 0, 'uc': "#ef4444", 'dc': "#3b82f6", 'u': "%"}, "inflation", "물가 지표", f"헤드라인CPI: {cpi_val}%, 근원CPI: {core_val}%")
    draw_section_with_ai("고용 지표 (경기 & 고용)", {'l': "비농업 고용 지수", 'v': job_val, 'c': job_chg, 'p': job_pct, 'd': job_data, 'col': "#3b82f6", 'prd': ["6개월", "1년", "3년"], 'idx': 0, 'uc': "#3b82f6", 'dc': "#ef4444", 'u': "k"}, {'l': "실업률", 'v': unemp_val, 'c': unemp_chg, 'p': unemp_pct, 'd': unemp_data, 'col': "#10b981", 'prd': ["6개월", "1년", "3년"], 'idx': 0, 'uc': "#10b981", 'dc': "#3b82f6", 'u': "%"}, "employment", "고용 지표", f"비농업: {job_val}k, 실업률: {unemp_val}%")

elif menu == "시장 심리":
    st.title("시장 심리 (Market Sentiment)")
    st.markdown('<div class="info-box"><strong>VIX와 RSI</strong>를 통해 시장의 공포와 과열 정도를 파악합니다.</div>', unsafe_allow_html=True)
    with st.spinner("데이터 분석 중..."):
        vix_curr, _, _, _ = get_yahoo_data("^VIX")
        _, _, _, sp_data = get_yahoo_data("^GSPC", "6mo")
        _, _, _, ks_data = get_yahoo_data("^KS11", "6mo")
        rsi_sp = calculate_rsi(sp_data); rsi_ks = calculate_rsi(ks_data)
    g1, g2, g3 = st.columns(3)
    with g1: draw_gauge_chart("공포 지수 (VIX)", vix_curr, 0, 50, [20, 30])
    with g2: draw_gauge_chart("RSI (S&P 500)", rsi_sp, 0, 100, [30, 70])
    with g3: draw_gauge_chart("RSI (코스피)", rsi_ks, 0, 100, [30, 70])
    
    # 🚦 3. 시장 심리 하단 신호등 3개 가로 배치
    st.markdown("<br>", unsafe_allow_html=True) 
    t1, t2, t3 = st.columns(3)
    with t1: draw_traffic_light_card("VIX 신호등", get_traffic_light_status("VIX", vix_curr))
    with t2: draw_traffic_light_card("S&P 500 신호등", get_traffic_light_status("RSI", rsi_sp))
    with t3: draw_traffic_light_card("코스 신호등", get_traffic_light_status("종합", vix_curr, rsi_sp))
    
    st.markdown("<div class='section-header'>AI 심리 분석</div>", unsafe_allow_html=True)
    if st.session_state.logged_in:
        is_analyzed_sentiment = "ai_res_sentiment" in st.session_state
        btn_text_sentiment = "✅ 분석 완료" if is_analyzed_sentiment else "현재 시장 심리 분석"
        
        if st.button(btn_text_sentiment, type="primary", disabled=is_analyzed_sentiment, use_container_width=True):
            if st.session_state.remaining_calls > 0:
                with st.spinner("AI 펀드매니저가 데이터를 분석 중입니다."):
                    t_text, content = analyze_market_ai("현재 시장 심리", f"VIX: {vix_curr}, S&P RSI: {rsi_sp}, 코스피 RSI: {rsi_ks}")
                    st.session_state.remaining_calls -= 1
                    deduct_user_call()
                    st.session_state["ai_res_sentiment"] = (t_text, content) 
                st.rerun()
            else: st.error("⚠️ 현재 유료 멤버십 결제 시스템을 준비 중입니다. (오픈 예정)")
        
        if is_analyzed_sentiment:
            t_text, content = st.session_state["ai_res_sentiment"]
            st.markdown(f"<div class='ai-box'><div class='ai-title'>👔 {t_text}</div><div class='ai-text'>{content}</div></div>", unsafe_allow_html=True)
    else:
        # 멤버십 안내 지우고 로그인 버튼만 유지
        st.link_button("AI 펀드매니저 연결", get_google_login_url(), type="primary", use_container_width=True)

elif menu == "시장 지도":
    st.title("시장 지도 (Market Map)")
    
    from datetime import datetime, date
    import pandas as pd
    import yfinance as yf
    import plotly.express as px
    import altair as alt
    
    current_time = datetime.now().strftime("%Y년 %m월 %d일 %H:%M 기준")
    st.caption(f"⏱️ 실시간 데이터 업데이트: **{current_time}**")
    
    today_str = date.today().strftime('%Y-%m-%d')
    
    sectors = {'XLK': '기술', 'XLV': '헬스케어', 'XLF': '금융', 'XLY': '임의소비재', 'XLP': '필수소비재', 'XLE': '에너지', 'XLI': '산업재', 'XLU': '유틸리티', 'XLRE': '부동산', 'XLB': '소재', 'XLC': '통신'}
    rows = []
    
    with st.spinner("섹터별 데이터를 수집 중입니다..."):
        for t, n in sectors.items():
            try:
                d = yf.Ticker(t).history(period="2d") 
                if len(d) >= 2:
                    c = (d['Close'].iloc[-1] - d['Close'].iloc[-2]) / d['Close'].iloc[-2] * 100
                    rows.append({'Sector': n, 'Change': c})
            except Exception as e:
                pass
            
    if rows:
        df_sector = pd.DataFrame(rows)
        
        st.markdown(f'<div class="info-box" style="margin-bottom:15px; font-weight:bold; color:#1e3a8a;">막대그래프로 보는 섹터별 등락 순위</div>', unsafe_allow_html=True)
        
        df_sector['Color'] = df_sector['Change'].apply(lambda x: '#22c55e' if x > 0 else '#ef4444') 
        
        bar_chart = alt.Chart(df_sector).mark_bar(cornerRadiusEnd=4).encode(
            x=alt.X('Change', title='등락률 (%)'),
            y=alt.Y('Sector', sort='-x', title=None, axis=alt.Axis(labelPadding=15)), 
            color=alt.Color('Color', scale=None),
            tooltip=['Sector', alt.Tooltip('Change', format='.2f', title='등락률 (%)')]
        ).properties(
            height=380, 
            padding={'top': 25, 'bottom': 20, 'left': 10, 'right': 30} 
        )
        
        st.altair_chart(bar_chart, use_container_width=True)
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        st.markdown(f'<div class="info-box" style="margin-bottom:15px; font-weight:bold; color:#1e3a8a;">한눈에 보는 시장 지도 </div>', unsafe_allow_html=True)
        
        df_sector['Absolute_Change'] = df_sector['Change'].abs() 
        df_sector['Label'] = df_sector['Change'].apply(lambda x: f"+{x:.2f}%" if x > 0 else f"{x:.2f}%")
        
        max_change = df_sector['Absolute_Change'].max()
        
        fig = px.treemap(
            df_sector, 
            path=['Sector'], 
            values='Absolute_Change', 
            color='Change', 
            color_continuous_scale=[[0, '#dc2626'], [0.5, '#4b5563'], [1, '#16a34a']], 
            range_color=[-max_change, max_change], 
            custom_data=['Label'] 
        )
        
        fig.update_traces(
            textposition="middle center",
            textinfo="label+text",
            textfont=dict(color="white"), 
            texttemplate="<span style='font-size:24px; font-weight:900;'>%{label}</span><br><br><span style='font-size:20px; font-weight:700;'>%{customdata[0]}</span>",
            hovertemplate="<b>%{label}</b><br>등락률: %{customdata[0]}<extra></extra>", 
            marker=dict(line=dict(width=3, color='#ffffff')), 
            tiling=dict(pad=3),
            root_color="rgba(0,0,0,0)" 
        )
        
        fig.update_layout(
            margin=dict(t=0, l=0, r=0, b=0), 
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            height=600 
        )
        
        fig.update_layout(coloraxis_showscale=False)
        
        st.plotly_chart(fig, use_container_width=True)
        
        st.markdown("<div style='font-size:14.5px; color:#6b7280; text-align:center; margin-top:5px; margin-bottom:20px; word-break:keep-all;'>💡 <b>블록의 크기</b>는 해당 섹터의 <b>변동성(등락폭의 절대값)</b>을 의미하며, 크기가 클수록 시장에서 자금 이동이 활발했던 섹터입니다.</div>", unsafe_allow_html=True)
        
    else:
        st.error("데이터를 수집하지 못했습니다. 잠시 후 다시 시도해 주세요.")

elif menu == "주요 일정":
    st.title("주요 일정 (Key Schedule)")
    fomc = [date(2026, 1, 28), date(2026, 3, 18), date(2026, 4, 29), date(2026, 6, 17), date(2026, 7, 29), date(2026, 9, 16), date(2026, 10, 28), date(2026, 12, 9)]
    today = date.today()
    next_f = next((d for d in fomc if d >= today), None)
    if next_f:
        st.markdown(f'<div class="d-day-container"><div class="d-day-title">Next FOMC Meeting</div><div class="d-day-count">D-{(next_f-today).days}</div><div class="d-day-date">{next_f.strftime("%Y년 %m월 %d일")}</div></div>', unsafe_allow_html=True)
    
    st.markdown("<div class='section-header'>네 마녀의 날 (Quadruple Witching Day)</div>", unsafe_allow_html=True)
    witching = [date(2026, 3, 20), date(2026, 6, 19), date(2026, 9, 18), date(2026, 12, 18)]
    w_cols = st.columns(4)
    for i, d in enumerate(witching):
        with w_cols[i]:
            with st.container(border=True): st.write(f"**{d.month}월 만기일**\n\n{d}")
            
    st.markdown("<div class='section-header'>주요 휴장일 (미국 증시)</div>", unsafe_allow_html=True)
    holidays = {date(2026, 4, 3): "성금요일", date(2026, 5, 25): "메모리얼 데이", date(2026, 6, 19): "준틴스", date(2026, 7, 3): "독립기념일", date(2026, 9, 7): "노동절", date(2026, 11, 26): "추수감사절", date(2026, 12, 25): "크리스마스"}
    h_cols = st.columns(3)
    upcoming = {d: n for d, n in holidays.items() if d >= today}
    for i, (d, n) in enumerate(list(upcoming.items())[:3]):
        with h_cols[i]:
            with st.container(border=True): st.write(f"**{n}**\n\n{d}")
                
elif menu == "🔒 VIP 포트폴리오":
    st.title("🔒 VIP 시크릿 매크로 리포트")
    
    if st.session_state.get('plan', 'Free') == 'Pro':
        st.success("👑 VIP 멤버십 인증 완료! 실시간 핵심 투자 전략을 확인하세요.")
        
        is_vip_analyzed = "vip_report" in st.session_state
        btn_text_vip = "✅ 실시간 VIP 리포트 생성 완료" if is_vip_analyzed else "🚀 실시간 VIP 시크릿 리포트 생성하기"
        
        if st.button(btn_text_vip, type="primary", disabled=is_vip_analyzed, use_container_width=True):
            with st.spinner("AI 펀드매니저가 거시경제 지표를 분석하여 대시보드와 리포트를 생성 중입니다..."):
                if not api_key:
                    st.error("설정 탭에서 API Key를 입력해주세요.")
                else:
                    client = openai.OpenAI(api_key=api_key)
                    
                    vip_prompt = """당신은 월스트리트의 전설적인 투자자 '버나드 바루크(Bernard Baruch)'의 '세계경제지표의 비밀' 논리를 완벽하게 구사하는 탑클래스 펀드매니저입니다. VIP 고객을 위한 현재 시점의 실시간 심층 투자 전략 리포트를 작성하세요.
                    
                    [데이터 및 방향성 제약 조건]
                    - '공시' 및 '증시 심리'에 대한 내용은 철저히 배제하세요.
                    - '외환', '금리', '전쟁(지정학적 리스크)' 이 3가지 키워드를 반드시 포함하여 시장을 분석하세요.
                    - 개별 특정 종목(티커)은 어떠한 경우에도 절대 언급하지 마세요. (특히 GST 등)
                    - 영어나 한자 혼용을 최소화하고, 목차에서 영어를 제거하세요.
                    - 💡 문장마다 억지로 줄바꿈하지 말고, 의미가 이어지는 문단 단위로만 자연스럽게 줄바꿈하세요.

                    [1. 대시보드 데이터 추출 (가장 먼저 작성)]
                    리포트의 맨 첫 줄은 무조건 아래 괄호 형식에 맞춰 현재 시장 상황을 요약한 데이터를 한 줄로 출력하세요. (파이썬이 인식할 비밀 코드입니다)
                    형식: [미국국면]|[한국국면]|[권장현금비중]|[핵심모니터링지표]
                    출력 예시: [경기 확장기]|[회복 지연기]|[30% 이상 확보]|[CPI & 고용보고서]

                    [2. 리포트 본문 구성] (위의 데이터 줄 바로 다음 줄부터 아래 대괄호 [] 목차를 정확히 출력하세요)
                    [1. 거시경제 분석]
                    현재 글로벌 경기 국면(확장, 둔화, 침체, 회복)을 결정지은 핵심 경제 지표(GDP, 고용, 물가 등)와 글로벌 자금 흐름을 통찰력 있게 분석하세요.
                    
                    [2. 리스크 방어 전략]
                    가장 우려되는 하락 시나리오와 이를 방어하기 위한 포트폴리오 관리법을 제시하세요.
                    
                    [3. 투자 전략 제언]
                    향후 1~3개월의 거시적 시나리오와 당장 취해야 할 포지션을 제안하세요.
                    
                    [4. 신규 진입 유망 섹터]
                    현 시점에서 수급이 누적되어 신규 진입하기 좋은 산업군을 2~3개 추천하고 논리적으로 설명하세요. (각 섹터 이름 양옆에는 <b> 와 </b> 태그를 붙여서 폰트를 굵게 강조하세요.)
                    """
                    try:
                        resp = client.chat.completions.create(
                            model="gpt-4o", 
                            messages=[{"role": "user", "content": vip_prompt}],
                            temperature=0.1 
                        )
                        raw_content = resp.choices[0].message.content.strip()
                        
                        lines = raw_content.split('\n')
                        first_line = lines[0]
                        
                        if '|' in first_line and '[' in first_line:
                            import re
                            parsed = re.findall(r'\[(.*?)\]', first_line)
                            if len(parsed) >= 4:
                                st.session_state["dash_us"] = parsed[0]
                                st.session_state["dash_kr"] = parsed[1]
                                st.session_state["dash_cash"] = parsed[2]
                                st.session_state["dash_risk"] = parsed[3]
                                st.session_state["vip_report"] = '\n'.join(lines[1:]).strip()
                            else:
                                st.session_state["vip_report"] = raw_content
                        else:
                            st.session_state["vip_report"] = raw_content
                            
                        st.rerun() 
                    except Exception as e:
                        st.error(f"오류 발생: {str(e)}")
        
        st.markdown("<br>", unsafe_allow_html=True) 
        
        dash_us = st.session_state.get("dash_us", "대기 중")
        dash_kr = st.session_state.get("dash_kr", "대기 중")
        dash_cash = st.session_state.get("dash_cash", "-")
        dash_risk = st.session_state.get("dash_risk", "버튼을 눌러주세요")
        
        st.markdown("<div class='section-header'>🧭 실시간 매크로 기상도 & 비중 가이드</div>", unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown(f"""
            <div style='background-color:#f0fdf4; border:1px solid #bbf7d0; padding:15px; border-radius:10px; text-align:center; height:125px; display:flex; flex-direction:column; justify-content:center;'>
                <div style='font-size:14px; color:#166534; margin-bottom:10px;'>현재 글로벌 경기 국면</div>
                <div style='display:flex; justify-content:space-evenly; align-items:center;'>
                    <div>
                        <div style='font-size:12px; color:#15803d;'>🇺🇸 미국</div>
                        <div style='font-size:18px; font-weight:800; color:#14532d;'>{dash_us}</div>
                    </div>
                    <div style='width:1px; height:45px; background-color:#bbf7d0;'></div>
                    <div>
                        <div style='font-size:12px; color:#15803d;'>🇰🇷 한국</div>
                        <div style='font-size:18px; font-weight:800; color:#14532d;'>{dash_kr}</div>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)
        with c2:
            st.markdown(f"<div style='background-color:#eff6ff; border:1px solid #bfdbfe; padding:15px; border-radius:10px; text-align:center; height:125px; display:flex; flex-direction:column; justify-content:center;'><div style='font-size:14px; color:#1e40af;'>권장 현금 비중</div><div style='font-size:22px; font-weight:800; color:#1e3a8a; margin-top:5px;'>{dash_cash}</div></div>", unsafe_allow_html=True)
        with c3:
            st.markdown(f"<div style='background-color:#fefce8; border:1px solid #fde047; padding:15px; border-radius:10px; text-align:center; height:125px; display:flex; flex-direction:column; justify-content:center;'><div style='font-size:14px; color:#854d0e;'>실시간 핵심 모니터링 지표</div><div style='font-size:20px; font-weight:800; color:#713f12; margin-top:5px; word-break:keep-all;'>{dash_risk}</div></div>", unsafe_allow_html=True)
        
        if is_vip_analyzed:
            report_content = st.session_state["vip_report"]
            
            import re
            report_content = re.sub(r'\n{3,}', '\n\n', report_content)
            
            html_content = report_content.replace('[1. 거시경제 분석]\n', "<div style='font-size:24px; font-weight:900; color:#111827; margin-top:20px; margin-bottom:6px;'>1. 거시경제 분석</div>")
            html_content = html_content.replace('[1. 거시경제 분석]', "<div style='font-size:24px; font-weight:900; color:#111827; margin-top:20px; margin-bottom:6px;'>1. 거시경제 분석</div>")
            html_content = html_content.replace('[2. 리스크 방어 전략]\n', "<div style='font-size:24px; font-weight:900; color:#111827; margin-top:35px; margin-bottom:6px;'>2. 리스크 방어 전략</div>")
            html_content = html_content.replace('[2. 리스크 방어 전략]', "<div style='font-size:24px; font-weight:900; color:#111827; margin-top:35px; margin-bottom:6px;'>2. 리스크 방어 전략</div>")
            html_content = html_content.replace('[3. 투자 전략 제언]\n', "<div style='font-size:24px; font-weight:900; color:#111827; margin-top:35px; margin-bottom:6px;'>3. 투자 전략 제언</div>")
            html_content = html_content.replace('[3. 투자 전략 제언]', "<div style='font-size:24px; font-weight:900; color:#111827; margin-top:35px; margin-bottom:6px;'>3. 투자 전략 제언</div>")
            html_content = html_content.replace('[4. 신규 진입 유망 섹터]\n', "<div style='font-size:24px; font-weight:900; color:#111827; margin-top:35px; margin-bottom:6px;'>4. 신규 진입 유망 섹터</div>")
            html_content = html_content.replace('[4. 신규 진입 유망 섹터]', "<div style='font-size:24px; font-weight:900; color:#111827; margin-top:35px; margin-bottom:6px;'>4. 신규 진입 유망 섹터</div>")
            
            html_content = html_content.replace('\n\n', "<div style='height:12px;'></div>") 
            html_content = html_content.replace('\n', '<br>')
            
            from datetime import datetime
            current_time = datetime.now().strftime("%Y년 %m월 %d일 %H:%M 기준")

            st.markdown(f"""
            <div style='background-color:#ffffff; border:2px solid #111827; border-radius:12px; padding:45px; margin-top:20px; box-shadow: 0 4px 10px rgba(0,0,0,0.08);'>
                <div style='display:flex; justify-content:space-between; align-items:baseline; border-bottom:2px solid #e5e7eb; padding-bottom:15px; margin-bottom:25px;'>
                    <h3 style='color:#111827; margin:0; font-size:28px; font-weight:900;'>[실시간 VIP] 매크로 심층 리포트</h3>
                    <span style='color:#6b7280; font-size:14px; font-weight:600;'>⏱️ {current_time}</span>
                </div>
                <div style='font-size:17px; line-height:1.8; color:#374151; word-break:keep-all;'>
                    {html_content}
                </div>
            </div>
            """, unsafe_allow_html=True)
            
    else:
        st.markdown("<div class='section-header'>🧭 실시간 매크로 기상도 & 비중 가이드</div>", unsafe_allow_html=True)
        st.markdown("""
        <div style='display:flex; gap:15px; filter: blur(6px); user-select: none; margin-bottom:30px;'>
            <div style='flex:1; background-color:#f0fdf4; border:1px solid #bbf7d0; padding:15px; border-radius:10px; text-align:center; height:125px; display:flex; flex-direction:column; justify-content:center;'>
                <div style='font-size:14px; margin-bottom:10px;'>현재 글로벌 경기 국면</div>
                <div style='display:flex; justify-content:space-evenly; align-items:center;'>
                    <div>
                        <div style='font-size:12px;'>🇺🇸 미국</div>
                        <div style='font-size:18px; font-weight:800;'>경기 확장기</div>
                    </div>
                    <div style='width:1px; height:45px; background-color:#bbf7d0;'></div>
                    <div>
                        <div style='font-size:12px;'>🇰🇷 한국</div>
                        <div style='font-size:18px; font-weight:800;'>회복 지연기</div>
                    </div>
                </div>
            </div>
            <div style='flex:1; background-color:#eff6ff; border:1px solid #bfdbfe; padding:15px; border-radius:10px; text-align:center; height:125px; display:flex; flex-direction:column; justify-content:center;'><div style='font-size:14px;'>권장 현금 비중</div><div style='font-size:22px; font-weight:800; margin-top:5px;'>30% 이상 확보</div></div>
            <div style='flex:1; background-color:#fefce8; border:1px solid #fde047; padding:15px; border-radius:10px; text-align:center; height:125px; display:flex; flex-direction:column; justify-content:center;'><div style='font-size:14px;'>실시간 핵심 모니터링 지표</div><div style='font-size:22px; font-weight:800; margin-top:5px;'>CPI & 고용보고서</div></div>
        </div>
        """, unsafe_allow_html=True)
        
        from datetime import datetime
        current_time = datetime.now().strftime("%Y년 %m월 %d일 %H:%M 기준")

        st.markdown("<div class='section-header'>🌎 실시간 탑다운 전략 리포트</div>", unsafe_allow_html=True)
        st.markdown(f"""
        <div style='background-color:#f9fafb; border:1px solid #e5e7eb; border-radius:12px; padding:40px; text-align:left; filter: blur(5px); user-select: none;'>
            <div style='display:flex; justify-content:space-between; align-items:baseline; border-bottom:2px solid #e5e7eb; padding-bottom:15px; margin-bottom:25px;'>
                <h3 style='color:#111827; margin:0; font-size:28px; font-weight:900;'>[실시간 VIP] 매크로 심층 리포트</h3>
                <span style='color:#6b7280; font-size:14px; font-weight:600;'>⏱️ {current_time}</span>
            </div>
            <p style='color:#374151; font-size:17px; line-height:1.8;'><b>1. 거시경제 분석:</b> 현재 글로벌 경제 환경은 주요 외환 시장의 변동성과 금리의 등락을 중심으로...</p>
            <p style='color:#374151; font-size:17px; line-height:1.8;'><b>2. 리스크 방어 전략:</b> 가장 우려되는 하락 시나리오는 인플레이션 재점화로 인한...</p>
            <p style='color:#374151; font-size:17px; line-height:1.8;'><b>3. 신규 진입 유망 섹터:</b> 다양한 산업군에서 수급이 누적된 압도적 주도주 3가지는...</p>
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown("""
        <div style='background-color:#fffbeb; border:2px solid #fde68a; border-radius:12px; padding:30px; text-align:center; margin-top:-250px; position:relative; z-index:10;'>
            <div style='font-size:40px; margin-bottom:10px;'>🔒</div>
            <h3 style='color:#b45309; margin-top:0;'>Pro 멤버십 전용 프리미엄 리포트</h3>
            <p style='color:#92400e; font-size:16px;'>실시간 거시 경제(외환/금리/전쟁) 기반의 탑다운 전략과 리스크 방어, 그리고 다양한 산업군에서 발굴한 신규 진입 유망 섹터를 확인하세요.</p>
            <p style='color:#9ca3af; font-size:14px; margin-top:15px;'>👉 왼쪽 사이드바에서 멤버십을 업그레이드할 수 있습니다.</p>
        </div>
        """, unsafe_allow_html=True)
        
# -----------------------------------------------------------------------------
# 7. 공통 푸터 (투자 면책 조항)
# -----------------------------------------------------------------------------
st.markdown("""
<div class="footer-disclaimer">
    <strong>[면책 조항]</strong> 본 웹사이트에서 제공하는 데이터 및 AI 분석 정보는 투자 참고용이며 최종 판단과 책임은 투자자 본인에게 있습니다.
</div>
""", unsafe_allow_html=True)











