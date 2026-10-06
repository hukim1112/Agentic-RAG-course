# 🏢 기업 데이터 연동을 위한 에이전틱 RAG 아키텍처 구축 실무

> 사내 규정(Markdown), 산업 보고서(PDF), 조직 정보(그래프)를 연동하는 **Agentic RAG 시스템**을 하루 동안 단계별로 만들어 보는 핸즈온 과정

에이전트 루프는 `create_agent` 한 줄로 만들어집니다. 이 과정은 그 바깥, 즉 **에이전트가 쓰는 도구와 데이터 계층**을 설계하고 평가하는 데 집중합니다.

---

## 📢 v2.0 업데이트 안내 (2026.10)

| 구분 | v1.0 (Legacy) | v2.0 (Current) |
| :--- | :--- | :--- |
| **웹 UI** | Streamlit (`app/ui.py`, 8501) | **Chainlit (`app/chainlit_ui.py`, 8080)** |
| **RAG 에이전트** | 단일 `rag_agent` | **`tool_rag_agent`(직접 바인딩) vs `skill_rag_agent`(Skills + MCP) 비교 구조** |
| **MCP 서버** | 인증 없는 FastMCP | **Bearer 토큰 + `rag:read` 스코프 인증** |
| **RAG 모듈** | `rag/*.py` 평면 구조 | **`rag/preprocessing · indexing · retrieval · graph` 패키지** |
| **DB 빌드** | `generate_database.py` | **`build_database.py` (`--targets`, `--extra-docs`로 무수정 확장)** |
| **노트북 / 미션** | `01~04_*.ipynb`, 단일 `Mission.md` | **`1~4_*.ipynb`, `missions/01~03_missions.md`** |
| **실행 환경** | Codespaces에서 매번 패키지 설치 | **사전 빌드 Docker 이미지 (`hukimartia/agentic-rag-lab`)** |

### 🌿 브랜치 안내

| 브랜치 | 용도 |
| :--- | :--- |
| `main` | **교육생용** — 미션 대상 코드가 `TODO`로 비어 있습니다 |
| `instructor` | **강사용** — 모든 미션이 완성된 정답본 |
| `main-v1` / `instructor-v1` | v1.0 백업 (`git checkout main-v1`) |

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

| 교시 | 노트북 | 미션 | 만드는 것 |
| :---: | :--- | :--- | :--- |
| 1 | `1_Agentic_RAG.ipynb` | [`01_missions.md`](missions/01_missions.md) | Naive RAG vs ReAct 검색 에이전트, `tool_rag_agent` 조립 및 UI 검증 |
| 2 | `2_Indexing.ipynb` | [`02_missions.md`](missions/02_missions.md) | 문서 형식과 무관한 인덱싱 파이프라인, 지식 그래프, GraphRAG, 신규 문서 무수정 확장 |
| 3 | `3_MCP_and_Skills.ipynb` | [`03_missions.md`](missions/03_missions.md) | Bearer 인증 MCP 서버, Skills 기반 `skill_rag_agent` |
| 4 | `4_Evaluation.ipynb` | - | 평가 하네스로 진단 → 개선 → 회귀 확인, HITL 승인 게이트 |

`notebooks/0_Template.ipynb`는 노트북 공통 환경 설정(루트 경로, `.env`, `nest_asyncio`) 템플릿입니다.

### ✏️ 미션에서 직접 작성하는 파일 (`main` 브랜치)

| 미션 | 파일 | 작성 내용 |
| :---: | :--- | :--- |
| 01 | `app/agents/tool_rag_agent/agent.py` | `create_agent_executor()` — LLM, `AsyncSqliteSaver` 체크포인터, 에이전트 조립 |
| 02 | (코드 작성 없음) | `build_database.py --extra-docs`로 새 문서 인덱싱 및 롤백 |
| 03 | `app/mcp/enterprise_rag_server.py` | 토큰 인증기, FastMCP 서버, Pydantic 스키마, `@mcp.tool` 4종 |
| 03 | `skills/mcp/references/mcp_servers.json` | `enterprise_rag` 서버 등록 |

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
| `chatbot` | 범용 도구 + 사용자 기억 | 서버/UI 통신 확인용 |
| `tool_rag_agent` | 검색 도구 4종을 `@tool`로 직접 바인딩 | 에이전트 프로세스가 DB를 직접 조회 |
| `skill_rag_agent` | 범용 도구 3종 (`glob_search`, `file_read`, `bash_command`) | `SKILL.md` → `mcp_servers.json` → MCP CLI로 점진적 탐색 |

두 RAG 에이전트는 같은 ReAct 루프와 같은 검색 로직을 쓰고, **도구를 연결하는 방식만** 다릅니다.

---

## 🗄️ 데이터베이스 (`app/database/`)

