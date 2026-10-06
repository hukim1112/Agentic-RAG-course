# 🎯 Mission 03: 인증된 MCP 서버 구축 및 Skills 기반 RAG 에이전트 연동

본 미션은 `notebooks/3_MCP_and_Skills.ipynb`에서 학습한 표준 Model Context Protocol (MCP) 명세를 바탕으로,  
사내 4대 데이터베이스를 **Bearer 토큰 기반 스코프(`rag:read`) 인증이 적용된 FastMCP 마이크로서비스 서버**로 패키징하고,  
에이전트가 도구를 사전에 고정 바인딩하지 않고 필요할 때 스스로 레지스트리를 탐색하여 호출하는 **Skills 에이전트(`skill_rag_agent`)**를 연동·검증하는 실습 과제입니다.

---

## 📂 실습 대상 및 핵심 파일

* **MCP 서버 구현 파일 (TODO 작성 대상)**: `app/mcp/enterprise_rag_server.py`  
  👉 **인증 프로바이더 및 4대 도구(@mcp.tool)를 직접 완성하세요!**
* **MCP 서버 레지스트리 (TODO 작성 대상)**: `skills/mcp/references/mcp_servers.json`  
  👉 **공개 위키백과(Stdio) 외에 사내 RAG 서버(HTTP)를 등록하세요!**
* **MCP 스킬 패키지 (제공)**:
  - 스킬 명세서: `skills/mcp/SKILL.md` (점진적 공개 Progressive Disclosure 지침)
  - MCP 범용 클라이언트 CLI: `skills/mcp/scripts/list_tools.py`, `skills/mcp/scripts/execute_tool.py`
* **Skills RAG 에이전트 (제공)**: `app/agents/skill_rag_agent/`
* **사전 학습 노트북**: `notebooks/3_MCP_and_Skills.ipynb`

---

## 📋 미션 목표

1. **[미션 3-1] FastMCP 토큰 인증 서버 구축**:
   - `StaticTokenVerifier`를 설정하여 `.env`의 `ENTERPRISE_RAG_MCP_TOKEN`과 `rag:read` 스코프를 검증하는 FastMCP 서버 인스턴스를 생성합니다.
2. **[미션 3-2] 4대 엔터프라이즈 도구 노출 (@mcp.tool)**:
   - 사내 규정, BOK 보고서, 지식 그래프, GraphRAG 검색 함수 4종을 Pydantic 입력 스키마 및 `require_scopes("rag:read")` 보안 데코레이터와 함께 구현합니다.
3. **[미션 3-3] CLI 클라이언트를 통한 보안 및 도구 실행 검증**:
   - 토큰이 없을 때 `401 Unauthorized`로 차단되는지 확인하고, `--token-env` 옵션으로 안전하게 도구 목록 조회 및 도구 실행을 완수합니다.
4. **[미션 3-4] 서버 레지스트리 등록 및 Skills vs Tool RAG 에이전트 비교**:
   - `mcp_servers.json`에 서버를 등록하고, Chainlit UI에서 `skill_rag_agent`가 도구를 자율 발견하여 답변하는 전체 ReAct 실행 궤적을 `tool_rag_agent`와 비교 분석합니다.

---

## 🛠️ 단계별 수행 가이드

### 1단계: 인증 토큰 (.env) 확인 및 생성

터미널(WSL 환경)에서 사내 MCP 서버 전용 Bearer 토큰이 설정되어 있는지 확인합니다:

```bash
# 토큰 환경변수 등록 여부 확인 (값은 마스킹)
grep -E '^ENTERPRISE_RAG_MCP_TOKEN=' .env | cut -d= -f1
```

> 💡 **토큰이 없는 경우**: 아래 명령어를 실행하여 32바이트 안전 난수 토큰을 자동 생성해 `.env`에 추가하세요:
> ```bash
> echo "ENTERPRISE_RAG_MCP_TOKEN=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')" >> .env
> ```

---

### 2단계: FastMCP 인증기 및 서버 인스턴스 생성 (미션 3-1)

`app/mcp/enterprise_rag_server.py` 파일을 열고, **TODO 1과 TODO 2**를 완성합니다:

