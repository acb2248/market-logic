import streamlit as st
import pandas as pd
import openai
import yfinance as yf
import requests
import altair as alt
from io import StringIO
import time

# -----------------------------------------------------------------------------
# 1. 페이지 설정 및 디자인
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Market Logic Pro", 
    page_icon="🚥", 
    layout="wide",
    initial_sidebar_state="collapsed"
)

# 커스텀 CSS (신호등 디자인 & 차트 스타일)
st.markdown("""
    <style>
    .stApp { background-color: #f8f9fa; }
    
    /* 차트 카드 */
    div[data-testid="metric-container"] {
        background-color: #ffffff;
        border: 1px solid #e0e0e0;
        padding: 15px;
        border-radius: 8px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }
    
    /* 신호등 컨테이너 */
    .traffic-light-box {
        background-color: #2b2b2b;
        padding: 20px;
        border-radius: 15px;
        text-align: center;
        margin-bottom: 20px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.3);
    }
    
    /* 신호등 전구 (기본 꺼짐 상태) */
    .light {
        height: 50px;
        width: 50px;
        border-radius: 50%;
        display: inline-block;
        margin: 0 10px;
        opacity: 0.2; /* 꺼짐 */
        transition: all 0.3s ease;
    }
    
    /* 켜진 상태 (Active) */
    .red.active { background-color: #ff4b4b; opacity: 1; box-shadow: 0 0 20px #ff4b4b; }
    .yellow.active { background-color: #ffca28; opacity: 1; box-shadow: 0 0 20px #ffca28; }
    .green.active { background-color: #00e676; opacity: 1; box-shadow: 0 0 20px #00e676; }
    
    /* 기본 색상 (꺼져있을 때도 색은 보이게) */
    .red { background-color: #ff4b4b; }
    .yellow { background-color: #ffca28; }
    .green { background-color: #00e676; }
    
    .signal-text {
        color: white;
        margin-top: 10px;
        font-size: 18px;
        font-weight: bold;
    }
    </style>
    """, unsafe_allow_html=True)

st.title("🚥 Market Logic: 투자의 신호등")
st.caption("좌측: 시장 데이터(Fact) / 우측: AI 판단(Signal)")

# -----------------------------------------------------------------------------
# 2. 사이드바 (설정)
# -----------------------------------------------------------------------------
with st.sidebar:
    st.header("🛠 설정")
    if st.button("🔄 데이터 새로고침", type="secondary"):
        st.rerun()
    
    st.divider()
    
    if "openai_api_key" in st.secrets:
        api_key = st.secrets["openai_api_key"]
        st.success("🔐 AI 연결됨")
    else:
        api_key = st.text_input("OpenAI API Key", type="password")
        
    st.info("🚦 **신호등 의미**\n\n"
            "🔴 **RED:** 위험! 현금 확보 (Risk Off)\n"
            "🟡 **YELLOW:** 관망/주의 (Neutral)\n"
            "🟢 **GREEN:** 매수 기회 (Risk On)")

# -----------------------------------------------------------------------------
# 3. 데이터 엔진 (안전장치 포함)
# -----------------------------------------------------------------------------
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

                if calculation_type == 'yoy':
                    df['Value'] = df.iloc[:, 0].pct_change(12) * 100
                elif calculation_type == 'diff':
                    df['Value'] = df.iloc[:, 0].diff()
                else:
                    df['Value'] = df.iloc[:, 0]

                df = df.dropna().tail(24)
                chart_df = df.reset_index()
                return df['Value'].iloc[-1], df['Value'].iloc[-1]-df['Value'].iloc[-2], df.index[-1].strftime('%Y-%m'), chart_df
        except:
            time.sleep(1)
            continue
    return None, None, None, None

