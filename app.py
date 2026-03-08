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
from streamlit_gsheets import GSheetsConnection # 💡 구글 시트 연결용
import extra_streamlit_components as stx

# 1. 쿠키 매니저 및 새로고침 방어 로직 (최상단 배치)
cookie_manager = stx.CookieManager()

# 💡 마법의 0.1초 딜레이: 브라우저가 방문증(쿠키)을 꺼낼 시간을 살짝 벌어줍니다.
import time
time.sleep(0.1) 

saved_email = cookie_manager.get("user_email")

# 로그인 안 된 상태인데, 쿠키(방문증)가 발견되었다면? -> 몰래 로그인 복구!
if saved_email and not st.session_state.get('logged_in', False):
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        
        # 💡 핵심 1: ttl=0 설정! 
        # 파이썬의 옛날 기억(캐시)을 무시하고, 무조건 구글 시트에서 최신 상태(Pro 등급)를 실시간으로 읽어오게 강제합니다.
        df = conn.read(worksheet="Users", ttl=0) 
        
        if not df.empty and 'Email' in df.columns and saved_email in df['Email'].values:
            user_idx = df.index[df['Email'] == saved_email].tolist()[0]
            
            # 세션 메모리 완벽 복구
            st.session_state.logged_in = True
            st.session_state.user_email = saved_email
            st.session_state.user_name = df.at[user_idx, 'Name']
            st.session_state.remaining_calls = int(df.at[user_idx, 'Remaining_Calls'])
            st.session_state.plan = df.at[user_idx, 'Plan']
            
            # 💡 핵심 2: st.rerun()!
            # 기억을 복구하자마자 화면을 강제로 1회 새로고침하여, 로그아웃 화면이 뜨기 전에 로그인된 Pro 화면으로 고정해 버립니다.
            st.rerun()
        else:
            cookie_manager.delete("user_email") # DB에 없으면 잘못된 쿠키이므로 파기
    except Exception as e:
        pass # 구글 시트 연결 일시 오류 시 조용히 넘어감

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
    
            # 정보 가져오기
            user_email = user_info.get("email")
            user_name = user_info.get("name")
    
            # 세션에 저장
            st.session_state.logged_in = True
            st.session_state.user_email = user_email
            st.session_state.user_name = user_name
    
            # 💡 브라우저에 쿠키(방문증) 저장! (이 한 줄이 핵심입니다)
            cookie_manager.set("user_email", user_email, max_age=30*24*60*60)
            
            # ---------------------------------------------------------
            # 💡 구글 시트 DB 연결 및 '매일 1회 무료' 로직 시작
            # ---------------------------------------------------------
            conn = st.connection("gsheets", type=GSheetsConnection)
            df = conn.read(worksheet="Users", ttl=0) # 시트 내용 읽기
            today_str = date.today().strftime('%Y-%m-%d')
            
            # 1. 빈 시트일 경우 기본 구조 생성
            if df.empty or 'Email' not in df.columns:
                df = pd.DataFrame(columns=['Email', 'Name', 'Plan', 'Remaining_Calls', 'Last_Free_Date'])
                
            if user_email in df['Email'].values:
                # 2. 기존 가입자인 경우
                user_idx = df.index[df['Email'] == user_email].tolist()[0]
                plan = df.at[user_idx, 'Plan']
                calls = int(df.at[user_idx, 'Remaining_Calls'])
                last_free = str(df.at[user_idx, 'Last_Free_Date'])
                
                # '매일 1회 무료' 로직: 오늘 접속한 게 아니면
                if last_free != today_str:
                    if calls < 1:  # 남은 횟수가 0일 때만 1회 충전 (결제 회원의 횟수는 깎지 않음)
                        calls = 1
                    df.at[user_idx, 'Remaining_Calls'] = calls
                    df.at[user_idx, 'Last_Free_Date'] = today_str
                    conn.update(worksheet="Users", data=df) # 시트에 변경사항 저장
            else:
                # 3. 신규 가입자인 경우 (환영 무료 1회 제공)
                plan = "Free"
                calls = 1
                last_free = today_str
                new_row = pd.DataFrame([{'Email': user_email, 'Name': user_name, 'Plan': plan, 'Remaining_Calls': calls, 'Last_Free_Date': last_free}])
                df = pd.concat([df, new_row], ignore_index=True)
                conn.update(worksheet="Users", data=df) # 시트에 새 회원 저장
                
            # 세션에 최종 횟수 및 등급 저장
            st.session_state.remaining_calls = calls
            st.session_state.plan = plan
            
            st.query_params.clear()

