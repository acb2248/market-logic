import streamlit as st
import pandas as pd
import openai
import yfinance as yf
import requests
from io import StringIO
import time

# -----------------------------------------------------------------------------
# 1. 페이지 설정 (디자인 기초)
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Market Logic Pro", 
    page_icon="📈", 
    layout="wide",
    initial_sidebar_state="collapsed" # 모바일 배려: 사이드바 숨김 시작
)

# 커스텀 CSS (카드 디자인, 폰트 강조)
st.markdown("""
    <style>
    .metric-card {
        background-color: #f9f9f9;
        border: 1px solid #e0e0e0;
        border-radius: 10px;
        padding: 20px;
        box-shadow: 2px 2px 5px rgba(0,0,0,0.05);
        margin-bottom: 20px;
    }
    .big-font { font-size: 24px !important; font-weight: bold; }
    .stTabs [data-baseweb="tab-list"] { gap: 20px; }
    .stTabs [data-baseweb="tab"] { height: 50px; white-space: pre-wrap; background-color: #f0f2f6; border-radius: 4px 4px 0 0; gap: 1px; padding-top: 10px; padding-bottom: 10px; }
    .stTabs [aria-selected="true"] { background-color: #ffffff; border-bottom: 2px solid #ff4b4b; }
    </style>
    """, unsafe_allow_html=True)

st.title("📈 Market Logic: 투자의 나침반")
st.markdown("### '결과'가 아니라 '원인'을 분석합니다.")
st.caption("Data: Yahoo Finance(Real-time) + FRED(Official Economic Data)")

# -----------------------------------------------------------------------------
# 2. 사이드바 (관리자 & 정보)
# -----------------------------------------------------------------------------
with st.sidebar:
    st.header("🛠 설정 및 정보")
    
    # API 키 관리
    if "openai_api_key" in st.secrets:
        api_key = st.secrets["openai_api_key"]
        st.success("🔐 AI 엔진 준비 완료")
    else:
        api_key = st.text_input("OpenAI API Key", type="password")
    
    st.divider()
    st.info("📚 **보몰의 핵심 지표 5선**\n\n"
            "1️⃣ **美 10년물 국채:** 자산 가격의 중력\n"
            "2️⃣ **원/달러 환율:** 외국인 수급 신호\n"
            "3️⃣ **비농업 고용:** 경기의 진짜 체력 (New!)\n"
            "4️⃣ **CPI (물가):** 금리 결정의 핵심\n"
            "5️⃣ **실업률:** 경기 침체 경고등")

# -----------------------------------------------------------------------------
# 3. 데이터 엔진 (재시도 + YoY 계산 기능 추가)
# -----------------------------------------------------------------------------

@st.cache_data(ttl=3600)
def get_fred_data_enhanced(series_id, calculation_type='raw'):
    """
    FRED 데이터를 가져와서 보기 좋게 가공하는 함수
    calculation_type: 'raw' (그대로), 'yoy' (전년 동기 대비 증감률 %)
    """
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    
    # 강력한 위장 헤더
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    for attempt in range(3):
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code != 200 or response.text.strip().startswith("<"):
                time.sleep(1)
                continue

            df = pd.read_csv(StringIO(response.text))
            
            # 날짜 컬럼 찾기
            date_col = next((c for c in df.columns if 'date' in c.lower()), None)
            if not date_col: return None, None, None, None, "Format Error"

            df = df.set_index(date_col)
            df.index = pd.to_datetime(df.index)
            df = df.sort_index()

            # --- 핵심: 데이터 가공 (YoY 등) ---
            if calculation_type == 'yoy':
                # 전년 동기 대비 변화율 계산 ((현재 - 1년전) / 1년전 * 100)
                df['Value'] = df.iloc[:, 0].pct_change(periods=12) * 100
                df = df.dropna()
            else:
                # 비농업 고용은 '증감 수' 자체가 중요하므로 그대로 쓰거나 차분(diff)
                if series_id == 'PAYEMS': 
                     # 전월 대비 일자리 증감 수 (천 명 단위)
                    df['Value'] = df.iloc[:, 0].diff() 
                else:
                    df['Value'] = df.iloc[:, 0]

            # 최근 2년치 데이터
            df_recent = df.tail(24)
            
            latest = df_recent['Value'].iloc[-1]
            prev = df_recent['Value'].iloc[-2]
            change = latest - prev
            date = df_recent.index[-1].strftime('%Y-%m')
            
            return latest, change, date, df_recent, None

        except Exception:
            time.sleep(1)
            continue

    return None, None, None, None, "Server Busy"

