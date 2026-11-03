"""
app/mcp/enterprise_rag_server.py
================================
[Instructor Solution] Enterprise RAG FastMCP Server (Stateless Streamable HTTP + Bearer 인증)

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

# 1. 인증기: 토큰마다 '무엇을 할 수 있나(scopes)'와 '누구인가(role, department, clearance)'를 등록
SERVER_TOKEN = os.getenv("ENTERPRISE_RAG_MCP_TOKEN")
if not SERVER_TOKEN:
    sys.exit("❌ .env에 ENTERPRISE_RAG_MCP_TOKEN이 없습니다. 토큰을 설정한 뒤 다시 실행하세요.")

# 역할별 권한 프로필. 운영 환경에서는 IdP가 사용자마다 JWT를 발급하고, 같은 정보가 JWT claim으로 들어옵니다.
#   - scopes:    도메인 접근권 (<도메인>:<동작>)
#   - clearance: 열람 가능한 최고 데이터 등급 (정보보안관리지침의 4등급)
ROLE_PROFILES = {
    "partner":   {"client_id": "user-partner",   "role": "partner",   "department": "외부협력사",
                  "clearance": "public",       "scopes": ["docs:read"]},
    "staff":     {"client_id": "user-staff",     "role": "staff",     "department": "AgenticAI팀",
                  "clearance": "internal",     "scopes": ["docs:read"]},
    "manager":   {"client_id": "user-manager",   "role": "manager",   "department": "경영기획팀",
                  "clearance": "confidential", "scopes": ["docs:read", "erp:read"]},
    "executive": {"client_id": "user-executive", "role": "executive", "department": "AI혁신본부",
                  "clearance": "secret",       "scopes": ["docs:read", "erp:read", "graph:read"]},
}

# 개발용 StaticTokenVerifier: 등록한 dict 전체가 토큰의 claims가 됩니다.
#   - 기본 토큰: 에이전트 서비스 계정 (모든 도구 사용)
#   - '<기본 토큰>:<역할>': 역할별 테스트 토큰
verifier = StaticTokenVerifier(
    tokens={
        SERVER_TOKEN: {"client_id": "enterprise-rag-agent", "role": "service", "department": "AI혁신본부",
                       "clearance": "confidential", "scopes": ["docs:read", "erp:read", "graph:read"]},
        **{f"{SERVER_TOKEN}:{name}": profile for name, profile in ROLE_PROFILES.items()},
    }
)

# 데이터 등급 (낮음 → 높음). 정보보안관리지침의 공개 · 사내한 · 대외비 · 극비
CLEARANCE_LEVELS = ["public", "internal", "confidential", "secret"]


# 사용자 정의 인가 규칙: AuthContext(검증된 토큰 + 접근하려는 도구)를 받아 허용 여부를 반환
def require_clearance(ctx: AuthContext) -> bool:
    """도구의 데이터 등급(class:* 태그)이 사용자의 열람 등급(clearance claim) 이하일 때만 통과합니다."""
    if ctx.token is None:
        return False
    tool_class = next((tag.split(":", 1)[1] for tag in ctx.component.tags if tag.startswith("class:")), None)
    if tool_class not in CLEARANCE_LEVELS:   # 등급이 없거나 모르는 등급의 도구는 막습니다 (fail-closed)
        return False
    user_clearance = ctx.token.claims.get("clearance", "public")
    return CLEARANCE_LEVELS.index(tool_class) <= CLEARANCE_LEVELS.index(user_clearance)


# 2. FastMCP 서버 인스턴스 생성
#    - auth: 토큰 없는 요청은 401로 차단
#    - AuthMiddleware: 모든 도구에 등급 규칙(require_clearance)을 적용하는 서버 전역 정책
mcp = FastMCP(
    name="Enterprise-RAG-Server",
    instructions="사내 규정집, AWS 아키텍처 백서, 전사 지식 그래프(GraphRAG) 및 사내 ERP(Text2SQL)를 제공하는 통합 RAG 서버",
    auth=verifier,
    middleware=[AuthMiddleware(auth=require_clearance)],
)

DB_DIR = os.path.join(PROJECT_ROOT, "app/database")
CHROMA_DIR = os.path.join(DB_DIR, "chroma_db")
SEMANTIC_LAYER_PATH = os.path.join(PROJECT_ROOT, "data/enterprise_erp_sql/semantic_layer.yaml")
ERP_DB_PATH = os.path.join(DB_DIR, "enterprise_erp.db")

embeddings = OpenAIEmbeddings(model="text-embedding-3-large")

# 3. 데이터베이스 및 검색기 인스턴스 로드
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


# 4. 입력 스키마: 각 도구의 인자 타입 힌트(Annotated, Field)로 정의하며 FastMCP가 Pydantic으로 검증합니다.

# 5. FastMCP 도구 등록
#    - auth:  1층 scope (이 도메인에 접근할 수 있는가)
#    - tags:  data:* 는 데이터 도메인, class:* 는 데이터 등급 (2층 등급 규칙이 읽음)
#    권한이 없으면 도구 목록에서 숨겨지고 호출도 거부됩니다.
# 5-1. 사내 규정: 사내한(internal) 등급
@mcp.tool(
    name="search_company_policy",
    description=(
        "사내 5대 공식 규정 문서(국내여비교통비지급규정, 인사복무규정, 정보보안관리지침, 전사위임전결및예산집행규정, 클라우드및GPU인프라운영지침)에서 "
        "출장비 기준, 인사·징계 양정, 보안 반출 절차, 금액별 전결 기준, GPU 유휴 회수 규정 등 사내 제도·원칙 조항을 검색합니다.\n\n"
        "반환 형태: 검색된 조항의 앞뒤 문맥이 결합된 본문과 함께 상단에 [문서 전체 목차(TOC)] 및 [현재 위치 경로(Breadcrumb)]가 포함된 텍스트를 반환합니다."
    ),
    auth=require_scopes("docs:read"),
    tags={"data:docs", "class:internal"},
)
def search_company_policy(query: str) -> str:
    docs = policy_retriever.search(query, top_k=2)
    if not docs:
        return f"'{query}' 관련 사내 규정을 찾지 못했습니다."
    return "\n\n".join([f"[{d.metadata.get('breadcrumb', '사내규정')}]:\n{d.page_content}" for d in docs])


# 5-2. AWS 백서: 공개(public) 등급
@mcp.tool(
    name="search_aws_guides",
    description=(
        "AWS Well-Architected Framework 4대 아키텍처 백서(Security, Reliability, Performance Efficiency, Cost Optimization)에서 "
        "클라우드 설계 원칙, 모범 사례(Best Practice), 흔한 안티패턴(Common anti-patterns), 구현 지침을 검색합니다.\n\n"
        "반환 형태: 검색된 모범 사례의 앞뒤 문맥이 결합된 본문과 함께 상단에 [문서 전체 목차(TOC)] 및 [현재 위치 경로(Breadcrumb)]가 포함된 텍스트를 반환합니다."
    ),
    auth=require_scopes("docs:read"),
    tags={"data:docs", "class:public"},
)
def search_aws_guides(query: str) -> str:
    docs = aws_retriever.search(query, top_k=2)
    if not docs:
        return f"'{query}' 관련 AWS 아키텍처 백서를 찾지 못했습니다."
    return "\n\n".join([f"[{d.metadata.get('breadcrumb', 'AWS 백서')}]:\n{d.page_content}" for d in docs])


# 5-3. 사내 ERP: 대외비(confidential) 등급 (프로젝트 상세 예산 · 인사 데이터)
@mcp.tool(
    name="search_enterprise_erp",
    description=(
        "사내 ERP 정형 데이터베이스(부서 마스터, 임직원 명부, 전략 프로젝트 및 투입 인력, 프로젝트 지출 결의 전표, "
        "GPU 클러스터 할당·가동률 대장, 부서별·비목별 운영 예산 원장)에서 실시간 수치와 현황 레코드를 조회합니다.\n"
        "query에는 SQL 문이 아니라 자연어 질문을 넣으세요. SQL은 이 도구가 스키마를 보고 직접 생성합니다.\n\n"
        "반환 형태: 자연어 질의를 변환해 실행한 SELECT SQL 쿼리문, 적용한 해석 가정, 조회된 결과 마크다운 표(컬럼명 및 행 데이터)를 반환합니다."
    ),
    auth=require_scopes("erp:read"),
    tags={"data:erp", "class:confidential"},
)
def search_enterprise_erp(
    query: Annotated[str, Field(description="조회하려는 내용을 담은 자연어 질문 (SQL 문 아님). 예: 'AgenticAI팀 프로젝트별 승인 예산'")],
    context: Annotated[str, Field(description="사내 규정 등에서 먼저 확인한 참고 기준값 (선택)")] = "",
) -> str:
    return erp_text2sql.invoke(query, context=context).to_text()


# 5-4. 지식 그래프 탐색 도구 5종: 대외비(confidential) 등급 (결재선 · 프로젝트 예산 · 리스크)
#      LangChain 도구의 이름·설명·함수를 그대로 등록해 tool_rag_agent와 정의를 공유합니다.
for graph_tool in graph_explorer_tools:
    mcp.tool(
        name=graph_tool.name,
        description=graph_tool.description,
        auth=require_scopes("graph:read"),
        tags={"data:graph", "class:confidential"},
    )(graph_tool.func)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Enterprise RAG FastMCP Server")
    parser.add_argument("--port", type=int, default=8010, help="서버 포트 (기본값: 8010)")
    args = parser.parse_args()

    print(f"🚀 Enterprise RAG FastMCP 서버 시작 (포트: {args.port}, Bearer 인증 + 도구별 인가 활성화)...")
    mcp.run(transport="http", host="0.0.0.0", port=args.port)
