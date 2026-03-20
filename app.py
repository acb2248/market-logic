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
import concurrent.futures

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
@st.cache_data(ttl=300)
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

# 💡 이 줄을 추가하세요! (86400초 = 24시간 동안 안 바뀜)
@st.cache_data(ttl=86400) 
def get_fred_data(series_id, calculation_type='raw'):
    # 금고에서 키를 꺼낼 수 없는 상황이면 에러 없이 안전하게 종료
    if "FRED_API_KEY" not in st.secrets:
        return None, None, None, None

    api_key = st.secrets["FRED_API_KEY"]
    url = f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}&api_key={api_key}&file_type=json"
    
    for _ in range(3):
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                data = r.json()
                observations = data.get('observations', [])
                if not observations: continue
                
                df = pd.DataFrame(observations)
                df = df.rename(columns={'date': 'Date', 'value': 'Value'})
                df['Date'] = pd.to_datetime(df['Date'])
                df = df.set_index('Date').sort_index()
                
                # 💡 핵심 수정 파트: FRED API의 미세한 찌꺼기를 완벽히 걸러내고 순수 숫자만 추출!
                # 1. 값이 '.' 이거나 빈칸인 것을 진짜 NaN(결측치)으로 바꿉니다.
                df['Value'] = df['Value'].replace('.', pd.NA) 
                df = df.dropna(subset=['Value']) # 빈칸 날리기
                # 2. 안전하게 숫자로 변환합니다.
                df['Value'] = pd.to_numeric(df['Value'], errors='coerce')
                df = df.dropna(subset=['Value']) # 변환 실패한 찌꺼기 한 번 더 날리기
                
                if df.empty: continue # 남은 데이터가 없으면 패스
                
                if calculation_type == 'yoy': 
                    df['Value'] = df['Value'].pct_change(12) * 100
                elif calculation_type == 'diff': 
                    df['Value'] = df['Value'].diff()
                    
                df = df.dropna(subset=['Value']) # 계산 후 생긴 앞쪽 빈칸 날리기
                
                if len(df) < 2: continue 
                
                curr = float(df['Value'].iloc[-1]) # 💡 확실하게 소수점 숫자로 못 박기
                prev = float(df['Value'].iloc[-2])
                change = curr - prev
                
                # 💡 0으로 고정되어 있던 부분에 정확한 퍼센트(%) 계산식을 추가했습니다!
                pct_change = (change / prev) * 100 if prev != 0 else 0
                
                return curr, change, pct_change, df.reset_index()
        except: 
            time.sleep(0.5)
            continue
            
    return None, None, None, None

