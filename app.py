import streamlit as st
import yfinance as yf
import os
from openai import OpenAI

# 1. 페이지 기본 설정
st.set_page_config(page_title="Market Logic", layout="wide")

st.title("📊 Market Logic: 지표와 연결고리")
st.markdown("### '결과'가 아니라 '원인'을 봅니다.")

# 2. 데이터 가져오기 (미국 10년물 국채 금리 + 원/달러 환율)
# 캐싱을 통해 데이터 로딩 속도를 높입니다.
@st.cache_data
def get_bond_data():
    ticker = "^TNX"  # 미국 10년물 국채 금리 티커
    data = yf.download(ticker, period="1y")
    return data

@st.cache_data
def get_exchange_rate_data():
    ticker = "KRW=X"  # 원/달러 환율 티커
    data = yf.download(ticker, period="1y")
    return data

# 변수 초기화
bond_data = None
exchange_data = None
current_rate = None
rate_change = None
current_exchange = None
exchange_change = None

# 금리 데이터 가져오기
try:
    bond_data = get_bond_data()
    
    # 금리 최신 데이터 추출
    current_rate = bond_data['Close'].iloc[-1].item()
    prev_rate = bond_data['Close'].iloc[-2].item()
    rate_change = current_rate - prev_rate
    
    # 3. 메인 화면 구성 - 금리 섹션
    st.subheader("🇺🇸 미국 10년물 국채 금리 추이")
    col1, col2 = st.columns([3, 1])
    
    with col1:
        st.line_chart(bond_data['Close'])
    
    with col2:
        st.metric(label="현재 금리", value=f"{current_rate:.3f}%", delta=f"{rate_change:.3f}%")
        st.info("💡 금리는 모든 자산 가격의 중력입니다.")

except Exception as e:
    st.error(f"금리 데이터를 가져오는 중 오류가 발생했습니다: {e}")

st.divider()

# 환율 데이터 가져오기
try:
    exchange_data = get_exchange_rate_data()
    
    # 환율 최신 데이터 추출
    current_exchange = exchange_data['Close'].iloc[-1].item()
    prev_exchange = exchange_data['Close'].iloc[-2].item()
    exchange_change = current_exchange - prev_exchange
    
    st.subheader("💱 원/달러 환율 추이 (티커: KRW=X)")
    col3, col4 = st.columns([3, 1])
    
    with col3:
        st.line_chart(exchange_data['Close'])
    
    with col4:
        st.metric(label="현재 환율", value=f"{current_exchange:.2f}원", delta=f"{exchange_change:.2f}원")
        st.info("💡 환율은 자금 흐름의 방향을 보여줍니다.")
        
except Exception as e:
    st.error(f"환율 데이터를 가져오는 중 오류가 발생했습니다: {e}")

st.divider()

# 4. AI 분석 섹션 (사이드바 관리자 모드 + 비용 절감 캐싱)
st.subheader("🤖 AI Market Analyst의 해설")

# 분석 파일 경로
ANALYSIS_FILE = "market_view.txt"

# 사이드바: 관리자 통제실
with st.sidebar:
    st.header("🛠 관리자 모드")
    api_key = st.text_input("OpenAI API Key", type="password")
    
    if st.button("🚀 AI 분석 실행 (비용 발생)"):
        if not api_key:
            st.error("API 키를 입력해주세요!")
        elif current_rate is None:
            st.error("금리 데이터를 먼저 불러와주세요!")
        else:
            try:
                # OpenAI 클라이언트 연결
                client = OpenAI(api_key=api_key)
                
                # 환율 정보 포함 여부 확인
                exchange_info = ""
                if current_exchange is not None and exchange_change is not None:
                    exchange_info = f"\n- 원/달러 환율: {current_exchange:.2f}원 (전일 대비 {exchange_change:+.2f}원)"
                
                # 프롬프트: 버너드 보몰의 논리 주입 + 마크다운 구조화
                prompt = f"""
                현재 시장 지표:
                - 미국 10년물 국채 금리: {current_rate:.3f}% (전일 대비 {rate_change:+.3f}%){exchange_info}
                
                이 데이터를 바탕으로 투자자들에게 시장 상황을 설명해줘.
                반드시 '버너드 보몰'의 경제지표 해석 논리(연결고리)를 따라야 해.
                
                [출력 형식 - 반드시 이 형식으로 작성해줘]
                * **📊 시장 진단:** (현재 상황 한 줄 요약)
                * **🔗 연결 고리:** (금리와 환율이 서로 미치는 영향 설명)
                * **💡 투자 전략:** (그래서 주식을 살지 팔지 구체적인 조언)
                
                [논리 구조]
                1. 금리 변동의 의미 (기업 자금 조달 비용, 주택 담보 대출 등)
                2. 주식 시장 영향 (특히 기술주/성장주 밸류에이션 압박 여부)
                3. 외환 시장 영향 (달러 강세/약세와 외국인 자금 흐름)
                4. 금리와 환율의 상호작용 (자금 흐름, 외국인 투자 등)
                
                [톤앤매너]
                - 말투: 쉽고 친절한 경제 과외 선생님 (비전공자도 이해하기 쉽게)
                - 각 항목은 2-3줄 정도로 핵심만 요약
                - 마크다운 글머리 기호 형식을 정확히 지켜줘
                """
                
                with st.spinner("AI가 시장을 분석 중입니다..."):
                    response = client.chat.completions.create(
                        model="gpt-4o-mini", # 가성비 모델 사용
                        messages=[{"role": "user", "content": prompt}]
                    )
                    analysis_text = response.choices[0].message.content
                    
                    # 결과를 파일로 저장 (캐싱)
                    with open(ANALYSIS_FILE, "w", encoding="utf-8") as f:
                        f.write(analysis_text)
                    
                st.success("분석 완료! 내용이 갱신되었습니다.")
                st.rerun() # 화면 새로고침
                
            except Exception as e:
                st.error(f"분석 실패: {e}")

# 메인 화면: 저장된 분석 내용 보여주기 (비용 0원)
if os.path.exists(ANALYSIS_FILE):
    with open(ANALYSIS_FILE, "r", encoding="utf-8") as f:
        saved_analysis = f.read()
    st.markdown(saved_analysis)
else:
    st.warning("아직 생성된 분석 리포트가 없습니다. 사이드바에서 분석을 실행해주세요.")