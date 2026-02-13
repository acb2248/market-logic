import streamlit as st
import pandas as pd
import openai
import yfinance as yf
import requests
import altair as alt # ✨ 새로운 차트 엔진
from io import StringIO
import time

# -----------------------------------------------------------------------------
# 1. 페이지 설정 및 디자인
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Market Logic Pro", 
    page_icon="📈", 
    layout="wide",
    initial_sidebar_state="collapsed"
)

# 커스텀 CSS (카드 디자인 + 폰트)
st.markdown("""
    <style>
    /* 전체 배경 및 폰트 */
    .stApp { background-color: #f8f9fa; }
    
    /* 메트릭 카드 디자인 */
    div[data-testid="metric-container"] {
        background-color: #ffffff;
        border: 1px solid #e0e0e0;
        padding: 20px;
        border-radius: 10px;
        box-shadow: 0 2px 5px rgba(0,0,0,0.05);
        transition: transform 0.2s;
    }
    div[data-testid="metric-container"]:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 10px rgba(0,0,0,0.1);
    }
    
    /* 탭 디자인 */
    .stTabs [data-baseweb="tab-list"] { gap: 10px; }
    .stTabs [data-baseweb="tab"] {
        height: 50px;
        background-color: #ffffff;
        border-radius: 5px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        font-weight: 600;
    }
    .stTabs [aria-selected="true"] {
        background-color: #e3f2fd;
        color: #1976d2;
    }
    </style>
    """, unsafe_allow_html=True)

st.title("📈 Market Logic: 투자의 나침반")
st.markdown("### '원인(Logic)'을 분석하여 '결과(Market)'를 예측합니다.")
st.caption("Updated: Real-time & Official Data Source")

# -----------------------------------------------------------------------------
# 2. 사이드바 (설정)
# -----------------------------------------------------------------------------
with st.sidebar:
    st.header("🛠 설정")
    if "openai_api_key" in st.secrets:
        api_key = st.secrets["openai_api_key"]
        st.success("🔐 AI 엔진 준비 완료")
    else:
        api_key = st.text_input("OpenAI API Key", type="password")
    
    st.info("💡 **차트 사용법**\n\n"
            "• **확대/축소:** 마우스 휠\n"
            "• **이동:** 클릭 후 드래그\n"
            "• **초기화:** 차트 더블 클릭")

# -----------------------------------------------------------------------------
# 3. 데이터 엔진 (Altair용 데이터 가공)
# -----------------------------------------------------------------------------

@st.cache_data(ttl=3600)
def get_fred_data(series_id, calculation_type='raw'):
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}

    for attempt in range(3):
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code != 200 or response.text.strip().startswith("<"):
                time.sleep(1)
                continue

            df = pd.read_csv(StringIO(response.text))
            
            # 날짜 처리
            date_col = next((c for c in df.columns if 'date' in c.lower()), None)
            if not date_col: return None, None, None, None
            
            df = df.rename(columns={date_col: 'Date'}) # Altair를 위해 컬럼명 통일
            df['Date'] = pd.to_datetime(df['Date'])
            df = df.set_index('Date').sort_index()

            # 계산 로직 (YoY, Diff 등)
            if calculation_type == 'yoy':
                df['Value'] = df.iloc[:, 0].pct_change(periods=12) * 100
            elif calculation_type == 'diff':
                df['Value'] = df.iloc[:, 0].diff()
            else:
                df['Value'] = df.iloc[:, 0]

            df = df.dropna().tail(24) # 최근 2년
            
            # Altair용으로 인덱스 리셋 (Date를 컬럼으로)
            chart_df = df.reset_index()
            
            latest = df['Value'].iloc[-1]
            prev = df['Value'].iloc[-2]
            change = latest - prev
            date = df.index[-1].strftime('%Y-%m')
            
            return latest, change, date, chart_df

        except:
            time.sleep(1)
            continue
    return None, None, None, None

@st.cache_data(ttl=3600)
def get_yahoo_data(ticker):
    try:
        data = yf.Ticker(ticker).history(period="1y")
        if not data.empty:
            current = data['Close'].iloc[-1]
            prev = data['Close'].iloc[-2]
            change = current - prev
            date = data.index[-1].strftime('%Y-%m-%d')
            
            # Altair용 데이터 프레임 (Date 컬럼 생성)
            chart_df = data[['Close']].reset_index()
            chart_df = chart_df.rename(columns={'Date': 'Date', 'Close': 'Value'})
            # 야후 날짜가 timezone이 있는 경우가 있어 제거
            chart_df['Date'] = chart_df['Date'].dt.tz_localize(None)
            
            return current, change, date, chart_df
    except:
        pass
    return None, None, None, None

# -----------------------------------------------------------------------------
# 4. 차트 그리기 함수 (Altair - 전문가용)
# -----------------------------------------------------------------------------
def create_chart(data, color, chart_type='line'):
    if data is None: return st.error("데이터 없음")
    
    # 기본 차트 설정
    base = alt.Chart(data).encode(
        x=alt.X('Date:T', axis=alt.Axis(format='%y-%m', title=None)), # 날짜 포맷
        tooltip=[alt.Tooltip('Date:T', format='%Y-%m-%d'), alt.Tooltip('Value', format=',.2f')] # 마우스 오버
    )

    if chart_type == 'line':
        chart = base.mark_line(
            interpolate='linear', # A안: 직선형 (뾰족함)
            strokeWidth=2,
            color=color
        ).encode(
            # ⭐ 핵심: Y축 자동 스케일 (zero=False)
            y=alt.Y('Value:Q', scale=alt.Scale(zero=False), axis=alt.Axis(title=None))
        )
    else: # bar
        chart = base.mark_bar(color=color).encode(
            y=alt.Y('Value:Q', axis=alt.Axis(title=None))
        )

    # 줌/팬 기능 추가 (interactive)
    return st.altair_chart(chart.interactive(), use_container_width=True)