```python
# app/mcp/enterprise_rag_server.py (TODO 1 & 2)

from fastmcp import FastMCP
from fastmcp.server.auth import require_scopes
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

# 1. 인증기 설정: 허용된 Bearer 토큰과 토큰별 스코프(rag:read) 등록
SERVER_TOKEN = os.getenv("ENTERPRISE_RAG_MCP_TOKEN")
if not SERVER_TOKEN:
    sys.exit("❌ .env에 ENTERPRISE_RAG_MCP_TOKEN이 없습니다. 토큰을 설정한 뒤 다시 실행하세요.")

verifier = StaticTokenVerifier(
    tokens={
        SERVER_TOKEN: {"client_id": "enterprise-rag-agent", "scopes": ["rag:read"]},
    }
)

# 2. FastMCP 서버 인스턴스 생성 (auth=verifier를 지정하여 무인가 요청 원천 차단)
mcp = FastMCP(
    name="Enterprise-RAG-Server",
    instructions="사내 규정집, 한국은행 산업보고서, 조직 지식 그래프 및 GraphRAG를 제공하는 통합 RAG 서버",
    auth=verifier,
)
```

---

### 3단계: 4대 엔터프라이즈 MCP 도구 구현 (미션 3-2)

`app/mcp/enterprise_rag_server.py`의 **TODO 4(Pydantic 스키마)와 TODO 5(도구 4종)**를 완성합니다.

모든 도구는 **`auth=require_scopes("rag:read")`** 데코레이터를 적용하여 권한이 있는 클라이언트만 실행할 수 있도록 보안을 강화합니다:

```python
# app/mcp/enterprise_rag_server.py (TODO 4 & 5)

# =============================================================================
# 4. Pydantic 입력 스키마 정의 (LLM의 잘못된 인자 전달 사전 방지)
# =============================================================================
class SearchMethod(str, Enum):
    GLOBAL = "global"
    LOCAL = "local"


class GraphRAGInput(BaseModel):
    query: str = Field(description="전사 프로젝트 거시 분석 또는 특정 인물 전결 규정 관련 질의문")
    search_method: SearchMethod = Field(default=SearchMethod.GLOBAL, description="검색 방식: 전사 종합 요약은 'global', 특정 인물/개체 심층 분석은 'local'")


class GraphRelationInput(BaseModel):
    seed_entity: str = Field(description="관계를 탐색할 출발 인물명 또는 부서명 (예: '김철수 수석', '클라우드운영팀')")
    max_hops: int = Field(default=2, ge=1, le=3, description="그래프 탐색 깊이 (1: 직속 관계, 2: 상위 본부/프로젝트까지 확장)")


# =============================================================================
# 5. FastMCP 도구 등록 (4대 DB 노출)
# =============================================================================

# [도구 1] 사내 규정 검색
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


# [도구 2] 한국은행(BOK) 산업보고서 검색
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


# [도구 3] 조직도 지식 그래프 2-Hop 탐색
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


# [도구 4] Microsoft GraphRAG 질의
@mcp.tool(
    name="query_enterprise_graphrag",
    description="Microsoft GraphRAG 엔진을 호출하여 전사 프로젝트 종합 리스크 분석(global) 또는 특정 인물/부서의 결재선 맥락(local)을 조회합니다.",
    auth=require_scopes("rag:read"),
)
def query_enterprise_graphrag(params: GraphRAGInput) -> str:
    graphrag_dir = os.path.join(DB_DIR, "graphrag")
    return run_graphrag_query(params.query, method=params.search_method.value, root_dir=graphrag_dir)
```

---

### 4단계: MCP 서버 가동 및 CLI 보안 검증 (미션 3-3)

새 터미널을 열어 FastMCP 서버를 가동합니다:

#### 🖥️ 터미널 3 (FastMCP 서버 가동 - 포트 8010):
```bash
python app/mcp/enterprise_rag_server.py --port 8010
```
**성공 콘솔 출력:**
```text
🚀 Enterprise RAG FastMCP 서버 시작 (포트: 8010, Bearer 인증 활성화)...
```

---

#### 🧪 CLI 클라이언트를 통한 3단계 보안 검증 (터미널 4에서 실행):

#### ① [보안 검증 1] 토큰 없이 요청 시 401 차단 확인
```bash
python skills/mcp/scripts/list_tools.py --url http://localhost:8010/mcp
```
**기대 출력 (차단 성공):**
```json
[*] Connecting to remote MCP Server: http://localhost:8010/mcp ...
{
  "status": "ERROR",
  "message": "Failed to retrieve tools from 'http://localhost:8010/mcp': Client error '401 Unauthorized' for url 'http://localhost:8010/mcp'..."
}
```

