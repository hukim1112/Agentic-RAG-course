# 🏢 기업 데이터 연동을 위한 에이전틱 RAG 아키텍처 구축 실무

> 사내 규정(Markdown), 클라우드 아키텍처 백서(PDF), 전사 조직·프로젝트(지식 그래프), 사내 ERP(SQLite)를 연동하는 **Agentic RAG 시스템**을 단계별로 만들어 보는 핸즈온 과정

에이전트 루프는 `create_agent` 한 줄로 만들어집니다. 이 과정은 **ReAct 에이전트의 3대 기본 구성(도구 · 시스템 프롬프트 · 메모리)** 에서 출발하여, **에이전트가 쓰는 다중 검색 도구와 데이터 계층**을 설계하고 정량 평가하는 데 집중합니다.

---

## 🌿 브랜치 안내

| 구분 | `main` (교육생용) | `instructor` (강사용) |
| :--- | :--- | :--- |
| **용도** | 노트북 학습 후 미션을 직접 수행 | 모든 미션이 완성된 정답본 |
| **Mission 01** `app/tools/file_rag_tools.py`, `app/agents/file_rag_agent.py` | `TODO` 도구 스켈레톤 제공 · `file_rag_agent.py` 미생성(직접 추가) | 완성 |
| **Mission 02** `app/agents/tool_rag_agent/agent.py` | `create_agent_executor()`가 `TODO` | 완성 |
| **Mission 03** `app/mcp/enterprise_rag_server.py` | 인증기 · 2층 인가 · 서버 · 도구(검색 3종 + 그래프 탐색 5종)가 `TODO` | 완성 |
| **Mission 04** `app/agents/skill_rag_agent/skills/mcp/references/mcp_servers.json` | `wikipedia`만 등록 | `wikipedia` + `enterprise_rag` 등록 |
| **그 외** (노트북, 미션 문서, DB, 공용 모듈) | 동일 | 동일 |

> 💡 미션 중 막히면 `instructor` 브랜치의 같은 파일과 비교해 보세요: `git diff main origin/instructor -- <파일 경로>`

---

## 🚀 시작하기 (환경 세팅)

### 1. GitHub Codespaces (권장 · 사전 빌드 Docker 이미지)

Codespaces는 사전 빌드된 Docker 이미지(`hukimartia/agentic-rag-lab:latest`)로 구동되므로 **별도의 패키지 설치가 필요하지 않습니다.**
(Python 3.12, LangChain/LangGraph, Chroma, GraphRAG, FastMCP, Chainlit, Node.js 22, 한글 폰트/로케일 포함)

1. 리포지토리 상단 **[Code] ➔ [Codespaces] ➔ [Create codespace]** 로 실습 환경을 생성합니다.
2. 컨테이너가 뜨면 `.env.example`이 `.env`로 자동 복사됩니다. (`CHAINLIT_AUTH_SECRET`, `ENTERPRISE_RAG_MCP_TOKEN`은 미리 채워져 있습니다.)
3. `.env`를 열어 API 키를 입력합니다.
   ```env
   OPENAI_API_KEY=...        # 임베딩 (text-embedding-3-large)
   GOOGLE_API_KEY=...        # 에이전트 LLM (gemini-3.8-flash), GraphRAG
   ```

### 2. 로컬 환경 (WSL2 / Linux 수동 설치)

Docker를 쓰지 않는 경우 설치 스크립트를 실행합니다. 한글 폰트/로케일, Python 패키지 설치와 `.env` 생성이 순서대로 진행됩니다.

```bash
bash install/install_all.sh
```

> 💡 위키백과 MCP 서버(`npx -y wikipedia-mcp`)를 쓰려면 로컬에 **Node.js 18+** 가 필요합니다.

### 3. 설치 확인

```bash
python app/mcp/test_database.py     # 4대 DB 검색이 모두 ✅로 끝나면 준비 완료
```

### 🔍 LangSmith 트레이싱 (선택)

```env
LANGCHAIN_API_KEY=...
LANGCHAIN_TRACING_V2=true
LANGCHAIN_PROJECT=agentic-rag
```

---

## 📚 커리큘럼: 노트북 → 미션

학습 흐름은 **노트북(개념 학습)** → **미션(서비스 코드 실습)** 입니다.