# 💡 이 줄을 추가하세요! (금리도 하루에 한 번만 갱신)
@st.cache_data(ttl=86400) 
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
    
    # 원본 데이터를 보호하기 위해 복사본을 만듭니다.
    chart_data = data.copy()
    
    # 💡 노이즈 제거: 데이터가 많으면 주간/월간 단위로 압축하여 선을 깔끔하게 만듭니다.
    if len(chart_data) > 200:
        # 데이터가 200개 이상(약 1년치 이상)이면 월간(M) 마지막 영업일 기준으로 압축
        chart_data = chart_data.set_index('Date').resample('M').last().dropna().reset_index()
    elif len(chart_data) > 60:
        # 데이터가 60개 이상(약 3~6개월치)이면 주간(W) 마지막 영업일 기준으로 압축
        chart_data = chart_data.set_index('Date').resample('W').last().dropna().reset_index()

    # (선생님이 기존에 설정하신 x축 포맷 그대로 유지)
    if period in ["1개월", "3개월", "6개월"]:
        x_format = '%m/%d'; tick_cnt = 5
    else:
        x_format = '%y.%m'; tick_cnt = 6
        
    chart = alt.Chart(chart_data).mark_line(
        color=color, 
        strokeWidth=2,
        # 💡 점 크기도 압축된 데이터 개수에 맞춰 자동으로 조절되게 세팅 (적으면 50, 많으면 15)
        point=alt.OverlayMarkDef(color=color, size=50 if len(chart_data) <= 30 else 15) 
    ).encode(
        x=alt.X('Date:T', axis=alt.Axis(format=x_format, title=None, grid=False, tickCount=tick_cnt)),
        y=alt.Y('Value:Q', scale=alt.Scale(zero=False), axis=alt.Axis(title=None)),
        # (선생님이 기존에 설정하신 한글 툴팁 그대로 유지)
        tooltip=[
            alt.Tooltip('Date:T', title='날짜', format='%Y-%m-%d'), 
            alt.Tooltip('Value:Q', title='값', format=',.2f')
        ]
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
        /* 1. 전체화면 (기본): 선생님의 원본 세팅 그대로 유지 */
        div[data-testid="stVerticalBlockBorderWrapper"] { padding: 20px 25px !important; }
        div[role="radiogroup"] { 
            flex-wrap: wrap !important; 
            gap: 5px 8px !important; 
            justify-content: flex-end !important; 
            padding-right: 8px !important; 
        }
        div[role="radiogroup"] label { white-space: nowrap !important; margin-right: 5px !important; }
        div[role="radiogroup"] p { font-size: 13px !important; }

        /* 2. 💡 분할화면 (좁은화면): 안전하게 위아래로 분리하는 마법 */
        @media (max-width: 1100px) {
            /* 억지로 50:50으로 나뉜 공간을 위아래(세로)로 배치되게 바꿉니다 */
            div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stHorizontalBlock"] {
                flex-direction: column !important; 
            }
            /* 숫자와 라디오버튼이 각각 가로 100% 공간을 쓰도록 넓혀서 겹침 방지 */
            div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="column"] {
                width: 100% !important; 
            }
            /* 밑으로 내려온 라디오버튼을 보기 좋게 좌측 정렬 */
            div[role="radiogroup"] {
                justify-content: flex-start !important;
                margin-top: 5px !important;
            }
        }
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
    
    prompt = f"""당신은 전설적인 투자자 '버나드 바루크'의 철학(세계경제지표의 비밀)을 계승한 탑클래스 펀드매니저입니다.
주제: {topic}
데이터: {data_summary}

[중요 지침]
1. 이모지(아이콘)와 볼드체(**)를 절대 사용하지 마세요. 오직 텍스트만 사용하세요.
2. 각 항목은 정확히 2문장으로만 아주 간결하고 냉철하게 작성하세요.
3. 아래의 대괄호 '[목차명]'을 반드시 그대로 출력하세요.
4. 모든 문장은 VIP 고객에게 브리핑하듯 정중한 존댓말(~입니다, ~습니다)로 작성하세요.

[핵심 요약]
현재 데이터를 바탕으로 시장의 전체적인 국면과 포지션 방향을 2문장으로 요약하세요.

[시장의 이면]
이 지표가 숨기고 있는 대중의 심리와 경제의 진짜 상황을 바루크의 관점에서 2문장으로 꿰뚫어보세요.

[자금의 이동 경로]
현재 지표의 결과로 인해 스마트머니(거대 자본)가 주식, 금리, 환율 중 어디로 어떻게 이동하고 있는지 2문장으로 추적하세요.

[리스크와 기회]
현재 국면에서 가장 취약한 섹터(리스크)와 자금이 몰릴 유망 자산(기회)을 2문장으로 명확히 구분하여 제시하세요.

[행동 지침]
향후 1~3개월 시나리오에 대비해 투자자가 지금 당장 실행해야 할 구체적인 행동을 2문장으로 지시하세요.
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
            # 아이콘 제거 정책에 따라 체크 아이콘 삭제
            btn_text = "분석 완료" if is_analyzed else f"{ai_topic} 분석"
            
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
        else:
            st.link_button("AI 투자 전략 보기", get_google_login_url(), type="primary", use_container_width=True)
            
    # --- 분석 완료 후 하단 영역 (가로 요약 + 4분할 카드) ---
    if st.session_state.logged_in and f"ai_res_{key_suffix}" in st.session_state:
        t_text, content = st.session_state[f"ai_res_{key_suffix}"]
        
        # 텍스트 파싱 처리
        try:
            summary = content.split('[핵심 요약]')[1].split('[시장의 이면]')[0].strip()
            part1 = content.split('[시장의 이면]')[1].split('[자금의 이동 경로]')[0].strip()
            part2 = content.split('[자금의 이동 경로]')[1].split('[리스크와 기회]')[0].strip()
            part3 = content.split('[리스크와 기회]')[1].split('[행동 지침]')[0].strip()
            part4 = content.split('[행동 지침]')[1].strip()
        except:
            summary = content[:150] + "..."
            part1, part2, part3, part4 = "", "", "", ""
        
        # 1. 하단 가로형 풀사이즈 핵심 요약 (파란색)
        st.markdown(f"""
        <div style='background-color:#eff6ff; padding:20px 25px; border-radius:12px; border-left:5px solid #3b82f6; margin-top:10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05);'>
            <div style='font-size:17px; color:#1d4ed8; font-weight:800; margin-bottom:10px;'>펀드매니저 핵심 요약</div>
            <div style='font-size:16px; font-weight:700; color:#1e3a8a; line-height:1.6; word-break:keep-all;'>{summary}</div>
        </div>
        """, unsafe_allow_html=True)
        
        # 2. 아이콘 없는 모던하고 정갈한 2x2 카드 그리드
        st.markdown("<div style='margin-top:20px;'></div>", unsafe_allow_html=True)
        
       # 2. 아이콘 없는 모던하고 정갈한 2x2 카드 그리드
        st.markdown("<div style='margin-top:20px;'></div>", unsafe_allow_html=True)
        
        if part1:
            # 💡 공통 카드 스타일 설정 (기존 높이와 비슷한 180px로 고정 + 길면 스크롤)
            card_style = "background-color:#ffffff; border:1px solid #e5e7eb; border-radius:12px; padding:22px; height:180px; overflow-y:auto; box-shadow: 0 1px 3px rgba(0,0,0,0.05);"
            title_style = "font-size:17px; font-weight:800; color:#111827; margin-bottom:12px; padding-bottom:10px; border-bottom:1px solid #f3f4f6;"
            text_style = "font-size:15px; line-height:1.7; color:#4b5563; word-break:keep-all;"
            
            row1_col1, row1_col2 = st.columns(2)
            with row1_col1:
                st.markdown(f"<div style='{card_style}'><div style='{title_style}'>시장의 이면</div><div style='{text_style}'>{part1}</div></div>", unsafe_allow_html=True)
            with row1_col2:
                st.markdown(f"<div style='{card_style}'><div style='{title_style}'>자금의 이동 경로</div><div style='{text_style}'>{part2}</div></div>", unsafe_allow_html=True)
                
            st.markdown("<div style='margin-top:15px;'></div>", unsafe_allow_html=True)
            
            row2_col1, row2_col2 = st.columns(2)
            with row2_col1:
                st.markdown(f"<div style='{card_style}'><div style='{title_style}'>리스크와 기회</div><div style='{text_style}'>{part3}</div></div>", unsafe_allow_html=True)
            with row2_col2:
                # 💡 행동 지침 박스도 동일하게 180px 고정 + 스크롤 추가
                st.markdown(f"<div style='background-color:#f8fafc; border:1px solid #cbd5e1; border-radius:12px; padding:22px; height:180px; overflow-y:auto; box-shadow: 0 1px 3px rgba(0,0,0,0.05);'><div style='font-size:17px; font-weight:800; color:#0f172a; margin-bottom:12px; padding-bottom:10px; border-bottom:1px solid #e2e8f0;'>행동 지침</div><div style='font-size:15px; line-height:1.7; color:#334155; word-break:keep-all; font-weight:600;'>{part4}</div></div>", unsafe_allow_html=True)

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
    # 💡 4개 버튼을 ["1개월", "3개월", "1년", "3년"]으로 통일했습니다.
    with c1: draw_chart_unit("다우존스", dow_v, dow_c, dow_p, dow_d, "#10b981", ["1개월", "3개월", "1년", "3년"], 0, "dow", "#10b981", "#ef4444", "", False)
    with c2: draw_chart_unit("S&P 500", sp_v, sp_c, sp_p, sp_d, "#10b981", ["1개월", "3개월", "1년", "3년"], 0, "sp500", "#10b981", "#ef4444", "", False)
    with c3: draw_chart_unit("나스닥 100", nas_v, nas_c, nas_p, nas_d, "#10b981", ["1개월", "3개월", "1년", "3년"], 0, "nasdaq", "#10b981", "#ef4444", "", False)
    
    st.markdown("<div class='section-header'>국내 증시 (KR Market)</div>", unsafe_allow_html=True)
    c4, c5 = st.columns(2)
    # 💡 4개 버튼을 ["1개월", "3개월", "1년", "3년"]으로 통일했습니다.
    with c4: draw_chart_unit("코스피", kospi_v, kospi_c, kospi_p, kospi_d, "#ef4444", ["1개월", "3개월", "1년", "3년"], 0, "kospi", "#ef4444", "#3b82f6", "", True)
    with c5: draw_chart_unit("코스닥", kosdaq_v, kosdaq_c, kosdaq_p, kosdaq_d, "#ef4444", ["1개월", "3개월", "1년", "3년"], 0, "kosdaq", "#ef4444", "#3b82f6", "", True)

elif menu == "투자 지표":
    st.title("투자 지표 (Economic Indicators)")
    
    # 🚨 선생님의 로컬(VSC) 환경에서 키가 없는지 친절하게 알려주는 경고창 추가
    if "FRED_API_KEY" not in st.secrets:
        st.error("🚨 API 키 오류: Streamlit 웹사이트(Secrets) 또는 로컬의 .streamlit/secrets.toml에 키가 없습니다!")

    with st.spinner('로딩 중... (API 프리패스 적용 완료!)'):
        # 동시 출발(병렬) 대신, 0.1초 만에 끝나는 정식 API 순차 호출(직렬)로 안전하게 실행
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
    with t3: draw_traffic_light_card("코스피 신호등", get_traffic_light_status("종합", vix_curr, rsi_sp))
    
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
            
            # 💡 [대괄호 제목] 위아래 여백과 줄바꿈을 규칙적으로 잡아주는 로직
            import re
            formatted_content = content.replace('\n', '<br>')
            # 모든 [제목]의 앞에는 넉넉한 한 줄 여백(<br><br>)을, 뒤에는 바로 아랫줄(<br>)로 내림
            formatted_content = re.sub(r'(?:<br>|\s)*(\[.*?\])(?:<br>|\s)*', r'<br><br>\1<br>', formatted_content)
            
            # 맨 처음에 불필요하게 들어간 여백을 깔끔하게 제거
            while formatted_content.startswith('<br>'):
                formatted_content = formatted_content[4:]
                
            st.markdown(f"<div class='ai-box'><div class='ai-title'>👔 {t_text}</div><div class='ai-text'>{formatted_content}</div></div>", unsafe_allow_html=True)
    else:
        # 멤버십 안내 지우고 로그인 버튼만 유지
        st.link_button("AI 투자 전략 보기", get_google_login_url(), type="primary", use_container_width=True)

elif menu == "시장 지도":
    st.title("시장 지도 (Market Map)")
    
    from datetime import datetime, timedelta, timezone, date
    import pandas as pd
    import yfinance as yf
    import plotly.express as px
    import altair as alt
    
    # 💡 1. 서버 위치 상관없이 무조건 한국 시간(KST)으로 기준을 잡습니다.
    kst = timezone(timedelta(hours=9))
    now_kst = datetime.now(kst)
    
    # 💡 2. 매일 아침 '6시 40분'을 마감 동결 시점으로 세팅합니다.
    target_time = now_kst.replace(hour=6, minute=40, second=0, microsecond=0)
    
    # 💡 3. 현재 시간이 6시 40분 전이면 '어제 6:40' 꼬리표를, 지났으면 '오늘 6:40' 꼬리표를 붙입니다.
    # 이 꼬리표(cache_key)가 안 바뀌면 하루 종일 야후에 안 가고 금고에서 0.1초 만에 꺼내옵니다.
    if now_kst < target_time:
        cache_key = (target_time - timedelta(days=1)).strftime("%Y년 %m월 %d일 %H:%M")
    else:
        cache_key = target_time.strftime("%Y년 %m월 %d일 %H:%M")

    st.caption(f"⏱️ 미국장 최종 마감 데이터 동결 기준: **{cache_key} (KST)**")
    
    # 💡 4. 데이터를 묶어두는 마법의 금고 함수
    @st.cache_data(ttl=86400, show_spinner=False)
    def get_frozen_market_map(key):
        sectors = {'XLK': '기술', 'XLV': '헬스케어', 'XLF': '금융', 'XLY': '임의소비재', 'XLP': '필수소비재', 'XLE': '에너지', 'XLI': '산업재', 'XLU': '유틸리티', 'XLRE': '부동산', 'XLB': '소재', 'XLC': '통신'}
        res = []
        for t, n in sectors.items():
            try:
                # 안전하게 5일 치를 가져와서 가장 마지막 거래일 2개를 비교 (휴장일/주말 방어)
                d = yf.Ticker(t).history(period="5d") 
                if len(d) >= 2:
                    c = (d['Close'].iloc[-1] - d['Close'].iloc[-2]) / d['Close'].iloc[-2] * 100
                    res.append({'Sector': n, 'Change': c})
            except:
                pass
        return res

    with st.spinner("섹터별 마감 데이터를 분석 중입니다... (최초 1회 수집 후 하루 종일 0.1초 렌더링!)"):
        rows = get_frozen_market_map(cache_key)
        
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
                
elif menu == "🔒 VIP 포트폴리오" or menu == "VIP 포트폴리오":
    # 💡 모든 이모지/아이콘 제거 & 프리미엄 타이틀 톤 앤 매너 적용
    st.markdown("<h1 style='font-size:32px; font-weight:900; color:#0f172a; margin-bottom:5px; padding-bottom:15px; border-bottom:1px solid #e2e8f0;'>VIP 시크릿 매크로 리포트</h1>", unsafe_allow_html=True)
    
    from datetime import datetime, timedelta, timezone
    import re
    
    # 💡 6:40 AM KST 데일리 동결 로직
    kst = timezone(timedelta(hours=9))
    now_kst = datetime.now(kst)
    target_time = now_kst.replace(hour=6, minute=40, second=0, microsecond=0)
    
    if now_kst < target_time:
        cache_key = (target_time - timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
    else:
        cache_key = target_time.strftime("%Y-%m-%d %H:%M")
        
    @st.cache_data(ttl=86400, show_spinner=False)
    def get_daily_vip_report(key, api_key_val):
        client = openai.OpenAI(api_key=api_key_val)
        
        rate_val, _, _, _ = get_interest_rate_hybrid()
        exch_val, _, _, _ = get_yahoo_data("KRW=X", "10y")
        vix_val, _, _, _ = get_yahoo_data("^VIX")
        _, _, _, sp_data = get_yahoo_data("^GSPC", "6mo")
        rsi_val = calculate_rsi(sp_data)
        
        rate_str = f"{rate_val:.2f}%" if rate_val else "데이터 없음"
        exch_str = f"{exch_val:,.2f}원" if exch_val else "데이터 없음"
        vix_str = f"{vix_val:.2f}" if vix_val else "데이터 없음"
        rsi_str = f"{rsi_val:.2f}" if rsi_val else "데이터 없음"
        
        live_data_str = f"미국 10년물 금리: {rate_str}, 원/달러 환율: {exch_str}, VIX: {vix_str}, S&P500 RSI: {rsi_str}"
        
        # 💡 프롬프트 수정: 4번 유망 섹터에 '투자 관점' 3줄 포맷 지시 추가
        vip_prompt = f"""당신은 월스트리트 수석 펀드매니저입니다.
