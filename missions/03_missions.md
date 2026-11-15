# 🎯 Mission 03: 인증·인가된 Enterprise RAG FastMCP 서버 구축 및 기동

본 미션은 `notebooks/5_MCP_and_Skills.ipynb`의 Part 1\~3에서 학습한 **FastMCP 프레임워크와 2층 인가(Authorization) 아키텍처**를 바탕으로,  
사내 4대 데이터베이스(규정집, AWS 아키텍처 백서, 사내 ERP, 전사 지식 그래프)를 **Bearer 토큰 인증과 역할·등급별 접근 제어가 적용된 독립 마이크로서비스 서버(`app/mcp/enterprise_rag_server.py`)**로 직접 구현하고 기동하는 실습 과제입니다.

---

## 📂 실습 대상 및 핵심 파일

* **MCP 서버 구현 파일 (TODO 작성 대상)**: `app/mcp/enterprise_rag_server.py`  
  👉 **이 파일의 `TODO 1, 2`(인증·인가 프로바이더 및 서버 생성)와 `TODO 3`(4대 DB 도구 등록)을 완성하세요!**
* **사전 구축된 4대 데이터베이스 (제공)**: `app/database/`
  - `chroma_db/`: 사내 규정(`enterprise_policy_store`, 239청크) 및 AWS Well-Architected 백서(`aws_waf_guides_store`, 4,641청크)
  - `enterprise_erp.db`: 사내 ERP 정형 데이터베이스 (SQLite, 7개 테이블 — `Text2SQL` 연동)
  - `graphrag/`: Microsoft GraphRAG 전사 지식 그래프 인덱스 (`rag/graph/graph_explorer.py`의 탐색 도구 5종 연동)
* **연계 학습 노트북**: `notebooks/5_MCP_and_Skills.ipynb`

---

## 📋 미션 목표

1. **[미션 3-1] 인증 토큰(`.env`) 점검 및 생성**:
   - 사내 MCP 서버 전용 Bearer 토큰(`ENTERPRISE_RAG_MCP_TOKEN`)이 환경 변수에 설정되어 있는지 확인합니다.
2. **[미션 3-2] FastMCP 토큰 인증기 및 2층 인가 미들웨어 구축 (`TODO 1, 2`)**:
   - `StaticTokenVerifier`에 에이전트 서비스 계정 토큰과 역할별 테스트 토큰(`:partner`, `:staff`, `:manager`, `:executive`)을 등록하고, 데이터 등급 규칙 `require_clearance`를 서버 전역 `AuthMiddleware`로 연결합니다.
3. **[미션 3-3] 4대 데이터베이스 MCP 도구 노출 (`TODO 3`)**:
   - 검색 도구 3종(`search_company_policy`, `search_aws_guides`, `search_enterprise_erp`)과 지식 그래프 탐색 도구 5종(`graph_*`)을 도메인 scope(`require_scopes("<도메인>:read")`)와 데이터 등급 태그(`tags={"data:*", "class:*"}`)와 함께 등록합니다.
4. **[미션 3-4] MCP 서버 기동 및 노트북 Part 3\~6.1 연동 확인**:
   - 포트 `8010`에 서버를 띄우고, `notebooks/5_MCP_and_Skills.ipynb`의 역할별 도구 가시성 테스트(Part 3)와 에이전트 연결 실습(Part 4\~5, Part 6.1 카탈로그 확인)을 내가 만든 서버로 실행합니다.

---

## 🧭 전체 진행 흐름 (노트북 5와 함께 진행)

| 순서 | 단계 | 수행 위치 |
| :---: | :--- | :--- |
| ① | **Part 1\~2 & Part 3(이론)**: MCP 개념, FastMCP 스키마 검증, 인증/인가 2층 구조 이해 | `notebooks/5_MCP_and_Skills.ipynb` |
| ② | **🎯 Mission 03 (현재 문서)**: 토큰 확인 → `enterprise_rag_server.py` TODO 1·2·3 완성 → 서버 기동 | **이 문서 1\~4단계** |
| ③ | **Part 3(실습)\~Part 6.1(카탈로그 확인)**: 역할별 가시성 검증, 정적 바인딩, Search & Proxy, Skills 개념 | `notebooks/5_MCP_and_Skills.ipynb` |
| ④ | **🎯 Mission 04 (1\~2단계)**: CLI 보안 검증 → `mcp_servers.json` 등록 | `missions/04_missions.md` |
| ⑤ | **Part 6.1(레지스트리 확인)\~Part 7**: Skills 에이전트 실행·토큰 비노출 검증 및 마무리 → **Mission 04 (3단계: Chainlit 비교)** | `notebooks/5_MCP_and_Skills.ipynb` → `missions/04_missions.md` |