# -----------------------------------------------------------------------------
# 2. 사이드바
# -----------------------------------------------------------------------------
with st.sidebar:
    st.title("Market Logic")
    
    if st.session_state.logged_in:
        # 💡 안전망(.get) 추가: 혹시 기억을 못 하면 기본값('회원', 0)을 사용해 에러를 막습니다.
        user_name = st.session_state.get('user_name', '회원')
        rem_calls = st.session_state.get('remaining_calls', 0)
        
        st.markdown(f"👤 **{user_name}** 님")
        
        # 👇 잔여 횟수 무제한(Pro) 표기 스마트 로직!
        user_plan = st.session_state.get('plan', 'Free')
        if user_plan == 'Pro' or int(rem_calls) > 100:
            st.info("⚡ 잔여 분석 횟수: **♾️ 무제한 (Pro)**")
        else:
            st.info(f"⚡ 잔여 분석 횟수: **{rem_calls} / 100회**")
            
        if st.button("로그아웃", use_container_width=True):
            cookie_manager.delete("user_email") # 💡 브라우저 쿠키 삭제
            st.session_state.clear()
            import time # time 라이브러리가 없다면 에러가 날 수 있어 추가합니다
            time.sleep(0.5) # 💡 쿠키가 지워질 수 있도록 0.5초 틈을 줍니다
            st.rerun()
        
        # 👇 여기서부터 결제 유도 시스템 시작!
        st.markdown("---")
        
       # 유저 등급이 'Free'일 때만 결제 안내 박스를 보여줍니다.
        if st.session_state.get('plan', 'Free') == 'Free':
            st.markdown("""
            <div style='background-color:#fffbeb; border:1px solid #fde68a; border-radius:10px; padding:15px; margin-bottom:15px; box-shadow: 0 2px 4px rgba(0,0,0,0.05);'>
                <div style='font-size:15px; font-weight:800; color:#b45309; margin-bottom:8px;'>👑 Pro 멤버십 업그레이드</div>
                <div style='font-size:13px; color:#92400e; line-height:1.5; margin-bottom:0px; word-break:keep-all;'>
                    무제한 AI 펀드매니저 분석과<br>VIP 시크릿 탭을 열어보세요! (월 9,900원)
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            # 카카오페이/토스 송금 링크 버튼 
            st.link_button("💸 간편 송금하기 (모바일 카카오페이)", "https://qr.kakaopay.com/Ej7mwSX0V135606469", use_container_width=True)
            
            # 💡 무통장 입금 계좌는 폼 안에 적혀있음을 안내하는 버튼!
            st.link_button("📝 무통장 입금 확인 및 승인 요청", "https://forms.google.com", type="primary", use_container_width=True)
            
        else:
            # Pro 회원에게 보여줄 자부심 넘치는 메시지!
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
        
    # 👇 완벽하게 업그레이드된 마법의 리셋 버튼!
    if st.button("🔄 서버 캐시 초기화 (관리자용)"):
        st.cache_data.clear() # 기존 데이터 찌꺼기 삭제
        
        # 💡 로그인 상태는 유지하면서, VIP 리포트 관련 기억만 콕 집어서 삭제!
        keys_to_clear = ["vip_report", "dash_us", "dash_kr", "dash_cash", "dash_risk"]
        for key in keys_to_clear:
            if key in st.session_state:
                del st.session_state[key]
                
        st.rerun() # 화면 새로고침

# -----------------------------------------------------------------------------
# 3. 데이터 엔진
# -----------------------------------------------------------------------------
@st.cache_data(ttl=3600)
def get_yahoo_data(ticker, period="10y"):
    try:
        data = yf.Ticker(ticker).history(period=period) 
        
        # 💡 다우존스(^DJI) 서버 에러 발생 시, 동일한 지수를 추종하는 ETF(DIA)로 자동 대체!
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
        <div style="display: flex; align-items: baseline; gap: 8px;">
            <div style="font-size: 26px; font-weight: 800; color: #111827;">{value:,.2f}<span style="font-size: 16px; color: #9ca3af; margin-left: 2px;">{unit}</span></div>
            <div style="font-size: 12px; font-weight: 700; color: {color}; background-color: {bg_color}; padding: 3px 6px; border-radius: 4px;">
                {arrow} {sign}{change:,.2f} ({sign}{pct_change:.2f}%)
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

def draw_chart_unit(label, val, chg, pct, data, color, periods, default_idx, key, up_c, down_c, unit="", use_columns=True):
    with st.container(border=True):
        if use_columns:
            c1, c2 = st.columns([1.5, 1.5])
            with c1: styled_metric(label, val, chg, pct, unit, up_c, down_c)
            with c2: 
                st.markdown('<div style="height: 10px;"></div>', unsafe_allow_html=True)
                selected_period = st.radio("기간", periods, index=default_idx, key=key, horizontal=True, label_visibility="collapsed")
        else:
            styled_metric(label, val, chg, pct, unit, up_c, down_c)
            st.markdown('<div style="height: 10px;"></div>', unsafe_allow_html=True)
            selected_period = st.radio("기간", periods, index=default_idx, key=key, horizontal=True, label_visibility="collapsed")
        st.markdown('<div style="margin-top: 15px;"></div>', unsafe_allow_html=True)
        filtered_data = filter_data_by_period(data, selected_period)
        create_chart(filtered_data, color, period=selected_period, height=180)

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
    
    # 💡 AI가 절대 딴짓을 못하도록 강력한 지침 추가
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
        
# 💡 분석 버튼 자리에 로그인 유도 로직 및 분할 레이아웃 적용
# 💡 분석 버튼 자리에 로그인 유도 로직 및 분할 레이아웃 적용
def draw_section_with_ai(title, chart1, chart2, key_suffix, ai_topic, ai_data):
    st.markdown(f"<div class='section-header'>{title}</div>", unsafe_allow_html=True)
    col_main, col_ai = st.columns([3, 1])
    with col_main:
        c1, c2 = st.columns(2)
        with c1: draw_chart_unit(chart1['l'], chart1['v'], chart1['c'], chart1['p'], chart1['d'], chart1['col'], chart1['prd'], 0, f"{key_suffix}_1", chart1['uc'], chart1['dc'], chart1['u'], True)
        with c2: draw_chart_unit(chart2['l'], chart2['v'], chart2['c'], chart2['p'], chart2['d'], chart2['col'], chart2['prd'], 0, f"{key_suffix}_2", chart2['uc'], chart2['dc'], chart2['u'], True)
    
    with col_ai:
        if st.session_state.logged_in:
            is_analyzed = f"ai_res_{key_suffix}" in st.session_state
            btn_text = "✅ 분석 완료" if is_analyzed else f"{ai_topic} 분석"
            
            if st.button(btn_text, key=f"btn_{key_suffix}", type="primary", disabled=is_analyzed, use_container_width=True):
                if st.session_state.remaining_calls > 0:
                    with st.spinner("AI 펀드매니저가 데이터를 분석 중입니다."):
                        t_text, content = analyze_market_ai(ai_topic, ai_data)
                        
                        # 💡 AI가 혹시라도 이모지를 넣었을 경우 파이썬에서 강제로 삭제해버림
                        for emoji in ['💡', '🔍', '🎯', '🚀', '📌', '👔', '✅']:
                            content = content.replace(emoji, '')
                            
                        st.session_state.remaining_calls -= 1
                        deduct_user_call()
                        st.session_state[f"ai_res_{key_suffix}"] = (t_text, content)
                    st.rerun() 
                else: st.error("⚠️ 현재 유료 멤버십 결제 시스템을 준비 중입니다.")
            
            # 💡 [우측 파란 박스] height: 370px 로 고정하여 차트 높이와 무조건 일치시킴!
            if is_analyzed:
                t_text, content = st.session_state[f"ai_res_{key_suffix}"]
                
                # '[지표의 숨은 의미]'를 기준으로 정확히 분리
                if '[지표의 숨은 의미]' in content:
                    summary_part = content.split('[지표의 숨은 의미]')[0]
                    summary = summary_part.replace('[핵심 요약]', '').strip()
                else:
                    summary = content[:100] + "..."
                
                st.markdown(f"""
                <div style='background-color:#eff6ff; padding:15px 20px; border-radius:12px; border-left:5px solid #3b82f6; margin-top:10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); display:flex; flex-direction:column; justify-content:space-between;'>
                    <div style='margin-bottom:10px;'>
                        <div style='font-size:16px; color:#1d4ed8; font-weight:800; margin-bottom:8px;'>펀드매니저 핵심 요약</div>
                        <div style='font-size:15px; font-weight:700; color:#1e3a8a; line-height:1.5; word-break:keep-all;'>{summary}</div>
                    </div>
                    
                    <div style='margin-top:10px; padding-top:10px; border-top:1px dashed #bfdbfe; font-size:12px; color:#1e40af; text-align:center; font-weight:700; line-height:1.4;'>
                        👉 변동성 장세에서 수급이 폭발할 유망 섹터는?
                        <br> <span style='color:#ea580c; font-size:13px;'>[🔒 VIP 포트폴리오]</span>에서 확인하세요!
                    </div>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.markdown(f"<div class='ai-box' style='background-color:#f8fafc;'><div class='ai-title' style='color:#64748b;'>🔐 멤버십 전용</div><div class='ai-text' style='color:#94a3b8; margin-bottom:15px;'>월스트리트급 AI 펀드매니저 분석은 회원만 이용 가능합니다.</div></div>", unsafe_allow_html=True)
            st.link_button("AI 펀드매니저 연결", get_google_login_url(), type="primary", use_container_width=True)
            
    # 💡 [하단 초록 박스] 글씨 크기(18px) 확대, 줄간격(2.0) 확대, 소제목 여백 45px 통일
    if st.session_state.logged_in and f"ai_res_{key_suffix}" in st.session_state:
        t_text, content = st.session_state[f"ai_res_{key_suffix}"]
        
        if '[지표의 숨은 의미]' in content:
            detail_raw = "[지표의 숨은 의미]" + content.split('[지표의 숨은 의미]')[1]
        else:
            detail_raw = content
            
        # 대괄호 소제목을 크고 굵은 HTML 디자인으로 변환 (위 여백 45px로 시원하게 분리)
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
    
    # 👇 제목 바로 아래에 데이터 기준 시간을 예쁘게 박아줍니다!
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
    
    st.markdown("<div class='section-header'>AI 심리 분석</div>", unsafe_allow_html=True)
    if st.session_state.logged_in:
        # 💡 분석 완료 여부 확인
        is_analyzed_sentiment = "ai_res_sentiment" in st.session_state
        btn_text_sentiment = "✅ 분석 완료" if is_analyzed_sentiment else "현재 시장 심리 분석"
        
        # 💡 버튼 강조(primary) 및 완료 시 회색 비활성화(disabled) 적용
        if st.button(btn_text_sentiment, type="primary", disabled=is_analyzed_sentiment, use_container_width=True):
            if st.session_state.remaining_calls > 0:
                with st.spinner("AI 펀드매니저가 데이터를 분석 중입니다."):
                    t_text, content = analyze_market_ai("현재 시장 심리", f"VIX: {vix_curr}, S&P RSI: {rsi_sp}, 코스피 RSI: {rsi_ks}")
                    st.session_state.remaining_calls -= 1
                    deduct_user_call()
                    st.session_state["ai_res_sentiment"] = (t_text, content) # 결과 저장
                st.rerun()
            else: st.error("⚠️ 현재 유료 멤버십 결제 시스템을 준비 중입니다. (오픈 예정)")
        
        # 💡 저장된 결과 화면에 유지
        if is_analyzed_sentiment:
            t_text, content = st.session_state["ai_res_sentiment"]
            st.markdown(f"<div class='ai-box'><div class='ai-title'>👔 {t_text}</div><div class='ai-text'>{content}</div></div>", unsafe_allow_html=True)
    else:
        st.info("🔐 심리 분석은 로그인 후 이용 가능합니다.")
        st.link_button("AI 펀드매니저 연결", get_google_login_url(), type="primary", use_container_width=True)

elif menu == "시장 지도":
    st.title("시장 지도 (Market Map)")
    
    # ⏱️ 1. 실시간 업데이트 시간 추가
    from datetime import datetime, date
    current_time = datetime.now().strftime("%Y년 %m월 %d일 %H:%M 기준")
    st.caption(f"⏱️ 실시간 데이터 업데이트: **{current_time}**")
    
    today_str = date.today().strftime('%Y-%m-%d')
    st.markdown(f'<div class="info-box">S&P 500 주요 섹터별 등락률 ({today_str})</div>', unsafe_allow_html=True)
    
    sectors = {'XLK': '기술', 'XLV': '헬스케어', 'XLF': '금융', 'XLY': '임의소비재', 'XLP': '필수소비재', 'XLE': '에너지', 'XLI': '산업재', 'XLU': '유틸리티', 'XLRE': '부동산', 'XLB': '소재', 'XLC': '통신'}
    rows = []
    
    # 데이터 수집 (기존과 동일)
    for t, n in sectors.items():
        try:
            d = yf.Ticker(t).history(period="5d")
            if len(d) >= 2:
                c = (d['Close'].iloc[-1] - d['Close'].iloc[-2]) / d['Close'].iloc[-2] * 100
                rows.append({'Sector': n, 'Change': c})
        except Exception as e:
            pass
            
    if rows:
        import plotly.express as px
        import pandas as pd
        
        df_sector = pd.DataFrame(rows)
        
        # 💡 2. 펀드매니저용 트리맵(히트맵)을 위한 데이터 가공
        df_sector['Root'] = '미국 S&P 500 섹터 맵' # 트리맵 최상단 이름
        # 박스 크기를 정하기 위해 변동률의 절대값 생성 (변동폭이 큰 섹터가 더 큰 네모로 표시됨)
        # 만약 변동성과 무관하게 똑같은 크기로 하려면 df_sector['Size'] = 1 로 두고 아래 values='Size'로 바꾸시면 됩니다.
        df_sector['Absolute_Change'] = df_sector['Change'].abs() 
        # 화면에 예쁘게 표시될 텍스트 라벨 (+1.23%, -0.54% 형태)
        df_sector['Label'] = df_sector['Change'].apply(lambda x: f"+{x:.2f}%" if x > 0 else f"{x:.2f}%")
        
        # 💡 3. 대망의 트리맵 그리기
        fig = px.treemap(
            df_sector, 
            path=['Root', 'Sector'], # 그룹 구조
            values='Absolute_Change', # 네모 블록의 크기
            color='Change', # 색상 기준
            color_continuous_scale='RdYlGn', # 🇺🇸 미국식 컬러: 하락(빨강/Red) -> 0(노랑/Yellow) -> 상승(초록/Green)
            color_continuous_midpoint=0, # 0을 기준으로 색상 반전
            custom_data=['Label'] # 추가 텍스트 데이터
        )
        
        # 폰트 및 텍스트 위치 디자인
        fig.update_traces(
            textposition="middle center",
            textinfo="label+text",
            texttemplate="<b>%{label}</b><br><br><span style='font-size:18px;'>%{customdata[0]}</span>",
            marker=dict(line=dict(width=2, color='white')) # 네모 칸 사이에 하얀색 예쁜 틈(선) 주기
        )
        
        # 여백 및 전체 크기 조절
        fig.update_layout(
            margin=dict(t=30, l=10, r=10, b=10),
            paper_bgcolor="rgba(0,0,0,0)", # 배경을 사이트 색상에 맞게 투명하게
            height=600 # 맵을 시원시원하게 크게!
        )
        
        # 완성된 Plotly 차트 출력
        st.plotly_chart(fig, use_container_width=True)

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
    
  # 💡 Pro 회원에게만 진짜 내용을 보여줍니다.
    if st.session_state.get('plan', 'Free') == 'Pro':
        st.success("👑 VIP 멤버십 인증 완료! 실시간 핵심 투자 전략을 확인하세요.")
        
        # =========================================================
        # 1. 🚀 리포트 생성 버튼 (화면 맨 위로 끌어올림!)
        # =========================================================
        is_vip_analyzed = "vip_report" in st.session_state
        btn_text_vip = "✅ 실시간 VIP 리포트 생성 완료" if is_vip_analyzed else "🚀 실시간 VIP 시크릿 리포트 생성하기"
        
        if st.button(btn_text_vip, type="primary", disabled=is_vip_analyzed, use_container_width=True):
            with st.spinner("AI 펀드매니저가 거시경제 지표를 분석하여 대시보드와 리포트를 생성 중입니다..."):
                if not api_key:
                    st.error("설정 탭에서 API Key를 입력해주세요.")
                else:
                    client = openai.OpenAI(api_key=api_key)
                    
                    # (기존과 동일한 완벽한 프롬프트 유지하되 '실시간' 강조)
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
        
        st.markdown("<br>", unsafe_allow_html=True) # 여백
        
        # =========================================================
        # 2. 📊 중간: AI 대시보드 (버튼 아래에 위치)
        # =========================================================
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
        
        # =========================================================
        # 3. 🤖 하단: 생성된 리포트 출력 창
        # =========================================================
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
        # 💡 일반 유저에게 보여주는 '결제 뽐뿌' 블러(흐림) 처리 화면 (Free 등급용 떡밥)
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


















































