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
# 1. 페이지 설정 및 CSS (아이콘 깨짐 방지 수정 완료 ✅)
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Market Logic", 
    page_icon="📈", 
    layout="wide", 
    initial_sidebar_state="auto"
)

st.markdown("""
    <style>
    /* 1. 폰트 적용 (Pretendard) */
    @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');
    
    /* 🚨 수정 포인트: 아이콘 폰트가 깨지지 않도록 선택자 범위를 안전하게 조정했습니다. */
    html, body, .stApp {
        font-family: 'Pretendard', sans-serif !important;
    }
    
    /* 2. 전체 배경색 (연한 회색) */
    .stApp {
        background-color: #f5f7f9;
    }

    /* 3. 섹션 헤더 디자인 */
    .section-header {
        font-size: 22px;
        font-weight: 800;
        color: #111827;
        margin-top: 10px;
        margin-bottom: 15px;
        letter-spacing: -0.5px;
    }

    /* 4. 카드 UI */
    div[data-testid="stVerticalBlockBorderWrapper"] {
        background-color: #ffffff;
        border: 1px solid #e5e7eb;
        border-radius: 16px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03);
        padding: 20px;
        margin-bottom: 20px;
        transition: transform 0.2s ease-in-out;
    }
    
    div[data-testid="stVerticalBlockBorderWrapper"]:hover {
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.05), 0 4px 6px -2px rgba(0, 0, 0, 0.025);
        border-color: #d1d5db;
    }

    /* 5. 버튼 디자인 (네이비 캡슐) */
    div[data-testid="stBlock"] div[role="radiogroup"] {
        background-color: transparent !important;
        flex-direction: row !important;
        gap: 6px !important;
        flex-wrap: wrap !important;
        justify-content: flex-end !important;
    }
    
    div[data-testid="stBlock"] div[role="radiogroup"] label {
        background-color: #f3f4f6 !important;
        padding: 4px 12px !important;
        border-radius: 9999px !important;
        border: 1px solid transparent !important;
        color: #6b7280 !important;
        font-size: 12px !important;
        font-weight: 600 !important;
        box-shadow: none !important;
    }
    
    div[data-testid="stBlock"] div[role="radiogroup"] label:has(input:checked) {
        background-color: #1e293b !important;
        color: #ffffff !important;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1) !important;
    }

    div[data-testid="stBlock"] div[role="radiogroup"] input { display: none; }
    div[data-testid="stBlock"] div[role="radiogroup"] div[data-testid="stMarkdownContainer"] { display: block; }

    /* 6. 반응형 (좁은 화면에서 세로 스택) */
    @media (max-width: 1200px) {
        div[data-testid="column"] {
            width: 100% !important;
            flex: 1 1 100% !important;
            min-width: 100% !important;
        }
    }

    /* 7. 사이드바 스타일 */
    section[data-testid="stSidebar"] {
        background-color: #ffffff;
        border-right: 1px solid #e5e7eb;
    }
    section[data-testid="stSidebar"] div[role="radiogroup"] {
        flex-direction: column !important;
        gap: 10px !important;
    }
    section[data-testid="stSidebar"] label:has(input:checked) {
        background-color: #eff6ff !important;
        color: #1d4ed8 !important;
        font-weight: 700 !important;
        border-radius: 8px !important;
    }
    
    /* AI 답변 스타일 */
    .ai-headline { font-size: 17px; font-weight: 800; color: #111827; margin-bottom: 8px; line-height: 1.4; }
    .ai-details { font-size: 14px; line-height: 1.6; color: #4b5563; background-color: #f9fafb; padding: 12px; border-radius: 8px; border: 1px solid #e5e7eb; }
    
    /* 신호등 박스 */
    .signal-box { display: flex; justify-content: center; gap: 10px; margin-bottom: 15px; }
    .light { width: 12px; height: 12px; border-radius: 50%; opacity: 0.2; background: #9ca3af; }
    .red.active { background: #ef4444; opacity: 1; box-shadow: 0 0 8px #ef4444; }
    .yellow.active { background: #f59e0b; opacity: 1; box-shadow: 0 0 8px #f59e0b; }
    .green.active { background: #10b981; opacity: 1; box-shadow: 0 0 8px #10b981; }

    </style>
    """, unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 2. 사이드바
# -----------------------------------------------------------------------------
with st.sidebar:
    st.title("Market Logic")
    menu = st.radio("메뉴", ["주가 지수", "투자 관련 지표"], index=0, label_visibility="collapsed")
    st.divider()
    st.header("🛠 설정")
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
                pct_change = 0
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

# Metric (HTML)
def styled_metric(label, value, change, pct_change, unit="", up_color="#ef4444", down_color="#3b82f6"):
    if value is None: 
        st.metric(label, "-")
        return
    
    if change > 0:
        color = up_color
        bg_color = f"{up_color}15"
        arrow = "▲"
        sign = "+"
    elif change < 0:
        color = down_color
        bg_color = f"{down_color}15"
        arrow = "▼"
        sign = ""
    else:
        color = "#6b7280"
        bg_color = "#f3f4f6"
        arrow = "-"
        sign = ""

    st.markdown(f"""
    <div style="display: flex; flex-direction: column; justify-content: center;">
        <div style="font-size: 13px; font-weight: 600; color: #6b7280; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.5px;">{label}</div>
        <div style="display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap;">
            <div style="font-size: 28px; font-weight: 800; color: #111827; letter-spacing: -1px;">{value:,.2f}<span style="font-size: 18px; color: #9ca3af; font-weight: 600; margin-left: 2px;">{unit}</span></div>
            <div style="font-size: 13px; font-weight: 700; color: {color}; background-color: {bg_color}; padding: 4px 8px; border-radius: 6px; display: flex; align-items: center;">
                {arrow} {sign}{change:,.2f} ({sign}{pct_change:.2f}%)
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

# 차트 유닛: 카드 UI
def draw_chart_unit(label, val, chg, pct, data, color, periods, default_idx, key, up_c, down_c, unit="", use_columns=True):
    with st.container(border=True):
        if use_columns:
            c1, c2 = st.columns([1.5, 1.5])
            with c1: 
                styled_metric(label, val, chg, pct, unit, up_c, down_c)
            with c2: 
                st.markdown('<div style="height: 10px;"></div>', unsafe_allow_html=True)
                period = st.radio("기간", periods, index=default_idx, key=key, horizontal=True, label_visibility="collapsed")
        else:
            styled_metric(label, val, chg, pct, unit, up_c, down_c)
            st.markdown('<div style="height: 10px;"></div>', unsafe_allow_html=True)
            period = st.radio("기간", periods, index=default_idx, key=key, horizontal=True, label_visibility="collapsed")
        
        st.markdown('<div style="margin-top: 15px;"></div>', unsafe_allow_html=True)
        filtered_data = filter_data_by_period(data, period)
        create_chart(filtered_data, color, height=180)

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
    with st.container(border=True):
        st.markdown(f"<div style='font-size: 16px; font-weight: 700; color: #111827; margin-bottom: 10px;'>🤖 {key_prefix} AI 분석</div>", unsafe_allow_html=True)
        
        if st.button("⚡ 분석 실행", key=f"btn_{key_prefix}", use_container_width=True):
            data_sum = f"{chart1['label']}={chart1['val']}, {chart2['label']}={chart2['val']}"
            sig, head, det = analyze_sector(key_prefix, data_sum)
            st.session_state['ai_results'][key_prefix.lower()] = {'signal': sig, 'headline': head, 'details': det}
        
        res = st.session_state['ai_results'].get(key_prefix.lower(), {'signal': None, 'headline': None})
        r = "active" if res['signal'] == "RED" else ""
        y = "active" if res['signal'] == "YELLOW" else ""
        g = "active" if res['signal'] == "GREEN" else ""
        
        st.markdown(f"""
        <div class="signal-box" style="margin-top: 15px;">
            <div class="light red {r}"></div>
            <div class="light yellow {y}"></div>
            <div class="light green {g}"></div>
        </div>
        """, unsafe_allow_html=True)
        
        if res['headline']:
            st.markdown(f"<div class='ai-headline'>{res['headline']}</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='ai-details'>{res['details']}</div>", unsafe_allow_html=True)
        else:
            st.info("버튼을 눌러 분석하세요.")

# -----------------------------------------------------------------------------
# 4. 페이지 로직 : 주가 지수 탭
# -----------------------------------------------------------------------------
if menu == "주가 지수":
    st.title("글로벌 시장 지수")
    
    with st.spinner("데이터 로딩 중..."):
        dow_v, dow_c, dow_p, dow_d = get_yahoo_data("^DJI")
        sp_v, sp_c, sp_p, sp_d = get_yahoo_data("^GSPC")
        nas_v, nas_c, nas_p, nas_d = get_yahoo_data("^IXIC")
        kospi_v, kospi_c, kospi_p, kospi_d = get_yahoo_data("^KS11")
        kosdaq_v, kosdaq_c, kosdaq_p, kosdaq_d = get_yahoo_data("^KQ11")

    # [1] 미국
    st.markdown("<div class='section-header'>미국 3대 지수 (US Market)</div>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1: draw_chart_unit("Dow Jones 30", dow_v, dow_c, dow_p, dow_d, "#10b981", ["1개월", "3개월", "1년", "전체"], 2, "dow", "#10b981", "#ef4444", "", False)
    with c2: draw_chart_unit("S&P 500", sp_v, sp_c, sp_p, sp_d, "#10b981", ["1개월", "3개월", "1년", "전체"], 2, "sp500", "#10b981", "#ef4444", "", False)
    with c3: draw_chart_unit("Nasdaq 100", nas_v, nas_c, nas_p, nas_d, "#10b981", ["1개월", "3개월", "1년", "전체"], 2, "nasdaq", "#10b981", "#ef4444", "", False)
    
    st.markdown("<div style='height: 30px'></div>", unsafe_allow_html=True)

    # [2] 한국
    st.markdown("<div class='section-header'>국내 증시 (KR Market)</div>", unsafe_allow_html=True)
    c4, c5 = st.columns(2)
    with c4: draw_chart_unit("KOSPI", kospi_v, kospi_c, kospi_p, kospi_d, "#ef4444", ["1개월", "3개월", "6개월", "1년", "전체"], 3, "kospi", "#ef4444", "#3b82f6", "", True)
    with c5: draw_chart_unit("KOSDAQ", kosdaq_v, kosdaq_c, kosdaq_p, kosdaq_d, "#ef4444", ["1개월", "3개월", "6개월", "1년", "전체"], 3, "kosdaq", "#ef4444", "#3b82f6", "", True)

# -----------------------------------------------------------------------------
# 5. 페이지 로직 : 투자 관련 지표 탭
# -----------------------------------------------------------------------------
elif menu == "투자 관련 지표":
    st.title("경제 지표")

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
            draw_chart_unit(chart1['label'], chart1['val'], chart1['chg'], chart1['pct'], chart1['data'], chart1['color'], chart1['periods'], chart1['idx'], f"{key_prefix}_1", "#ef4444", "#3b82f6", chart1['unit'], True)
            st.markdown("<div style='margin-bottom: 20px;'></div>", unsafe_allow_html=True)
            draw_chart_unit(chart2['label'], chart2['val'], chart2['chg'], chart2['pct'], chart2['data'], chart2['color'], chart2['periods'], chart2['idx'], f"{key_prefix}_2", "#ef4444", "#3b82f6", chart2['unit'], True)
        
        with col_ai:
            draw_ai_section(key_prefix, chart1, chart2)
        st.markdown("<hr>", unsafe_allow_html=True)

    draw_macro_section("1. 금융 시장 (금리 & 환율)", "Market",
        {'label': "美 10년물 금리", 'val': rate_val, 'chg': rate_chg, 'pct': rate_pct, 'data': rate_data, 'color': '#f59e0b', 'periods': ["1개월", "3개월", "6개월", "1년", "전체"], 'idx': 3, 'unit': "%"},
        {'label': "원/달러 환율", 'val': exch_val, 'chg': exch_chg, 'pct': exch_pct, 'data': exch_data, 'color': '#10b981', 'periods': ["1개월", "3개월", "6개월", "1년", "전체"], 'idx': 3, 'unit': "원"}
    )
    
    draw_macro_section("2. 물가 지표 (물가 상승률)", "Inflation",
        {'label': "헤드라인 CPI", 'val': cpi_val, 'chg': cpi_chg, 'pct': cpi_pct, 'data': cpi_data, 'color': '#f59e0b', 'periods': ["1년", "3년", "5년", "전체"], 'idx': 1, 'unit': "%"},
        {'label': "근원(Core) CPI", 'val': core_val, 'chg': core_chg, 'pct': core_pct, 'data': core_data, 'color': '#ef4444', 'periods': ["1년", "3년", "5년", "전체"], 'idx': 1, 'unit': "%"}
    )
    
    draw_macro_section("3. 고용 지표 (고용 & 경기)", "Economy",
        {'label': "비농업 고용", 'val': job_val, 'chg': job_chg, 'pct': job_pct, 'data': job_data, 'color': '#3b82f6', 'periods': ["1년", "3년", "5년", "전체"], 'idx': 1, 'unit': "k"},
        {'label': "실업률", 'val': unemp_val, 'chg': unemp_chg, 'pct': unemp_pct, 'data': unemp_data, 'color': '#10b981', 'periods': ["1년", "3년", "5년", "전체"], 'idx': 1, 'unit': "%"}
    )