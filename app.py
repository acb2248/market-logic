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
    hr { margin-top: 30px; margin-bottom: 30px; border: 0; border-top: 1px solid #eee; }
    div[data-testid="stMetricValue"] { font-size: 24px; font-weight: bold; color: #333; }
    
    /* 신호등 박스 */
    .signal-box {
        background-color: #f8f9fa; border: 1px solid #e9ecef; border-radius: 12px; 
        padding: 20px; height: 100%; display: flex; flex-direction: column; align-items: center;
    }
    
    .light {
        width: 40px; height: 40px; border-radius: 50%; background: #ddd; opacity: 0.3; margin: 0 5px; 
        display: inline-block; transition: all 0.3s ease;
    }
    .red.active { background: #ff4b4b; opacity: 1; box-shadow: 0 0 15px #ff4b4b; transform: scale(1.1); }
    .yellow.active { background: #ffca28; opacity: 1; box-shadow: 0 0 15px #ffca28; transform: scale(1.1); }
    .green.active { background: #00e676; opacity: 1; box-shadow: 0 0 15px #00e676; transform: scale(1.1); }
    
    /* AI 답변 스타일 (핵심 vs 상세) */
    .ai-headline {
        font-size: 18px; font-weight: 800; color: #1a1a1a; margin-top: 15px; margin-bottom: 8px;
        line-height: 1.4; text-align: left; width: 100%;
    }
    .ai-details {
        font-size: 13px; line-height: 1.6; color: #666; background-color: white; 
        padding: 12px; border-radius: 8px; border-left: 3px solid #ccc; width: 100%; text-align: left;
    }
    
    .section-header { font-size: 22px; font-weight: 700; color: #212529; margin-bottom: 10px; }
    
    /* 라디오 버튼을 탭(버튼)처럼 보이게 하는 CSS */
    div[role="radiogroup"] > label > div:first-child { display: none; }
    div[role="radiogroup"] { flex-direction: row; gap: 10px; }
    div[role="radiogroup"] label { 
        background-color: #f1f3f5; padding: 4px 12px; border-radius: 20px; 
        font-size: 12px; border: 1px solid transparent; cursor: pointer; transition: 0.2s;
    }
    div[role="radiogroup"] label:hover { background-color: #e9ecef; }
    div[role="radiogroup"] label[data-checked="true"] { 
        background-color: #333; color: white; font-weight: bold; 
    }
    </style>
    """, unsafe_allow_html=True)

st.title("🚥 Market Logic: 섹터별 정밀 분석")
st.caption("기간별 데이터 흐름과 AI의 핵심 요약을 제공합니다.")

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
                df = df.dropna() # 전체 데이터 반환 (필터링은 나중에)
                return df['Value'].iloc[-1], df['Value'].iloc[-1]-df['Value'].iloc[-2], df.index[-1].strftime('%Y-%m'), df.reset_index()
        except: time.sleep(1); continue
    return None, None, None, None

@st.cache_data(ttl=3600)
def get_yahoo_data(ticker):
    try:
        data = yf.Ticker(ticker).history(period="10y") # 넉넉하게 가져옴
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

# ⭐ 차트 필터링 로직 (기간 버튼용)
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

# ⭐ 차트 그리기 (초기화 버튼 삭제 -> 기간 버튼으로 대체)
def create_chart(data, color, height=200):
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
# 5. AI 분석 (헤드라인 분리)
# -----------------------------------------------------------------------------
if 'ai_results' not in st.session_state:
    st.session_state['ai_results'] = {
        'market': {'signal': None, 'headline': None, 'details': None},
        'inflation': {'signal': None, 'headline': None, 'details': None},
        'economy': {'signal': None, 'headline': None, 'details': None}
    }

def analyze_sector(sector_name, data_summary):
    if not api_key: return st.error("API 키를 입력해주세요.")
    
    client = openai.OpenAI(api_key=api_key)
    # ⭐ 프롬프트 수정: 헤드라인과 상세내용 분리 요청
    prompt = f"""
    당신은 펀드매니저 버너드 보몰입니다.
    데이터: {data_summary}
    
    [Output Rules]
    1. Language: Korean (한국어)
    2. Format:
       SIGNAL: (RED or YELLOW or GREEN)
       HEADLINE: (Bold 1-line summary, less than 20 chars, aggressive tone)
       DETAILS: (2-3 sentences explaining the 'Why' and 'Action')
    """
    
    with st.spinner(f"AI가 {sector_name} 분석 중..."):
        try:
            resp = client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": prompt}])
            text = resp.choices[0].message.content
            
            signal = "YELLOW"
            if "RED" in text: signal = "RED"
            elif "GREEN" in text: signal = "GREEN"
            
            headline = "분석 결과 없음"
            details = text
            
            # 파싱 로직
            if "HEADLINE:" in text and "DETAILS:" in text:
                parts = text.split("HEADLINE:")[1].split("DETAILS:")
                headline = parts[0].strip()
                details = parts[1].strip()
            
            return signal, headline, details
        except Exception as e:
            return "YELLOW", "오류 발생", f"Error: {e}"

# -----------------------------------------------------------------------------
# 6. UI 그리기 (기간 버튼 추가)
# -----------------------------------------------------------------------------

def draw_section(title, key_prefix, chart1, chart2, period_options, default_idx):
    st.markdown(f"<div class='section-header'>{title}</div>", unsafe_allow_html=True)

    # 1. 기간 선택 버튼 (Radio Button을 가로로 배치하여 탭처럼 사용)
    # key를 유니크하게 만들기 위해 prefix 사용
    period = st.radio(
        "기간 선택", 
        period_options, 
        index=default_idx, 
        key=f"period_{key_prefix}", 
        horizontal=True,
        label_visibility="collapsed"
    )

    col_chart, col_ai = st.columns([3, 1])
    
    # [왼쪽] 차트 영역
    with col_chart:
        # 데이터 필터링
        data1_filtered = filter_data_by_period(chart1['data'], period)
        data2_filtered = filter_data_by_period(chart2['data'], period)

        # 차트 1
        st.metric(chart1['label'], chart1['val_str'], chart1['chg_str'])
        create_chart(data1_filtered, chart1['color'])
        st.markdown("<br>", unsafe_allow_html=True)
        # 차트 2
        st.metric(chart2['label'], chart2['val_str'], chart2['chg_str'])
        create_chart(data2_filtered, chart2['color'])

    # [오른쪽] AI 영역
    with col_ai:
        st.markdown(f"<div class='signal-box'>", unsafe_allow_html=True)
        st.markdown(f"**🤖 {key_prefix} AI 분석**")
        
        if st.button("⚡ 분석 실행", key=f"btn_{key_prefix}", use_container_width=True):
            data_sum = f"{chart1['label']}={chart1['val_str']}, {chart2['label']}={chart2['val_str']}"
            sig, head, det = analyze_sector(key_prefix, data_sum)
            st.session_state['ai_results'][key_prefix.lower()] = {'signal': sig, 'headline': head, 'details': det}
        
        res = st.session_state['ai_results'][key_prefix.lower()]
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
            # ⭐ 헤드라인과 상세내용 분리 출력
            st.markdown(f"<div class='ai-headline'>{res['headline']}</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='ai-details'>{res['details']}</div>", unsafe_allow_html=True)
        else:
            st.info("버튼을 눌러 분석하세요.")
            
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<hr>", unsafe_allow_html=True)

# --- 1. 시장 (Market) : 매일 변하므로 짧은 기간 위주 ---
draw_section(
    "1. Money Flow (시장 금리 & 환율)", "Market",
    {'label': "美 10년물 금리", 'val_str': f"{rate_val:.2f}%" if rate_val else "-", 'chg_str': f"{rate_chg:.2f}%" if rate_val else "-", 'data': rate_data, 'color': '#d32f2f'},
    {'label': "원/달러 환율", 'val_str': f"{exch_val:.2f}원" if exch_val else "-", 'chg_str': f"{exch_chg:.2f}원" if exch_val else "-", 'data': exch_data, 'color': '#1976d2'},
    ["1개월", "3개월", "6개월", "1년", "전체"], 3 # 기본값 1년
)

# --- 2. 물가 (Inflation) : 월간 데이터라 긴 기간 위주 ---
draw_section(
    "2. Inflation (물가 상승률)", "Inflation",
    {'label': "헤드라인 CPI (YoY)", 'val_str': f"{cpi_val:.2f}%" if cpi_val else "-", 'chg_str': f"{cpi_chg:.2f}%p" if cpi_val else "-", 'data': cpi_data, 'color': '#ed6c02'},
    {'label': "근원(Core) CPI (YoY)", 'val_str': f"{core_val:.2f}%" if core_val else "-", 'chg_str': f"{core_chg:.2f}%p" if core_val else "-", 'data': core_data, 'color': '#9c27b0'},
    ["1년", "3년", "5년", "전체"], 1 # 기본값 3년
)

# --- 3. 경기 (Economy) : 월간 데이터라 긴 기간 위주 ---
draw_section(
    "3. Economy (고용 & 경기)", "Economy",
    {'label': "비농업 신규 고용", 'val_str': f"{int(job_val)}k" if job_val else "-", 'chg_str': f"{int(job_chg)}k" if job_val else "-", 'data': job_data, 'color': '#2e7d32'},
    {'label': "실업률", 'val_str': f"{unemp_val:.1f}%" if unemp_val else "-", 'chg_str': f"{unemp_chg:.1f}%p" if unemp_val else "-", 'data': unemp_data, 'color': '#616161'},
    ["1년", "3년", "5년", "전체"], 1 # 기본값 3년
)