import streamlit as st
import pandas as pd
import openai
import yfinance as yf
import requests
from io import StringIO
import time

# -----------------------------------------------------------------------------
# 1. 기본 설정
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Market Logic: The Secrets", page_icon="📊", layout="wide")

st.title("📊 Market Logic: 경제지표의 비밀")
st.markdown("### 🔍 '시장 예상(Consensus)'과 '근원(Core)'을 꿰뚫어보다")
st.caption("데이터 출처: Yahoo Finance(시장) + FRED(경제지표)")
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
# 3. 데이터 가져오기 (강력한 재시도 기능 추가 ⭐)
# -----------------------------------------------------------------------------

# (1) FRED 데이터 (위장술 + 에러 방어)
@st.cache_data(ttl=3600) # 1시간마다 갱신
def get_fred_data(series_id, name):
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    
    # 더 강력한 위장 헤더
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/csv,text/plain;q=0.9',
        'Accept-Language': 'en-US,en;q=0.9'
    }

    # 3번 재시도 (Retry Logic)
    for attempt in range(3):
        try:
            response = requests.get(url, headers=headers, timeout=10)
            
            # 차단되었거나 에러인 경우
            if response.status_code != 200:
                time.sleep(1) # 1초 쉬고 재시도
                continue
            
            # HTML(차단 메시지)이 왔는지 확인 ('<'로 시작하면 HTML임)
            if response.text.strip().startswith("<"):
                return None, None, None, None, "FRED 서버 차단됨 (HTML 응답)"

            # CSV 파싱
            df = pd.read_csv(StringIO(response.text))
            
            # 'DATE' 컬럼 찾기 (대소문자 구분 없이)
            date_col = None
            for col in df.columns:
                if col.lower() == 'date' or col.lower() == 'observation_date':
                    date_col = col
                    break
            
            if date_col is None:
                return None, None, None, None, "날짜 컬럼 없음 (데이터 형식 오류)"

            df = df.set_index(date_col)
            df.index = pd.to_datetime(df.index)
            df = df.sort_index().tail(24) # 최근 2년
            
            latest = df.iloc[-1, 0]
            prev = df.iloc[-2, 0]
            change = latest - prev
            date = df.index[-1].strftime('%Y-%m')
            
            return latest, change, date, df, None # 성공!

        except Exception as e:
            time.sleep(1) # 에러나면 1초 쉬고 재시도
            continue

    return None, None, None, None, "3회 연결 실패 (서버 불안정)"

# (2) 야후 데이터 (재시도 기능 추가)
@st.cache_data(ttl=3600)
def get_yahoo_data(ticker):
    for attempt in range(3):
        try:
            data = yf.Ticker(ticker).history(period="1y")
            if not data.empty:
                current = data['Close'].iloc[-1]
                prev = data['Close'].iloc[-2]
                change = current - prev
                date = data.index[-1].strftime('%Y-%m-%d')
                return current, change, date, data, None
            time.sleep(1)
        except:
            time.sleep(1)
            
    return None, None, None, None, "데이터 로딩 실패"

# -----------------------------------------------------------------------------
# 4. 데이터 로딩 실행
# -----------------------------------------------------------------------------

# 1. 시장 데이터 (야후가 제일 튼튼함)
# 금리(^TNX), 환율(KRW=X) -> 야후로 통일 (FRED 차단 회피)
rate_val, rate_chg, rate_date, rate_data, rate_err = get_yahoo_data("^TNX")
exch_val, exch_chg, exch_date, exch_data, exch_err = get_yahoo_data("KRW=X")

# 2. 경제 지표 (FRED)
cpi_val, cpi_chg, cpi_date, cpi_data, cpi_err = get_fred_data("CPIAUCSL", "전체CPI")
core_val, core_chg, core_date, core_data, core_err = get_fred_data("CPILFESL", "근원CPI")
unemp_val, unemp_chg, unemp_date, unemp_data, unemp_err = get_fred_data("UNRATE", "실업률")

# -----------------------------------------------------------------------------
# 5. 대시보드 레이아웃
# -----------------------------------------------------------------------------

# [1단] 시장의 속도
col1, col2 = st.columns(2)
with col1:
    st.subheader("1️⃣ 미국 10년물 국채 금리")
    if rate_val is not None:
        st.metric(f"수익률 ({rate_date})", f"{rate_val:.2f}%", f"{rate_chg:+.2f}%")
        st.line_chart(rate_data['Close'], color="#FF4B4B")
    else:
        st.error(f"⚠️ {rate_err}")

with col2:
    st.subheader("2️⃣ 원/달러 환율")
    if exch_val is not None:
        st.metric(f"환율 ({exch_date})", f"{exch_val:.2f}원", f"{exch_chg:.2f}원")
        st.line_chart(exch_data['Close'], color="#4B4BFF")
    else:
        st.error(f"⚠️ {exch_err}")

st.divider()

# [2단] 물가 심층 분석
st.markdown("### 🛒 인플레이션 심층 분석 (Headline vs Core)")
col3, col4 = st.columns(2)

with col3:
    st.subheader("3️⃣ 전체 소비자 물가 (Headline)")
    if cpi_val is not None:
        st.metric(f"CPI 지수 ({cpi_date})", f"{cpi_val:.1f}", f"{cpi_chg:+.1f}")
        st.area_chart(cpi_data, color="#FFA500", height=150)
    else:
        st.warning(f"⚠️ 데이터 수신 지연: {cpi_err}")

with col4:
    st.subheader("4️⃣ 근원 소비자 물가 (Core) ⭐")
    if core_val is not None:
        st.metric(f"Core CPI ({core_date})", f"{core_val:.1f}", f"{core_chg:+.1f}")
        st.area_chart(core_data, color="#800080", height=150)
    else:
        st.warning(f"⚠️ 데이터 수신 지연: {core_err}")

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
    st.warning(f"⚠️ 데이터 수신 지연: {unemp_err}")

# -----------------------------------------------------------------------------
# 6. AI 분석
# -----------------------------------------------------------------------------
st.divider()
st.subheader("🤖 버너드 보몰의 심층 리포트")

if st.button("🚀 Core CPI & 컨센서스 기반 분석 실행"):
    if not api_key:
        st.warning("API 키를 확인해주세요.")
    else:
        try:
            safe_rate = rate_val if rate_val else 0.0
            safe_exch = exch_val if exch_val else 0.0
            safe_cpi = cpi_val if cpi_val else 0.0
            safe_core = core_val if core_val else 0.0
            safe_unemp = unemp_val if unemp_val else 0.0
            
            client = openai.OpenAI(api_key=api_key)
            prompt = f"""
            당신은 '경제지표의 비밀' 저자 버너드 보몰입니다.
            
            [현재 데이터]
            1. 국채금리: {safe_rate:.2f}%
            2. 환율: {safe_exch:.1f}원
            3. 전체 CPI: {safe_cpi}
            4. 근원(Core) CPI: {safe_core}
            5. 실업률: {safe_unemp}%

            [분석 요청]
            1. **Core CPI 분석:** 전체 물가와 근원 물가의 차이를 보고, 인플레이션의 성격(일시적 vs 구조적)을 진단하세요.
            2. **컨센서스 관점:** 시장의 예상과 현재 수치가 부합하는지 추론해 주세요.
            3. **투자 전략:** 연준의 금리 향방과 주식 비중 조절 전략을 제시하세요.
            """
            
            with st.spinner("AI가 분석 중입니다..."):
                response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role": "user", "content": prompt}]
                )
                st.markdown(response.choices[0].message.content)
        except Exception as e:
            st.error(f"오류 발생: {e}")