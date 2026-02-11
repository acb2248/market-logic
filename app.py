import streamlit as st
import pandas_datareader.data as web
import datetime
import openai
import yfinance as yf

# -----------------------------------------------------------------------------
# 1. 기본 설정
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Market Logic: The Secrets", page_icon="📊", layout="wide")

st.title("📊 Market Logic: 경제지표의 비밀")
st.markdown("### 🔍 '시장 예상(Consensus)'과 '근원(Core)'을 꿰뚫어보다")
st.divider()

# -----------------------------------------------------------------------------
# 2. 사이드바 & API 키
# -----------------------------------------------------------------------------
with st.sidebar:
    st.header("🛠 관리자 모드")
    if "openai_api_key" in st.secrets:
        api_key = st.secrets["openai_api_key"]
        st.success("🔐 API 키 로드 완료")
    else:
        api_key = st.text_input("OpenAI API Key", type="password")
    
    st.info("📚 **버너드 보몰의 조언**\n\n"
            "1️⃣ **시장 반응:** 절대 수치보다 '예상 밖의 쇼크'에 반응한다.\n"
            "2️⃣ **Core CPI:** 연준은 변동성이 큰 에너지/식품을 뺀 '근원 물가'를 본다.")

# -----------------------------------------------------------------------------
# 3. 데이터 가져오기 함수 (안전장치 추가됨 ⭐)
# -----------------------------------------------------------------------------
@st.cache_data
def get_fred_data(symbol):
    try:
        end = datetime.datetime.now()
        start = end - datetime.timedelta(days=700)
        df = web.DataReader(symbol, 'fred', start, end)
        
        # 데이터가 비어있는지 확인
        if df is None or df.empty or len(df) < 2:
            return None, None, None, None
            
        latest = df.iloc[-1, 0]
        prev = df.iloc[-2, 0]
        change = latest - prev
        date = df.index[-1].strftime('%Y-%m')
        
        return latest, change, date, df
    except:
        return None, None, None, None

@st.cache_data
def get_yahoo_data(symbol):
    try:
        data = yf.Ticker(symbol).history(period="1y")
        
        # [수정된 부분] 데이터가 없거나 너무 적으면 안전하게 종료
        if data.empty or len(data) < 2:
            return None, None, None
            
        current = data['Close'].iloc[-1]
        prev = data['Close'].iloc[-2]
        change = current - prev
        return data, current, change
    except:
        return None, None, None

# -----------------------------------------------------------------------------
# 4. 데이터 로딩 실행
# -----------------------------------------------------------------------------
# 1. 시장 데이터 (매일 변함)
rate_data, rate_val, rate_chg = get_yahoo_data("^TNX")   # 국채 10년물
exch_data, exch_val, exch_chg = get_yahoo_data("KRW=X")  # 원달러 환율

# 2. 경제 기초 체력 (월간 발표)
cpi_val, cpi_chg, cpi_date, cpi_data = get_fred_data("CPIAUCSL")     # 전체 CPI
core_val, core_chg, core_date, core_data = get_fred_data("CPILFESL") # 근원 CPI
unemp_val, unemp_chg, unemp_date, unemp_data = get_fred_data("UNRATE") # 실업률

# -----------------------------------------------------------------------------
# 5. 대시보드 레이아웃 (3단 구성)
# -----------------------------------------------------------------------------

# [1단] 시장의 속도 (금리 & 환율)
col1, col2 = st.columns(2)
with col1:
    st.subheader("1️⃣ 미국 10년물 국채 금리")
    if rate_val is not None:
        st.metric("수익률", f"{rate_val:.3f}%", f"{rate_chg:.3f}%")
        st.line_chart(rate_data['Close'], color="#FF4B4B")
    else:
        st.warning("⚠️ 금리 데이터를 가져오지 못했습니다. (일시적 오류)")