| 순서 | 노트북 | 미션 | 만드는 것 |
| :---: | :--- | :--- | :--- |
| 1 | `1_Create_Agent.ipynb` | [`01_missions.md`](missions/01_missions.md) | ReAct 에이전트 3대 구성(File RAG 도구 3종 & 스키마 전달 원리 · 시스템 프롬프트 간접 통제 · 체크포인터), 4계층 서빙 구조 해부, `file_rag_agent` 신설 및 Chat UI 검증 |
| 2 | `2_Agentic_RAG.ipynb` | [`02_missions.md`](missions/02_missions.md) | Naive RAG vs Agentic RAG 비교, 데이터 특성별 4대 저장소 선택 기준, `tool_rag_agent` 조립 및 UI 검증 |
| 3 | `3_Vector_and_Graph_RAG.ipynb` | - *(노트북 Part 9 내장)* | 문서 형식과 무관한 인덱싱 파이프라인(`chunk_overlap=0`, `window_size=2`), 지식 그래프 & GraphRAG 탐색 도구 5종, 신규 문서 무수정 확장(`--extra-docs`) |
| 4 | `4_Text2SQL.ipynb` | - | 정형 ERP Text2SQL 파이프라인: 시멘틱 레이어(`semantic_layer.yaml`), 스키마 링킹(카드 검색 + FK 확장), 값 연결(Value Linking), 읽기 전용 2중 가드레일 · Self-Healing 루프 및 비정형 규정 결합 |
| 5 | `5_MCP_and_Skills.ipynb` | [`03_missions.md`](missions/03_missions.md)<br>[`04_missions.md`](missions/04_missions.md) | **Mission 03**: Bearer 인증 · 2층 인가(Scope + Clearance) FastMCP 서버 구축 및 기동 (`enterprise_rag_server.py`)<br>**Mission 04**: CLI 보안 검증, `mcp_servers.json` 등록 및 `skill_rag_agent` vs `tool_rag_agent` 비교 |
| 6 | `6_Evaluation.ipynb` | - | 3계층(Retrieval · Groundedness · Answer) 평가 하네스로 진단 → 개선 → 회귀 확인 및 실시간 미들웨어 연동 |

