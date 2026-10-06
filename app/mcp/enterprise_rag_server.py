"""
app/mcp/enterprise_rag_server.py
================================
[Mission 03] Enterprise RAG FastMCP Server (Stateless Streamable HTTP + Bearer 인증)

사내 규정집, 한국은행 산업보고서, 조직 지식 그래프 및 Microsoft GraphRAG를
FastMCP 도구로 노출하는 엔터프라이즈 RAG 마이크로서비스 서버입니다.

인증:
  .env의 ENTERPRISE_RAG_MCP_TOKEN과 일치하는 Bearer 토큰을 가진 클라이언트만 도구를 호출할 수 있습니다.
  토큰에는 'rag:read' 스코프가 부여되며, 모든 도구는 이 스코프를 요구합니다.

👉 TODO 1, 2, 4, 5를 완성하세요. (missions/03_missions.md 2~3단계 참고)
   검색 로직은 app/mcp/test_database.py의 각 테스트 함수와 같습니다.

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

# ==============================================================================
# TODO 1. 인증기: 허용된 토큰과 토큰별 권한(스코프) 등록
#   - os.getenv("ENTERPRISE_RAG_MCP_TOKEN")으로 토큰을 읽고, 없으면 sys.exit()로 종료
#   - StaticTokenVerifier(tokens={토큰: {"client_id": "enterprise-rag-agent", "scopes": ["rag:read"]}})
# ==============================================================================
verifier = None  # TODO


# ==============================================================================
# TODO 2. FastMCP 서버 인스턴스 생성
#   - name="Enterprise-RAG-Server", instructions="...", auth=verifier
#   - auth를 지정하면 토큰 없는 요청은 401로 차단됩니다.
# ==============================================================================
mcp = None  # TODO


DB_DIR = os.path.join(PROJECT_ROOT, "app/database")
CHROMA_DIR = os.path.join(DB_DIR, "chroma_db")
embeddings = OpenAIEmbeddings(model="text-embedding-3-large")

# 3. 데이터베이스 인스턴스 로드 (제공)
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


# ==============================================================================
# TODO 4. Pydantic 입력 스키마 정의
#   - SearchMethod(str, Enum): GLOBAL="global", LOCAL="local"
#   - GraphRAGInput: query(str), search_method(SearchMethod, 기본값 GLOBAL)
#   - GraphRelationInput: seed_entity(str), max_hops(int, 기본값 2, ge=1, le=3)
#   - 각 Field에는 LLM이 읽을 description을 작성하세요.
# ==============================================================================


# ==============================================================================
# TODO 5. FastMCP 도구 등록 (모든 도구에 auth=require_scopes("rag:read") 적용)
#   - search_company_policy(query: str)            → policy_vstore.similarity_search(query, k=2)
#   - search_bok_reports(query: str, quarter: 1~4)  → bok_vstore.similarity_search(query, k=3, filter={"quarter": quarter})
#   - search_graph_relations(params: GraphRelationInput) → multi_hop_search(G, ...)
#   - query_enterprise_graphrag(params: GraphRAGInput)   → run_graphrag_query(..., root_dir=DB_DIR/graphrag)
#
#   도구 인터페이스 설계 체크포인트:
#   - 결과가 없을 때 "찾지 못했다"는 메시지를 반환하나요?
#   - 반환 결과에 출처(breadcrumb 등)가 포함되나요?
# ==============================================================================


if __name__ == "__main__":
    if mcp is None:
        sys.exit("❌ TODO 1, 2를 먼저 완성하세요. (missions/03_missions.md 2단계)")

    parser = argparse.ArgumentParser(description="Enterprise RAG FastMCP Server")
    parser.add_argument("--port", type=int, default=8010, help="서버 포트 (기본값: 8010)")
    args = parser.parse_args()

    print(f"🚀 Enterprise RAG FastMCP 서버 시작 (포트: {args.port}, Bearer 인증 활성화)...")
    mcp.run(transport="http", host="0.0.0.0", port=args.port)
