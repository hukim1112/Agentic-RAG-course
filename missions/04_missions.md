# 🎯 Mission 04: Skills 에이전트 MCP 레지스트리 연동 및 Tool vs Skills 비교

본 미션은 **Mission 03**에서 직접 구축·기동한 사내 Enterprise RAG MCP 서버(`http://localhost:8010/mcp`)를 대상으로,  
`notebooks/5_MCP_and_Skills.ipynb`의 Part 6에서 학습한 **Anthropic Skills 기반 점진적 공개(Progressive Disclosure)** 패턴을 적용하여  
CLI 스크립트 보안 검증, **MCP 서버 레지스트리(`mcp_servers.json`) 등록**, 그리고 Chainlit 웹 UI에서의 **`skill_rag_agent` vs `tool_rag_agent` 실전 비교**를 수행하는 실습 과제입니다.

---

## 📂 실습 대상 및 핵심 파일

* **MCP 서버 레지스트리 (TODO 작성 대상)**: `app/agents/skill_rag_agent/skills/mcp/references/mcp_servers.json`  
  👉 **이미 등록된 공개 위키백과(Stdio) 서버 옆에 사내 Enterprise RAG 서버(HTTP)를 추가 등록하세요!**
* **MCP 스킬 패키지 (제공)**:
  - 스킬 매뉴얼: `app/agents/skill_rag_agent/skills/mcp/Skill.md` (점진적 공개 Progressive Disclosure 지침)
  - MCP 범용 클라이언트 CLI: `app/agents/skill_rag_agent/skills/mcp/scripts/list_tools.py`, `app/agents/skill_rag_agent/skills/mcp/scripts/execute_tool.py`
* **비교 대상 에이전트 2종**:
  - `app/agents/tool_rag_agent/` (Mission 02에서 완성한 도구 직접 바인딩 에이전트)
  - `app/agents/skill_rag_agent/` (범용 원시 도구 3종 + 스킬 카탈로그만으로 동작하는 자율 탐색 에이전트)
* **사전 조건**: Mission 03에서 구현한 `app/mcp/enterprise_rag_server.py`가 포트 `8010`에서 실행 중이어야 합니다.

---

## 📋 미션 목표

1. **[미션 4-1] Skills CLI 클라이언트를 통한 보안 및 원격 도구 실행 검증**:
   - `skill_rag_agent`가 내부적으로 사용하는 `list_tools.py`와 `execute_tool.py`를 직접 실행하여, 토큰이 없을 때 `401 Unauthorized`로 차단되는지 확인하고 `--token-env` 옵션으로 도구 조회 및 실행을 검증합니다.
2. **[미션 4-2] MCP 서버 레지스트리(`mcp_servers.json`) 등록**:
   - 실제 토큰 값을 노출하지 않는 `--token-env` 보안 규격에 맞추어 `mcp_servers.json`에 `"enterprise_rag"` 서버를 등록하고, 노트북 `Part 6.1(레지스트리 확인) ~ Part 7` 셀을 실행해 검증합니다.
3. **[미션 4-3] Chainlit 웹 UI에서 `skill_rag_agent` vs `tool_rag_agent` 실전 비교**:
   - 동일한 질문에 대해 두 에이전트의 도구 탐색 과정(Trajectory), 호출 횟수, 초기 프롬프트 토큰 비용, 확장성의 차이를 직접 비교 분석합니다.

---

## 🛠️ 단계별 수행 가이드

### 1단계: CLI 클라이언트를 통한 3단계 보안 및 실행 검증 (미션 4-1)

에이전트에게 실행을 맡기기에 앞서, `skill_rag_agent`가 `bash_command`로 호출하게 될 CLI 스크립트를 터미널에서 먼저 검증합니다.  
*(FastMCP 서버가 꺼져 있다면 다른 터미널에서 `python app/mcp/enterprise_rag_server.py --port 8010`을 먼저 실행하세요.)*

#### ① [보안 검증 1] 토큰 없이 요청 시 `401 Unauthorized` 차단 확인
```bash
python app/agents/skill_rag_agent/skills/mcp/scripts/list_tools.py --url http://localhost:8010/mcp
```
**기대 출력 (차단 성공):**
```json
[*] Connecting to remote MCP Server: http://localhost:8010/mcp ...
{
  "status": "ERROR",
  "message": "Failed to retrieve tools from 'http://localhost:8010/mcp': Client error '401 Unauthorized' for url 'http://localhost:8010/mcp'..."
}
```