with col2:
    st.subheader("2️⃣ 원/달러 환율")
    if exch_val is not None:
        st.metric("환율", f"{exch_val:.2f}원", f"{exch_chg:.2f}원")
        st.line_chart(exch_data['Close'], color="#4B4BFF")
    else:
        st.warning("⚠️ 환율 데이터를 가져오지 못했습니다.")

st.divider()

# [2단] 물가 심층 분석 (헤드라인 vs Core)
st.markdown("### 🛒 인플레이션 심층 분석 (Headline vs Core)")
col3, col4 = st.columns(2)

with col3:
    st.subheader("3️⃣ 전체 소비자 물가 (Headline)")
    if cpi_val is not None:
        st.caption("체감 물가 (에너지/식품 포함)")
        st.metric(f"CPI 지수 ({cpi_date})", f"{cpi_val:.1f}", f"{cpi_chg:+.1f}")
        st.area_chart(cpi_data, color="#FFA500", height=150)
    else:
        st.error("CPI 데이터 로딩 실패")

with col4:
    st.subheader("4️⃣ 근원 소비자 물가 (Core) ⭐")
    if core_val is not None:
        st.caption("연준의 기준 (에너지/식품 제외)")
        st.metric(f"Core CPI ({core_date})", f"{core_val:.1f}", f"{core_chg:+.1f}")
        st.area_chart(core_data, color="#800080", height=150)
    else:
        st.error("Core CPI 데이터 로딩 실패")

st.divider()

# [3단] 경기와 고용
st.subheader("5️⃣ 실업률 (Unemployment)")
if unemp_val is not None:
    col5, col6 = st.columns([1, 3])
    with col5:
        st.metric(f"실업률 ({unemp_date})", f"{unemp_val:.1f}%", f"{unemp_chg:+.1f}%")
    with col6:
        st.bar_chart(unemp_data, color="#008000", height=150)
else:
    st.error("실업률 데이터 로딩 실패")

# -----------------------------------------------------------------------------
# 6. AI 고도화 분석
# -----------------------------------------------------------------------------
st.divider()
st.subheader("🤖 버너드 보몰의 심층 리포트")

if st.button("🚀 Core CPI & 컨센서스 기반 분석 실행"):
    if not api_key:
        st.warning("API 키를 확인해주세요.")
    else:
        try:
            # 데이터가 없는 경우를 대비해 기본값 처리
            safe_rate = rate_val if rate_val else 0.0
            safe_exch = exch_val if exch_val else 0.0
            safe_cpi = cpi_val if cpi_val else 0.0
            safe_core = core_val if core_val else 0.0
            safe_unemp = unemp_val if unemp_val else 0.0
            
            client = openai.OpenAI(api_key=api_key)
            prompt = f"""
            당신은 '경제지표의 비밀' 저자 버너드 보몰입니다.
            제공된 데이터를 바탕으로 월가 스타일의 분석 보고서를 작성하세요.

            [현재 데이터]
            1. 국채금리: {safe_rate:.2f}%
            2. 환율: {safe_exch:.1f}원
            3. 전체 CPI: {safe_cpi}
            4. 근원(Core) CPI: {safe_core}
            5. 실업률: {safe_unemp}%

            [필수 분석 항목]
            1. **Core CPI 분석:** 전체 물가와 근원 물가의 차이를 보고, 인플레이션의 성격(일시적 vs 구조적)을 진단하세요.
            2. **컨센서스 관점:** 최근 시장이 우려하는 시나리오와 현재 수치가 부합하는지 추론해 주세요.
            3. **투자 전략:** 이 상황에서 연준이 금리를 올릴 명분이 강합니까, 내릴 명분이 강합니까? 이에 따른 주식 비중 조절 전략을 제시하세요.
            """
            
            with st.spinner("AI가 근원 물가와 시장 기대치를 분석 중입니다..."):
                response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role": "user", "content": prompt}]
                )
                st.markdown(response.choices[0].message.content)
        except Exception as e:
            st.error(f"오류 발생: {e}")