현재 수집된 실시간 시장 데이터({live_data_str})를 기반으로 투자 판단을 위한 '데일리 모닝 브리핑'을 작성하세요.

[제약 조건]
- 공시, 증시 심리, 개별 특정 종목(티커) 언급 절대 금지.
- 기호(▲, ▼, ->, ↳ 등) 및 이모지 절대 사용 금지. (단, 투자 관점 줄의 '→' 기호는 허용)
- 문체: "~로 판단됩니다", "~가능성이 존재합니다", "~압력이 확대되고 있습니다" 등 리서치 톤 유지.

[1. 데이터 추출 (첫 줄)]
아래 형식으로 현재 시장 상태를 한 줄로 출력하세요. 파이썬 파싱을 위해 대괄호 []와 파이프 | 기호를 반드시 지키세요.
형식: [시장상태]|[핵심요인]|[미국국면]|[한국국면]|[권장현금비중]
예시: [경계]|[금리 상승, 환율 상승, 변동성 확대]|[경기 둔화기]|[회복 지연기]|[40% 이상 확보]

[2. 본문 구성] (위 줄 바로 다음부터 아래 목차 대괄호 []를 정확히 출력하세요)

[핵심 매크로 지표 요약]
숫자보다 해석을 앞세워 아래 구조로 작성하세요. 상승/위험 관련 해석은 <span style="color:#dc2626; font-weight:bold;">, 하락/안전은 <span style="color:#16a34a; font-weight:bold;">, 중립은 <span style="color:#6b7280; font-weight:bold;"> 태그로 감싸세요.
금리: <span style="color:#dc2626; font-weight:bold;">상승 압력 유지</span> ({rate_str})
환율: <span style="color:#dc2626; font-weight:bold;">달러 강세 지속</span> ({exch_str})
VIX: <span style="color:#6b7280; font-weight:bold;">변동성 확대 경계</span> ({vix_str})
RSI: <span style="color:#16a34a; font-weight:bold;">과매도 근접</span> ({rsi_str})
종합 판단: 현재 시장은 단기 변동성 확대 가능성이 높은 구간으로 판단됩니다.

