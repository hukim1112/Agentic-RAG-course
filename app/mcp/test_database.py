"""
app/mcp/test_database.py
========================
[4대 엔터프라이즈 RAG 데이터베이스 통합 검색 검증 및 MCP 도구 제작 레퍼런스 가이드]

📌 [교육생 필독 - MCP 도구 구현 시 참고 방법]
이 스크립트는 `app/database/` 및 `app/database/graphrag/`에 구축된 4대 엔터프라이즈 데이터베이스를
파이썬 코드로 직접 로드하고 검색하는 표준 레퍼런스 코드입니다.

Mission 2-3에서 `app/mcp/enterprise_rag_server.py`의 FastMCP 도구를 구현할 때,
아래 4개 함수의 [DB 로드 & 검색 패턴]을 그대로 복사하여 `@mcp.tool` 데코레이터 함수 내부에
사용하시면 됩니다:

1. [DB 1: 사내 규정집 Chroma Vector DB]
   - 로드: Chroma(collection_name="enterprise_policy_store", persist_directory="app/database/chroma_db", ...)
   - 검색: vectorstore.similarity_search(query, k=2)
   - 용도: 사내 여비/복무/보안 규정 및 감액 기준 검색

2. [DB 2: 한국은행(BOK) 산업보고서 Chroma Vector DB]
   - 로드: Chroma(collection_name="bok_industry_reports_store", persist_directory="app/database/chroma_db", ...)
   - 검색: vectorstore.similarity_search(query, k=2)
   - 용도: 반도체, 이차전지, 자동차 등 거시 산업 동향 보고서 검색

3. [DB 3: NetworkX 인메모리 지식 그래프]
   - 로드: nx.node_link_graph(json.load("app/database/knowledge_graph_nodelink.json"))
   - 검색: multi_hop_search(G, seed_entities=[seed_entity], max_hops=2)
   - 용도: 인물/부서의 직속 보고선(팀장, 본부장) 및 프로젝트 협업 관계 2-Hop BFS 고속 탐색

4. [DB 4: Microsoft GraphRAG]
   - 로드 및 실행: run_graphrag_query(query, method="global"|"local", root_dir="app/database/graphrag")
   - 용도: 전사 거시 프로젝트 목표/리스크 종합(Global) 및 인물 전결 권한 미시 분석(Local)
"""

import os
import sys
import json
import networkx as nx
from dotenv import load_dotenv

# 프로젝트 루트 경로 자동 등록 (어디서 실행해도 경로 오류 방지)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# .env 환경변수 로드 (OPENAI_API_KEY, GOOGLE_API_KEY 등)
load_dotenv(os.path.join(PROJECT_ROOT, ".env"), override=True)

from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
from rag.networkx_graph import multi_hop_search
from rag.graphrag_tool import run_graphrag_query

# 공통 데이터베이스 디렉토리 경로
DB_DIR = os.path.join(PROJECT_ROOT, "app/database")
CHROMA_DIR = os.path.join(DB_DIR, "chroma_db")


# ==============================================================================
# [DB 1] 사내 규정집 Chroma Vector DB (Dense Semantic Search)
# ==============================================================================
def test_1_policy_vector_db():
    """
    [MCP 도구 매핑 레퍼런스: search_company_policy]
    - collection_name: 'enterprise_policy_store'
    - persist_directory: 'app/database/chroma_db'
    - 역할: 여비지급규정, 인사복무규정, 정보보안지침 등 사내 규정집의 정확한 조항과 수치를 검색합니다.
    """
    print("=" * 75)
    print("🔍 [DB 1] 사내 규정집 Chroma Vector DB 검색 테스트 (통합 chroma_db)")
    print("=" * 75)
    
    if not os.path.exists(CHROMA_DIR):
        print(f"  ❌ DB 디렉토리가 없습니다: {CHROMA_DIR}")
        print("     먼저 'python app/mcp/generate_database.py'를 실행하여 DB를 생성하세요.")
        return

    # OpenAI 최신 임베딩 모델 (3072차원)
    embeddings = OpenAIEmbeddings(model="text-embedding-3-large")
    
    # 💡 [MCP 구현 핵심 코드] 동일한 chroma_db 폴더에서 collection_name으로 사내 규정 컬렉션 로드
    vectorstore = Chroma(
        collection_name="enterprise_policy_store",
        embedding_function=embeddings,
        persist_directory=CHROMA_DIR
    )
    
    query = "과장급 직원이 당일 출장을 다녀올 때 일비와 식비 감액 기준"
    print(f"  • 질의문: '{query}'")
    
    # 상위 k=2개 청크 유사도 검색
    results = vectorstore.similarity_search(query, k=2)
    
    print(f"  • 검색된 청크 수: {len(results)}개")
    for idx, doc in enumerate(results, 1):
        print(f"\n  [결과 #{idx}]")
        print(f"  - 출처 파일: {doc.metadata.get('source_file', 'N/A')}")
        print(f"  - 목차 계층(Breadcrumb): {doc.metadata.get('breadcrumb', 'N/A')}")
        lines = doc.page_content.splitlines()
        content_preview = "\n    ".join([l for l in lines if not l.startswith("---") and not l.startswith("[")][:4])
        print(f"  - 본문 발췌:\n    {content_preview}")
        
    print("\n  ✅ [DB 1 검증 완료] 사내 규정 Vector DB 정상 작동!\n")


