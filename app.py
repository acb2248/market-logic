import streamlit as st
import pandas as pd
import openai
import yfinance as yf
import requests
import altair as alt
from io import StringIO
import time

# -----------------------------------------------------------------------------
# 1. 페이지 설정
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Market Logic Pro", page_icon="🚥", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
    <style>
    .stApp { background-color: #f8f9fa; }
    
    /* 차트 박스 */
    div[data-testid="metric-container"] {
        background-color: white; border-radius: 12px;
        box-shadow: 0 2px 5px rgba(0,0,0,0.05); padding: 15px; border: 1px solid #eee;
    }
    
    /* 신호등 박스 */
    .signal-box {
        background-color: #2b2b2b; color: white;
        border-radius: 15px; padding: 15px; text-align: center;
        box-shadow: 0 4px 15px rgba(0,0,0,0.2); height: 100%;
        display: flex; flex-direction: column; justify-content: center; align-items: center;
    }
    
    .light {
        width: 35px; height: 35px; border-radius: 50%;
        background: #555; opacity: 0.3; margin: 5px; display: inline-block;
        transition: all 0.3s ease;
    }
    
    .red.active { background: #ff4b4b; opacity: 1; box-shadow: 0 0 15px #ff4b4b; transform: scale(1.1); }
    .yellow.active { background: #ffca28; opacity: 1; box-shadow: 0 0 15px #ffca28; transform: scale(1.1); }
    .green.active { background: #00e676; opacity: 1; box-shadow: 0 0 15px #00e676; transform: scale(1.1); }
    
    .comment-box {
        background: #444; color: #ddd; padding: 10px; border-radius: 8px;
        margin-top: 10px; font-size: 13px; text-align: left; line-height: 1.4; width: 100%;
    }
    .sector-title { font-size: 16px; font-weight: bold; margin-bottom: 10px; color: #fff; }
    </style>
    """, unsafe_allow_html=True)

st.title("🚥 Market Logic: 섹터별 정밀 분석")
st.caption("3가지 핵심 분야(시장/물가/경기)를 개별 진단합니다.")

# -----------------------------------------------------------------------------
# 2. 사이드바 및 API
# -----------------------------------------------------------------------------
with st.sidebar:
    st.header("🛠 설정")
    if st.button("🔄 전체 데이터 새로고침"): st.rerun()
    st.divider()
    if "openai_api_key" in st.secrets:
        api_key = st.secrets["openai_api_key"]
        st.success("🔐 AI 연결됨")
    else:
        api_key = st.text_input("OpenAI API Key", type="password")

# -----------------------------------------------------------------------------
# 3. 데이터 엔진
# -----------------------------------------------------------------------------
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
                df = df.dropna().tail(24)
                return df['Value'].iloc[-1], df['Value'].iloc[-1]-df['Value'].iloc[-2], df.index[-1].strftime('%Y-%m'), df.reset_index()
        except: time.sleep(1); continue
    return None, None, None, None

@st.cache_data(ttl=3600)
def get_yahoo_data(ticker):
    try:
        data = yf.Ticker(ticker).history(period="1y")
        if len(data) > 1:
            curr = data['Close'].iloc[-1]
            change = curr - data['Close'].iloc[-2]
            chart_df = data[['Close']].reset_index()
            chart_df.columns = ['Date', 'Value']
            chart_df['Date'] = chart_df['Date'].dt.tz_localize(None)
            return curr, change, data.index[-1].strftime('%Y-%m-%d'), chart_df
    except: pass
    return None, None, None, None

def get_interest_rate_hybrid():
    res = get_yahoo_data("^TNX")
    if res: return res
    return get_fred_data("DGS10", "raw")

# ⭐ 차트 함수 복구 (안전한 방식)
def create_chart(data, color):
    if data is None: return st.error("No Data")
    
    base = alt.Chart(data).encode(
        x=alt.X('Date:T', axis=None), 
        tooltip=['Date:T', alt.Tooltip('Value', format=',.2f')]
    )
    
    # 그라데이션 대신 '투명도(opacity)'를 사용한 영역 채우기 (에러 없음!)
    area = base.mark_area(
        line={'color': color}, 
        color=color, 
        opacity=0.1  # 은은하게 채우기
    ).encode(
        y=alt.Y('Value:Q', scale=alt.Scale(zero=False), axis=None)
    )
    
    return st.altair_chart(area.interactive(), use_container_width=True)

# -----------------------------------------------------------------------------
# 4. 데이터 로딩
# -----------------------------------------------------------------------------
with st.spinner('데이터 분석 중...'):
    rate_val, rate_chg, _, rate_data = get_interest_rate_hybrid()
    exch_val, exch_chg, _, exch_data = get_yahoo_data("KRW=X")
    cpi_val, cpi_chg, _, cpi_data = get_fred_data("CPIAUCSL", "yoy")
    core_val, core_chg, _, core_data = get_fred_data("CPILFESL", "yoy")
    job_val, job_chg, _, job_data = get_fred_data("PAYEMS", "diff")
    unemp_val, unemp_chg, _, unemp_data = get_fred_data("UNRATE", "raw")

# -----------------------------------------------------------------------------
# 5. AI 분석 로직
# -----------------------------------------------------------------------------
if 'signals' not in st.session_state:
    st.session_state['signals'] = {'market': 'OFF', 'inflation': 'OFF', 'economy': 'OFF'}
    st.session_state['comments'] = {'market': '분석 대기', 'inflation': '분석 대기', 'economy': '분석 대기'}

if st.button("🚀 전체 섹터 AI 진단 실행 (Click)", type="primary", use_container_width=True):
    if not api_key: st.error("API 키 필요")
    else:
        with st.spinner("3개 섹터 동시 분석 중..."):
            try:
                client = openai.OpenAI(api_key=api_key)
                prompt = f"""
                당신은 버너드 보몰입니다. 3개 섹터를 분석하세요.
                
                [Data]
                1. MARKET: Rate {rate_val:.2f}, Exch {exch_val:.0f}
                2. INFLATION: CPI {cpi_val:.2f}, Core {core_val:.2f}
                3. ECONOMY: Job {job_val}, Unemp {unemp_val:.1f}

                [Output Format]
                Strictly use this format with '|||' separator:
                MARKET_SIGNAL: (RED or YELLOW or GREEN)
                MARKET_COMMENT: (1 sentence summary)
                |||
                INFLATION_SIGNAL: (RED or YELLOW or GREEN)
                INFLATION_COMMENT: (1 sentence summary)
                |||
                ECONOMY_SIGNAL: (RED or YELLOW or GREEN)
                ECONOMY_COMMENT: (1 sentence summary)
                """
                response = client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": prompt}])
                text = response.choices[0].message.content
                
                parts = text.split('|||')
                for part in parts:
                    if "MARKET_SIGNAL" in part:
                        st.session_state['signals']['market'] = "RED" if "RED" in part else "GREEN" if "GREEN" in part else "YELLOW"
                        st.session_state['comments']['market'] = part.split("COMMENT:")[1].strip()
                    elif "INFLATION_SIGNAL" in part:
                        st.session_state['signals']['inflation'] = "RED" if "RED" in part else "GREEN" if "GREEN" in part else "YELLOW"
                        st.session_state['comments']['inflation'] = part.split("COMMENT:")[1].strip()
                    elif "ECONOMY_SIGNAL" in part:
                        st.session_state['signals']['economy'] = "RED" if "RED" in part else "GREEN" if "GREEN" in part else "YELLOW"
                        st.session_state['comments']['economy'] = part.split("COMMENT:")[1].strip()
            except Exception as e: st.error(f"Error: {e}")

# -----------------------------------------------------------------------------
# 6. 신호등 UI 함수
# -----------------------------------------------------------------------------
def draw_signal_box(title, signal, comment):
    r = "active" if signal == "RED" else ""
    y = "active" if signal == "YELLOW" else ""
    g = "active" if signal == "GREEN" else ""
    
    st.markdown(f"""
    <div class="signal-box">
        <div class="sector-title">{title}</div>
        <div>
            <div class="light red {r}"></div>
            <div class="light yellow {y}"></div>
            <div class="light green {g}"></div>
        </div>
        <div class="comment-box">{comment}</div>
    </div>
    """, unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 7. 메인 레이아웃 (3단 구성)
# -----------------------------------------------------------------------------

# Row 1: 시장
st.subheader("1. Money Flow (시장)")
col1, col2, col3 = st.columns([3, 3, 2])
with col1:
    st.metric("美 10년물 금리", f"{rate_val:.2f}%", f"{rate_chg:.2f}%")
    create_chart(rate_data, "#d32f2f")
with col2:
    st.metric("원/달러 환율", f"{exch_val:.2f}원", f"{exch_chg:.2f}원")
    create_chart(exch_data, "#1976d2")
with col3:
    draw_signal_box("Market Signal", st.session_state['signals']['market'], st.session_state['comments']['market'])

st.divider()

# Row 2: 물가
st.subheader("2. Inflation (물가)")
col4, col5, col6 = st.columns([3, 3, 2])
with col4:
    st.metric("헤드라인 CPI (YoY)", f"{cpi_val:.2f}%", f"{cpi_chg:.2f}%p")
    create_chart(cpi_data, "#f57c00")
with col5:
    st.metric("근원(Core) CPI (YoY)", f"{core_val:.2f}%", f"{core_chg:.2f}%p")
    create_chart(core_data, "#7b1fa2")
with col6:
    draw_signal_box("Inflation Signal", st.session_state['signals']['inflation'], st.session_state['comments']['inflation'])

st.divider()

# Row 3: 경기
st.subheader("3. Economy (경기)")
col7, col8, col9 = st.columns([3, 3, 2])
with col7:
    st.metric("비농업 고용 (Change)", f"{int(job_val)}k", f"{int(job_chg)}k")
    create_chart(job_data, "#388e3c")
with col8:
    st.metric("실업률", f"{unemp_val:.1f}%", f"{unemp_chg:.1f}%p")
    create_chart(unemp_data, "#616161")
with col9:
    draw_signal_box("Economy Signal", st.session_state['signals']['economy'], st.session_state['comments']['economy'])