#### ② [보안 검증 2] 환경 변수 토큰(`--token-env`)과 함께 도구 목록 조회
```bash
python skills/mcp/scripts/list_tools.py --url http://localhost:8010/mcp --token-env ENTERPRISE_RAG_MCP_TOKEN
```
**기대 출력 (도구 4종 정상 조회):**
```json
[*] Connecting to remote MCP Server: http://localhost:8010/mcp ...
{
  "status": "SUCCESS",
  "mcp_target": "http://localhost:8010/mcp",
  "tools": [
    {
      "name": "search_company_policy",
      "description": "사내 복무규정, 출장여비 지급지침, 정보보안 지침을 검색하여 상세 조항과 감액 기준을 반환합니다."
    },
    {
      "name": "search_bok_reports",
      "description": "한국은행(BOK) 2024년 분기별 주력산업 모니터링 보고서..."
    },
    {
      "name": "search_graph_relations",
      "description": "조직도 지식 그래프에서 특정 인물/부서의 직속 상위 보고선..."
    },
    {
      "name": "query_enterprise_graphrag",
      "description": "Microsoft GraphRAG 엔진을 호출하여 전사 프로젝트 종합 리스크 분석..."
    }
  ]
}
```

#### ③ [도구 실행 검증 3] 조직 지식 그래프 도구 원격 실행
```bash
python skills/mcp/scripts/execute_tool.py --url http://localhost:8010/mcp --token-env ENTERPRISE_RAG_MCP_TOKEN \
  --tool search_graph_relations --args '{"params": {"seed_entity": "김철수 수석", "max_hops": 2}}'
```
**기대 출력:**
```json
[*] Connecting to remote MCP Server: http://localhost:8010/mcp ...
{
  "status": "SUCCESS",
  "mcp_target": "http://localhost:8010/mcp",
  "tool_name": "search_graph_relations",
  "output": "- [클라우드사업본부] ──(산하조직)──> [클라우드운영팀]\n- [클라우드운영팀] ──(팀장)──> [김철수 수석]..."
}
```

> 💡 **보너스: 기본 제공되는 공개 Stdio 위키백과 MCP 서버 테스트**:
> ```bash
> python skills/mcp/scripts/list_tools.py --transport stdio --command "npx -y wikipedia-mcp"
> ```
> 위 명령어로 `search`, `readArticle` 등 표준 Stdio MCP 도구 목록이 조회되는 것도 확인해 보세요!

---

### 5단계: 레지스트리 등록 및 Skills vs Tool RAG 비교 (미션 3-4)

`skills/mcp/references/mcp_servers.json` 파일을 열고, 기존의 위키백과(Stdio) 서버와 함께 방금 구축한 사내 엔터프라이즈 RAG 서버를 등록합니다:

```json
{
  "wikipedia": {
    "name": "Wikipedia-MCP-Server",
    "transport": "stdio",
    "url": "npx -y wikipedia-mcp",
    "description": "위키백과 백과사전 검색 및 문서 읽기 도구 (search, readArticle. 영문 query만 허용)"
  },
  "enterprise_rag": {
    "name": "Enterprise-RAG-Server",
    "transport": "streamable-http",
    "url": "http://localhost:8010/mcp",
    "auth": {
      "type": "bearer",
      "token_env": "ENTERPRISE_RAG_MCP_TOKEN"
    },
    "description": "사내 규정 검색, 한국은행 산업보고서 검색, 조직도 관계 그래프 탐색, GraphRAG 분석 도구"
  }
}
```

> 🔑 **보안 핵심 원칙 (`token_env`)**:  
> JSON 파일에 실제 토큰 문자열(비밀값)을 직접 하드코딩하지 않고, **환경 변수 이름(`ENTERPRISE_RAG_MCP_TOKEN`)**만 기술합니다.  
> 이를 통해 에이전트의 시스템 프롬프트나 대화 히스토리 및 모니터링 로그에 실제 토큰이 절대 노출되지 않습니다.

---

### 6단계: 웹 UI에서 `skill_rag_agent` 자율 실행 궤적 관찰

FastAPI 서버(`server.py`)와 Chainlit UI(`chainlit_ui.py`)가 띄워진 상태에서, Chainlit UI 프로필을 **`skill_rag_agent`**로 변경하고 테스트를 진행합니다:

