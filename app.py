import streamlit as st
import pandas as pd
import openai
import yfinance as yf
import requests
import altair as alt
from io import StringIO
import time
from datetime import datetime, timedelta

# -----------------------------------------------------------------------------
# 1. 페이지 설정 및 스타일
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Market Logic Pro", page_icon="📈", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
    <style>
    .stApp { background-color: #ffffff; }
    hr { margin-top: 20px; margin-bottom: 20px; border: 0; border-top: 1px solid #eee; }
    div[data-testid="stMetricValue"] { font-size: 24px; font-weight: bold; color: #333; }
    
    /* 신호등 박스 */
    .signal-box {
        background-color: #f8f9fa; border: 1px solid #e9ecef; border-radius: 12px; 
        padding: 20px; height: 100%; display: flex; flex-direction: column; align-items: center;
    }
    .light {
        width: 35px; height: 35px; border-radius: 50%; background: #ddd; opacity: 0.3; margin: 0 5px; 
        display: inline-block; transition: all 0.3s ease;
    }
    .red.active { background: #ff4b4b; opacity: 1; box-shadow: 0 0 15px #ff4b4b; transform: scale(1.1); }
    .yellow.active { background: #ffca28; opacity: 1; box-shadow: 0 0 15px #ffca28; transform: scale(1.1); }
    .green.active { background: #00e676; opacity: 1; box-shadow: 0 0 15px #00e676; transform: scale(1.1); }
    
    /* AI 답변 스타일 */
    .ai-headline { font-size: 16px; font-weight: 800; color: #1a1a1a; margin-top: 15px; margin-bottom: 5px; width: 100%; text-align: left; }
    .ai-details { font-size: 13px; line-height: 1.5; color: #666; background-color: white; padding: 10px; border-radius: 8px; border-left: 3px solid #ccc; width: 100%; text-align: left; }
    
    .section-header { font-size: 20px; font-weight: 700; color: #212529; margin-bottom: 5px; }
    
    /* 라디오 버튼 커스텀 */
    div[role="radiogroup"] > label > div:first-child { display: none; }
    div[role="radiogroup"] { flex-direction: row; gap: 6px; margin-bottom: 10px; }
    div[role="radiogroup"] label { 
        background-color: #f1f3f5; padding: 2px 10px; border-radius: 12px; 
        font-size: 11px; border: 1px solid transparent; cursor: pointer; transition: 0.2s; color: #555;
    }
    div[role="radiogroup"] label:hover { background-color: #e9ecef; }
    div[role="radiogroup"] label[data-checked="true"] { background-color: #555; color: white; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 2. 사이드바 (메뉴 선택 & API)
# -----------------------------------------------------------------------------
with st.sidebar:
    st.title("Market Logic")
    
    # ⭐ 메뉴 탭 (여기가 핵심!)
    menu = st.radio("메뉴 선택", ["주가 지수", "투자 관련 지표"], index=0)
    
    st.divider()
    
    st.header("🛠 설정")
    if st.button("🔄 데이터 새로고침"): st.rerun()
    
    if "openai_api_key" in st.secrets:
        api_key = st.secrets["openai_api_key"]
        st.success("🔐 AI 연결됨")
    else:
        api_key = st.text_input("OpenAI API Key", type="password")

# -----------------------------------------------------------------------------
# 3. 데이터 엔진 (공통 함수)
# -----------------------------------------------------------------------------
@st.cache_data(ttl=3600)
def get_yahoo_data(ticker, period="10y"):
    try:
        data = yf.Ticker(ticker).history(period=period) 
        if len(data) > 1:
            curr = data['Close'].iloc[-1]
            change = curr - data['Close'].iloc[-2]
            pct_change = (change / data['Close'].iloc[-2]) * 100
            
            chart_df = data[['Close']].reset_index()
            chart_df.columns = ['Date', 'Value']
            chart_df['Date'] = chart_df['Date'].dt.tz_localize(None)
            
            # 포맷팅 (지수는 소수점 2자리, 등락률은 %)
            val_str = f"{curr:,.2f}"
            chg_str = f"{change:+.2f} ({pct_change:+.2f}%)"
            
            return val_str, chg_str, data.index[-1].strftime('%Y-%m-%d'), chart_df
    except: pass
    return "-", "-", "-", None

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
                return f"{df['Value'].iloc[-1]:.2f}", f"{df['Value'].iloc[-1]-df['Value'].iloc[-2]:+.2f}", df.index[-1].strftime('%Y-%m'), df.reset_index()
        except: time.sleep(1); continue
    return "-", "-", "-", None

# 하이브리드 금리
def get_interest_rate_hybrid():
    val, chg, date, data = get_yahoo_data("^TNX")
    if data is not None: return val, chg, date, data
    return get_fred_data("DGS10", "raw")

# 차트 필터링 & 그리기
def filter_data_by_period(df, period):
    if df is None or df.empty: return df
    end_date = df['Date'].max()
    if period == "1개월": start = end_date - timedelta(days=30)
    elif period == "3개월": start = end_date - timedelta(days=90)
    elif period == "6개월": start = end_date - timedelta(days=180)
    elif period == "1년": start = end_date - timedelta(days=365)
    elif period == "3년": start = end_date - timedelta(days=365*3)
    elif period == "5년": start = end_date - timedelta(days=365*5)
    else: start = df['Date'].min()
    return df[df['Date'] >= start]

def create_chart(data, color, height=180):
    if data is None or data.empty: return st.error("No Data")
    chart = alt.Chart(data).mark_line(color=color, strokeWidth=2).encode(
        x=alt.X('Date:T', axis=alt.Axis(format='%y-%m', title=None, grid=False)),
        y=alt.Y('Value:Q', scale=alt.Scale(zero=False), axis=alt.Axis(title=None)),
        tooltip=['Date:T', alt.Tooltip('Value', format=',.2f')]
    ).properties(height=height).interactive()
    return st.altair_chart(chart, use_container_width=True)

# 차트 단위 그리기 함수
def draw_chart_unit(label, val, chg, data, color, periods, default_idx, key):
    c1, c2 = st.columns([1, 2])
    with c1: st.metric(label, val, chg)
    with c2: period = st.radio("기간", periods, index=default_idx, key=key, horizontal=True, label_visibility="collapsed")
    filtered_data = filter_data_by_period(data, period)
    create_chart(filtered_data, color)

# AI 분석 함수
def analyze_data(prompt_context, key_prefix):
    if not api_key: return st.error("API 키 필요")
    client = openai.OpenAI(api_key=api_key)
    prompt = f"""
    당신은 펀드매니저 버너드 보몰입니다. 데이터: {prompt_context}
    [Output Rules]
    1. Language: Korean (한국어)
    2. Format:
       SIGNAL: (RED or YELLOW or GREEN)
       HEADLINE: (Bold 1-line summary, aggressive tone, max 20 chars)
       DETAILS: (2-3 sentences explanation)
    """
    try:
        resp = client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": prompt}])
        text = resp.choices[0].message.content
        signal = "RED" if "RED" in text else "GREEN" if "GREEN" in text else "YELLOW"
        headline = text.split("HEADLINE:")[1].split("DETAILS:")[0].strip() if "HEADLINE:" in text else "분석 완료"
        details = text.split("DETAILS:")[1].strip() if "DETAILS:" in text else text
        return signal, headline, details
    except: return "YELLOW", "오류 발생", "분석 실패"

def draw_ai_box(key_prefix, context):
    st.markdown(f"<div class='signal-box'>", unsafe_allow_html=True)
    st.markdown(f"**🤖 {key_prefix} AI 분석**")
    
    if st.button("⚡ 분석 실행", key=f"btn_{key_prefix}", use_container_width=True):
        sig, head, det = analyze_data(context, key_prefix)
        st.session_state[f'ai_{key_prefix}'] = {'signal': sig, 'headline': head, 'details': det}
    
    res = st.session_state.get(f'ai_{key_prefix}', {'signal': None, 'headline': None})
    
    r = "active" if res['signal'] == "RED" else ""
    y = "active" if res['signal'] == "YELLOW" else ""
    g = "active" if res['signal'] == "GREEN" else ""
    
    st.markdown(f"""
    <div style="margin-top: 15px; margin-bottom: 10px;">
        <div class="light red {r}"></div>
        <div class="light yellow {y}"></div>
        <div class="light green {g}"></div>
    </div>
    """, unsafe_allow_html=True)
    
    if res['headline']:
        st.markdown(f"<div class='ai-headline'>{res['headline']}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='ai-details'>{res['details']}</div>", unsafe_allow_html=True)
    else: st.info("버튼을 눌러 분석하세요.")
    st.markdown("</div>", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 4. 페이지 로직 : 주가 지수 탭
# -----------------------------------------------------------------------------
if menu == "주가 지수":
    st.title("📈 Global Market Indices")
    st.caption("미국 3대 지수와 한국 2대 지수의 흐름을 한눈에 파악합니다.")
    
    # 데이터 로딩
    with st.spinner("주가 데이터 수집 중..."):
        dow_v, dow_c, _, dow_d = get_yahoo_data("^DJI")
        sp_v, sp_c, _, sp_d = get_yahoo_data("^GSPC")
        nas_v, nas_c, _, nas_d = get_yahoo_data("^IXIC")
        kospi_v, kospi_c, _, kospi_d = get_yahoo_data("^KS11")
        kosdaq_v, kosdaq_c, _, kosdaq_d = get_yahoo_data("^KQ11")

    # [1] 미국 시장 섹션
    st.markdown("<div class='section-header'>🇺🇸 US Market (미국 3대 지수)</div>", unsafe_allow_html=True)
    
    c1, c2 = st.columns([3, 1])
    with c1:
        # 다우
        draw_chart_unit("Dow Jones 30", dow_v, dow_c, dow_d, "#003366", ["1개월", "3개월", "6개월", "1년", "전체"], 3, "dow")
        st.markdown("<br>", unsafe_allow_html=True)
        # S&P 500
        draw_chart_unit("S&P 500", sp_v, sp_c, sp_d, "#003366", ["1개월", "3개월", "6개월", "1년", "전체"], 3, "sp500")
        st.markdown("<br>", unsafe_allow_html=True)
        # 나스닥
        draw_chart_unit("Nasdaq 100", nas_v, nas_c, nas_d, "#003366", ["1개월", "3개월", "6개월", "1년", "전체"], 3, "nasdaq")
    
    with c2:
        context_us = f"Dow: {dow_v}, S&P: {sp_v}, Nasdaq: {nas_v}"
        draw_ai_box("US_Market", context_us)

    st.markdown("<hr>", unsafe_allow_html=True)

    # [2] 한국 시장 섹션
    st.markdown("<div class='section-header'>🇰🇷 KR Market (한국 양대 지수)</div>", unsafe_allow_html=True)
    
    c3, c4 = st.columns([3, 1])
    with c3:
        # 코스피
        draw_chart_unit("KOSPI", kospi_v, kospi_c, kospi_d, "#005a92", ["1개월", "3개월", "6개월", "1년", "전체"], 3, "kospi")
        st.markdown("<br>", unsafe_allow_html=True)
        # 코스닥
        draw_chart_unit("KOSDAQ", kosdaq_v, kosdaq_c, kosdaq_d, "#005a92", ["1개월", "3개월", "6개월", "1년", "전체"], 3, "kosdaq")
        
    with c4:
        context_kr = f"KOSPI: {kospi_v}, KOSDAQ: {kosdaq_v}"
        draw_ai_box("KR_Market", context_kr)

# -----------------------------------------------------------------------------
# 5. 페이지 로직 : 투자 관련 지표 탭 (기존 코드)
# -----------------------------------------------------------------------------
elif menu == "투자 관련 지표":
    st.title("🚥 Macro Indicators")
    st.caption("금리, 환율, 물가, 경기를 분석하여 투자의 방향을 잡습니다.")

    with st.spinner('거시경제 데이터 분석 중...'):
        rate_val, rate_chg, _, rate_data = get_interest_rate_hybrid()
        exch_val, exch_chg, _, exch_data = get_yahoo_data("KRW=X", "10y") # 환율 데이터 포맷 맞춤
        cpi_val, cpi_chg, _, cpi_data = get_fred_data("CPIAUCSL", "yoy")
        core_val, core_chg, _, core_data = get_fred_data("CPILFESL", "yoy")
        job_val, job_chg, _, job_data = get_fred_data("PAYEMS", "diff")
        unemp_val, unemp_chg, _, unemp_data = get_fred_data("UNRATE", "raw")

    # 1. 시장 (Market)
    st.markdown("<div class='section-header'>1. Money Flow (시장 금리 & 환율)</div>", unsafe_allow_html=True)
    c1, c2 = st.columns([3, 1])
    with c1:
        draw_chart_unit("美 10년물 금리", rate_val, rate_chg, rate_data, "#d32f2f", ["1개월", "3개월", "6개월", "1년", "전체"], 3, "rate")
        st.markdown("<br>", unsafe_allow_html=True)
        draw_chart_unit("원/달러 환율", exch_val, exch_chg, exch_data, "#1976d2", ["1개월", "3개월", "6개월", "1년", "전체"], 3, "exch")
    with c2:
        draw_ai_box("Macro_Market", f"Rate: {rate_val}, Exch: {exch_val}")
    st.markdown("<hr>", unsafe_allow_html=True)

    # 2. 물가 (Inflation)
    st.markdown("<div class='section-header'>2. Inflation (물가 상승률)</div>", unsafe_allow_html=True)
    c3, c4 = st.columns([3, 1])
    with c3:
        draw_chart_unit("헤드라인 CPI (YoY)", f"{cpi_val}%", f"{cpi_chg}%p", cpi_data, "#ed6c02", ["1년", "3년", "5년", "전체"], 1, "cpi")
        st.markdown("<br>", unsafe_allow_html=True)
        draw_chart_unit("근원(Core) CPI (YoY)", f"{core_val}%", f"{core_chg}%p", core_data, "#9c27b0", ["1년", "3년", "5년", "전체"], 1, "core")
    with c4:
        draw_ai_box("Macro_Inflation", f"CPI: {cpi_val}, Core: {core_val}")
    st.markdown("<hr>", unsafe_allow_html=True)

    # 3. 경기 (Economy)
    st.markdown("<div class='section-header'>3. Economy (고용 & 경기)</div>", unsafe_allow_html=True)
    c5, c6 = st.columns([3, 1])
    with c5:
        # 고용 데이터 포맷팅 필요 (단위 k 등)
        draw_chart_unit("비농업 신규 고용", f"{job_val}k", f"{job_chg}k", job_data, "#2e7d32", ["1년", "3년", "5년", "전체"], 1, "job")
        st.markdown("<br>", unsafe_allow_html=True)
        draw_chart_unit("실업률", f"{unemp_val}%", f"{unemp_chg}%p", unemp_data, "#616161", ["1년", "3년", "5년", "전체"], 1, "unemp")
    with c6:
        draw_ai_box("Macro_Economy", f"Job: {job_val}, Unemp: {unemp_val}")