| 데이터 | 원천 | 인덱스 | 검색 도구 |
| :--- | :--- | :--- | :--- |
| 사내 규정 | `data/policies/*.md` | Chroma `enterprise_policy_store` (24청크) | `search_company_policy` |
| 한국은행 보고서 | `data/bok_major_industry_reports/*.pdf` | Chroma `bok_industry_reports_store` (분기 메타데이터 포함) | `search_bok_reports` |
| 조직/프로젝트 관계 | `data/graph/org_relationships.txt` | NetworkX `knowledge_graph_nodelink.json` | `search_graph_relations` |
| 전사 거시 분석 | 같은 원천 | Microsoft GraphRAG `graphrag/` | `query_enterprise_graphrag` |

**사전 구축된 DB가 함께 배포되므로 다시 빌드할 필요가 없습니다.** 빌드 옵션은 `python app/mcp/build_database.py --help`를 참고하세요.

```bash
# 신규 문서를 사내 규정에 추가 인덱싱 (24 → 30청크)
python app/mcp/build_database.py --targets policy --extra-docs data/new_documents

# 사내 규정만 원래 상태로 되돌리기 (24청크)
python app/mcp/build_database.py --targets policy

# 사전 구축본 전체로 되돌리기
git checkout -- app/database
```

---

## 🔌 MCP 서버 레지스트리 (`skills/mcp/references/mcp_servers.json`)

| 서버 | 전송 방식 | 접속 정보 | 비고 |
| :--- | :--- | :--- | :--- |
| `wikipedia` | stdio | `npx -y wikipedia-mcp` | 기본 제공 · 영문 query만 허용 |
| `enterprise_rag` | streamable-http | `http://localhost:8010/mcp` | Mission 03에서 등록 · Bearer 인증 |

```bash
python skills/mcp/scripts/list_tools.py --url "npx -y wikipedia-mcp"
python skills/mcp/scripts/list_tools.py --url http://localhost:8010/mcp --token-env ENTERPRISE_RAG_MCP_TOKEN
```

### 🔐 인증

`app/mcp/enterprise_rag_server.py`는 `.env`의 `ENTERPRISE_RAG_MCP_TOKEN`과 일치하는 Bearer 토큰만 허용합니다.
스킬 CLI는 토큰 **값** 대신 **환경 변수 이름**을 받으므로(`--token-env ENTERPRISE_RAG_MCP_TOKEN`), 토큰이 에이전트의 프롬프트나 대화 기록에 남지 않습니다.

---

## 📂 프로젝트 구조

```
├── app/
│   ├── agents/
│   │   ├── chatbot.py
│   │   ├── tool_rag_agent/      # agent.py, prompt.py, tools.py
│   │   └── skill_rag_agent/     # agent.py, prompt.py, tools.py
│   ├── mcp/
│   │   ├── enterprise_rag_server.py   # Bearer 인증 FastMCP 서버
│   │   ├── build_database.py          # 인덱싱 파이프라인으로 DB 빌드
│   │   └── test_database.py           # 4대 DB 검색 검증
│   ├── eval/rag_eval.py         # 오프라인 평가 하네스 러너
│   ├── middleware/              # 로깅, 스킬 카탈로그, RAG 평가 하네스 미들웨어
│   ├── tools/                   # 범용 도구 (file_read, bash_command 등)
│   ├── utils/                   # 모델 팩토리, 메시지/DB 유틸
│   ├── database/                # 사전 구축된 4대 DB
│   ├── server.py                # FastAPI 에이전트 서버
│   └── chainlit_ui.py           # Chainlit 웹 UI
├── rag/                         # 공용 RAG 모듈: preprocessing · indexing · retrieval · graph
├── skills/mcp/                  # MCP CLI 스킬 (SKILL.md, references/mcp_servers.json, scripts/)
├── data/                        # 원천 문서, 골든 평가셋, 미션용 새 문서
├── notebooks/                   # 교시별 실습 노트북
├── missions/                    # 교시별 미션 가이드
├── install/                     # 설치 스크립트, requirements.txt
├── Dockerfile                   # Codespaces 사전 빌드 이미지 정의
└── .devcontainer/               # Codespaces 설정 (이미지, 포트 포워딩)
```

---

## 🔧 트러블슈팅

| 증상 | 해결 |
| :--- | :--- |
| Chainlit 에이전트 목록이 `chatbot`(폴백)만 보임 | 터미널 1의 FastAPI 서버(8000)가 실행 중인지 확인 |
| `tool_rag_agent` 선택 시 500 에러 (`NotImplementedError`) | Mission 01의 `agent.py` TODO를 완성한 뒤 서버 재시작 |
| MCP 서버 접속 시 `401 Unauthorized` | `--token-env ENTERPRISE_RAG_MCP_TOKEN` 전달 여부와 `.env` 토큰 값 확인 |
| `Address already in use` | `lsof -ti:<포트> \| xargs -r kill -9` |
| DB 빌드 후 검색 결과가 이상함 | `git checkout -- app/database`로 사전 구축본 복구 |