@st.cache_data(ttl=3600)
def get_yahoo_data(ticker):
    try:
        data = yf.Ticker(ticker).history(period="1y")
        if not data.empty:
            current = data['Close'].iloc[-1]
            prev = data['Close'].iloc[-2]
            change = current - prev
            date = data.index[-1].strftime('%Y-%m-%d')
            return current, change, date, data, None
    except:
        pass
    return None, None, None, None, "Load Failed"

# -----------------------------------------------------------------------------
# 4. 데이터 로딩 (5대 지표)
# -----------------------------------------------------------------------------
with st.spinner('🔄 글로벌 시장 데이터를 수집하고 분석 중입니다...'):
    # 1. 시장 지표 (Yahoo)
    rate_val, rate_chg, rate_date, rate_data, rate_err = get_yahoo_data("^TNX")
    exch_val, exch_chg, exch_date, exch_data, exch_err = get_yahoo_data("KRW=X")

    # 2. 경제 지표 (FRED) - YoY(물가) 및 변화량(고용) 계산 적용
    # CPI는 이제 '지수'가 아니라 '전년 대비 상승률(%)'로 가져옵니다!
    cpi_val, cpi_chg, cpi_date, cpi_data, cpi_err = get_fred_data_enhanced("CPIAUCSL", "yoy")
    core_val, core_chg, core_date, core_data, core_err = get_fred_data_enhanced("CPILFESL", "yoy")
    
    # 비농업 고용 (PAYEMS) - 전월 대비 증감 수
    job_val, job_chg, job_date, job_data, job_err = get_fred_data_enhanced("PAYEMS", "diff")
    
    # 실업률 (UNRATE) - 그대로
    unemp_val, unemp_chg, unemp_date, unemp_data, unemp_err = get_fred_data_enhanced("UNRATE", "raw")

# -----------------------------------------------------------------------------
# 5. UI 구성 (탭 방식 도입)
# -----------------------------------------------------------------------------

tab1, tab2 = st.tabs(["📊 시장 대시보드 (Dashboard)", "🧠 AI 전략 리포트 (Insight)"])