@st.cache_data(ttl=3600)
def get_yahoo_data(ticker):
    try:
        data = yf.Ticker(ticker).history(period="1y")
        if len(data) > 1:
            curr = data['Close'].iloc[-1]
            change = curr - data['Close'].iloc[-2]
            date = data.index[-1].strftime('%Y-%m-%d')
            chart_df = data[['Close']].reset_index()
            chart_df.columns = ['Date', 'Value']
            chart_df['Date'] = chart_df['Date'].dt.tz_localize(None)
            return curr, change, date, chart_df
    except: pass
    return None, None, None, None

def get_interest_rate_hybrid():
    res = get_yahoo_data("^TNX")
    if res: return res
    return get_fred_data("DGS10", "raw")

def create_chart(data, color, chart_type='line'):
    if data is None: return st.error("No Data")
    base = alt.Chart(data).encode(
        x=alt.X('Date:T', axis=alt.Axis(format='%y-%m', title=None)),
        tooltip=[alt.Tooltip('Date:T', format='%Y-%m-%d'), alt.Tooltip('Value', format=',.2f')]
    )
    if chart_type == 'line':
        chart = base.mark_line(interpolate='linear', strokeWidth=2, color=color)
    else:
        chart = base.mark_bar(color=color)
    
    return st.altair_chart(chart.encode(y=alt.Y('Value:Q', scale=alt.Scale(zero=False), axis=None)).interactive(), use_container_width=True)

# -----------------------------------------------------------------------------
# 4. 데이터 로딩
# -----------------------------------------------------------------------------
with st.spinner('데이터를 분석 중입니다...'):
    rate_val, rate_chg, rate_date, rate_data = get_interest_rate_hybrid()
    exch_val, exch_chg, exch_date, exch_data = get_yahoo_data("KRW=X")
    cpi_val, cpi_chg, cpi_date, cpi_data = get_fred_data("CPIAUCSL", "yoy")
    core_val, core_chg, core_date, core_data = get_fred_data("CPILFESL", "yoy")
    job_val, job_chg, job_date, job_data = get_fred_data("PAYEMS", "diff")
    unemp_val, unemp_chg, unemp_date, unemp_data = get_fred_data("UNRATE", "raw")

# -----------------------------------------------------------------------------
# 5. 메인 레이아웃 (Split View)
# -----------------------------------------------------------------------------

# 화면 비율 (차트 3 : AI 1.2)
col_charts, col_ai = st.columns([3, 1.2])

# [왼쪽] 차트 영역
with col_charts:
    # 1행
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("1️⃣ 美 10년물 금리")
        if rate_val: 
            st.metric("Yield", f"{rate_val:.2f}%", f"{rate_chg:.2f}%")
            create_chart(rate_data, "#d32f2f")
    with c2:
        st.subheader("2️⃣ 원/달러 환율")
        if exch_val:
            st.metric("Exchange", f"{exch_val:.2f}원", f"{exch_chg:.2f}원")
            create_chart(exch_data, "#1976d2")
    
    st.divider()
    
    # 2행
    c3, c4 = st.columns(2)
    with c3:
        st.subheader("3️⃣ 헤드라인 CPI (YoY)")
        if cpi_val:
            st.metric(f"Inflation ({cpi_date})", f"{cpi_val:.2f}%", f"{cpi_chg:.2f}%p")
            create_chart(cpi_data, "#f57c00")
    with c4:
        st.subheader("4️⃣ 근원(Core) CPI (YoY)")
        if core_val:
            st.metric(f"Core ({core_date})", f"{core_val:.2f}%", f"{core_chg:.2f}%p")
            create_chart(core_data, "#7b1fa2")

    st.divider()

    # 3행
    c5, c6 = st.columns(2)
    with c5:
        st.subheader("5️⃣ 비농업 고용 (Change)")
        if job_val:
            st.metric(f"Payrolls ({job_date})", f"{int(job_val)}k", f"{int(job_chg)}k")
            create_chart(job_data, "#388e3c", "bar")
    with c6:
        st.subheader("6️⃣ 실업률")
        if unemp_val:
            st.metric(f"Unemployment ({unemp_date})", f"{unemp_val:.1f}%", f"{unemp_chg:.1f}%p")
            create_chart(unemp_data, "#616161")