# -----------------------------------------------------------------------------
# 5. 데이터 로딩
# -----------------------------------------------------------------------------
# 1. Market Data
rate_val, rate_chg, rate_date, rate_data = get_yahoo_data("^TNX")
exch_val, exch_chg, exch_date, exch_data = get_yahoo_data("KRW=X")

# 2. Economic Data
cpi_val, cpi_chg, cpi_date, cpi_data = get_fred_data("CPIAUCSL", "yoy")
core_val, core_chg, core_date, core_data = get_fred_data("CPILFESL", "yoy")
job_val, job_chg, job_date, job_data = get_fred_data("PAYEMS", "diff")
unemp_val, unemp_chg, unemp_date, unemp_data = get_fred_data("UNRATE", "raw")

# -----------------------------------------------------------------------------
# 6. UI 레이아웃 (Tabs)
# -----------------------------------------------------------------------------
tab1, tab2 = st.tabs(["📊 시장 대시보드", "🧠 AI 전략 리포트"])

with tab1:
    # 섹션 1: 시장 (Market)
    st.subheader("🌏 Market Trends (금리 & 환율)")
    col1, col2 = st.columns(2)
    
    with col1:
        if rate_val:
            st.metric("美 10년물 국채 금리", f"{rate_val:.3f}%", f"{rate_chg:.3f}%")
            create_chart(rate_data, "#d32f2f") # 빨강
        else: st.warning("Loading...")
            
    with col2:
        if exch_val:
            st.metric("원/달러 환율", f"{exch_val:.2f}원", f"{exch_chg:.2f}원")
            create_chart(exch_data, "#1976d2") # 파랑
        else: st.warning("Loading...")

    st.divider()

    # 섹션 2: 물가 (Inflation)
    st.subheader("🛒 Inflation (물가 상승률 YoY)")
    col3, col4 = st.columns(2)
    
    with col3:
        if cpi_val:
            st.metric(f"헤드라인 CPI ({cpi_date})", f"{cpi_val:.2f}%", f"{cpi_chg:.2f}%p")
            create_chart(cpi_data, "#f57c00") # 주황
        else: st.warning("Loading...")

    with col4:
        if core_val:
            st.metric(f"근원(Core) CPI ({core_date}) ⭐", f"{core_val:.2f}%", f"{core_chg:.2f}%p")
            create_chart(core_data, "#7b1fa2") # 보라
        else: st.warning("Loading...")

    st.divider()

    # 섹션 3: 고용 (Jobs)
    st.subheader("🏗️ Job Market (고용 지표)")
    col5, col6 = st.columns(2)
    
    with col5:
        if job_val:
            st.metric(f"비농업 신규 고용 ({job_date})", f"{int(job_val)}k", f"{int(job_chg)}k")
            create_chart(job_data, "#388e3c", "bar") # 초록 (막대 그래프가 적합)
        else: st.warning("Loading...")

    with col6:
        if unemp_val:
            st.metric(f"실업률 ({unemp_date})", f"{unemp_val:.1f}%", f"{unemp_chg:.1f}%p")
            create_chart(unemp_data, "#616161") # 회색
        else: st.warning("Loading...")

with tab2:
    st.header("🤖 버너드 보몰의 Insight")
    st.info("💡 위 6가지 지표를 분석하여 '지금 당장' 취해야 할 포지션을 제안합니다.")
    
    if st.button("🚀 AI 심층 분석 실행 (Click)", type="primary"):
        if not api_key:
            st.error("API 키가 필요합니다.")
        else:
            try:
                s_rate = rate_val if rate_val else 0.0
                s_exch = exch_val if exch_val else 0.0
                s_cpi = cpi_val if cpi_val else 0.0
                s_core = core_val if core_val else 0.0
                s_job = job_val if job_val else 0.0
                s_unemp = unemp_val if unemp_val else 0.0
                
                client = openai.OpenAI(api_key=api_key)
                prompt = f"""
                당신은 월가의 전설적인 전략가 버너드 보몰입니다.
                다음 데이터를 보고 트레이더에게 즉시 실행 가능한 조언을 하세요.

                [데이터]
                - 금리: {s_rate:.2f}%
                - 환율: {s_exch:.1f}원
                - 물가(YoY): 전체 {s_cpi:.2f}% / 근원 {s_core:.2f}%
                - 고용: 신규 {int(s_job)}k / 실업률 {s_unemp:.1f}%

                [분석 포인트]
                1. **Market Tone:** 현재 시장이 '긴축 공포' 구간인지 '경기 침체' 구간인지 진단.
                2. **Fed Action:** 물가와 고용을 볼 때 연준의 다음 스텝(인상/동결/인하) 확률.
                3. **Trade Call:** 주식(Buy/Sell/Hold), 채권(Buy/Sell), 달러(Buy/Sell) 명확히 제시.
                4. **Risk:** 지금 가장 조심해야 할 변수 하나.
                """
                
                with st.spinner("AI가 분석 중입니다..."):
                    response = client.chat.completions.create(
                        model="gpt-4o",
                        messages=[{"role": "user", "content": prompt}]
                    )
                    st.markdown("---")
                    st.markdown(response.choices[0].message.content)
            except Exception as e:
                st.error(f"Error: {e}")