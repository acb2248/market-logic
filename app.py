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
# 1. 페이지 설정 및 CSS
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
    
    html, body, .stApp {
        font-family: 'Pretendard', sans-serif !important;
    }
    
    /* 2. 전체 배경색 */
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
    }

    /* 5. 라디오 버튼 디자인 */
    div[data-testid="stBlock"] div[role="radiogroup"] {
        background-color: transparent !important;
        flex-direction: row !important;
        gap: 6px !important;
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
    }

    /* 6. 사이드바 스타일 */
    section[data-testid="stSidebar"] {
        background-color: #ffffff;
        border-right: 1px solid #e5e7eb;
    }
    
    /* AI 답변 스타일 */
    .ai-headline { font-size: 17px; font-weight: 800; color: #111827; margin-bottom: 8px; line-height: 1.4; }
    .ai-details { font-size: 14px; line-height: 1.6; color: #374151; background-color: #f9fafb; padding: 15px; border-radius: 8px; border: 1px solid #e5e7eb; }
    
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
    menu = st.radio("메뉴", ["주가 지수", "투자 관련 지표", "📈 유망 종목 스캐너"], index=0)
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

# --- 스캐너용 데이터 함수 (Volume, High, Low 필요) ---
def get_scanner_data(ticker):
    try:
        df = yf.download(ticker, period="6mo", progress=False)
        if df.empty: return None
        # 멀티인덱스 처리 (yfinance 최신버전 대응)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df
    except: return None

def calculate_accumulation_score(df):
    """매집 점수 계산 (장기이평선 위 + 변동성 축소 + 거래량 증가)"""
    if len(df) < 100: return 0, "데이터 부족"
    
    df['MA60'] = df['Close'].rolling(window=60).mean()
    df['Vol20'] = df['Volume'].rolling(window=20).mean()
    
    curr_price = df['Close'].iloc[-1]
    ma60 = df['MA60'].iloc[-1]
    
    # 1. 추세 (60일선 위)
    trend_score = 1 if curr_price >= ma60 else 0
    
    # 2. 변동성 (최근 20일 고저폭 15% 이내)
    recent_high = df['High'].tail(20).max()
    recent_low = df['Low'].tail(20).min()
    volatility = (recent_high - recent_low) / recent_low
    vol_score = 1 if volatility < 0.15 else 0
    
    # 3. 수급 (최근 5일 평균 거래량이 20일 평균보다 10% 이상 증가)
    recent_vol = df['Volume'].tail(5).mean()
    avg_vol = df['Vol20'].iloc[-1]
    volume_score = 1 if recent_vol > avg_vol * 1.1 else 0
    
    total = trend_score + vol_score + volume_score
    reasons = []
    if trend_score: reasons.append("추세 우상향")
    if vol_score: reasons.append("기간 조정 중")
    if volume_score: reasons.append("수급 유입")
    
    return total, ", ".join(reasons)

# -----------------------------------------------------------------------------
# 4. 차트 및 UI 컴포넌트
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
            <div style="font-size: 28px; font-weight: 800; color: #111827;">{value:,.2f}<span style="font-size: 18px; color: #9ca3af; margin-left: 2px;">{unit}</span></div>
            <div style="font-size: 13px; font-weight: 700; color: {color}; background-color: {bg_color}; padding: 4px 8px; border-radius: 6px;">
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
        create_chart(filter_data_by_period(data, period), color, height=180)

# -----------------------------------------------------------------------------
# 5. AI 분석 엔진 (4가지 지표 포함)
# -----------------------------------------------------------------------------
if 'ai_results' not in st.session_state: st.session_state['ai_results'] = {}

def analyze_sector(sector_name, data_summary):
    if not api_key: return "YELLOW", "API 키 필요", "설정 탭에서 API Key를 입력해주세요."
    
    client = openai.OpenAI(api_key=api_key)
    
    # 요청하신 4가지 지표를 포함한 프롬프트
    prompt = f"""
    당신은 글로벌 헤지펀드 매니저입니다. 데이터: {data_summary}
    주제: {sector_name}
    
    [필수 작성 항목]
    1. SIGNAL: (RED/YELLOW/GREEN 중 택1)
    2. HEADLINE: (핵심을 찌르는 1줄 요약)
    3. DETAILS: 아래 형식으로 작성 (Markdown)
       - 📊 **Thoroughness Score**: (0~100점, 분석 신뢰도)
       - 🛡️ **Risk & Counter-argument**: (치명적 리스크 1가지)
       - 🔮 **Future Strategy**: (단기 대응 전략 1줄)
       - 🏷️ **Keywords**: (관련 심층 키워드 3개 해시태그)
       - ❓ **Engagement Trigger**: (통찰을 주는 질문 1개)
    
    답변은 반드시 한국어로, 전문적이지만 읽기 쉽게 작성하세요.
    """
    try:
        resp = client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": prompt}])
        text = resp.choices[0].message.content
        
        signal = "RED" if "RED" in text else "GREEN" if "GREEN" in text else "YELLOW"
        
        # 파싱 로직 강화
        if "HEADLINE:" in text:
            parts = text.split("HEADLINE:")
            headline = parts[1].split("DETAILS:")[0].strip()
            details = parts[1].split("DETAILS:")[1].strip()
        else:
            headline = "분석 완료"
            details = text
            
        return signal, headline, details
    except Exception as e: return "YELLOW", "오류 발생", f"분석 중 문제가 생겼습니다: {str(e)}"

def draw_ai_section(key_prefix, chart1, chart2):
    with st.container(border=True):
        st.markdown(f"<div style='font-size: 16px; font-weight: 700; color: #111827; margin-bottom: 10px;'>🤖 {key_prefix} AI 분석</div>", unsafe_allow_html=True)
        
        if st.button("⚡ 정밀 분석 실행", key=f"btn_{key_prefix}", use_container_width=True):
            data_sum = f"{chart1['label']}={chart1['val']}, {chart2['label']}={chart2['val']}"
            sig, head, det = analyze_sector(key_prefix, data_sum)
            st.session_state['ai_results'][key_prefix.lower()] = {'signal': sig, 'headline': head, 'details': det}
        
        res = st.session_state['ai_results'].get(key_prefix.lower(), {'signal': None, 'headline': None})
        
        # 신호등 표시
        r = "active" if res['signal'] == "RED" else ""
        y = "active" if res['signal'] == "YELLOW" else ""
        g = "active" if res['signal'] == "GREEN" else ""
        
        if res['signal']:
            st.markdown(f"""
            <div class="signal-box" style="margin-top: 15px;">
                <div class="light red {r}"></div>
                <div class="light yellow {y}"></div>
                <div class="light green {g}"></div>
            </div>
            """, unsafe_allow_html=True)
            
            st.markdown(f"<div class='ai-headline'>{res['headline']}</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='ai-details'>{res['details']}</div>", unsafe_allow_html=True)
        else:
            st.info("버튼을 눌러 4가지 지표가 포함된 리포트를 받아보세요.")

# -----------------------------------------------------------------------------
# 6. 메인 페이지 로직
# -----------------------------------------------------------------------------
if menu == "주가 지수":
    st.title("글로벌 시장 지수")
    
    with st.spinner("데이터 로딩 중..."):
        # 다우존스는 ETF(DIA)로 대체 (안정성 확보)
        dow_v, dow_c, dow_p, dow_d = get_yahoo_data("DIA")
        sp_v, sp_c, sp_p, sp_d = get_yahoo_data("^GSPC")
        nas_v, nas_c, nas_p, nas_d = get_yahoo_data("^IXIC")
        kospi_v, kospi_c, kospi_p, kospi_d = get_yahoo_data("^KS11")
        kosdaq_v, kosdaq_c, kosdaq_p, kosdaq_d = get_yahoo_data("^KQ11")

    # [1] 미국
    st.markdown("<div class='section-header'>미국 3대 지수 (US Market)</div>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1: draw_chart_unit("Dow Jones (ETF)", dow_v, dow_c, dow_p, dow_d, "#10b981", ["1개월", "3개월", "1년", "전체"], 2, "dow", "#10b981", "#ef4444", "", False)
    with c2: draw_chart_unit("S&P 500", sp_v, sp_c, sp_p, sp_d, "#10b981", ["1개월", "3개월", "1년", "전체"], 2, "sp500", "#10b981", "#ef4444", "", False)
    with c3: draw_chart_unit("Nasdaq 100", nas_v, nas_c, nas_p, nas_d, "#10b981", ["1개월", "3개월", "1년", "전체"], 2, "nasdaq", "#10b981", "#ef4444", "", False)
    
    st.markdown("<div style='height: 30px'></div>", unsafe_allow_html=True)

    # [2] 한국
    st.markdown("<div class='section-header'>국내 증시 (KR Market)</div>", unsafe_allow_html=True)
    c4, c5 = st.columns(2)
    with c4: draw_chart_unit("KOSPI", kospi_v, kospi_c, kospi_p, kospi_d, "#ef4444", ["1개월", "3개월", "6개월", "1년", "전체"], 3, "kospi", "#ef4444", "#3b82f6", "", True)
    with c5: draw_chart_unit("KOSDAQ", kosdaq_v, kosdaq_c, kosdaq_p, kosdaq_d, "#ef4444", ["1개월", "3개월", "6개월", "1년", "전체"], 3, "kosdaq", "#ef4444", "#3b82f6", "", True)

elif menu == "투자 관련 지표":
    st.title("경제 지표 & AI 분석")

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

# -----------------------------------------------------------------------------
# 7. 신규 기능: 유망 종목 스캐너 (Beta)
# -----------------------------------------------------------------------------
elif menu == "📈 유망 종목 스캐너":
    st.title("📈 유망 매집(Accumulation) 종목 발굴")
    st.info("""
    💡 **Weinstein Stage Analysis 기반**: 
    1. **추세**: 60일 이평선 위에 주가가 형성되어야 함.
    2. **기간 조정**: 최근 가격 변동성이 낮아야 함 (바닥 다지기).
    3. **수급**: 평소보다 거래량이 증가하는 '매집' 신호가 보여야 함.
    """)

    # 분석 대상 (주요 섹터 대장주)
    target_sectors = {
        "반도체/IT": ["005930.KS", "000660.KS", "042700.KS"],
        "배터리/2차전지": ["373220.KS", "006400.KS", "003670.KS"],
        "자동차/모빌리티": ["005380.KS", "000270.KS", "012330.KS"],
        "바이오/헬스케어": ["207940.KS", "068270.KS", "000100.KS"],
        "플랫폼/게임": ["035420.KS", "035720.KS", "259960.KS"],
        "금융/지주": ["105560.KS", "055550.KS", "086790.KS"]
    }

    selected_sector = st.selectbox("분석할 섹터를 선택하세요", list(target_sectors.keys()))
    
    if st.button("🔍 스캔 시작", use_container_width=True):
        tickers = target_sectors[selected_sector]
        results = []
        progress = st.progress(0)
        
        for idx, t in enumerate(tickers):
            df = get_scanner_data(t)
            if df is not None:
                score, reason = calculate_accumulation_score(df)
                price = df['Close'].iloc[-1]
                results.append({"티커": t, "현재가": price, "매집 점수": score, "포착 사유": reason})
            progress.progress((idx + 1) / len(tickers))
        
        progress.empty()
        
        if results:
            res_df = pd.DataFrame(results).sort_values(by="매집 점수", ascending=False)
            
            st.markdown("### 📊 분석 결과")
            st.dataframe(
                res_df,
                column_config={
                    "현재가": st.column_config.NumberColumn(format="%d원"),
                    "매집 점수": st.column_config.ProgressColumn(
                        "매집 강도 (3점 만점)", min_value=0, max_value=3, format="%d점"
                    )
                },
                hide_index=True,
                use_container_width=True
            )
            
            # 1위 종목 AI 코멘트
            best = res_df.iloc[0]
            if best['매집 점수'] >= 2:
                st.success(f"🏆 Top Pick: **{best['티커']}** - {best['포착 사유']}")
        else:
            st.warning("데이터를 가져올 수 없습니다.")
