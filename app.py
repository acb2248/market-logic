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
st.set_page_config(page_title="Market Logic Pro", page_icon="🚥", layout="wide", initial_sidebar_state="collapsed")

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
    
    /* 라디오 버튼 커스텀 (작은 탭 스타일) */
    div[role="radiogroup"] > label > div:first-child { display: none; }
    div[role="radiogroup"] { flex-direction: row; gap: 6px; margin-bottom: 10px; }
    div[role="radiogroup"] label { 
        background-color: #f1f3f5; padding: 2px 10px; border-radius: 12px; 
        font-size: 11px; border: 1px solid transparent; cursor: pointer; transition: 0.2s; color: #555;
    }
    div[role="radiogroup"] label:hover { background-color: #e9ecef; }
    div[role="radiogroup"] label[data-checked="true"] { 
        background-color: #555; color: white; font-weight: bold; 
    }
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
                df = df.dropna()
                return df['Value'].iloc[-1], df['Value'].iloc[-1]-df['Value'].iloc[-2], df.index[-1].strftime('%Y-%m'), df.reset_index()
        except: time.sleep(1); continue
    return None, None, None, None

@st.cache_data(ttl=3600)
def get_yahoo_data(ticker):
    try:
        data = yf.Ticker(ticker).history(period="10y") 
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

def filter_data_by_period(df, period):
    if df is None or df.empty: return df
    end_date = df['Date'].max()
    start_date = df['Date'].min()
    
    if period == "1개월": start_date = end_date - timedelta(days=30)
    elif period == "3개월": start_date = end_date - timedelta(days=90)
    elif period == "6개월": start_date = end_date - timedelta(days=180)
    elif period == "1년": start_date = end_date - timedelta(days=365)
    elif period == "3년": start_date = end_date - timedelta(days=365*3)
    elif period == "5년": start_date = end_date - timedelta(days=365*5)
    
    return df[df['Date'] >= start_date]

def create_chart(data, color, height=180):
    if data is None or data.empty: return st.error("No Data")
    chart = alt.Chart(data).mark_line(color=color, strokeWidth=2).encode(
        x=alt.X('Date:T', axis=alt.Axis(format='%y-%m', title=None, grid=False)),
        y=alt.Y('Value:Q', scale=alt.Scale(zero=False), axis=alt.Axis(title=None)),
        tooltip=['Date:T', alt.Tooltip('Value', format=',.2f')]
    ).properties(height=height).interactive()
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
# 5. AI 분석 (오류 방지 및 초기화)
# -----------------------------------------------------------------------------
# ⭐ KeyError 방지를 위한 세션 상태 강제 초기화 로직
if 'ai_results' not in st.session_state or 'headline' not in st.session_state['ai_results'].get('market', {}):
    st.session_state['ai_results'] = {
        'market': {'signal': None, 'headline': None, 'details': None},
        'inflation': {'signal': None, 'headline': None, 'details': None},
        'economy': {'signal': None, 'headline': None, 'details': None}
    }

def analyze_sector(sector_name, data_summary):
    if not api_key: return st.error("API 키 필요")
    client = openai.OpenAI(api_key=api_key)
    prompt = f"""
    당신은 펀드매니저 버너드 보몰입니다. 데이터: {data_summary}
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
    except: return "YELLOW", "오류 발생", "분석 중 문제가 생겼습니다."

# -----------------------------------------------------------------------------
# 6. UI 그리기 (차트별 개별 버튼 적용)
# -----------------------------------------------------------------------------

# ⭐ 차트 하나를 그리는 단위 함수 (버튼 포함)
def draw_chart_unit(label, val, chg, data, color, periods, default_idx, key):
    # 상단: 메트릭 + 기간버튼을 한 줄에 배치하되, 공간 분리
    c1, c2 = st.columns([1, 2])
    with c1:
        st.metric(label, val, chg)
    with c2:
        # 개별 차트용 기간 선택 버튼
        period = st.radio("기간", periods, index=default_idx, key=f"p_{key}", horizontal=True, label_visibility="collapsed")
    
    # 하단: 차트
    filtered_data = filter_data_by_period(data, period)
    create_chart(filtered_data, color)

def draw_section(title, key_prefix, chart1, chart2):
    st.markdown(f"<div class='section-header'>{title}</div>", unsafe_allow_html=True)
    
    col_chart, col_ai = st.columns([3, 1])
    
    # [왼쪽] 차트 영역
    with col_chart:
        # 차트 1 (개별 버튼 적용)
        draw_chart_unit(
            chart1['label'], chart1['val_str'], chart1['chg_str'], chart1['data'], chart1['color'],
            chart1['periods'], chart1['default_idx'], f"{key_prefix}_1"
        )
        st.markdown("<div style='margin-bottom: 20px;'></div>", unsafe_allow_html=True) # 간격
        # 차트 2 (개별 버튼 적용)
        draw_chart_unit(
            chart2['label'], chart2['val_str'], chart2['chg_str'], chart2['data'], chart2['color'],
            chart2['periods'], chart2['default_idx'], f"{key_prefix}_2"
        )

    # [오른쪽] AI 영역
    with col_ai:
        st.markdown(f"<div class='signal-box'>", unsafe_allow_html=True)
        st.markdown(f"**🤖 {key_prefix} AI 분석**")
        
        if st.button("⚡ 분석 실행", key=f"btn_{key_prefix}", use_container_width=True):
            data_sum = f"{chart1['label']}={chart1['val_str']}, {chart2['label']}={chart2['val_str']}"
            sig, head, det = analyze_sector(key_prefix, data_sum)
            st.session_state['ai_results'][key_prefix.lower()] = {'signal': sig, 'headline': head, 'details': det}
        
        res = st.session_state['ai_results'].get(key_prefix.lower(), {'signal': None, 'headline': None})
        signal = res['signal']
        
        r = "active" if signal == "RED" else ""
        y = "active" if signal == "YELLOW" else ""
        g = "active" if signal == "GREEN" else ""
        
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
        else:
            st.info("버튼을 눌러 분석하세요.")
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<hr>", unsafe_allow_html=True)

# --- 1. 시장 (Market) : 기본값 '1년' (Index 3) ---
draw_section(
    "1. Money Flow (시장 금리 & 환율)", "Market",
    {
        'label': "美 10년물 금리", 
        'val_str': f"{rate_val:.2f}%" if rate_val else "-", 
        'chg_str': f"{rate_chg:.2f}%" if rate_val else "-", 
        'data': rate_data, 'color': '#d32f2f',
        'periods': ["1개월", "3개월", "6개월", "1년", "전체"], 'default_idx': 3
    },
    {
        'label': "원/달러 환율", 
        'val_str': f"{exch_val:.2f}원" if exch_val else "-", 
        'chg_str': f"{exch_chg:.2f}원" if exch_val else "-", 
        'data': exch_data, 'color': '#1976d2',
        'periods': ["1개월", "3개월", "6개월", "1년", "전체"], 'default_idx': 3
    }
)

# --- 2. 물가 (Inflation) : 기본값 '1년' (Index 0) ---
draw_section(
    "2. Inflation (물가 상승률)", "Inflation",
    {
        'label': "헤드라인 CPI (YoY)", 
        'val_str': f"{cpi_val:.2f}%" if cpi_val else "-", 
        'chg_str': f"{cpi_chg:.2f}%p" if cpi_val else "-", 
        'data': cpi_data, 'color': '#ed6c02',
        'periods': ["1년", "3년", "5년", "전체"], 'default_idx': 0
    },
    {
        'label': "근원(Core) CPI (YoY)", 
        'val_str': f"{core_val:.2f}%" if core_val else "-", 
        'chg_str': f"{core_chg:.2f}%p" if core_val else "-", 
        'data': core_data, 'color': '#9c27b0',
        'periods': ["1년", "3년", "5년", "전체"], 'default_idx': 0
    }
)

# --- 3. 경기 (Economy) : 기본값 '1년' (Index 0) ---
draw_section(
    "3. Economy (고용 & 경기)", "Economy",
    {
        'label': "비농업 신규 고용", 
        'val_str': f"{int(job_val)}k" if job_val else "-", 
        'chg_str': f"{int(job_chg)}k" if job_val else "-", 
        'data': job_data, 'color': '#2e7d32',
        'periods': ["1년", "3년", "5년", "전체"], 'default_idx': 0
    },
    {
        'label': "실업률", 
        'val_str': f"{unemp_val:.1f}%" if unemp_val else "-", 
        'chg_str': f"{unemp_chg:.1f}%p" if unemp_val else "-", 
        'data': unemp_data, 'color': '#616161',
        'periods': ["1년", "3년", "5년", "전체"], 'default_idx': 0
    }
)