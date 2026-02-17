import streamlit as st
import pandas as pd
import openai
import yfinance as yf
import requests
import altair as alt
import plotly.graph_objects as go
from io import StringIO
import time
from datetime import datetime, date, timedelta  # 🚨 timedelta 포함됨

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
    /* 1. 폰트 적용 (Pretendard) */
    @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');
    
    html, body, .stApp {
        font-family: 'Pretendard', sans-serif !important;
    }
    
    /* 2. 전체 배경색 */
    .stApp {
        background-color: #f5f7f9;
    }

    /* 3. 섹션 헤더 디자인 */
    .section-header {
        font-size: 20px;
        font-weight: 700;
        color: #111827;
        margin-top: 25px;
        margin-bottom: 15px;
        border-left: 4px solid #111827;
        padding-left: 10px;
    }

    /* 4. 카드 UI */
    div[data-testid="stVerticalBlockBorderWrapper"] {
        background-color: #ffffff;
        border: 1px solid #e5e7eb;
        border-radius: 12px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        padding: 20px;
        margin-bottom: 15px;
    }

    /* 5. D-Day 카운터 스타일 (진한 네이비) */
    .d-day-card {
        background-color: #1e293b;
        color: white;
        padding: 25px;
        border-radius: 16px;
        text-align: center;
        margin-bottom: 20px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .d-day-title { font-size: 15px; font-weight: 500; color: #94a3b8; margin-bottom: 8px; letter-spacing: 1px; }
    .d-day-count { font-size: 48px; font-weight: 800; color: #ffffff; line-height: 1; }
    .d-day-date { font-size: 16px; color: #cbd5e1; margin-top: 10px; font-weight: 500; }

    /* 6. AI 분석 박스 */
    .ai-box { background-color: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 20px; margin-top: 20px; }
    .ai-title { font-weight: 700; font-size: 18px; margin-bottom: 10px; color: #111827; }
    .ai-text { font-size: 15px; line-height: 1.7; color: #374151; }

    </style>
    """, unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 2. 사이드바 (메뉴 4개로 분리)
# -----------------------------------------------------------------------------
with st.sidebar:
    st.title("Market Logic")
    
    menu = st.radio("메뉴 선택", [
        "주가 지수", 
        "투자 관련 지표", 
        "시장 심리 (Sentiment)", 
        "주요 경제 일정"
    ], index=0)
    
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

# --- RSI 계산 함수 ---
def calculate_rsi(data, window=14):
    if data is None or len(data) < window: return None
    delta = data['Value'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1]

# -----------------------------------------------------------------------------
# 4. 차트 및 시각화 컴포넌트
# -----------------------------------------------------------------------------
def create_chart(data, color, height=180):
    if data is None or data.empty: return st.error("데이터 없음")
    chart = alt.Chart(data).mark_line(color=color, strokeWidth=2).encode(
        x=alt.X('Date:T', axis=alt.Axis(format='%y-%m', title=None, grid=False)),
        y=alt.Y('Value:Q', scale=alt.Scale(zero=False), axis=alt.Axis(title=None)),
        tooltip=['Date:T', alt.Tooltip('Value', format=',.2f')]
    ).properties(height=height).interactive()
    return st.altair_chart(chart, use_container_width=True)

def styled_metric(label, value, change, pct_change, unit="", up_color="#ef4444", down_color="#3b82f6"):
    if value is None: 
        st.metric(label, "-")
        return
    
    if change > 0:
        color, bg_color, arrow, sign = up_color, f"{up_color}15", "▲", "+"
    elif change < 0:
        color, bg_color, arrow, sign = down_color, f"{down_color}15", "▼", ""
    else:
        color, bg_color, arrow, sign = "#6b7280", "#f3f4f6", "-", ""

    st.markdown(f"""
    <div style="display: flex; flex-direction: column; justify-content: center;">
        <div style="font-size: 13px; font-weight: 600; color: #6b7280; margin-bottom: 4px; text-transform: uppercase;">{label}</div>
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
                period = st.radio("기간", periods, index=default_idx, key=key, horizontal=True, label_visibility="collapsed")
        else:
            styled_metric(label, val, chg, pct, unit, up_c, down_c)
            st.markdown('<div style="height: 10px;"></div>', unsafe_allow_html=True)
            period = st.radio("기간", periods, index=default_idx, key=key, horizontal=True, label_visibility="collapsed")
        
        st.markdown('<div style="margin-top: 15px;"></div>', unsafe_allow_html=True)
        # 차트 그리기 헬퍼
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

        create_chart(filter_data_by_period(data, period), color, height=180)

# -----------------------------------------------------------------------------
# 5. 계기판(Gauge) 차트 그리기
# -----------------------------------------------------------------------------
def draw_gauge_chart(title, value, min_val, max_val, thresholds, inverse=False):
    """
    thresholds: [녹색 구간 끝, 노란색 구간 끝]
    """
    # 색상 결정 로직
    steps = []
    bar_color = "black"
    
    if "공포" in title: # VIX
        steps = [
            {'range': [0, 20], 'color': "#dcfce7"},
            {'range': [20, 30], 'color': "#fef9c3"},
            {'range': [30, 100], 'color': "#fee2e2"}
        ]
        if value < 20: bar_color = "#16a34a"
        elif value < 30: bar_color = "#ca8a04"
        else: bar_color = "#dc2626"
        
    elif "RSI" in title: # RSI
        steps = [
            {'range': [0, 30], 'color': "#dcfce7"},
            {'range': [30, 70], 'color': "#f3f4f6"},
            {'range': [70, 100], 'color': "#fee2e2"}
        ]
        if value < 30: bar_color = "#16a34a"
        elif value > 70: bar_color = "#dc2626"
        else: bar_color = "#4b5563"

    fig = go.Figure(go.Indicator(
        mode = "gauge+number",
        value = value,
        title = {'text': title, 'font': {'size': 18, 'color': "#374151"}},
        gauge = {
            'axis': {'range': [min_val, max_val], 'tickwidth': 1, 'tickcolor': "#374151"},
            'bar': {'color': bar_color},
            'bgcolor': "white",
            'borderwidth': 2,
            'bordercolor': "white",
            'steps': steps,
            'threshold': {
                'line': {'color': "red", 'width': 4},
                'thickness': 0.75,
                'value': value
            }
        }
    ))
    
    fig.update_layout(
        height=250, 
        margin=dict(l=20, r=20, t=50, b=20),
        paper_bgcolor='rgba(0,0,0,0)',
        font={'family': "Pretendard"}
    )
    st.plotly_chart(fig, use_container_width=True)

# -----------------------------------------------------------------------------
# 6. AI 분석 엔진
# -----------------------------------------------------------------------------
if 'ai_results' not in st.session_state: st.session_state['ai_results'] = {}

def analyze_market_ai(topic, data_summary):
    if not api_key: return "API Key 필요", "설정 탭에서 API Key를 입력해주세요."
    
    client = openai.OpenAI(api_key=api_key)
    prompt = f"""
    당신은 글로벌 매크로 전략가입니다.
    주제: {topic}
    데이터: {data_summary}
    
    [작성 양식]
    1. **한줄 요약**: (시장 심리나 상태를 정의하는 1문장)
    2. **상세 분석**: (불렛포인트로 핵심만 간결하게)
    3. **대응 전략**: (투자자가 취해야 할 행동)
    
    한국어로 작성하세요.
    """
    try:
        resp = client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": prompt}])
        return "AI 분석 결과", resp.choices[0].message.content
    except Exception as e: return "오류 발생", str(e)

# -----------------------------------------------------------------------------
# 7. 메인 페이지 로직
# -----------------------------------------------------------------------------

# [메뉴 1] 주가 지수
if menu == "주가 지수":
    st.title("글로벌 시장 지수")
    with st.spinner("데이터 로딩 중..."):
        dow_v, dow_c, dow_p, dow_d = get_yahoo_data("DIA")
        sp_v, sp_c, sp_p, sp_d = get_yahoo_data("^GSPC")
        nas_v, nas_c, nas_p, nas_d = get_yahoo_data("^IXIC")
        kospi_v, kospi_c, kospi_p, kospi_d = get_yahoo_data("^KS11")
        kosdaq_v, kosdaq_c, kosdaq_p, kosdaq_d = get_yahoo_data("^KQ11")

    st.markdown("<div class='section-header'>미국 3대 지수 (US Market)</div>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1: draw_chart_unit("다우존스 (ETF)", dow_v, dow_c, dow_p, dow_d, "#10b981", ["1개월", "3개월", "1년", "전체"], 2, "dow", "#10b981", "#ef4444", "", False)
    with c2: draw_chart_unit("S&P 500", sp_v, sp_c, sp_p, sp_d, "#10b981", ["1개월", "3개월", "1년", "전체"], 2, "sp500", "#10b981", "#ef4444", "", False)
    with c3: draw_chart_unit("나스닥 100", nas_v, nas_c, nas_p, nas_d, "#10b981", ["1개월", "3개월", "1년", "전체"], 2, "nasdaq", "#10b981", "#ef4444", "", False)
    
    st.markdown("<div style='height: 30px'></div>", unsafe_allow_html=True)

    st.markdown("<div class='section-header'>국내 증시 (KR Market)</div>", unsafe_allow_html=True)
    c4, c5 = st.columns(2)
    with c4: draw_chart_unit("코스피 (KOSPI)", kospi_v, kospi_c, kospi_p, kospi_d, "#ef4444", ["1개월", "3개월", "6개월", "1년"], 3, "kospi", "#ef4444", "#3b82f6", "", True)
    with c5: draw_chart_unit("코스닥 (KOSDAQ)", kosdaq_v, kosdaq_c, kosdaq_p, kosdaq_d, "#ef4444", ["1개월", "3개월", "6개월", "1년"], 3, "kosdaq", "#ef4444", "#3b82f6", "", True)

# [메뉴 2] 투자 관련 지표 (복구 완료!)
elif menu == "투자 관련 지표":
    st.title("경제 지표 (Economic Indicators)")
    with st.spinner('데이터 로딩 중...'):
        rate_val, rate_chg, rate_pct, rate_data = get_interest_rate_hybrid()
        exch_val, exch_chg, exch_pct, exch_data = get_yahoo_data("KRW=X", "10y")
        cpi_val, cpi_chg, cpi_pct, cpi_data = get_fred_data("CPIAUCSL", "yoy")
        core_val, core_chg, core_pct, core_data = get_fred_data("CPILFESL", "yoy")
        # 🚨 고용 데이터 복구
        job_val, job_chg, job_pct, job_data = get_fred_data("PAYEMS", "diff")
        unemp_val, unemp_chg, unemp_pct, unemp_data = get_fred_data("UNRATE", "raw")

    st.markdown("<div class='section-header'>금융 시장 (금리 & 환율)</div>", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1: draw_chart_unit("미국 10년물 금리", rate_val, rate_chg, rate_pct, rate_data, "#f59e0b", ["1개월", "1년", "전체"], 1, "rate", "#f59e0b", "#3b82f6", "%", True)
    with c2: draw_chart_unit("원/달러 환율", exch_val, exch_chg, exch_pct, exch_data, "#10b981", ["1개월", "1년", "전체"], 1, "exch", "#10b981", "#3b82f6", "원", True)

    st.markdown("<div style='height: 20px'></div>", unsafe_allow_html=True)

    st.markdown("<div class='section-header'>물가 지표 (인플레이션)</div>", unsafe_allow_html=True)
    c3, c4 = st.columns(2)
    with c3: draw_chart_unit("헤드라인 CPI (전년비)", cpi_val, cpi_chg, cpi_pct, cpi_data, "#ef4444", ["1년", "5년", "전체"], 1, "cpi", "#ef4444", "#3b82f6", "%", True)
    with c4: draw_chart_unit("근원(Core) CPI (전년비)", core_val, core_chg, core_pct, core_data, "#ef4444", ["1년", "5년", "전체"], 1, "core", "#ef4444", "#3b82f6", "%", True)

    st.markdown("<div style='height: 20px'></div>", unsafe_allow_html=True)

    # 🚨 고용 지표 섹션 복구
    st.markdown("<div class='section-header'>고용 지표 (경기 & 고용)</div>", unsafe_allow_html=True)
    c5, c6 = st.columns(2)
    with c5: draw_chart_unit("비농업 고용 지수 (전월비)", job_val, job_chg, job_pct, job_data, "#3b82f6", ["1년", "5년", "전체"], 1, "job", "#3b82f6", "#ef4444", "k", True)
    with c6: draw_chart_unit("실업률", unemp_val, unemp_chg, unemp_pct, unemp_data, "#10b981", ["1년", "5년", "전체"], 1, "unemp", "#10b981", "#3b82f6", "%", True)

    # 🚨 AI 분석 버튼 복구
    st.markdown("<div class='section-header'>AI 경제 분석</div>", unsafe_allow_html=True)
    if st.button("📢 현재 경제 지표 AI 분석", use_container_width=True):
        summary_text = f"금리: {rate_val}%, 환율: {exch_val}원, CPI: {cpi_val}%, 실업률: {unemp_val}%"
        title, content = analyze_market_ai("현재 거시경제 및 금융시장 분석", summary_text)
        
        st.markdown(f"""
        <div class="ai-box">
            <div class="ai-title">🤖 {title}</div>
            <div class="ai-text">{content}</div>
        </div>
        """, unsafe_allow_html=True)

# [메뉴 3] 시장 심리 (Sentiment)
elif menu == "시장 심리 (Sentiment)":
    st.title("시장 심리 (Market Sentiment)")
    st.info("💡 **계기판 보는 법**: 바늘이 **초록색**이면 기회(침체/안정), **빨간색**이면 위험(과열/공포) 구간을 의미합니다.")

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
        summary_text = f"VIX(공포지수): {vix_curr:.2f}, S&P500 RSI: {rsi_sp:.2f}, 코스피 RSI: {rsi_ks:.2f}"
        title, content = analyze_market_ai("현재 시장 심리 및 대응 전략", summary_text)
        
        st.markdown(f"""
        <div class="ai-box">
            <div class="ai-title">🤖 {title}</div>
            <div class="ai-text">{content}</div>
        </div>
        """, unsafe_allow_html=True)

# [메뉴 4] 주요 경제 일정 (Macro Calendar)
elif menu == "주요 경제 일정":
    st.title("주요 경제 일정 (Macro Calendar)")

    # 1. FOMC D-Day
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
        <div class="d-day-card">
            <div class="d-day-title">NEXT FOMC MEETING</div>
            <div class="d-day-count">D-{days_left}</div>
            <div class="d-day-date">{next_fomc.strftime('%Y년 %m월 %d일')} (금리 결정)</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.info("2026년 FOMC 일정이 모두 종료되었습니다.")

    # 2. 주요 휴장일 정보
    st.markdown("<div class='section-header'>주요 휴장일 (미국 증시)</div>", unsafe_allow_html=True)
    holidays_2026 = {
        date(2026, 1, 1): "새해 첫날 (New Year's Day)",
        date(2026, 1, 19): "마틴 루터 킹 데이",
        date(2026, 2, 16): "대통령의 날 (Washington's Birthday)",
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
