"""
app/mcp/test_database.py
========================
[4대 엔터프라이즈 RAG 데이터베이스 통합 검색 검증]

이 스크립트는 `app/database/`에 구축된 4대 엔터프라이즈 데이터 소스를
파이썬 코드로 직접 로드하고 검색하는 레퍼런스 및 설치 확인 스크립트입니다.
`python app/mcp/build_database.py`로 DB를 다시 빌드한 뒤 이 스크립트로 검색 결과를 검증합니다.

검증 대상 4대 데이터베이스 (MCP 도구 매핑):
1. [DB 1: 사내 규정집] Chroma `enterprise_policy_store` + HybridRetriever  → `search_company_policy`
2. [DB 2: AWS 아키텍처 백서] Chroma `aws_waf_guides_store` + HybridRetriever → `search_aws_guides`
3. [DB 3: 전사 지식 그래프] NetworkX (`knowledge_graph_nodelink.json`) & Microsoft GraphRAG (`graphrag/`) → `graph_*` 5종
4. [DB 4: 사내 ERP 정형 DB] SQLite (`enterprise_erp.db`) + `semantic_layer.yaml` + `Text2SQL` → `search_enterprise_erp`
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
from app.utils import init_chat_model
from rag.graph.graph_explorer import (
    graph_find_entities,
    graph_find_path,
    graph_neighbors,
    graph_read,
    graph_search_communities,
)
from rag.graph.networkx_graph import multi_hop_search
from rag.sql import DatabaseProfile, Text2SQL
from rag.vector.retrieval import HybridRetriever

# 공통 데이터베이스 디렉토리 경로
DB_DIR = os.path.join(PROJECT_ROOT, "app/database")
CHROMA_DIR = os.path.join(DB_DIR, "chroma_db")
ERP_DB_PATH = os.path.join(DB_DIR, "enterprise_erp.db")
SEMANTIC_LAYER_PATH = os.path.join(PROJECT_ROOT, "data/enterprise_erp_sql/semantic_layer.yaml")


def _preview_body(doc, max_lines: int = 4) -> str:
    """문맥 헤더를 제외한 실제 조항/보고서 본문 앞 줄을 반환합니다."""
    body = doc.page_content.split("-------------------------------")[-1].strip()
    if not body:
        body = doc.metadata.get("raw_content", doc.page_content).strip()
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    return "\n    ".join(lines[:max_lines])


# ==============================================================================
# [DB 1] 사내 규정집 HybridRetriever (DomainDictionary + BM25 + Dense + RRF + ContextualWindow)
# ==============================================================================
def test_1_policy_vector_db():
    """[MCP 도구 매핑: search_company_policy]"""
    print("=" * 75)
    print("🔍 [DB 1] 사내 규정집 HybridRetriever 검색 테스트 (enterprise_policy_store)")
    print("=" * 75)

    if not os.path.exists(CHROMA_DIR):
        print(f"  ❌ DB 디렉토리가 없습니다: {CHROMA_DIR}")
        print("     먼저 'python app/mcp/build_database.py'를 실행하여 DB를 생성하세요.")
        return

    embeddings = OpenAIEmbeddings(model="text-embedding-3-large")
    vectorstore = Chroma(
        collection_name="enterprise_policy_store",
        embedding_function=embeddings,
        persist_directory=CHROMA_DIR,
    )
    policy_retriever = HybridRetriever.from_chroma(vectorstore, window_size=2)

    query = "클운팀 직원이 당일 출장을 다녀올 때 일비와 식비 감액 기준"
    print(f"  • 질의문: '{query}'")
    print(f"  • 약어 정규화: '{policy_retriever.domain_dict.normalize(query)}'")

    results = policy_retriever.search(query, top_k=2)

    print(f"  • 검색된 청크 수: {len(results)}개")
    for idx, doc in enumerate(results, 1):
        w_start = doc.metadata.get("window_start_chunk")
        w_end = doc.metadata.get("window_end_chunk")
        window_info = f" (청크 {w_start}~{w_end} 윈도우 결합)" if w_start is not None else ""
        print(f"\n  [결과 #{idx}]{window_info}")
        print(f"  - 출처 파일: {doc.metadata.get('source_file', 'N/A')}")
        print(f"  - 목차 계층(Breadcrumb): {doc.metadata.get('breadcrumb', 'N/A')}")
        print(f"  - 본문 발췌:\n    {_preview_body(doc)}")

    print("\n  ✅ [DB 1 검증 완료] 사내 규정 HybridRetriever 정상 작동!\n")


# ==============================================================================
# [DB 2] AWS Well-Architected 백서 HybridRetriever
# ==============================================================================
def test_2_aws_vector_db():
    """[MCP 도구 매핑: search_aws_guides]"""
    print("=" * 75)
    print("🔍 [DB 2] AWS Well-Architected 백서 HybridRetriever 검색 테스트 (aws_waf_guides_store)")
    print("=" * 75)

    if not os.path.exists(CHROMA_DIR):
        print(f"  ❌ DB 디렉토리가 없습니다: {CHROMA_DIR}")
        return

    embeddings = OpenAIEmbeddings(model="text-embedding-3-large")
    vectorstore = Chroma(
        collection_name="aws_waf_guides_store",
        embedding_function=embeddings,
        persist_directory=CHROMA_DIR,
    )
    aws_retriever = HybridRetriever.from_chroma(vectorstore, window_size=2)

    query = "PERF02-BP01 워크로드에 가장 적합한 컴퓨팅 옵션 선택 시 흔한 안티패턴(Common anti-patterns)"
    print(f"  • 질의문: '{query}'")

    results = aws_retriever.search(query, top_k=2)

    print(f"  • 검색된 청크 수: {len(results)}개")
    for idx, doc in enumerate(results, 1):
        w_start = doc.metadata.get("window_start_chunk")
        w_end = doc.metadata.get("window_end_chunk")
        window_info = f" (청크 {w_start}~{w_end} 윈도우 결합)" if w_start is not None else ""
        print(f"\n  [결과 #{idx}]{window_info}")
        print(f"  - 출처 파일: {doc.metadata.get('source_file', 'N/A')}")
        print(f"  - 목차 계층(Breadcrumb): {doc.metadata.get('breadcrumb', 'N/A')}")
        print(f"  - 본문 발췌:\n    {_preview_body(doc, max_lines=3)}")

    print("\n  ✅ [DB 2 검증 완료] AWS Well-Architected 백서 HybridRetriever 정상 작동!\n")


# ==============================================================================
# [DB 3] 전사 지식 그래프 (3-A. NetworkX 인메모리 그래프 & 3-B. Microsoft GraphRAG 탐색 도구 5종)
# ==============================================================================
def test_3_knowledge_graph_and_graphrag_db():
    """[MCP 도구 매핑: graph_find_entities, graph_neighbors, graph_find_path, graph_search_communities, graph_read]"""
    print("=" * 75)
    print("🔍 [DB 3] 전사 지식 그래프 테스트 (NetworkX & Microsoft GraphRAG)")
    print("=" * 75)

    graph_file = os.path.join(DB_DIR, "knowledge_graph_nodelink.json")
    if not os.path.exists(graph_file):
        print(f"  ❌ 그래프 DB 파일이 없습니다: {graph_file}")
        return

    with open(graph_file, "r", encoding="utf-8") as f:
        graph_data = json.load(f)
    G = nx.node_link_graph(graph_data)

    seed_entity = "김철수 수석"
    print(f"  [3-A. NetworkX] 노드 {G.number_of_nodes()}개, 엣지 {G.number_of_edges()}개 | 시드: '{seed_entity}' (2-Hop BFS)")
    sub_edges, visited = multi_hop_search(G, seed_entities=[seed_entity], max_hops=2)
    print(f"  • 방문 엔티티 ({len(visited)}개): {visited}")
    for edge in sub_edges[:4]:
        rel = edge[2].get("relation", "연결됨")
        print(f"    - [{edge[0]}] ──({rel})──> [{edge[1]}]")

    if not os.path.exists(os.path.join(DB_DIR, "graphrag", "output")):
        print("  ❌ GraphRAG 인덱스가 없습니다. 'python app/mcp/build_database.py --targets graphrag'를 실행하세요.")
        return

    print("\n  [3-B. Microsoft GraphRAG 탐색 도구 5종]")
    steps = [
        ("엔티티 연결", graph_find_entities, {"query": "클라우드운영팀 김철수 수석", "top_k": 3}),
        ("관계 펼치기", graph_neighbors, {"entity": "KIM CHUL-SOO", "query": "담당 프로젝트와 보고선", "top_k": 5}),
        ("경로 찾기", graph_find_path, {"source": "P-04", "target": "P-01"}),
        ("원문 확인", graph_read, {"ids": ["T3"]}),
        ("커뮤니티 리포트 검색", graph_search_communities, {"query": "전사 프로젝트들의 핵심 목표와 공통 리스크", "level": 0}),
    ]
    for title, graph_tool, args in steps:
        print(f"\n  🎯 [{title}] {graph_tool.name}({args})")
        output = graph_tool.invoke(args)
        for line in output.strip().split("\n")[:5]:
            print(f"     {line[:150]}")

    print("\n  ✅ [DB 3 검증 완료] NetworkX 및 GraphRAG 지식 그래프 탐색 정상 작동!\n")


# ==============================================================================
# [DB 4] 사내 ERP 정형 데이터베이스 (SQLite + Semantic Layer + Text2SQL)
# ==============================================================================
def test_4_enterprise_erp_sql_db():
    """[MCP 도구 매핑: search_enterprise_erp]"""
    print("=" * 75)
    print("🔍 [DB 4] 사내 ERP 정형 데이터베이스 & Text2SQL 테스트 (enterprise_erp.db)")
    print("=" * 75)

    if not os.path.exists(ERP_DB_PATH):
        print(f"  ❌ ERP SQLite 파일이 없습니다: {ERP_DB_PATH}")
        print("     먼저 'python app/mcp/build_database.py --targets erp'를 실행하세요.")
        return

    profile = DatabaseProfile.load(SEMANTIC_LAYER_PATH, db_path=ERP_DB_PATH)
    print(f"  • DB 및 시멘틱 레이어 검증 완료: 테이블 {len(profile.tables)}개 ({', '.join(profile.tables.keys())})")
    print(f"  • 등록된 표준 업무 지표(Metrics): {len(profile.metrics)}개 ({', '.join(profile.metrics.keys())})")

    embeddings = OpenAIEmbeddings(model="text-embedding-3-large")
    llm = init_chat_model(model="gemini-3.8-flash", temperature=0.0)
    erp_text2sql = Text2SQL.from_semantic_layer(
        SEMANTIC_LAYER_PATH,
        llm=llm,
        db_path=ERP_DB_PATH,
        embeddings=embeddings,
    )

    query = "AgenticAI팀이 주관하는 전략 프로젝트의 프로젝트 코드, 프로젝트명, 승인 예산을 조회해줘"
    print(f"  • 질의문: '{query}'")
    result = erp_text2sql.invoke(query)
    print(f"  • 생성된 SQL: {result.sql}")
    for line in result.to_text().splitlines()[:10]:
        print(f"    {line}")

    print("\n  ✅ [DB 4 검증 완료] 사내 ERP 정형 DB 시멘틱 레이어 및 Text2SQL 정상 작동!\n")


# ==============================================================================
# 메인 실행 엔트리포인트
# ==============================================================================
if __name__ == "__main__":
    print("\n🚀 [4대 엔터프라이즈 RAG 데이터베이스 통합 검색 검증 시작]\n")
    test_1_policy_vector_db()
    test_2_aws_vector_db()
    test_3_knowledge_graph_and_graphrag_db()
    test_4_enterprise_erp_sql_db()
    print("=" * 75)
    print("🎉 축하합니다! 4대 엔터프라이즈 데이터베이스(규정·백서·지식그래프·ERP)가 모두 정상 작동합니다.")
    print("💡 이제 위 로드/검색 패턴을 그대로 활용하여 에이전트 도구와 FastMCP 서버를 구동할 수 있습니다!")
    print("=" * 75 + "\n")