`notebooks/0_Template.ipynb`는 노트북 공통 환경 설정(루트 경로, `.env`, `nest_asyncio`) 템플릿입니다.
미션에서 직접 작성하는 파일은 위 [브랜치 안내](#-브랜치-안내) 표를 참고하세요.

---

## 🖥️ 서비스 실행

```bash
# 터미널 1: FastAPI 에이전트 서버 (8000)
python app/server.py

# 터미널 2: Chainlit 웹 UI (8080) → 로그인 user / 1234
chainlit run app/chainlit_ui.py --port 8080

# 터미널 3: Enterprise RAG MCP 서버 (8010, skill_rag_agent용 · Mission 03 완료 후)
python app/mcp/enterprise_rag_server.py
```

| 포트 | 서비스 |
| :---: | :--- |
| 8080 | Chainlit Chat UI |
| 8000 | FastAPI Agent Server |
| 8010 | Enterprise RAG FastMCP Server |
| 8888 | Jupyter Notebook |

### 평가 실행

```bash
python -m app.eval.rag_eval --agent tool_rag_agent
python -m app.eval.rag_eval --agent tool_rag_agent --compare artifacts/eval_runs/<이전 리포트>.json
```

---

## 🤖 에이전트

| 에이전트 | 도구 | 데이터 접근 방식 |
| :--- | :--- | :--- |
| `file_rag_agent` *(Mission 01)* | File RAG 도구 3종 (`list_docs`, `search_docs`, `read_doc`) | 별도 DB 인덱싱 없이 사내 문서를 탐색·검색·줄 구간 열람하는 베이스 에이전트 |
| `tool_rag_agent` *(Mission 02)* | 검색 도구 3종 + 그래프 탐색 도구 5종을 `@tool`로 직접 바인딩 | 에이전트 프로세스가 4대 DB를 직접 조회 |
| `skill_rag_agent` *(Mission 04)* | 범용 도구 3종 (`glob_search`, `file_read`, `bash_command`) | `SKILL.md` → `mcp_servers.json` → MCP CLI로 점진적 탐색 |

`tool_rag_agent`와 `skill_rag_agent`는 같은 ReAct 루프와 같은 검색 로직을 쓰고, **도구를 연결하는 방식만** 다릅니다.

---

## 🗄️ 데이터베이스 (`app/database/`)

| 데이터 | 원천 | 인덱스 / DB | 검색 도구 |
| :--- | :--- | :--- | :--- |
| 사내 규정 | `data/policies/*.md` | Chroma `enterprise_policy_store` (239청크) | `search_company_policy` |
| AWS 아키텍처 백서 | `data/tech_pdfs/aws_waf_series/*.pdf` | Chroma `aws_waf_guides_store` (4,641청크, `pillar` 메타데이터) | `search_aws_guides` |
| 전사 조직·프로젝트·인프라 | `data/graphrag/` & `data/graph/` | Microsoft GraphRAG `graphrag/` & NetworkX `enterprise_graph.json` | `graph_find_entities` · `graph_neighbors` · `graph_find_path` · `graph_search_communities` · `graph_read` |
| 사내 ERP 정형 데이터 | `data/enterprise_erp_sql/` | SQLite `enterprise_erp.db` + `semantic_layer.yaml` | `search_enterprise_erp` |

**사전 구축된 DB가 함께 배포되므로 다시 빌드할 필요가 없습니다.** 빌드 옵션은 `python app/mcp/build_database.py --help`를 참고하세요.

```bash
# 신규 문서를 사내 규정에 추가 인덱싱 (239 → 272청크)
python app/mcp/build_database.py --targets policy --extra-docs data/new_documents

# 사내 규정만 원래 상태로 되돌리기 (239청크)
python app/mcp/build_database.py --targets policy

# 사전 구축본 전체로 되돌리기
git checkout -- app/database
```

---

## 🔌 MCP 서버 레지스트리 (`app/agents/skill_rag_agent/skills/mcp/references/mcp_servers.json`)

| 서버 | 전송 방식 | 접속 정보 | 비고 |
| :--- | :--- | :--- | :--- |
| `wikipedia` | stdio | `npx -y wikipedia-mcp` | 기본 제공 · 영문 query만 허용 |
| `enterprise_rag` | streamable-http | `http://localhost:8010/mcp` | Mission 04에서 등록 · Bearer 인증 |

```bash
python app/agents/skill_rag_agent/skills/mcp/scripts/list_tools.py --url "npx -y wikipedia-mcp"
python app/agents/skill_rag_agent/skills/mcp/scripts/list_tools.py --url http://localhost:8010/mcp --token-env ENTERPRISE_RAG_MCP_TOKEN
```

### 🔐 인증

`app/mcp/enterprise_rag_server.py`는 `.env`의 `ENTERPRISE_RAG_MCP_TOKEN`과 일치하는 Bearer 토큰만 허용합니다.
스킬 CLI는 토큰 **값** 대신 **환경 변수 이름**을 받으므로(`--token-env ENTERPRISE_RAG_MCP_TOKEN`), 토큰이 에이전트의 프롬프트나 대화 기록에 남지 않습니다.

---

## 📂 프로젝트 구조

```
├── app/
│   ├── agents/
│   │   ├── file_rag_agent.py    # File RAG 베이스 에이전트 (Mission 01에서 추가)
│   │   ├── tool_rag_agent/      # agent.py, prompt.py, tools.py
│   │   └── skill_rag_agent/     # agent.py, prompt.py, tools.py, skills/ (mcp, pdf_processing)
│   ├── mcp/
│   │   ├── enterprise_rag_server.py   # Bearer 인증 FastMCP 서버
│   │   ├── build_database.py          # 인덱싱 파이프라인으로 DB 빌드
│   │   └── test_database.py           # 4대 DB 검색 검증
│   ├── eval/rag_eval.py         # 오프라인 평가 하네스 러너
│   ├── middleware/              # 로깅, 스킬 카탈로그, RAG 평가 하네스 미들웨어
│   ├── tools/                   # 범용 도구 및 file_rag_tools.py (Mission 01)
│   ├── utils/                   # 모델 팩토리, 메시지/DB 유틸
│   ├── database/                # 사전 구축된 4대 DB
│   ├── server.py                # FastAPI 에이전트 서버
│   └── chainlit_ui.py           # Chainlit 웹 UI
├── rag/                         # 공용 RAG 모듈: vector (preprocessing · indexing · retrieval) · sql · graph
├── data/                        # 원천 문서, 골든 평가셋, 미션용 새 문서
├── notebooks/                   # 실습 노트북 (1_Create_Agent ~ 6_Evaluation)
├── missions/                    # 미션 가이드 (01_missions ~ 04_missions)
├── install/                     # 설치 스크립트, requirements.txt
├── Dockerfile                   # Codespaces 사전 빌드 이미지 정의
└── .devcontainer/               # Codespaces 설정 (이미지, 포트 포워딩)
```

---

## 🔧 트러블슈팅

| 증상 | 해결 |
| :--- | :--- |
| Chainlit 에이전트 목록이 기본 폴백만 보임 | 터미널 1의 FastAPI 서버(8000)가 실행 중인지 확인 |
| Chainlit 에이전트 목록에 `file_rag_agent`가 안 보임 | Mission 01의 `app/agents/file_rag_agent.py` 생성 후 터미널 1 서버 재시작 |
| `tool_rag_agent` 선택 시 500 에러 (`NotImplementedError`) | Mission 02의 `agent.py` TODO를 완성한 뒤 서버 재시작 |
| MCP 서버 접속 시 `401 Unauthorized` | `--token-env ENTERPRISE_RAG_MCP_TOKEN` 전달 여부와 `.env` 토큰 값 확인 |
| `Address already in use` | `lsof -ti:<포트> \| xargs -r kill -9` |
| DB 빌드 후 검색 결과가 이상함 | `git checkout -- app/database`로 사전 구축본 복구 |