---

## 🛠️ 단계별 수행 가이드

### 1단계: 인증 토큰 (.env) 확인 및 생성 (미션 3-1)

터미널에서 사내 MCP 서버 전용 Bearer 토큰이 `.env`에 설정되어 있는지 확인합니다:

```bash
# 토큰 환경변수 등록 여부 확인 (값은 마스킹되어 변수명만 출력됨)
grep -E '^ENTERPRISE_RAG_MCP_TOKEN=' .env | cut -d= -f1
```

> 💡 **`ENTERPRISE_RAG_MCP_TOKEN`이 출력되지 않는 경우**: 아래 명령어를 실행하여 32바이트 난수 토큰을 생성해 `.env`에 추가하세요:
> ```bash
> echo "ENTERPRISE_RAG_MCP_TOKEN=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')" >> .env
> ```

---

### 2단계: FastMCP 인증기 및 서버 인스턴스 생성 (미션 3-2)

`app/mcp/enterprise_rag_server.py` 파일을 열고, **TODO 1과 TODO 2**를 완성합니다.

> 📌 **시작 상태 확인**:  
> 파일 상단에는 `FastMCP`, `AuthContext`, `require_scopes`, `StaticTokenVerifier`, `AuthMiddleware` 등의 import 문이 이미 준비되어 있고, 중간(3번 섹션)에는 DB 및 검색기 로딩 코드가 작성되어 있습니다.  
> 파일의 **`TODO 1` ~ `TODO 2` 구간(`verifier = None  # TODO` 및 `mcp = None  # TODO`)을 아래 코드로 교체**하세요.  
> *(TODO 2를 완성하기 전에 서버를 실행하면 `❌ TODO 1, 2를 먼저 완성하세요.` 메시지와 함께 종료됩니다.)*

```python
# app/mcp/enterprise_rag_server.py (TODO 1 & 2 교체 코드)

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
```

---

### 3단계: 4대 데이터베이스 MCP 도구 구현 (미션 3-3)

이어서 `app/mcp/enterprise_rag_server.py` 하단의 **TODO 3(검색 도구 3종 + 그래프 탐색 도구 5종 등록)**을 완성합니다.

> 📌 **교체 위치**: 파일 하단의 **`TODO 3` 주석 블록을 아래 코드 전체로 교체**하세요 (`if __name__ == "__main__":` 줄 바로 위).  
> `@mcp.tool` 데코레이터는 2단계에서 만든 `mcp` 인스턴스를 사용하므로 반드시 2단계를 먼저 작성해야 합니다.

각 도구에는 **두 층의 인가**가 적용됩니다:
- **1층 (도메인 접근권)**: 각 도구의 `auth=require_scopes("<도메인>:read")`가 토큰의 `scopes`를 검사합니다.
- **2층 (데이터 보안 등급)**: 각 도구의 `tags={"class:<등급>"}`을 서버 전역 미들웨어(`require_clearance`)가 읽어 토큰의 `clearance` 등급과 비교합니다.

| 도구 | 부여할 `tags` | 요구할 `scope` | 접근 가능한 역할 (`partner` / `staff` / `manager` / `executive`) |
| :--- | :--- | :--- | :--- |
| `search_aws_guides` | `data:docs`, `class:public` | `docs:read` | 전원 (`partner`, `staff`, `manager`, `executive`) |
| `search_company_policy` | `data:docs`, `class:internal` | `docs:read` | 사내 직원 이상 (`staff`, `manager`, `executive`) |
| `search_enterprise_erp` | `data:erp`, `class:confidential` | `erp:read` | 팀장 이상 (`manager`, `executive`) |
| `graph_*` 탐색 도구 5종 | `data:graph`, `class:confidential` | `graph:read` | 임원 (`executive`) 및 에이전트 서비스 계정 |

지식 그래프 도구 5종(`graph_find_entities`, `graph_neighbors`, `graph_find_path`, `graph_search_communities`, `graph_read`)은 `rag/graph/graph_explorer.py`에 LangChain 도구로 이미 정의되어 있으므로, 중복 작성 없이 **이름·설명·함수를 그대로 꺼내 `mcp.tool()`에 등록**합니다:

```python
# app/mcp/enterprise_rag_server.py (TODO 3 교체 코드)

# 4. FastMCP 도구 등록 (입력 스키마는 인자 타입 힌트 Annotated·Field로 정의하며 FastMCP가 Pydantic으로 검증)
#    - auth:  1층 scope (이 도메인에 접근할 수 있는가)
#    - tags:  data:* 는 데이터 도메인, class:* 는 데이터 등급 (2층 등급 규칙이 읽음)
#    권한이 없으면 도구 목록에서 숨겨지고 호출도 거부됩니다.
# 4-1. 사내 규정: 사내한(internal) 등급
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


# 4-2. AWS 백서: 공개(public) 등급
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


# 4-3. 사내 ERP: 대외비(confidential) 등급 (프로젝트 상세 예산 · 인사 데이터)
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


# 4-4. 지식 그래프 탐색 도구 5종: 대외비(confidential) 등급 (결재선 · 프로젝트 예산 · 리스크)
#      LangChain 도구의 이름·설명·함수를 그대로 등록해 tool_rag_agent와 정의를 공유합니다.
for graph_tool in graph_explorer_tools:
    mcp.tool(
        name=graph_tool.name,
        description=graph_tool.description,
        auth=require_scopes("graph:read"),
        tags={"data:graph", "class:confidential"},
    )(graph_tool.func)
```

> 💡 `@mcp.tool(...)`은 데코레이터이므로 `mcp.tool(...)(함수)`처럼 함수 호출 형태로도 사용할 수 있습니다. 인자 설명(`Annotated[..., Field(description=...)]`)은 `graph_tool.func`의 타입 힌트에 이미 들어 있어 FastMCP가 그대로 입력 스키마로 변환합니다.

---

### 4단계: FastMCP 서버 기동 확인 (미션 3-4)

새 터미널을 열어 작성한 FastMCP 서버가 오류 없이 기동되는지 확인합니다:

```bash
python app/mcp/enterprise_rag_server.py --port 8010
```

**성공 콘솔 출력:**
```text
🚀 Enterprise RAG FastMCP 서버 시작 (포트: 8010, Bearer 인증 + 도구별 인가 활성화)...
```

---

> ### ✅ Mission 03 완료 → 노트북 `5_MCP_and_Skills.ipynb`의 Part 3 실습 셀로 돌아가세요!
> 1. 위 터미널에 띄운 MCP 서버(포트 8010)를 켜 둔 채로(또는 노트북의 서버 자동 기동 셀을 사용하여) 노트북 **Part 3의 코드 셀**부터 이어서 실행합니다.
> 2. Part 3의 역할별 도구 가시성 표에서 **`partner(1개) / staff(2개) / manager(3개) / executive(8개)`** 가 정확히 출력되면 서버의 인증·인가 구현이 완벽히 성공한 것입니다!
> 3. 이어서 내가 만든 서버를 대상으로 **Part 4(정적 바인딩)**, **Part 5(Search & Proxy)**, **Part 6.1(스킬 카탈로그 확인 셀)** 까지 실행한 뒤, 노트북의 안내 배너가 나오면 **`missions/04_missions.md`(Mission 04의 1\~2단계)** 로 이동하세요.

---

## 🔧 트러블슈팅 가이드

| 증상 / 오류 메시지 | 원인 | 해결 방법 |
| :--- | :--- | :--- |
| `❌ TODO 1, 2를 먼저 완성하세요.` | `mcp = None` 상태가 그대로 남아 있음 | 2단계의 `verifier = StaticTokenVerifier(...)` 및 `mcp = FastMCP(...)` 코드로 `TODO 1, 2`를 교체했는지 확인 |
| `AttributeError: 'NoneType' object has no attribute 'tool'` | `mcp = FastMCP(...)`보다 `@mcp.tool`이 먼저 실행되었거나 `mcp = None`이 아래쪽에 남아 있음 | 2단계에서 `mcp = None  # TODO` 줄을 삭제하고 `mcp = FastMCP(...)`로 교체했는지 확인 |
| `Address already in use (:8010)` | 이전 FastMCP 서버 프로세스가 이미 포트 8010을 점유 중 | `lsof -ti:8010 \| xargs -r kill -9` 또는 `pkill -f enterprise_rag_server` 실행 후 재기동 |

---

## 🏆 미션 완료 체크리스트

- [ ] `.env`에 `ENTERPRISE_RAG_MCP_TOKEN`이 정상 설정되어 있음을 확인했다.
- [ ] `app/mcp/enterprise_rag_server.py`에 `StaticTokenVerifier`, `ROLE_PROFILES`, `require_clearance`, `AuthMiddleware` 기반의 인증·인가 서버 인스턴스를 완성했다 (`TODO 1, 2`).
- [ ] 검색 도구 3종(`search_company_policy`, `search_aws_guides`, `search_enterprise_erp`)과 그래프 탐색 도구 5종(`graph_*`)을 `@mcp.tool`로 등록했다 (`TODO 3`).
- [ ] 포트 `8010`에 FastMCP 서버를 기동하고, 노트북 Part 3의 역할별 도구 가시성 표(`partner` 1개, `staff` 2개, `manager` 3개, `executive` 8개)가 정상 출력됨을 확인했다.
