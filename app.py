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
# 1. 페이지 설정 및 CSS (버튼 & 사이드바 디자인 수정)
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Market Logic", page_icon="📈", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
    <style>
    .stApp { background-color: #ffffff; }
    hr { margin-top: 20px; margin-bottom: 20px; border: 0; border-top: 1px solid #eee; }
    
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
    
    .section-header { font-size: 20px; font-weight: 700; color: #212529; margin-bottom: 10px; }
    
    /* ====================================================================
       ⭐ 사이드바 디자인 개선 (간격 넓히기)
       ==================================================================== */
    section[data-testid="stSidebar"] div[role="radiogroup"] {
        gap: 15px !important; /* 메뉴 간격 넓힘 */
        padding-top: 20px;
    }
    section[data-testid="stSidebar"] label {
        padding: 10px 15px !important;
        border-radius: 8px !important;
        transition: background-color 0.3s;
    }
    /* 사이드바 선택된 항목 스타일 */
    section[data-testid="stSidebar"] label:has(input:checked) {
        background-color: #e3f2fd !important;
        color: #0d47a1 !important;
        font-weight: bold !important;
    }

    /* ====================================================================
       ⭐ 메인 화면 기간 버튼 디자인 (강제 적용)
       ==================================================================== */
    /* 메인 화면의 라디오 버튼 그룹만 타겟팅 (사이드바 제외) */
    div[data-testid="stBlock"] div[role="radiogroup"] {
        background-color: transparent !important;
        flex-direction: row !important;
        gap: 8px !important;
    }
    
    /* 기본 버튼 스타일 */
    div[data-testid="stBlock"] div[role="radiogroup"] label {
        background-color: #f1f3f5 !important;
        padding: 6px 16px !important;
        border-radius: 20px !important;
        border: 1px solid #e9ecef !important;
        color: #666 !important;
        font-size: 13px !important;
        cursor: pointer !important;
        box-shadow: none !important;
        display: flex !important; justify-content: center !important; align-items: center !important;
    }
    
    /* 선택된 버튼 스타일 (진한 네이비) */
    div[data-testid="stBlock"] div[role="radiogroup"] label:has(input:checked) {
        background-color: #003366 !important;
        color: #ffffff !important;
        border-color: #003366 !important;
        font-weight: 600 !important;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1) !important;
    }
    
    div[data-testid="stBlock"] div[role="radiogroup"] label:hover {
        background-color: #e2e6ea !important;
        color: #333 !important;
    }
    
    /* 라디오 버튼 원형 숨김 */
    div[data-testid="stBlock"] div[role="radiogroup"] input { display: none; }
    div[data-testid="stBlock"] div[role="radiogroup"] div[data-testid="stMarkdownContainer"] { display: block; }
    
    </style>
    """, unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 2. 사이드바
# -----------------------------------------------------------------------------
with st.sidebar:
    st.title("Market Logic")
    # 라디오 버튼의 label_visibility="collapsed"를 제거하거나 사이드바 전용 CSS 적용
    menu = st.radio("메뉴", ["주가 지수", "투자 관련 지표"], index=0, label_visibility="collapsed")
    
    st.divider()
    
    st.header("🛠 설정")
    # '데이터 새로고침' 버튼 삭제 완료
    
    if "openai_api_key" in st.secrets:
        api_key = st.secrets["openai_api_key"]
        st.success("🔐 AI 연결됨")
    else:
        api_key = st.text_input("OpenAI API Key", type="password")

# -----------------------------------------------------------------------------
# 3. 데이터 엔진
# -----------------------------------------------------------------------------
@st.cache_data(ttl=3600)
def get_yahoo_data(ticker, period="10y"):
    try:
        data = yf.Ticker(ticker).history(period=period) 
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
                pct_change = 0 # FRED 데이터는 % 변화보다는 단순 증감이 중요
                
                return curr, change, pct_change, df.reset_index()
        except: time.sleep(1); continue
    return None, None, None, None

def get_interest_rate_hybrid():
    res = get_yahoo_data("^TNX")
    if res[0] is not None: return res
    return get_fred_data("DGS10", "raw")

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

# ⭐ 커스텀 메트릭 함수 (HTML) - 색상 제어용
def styled_metric(label, value, change, pct_change, unit="", up_color="red", down_color="blue"):
    if value is None: 
        st.metric(label, "-")
        return

    # 색상 결정
    if change > 0:
        color = up_color
        arrow = "▲"
        sign = "+"
    elif change < 0:
        color = down_color
        arrow = "▼"
        sign = ""
    else:
        color = "gray"
        arrow = "-"
        sign = ""

    # HTML 렌더링
    st.markdown(f"""
    <div style="margin-bottom: 5px;">
        <div style="font-size: 14px; color: #666; margin-bottom: 2px;">{label}</div>
        <div style="display: flex; align-items: baseline; gap: 8px;">
            <div style="font-size: 26px; font-weight: 700; color: #111;">{value:,.2f}{unit}</div>
            <div style="font-size: 14px; font-weight: 600; color: {color}; background-color: {color}15; padding: 2px 6px; border-radius: 4px;">
                {arrow} {sign}{change:,.2f} ({sign}{pct_change:.2f}%)
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

# 차트 단위 그리기 함수
def draw_chart_unit(label, val, chg, pct, data, color, periods, default_idx, key, up_c, down_c, unit="", use_columns=True):
    # 상단: 메트릭 + 기간버튼
    if use_columns:
        c1, c2 = st.columns([1.2, 1.8])
        with c1: 
            styled_metric(label, val, chg, pct, unit, up_c, down_c)
        with c2: 
            # 버튼을 오른쪽 끝으로 정렬하기 위해 빈 공간을 두고 컬럼 사용 가능하지만 CSS로 flex-end 처리함
            period = st.radio("기간", periods, index=default_idx, key=key, horizontal=True, label_visibility="collapsed")
    else:
        styled_metric(label, val, chg, pct, unit, up_c, down_c)
        period = st.radio("기간", periods, index=default_idx, key=key, horizontal=True, label_visibility="collapsed")
        
    filtered_data = filter_data_by_period(data, period)
    create_chart(filtered_data, color, height=180)

# AI 분석 관련 함수
if 'ai_results' not in st.session_state: st.session_state['ai_results'] = {}

def analyze_sector(sector_name, data_summary):
    if not api_key: return "YELLOW", "API 키 필요", "설정에서 키를 입력하세요."
    client = openai.OpenAI(api_key=api_key)
    prompt = f"""
    당신은 펀드매니저 버너드 보몰입니다. 데이터: {data_summary}
    [Output Rules]
    1. Language: Korean (한국어)
    2. Format: SIGNAL: (RED/YELLOW/GREEN) HEADLINE: (Bold 1-line) DETAILS: (2-3 sentences)
    """
    try:
        resp = client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": prompt}])
        text = resp.choices[0].message.content
        signal = "RED" if "RED" in text else "GREEN" if "GREEN" in text else "YELLOW"
        headline = text.split("HEADLINE:")[1].split("DETAILS:")[0].strip() if "HEADLINE:" in text else "분석 완료"
        details = text.split("DETAILS:")[1].strip() if "DETAILS:" in text else text
        return signal, headline, details
    except: return "YELLOW", "오류 발생", "분석 실패"

def draw_ai_section(key_prefix, chart1, chart2):
    st.markdown(f"<div class='signal-box'>", unsafe_allow_html=True)
    st.markdown(f"**🤖 {key_prefix} AI 분석**")
    if st.button("⚡ 분석 실행", key=f"btn_{key_prefix}", use_container_width=True):
        data_sum = f"{chart1['label']}={chart1['val']}, {chart2['label']}={chart2['val']}"
        sig, head, det = analyze_sector(key_prefix, data_sum)
        st.session_state['ai_results'][key_prefix.lower()] = {'signal': sig, 'headline': head, 'details': det}
    
    res = st.session_state['ai_results'].get(key_prefix.lower(), {'signal': None, 'headline': None})
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
    st.title("Global Market Indices")
    st.caption("AI 분석 없이 차트 흐름에 집중하는 대시보드입니다.")
    
    with st.spinner("주가 데이터 수집 중..."):
        dow_v, dow_c, dow_p, dow_d = get_yahoo_data("^DJI")
        sp_v, sp_c, sp_p, sp_d = get_yahoo_data("^GSPC")
        nas_v, nas_c, nas_p, nas_d = get_yahoo_data("^IXIC")
        kospi_v, kospi_c, kospi_p, kospi_d = get_yahoo_data("^KS11")
        kosdaq_v, kosdaq_c, kosdaq_p, kosdaq_d = get_yahoo_data("^KQ11")

    # [1] 미국: 상승=초록(#00C853), 하락=빨강(#D32F2F)
    st.markdown("<div class='section-header'>🇺🇸 US Market (3 Major Indices)</div>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    
    with c1: draw_chart_unit("Dow Jones 30", dow_v, dow_c, dow_p, dow_d, "#00c853", ["1개월", "3개월", "1년", "전체"], 2, "dow", "#00C853", "#D32F2F", "", False)
    with c2: draw_chart_unit("S&P 500", sp_v, sp_c, sp_p, sp_d, "#00c853", ["1개월", "3개월", "1년", "전체"], 2, "sp500", "#00C853", "#D32F2F", "", False)
    with c3: draw_chart_unit("Nasdaq 100", nas_v, nas_c, nas_p, nas_d, "#00c853", ["1개월", "3개월", "1년", "전체"], 2, "nasdaq", "#00C853", "#D32F2F", "", False)
    
    st.markdown("<hr>", unsafe_allow_html=True)

    # [2] 한국: 상승=빨강(#FF3333), 하락=파랑(#0066FF)
    st.markdown("<div class='section-header'>🇰🇷 KR Market (KOSPI & KOSDAQ)</div>", unsafe_allow_html=True)
    c4, c5 = st.columns(2)
    
    with c4: draw_chart_unit("KOSPI", kospi_v, kospi_c, kospi_p, kospi_d, "#ff1744", ["1개월", "3개월", "6개월", "1년", "전체"], 3, "kospi", "#FF3333", "#0066FF", "", True)
    with c5: draw_chart_unit("KOSDAQ", kosdaq_v, kosdaq_c, kosdaq_p, kosdaq_d, "#ff1744", ["1개월", "3개월", "6개월", "1년", "전체"], 3, "kosdaq", "#FF3333", "#0066FF", "", True)

# -----------------------------------------------------------------------------
# 5. 페이지 로직 : 투자 관련 지표 탭
# -----------------------------------------------------------------------------
elif menu == "투자 관련 지표":
    st.title("Macro Indicators")
    st.caption("3가지 핵심 분야(시장/물가/경기)를 정밀 진단합니다.")

    with st.spinner('거시경제 데이터 분석 중...'):
        rate_val, rate_chg, rate_pct, rate_data = get_interest_rate_hybrid()
        exch_val, exch_chg, exch_pct, exch_data = get_yahoo_data("KRW=X", "10y")
        cpi_val, cpi_chg, cpi_pct, cpi_data = get_fred_data("CPIAUCSL", "yoy")
        core_val, core_chg, core_pct, core_data = get_fred_data("CPILFESL", "yoy")
        job_val, job_chg, job_pct, job_data = get_fred_data("PAYEMS", "diff")
        unemp_val, unemp_chg, unemp_pct, unemp_data = get_fred_data("UNRATE", "raw")

    def draw_macro_section(title, key_prefix, chart1, chart2):
        st.markdown(f"<div class='section-header'>{title}</div>", unsafe_allow_html=True)
        col_chart, col_ai = st.columns([3, 1])
        with col_chart:
            # 2번 탭(지표)은 한국식 (상승=빨강, 하락=파랑) 통일
            draw_chart_unit(chart1['label'], chart1['val'], chart1['chg'], chart1['pct'], chart1['data'], chart1['color'], chart1['periods'], chart1['idx'], f"{key_prefix}_1", "#FF3333", "#0066FF", chart1['unit'], True)
            st.markdown("<div style='margin-bottom: 20px;'></div>", unsafe_allow_html=True)
            draw_chart_unit(chart2['label'], chart2['val'], chart2['chg'], chart2['pct'], chart2['data'], chart2['color'], chart2['periods'], chart2['idx'], f"{key_prefix}_2", "#FF3333", "#0066FF", chart2['unit'], True)
        with col_ai:
            draw_ai_section(key_prefix, chart1, chart2)
        st.markdown("<hr>", unsafe_allow_html=True)

    # 1. Market: 금리(오렌지), 환율(달러그린) -> 등락 표시는 한국식(빨강/파랑)
    draw_macro_section("1. Money Flow (시장 금리 & 환율)", "Market",
        {'label': "美 10년물 금리", 'val': rate_val, 'chg': rate_chg, 'pct': rate_pct, 'data': rate_data, 'color': '#fb8c00', 'periods': ["1개월", "3개월", "6개월", "1년", "전체"], 'idx': 3, 'unit': "%"},
        {'label': "원/달러 환율", 'val': exch_val, 'chg': exch_chg, 'pct': exch_pct, 'data': exch_data, 'color': '#2e7d32', 'periods': ["1개월", "3개월", "6개월", "1년", "전체"], 'idx': 3, 'unit': "원"}
    )
    
    # 2. Inflation: 물가(오렌지), 근원(빨강)
    draw_macro_section("2. Inflation (물가 상승률)", "Inflation",
        {'label': "헤드라인 CPI", 'val': cpi_val, 'chg': cpi_chg, 'pct': cpi_pct, 'data': cpi_data, 'color': '#fb8c00', 'periods': ["1년", "3년", "5년", "전체"], 'idx': 1, 'unit': "%"},
        {'label': "근원(Core) CPI", 'val': core_val, 'chg': core_chg, 'pct': core_pct, 'data': core_data, 'color': '#d32f2f', 'periods': ["1년", "3년", "5년", "전체"], 'idx': 1, 'unit': "%"}
    )
    
    # 3. Economy: 고용(블루), 실업률(초록)
    draw_macro_section("3. Economy (고용 & 경기)", "Economy",
        {'label': "비농업 고용", 'val': job_val, 'chg': job_chg, 'pct': job_pct, 'data': job_data, 'color': '#1565c0', 'periods': ["1년", "3년", "5년", "전체"], 'idx': 1, 'unit': "k"},
        {'label': "실업률", 'val': unemp_val, 'chg': unemp_chg, 'pct': unemp_pct, 'data': unemp_data, 'color': '#2e7d32', 'periods': ["1년", "3년", "5년", "전체"], 'idx': 1, 'unit': "%"}
    )