# --- TAB 1: 대시보드 ---
with tab1:
    st.markdown("#### 🌏 실시간 금융 흐름")
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown('<div class="metric-card">', unsafe_allow_html=True)
        st.subheader("1️⃣ 美 10년물 국채 금리")
        if rate_val:
            st.metric("Yield", f"{rate_val:.3f}%", f"{rate_chg:.3f}%")
            st.line_chart(rate_data['Close'], color="#FF4B4B", height=150)
        else: st.warning("데이터 로딩 중...")
        st.markdown('</div>', unsafe_allow_html=True)

    with col2:
        st.markdown('<div class="metric-card">', unsafe_allow_html=True)
        st.subheader("2️⃣ 원/달러 환율")
        if exch_val:
            st.metric("Exchange Rate", f"{exch_val:.2f}원", f"{exch_chg:.2f}원")
            st.line_chart(exch_data['Close'], color="#4B4BFF", height=150)
        else: st.warning("데이터 로딩 중...")
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown("#### 🛒 인플레이션 (전년 대비 상승률 %)")
    col3, col4 = st.columns(2)
    
    with col3:
        st.markdown('<div class="metric-card">', unsafe_allow_html=True)
        st.subheader("3️⃣ 헤드라인 CPI (YoY)")
        if cpi_val:
            st.caption(f"기준: {cpi_date}")
            st.metric("Inflation Rate", f"{cpi_val:.2f}%", f"{cpi_chg:.2f}%p")
            st.area_chart(cpi_data['Value'], color="#FFA500", height=150)
        else: st.warning("데이터 로딩 중...")
        st.markdown('</div>', unsafe_allow_html=True)

    with col4:
        st.markdown('<div class="metric-card">', unsafe_allow_html=True)
        st.subheader("4️⃣ 근원(Core) CPI (YoY) ⭐")
        if core_val:
            st.caption("연준이 보는 진짜 물가")
            st.metric("Core Inflation", f"{core_val:.2f}%", f"{core_chg:.2f}%p")
            st.area_chart(core_data['Value'], color="#800080", height=150)
        else: st.warning("데이터 로딩 중...")
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown("#### 🏗️ 고용 시장 (경기 체력)")
    col5, col6 = st.columns(2)
    
    with col5:
        st.markdown('<div class="metric-card">', unsafe_allow_html=True)
        st.subheader("5️⃣ 비농업 신규 고용 (New!)")
        if job_val:
            st.caption("전월 대비 일자리 증감 (천 명)")
            st.metric("Nonfarm Payrolls", f"{int(job_val)}k", f"{int(job_chg)}k")
            st.bar_chart(job_data['Value'], color="#008000", height=150)
        else: st.warning("데이터 로딩 중...")
        st.markdown('</div>', unsafe_allow_html=True)

    with col6:
        st.markdown('<div class="metric-card">', unsafe_allow_html=True)
        st.subheader("6️⃣ 실업률")
        if unemp_val:
            st.caption(f"기준: {unemp_date}")
            st.metric("Unemployment Rate", f"{unemp_val:.1f}%", f"{unemp_chg:.1f}%p")
            st.line_chart(unemp_data['Value'], color="#555555", height=150)
        else: st.warning("데이터 로딩 중...")
        st.markdown('</div>', unsafe_allow_html=True)

# --- TAB 2: AI 리포트 ---
with tab2:
    st.subheader("🤖 버너드 보몰의 Market Insight")
    st.info("💡 위의 6가지 핵심 지표를 바탕으로 AI가 투자 전략을 수립합니다.")
    
    if st.button("🚀 심층 투자 전략 보고서 생성 (Click)", type="primary"):
        if not api_key:
            st.error("⚠️ 사이드바에 API 키를 입력해주세요.")
        else:
            try:
                # 안전한 값 처리
                s_rate = rate_val if rate_val else 0.0
                s_exch = exch_val if exch_val else 0.0
                s_cpi = cpi_val if cpi_val else 0.0
                s_core = core_val if core_val else 0.0
                s_job = job_val if job_val else 0.0
                s_unemp = unemp_val if unemp_val else 0.0
                
                client = openai.OpenAI(api_key=api_key)
                prompt = f"""
                당신은 '경제지표의 비밀' 저자 버너드 보몰입니다. 냉철한 펀드매니저에게 브리핑하듯 직설적으로 분석하세요.

                [Market Data]
                1. US 10Y Yield: {s_rate:.2f}%
                2. KRW/USD: {s_exch:.1f}
                3. Headline CPI (YoY): {s_cpi:.2f}%
                4. Core CPI (YoY): {s_core:.2f}%
                5. Nonfarm Payrolls Change: {int(s_job)}k (thousand jobs)
                6. Unemployment Rate: {s_unemp:.1f}%

                [Analysis Required]
                1. **Inflation & Fed:** Core CPI와 고용(Payrolls)을 볼 때, 연준이 금리를 올릴까 내릴까? (확률로 표현)
                2. **Market Signal:** 현재 금리 수준이 주식 시장에 '매수 기회'인가 '위험 구간'인가?
                3. **USD Strategy:** 환율 흐름을 볼 때 달러를 사야 하는가, 팔아야 하는가?
                4. **Final Call:** 주식 비중을 확대/축소/유지 중 하나로 결론 내릴 것.
                """
                
                with st.spinner("AI가 월가 데이터를 분석 중입니다..."):
                    response = client.chat.completions.create(
                        model="gpt-4o",
                        messages=[{"role": "user", "content": prompt}]
                    )
                    st.markdown("---")
                    st.markdown(response.choices[0].message.content)
            except Exception as e:
                st.error(f"분석 중 오류 발생: {e}")