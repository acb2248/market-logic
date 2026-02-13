import streamlit as st
import pandas as pd
import openai
import yfinance as yf
import requests
import altair as alt
from io import StringIO
import time

# -----------------------------------------------------------------------------
# 1. 페이지 설정 및 스타일
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Market Logic Pro", page_icon="🚥", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
    <style>
    .stApp { background-color: #ffffff; }
    
    /* 섹션 구분선 */
    hr { margin-top: 30px; margin-bottom: 30px; border: 0; border-top: 1px solid #eee; }
    
    /* 메트릭(숫자) 스타일 */
    div[data-testid="stMetricValue"] { font-size: 24px; font-weight: bold; color: #333; }
    
    /* 신호등 박스 */
    .signal-box {
        background-color: #f8f9fa; 
        border: 1px solid #e9ecef;
        border-radius: 12px; 
        padding: 20px; 
        height: 100%;
        display: flex; flex-direction: column; align-items: center; justify-content: flex-start;
    }
    
    /* 신호등 전구 */
    .light {
        width: 40px; height: 40px; border-radius: 50%;
        background: #ddd; opacity: 0.3; margin: 0 5px; display: inline-block;
        transition: all 0.3s ease;
    }
    
    /* 활성화 효과 */
    .red.active { background: #ff4b4b; opacity: 1; box-shadow: 0 0 15px #ff4b4b; transform: scale(1.1); }
    .yellow.active { background: #ffca28; opacity: 1; box-shadow: 0 0 15px #ffca28; transform: scale(1.1); }
    .green.active { background: #00e676; opacity: 1; box-shadow: 0 0 15px #00e676; transform: scale(1.1); }
    
    /* AI 코멘트 텍스트 */
    .ai-comment {
        font-size: 14px; line-height: 1.6; color: #495057;
        background-color: white; padding: 15px; border-radius: 8px;
        border-left: 4px solid #333; margin-top: 20px; width: 100%; text-align: left;
    }
    
    /* 섹션 제목 */
    .section-header { font-size: 22px; font-weight: 700; color: #212529; margin-bottom: 10px; display: flex; align-items: center; gap: 10px; }
    
    </style>
    """, unsafe_allow_html=True)

st.title("🚥 Market Logic: 섹터별 정밀 분석")
st.caption("차트의 흐름(Flow)과 AI의 판단(Signal)을 연결합니다.")

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
                df = df.dropna().tail(30) # 최근 30개월/일 데이터 (가로로 길게 보기 위해)
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

# ⭐ 차트 함수 (가로형, 축 표시, 라인만 깔끔하게)
def create_chart(data, color, height=200):
    if data is None: return st.error("No Data")
    
    chart = alt.Chart(data).mark_line(
        color=color, 
        strokeWidth=2
    ).encode(
        # X축: 날짜 (포맷 지정)
        x=alt.X('Date:T', axis=alt.Axis(format='%y-%m', title=None, grid=False)),
        # Y축: 값 (자동 스케일, 숫자 표시)
        y=alt.Y('Value:Q', scale=alt.Scale(zero=False), axis=alt.Axis(title=None)),
        tooltip=['Date:T', alt.Tooltip('Value', format=',.2f')]
    ).properties(
        height=height # 차트 높이 고정 (가로는 container width를 따름)
    ).interactive()
    
    return st.altair_chart(chart, use_container_width=True)

# -----------------------------------------------------------------------------
# 4. 데이터 로딩
# -----------------------------------------------------------------------------
with st.spinner('데이터 준비 중...'):
    rate_val, rate_chg, _, rate_data = get_interest_rate_hybrid()
    exch_val, exch_chg, _, exch_data = get_yahoo_data("KRW=X")
    cpi_val, cpi_chg, _, cpi_data = get_fred_data("CPIAUCSL", "yoy")
    core_val, core_chg, _, core_data = get_fred_data("CPILFESL", "yoy")
    job_val, job_chg, _, job_data = get_fred_data("PAYEMS", "diff")
    unemp_val, unemp_chg, _, unemp_data = get_fred_data("UNRATE", "raw")

# -----------------------------------------------------------------------------
# 5. AI 분석 로직 (개별 분석 함수)
# -----------------------------------------------------------------------------
if 'ai_results' not in st.session_state:
    st.session_state['ai_results'] = {
        'market': {'signal': None, 'comment': None},
        'inflation': {'signal': None, 'comment': None},
        'economy': {'signal': None, 'comment': None}
    }

def analyze_sector(sector_name, data_summary):
    if not api_key: return st.error("API 키를 입력해주세요.")
    
    client = openai.OpenAI(api_key=api_key)
    prompt = f"""
    당신은 펀드매니저 버너드 보몰입니다. 다음 데이터를 분석하세요.
    
    [Sector: {sector_name}]
    {data_summary}
    
    [Requirements]
    1. Output MUST be in KOREAN (한국어).
    2. Format:
       SIGNAL: (RED or YELLOW or GREEN)
       COMMENT: (3 bullet points analyzing the situation)
    """
    
    with st.spinner(f"{sector_name} 섹터 분석 중..."):
        try:
            resp = client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": prompt}])
            text = resp.choices[0].message.content
            
            signal = "YELLOW"
            if "RED" in text: signal = "RED"
            elif "GREEN" in text: signal = "GREEN"
            
            comment = text.split("COMMENT:")[1].strip() if "COMMENT:" in text else text
            return signal, comment
        except Exception as e:
            return "YELLOW", f"Error: {e}"

# -----------------------------------------------------------------------------
# 6. UI 레이아웃 (가로형 차트 + 우측 AI 패널)
# -----------------------------------------------------------------------------

def draw_section(title, key_prefix, chart1_info, chart2_info, ai_key):
    # 상단 헤더
    c_title, c_reset = st.columns([9, 1])
    with c_title: st.markdown(f"<div class='section-header'>{title}</div>", unsafe_allow_html=True)
    with c_reset: 
        if st.button("🔄", key=f"reset_{key_prefix}", help="차트 리셋"): st.rerun()

    # 메인 레이아웃 (좌 7.5 : 우 2.5)
    col_chart, col_ai = st.columns([3, 1])
    
    # [왼쪽] 차트 영역 (위아래로 배치하여 가로로 길게)
    with col_chart:
        # 차트 1
        st.metric(chart1_info['label'], chart1_info['val_str'], chart1_info['chg_str'])
        create_chart(chart1_info['data'], chart1_info['color'])
        
        st.markdown("<br>", unsafe_allow_html=True) # 간격
        
        # 차트 2
        st.metric(chart2_info['label'], chart2_info['val_str'], chart2_info['chg_str'])
        create_chart(chart2_info['data'], chart2_info['color'])

    # [오른쪽] AI 신호등 영역
    with col_ai:
        st.markdown(f"<div class='signal-box'>", unsafe_allow_html=True)
        st.markdown(f"**🤖 {key_prefix} AI 분석**")
        
        # 분석 버튼 (개별)
        if st.button("⚡ 분석 실행", key=f"btn_{key_prefix}", use_container_width=True):
            # 데이터 요약 생성
            data_sum = f"Metrics: {chart1_info['label']}={chart1_info['val_str']}, {chart2_info['label']}={chart2_info['val_str']}"
            sig, com = analyze_sector(key_prefix, data_sum)
            st.session_state['ai_results'][ai_key] = {'signal': sig, 'comment': com}
        
        # 결과 표시
        res = st.session_state['ai_results'][ai_key]
        signal = res['signal']
        
        r = "active" if signal == "RED" else ""
        y = "active" if signal == "YELLOW" else ""
        g = "active" if signal == "GREEN" else ""
        
        st.markdown(f"""
        <div style="margin-top: 20px;">
            <div class="light red {r}"></div>
            <div class="light yellow {y}"></div>
            <div class="light green {g}"></div>
        </div>
        """, unsafe_allow_html=True)
        
        if res['comment']:
            st.markdown(f"<div class='ai-comment'>{res['comment']}</div>", unsafe_allow_html=True)
        else:
            st.info("버튼을 눌러 분석하세요.")
            
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<hr>", unsafe_allow_html=True)

# --- 1. 시장 (Market) ---
draw_section(
    "1. Money Flow (시장 금리 & 환율)", "Market",
    {'label': "美 10년물 금리", 'val_str': f"{rate_val:.2f}%" if rate_val else "-", 'chg_str': f"{rate_chg:.2f}%" if rate_val else "-", 'data': rate_data, 'color': '#d32f2f'},
    {'label': "원/달러 환율", 'val_str': f"{exch_val:.2f}원" if exch_val else "-", 'chg_str': f"{exch_chg:.2f}원" if exch_val else "-", 'data': exch_data, 'color': '#1976d2'},
    'market'
)

# --- 2. 물가 (Inflation) ---
draw_section(
    "2. Inflation (물가 상승률)", "Inflation",
    {'label': "헤드라인 CPI (YoY)", 'val_str': f"{cpi_val:.2f}%" if cpi_val else "-", 'chg_str': f"{cpi_chg:.2f}%p" if cpi_val else "-", 'data': cpi_data, 'color': '#ed6c02'},
    {'label': "근원(Core) CPI (YoY)", 'val_str': f"{core_val:.2f}%" if core_val else "-", 'chg_str': f"{core_chg:.2f}%p" if core_val else "-", 'data': core_data, 'color': '#9c27b0'},
    'inflation'
)

# --- 3. 경기 (Economy) ---
draw_section(
    "3. Economy (고용 & 경기)", "Economy",
    {'label': "비농업 신규 고용", 'val_str': f"{int(job_val)}k" if job_val else "-", 'chg_str': f"{int(job_chg)}k" if job_val else "-", 'data': job_data, 'color': '#2e7d32'},
    {'label': "실업률", 'val_str': f"{unemp_val:.1f}%" if unemp_val else "-", 'chg_str': f"{unemp_chg:.1f}%p" if unemp_val else "-", 'data': unemp_data, 'color': '#616161'},
    'economy'
)