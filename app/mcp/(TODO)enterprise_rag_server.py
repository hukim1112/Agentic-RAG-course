"""
app/mcp/enterprise_rag_server.py
================================
[실습 미션 2-2] Enterprise RAG FastMCP 서버 구현 (Stateless Streamable HTTP)

📌 [교육생 실습 가이드]
이 파일은 4대 엔터프라이즈 데이터베이스(사내 규정, BOK 보고서, 조직 지식그래프, GraphRAG)를
FastMCP 도구로 노출하여 에이전트가 호출할 수 있는 마이크로서비스 서버를 구축하는 실습입니다.

💡 힌트:
앞선 단계(Mission 2-1)에서 실행한 `app/mcp/test_database.py`의 각 DB 로드 및 검색 코드를
참고하여 아래의 TODO 항목들을 차례대로 완성하세요!
"""

import os
import sys
import json
import networkx as nx
from enum import Enum
from pydantic import BaseModel, Field
from fastmcp import FastMCP

# 프로젝트 루트 경로 등록 (모듈 import 경로 자동 설정)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"), override=True)

from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
from rag.graphrag_tool import run_graphrag_query
from rag.networkx_graph import multi_hop_search

# ==============================================================================
# 1. FastMCP 서버 인스턴스 초기화
# ==============================================================================
mcp = FastMCP(
    name="Enterprise-RAG-Server",
    instructions="사내 규정집, 한국은행 산업보고서, 조직 지식 그래프 및 GraphRAG를 제공하는 통합 RAG 서버"
)

# 데이터베이스 디렉토리 및 공통 임베딩 모델 설정
DB_DIR = os.path.join(PROJECT_ROOT, "app/database")
CHROMA_DIR = os.path.join(DB_DIR, "chroma_db")
embeddings = OpenAIEmbeddings(model="text-embedding-3-large")


# ==============================================================================
# 2. [TODO 1] 4대 데이터베이스 인스턴스 로드 (test_database.py 코드 참고)
# ==============================================================================

# TODO 1-1: [DB 1] 사내 규정 Chroma Vector DB 로드 (collection_name: 'enterprise_policy_store')
policy_vstore = Chroma(
    collection_name="enterprise_policy_store",
    embedding_function=embeddings,
    persist_directory=CHROMA_DIR
)

# TODO 1-2: [DB 2] 한국은행(BOK) 산업보고서 Chroma Vector DB 로드 (collection_name: 'bok_industry_reports_store')
bok_vstore = Chroma(
    collection_name="bok_industry_reports_store",
    embedding_function=embeddings,
    persist_directory=CHROMA_DIR
)

# TODO 1-3: [DB 3] NetworkX 지식 그래프 로드 ('knowledge_graph_nodelink.json')
graph_path = os.path.join(DB_DIR, "knowledge_graph_nodelink.json")
if os.path.exists(graph_path):
    with open(graph_path, "r", encoding="utf-8") as f:
        G = nx.node_link_graph(json.load(f))
else:
    G = nx.Graph()


# ==============================================================================
# 3. [TODO 2] FastMCP 도구 입력용 Pydantic 스키마 정의
# ==============================================================================

class SearchMethod(str, Enum):
    GLOBAL = "global"
    LOCAL = "local"


# TODO 2-1: GraphRAG 질의 입력 스키마 정의 (query, search_method)
class GraphRAGInput(BaseModel):
    query: str = Field(description="전사 프로젝트 거시 분석 또는 특정 인물 전결 규정 관련 질의문")
    search_method: SearchMethod = Field(
        default=SearchMethod.GLOBAL, 
        description="검색 방식: 전사 종합 요약은 'global', 특정 인물/개체 심층 분석은 'local'"
    )


# TODO 2-2: 지식 그래프 관계 탐색 입력 스키마 정의 (seed_entity, max_hops)
class GraphRelationInput(BaseModel):
    seed_entity: str = Field(description="관계를 탐색할 출발 인물명 또는 부서명 (예: '김철수 수석', '클라우드운영팀')")
    max_hops: int = Field(default=2, ge=1, le=3, description="그래프 탐색 깊이 (1: 직속 관계, 2: 상위 본부/프로젝트까지 확장)")


# ==============================================================================
# 4. [TODO 3] FastMCP 도구 등록 (@mcp.tool 데코레이터 활용)
# ==============================================================================