[1. 글로벌 거시경제 및 국면 분석]
미국 국면과 한국 국면 판정 이유를 거시적 근거를 들어 3~4줄 문단으로 설명하세요.

[2. 리스크 방어 및 현금 비중 전략]
현금 비중 확대 근거를 아래와 같이 구조화하여 번호 매기기로 출력하고, 그 아래에 설명 문단을 추가하세요.
현금 비중 확대 근거
1. 금리 상승 지속
2. 환율 변동성 확대
3. 지정학 리스크 증가
(이하 설명 문단...)

[3. 지표 기반 투자 전략]
실제 데이터 흐름과 연결된 구체적이고 짧은 실행형 전략(예: 비중 축소 권고, 비중 확대 검토 등 행동 지시형 문장)을 불릿(•) 3개로 제시하세요. 특수문자 화살표는 쓰지 마세요.
예시:
• 고금리 환경 지속 국면, 성장주 비중 축소 권고
• 변동성 확대 구간 대비 현금 비중 유지 및 단기 대응 전략 병행

[4. 유망 섹터 및 근거]
특정 섹터(수출주, 방산 등)를 미리 고정해서 반복 추천하지 마세요. 반드시 당일 분석한 '매크로 조건(금리, 환율, 변동성 등)'을 우선적으로 해석한 뒤, '한국 주식시장' 기준으로 그 매크로 환경에서 상대적으로 설명력이 높거나 수혜/방어가 가능한 섹터 3가지를 매일 유동적으로 도출하세요. 
각 항목은 아래와 같이 총 3줄로 정확히 줄바꿈하여 출력하세요.
첫째 줄: '섹터명'을 <b>태그로 감싸서 출력
둘째 줄: 왜 이 환경에서 이 섹터를 봐야 하는지 설명하는 관찰형 1문장
셋째 줄: '→ 투자 관점: '으로 시작하는 행동 지시형 1문장
예시:
<b>고배당 및 방어주</b>
금리 상승 압력이 지속되는 구간에서는 안정적인 현금흐름과 배당 매력이 부각될 가능성이 존재합니다.
→ 투자 관점: 포트폴리오 내 비중 확대 고려
<b>조선 및 피팅 업종</b>
원화 약세 국면이 맞물려 환차익 수혜 및 실적 방어 기대감이 커질 수 있습니다.
→ 투자 관점: 환율 상승 구간에서 방어적 대안으로 유효
"""
        resp = client.chat.completions.create(
            model="gpt-4o", 
            messages=[{"role": "user", "content": vip_prompt}],
            temperature=0.1 
        )
        return resp.choices[0].message.content.strip()

    # 💡 본문 폭 제한 래퍼(Wrapper) 적용 시작
    st.markdown("<div style='max-width:850px; margin:0 auto;'>", unsafe_allow_html=True)

    if st.session_state.get('plan', 'Free') == 'Pro':
        st.markdown(f"<div style='font-size:14px; font-weight:700; color:#64748b; margin-top:10px; margin-bottom:5px; text-transform:uppercase; letter-spacing:1px;'>Update: {cache_key}</div>", unsafe_allow_html=True)
        st.markdown("<div style='font-size:15px; color:#334155; margin-bottom:25px; line-height:1.5;'>VIP 멤버십 인증이 완료되었습니다. 최신 매크로 지표를 기반으로 생성된 오늘의 데일리 브리핑을 확인하세요.</div>", unsafe_allow_html=True)
        
        is_vip_analyzed = "vip_report" in st.session_state
        btn_text_vip = "오늘의 VIP 모닝 브리핑 로딩 완료" if is_vip_analyzed else "오늘의 VIP 시크릿 리포트 보기"
        
        st.markdown("<div style='background-color:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:15px; margin-bottom:30px; box-shadow: inset 0 1px 2px rgba(0,0,0,0.02); display:flex; justify-content:center;'>", unsafe_allow_html=True)
        if st.button(btn_text_vip, type="primary", disabled=is_vip_analyzed, use_container_width=True):
            with st.spinner("데이터 분석 및 대시보드 렌더링 중..."):
                if not api_key:
                    st.error("설정 탭에서 API Key를 입력해주세요.")
                else:
                    try:
                        raw_content = get_daily_vip_report(cache_key, api_key)
                        
                        lines = raw_content.split('\n')
                        first_line = lines[0]
                        
                        if '|' in first_line and '[' in first_line:
                            parsed = re.findall(r'\[(.*?)\]', first_line)
                            if len(parsed) >= 5:
                                st.session_state["dash_status"] = parsed[0]
                                st.session_state["dash_factor"] = parsed[1]
                                st.session_state["dash_us"] = parsed[2]
                                st.session_state["dash_kr"] = parsed[3]
                                st.session_state["dash_cash"] = parsed[4]
                                st.session_state["vip_report"] = '\n'.join(lines[1:]).strip()
                            else:
                                st.session_state["vip_report"] = raw_content
                        else:
                            st.session_state["vip_report"] = raw_content
                            
                        st.session_state["auto_scroll"] = True
                        st.rerun() 
                    except Exception as e:
                        st.error(f"오류 발생: {str(e)}")
        st.markdown("</div>", unsafe_allow_html=True)
        
        st.markdown("<div id='report_anchor'></div>", unsafe_allow_html=True)
        if st.session_state.get("auto_scroll"):
            st.components.v1.html("""<script>const anchor = window.parent.document.getElementById('report_anchor'); if(anchor){anchor.scrollIntoView({behavior: 'smooth'});}</script>""", height=0)
            st.session_state["auto_scroll"] = False
        
        if is_vip_analyzed:
            dash_status = st.session_state.get("dash_status", "대기 중")
            dash_factor = st.session_state.get("dash_factor", "-")
            dash_us = st.session_state.get("dash_us", "-")
            dash_kr = st.session_state.get("dash_kr", "-")
            dash_cash = st.session_state.get("dash_cash", "-")
            
            status_color = "#dc2626" if "경계" in dash_status or "위험" in dash_status else "#16a34a" if "안정" in dash_status else "#475569"
            
            # 💡 1번: 보고서 본문을 먼저 파싱하여 시장 상태 강도(초기/중간/강) 점수를 수식 계산
            report_content = st.session_state["vip_report"]
            sections = re.split(r'\[(핵심 매크로 지표 요약|[1-4]\.\s*[^\]]+)\]', report_content)
            c_dict = {}
            if len(sections) >= 3:
                for i in range(1, len(sections), 2):
                    title = sections[i].strip()
                    body = sections[i+1].strip()
                    c_dict[title] = body
            else:
                c_dict['본문'] = report_content
                
            intensity_score = 0
            if "금리 상승" in dash_factor or "고금리" in dash_factor: intensity_score += 1
            if "환율 상승" in dash_factor or "달러 강세" in dash_factor or "원화 약세" in dash_factor: intensity_score += 1
            
            key_0 = next((k for k in c_dict if '요약' in k), None)
            if key_0: 
                body_0 = c_dict[key_0]
                vix_match = re.search(r'VIX:.*?\(([\d\.]+)\)', body_0)
                if vix_match:
                    try:
                        if float(vix_match.group(1)) >= 25.0: intensity_score += 1
                    except: pass
                rsi_match = re.search(r'RSI:.*?\(([\d\.]+)\)', body_0)
                if rsi_match:
                    try:
                        if float(rsi_match.group(1)) <= 30.0: intensity_score += 1
                    except: pass
            
            if intensity_score <= 1: dash_intensity = "초기"
            elif intensity_score == 2: dash_intensity = "중간"
            else: dash_intensity = "강"
            
            dash_status_display = f"{dash_status} ({dash_intensity})"
            
            # 💡 2번: 상단 시장 요약 구조(항목: 내용) 통일 및 1번 강도 렌더링
            st.markdown(f"""
            <div style='background-color:#ffffff; border:1px solid #e2e8f0; border-radius:8px; padding:20px 25px; margin-bottom:35px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);'>
                <div style='font-size:16px; font-weight:800; color:#0f172a; margin-bottom:12px; border-bottom:1px solid #f1f5f9; padding-bottom:8px;'>오늘 시장 상태</div>
                <div style='display:flex; flex-direction:column; gap:8px; margin-bottom:18px;'>
                    <div style='display:flex; align-items:baseline;'><span style='font-size:14px; color:#64748b; font-weight:600; width:65px; flex-shrink:0;'>상태</span> <span style='font-size:15px; font-weight:800; color:{status_color};'>{dash_status_display}</span></div>
                    <div style='display:flex; align-items:baseline;'><span style='font-size:14px; color:#64748b; font-weight:600; width:65px; flex-shrink:0;'>핵심 요인</span> <span style='font-size:14px; color:#334155; font-weight:600; line-height:1.5;'>{dash_factor}</span></div>
                </div>
                <div style='background-color:#f8fafc; border:1px solid #f1f5f9; border-radius:6px; padding:15px; display:flex; flex-direction:column; gap:8px;'>
                    <div style='font-size:13px; color:#334155; font-weight:800; margin-bottom:2px; text-transform:uppercase;'>현재 시장 요약</div>
                    <div style='font-size:14px; color:#334155;'><span style='font-weight:600; color:#64748b; width:45px; display:inline-block;'>경기:</span> 미국 {dash_us} / 한국 {dash_kr}</div>
                    <div style='font-size:14px; color:#334155;'><span style='font-weight:600; color:#64748b; width:45px; display:inline-block;'>리스크:</span> {dash_factor}</div>
                    <div style='font-size:14px; color:#334155;'><span style='font-weight:600; color:#64748b; width:45px; display:inline-block;'>전략:</span> <span style='font-weight:700;'>현금 {dash_cash}</span></div>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            st.markdown("<div style='font-size:20px; font-weight:900; color:#0f172a; margin-top:10px; margin-bottom:20px; border-bottom:2px solid #334155; padding-bottom:8px; letter-spacing:-0.5px;'>데일리 매크로 심층 리포트</div>", unsafe_allow_html=True)
            
            def render_common_card(title, content):
                return f"""
                <div style='background-color:#ffffff; border:1px solid #e2e8f0; border-radius:8px; padding:18px 22px; margin-bottom:20px; box-shadow: 0 1px 3px rgba(0,0,0,0.02);'>
                    <div style='font-size:16px; font-weight:800; color:#0f172a; margin-bottom:10px; border-bottom:1px solid #f1f5f9; padding-bottom:8px;'>{title}</div>
                    <div style='font-size:14.5px; line-height:1.7; color:#334155; word-break:keep-all;'>{content}</div>
                </div>
                """
            
            if key_0: 
                body_0_formatted = c_dict[key_0].replace('\n', '<br>')
                st.markdown(f"<div style='background-color:#f8fafc; border:1px solid #cbd5e1; border-radius:8px; padding:18px 22px; margin-bottom:20px;'><div style='font-size:16px; font-weight:800; color:#0f172a; margin-bottom:10px;'>{key_0}</div><div style='font-size:14.5px; line-height:1.7; color:#334155; word-break:keep-all;'>{body_0_formatted}</div></div>", unsafe_allow_html=True)
            
            key_1 = next((k for k in c_dict if '1.' in k), None)
            if key_1:
                body_1 = c_dict[key_1].replace('\n', '<br>')
                st.markdown(render_common_card(key_1, body_1), unsafe_allow_html=True)
            
            key_2 = next((k for k in c_dict if '2.' in k), None)
            if key_2: 
                body_2 = c_dict[key_2].replace('\n', '<br>')
                body_2 = body_2.replace("현금 비중 확대 근거", "<div style='font-weight:800; color:#0f172a; margin-bottom:4px; font-size:14.5px;'>현금 비중 확대 근거</div>").replace("<br><br>", "<div style='height:8px;'></div>")
                st.markdown(render_common_card(key_2, body_2), unsafe_allow_html=True)
            
            key_3 = next((k for k in c_dict if '3.' in k), None)
            if key_3: 
                body_3 = c_dict[key_3].replace('\n', '<br>')
                body_3 = body_3.replace("•", "</div><div style='margin-bottom:6px; padding-left:12px; text-indent:-12px;'><span style='color:#0f172a; font-weight:900; margin-right:4px;'>•</span><span style='color:#1e293b; font-weight:600;'>")
                if body_3.startswith("</div>"): body_3 = body_3[6:] + "</span></div>"
                body_3 = body_3.replace("<br></div>", "</div>").replace("</div><br>", "</div>")
                st.markdown(render_common_card(key_3, body_3), unsafe_allow_html=True)
            
            # 💡 3번: 4번 섹션 파싱 구조 대수술 - '투자 관점' 3단 블록 처리 추가
            key_4 = next((k for k in c_dict if '4.' in k), None)
            if key_4:
                raw_lines = c_dict[key_4].split('\n')
                safe_body_4 = ""
                
                for line in raw_lines:
                    line = line.strip()
                    if not line: continue
                    
                    if "<b>" in line:
                        if safe_body_4 != "":
                            safe_body_4 += "</div>" # 이전 블록 닫기
                        clean_sector = line.replace("<b>", "").replace("</b>", "").strip()
                        safe_body_4 += f"<div style='margin-bottom:16px;'><div style='font-weight:800; color:#0f172a; font-size:15px; margin-bottom:4px;'>{clean_sector}</div>"
                    elif line.startswith("→") or "투자 관점" in line:
                        # 💡 행동 중심 문장(투자 관점) 특별 스타일 지정
                        safe_body_4 += f"<div style='color:#0f172a; font-size:14.5px; font-weight:700; margin-top:6px;'>{line}</div>"
                    else:
                        safe_body_4 += f"<div style='color:#475569; font-size:14px; line-height:1.6;'>{line}</div>"
                
                if safe_body_4 != "":
                    safe_body_4 += "</div>" # 마지막 블록 닫기
                    st.markdown(render_common_card(key_4, safe_body_4), unsafe_allow_html=True)
                else:
                    st.markdown(render_common_card(key_4, c_dict[key_4].replace('\n', '<br>')), unsafe_allow_html=True)
            
            if '본문' in c_dict:
                st.markdown(f"<div style='font-size:14.5px; line-height:1.7; color:#334155; word-break:keep-all;'>{c_dict['본문'].replace(chr(10), '<br>')}</div>", unsafe_allow_html=True)

    else:
        st.markdown(f"<div style='font-size:14px; font-weight:700; color:#64748b; margin-top:10px; margin-bottom:20px; text-transform:uppercase; letter-spacing:1px;'>Update: {cache_key}</div>", unsafe_allow_html=True)
        
        st.markdown("""
        <div style='background-color:#ffffff; border:1px solid #e2e8f0; border-radius:8px; padding:20px 25px; margin-bottom:35px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); filter: blur(6px); user-select: none;'>
            <div style='font-size:16px; font-weight:800; color:#0f172a; margin-bottom:12px; border-bottom:1px solid #f1f5f9; padding-bottom:8px;'>오늘 시장 상태</div>
            <div style='display:flex; flex-direction:column; gap:8px; margin-bottom:18px;'>
                <div style='display:flex; align-items:baseline;'><span style='font-size:14px; color:#64748b; font-weight:600; width:65px; flex-shrink:0;'>상태</span> <span style='font-size:15px; font-weight:800; color:#dc2626;'>경계 (중간)</span></div>
                <div style='display:flex; align-items:baseline;'><span style='font-size:14px; color:#64748b; font-weight:600; width:65px; flex-shrink:0;'>핵심 요인</span> <span style='font-size:14px; color:#334155; font-weight:600;'>금리 상승, 환율 상승, 변동성 확대</span></div>
            </div>
            <div style='background-color:#f8fafc; border:1px solid #f1f5f9; border-radius:6px; padding:15px; display:flex; flex-direction:column; gap:8px;'>
                <div style='font-size:13px; color:#334155; font-weight:800; margin-bottom:2px; text-transform:uppercase;'>현재 시장 요약</div>
                <div style='font-size:14px; color:#334155;'><span style='font-weight:600; color:#64748b; width:45px; display:inline-block;'>경기:</span> 미국 둔화 / 한국 회복 지연</div>
                <div style='font-size:14px; color:#334155;'><span style='font-weight:600; color:#64748b; width:45px; display:inline-block;'>리스크:</span> 금리 상승, 환율 상승</div>
                <div style='font-size:14px; color:#334155;'><span style='font-weight:600; color:#64748b; width:45px; display:inline-block;'>전략:</span> <span style='font-weight:700;'>현금 40% 이상 확보</span></div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("<div style='font-size:20px; font-weight:900; color:#0f172a; margin-top:10px; margin-bottom:20px; border-bottom:2px solid #334155; padding-bottom:8px;'>데일리 매크로 심층 리포트</div>", unsafe_allow_html=True)
        st.markdown(f"""
        <div style='background-color:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:20px; filter: blur(5px); user-select: none;'>
            <p style='color:#0f172a; font-size:16px; font-weight:800; margin-bottom:10px; border-bottom:1px solid #f1f5f9; padding-bottom:8px;'>핵심 매크로 지표 요약</p>
            <p style='color:#334155; font-size:14.5px; line-height:1.7;'>금리: 상승 압력 유지 (4.28%)<br>환율: 달러 강세 지속 (1,491원)</p>
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown("""
        <div style='background-color:#ffffff; border:1px solid #cbd5e1; border-radius:8px; padding:30px; text-align:center; margin-top:-140px; position:relative; z-index:10; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);'>
            <h3 style='color:#0f172a; margin-top:0; font-size:18px;'>Pro 멤버십 전용 프리미엄 리포트</h3>
            <p style='color:#475569; font-size:14px; line-height:1.6;'>실시간 거시 경제 데이터 기반의 탑다운 전략, 리스크 방어 논리, 그리고 한국 시장 맞춤형 유망 섹터를 매일 아침 확인하세요.</p>
            <p style='color:#94a3b8; font-size:13px; margin-top:20px;'>왼쪽 사이드바에서 멤버십을 업그레이드할 수 있습니다.</p>
        </div>
        """, unsafe_allow_html=True)
        
    # 💡 본문 폭 제한 래퍼 종료
    st.markdown("</div>", unsafe_allow_html=True)

        
# -----------------------------------------------------------------------------
# 7. 공통 푸터 (투자 면책 조항)
# -----------------------------------------------------------------------------
st.markdown("""
<div class="footer-disclaimer">
    <strong>[면책 조항]</strong> 본 웹사이트에서 제공하는 데이터 및 AI 분석 정보는 투자 참고용이며 최종 판단과 책임은 투자자 본인에게 있습니다.
</div>
""", unsafe_allow_html=True)
















