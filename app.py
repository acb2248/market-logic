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

    /* 섹션 헤더 */
    .section-header {
        font-size: 20px; font-weight: 700; color: #111827;
        margin-top: 30px; margin-bottom: 15px;
        border-left: 4px solid #111827; padding-left: 10px;
    }

    /* 카드 UI */
    div[data-testid="stVerticalBlockBorderWrapper"] {
        background-color: #ffffff;
        border: 1px solid #e5e7eb; border-radius: 12px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        padding: 20px; margin-bottom: 15px;
    }

    /* D-Day 카드 (디자인 강제 적용) */
    div.d-day-container {
        background-color: #1e293b; 
        color: white;
        padding: 30px; 
        border-radius: 16px; 
        text-align: center;
        margin-bottom: 20px; 
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .d-day-title { font-size: 16px; color: #94a3b8; margin-bottom: 10px; letter-spacing: 1px; text-transform: uppercase; }
    .d-day-count { font-size: 56px; font-weight: 800; color: #ffffff; line-height: 1.1; margin: 10px 0; }
    .d-day-date { font-size: 18px; color: #cbd5e1; margin-top: 10px; }

    /* AI 분석 박스 */
    .ai-box { background-color: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 20px; height: 100%; }
    .ai-title { font-weight: 700; font-size: 16px; margin-bottom: 10px; color: #166534; border-bottom: 1px solid #bbf7d0; padding-bottom: 5px; }
    .ai-text { font-size: 14px; line-height: 1.7; color: #14532d; word-break: keep-all; }
    
    /* [공통] 설명 박스 디자인 (파란색) */
    .info-box {
        background-color: #eff6ff;
        border: 1px solid #bfdbfe;
        border-radius: 8px;
        padding: 15px;
        color: #1e3a8a;
        font-size: 14px;
        line-height: 1.6;
        margin-bottom: 20px;
    }

    /* [공통] 경고/알림 박스 디자인 (노란색) */
    .warning-box {
        background-color: #fefce8;
        border: 1px solid #fde047;
        border-radius: 8px;
        padding: 15px;
        color: #854d0e;
        font-size: 14px;
        line-height: 1.6;
        margin-bottom: 20px;
    }
    
    /* 면책 조항 푸터 */
    .footer-disclaimer {
        text-align: center;
        color: #9ca3af;
        font-size: 13px;
        padding: 20px 0;
        margin-top: 40px;
        border-top: 1px solid #e5e7eb;
        line-height: 1.6;
    }
    </style>
    """, unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 2. 사이드바
# -----------------------------------------------------------------------------
with st.sidebar:
    st.title("Market Logic")
    menu = st.radio("메뉴 선택", ["주가 지수", "투자 지표", "시장 심리", "시장 지도", "주요 일정"], index=0)
    st.markdown("---")
    st.subheader("설정 (Settings)")
    if "openai_api_key" in st.secrets:
        api_key = st.secrets["openai_api_key"]
        st.success("✅ AI 연결됨")
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
                df = df.sort_index()
                
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
    else: start = end_date - timedelta(days=365) # Fallback
    
    return df[df['Date'] >= start]

def create_chart(data, color, period="1년", height=180):
    if data is None or data.empty: return st.error("데이터 없음")
    
    # 💡 기간별 가로축(X축) 날짜 표기 변경
    if period in ["1개월", "3개월", "6개월"]:
        x_format = '%m/%d'  # 1년 미만은 '월/일' 형식
    else:
        x_format = '%y.%m'  # 1년 이상은 '년.월' 형식

    chart = alt.Chart(data).mark_line(color=color, strokeWidth=2).encode(
        x=alt.X('Date:T', axis=alt.Axis(format=x_format, title=None, grid=False)),
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
        
        # 선택된 기간(selected_period)을 create_chart로 넘겨줌
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
        gauge = {
            'axis': {'range': [min_val, max_val], 'tickwidth': 1, 'tickcolor': "#374151"},
            'bar': {'color': bar_color}, 'bgcolor': "white", 'borderwidth': 2, 'bordercolor': "white",
            'steps': steps, 'threshold': {'line': {'color': "red", 'width': 4}, 'thickness': 0.75, 'value': value}
        }
    ))
    fig.update_layout(height=250, margin=dict(l=20, r=20, t=50, b=20), paper_bgcolor='rgba(0,0,0,0)', font={'family': "Pretendard"})
    st.plotly_chart(fig, use_container_width=True)

# -----------------------------------------------------------------------------
# 5. AI 분석 엔진
# -----------------------------------------------------------------------------
def analyze_market_ai(topic, data_summary):
    if not api_key: return "API Key 필요", "설정 탭에서 API Key를 입력해주세요."
    client = openai.OpenAI(api_key=api_key)
    prompt = f"""
    당신은 글로벌 매크로 전략가입니다. 주제: {topic}, 데이터: {data_summary}
    [작성 양식]
    - 핵심 요약: (상황 정의 1문장)
    - 상세 분석: (3개 내외 불렛포인트)
    - 대응 전략: (투자자 행동 가이드)
    
    주의: 텍스트에 볼드체(**)를 절대 사용하지 마세요. 평문으로 작성하세요.
    한국어로 작성하세요.
    """
    try:
        resp = client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": prompt}])
        return "AI 분석 리포트", resp.choices[0].message.content
    except Exception as e: return "오류 발생", str(e)

def draw_section_with_ai(title, chart1, chart2, key_suffix, ai_topic, ai_data):
    st.markdown(f"<div class='section-header'>{title}</div>", unsafe_allow_html=True)
    col_main, col_ai = st.columns([3, 1])
    with col_main:
        c1, c2 = st.columns(2)
        with c1: draw_chart_unit(chart1['l'], chart1['v'], chart1['c'], chart1['p'], chart1['d'], chart1['col'], chart1['prd'], 0, f"{key_suffix}_1", chart1['uc'], chart1['dc'], chart1['u'], True)
        with c2: draw_chart_unit(chart2['l'], chart2['v'], chart2['c'], chart2['p'], chart2['d'], chart2['col'], chart2['prd'], 0, f"{key_suffix}_2", chart2['uc'], chart2['dc'], chart2['u'], True)
    with col_ai:
        if st.button(f"⚡ {ai_topic} 분석", key=f"btn_{key_suffix}", use_container_width=True):
            title, content = analyze_market_ai(ai_topic, ai_data)
            st.markdown(f"<div class='ai-box'><div class='ai-title'>🤖 {title}</div><div class='ai-text'>{content}</div></div>", unsafe_allow_html=True)
        else:
            st.markdown(f"<div class='ai-box' style='background-color:#f9fafb; border-color:#e5e7eb;'><div class='ai-title' style='color:#6b7280; border-color:#e5e7eb;'>AI Analyst</div><div class='ai-text' style='color:#9ca3af;'>버튼을 누르면<br>{ai_topic}에 대한<br>심층 분석을 시작합니다.</div></div>", unsafe_allow_html=True)
    st.markdown("<hr>", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 6. 메인 페이지 로직
# -----------------------------------------------------------------------------
if menu == "주가 지수":
    st.title("글로벌 시장 지수")
    with st.spinner("데이터 로딩 중..."):
        dow_v, dow_c, dow_p, dow_d = get_yahoo_data("^DJI")
        sp_v, sp_c, sp_p, sp_d = get_yahoo_data("^GSPC")
        nas_v, nas_c, nas_p, nas_d = get_yahoo_data("^IXIC")
        kospi_v, kospi_c, kospi_p, kospi_d = get_yahoo_data("^KS11")
        kosdaq_v, kosdaq_c, kosdaq_p, kosdaq_d = get_yahoo_data("^KQ11")

    st.markdown("<div class='section-header'>미국 3대 지수 (US Market)</div>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1: draw_chart_unit("다우존스 지수", dow_v, dow_c, dow_p, dow_d, "#10b981", ["1개월", "3개월", "1년", "전체"], 0, "dow", "#10b981", "#ef4444", "", False)
    with c2: draw_chart_unit("S&P 500", sp_v, sp_c, sp_p, sp_d, "#10b981", ["1개월", "3개월", "1년", "전체"], 0, "sp500", "#10b981", "#ef4444", "", False)
    with c3: draw_chart_unit("나스닥 100", nas_v, nas_c, nas_p, nas_d, "#10b981", ["1개월", "3개월", "1년", "전체"], 0, "nasdaq", "#10b981", "#ef4444", "", False)
    
    st.markdown("<div style='height: 30px'></div>", unsafe_allow_html=True)
    st.markdown("<div class='section-header'>국내 증시 (KR Market)</div>", unsafe_allow_html=True)
    c4, c5 = st.columns(2)
    with c4: draw_chart_unit("코스피 (KOSPI)", kospi_v, kospi_c, kospi_p, kospi_d, "#ef4444", ["1개월", "3개월", "6개월", "1년"], 0, "kospi", "#ef4444", "#3b82f6", "", True)
    with c5: draw_chart_unit("코스닥 (KOSDAQ)", kosdaq_v, kosdaq_c, kosdaq_p, kosdaq_d, "#ef4444", ["1개월", "3개월", "6개월", "1년"], 0, "kosdaq", "#ef4444", "#3b82f6", "", True)

elif menu == "투자 지표":
    st.title("투자 지표 (Economic Indicators)")
    with st.spinner('데이터 로딩 중...'):
        rate_val, rate_chg, rate_pct, rate_data = get_interest_rate_hybrid()
        exch_val, exch_chg, exch_pct, exch_data = get_yahoo_data("KRW=X", "10y")
        cpi_val, cpi_chg, cpi_pct, cpi_data = get_fred_data("CPIAUCSL", "yoy")
        core_val, core_chg, core_pct, core_data = get_fred_data("CPILFESL", "yoy")
        job_val, job_chg, job_pct, job_data = get_fred_data("PAYEMS", "diff")
        unemp_val, unemp_chg, unemp_pct, unemp_data = get_fred_data("UNRATE", "raw")

    # 1. 금융 시장 (금리/환율: 1개월 / 3개월 / 1년)
    draw_section_with_ai(
        "금융 시장 (금리 & 환율)",
        {'l': "미국 10년물 금리", 'v': rate_val, 'c': rate_chg, 'p': rate_pct, 'd': rate_data, 'col': "#f59e0b", 'prd': ["1개월", "3개월", "1년"], 'idx': 0, 'uc': "#f59e0b", 'dc': "#3b82f6", 'u': "%"},
        {'l': "원/달러 환율", 'v': exch_val, 'c': exch_chg, 'p': exch_pct, 'd': exch_data, 'col': "#10b981", 'prd': ["1개월", "3개월", "1년"], 'idx': 0, 'uc': "#10b981", 'dc': "#3b82f6", 'u': "원"},
        "finance", "금융 시장(금리, 환율)", f"금리: {rate_val}%, 환율: {exch_val}원"
    )

    # 2. 물가 지표 (6개월 / 1년 / 3년)
    draw_section_with_ai(
        "물가 지표 (인플레이션)",
        {'l': "헤드라인 CPI", 'v': cpi_val, 'c': cpi_chg, 'p': cpi_pct, 'd': cpi_data, 'col': "#ef4444", 'prd': ["6개월", "1년", "3년"], 'idx': 0, 'uc': "#ef4444", 'dc': "#3b82f6", 'u': "%"},
        {'l': "근원(Core) CPI", 'v': core_val, 'c': core_chg, 'p': core_pct, 'd': core_data, 'col': "#ef4444", 'prd': ["6개월", "1년", "3년"], 'idx': 0, 'uc': "#ef4444", 'dc': "#3b82f6", 'u': "%"},
        "inflation", "물가 지표(CPI)", f"헤드라인CPI: {cpi_val}%, 근원CPI: {core_val}%"
    )

    # 3. 고용 지표 (6개월 / 1년 / 3년)
    draw_section_with_ai(
        "고용 지표 (경기 & 고용)",
        {'l': "비농업 고용 지수", 'v': job_val, 'c': job_chg, 'p': job_pct, 'd': job_data, 'col': "#3b82f6", 'prd': ["6개월", "1년", "3년"], 'idx': 0, 'uc': "#3b82f6", 'dc': "#ef4444", 'u': "k"},
        {'l': "실업률", 'v': unemp_val, 'c': unemp_chg, 'p': unemp_pct, 'd': unemp_data, 'col': "#10b981", 'prd': ["6개월", "1년", "3년"], 'idx': 0, 'uc': "#10b981", 'dc': "#3b82f6", 'u': "%"},
        "employment", "고용 지표(실업률)", f"비농업고용: {job_val}k, 실업률: {unemp_val}%"
    )

elif menu == "시장 심리":
    st.title("시장 심리 (Market Sentiment)")
    
    st.markdown("""
    <div class="info-box">
        <strong>[지표 정의]</strong><br>
        • <strong>VIX (공포지수)</strong>: 향후 30일간 S&P 500 지수의 변동성에 대한 시장의 기대치를 나타냅니다.<br>
        • <strong>RSI (상대강도지수)</strong>: 일정 기간 동안 주가가 전일 대비 상승한 변화량과 하락한 변화량의 평균값을 구하여, 상승분 강도를 백분율로 나타낸 지표입니다.
    </div>
    """, unsafe_allow_html=True)

    st.markdown("<div class='section-header'>위험 및 과열 신호 (Gauge)</div>", unsafe_allow_html=True)
    with st.spinner("지표 분석 중..."):
        vix_curr, _, _, _ = get_yahoo_data("^VIX")
        _, _, _, sp_data = get_yahoo_data("^GSPC", "6mo")
        _, _, _, ks_data = get_yahoo_data("^KS11", "6mo")
        rsi_sp = calculate_rsi(sp_data)
        rsi_ks = calculate_rsi(ks_data)

    g1, g2, g3 = st.columns(3)
    with g1:
        if vix_curr: draw_gauge_chart("공포 지수 (VIX)", vix_curr, 0, 50, [20, 30])
        else: st.error("VIX 데이터 오류")
    with g2:
        if rsi_sp: draw_gauge_chart("RSI (S&P 500)", rsi_sp, 0, 100, [30, 70])
        else: st.error("RSI 데이터 오류")
    with g3:
        if rsi_ks: draw_gauge_chart("RSI (코스피)", rsi_ks, 0, 100, [30, 70])
        else: st.error("RSI 데이터 오류")

    st.markdown("<div class='section-header'>AI 심리 분석</div>", unsafe_allow_html=True)
    if st.button("📢 현재 시장 심리 AI 분석", use_container_width=True):
        title, content = analyze_market_ai("현재 시장 심리", f"VIX: {vix_curr:.2f}, S&P500 RSI: {rsi_sp:.2f}, 코스피 RSI: {rsi_ks:.2f}")
        st.markdown(f"<div class='ai-box'><div class='ai-title'>🤖 {title}</div><div class='ai-text'>{content}</div></div>", unsafe_allow_html=True)

elif menu == "시장 지도":
    st.title("시장 지도 (Market Map)")
    
    today_str = date.today().strftime('%Y-%m-%d')
    st.markdown(f"""
    <div class="info-box">
        S&P 500 주요 섹터(ETF)의 등락률을 통해 오늘의 자금 흐름을 한눈에 파악합니다.<br>
        <span style="font-size: 13px; color: #64748b;">기준일: {today_str}</span>
    </div>
    """, unsafe_allow_html=True)

    sectors = {
        'XLK': '기술 (Tech)',
        'XLV': '헬스케어 (Health)',
        'XLF': '금융 (Financials)',
        'XLY': '임의소비재 (Discret.)',
        'XLP': '필수소비재 (Staples)',
        'XLE': '에너지 (Energy)',
        'XLI': '산업재 (Industrial)',
        'XLU': '유틸리티 (Utilities)',
        'XLRE': '부동산 (Real Estate)',
        'XLB': '소재 (Materials)',
        'XLC': '통신 (Comm.)'
    }

    with st.spinner("섹터 데이터 분석 중..."):
        rows = []
        for ticker, name in sectors.items():
            try:
                d = yf.Ticker(ticker).history(period="5d")
                if len(d) >= 2:
                    curr = d['Close'].iloc[-1]
                    prev = d['Close'].iloc[-2]
                    chg = (curr - prev) / prev * 100
                    rows.append({'Sector': name, 'Change': chg})
            except:
                pass

    if rows:
        df_sector = pd.DataFrame(rows)
        df_sector = df_sector.sort_values('Change', ascending=False)
        df_sector['Color'] = df_sector['Change'].apply(lambda x: '#ef4444' if x > 0 else '#3b82f6')

        chart = alt.Chart(df_sector).mark_bar().encode(
            x=alt.X('Change', title='등락률 (%)', axis=alt.Axis(format='.2f')),
            y=alt.Y('Sector', sort='-x', title=None),
            color=alt.Color('Color', scale=None),
            tooltip=['Sector', alt.Tooltip('Change', format='.2f')]
        ).properties(height=450)

        st.altair_chart(chart, use_container_width=True)
    else:
        st.error("섹터 데이터를 불러올 수 없습니다.")

elif menu == "주요 일정":
    st.title("주요 일정 (Key Schedule)")

    fomc_dates_2026 = [
        date(2026, 1, 28), date(2026, 3, 18), date(2026, 4, 29), 
        date(2026, 6, 17), date(2026, 7, 29), date(2026, 9, 16), 
        date(2026, 10, 28), date(2026, 12, 9)
    ]
    today = date.today()
    next_fomc = None
    days_left = 0
    for d in fomc_dates_2026:
        if d >= today:
            next_fomc = d
            days_left = (d - today).days
            break
            
    if next_fomc:
        st.markdown(f"""
        <div class="d-day-container">
            <div class="d-day-title">Next FOMC Meeting</div>
            <div class="d-day-count">D-{days_left}</div>
            <div class="d-day-date">{next_fomc.strftime('%Y년 %m월 %d일')} (금리 결정)</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.info("2026년 FOMC 일정이 종료되었습니다.")

    st.markdown("<div class='section-header'>네 마녀의 날 (Quadruple Witching Day)</div>", unsafe_allow_html=True)
    
    st.markdown("""
    <div class="warning-box">
        매 분기(3, 6, 9, 12월) 셋째 주 금요일은 선물/옵션 만기일이 겹쳐 변동성이 극대화되는 날입니다.
    </div>
    """, unsafe_allow_html=True)
    
    witching_days_2026 = [date(2026, 3, 20), date(2026, 6, 19), date(2026, 9, 18), date(2026, 12, 18)]
    w_cols = st.columns(4)
    for i, d in enumerate(witching_days_2026):
        with w_cols[i]:
            bg_color = "#fee2e2" if d >= today and (d - today).days < 30 else "#ffffff"
            with st.container(border=True):
                st.markdown(f"**{d.month}월 만기일**")
                st.markdown(f"{d.strftime('%Y-%m-%d')}")

    st.markdown("<div class='section-header'>주요 휴장일 (미국 증시)</div>", unsafe_allow_html=True)
    holidays_2026 = {
        date(2026, 4, 3): "성금요일 (Good Friday)",
        date(2026, 5, 25): "메모리얼 데이 (Memorial Day)",
        date(2026, 6, 19): "준틴스 (Juneteenth)",
        date(2026, 7, 3): "독립기념일 (Independence Day)",
        date(2026, 9, 7): "노동절 (Labor Day)",
        date(2026, 11, 26): "추수감사절 (Thanksgiving Day)",
        date(2026, 12, 25): "크리스마스 (Christmas Day)"
    }
    
    upcoming_holidays = {d: n for d, n in holidays_2026.items() if d >= today}
    h_cols = st.columns(3)
    if upcoming_holidays:
        for i, (d, name) in enumerate(list(upcoming_holidays.items())[:3]):
            with h_cols[i]:
                with st.container(border=True):
                    st.markdown(f"**{name}**")
                    st.markdown(f"<span style='color:#6b7280; font-weight:bold;'>{d.strftime('%Y-%m-%d')}</span>", unsafe_allow_html=True)
    else:
        st.write("올해 남은 휴장일이 없습니다.")

# -----------------------------------------------------------------------------
# 7. 공통 푸터 (투자 면책 조항)
# -----------------------------------------------------------------------------
st.markdown("""
<div class="footer-disclaimer">
    <strong>[면책 조항]</strong> 본 웹사이트에서 제공하는 모든 데이터 및 AI 분석 정보는 투자 참고용입니다.<br>
    시장의 변동성이나 데이터 제공처의 사정에 따라 정보의 정확성이나 완벽성을 보장할 수 없으며, 투자에 대한 최종 판단과 책임은 전적으로 투자자 본인에게 있습니다.
</div>
""", unsafe_allow_html=True)