#### ② [보안 검증 2] 환경 변수 이름(`--token-env`)과 함께 도구 목록 조회
```bash
python app/agents/skill_rag_agent/skills/mcp/scripts/list_tools.py --url http://localhost:8010/mcp --token-env ENTERPRISE_RAG_MCP_TOKEN
```
**기대 출력 (검색 도구 3종 + 그래프 탐색 도구 5종, 총 8개 정상 조회 — 긴 문자열·스키마 일부 축약):**
```json
[*] Connecting to remote MCP Server: http://localhost:8010/mcp ...
{
  "status": "SUCCESS",
  "mcp_target": "http://localhost:8010/mcp",
  "tools": [
    {
      "name": "search_company_policy",
      "description": "사내 5대 공식 규정 문서(국내여비교통비지급규정, 인사복무규정, 정보보안관리지침, 전사위임전결및예산집행규정, 클라우드및GPU인프라운영지침)에서...",
      "input_schema": { "type": "object", "properties": { "query": { "type": "string" } }, "required": ["query"] }
    },
    {
      "name": "search_aws_guides",
      "description": "AWS Well-Architected Framework 4대 아키텍처 백서(Security, Reliability, Performance Efficiency, Cost Optimization)에서...",
      "input_schema": { "type": "object", "properties": { "query": { "type": "string" } }, "required": ["query"] }
    },
    {
      "name": "search_enterprise_erp",
      "description": "사내 ERP 정형 데이터베이스(부서 마스터, 임직원 명부, 전략 프로젝트 및 투입 인력...",
      "input_schema": { "type": "object", "properties": { "query": { ... }, "context": { ... } }, "required": ["query"] }
    },
    {
      "name": "graph_find_entities",
      "description": "전사 지식 그래프(조직도, 보고선·결재선, 전략 프로젝트 P-01~P-06)에서 질문 속 인물·부서·프로젝트에 해당하는 엔티티를 찾습니다...",
      "input_schema": { ... }
    },
    {
      "name": "graph_neighbors",
      "description": "지식 그래프에서 한 엔티티와 연결된 관계(소속, 보고, 담당, 승인, 의존 등)를 펼칩니다...",
      "input_schema": { ... }
    },
    { "name": "graph_find_path", "description": "...", "input_schema": { ... } },
    { "name": "graph_search_communities", "description": "...", "input_schema": { ... } },
    { "name": "graph_read", "description": "...", "input_schema": { ... } }
  ]
}
```

#### ③ [도구 실행 검증 3] 지식 그래프 탐색 도구(`graph_neighbors`) 원격 실행
```bash
python app/agents/skill_rag_agent/skills/mcp/scripts/execute_tool.py --url http://localhost:8010/mcp --token-env ENTERPRISE_RAG_MCP_TOKEN \
  --tool graph_neighbors --args '{"entity": "KIM CHUL-SOO", "query": "담당 프로젝트와 보고선", "top_k": 3}'
```
**기대 출력:**
```json
[*] Connecting to remote MCP Server: http://localhost:8010/mcp ...
{
  "status": "SUCCESS",
  "mcp_target": "http://localhost:8010/mcp",
  "tool_name": "graph_neighbors",
  "output": "### KIM CHUL-SOO의 1홉 관계 3/13개 ('담당 프로젝트와 보고선'와 가까운 순)\nR159 KIM CHUL-SOO ─ PROJECT P-01 [가중치 9] Kim Chul-soo is the PM for Project P-01 (근거 T7)\n..."
}
```

> 💡 **보너스: 기본 제공되는 공개 Stdio 위키백과 MCP 서버 테스트**:
> ```bash
> python app/agents/skill_rag_agent/skills/mcp/scripts/list_tools.py --url "npx -y wikipedia-mcp"
> ```
> `--url` 값이 `http`로 시작하지 않으면 CLI가 자동으로 Stdio 서브프로세스로 실행하여 `search`, `readArticle` 등의 도구 목록을 조회합니다.

---

### 2단계: MCP 서버 레지스트리 등록 (미션 4-2)

`skill_rag_agent`는 어떤 MCP 서버가 존재하는지 알아내기 위해 `app/agents/skill_rag_agent/skills/mcp/references/mcp_servers.json` 파일을 가장 먼저 읽습니다.  
이 파일을 열면 현재 위키백과(`"wikipedia"`) 서버만 등록되어 있습니다.