# TODO 3-1: [도구 1] 사내 규정 검색 도구 (search_company_policy)
@mcp.tool(
    name="search_company_policy",
    description="사내 복무규정, 출장여비 지급지침을 검색하여 상세 조항과 감액 기준을 반환합니다."
)
def search_company_policy(query: str) -> str:
    """
    사내 규정집 Chroma DB에서 쿼리와 가장 유사한 상위 k=2개 문서를 검색하여 반환합니다.
    """
    # TODO: policy_vstore.similarity_search(query, k=2)를 호출하고 포맷팅하여 반환하세요.
    docs = policy_vstore.similarity_search(query, k=2)
    if not docs:
        return f"'{query}' 관련 사내 규정을 찾지 못했습니다."
    return "\n\n".join([f"[{d.metadata.get('breadcrumb', '사내규정')}]:\n{d.page_content}" for d in docs])


# TODO 3-2: [도구 2] 한국은행 BOK 산업보고서 검색 도구 (search_bok_reports)
@mcp.tool(
    name="search_bok_reports",
    description="한국은행(BOK) 분기별 주력산업 모니터링 보고서(반도체, 자동차 등)의 실적과 전망을 검색합니다."
)
def search_bok_reports(query: str) -> str:
    """
    BOK 산업보고서 Chroma DB에서 쿼리와 가장 유사한 상위 k=2개 문서를 검색하여 반환합니다.
    """
    # TODO: bok_vstore.similarity_search(query, k=2)를 호출하고 포맷팅하여 반환하세요.
    docs = bok_vstore.similarity_search(query, k=2)
    if not docs:
        return f"'{query}' 관련 산업보고서를 찾지 못했습니다."
    return "\n\n".join([f"[{d.metadata.get('source_file', '산업보고서')}]:\n{d.page_content}" for d in docs])


# TODO 3-3: [도구 3] 조직도 지식 그래프 2-Hop 탐색 도구 (search_graph_relations)
@mcp.tool(
    name="search_graph_relations",
    description="조직도 지식 그래프에서 특정 인물/부서의 직속 상위 보고선(본부장), 동료, 프로젝트 연결 관계를 고속 탐색합니다."
)
def search_graph_relations(params: GraphRelationInput) -> str:
    """
    NetworkX 지식 그래프에서 seed_entity로부터 max_hops 이내의 서브그래프 관계 목록을 추출합니다.
    """
    # TODO: multi_hop_search(G, seed_entities=[params.seed_entity], max_hops=params.max_hops)를 호출하세요.
    sub_edges, _ = multi_hop_search(G, seed_entities=[params.seed_entity], max_hops=params.max_hops)
    if not sub_edges:
        return f"엔티티 '{params.seed_entity}'와 연결된 관계를 찾을 수 없습니다."
    return "\n".join([f"- [{u}] ──({d.get('relation', '연결됨')})──> [{v}]" for u, v, d in sub_edges])


# TODO 3-4: [도구 4] Microsoft GraphRAG 질의 도구 (query_enterprise_graphrag)
@mcp.tool(
    name="query_enterprise_graphrag",
    description="Microsoft GraphRAG 엔진을 호출하여 전사 프로젝트 종합 리스크 분석(global) 또는 특정 인물/부서의 결재선 맥락(local)을 조회합니다."
)
def query_enterprise_graphrag(params: GraphRAGInput) -> str:
    """
    Microsoft GraphRAG 엔진에 global 또는 local 검색 쿼리를 전달하여 결과를 반환합니다.
    """
    # TODO: run_graphrag_query(params.query, method=params.search_method.value, root_dir=...)를 호출하세요.
    graphrag_dir = os.path.join(DB_DIR, "graphrag")
    if not os.path.exists(graphrag_dir):
        graphrag_dir = os.path.join(PROJECT_ROOT, "data/graphrag")
    return run_graphrag_query(params.query, method=params.search_method.value, root_dir=graphrag_dir)


# ==============================================================================
# 5. FastMCP 서버 구동 (포트: 8010, Stateless Streamable HTTP)
# ==============================================================================
if __name__ == "__main__":
    print("🚀 [FastMCP] Enterprise RAG 서버 가동 중 (http://0.0.0.0:8010/mcp)...")
    mcp.run(transport="http", host="0.0.0.0", port=8010)