# [오른쪽] AI 신호등 영역 (핵심 변경!)
with col_ai:
    st.markdown("### 🚦 Market Signal")
    st.info("AI가 '매수/관망/매도'를 판단합니다.")
    
    # 초기 상태 변수 (Session State)
    if 'market_signal' not in st.session_state:
        st.session_state['market_signal'] = None
    if 'ai_report' not in st.session_state:
        st.session_state['ai_report'] = None

    # 분석 버튼
    if st.button("🚀 신호등 켜기 (Click)", type="primary", use_container_width=True):
        if not api_key:
            st.error("API 키 필요")
        else:
            try:
                # 안전한 값
                val_list = [rate_val, exch_val, cpi_val, core_val, job_val, unemp_val]
                if any(v is None for v in val_list):
                    st.warning("데이터 로딩 중...")
                
                client = openai.OpenAI(api_key=api_key)
                
                # 프롬프트: 색상(RED/YELLOW/GREEN)을 강제함
                prompt = f"""
                당신은 냉철한 트레이더 버너드 보몰입니다. 다음 데이터를 분석해 '신호등 색상'을 결정하세요.

                [Data]
                Rate: {rate_val if rate_val else 0:.2f}%
                Exch: {exch_val if exch_val else 0:.1f}
                CPI: {cpi_val if cpi_val else 0:.2f}%
                Core: {core_val if core_val else 0:.2f}%
                Job: {job_val if job_val else 0}k

                [Rule]
                1. 첫 줄에 반드시 SIGNAL: RED 또는 SIGNAL: YELLOW 또는 SIGNAL: GREEN 중 하나만 출력.
                   - RED: 시장 위험, 현금화 (Risk Off)
                   - YELLOW: 애매함, 관망 (Neutral)
                   - GREEN: 시장 호재, 매수 (Risk On)
                2. 두 번째 줄부터 짧고 굵은 전략 리포트 작성.
                """
                
                with st.spinner("신호등 색상 결정 중..."):
                    response = client.chat.completions.create(
                        model="gpt-4o",
                        messages=[{"role": "user", "content": prompt}]
                    )
                    full_text = response.choices[0].message.content
                    st.session_state['ai_report'] = full_text
                    
                    # 신호 파싱
                    if "SIGNAL: RED" in full_text: st.session_state['market_signal'] = "RED"
                    elif "SIGNAL: GREEN" in full_text: st.session_state['market_signal'] = "GREEN"
                    else: st.session_state['market_signal'] = "YELLOW"
                    
            except Exception as e:
                st.error(f"Error: {e}")

    # 신호등 UI 그리기
    signal = st.session_state['market_signal']
    report = st.session_state['ai_report']
    
    # CSS 클래스 결정
    r_cls = "active" if signal == "RED" else ""
    y_cls = "active" if signal == "YELLOW" else ""
    g_cls = "active" if signal == "GREEN" else ""
    
    msg = "분석 전"
    if signal == "RED": msg = "🚨 위험 (Risk Off)"
    elif signal == "YELLOW": msg = "✋ 관망 (Neutral)"
    elif signal == "GREEN": msg = "🚀 매수 (Risk On)"

    # HTML 신호등 렌더링
    st.markdown(f"""
    <div class="traffic-light-box">
        <div class="light red {r_cls}"></div>
        <div class="light yellow {y_cls}"></div>
        <div class="light green {g_cls}"></div>
        <div class="signal-text">{msg}</div>
    </div>
    """, unsafe_allow_html=True)

    # 리포트 출력
    if report:
        st.markdown("#### 📝 Strategy Note")
        # 첫 줄(SIGNAL: ...) 제거하고 출력
        clean_report = "\n".join(report.split('\n')[1:])
        st.markdown(clean_report)