`"wikipedia": {...}` 블록 닫는 중괄호 뒤에 **쉼표(`,`)를 붙이고 `"enterprise_rag"` 블록을 추가**하여 아래와 같이 만드세요. *(파일 전체를 아래 JSON으로 통째로 교체해도 됩니다.)*

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
    "description": "사내 규정 검색(search_company_policy), AWS 아키텍처 백서 검색(search_aws_guides), 전사 지식 그래프 탐색(graph_find_entities, graph_neighbors, graph_find_path, graph_search_communities, graph_read), 사내 ERP Text2SQL 조회(search_enterprise_erp) 도구"
  }
}
```

> 🔑 **보안 핵심 원칙 (`token_env`)**:  
> JSON 파일에 실제 토큰 문자열(비밀값)을 직접 하드코딩하지 않고, **환경 변수 이름(`ENTERPRISE_RAG_MCP_TOKEN`)**만 기술합니다.  
> 덕분에 에이전트가 이 JSON 파일을 `file_read`로 읽더라도 시스템 프롬프트, 대화 히스토리, LangSmith 트레이스 로그에 실제 토큰 값이 절대 노출되지 않습니다.

> 📌 **노트북 Part 6.1(레지스트리 확인) ~ Part 7 실행 확인**:  
> 레지스트리 파일을 저장한 뒤, `notebooks/5_MCP_and_Skills.ipynb`로 돌아가 **Part 6.1 레지스트리 확인 셀 ~ Part 7 마지막 셀**까지 실행해 보세요. 에이전트가 방금 등록한 `mcp_servers.json`을 읽고 도구를 스스로 찾아 답변하며, 토큰 노출 검사에서 `노출 없음 ✅`이 출력되는 것을 확인한 뒤 아래 **3단계(Chainlit 비교)** 로 이어갑니다.

---

### 3단계: Chainlit 웹 UI에서 `skill_rag_agent` vs `tool_rag_agent` 비교 (미션 4-3)

이제 웹 UI 환경에서 `skill_rag_agent`와 `tool_rag_agent`를 직접 비교합니다.

> ⚠️ **사전 조건 점검 (터미널 3개)**:
> 1. **터미널 1 (FastAPI 백엔드)**: `python app/server.py` (포트 8000)
> 2. **터미널 2 (Chainlit UI)**: `chainlit run app/chainlit_ui.py --port 8080` (포트 8080)
> 3. **터미널 3 (FastMCP 서버)**: `python app/mcp/enterprise_rag_server.py --port 8010` (포트 8010)  
>    *(주의: 노트북 마지막 셀에서 노트북이 띄운 MCP 서버를 종료했다면, 반드시 터미널 3에서 다시 띄워 두어야 `skill_rag_agent`가 접속할 수 있습니다!)*

Chainlit UI(`http://localhost:8080`) 상단 프로필을 **`skill_rag_agent`**로 변경하고 아래 질문들을 전송해 보세요.

#### 🧪 `skill_rag_agent`의 5단계 자율 탐색 궤적 (Trajectory) 관찰:
1. **레지스트리 확인**: 전용 검색 도구가 없음을 인지하고, `file_read("app/agents/skill_rag_agent/skills/mcp/references/mcp_servers.json")`로 사내 서버 URL(`http://localhost:8010/mcp`)과 인증 환경 변수명(`ENTERPRISE_RAG_MCP_TOKEN`) 파악
2. **스킬 명세 열람**: `file_read("app/agents/skill_rag_agent/skills/mcp/Skill.md")`로 CLI 스크립트 사용법 확인
3. **도구 목록 조회**: `bash_command`로 `list_tools.py --url http://localhost:8010/mcp --token-env ENTERPRISE_RAG_MCP_TOKEN`을 실행하여 도구 스키마 획득
4. **원격 도구 실행**: 필요한 인자를 담아 `execute_tool.py`를 실행하여 사내 DB 결과 수집 (복합 질문 시 여러 번 호출)
5. **최종 응답 생성**: 수집된 근거를 종합하여 조항 번호·수치와 함께 최종 답변 작성

> 💡 1·2번 순서는 모델 판단에 따라 바뀔 수 있습니다. 핵심은 **도구 스키마를 미리 받지 않고 파일(`mcp_servers.json`, `Skill.md`) → CLI(`list_tools.py`, `execute_tool.py`) 순으로 스스로 찾아간다**는 점입니다. 또한 **같은 대화 세션에서 후속 질문을 던지면** 이미 확인한 서버 URL과 도구 목록을 기억하므로 1\~3단계를 생략하고 곧바로 `execute_tool.py`(4단계)만 실행합니다!

#### 🧪 테스트 질문 및 기대 결과:

| 질문 | 주요 호출 도구 | 기대 답변 핵심 | 소요 시간(참고) |
| :--- | :--- | :--- | :--- |
| `"정보보안 지침상 데이터 반출 승인 절차는?"` | `search_company_policy` 1회 | DLP 결재 시스템으로 사전 신청 → 1차 소속 팀장, 2차 CISO 승인 (정보보안관리지침 제14조) | 약 20초 |
| `"AgenticAI팀이 총괄하는 프로젝트의 예산과 승인권자는?"` | `graph_find_entities` → `graph_neighbors` 또는 `search_enterprise_erp` | P-02 엔터프라이즈 Agentic RAG 플랫폼 구축, 총괄 PM 홍팀장 수석, 예산 4억 8,000만원, 승인권자 송본부장 상무 | 약 30초 |
| `"과장급 직원이 지방으로 당일 출장을 다녀오면 일비 감액 기준이 어떻게 되나요?"` | `search_company_policy` | 당일 출장 일비는 기준액의 50% 지급 (국내여비교통비지급규정 제15조). 사내 직급 체계(수석/책임/선임/전임) 기준 함께 안내 | 약 35초 |

---

### 📊 종합 비교: Tool RAG vs Skills RAG

같은 질문을 `tool_rag_agent`에도 던져 보고 두 아키텍처의 차이를 비교해 보세요:

| 비교 항목 | Tool RAG (`tool_rag_agent`) | Skills RAG (`skill_rag_agent`) |
| :--- | :--- | :--- |
| **도구 바인딩 방식** | 파이썬 코드 레벨에서 `@tool`로 직접 바인딩 | `Skill.md` + `mcp_servers.json` 기반 동적 탐색 |
| **초기 프롬프트 토큰** | 도구가 늘어날수록 토큰 급증 (100개면 수만 토큰 소모) | **스킬 카탈로그 몇 줄로 고정** (도구 스키마는 필요할 때만 조회) |
| **확장성 (Scalability)** | 새 도구 추가 시 에이전트 코드 수정 및 서버 재시작 필요 | **에이전트 코드 수정·재시작 없음** (`mcp_servers.json`에 서버만 추가) |
| **응답 속도** | 빠름 (곧바로 도구 호출) | 첫 질문 시 탐색 단계(파일 읽기 2회 + `list_tools` 1회)만큼 시간 소요 |
| **실무 적용 추천** | 고정된 핵심 도구 5\~10개를 쓰는 목적형 에이전트 | 사내 수십 개 마이크로서비스와 CLI를 넘나드는 **범용·코딩·분석 에이전트** |

---

## 🔧 트러블슈팅 가이드

| 증상 / 오류 메시지 | 원인 | 해결 방법 |
| :--- | :--- | :--- |
| `Failed to retrieve tools ... ConnectError` | 포트 `8010`에 FastMCP 서버가 떠 있지 않음 | 터미널 3에서 `python app/mcp/enterprise_rag_server.py --port 8010` 실행 |
| `StaticTokenVerifier: 401 Unauthorized` | `.env`의 토큰과 클라이언트 환경 변수 불일치 | `grep ENTERPRISE_RAG_MCP_TOKEN .env` 값을 확인하고 서버를 재시작 |
| `json.decoder.JSONDecodeError` (`--args`) | CLI 인자의 따옴표 이스케이프 오류 | `--args` 전체는 작은따옴표(`'...'`)로 감싸고 내부 JSON 키/문자열은 큰따옴표(`"..."`)로 전달: `'{"query": "..."}'` |
| `skill_rag_agent`가 사내 서버를 못 찾고 위키백과만 봄 | `mcp_servers.json`에 `"enterprise_rag"` 미등록 또는 JSON 문법 오류 | 2단계의 JSON 코드로 `app/agents/skill_rag_agent/skills/mcp/references/mcp_servers.json`을 저장했는지 확인 |

---

## 🏆 미션 완료 체크리스트

- [ ] 토큰이 없을 때 `401 Unauthorized` 차단, `--token-env` 사용 시 도구 목록 조회 및 원격 도구 실행이 성공함을 CLI로 확인했다.
- [ ] `app/agents/skill_rag_agent/skills/mcp/references/mcp_servers.json`에 `"enterprise_rag"` 서버를 보안 규격(`token_env`)에 맞추어 등록했다.
- [ ] 노트북 `5_MCP_and_Skills.ipynb`의 Part 6.1(레지스트리 확인)\~Part 7을 실행하여 Skills 에이전트 동작과 토큰 비노출(`노출 없음 ✅`)을 확인했다.
- [ ] Chainlit UI에서 `skill_rag_agent`의 5단계 점진적 탐색 궤적(파일 읽기 → `list_tools` → `execute_tool`)을 관찰하고, `tool_rag_agent`와의 트레이드오프를 이해했다.

축하합니다! 이제 여러분은 도구가 에이전트 코드에 강결합된 구조를 넘어, **인증·인가된 MCP 서버와 Skills 점진적 공개 아키텍처**까지 완벽하게 구축하고 검증했습니다! 🚀