#### 🧪 `skill_rag_agent`의 5단계 자율 탐색 궤적 (Trajectory):
1. **스킬 명세 열람**: 질문을 받은 에이전트는 프롬프트에 도구가 없음을 인지하고, `file_read("skills/mcp/SKILL.md")`를 실행
2. **레지스트리 확인**: `file_read("skills/mcp/references/mcp_servers.json")`를 열어 사내 서버 URL과 인증 정보(`ENTERPRISE_RAG_MCP_TOKEN`) 파악
3. **도구 목록 조회**: `bash_command`로 `list_tools.py --url http://localhost:8010/mcp --token-env ...` 실행하여 도구 스키마 획득
4. **원격 도구 실행**: 필요한 인자를 담아 `execute_tool.py`를 실행하여 사내 DB 결과 수집
5. **최종 응답 생성**: 수집된 사실을 종합하여 사용자에게 근거 조항과 함께 최종 답변 반환!

---

### 📊 종합 비교: Tool RAG vs Skills RAG

| 비교 항목 | Tool RAG (`tool_rag_agent`) | Skills RAG (`skill_rag_agent`) |
| :--- | :--- | :--- |
| **도구 바인딩 방식** | 파이썬 코드 레벨에서 `@tool`로 하드코딩 | `SKILL.md` + JSON 레지스트리 기반 동적 탐색 |
| **초기 프롬프트 토큰** | 도구가 늘어날수록 토큰 급증 (100개면 수만 토큰 소모) | **0 토큰** (필요할 때만 파일을 열어보므로 고정 비용) |
| **확장성 (Scalability)** | 새 도구 추가 시 파이썬 에이전트 코드 수정 및 서버 재시작 필요 | **서버 재시작 없음** (`mcp_servers.json`에 줄만 추가) |
| **응답 속도** | 빠름 (곧바로 도구 1회 호출) | 단계별 탐색 과정으로 인해 호출 횟수 및 시간 소요 |
| **실무 적용 추천** | 고정된 핵심 도구 3~5개를 쓰는 단일 목적 챗봇 | 사내 수십 개 마이크로서비스를 넘나드는 **자율형 기업 비서** |

---

## 🔧 트러블슈팅 가이드

| 증상 / 오류 메시지 | 원인 | 해결 방법 |
| :--- | :--- | :--- |
| `Address already in use (:8010)` | 이전 FastMCP 서버가 아직 실행 중 | `lsof -ti:8010 \| xargs -r kill -9` 또는 `pkill -f enterprise_rag_server` |
| `StaticTokenVerifier: 401 Unauthorized` | `.env`의 토큰과 클라이언트 환경 변수 불일치 | `grep ENTERPRISE_RAG_MCP_TOKEN .env` 값을 확인하고, 서버와 클라이언트가 동일한 `.env`를 바라보는지 점검 |
| `json.decoder.JSONDecodeError` (`--args`) | CLI 인자의 따옴표 이스케이프 오류 | 파라미터는 반드시 작은따옴표로 감싸고 내부 키/문자열을 큰따옴표로 전달: `'{"query": "..."}'` |

---

## 🏆 미션 완료 체크리스트

- [ ] `.env`에 `ENTERPRISE_RAG_MCP_TOKEN`이 정상 설정되어 있음을 확인했다.
- [ ] `StaticTokenVerifier` 기반의 인증 FastMCP 서버를 완성했다.
- [ ] 사내 규정, BOK 보고서, 지식 그래프, GraphRAG 도구 4종을 `@mcp.tool`로 완성했다.
- [ ] 토큰이 없을 때 401 차단, 토큰이 있을 때 도구 목록 조회 및 원격 도구 실행이 됨을 CLI로 검증했다.
- [ ] `skills/mcp/references/mcp_servers.json`에 `enterprise_rag`를 보안 규격(`token_env`)에 맞추어 등록했다.
- [ ] Chainlit UI에서 `skill_rag_agent`가 점진적 공개(Progressive Disclosure) 방식으로 MCP 서버를 스스로 찾아 답하는 궤적을 확인했다.
- [ ] Tool RAG와 Skills RAG의 토큰 소모 및 확장성 차이를 완벽히 이해했다.

축하합니다! 이제 여러분은 모델과 도구가 결합된 레거시 구조를 탈피하여, **보안과 토큰 효율성, 무한한 확장성을 겸비한 프로덕션 엔터프라이즈 MCP & Skills 에이전트 아키텍처**를 완벽하게 정복했습니다! 👑🚀