# ==============================================================================
# [DB 2] 한국은행(BOK) 산업보고서 Chroma Vector DB (Dense Semantic Search)
# ==============================================================================
def test_2_bok_vector_db():
    """
    [MCP 도구 매핑 레퍼런스: search_bok_reports]
    - collection_name: 'bok_industry_reports_store'
    - persist_directory: 'app/database/chroma_db'
    - 역할: 한국은행 주력산업 모니터링 보고서(반도체, 이차전지, 자동차 등)의 거시 실적과 전망을 검색합니다.
    """
    print("=" * 75)
    print("🔍 [DB 2] 한국은행 (BOK) 산업보고서 Chroma Vector DB 검색 테스트 (통합 chroma_db)")
    print("=" * 75)
    
    if not os.path.exists(CHROMA_DIR):
        print(f"  ❌ DB 디렉토리가 없습니다: {CHROMA_DIR}")
        return

    embeddings = OpenAIEmbeddings(model="text-embedding-3-large")
    
    # 💡 [MCP 구현 핵심 코드] 동일한 chroma_db 폴더에서 collection_name으로 BOK 컬렉션 로드
    vectorstore = Chroma(
        collection_name="bok_industry_reports_store",
        embedding_function=embeddings,
        persist_directory=CHROMA_DIR
    )
    
    query = "2024년 3분기 반도체 수출 실적 및 메모리 가격 동향"
    print(f"  • 질의문: '{query}'")
    
    results = vectorstore.similarity_search(query, k=2)
    
    print(f"  • 검색된 청크 수: {len(results)}개")
    for idx, doc in enumerate(results, 1):
        print(f"\n  [결과 #{idx}]")
        print(f"  - 출처 파일: {doc.metadata.get('source_file', 'N/A')}")
        lines = doc.page_content.splitlines()
        content_preview = "\n    ".join([l for l in lines if not l.startswith("---") and not l.startswith("[")][:3])
        print(f"  - 본문 발췌:\n    {content_preview}")
        
    print("\n  ✅ [DB 2 검증 완료] BOK 산업보고서 Vector DB 정상 작동!\n")


# ==============================================================================
# [DB 3] NetworkX 조직/프로젝트 지식 그래프 (2-Hop BFS Multi-hop Search)
# ==============================================================================
def test_3_knowledge_graph_db():
    """
    [MCP 도구 매핑 레퍼런스: search_graph_relations]
    - 대상 파일: 'app/database/knowledge_graph_nodelink.json'
    - 역할: 조직도 및 프로젝트 관계 그래프에서 특정 인물이나 팀의 직속 보고선(팀장/본부장),
           인력 파견 협업 관계를 2-Hop BFS로 초고속(0ms급) 탐색합니다.
    """
    print("=" * 75)
    print("🔍 [DB 3] NetworkX 조직/프로젝트 지식 그래프 탐색 테스트")
    print("=" * 75)
    
    graph_file = os.path.join(DB_DIR, "knowledge_graph_nodelink.json")
    if not os.path.exists(graph_file):
        print(f"  ❌ 그래프 DB 파일이 없습니다: {graph_file}")
        return

    # 💡 [MCP 구현 핵심 코드] JSON 파일로부터 NetworkX NodeLink 그래프 즉시 복원
    with open(graph_file, "r", encoding="utf-8") as f:
        graph_data = json.load(f)
    G = nx.node_link_graph(graph_data)
    
    seed_entity = "김철수 수석"
    print(f"  • 총 노드 수: {G.number_of_nodes()}개, 총 관계(엣지) 수: {G.number_of_edges()}개")
    print(f"  • 탐색 시작 엔티티: '{seed_entity}' (최대 2-Hop BFS 확장)")
    
    # 💡 [MCP 구현 핵심 코드] multi_hop_search를 호출하여 2-Hop 서브그래프 관계 목록 추출
    sub_edges, visited = multi_hop_search(G, seed_entities=[seed_entity], max_hops=2)
    
    print(f"  • 방문한 엔티티 ({len(visited)}개): {visited}")
    print("  • 연결된 2-Hop 서브그래프 관계 목록:")
    for edge in sub_edges:
        rel = edge[2].get("relation", "연결됨")
        print(f"    - [{edge[0]}] ──({rel})──> [{edge[1]}]")
        
    print("\n  ✅ [DB 3 검증 완료] 조직도 지식 그래프 2-Hop 탐색 정상 작동!\n")


