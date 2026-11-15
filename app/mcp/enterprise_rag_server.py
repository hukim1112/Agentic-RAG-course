"""
app/mcp/enterprise_rag_server.py
================================
[Mission 03] Enterprise RAG FastMCP Server (Stateless Streamable HTTP + Bearer 인증 · 도구별 인가)

사내 규정집(Vector), AWS 아키텍처 백서(Vector), 전사 지식 그래프(GraphRAG), 사내 ERP(Text2SQL)를
FastMCP 도구(`search_*` 3종 + 지식 그래프 탐색 `graph_*` 5종)로 노출하는 엔터프라이즈 RAG 마이크로서비스 서버입니다.

인증:
  .env의 ENTERPRISE_RAG_MCP_TOKEN과 일치하는 Bearer 토큰을 가진 클라이언트만 도구를 호출할 수 있습니다.
  이 토큰은 에이전트용 서비스 계정으로 모든 도구를 쓸 수 있습니다.
  역할별 테스트 토큰은 '<기본 토큰>:partner', ':staff', ':manager', ':executive' 형태입니다.

인가 (두 층):
  1층 scope  도메인 접근권  도구마다 require_scopes("<도메인>:read")
  2층 등급   데이터 등급     도구의 class:* 태그 ≤ 사용자의 clearance claim (서버 전역 AuthMiddleware)

  도구                       tag                              scope
  search_company_policy      data:docs   class:internal        docs:read
  search_aws_guides          data:docs   class:public          docs:read
  search_enterprise_erp      data:erp    class:confidential    erp:read
  graph_* (탐색 도구 5종)     data:graph  class:confidential    graph:read

👉 TODO 1, 2, 3을 완성하세요. (missions/03_missions.md 2~3단계 참고)

실행:
  python app/mcp/enterprise_rag_server.py            # http://localhost:8010/mcp
"""

import os
import sys
import argparse
from typing import Annotated, Optional
from pydantic import Field
from fastmcp import FastMCP
from fastmcp.server.auth import AuthContext, require_scopes
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier
from fastmcp.server.middleware import AuthMiddleware

# 프로젝트 루트 경로 등록
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"), override=True)

from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
from app.utils import init_chat_model
from rag.graph.graph_explorer import graph_explorer_tools
from rag.sql import Text2SQL
from rag.vector.retrieval import HybridRetriever

# ==============================================================================
# TODO 1. 인증기 및 등급 규칙 정의 (missions/03_missions.md 2단계 참고)
#   - os.getenv("ENTERPRISE_RAG_MCP_TOKEN")으로 토큰을 읽고, 없으면 sys.exit()로 종료
#   - ROLE_PROFILES (partner, staff, manager, executive) 정의: role, department, clearance, scopes
#   - StaticTokenVerifier에 SERVER_TOKEN(서비스 계정) 및 '<SERVER_TOKEN>:<role>' 등록
#   - CLEARANCE_LEVELS = ["public", "internal", "confidential", "secret"]
#   - require_clearance(ctx: AuthContext) 사용자 정의 인가 규칙 작성
#       도구의 class:* 태그 등급 ≤ 토큰 claims의 clearance 이면 True (등급 태그가 없으면 False)
# ==============================================================================
verifier = None  # TODO


# ==============================================================================
# TODO 2. FastMCP 서버 인스턴스 생성
#   - name="Enterprise-RAG-Server", instructions="...", auth=verifier
#   - middleware=[AuthMiddleware(auth=require_clearance)]
# ==============================================================================
mcp = None  # TODO


DB_DIR = os.path.join(PROJECT_ROOT, "app/database")
CHROMA_DIR = os.path.join(DB_DIR, "chroma_db")
SEMANTIC_LAYER_PATH = os.path.join(PROJECT_ROOT, "data/enterprise_erp_sql/semantic_layer.yaml")
ERP_DB_PATH = os.path.join(DB_DIR, "enterprise_erp.db")

embeddings = OpenAIEmbeddings(model="text-embedding-3-large")

# 3. 데이터베이스 및 검색기 인스턴스 로드 (제공)
# 3-1. 사내 규정 Vector DB + HybridRetriever
policy_vstore = Chroma(
    collection_name="enterprise_policy_store",
    embedding_function=embeddings,
    persist_directory=CHROMA_DIR,
)
policy_retriever = HybridRetriever.from_chroma(policy_vstore, window_size=2)

# 3-2. AWS Well-Architected 백서 Vector DB + HybridRetriever
aws_vstore = Chroma(
    collection_name="aws_waf_guides_store",
    embedding_function=embeddings,
    persist_directory=CHROMA_DIR,
)
aws_retriever = HybridRetriever.from_chroma(aws_vstore, window_size=2)

# 3-3. 사내 ERP Text2SQL 워크플로우
erp_llm = init_chat_model(model="gemini-3.8-flash", temperature=0.0)
erp_text2sql = Text2SQL.from_semantic_layer(
    SEMANTIC_LAYER_PATH,
    llm=erp_llm,
    db_path=ERP_DB_PATH if os.path.exists(ERP_DB_PATH) else None,
    embeddings=embeddings,
)


# ==============================================================================
# TODO 3. FastMCP 도구 등록: 검색 도구 3종 + 지식 그래프 탐색 도구 5종 (missions/03_missions.md 3단계 참고)
#   ※ 입력 스키마는 별도 클래스 없이 각 도구의 인자 타입 힌트(Annotated, Field)로 정의합니다.
#   - search_company_policy(query: str)
#       auth=require_scopes("docs:read"),  tags={"data:docs", "class:internal"}
#   - search_aws_guides(query: str)
#       auth=require_scopes("docs:read"),  tags={"data:docs", "class:public"}
#   - search_enterprise_erp(query: str, context: str = "")   ※ query는 자연어 질문 (SQL 아님)
#       auth=require_scopes("erp:read"),   tags={"data:erp", "class:confidential"}
#   - 지식 그래프 탐색 도구 5종: graph_explorer_tools(rag/graph/graph_explorer.py)의 이름·설명·함수를 그대로 등록
#       auth=require_scopes("graph:read"), tags={"data:graph", "class:confidential"}
# ==============================================================================


if __name__ == "__main__":
    if mcp is None:
        sys.exit("❌ TODO 1, 2를 먼저 완성하세요. (missions/03_missions.md 2단계)")

    parser = argparse.ArgumentParser(description="Enterprise RAG FastMCP Server")
    parser.add_argument("--port", type=int, default=8010, help="서버 포트 (기본값: 8010)")
    args = parser.parse_args()

    print(f"🚀 Enterprise RAG FastMCP 서버 시작 (포트: {args.port}, Bearer 인증 + 도구별 인가 활성화)...")
    mcp.run(transport="http", host="0.0.0.0", port=args.port)
