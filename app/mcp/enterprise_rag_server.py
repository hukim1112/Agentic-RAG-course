"""
app/mcp/enterprise_rag_server.py
================================
[Instructor Solution] Enterprise RAG FastMCP Server (Stateless Streamable HTTP + Bearer 인증)

사내 규정집, 한국은행 산업보고서, 조직 지식 그래프 및 Microsoft GraphRAG를
FastMCP 도구로 노출하는 엔터프라이즈 RAG 마이크로서비스 서버입니다.

인증:
  .env의 ENTERPRISE_RAG_MCP_TOKEN과 일치하는 Bearer 토큰을 가진 클라이언트만 도구를 호출할 수 있습니다.
  토큰에는 'rag:read' 스코프가 부여되며, 모든 도구는 이 스코프를 요구합니다.

실행:
  python app/mcp/enterprise_rag_server.py            # http://localhost:8010/mcp
"""

import os
import sys
import json
import argparse
import networkx as nx
from enum import Enum
from typing import Annotated, Optional
from pydantic import BaseModel, Field
from fastmcp import FastMCP
from fastmcp.server.auth import require_scopes
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

# 프로젝트 루트 경로 등록
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"), override=True)

from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
from rag.graph.graphrag_tool import run_graphrag_query
from rag.graph.networkx_graph import multi_hop_search

# 1. 인증기: 허용된 토큰과 토큰별 권한(스코프) 등록
SERVER_TOKEN = os.getenv("ENTERPRISE_RAG_MCP_TOKEN")
if not SERVER_TOKEN:
    sys.exit("❌ .env에 ENTERPRISE_RAG_MCP_TOKEN이 없습니다. 토큰을 설정한 뒤 다시 실행하세요.")

verifier = StaticTokenVerifier(
    tokens={
        SERVER_TOKEN: {"client_id": "enterprise-rag-agent", "scopes": ["rag:read"]},
    }
)

# 2. FastMCP 서버 인스턴스 생성 (auth를 지정하면 토큰 없는 요청은 401로 차단됩니다)
mcp = FastMCP(
    name="Enterprise-RAG-Server",
    instructions="사내 규정집, 한국은행 산업보고서, 조직 지식 그래프 및 GraphRAG를 제공하는 통합 RAG 서버",
    auth=verifier,
)

DB_DIR = os.path.join(PROJECT_ROOT, "app/database")
CHROMA_DIR = os.path.join(DB_DIR, "chroma_db")
embeddings = OpenAIEmbeddings(model="text-embedding-3-large")

# 3. 데이터베이스 인스턴스 로드
# 3-1. 사내 규정 Vector DB
policy_vstore = Chroma(
    collection_name="enterprise_policy_store",
    embedding_function=embeddings,
    persist_directory=CHROMA_DIR
)

# 3-2. BOK 산업보고서 Vector DB
bok_vstore = Chroma(
    collection_name="bok_industry_reports_store",
    embedding_function=embeddings,
    persist_directory=CHROMA_DIR
)

# 3-3. NetworkX 지식 그래프 로드
graph_path = os.path.join(DB_DIR, "knowledge_graph_nodelink.json")
with open(graph_path, "r", encoding="utf-8") as f:
    G = nx.node_link_graph(json.load(f))


# 4. Pydantic 입력 스키마 정의
class SearchMethod(str, Enum):
    GLOBAL = "global"
    LOCAL = "local"


class GraphRAGInput(BaseModel):
    query: str = Field(description="전사 프로젝트 거시 분석 또는 특정 인물 전결 규정 관련 질의문")
    search_method: SearchMethod = Field(default=SearchMethod.GLOBAL, description="검색 방식: 전사 종합 요약은 'global', 특정 인물/개체 심층 분석은 'local'")


class GraphRelationInput(BaseModel):
    seed_entity: str = Field(description="관계를 탐색할 출발 인물명 또는 부서명 (예: '김철수 수석', '클라우드운영팀')")
    max_hops: int = Field(default=2, ge=1, le=3, description="그래프 탐색 깊이 (1: 직속 관계, 2: 상위 본부/프로젝트까지 확장)")


# 5. FastMCP 도구 등록 (모든 도구는 'rag:read' 스코프를 요구)
@mcp.tool(
    name="search_company_policy",
    description="사내 복무규정, 출장여비 지급지침, 정보보안 지침을 검색하여 상세 조항과 감액 기준을 반환합니다.",
    auth=require_scopes("rag:read"),
)
def search_company_policy(query: str) -> str:
    docs = policy_vstore.similarity_search(query, k=2)
    if not docs:
        return f"'{query}' 관련 사내 규정을 찾지 못했습니다."
    return "\n\n".join([f"[{d.metadata.get('breadcrumb', '사내규정')}]:\n{d.page_content}" for d in docs])


@mcp.tool(
    name="search_bok_reports",
    description="한국은행(BOK) 2024년 분기별 주력산업 모니터링 보고서(반도체, 자동차 등)의 실적과 전망을 검색합니다. "
                "한 번에 1개 분기, 1개 산업만 검색하세요. 특정 분기의 수치가 필요하면 quarter(1~4)를 지정하세요.",
    auth=require_scopes("rag:read"),
)
def search_bok_reports(
    query: str,
    quarter: Annotated[Optional[int], Field(ge=1, le=4, description="2024년 분기 번호. 지정하면 해당 분기 보고서에서만 검색")] = None,
) -> str:
    search_kwargs = {"filter": {"quarter": quarter}} if quarter else {}
    docs = bok_vstore.similarity_search(query, k=3, **search_kwargs)
    if not docs:
        return f"'{query}' 관련 산업보고서를 찾지 못했습니다."
    return "\n\n".join(
        f"[{d.metadata.get('breadcrumb', '산업보고서')}]:\n"
        f"{d.metadata.get('raw_content', d.page_content)}"
        for d in docs
    )


@mcp.tool(
    name="search_graph_relations",
    description="조직도 지식 그래프에서 특정 인물/부서의 직속 상위 보고선(본부장), 동료, 프로젝트 연결 관계를 탐색합니다.",
    auth=require_scopes("rag:read"),
)
def search_graph_relations(params: GraphRelationInput) -> str:
    sub_edges, _ = multi_hop_search(G, seed_entities=[params.seed_entity], max_hops=params.max_hops)
    if not sub_edges:
        return f"엔티티 '{params.seed_entity}'와 연결된 관계를 찾을 수 없습니다."
    return "\n".join([f"- [{u}] ──({d.get('relation', '연결됨')})──> [{v}]" for u, v, d in sub_edges])


@mcp.tool(
    name="query_enterprise_graphrag",
    description="Microsoft GraphRAG 엔진을 호출하여 전사 프로젝트 종합 리스크 분석(global) 또는 특정 인물/부서의 결재선 맥락(local)을 조회합니다.",
    auth=require_scopes("rag:read"),
)
def query_enterprise_graphrag(params: GraphRAGInput) -> str:
    graphrag_dir = os.path.join(DB_DIR, "graphrag")
    return run_graphrag_query(params.query, method=params.search_method.value, root_dir=graphrag_dir)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Enterprise RAG FastMCP Server")
    parser.add_argument("--port", type=int, default=8010, help="서버 포트 (기본값: 8010)")
    args = parser.parse_args()

    print(f"🚀 Enterprise RAG FastMCP 서버 시작 (포트: {args.port}, Bearer 인증 활성화)...")
    mcp.run(transport="http", host="0.0.0.0", port=args.port)