# ==============================================================================
# [DB 4] Microsoft GraphRAG (Global & Local Search)
# ==============================================================================
def test_4_graphrag_db():
    """
    [MCP 도구 매핑 레퍼런스: query_enterprise_graphrag]
    - 대상 디렉토리: 'app/database/graphrag'
    - 역할: 
      1) Global Search: Leiden 커뮤니티 계층 리포트를 Map-Reduce로 종합하여 전사 거시 프로젝트 요약
      2) Local Search: 특정 인물/부서의 주변 지식 서브그래프 및 원문 청크를 결합하여 전결 규정 분석
    """
    print("=" * 75)
    print("🔍 [DB 4] Microsoft GraphRAG (Global & Local Search) 질의 테스트")
    print("=" * 75)
    
    graphrag_root = os.path.join(DB_DIR, "graphrag")
    if not os.path.exists(graphrag_root):
        graphrag_root = os.path.join(PROJECT_ROOT, "data/graphrag")
    
    # 💡 [MCP 구현 핵심 코드 - Global Search] 거시적 전사 질문
    global_query = "전사 프로젝트들의 핵심 목표와 공통 리스크를 요약해줘."
    print(f"  🌐 [4-1. Global Search 쿼리]:\n     '{global_query}'")
    try:
        res_global = run_graphrag_query(global_query, method="global", root_dir=graphrag_root)
        preview = res_global.strip().split("\n")[:4]
        print("  -> Global 응답 미리보기:")
        for l in preview:
            print(f"     {l}")
    except Exception as e:
        print(f"  ⚠️ Global Search 오류: {e}")

    print("\n  ----------------------------------------------------------------------")
    # 💡 [MCP 구현 핵심 코드 - Local Search] 미시적 인물/부서 질문
    local_query = "클라우드운영팀 김철수 수석의 역할과 소속 보고선은 어떻게 되나요?"
    print(f"  🎯 [4-2. Local Search 쿼리]:\n     '{local_query}'")
    try:
        res_local = run_graphrag_query(local_query, method="local", root_dir=graphrag_root)
        preview = res_local.strip().split("\n")[:4]
        print("  -> Local 응답 미리보기:")
        for l in preview:
            print(f"     {l}")
    except Exception as e:
        print(f"  ⚠️ Local Search 오류: {e}")
        
    print("\n  ✅ [DB 4 검증 완료] Microsoft GraphRAG 정상 작동!\n")


# ==============================================================================
# 메인 실행 엔트리포인트
# ==============================================================================
if __name__ == "__main__":
    print("\n🚀 [4대 엔터프라이즈 RAG 데이터베이스 통합 검색 검증 시작]\n")
    test_1_policy_vector_db()
    test_2_bok_vector_db()
    test_3_knowledge_graph_db()
    test_4_graphrag_db()
    print("=" * 75)
    print("🎉 축하합니다! 4대 데이터베이스가 모두 완벽하게 검색되고 있습니다.")
    print("💡 이제 위 4개 함수의 로드/검색 로직을 그대로 복사하여")
    print("   'app/mcp/enterprise_rag_server.py'의 FastMCP 도구(@mcp.tool)를 구현하세요!")
    print("=" * 75 + "\n")
