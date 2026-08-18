"""
[FastMCP 금융 실시간 데이터 & 뉴스 스크래퍼 서버 (FinanceTools)]

■ 설계 및 학습 목표:
  1. 외부 실시간 금융 API (Yahoo Finance: yfinance) 및 웹 스크래핑(Finviz: BeautifulSoup)을 연동하는 표준 FastMCP 서버 구축
  2. LLM 에이전트가 호출하기 쉬운 정형화된 JSON 출력 구조 설계 및 Pydantic/Dictionary 직렬화
  3. 최신 무상태(Stateless) Streamable HTTP 전송 방식을 통해 외부 에이전트(LangChain/Anthropic Skills)에 도구 서빙

■ 제공 도구(Tools):
  • stock_data(input: str) -> dict
    - 티커 목록(예: 'AAPL, NVDA', 'TSLA')을 받아 최근 1개월 주가, 등락률, 52주 최고/최저가, 시총, PER 조회
  • web_scraper(input: str) -> dict
    - Finviz 금융 포털에서 특정 기업의 최신 헤드라인 뉴스 5건 및 핵심 재무 스냅샷 테이블 크롤링

■ 실행 방법:
  python finance_mcp_server.py --port 6501
"""

from fastmcp import FastMCP
import argparse
import re
import yfinance as yf
import pandas as pd
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin


# ═══════════════════════════════════════════════════════════════════════════
# ① FastMCP 서버 인스턴스 선언
# ═══════════════════════════════════════════════════════════════════════════

app = FastMCP(
    name="FinanceTools",
    instructions="실시간 주가 데이터 조회 및 Finviz 금융 뉴스/스냅샷을 제공하는 금융 특화 MCP 서버",
)


# ═══════════════════════════════════════════════════════════════════════════
# ② 도구 1: 실시간 주가 및 재무 지표 조회 (stock_data)
# ═══════════════════════════════════════════════════════════════════════════

@app.tool(description="티커 목록으로 최근 주가 및 핵심 재무 지표(등락률, 시총, PER 등)를 조회합니다. 예: 'AAPL, NVDA'")
def stock_data(input: str = "") -> dict:
    """
    Yahoo Finance API를 호출하여 종목별 최신 시장 지표를 반환합니다.
    - 입력: 쉼표 또는 공백으로 구분된 티커 문자열 (예: 'NVDA, TSLA')
    - 출력: 티커별 시세 및 밸류에이션 지표 딕셔너리
    """
    text = input.strip()
    if not text:
        return {"error": "input이 비어있습니다. 조회할 티커를 입력하세요. 예: 'AAPL, NVDA'"}

    # 정규식을 사용하여 쉼표(,), 공백 등으로 구분된 티커 목록 파싱
    tickers = [t.strip().upper() for t in re.split(r"[,\s]+", text) if t.strip()]
    if not tickers:
        return {"error": "유효한 티커를 인식하지 못했습니다."}

    results = {}
    for t in tickers:
        try:
            # 1. yfinance Ticker 인스턴스 생성
            tk = yf.Ticker(t)
            # 2. 최근 1개월 히스토리 데이터 로드
            hist = tk.history(period="1mo")
            if hist.empty:
                results[t] = {"error": f"티커 '{t}'에 대한 주가 데이터를 찾을 수 없습니다."}
                continue

            # 3. 최근 가격 및 등락률 계산
            first, last = hist.iloc[0], hist.iloc[-1]
            change = float(last["Close"] - first["Close"])
            pct = (change / float(first["Close"])) * 100.0
            info = tk.info

            # 4. LLM이 이해하기 쉬운 요약 스키마 구성
            summary = {
                "latest_price": float(last["Close"]),
                "price_change": change,
                "pct_change": pct,
                "52w_high": info.get("fiftyTwoWeekHigh"),
                "52w_low": info.get("fiftyTwoWeekLow"),
                "market_cap": info.get("marketCap"),
                "pe_ratio": info.get("trailingPE"),
            }

            # NaN 값 안전 처리 및 부동소수점 형변환
            results[t] = {
                k: (None if pd.isna(v) else (float(v) if isinstance(v, (int, float)) else v))
                for k, v in summary.items()
            }
        except Exception as e:
            results[t] = {"error": f"데이터 수집 실패 ({t}): {str(e)}"}

    return results


# ═══════════════════════════════════════════════════════════════════════════
# ③ 도구 2: Finviz 금융 포털 뉴스 및 스냅샷 크롤러 (web_scraper)
# ═══════════════════════════════════════════════════════════════════════════

@app.tool(description="Finviz에서 특정 종목의 최신 헤드라인 뉴스와 핵심 스냅샷 정보를 수집합니다. 입력: 티커 문자열 (예: 'AAPL')")
def web_scraper(input: str = "") -> dict:
    """
    Finviz 웹페이지를 파싱하여 최신 뉴스 헤드라인과 기업 펀더멘털 스냅샷 테이블을 추출합니다.
    """
    ticker = input.strip().upper()
    if not ticker:
        return {"error": "티커가 필요합니다. 예: 'AAPL'"}

    url = f"https://finviz.com/quote.ashx?t={ticker.lower()}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        return {"error": f"Finviz 웹 요청 실패 ({url}): {e}"}

    soup = BeautifulSoup(resp.text, "html.parser")

    # 1. 뉴스 테이블 파싱 (#news-table의 상위 5개 기사 수집)
    news_items = []
    for row in soup.select("#news-table tr")[:5]:
        tds = row.find_all("td")
        if len(tds) < 2:
            continue
        date_td, title_td = tds[0], tds[1]
        a = title_td.find("a")
        link = a["href"] if a and a.has_attr("href") else ""
        if link and not link.startswith("http"):
            link = urljoin(url, link)
        news_items.append({
            "date": date_td.get_text(strip=True),
            "title": title_td.get_text(strip=True),
            "link": link,
        })

    # 2. 기업 스냅샷 펀더멘털 테이블 파싱 (.snapshot-table2)
    details = {}
    snap = soup.find("table", {"class": "snapshot-table2"})
    if snap:
        for r in snap.find_all("tr"):
            cells = r.find_all("td")
            for i in range(0, len(cells), 2):
                k = cells[i].get_text(strip=True)
                v = cells[i + 1].get_text(strip=True) if i + 1 < len(cells) else ""
                details[k] = v

    return {"ticker": ticker, "news_items": news_items, "snapshot": details}


# ═══════════════════════════════════════════════════════════════════════════
# ④ 메인 실행 루틴
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FinanceTools FastMCP Server")
    parser.add_argument("--port", type=int, default=6501, help="서버 포트 (기본값: 6501)")
    args = parser.parse_args()

    print(f"🚀 FinanceTools MCP Server 시작: http://0.0.0.0:{args.port}/mcp")
    print(f"   도구 목록: stock_data, web_scraper")

    # 최신 Stateless Streamable HTTP 전송 방식으로 단일 엔드포인트(/mcp) 서빙
    app.run(transport="http", port=args.port)
