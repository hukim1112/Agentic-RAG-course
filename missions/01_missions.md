# 🎯 Mission 01: Tool RAG Agent 서비스 조립 및 UI 검증

본 미션은 `notebooks/1_Agentic_RAG.ipynb`에서 학습한 ReAct 검색 에이전트를 **프로덕션 서비스 패키지(`app/agents/tool_rag_agent/`)로 직접 조립**하고,  
FastAPI 백엔드 서버와 Chainlit 채팅 UI 환경에서 가동하여 **에이전트의 도구 선택, 멀티스텝 호출 과정, SQLite 영구 기억 유지**를 직접 검증하는 실습 과제입니다.

---

## 📂 실습 대상 및 핵심 파일

* **에이전트 조립 파일 (TODO 작성 대상)**: `app/agents/tool_rag_agent/agent.py`  
  👉 **이 파일의 `create_agent_executor()`를 완성하세요!**
* **검색 도구 (제공)**: `app/agents/tool_rag_agent/tools.py`의 `tools_tool_rag` — 노트북 Part 4에서 다룬 4대 데이터 소스용 도구:
  - `search_company_policy`: 사내 5대 공식 규정집 검색 (Vector + BM25 Hybrid)
  - `search_aws_guides`: AWS Well-Architected 4대 아키텍처 백서 검색 (Vector + BM25 Hybrid)
  - `search_enterprise_erp`: 사내 ERP 정형 데이터베이스 조회 (Text2SQL)
  - 지식 그래프 탐색 도구 5종 (GraphRAG 인덱스): `graph_find_entities`(엔티티 연결), `graph_neighbors`(관계 펼치기), `graph_find_path`(경로 찾기), `graph_search_communities`(커뮤니티 리포트 검색), `graph_read`(원문 확인)
* **시스템 프롬프트 (제공)**: `app/agents/tool_rag_agent/prompt.py` — ReAct 판단 원칙 및 답변 가이드라인
* **실행 엔트리포인트 (제공)**:
  - 백엔드 서버: `app/server.py` (FastAPI, 포트 8000)
  - 웹 채팅 UI: `app/chainlit_ui.py` (Chainlit, 포트 8080)
* **사전 학습 노트북**: `notebooks/1_Agentic_RAG.ipynb`

---

## 📋 미션 목표

1. **[미션 1-1] 환경 확인 및 서버/UI 가동**:
   - 필수 API 키를 점검하고, FastAPI 백엔드와 Chainlit UI를 띄워 기본 `chatbot` 프로필과의 통신을 확인합니다.
2. **[미션 1-2] Tool RAG Agent 완성 (`agent.py`)**:
   - `AsyncSqliteSaver` 기반의 SQLite 영구 세션 메모리를 구축하고, LLM과 4대 검색 도구를 바인딩한 에이전트 팩토리 함수를 구현합니다.
3. **[미션 1-3] 웹 UI 단계별 시나리오 검증**:
   - Chainlit UI에서 `tool_rag_agent`를 선택하고, 단일 규정 검색, 멀티홉 그래프+규정 추론, 아키텍처 영역(Pillar)별 비교, ERP 정형 데이터 조회, 대화 맥락 기억(세션 영속성)을 차례로 검증합니다.
4. **[심화 1-4] 도구 설명(Docstring) 변경 실험**:
   - 도구 설명문이 에이전트의 자율적 판단(도구 및 인자 선택)에 미치는 영향을 직접 관찰합니다.

---

## 🛠️ 단계별 수행 가이드

### 1단계: 환경 변수 (.env) 확인

터미널(WSL 환경)에서 에이전트 실행에 필요한 필수 API 키와 UI 시크릿이 정상 등록되어 있는지 확인합니다:

```bash
# 필수 환경 변수 등록 여부 점검 (값은 마스킹되어 이름만 출력됨)
grep -E '^(OPENAI_API_KEY|GOOGLE_API_KEY|CHAINLIT_AUTH_SECRET)=' .env | cut -d= -f1
```

> 💡 **출력 확인**: 위 3개 키 이름이 모두 출력되어야 합니다. 누락된 항목이 있다면 `.env` 파일을 열어 설정하세요.

---

### 2단계: 서버와 Chainlit UI 실행 (미션 1-1)

터미널 2개를 열어 각각 백엔드 서버와 프론트엔드 UI를 구동합니다:

#### 🖥️ 터미널 1 (FastAPI 백엔드 가동 - 포트 8000):
```bash
python app/server.py
```
**성공 콘솔 출력 예시:**
```text
Loading .env from: .../.env
📈 LangSmith Tracing Enabled. Project: llmops-agent-server
INFO:     Started server process [12345]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

#### 🌐 터미널 2 (Chainlit 웹 채팅 UI 가동 - 포트 8080):
```bash
chainlit run app/chainlit_ui.py --port 8080
```
**성공 콘솔 출력 예시:**
```text
Your app is available at http://localhost:8080
```

#### 🧪 기본 통신 테스트:
1. 웹 브라우저에서 `http://localhost:8080` 접속
2. 로그인 화면에서 아이디: `user`, 비밀번호: `1234` 입력 후 로그인
3. 좌측 상단 프로필에서 기본 에이전트인 **`chatbot`**을 선택하고 `"안녕? 오늘 날씨 어때?"`라고 전송하여 실시간 SSE 스트리밍 통신이 원활한지 확인합니다.

> 💡 `app/server.py`는 `app/agents/` 폴더 하위를 자동으로 스캔하여 `create_agent_executor()`를 노출하는 에이전트를 동적으로 등록합니다.

---

### 3단계: `agent.py` 완성하기 (미션 1-2)

`app/agents/tool_rag_agent/agent.py` 파일을 열고, `create_agent_executor()` 함수를 완성합니다.

> 📝 **시작 상태**: import 문과 `AGENT_METADATA`는 이미 작성되어 있고, `create_agent_executor()` 안에는 `TODO 1~3` 주석과 `raise NotImplementedError(...)`만 있습니다.  
> 아래 코드의 함수 본문으로 **TODO 주석과 `raise NotImplementedError` 줄을 교체**하세요. (파일 전체를 아래 코드로 바꿔도 됩니다.)

노트북 `1_Agentic_RAG.ipynb`의 Part 5에서 실습한 에이전트 조립 구조를 따르되, 서버가 재시작되어도 사용자와의 대화 기록이 영구 보존되도록 **`InMemorySaver` 대신 `AsyncSqliteSaver`**를 체크포인터로 연결합니다:

```python
# app/agents/tool_rag_agent/agent.py

import os
import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langchain.agents import create_agent
from app.utils import init_chat_model
from app.utils.context import AgentContext

from .prompt import TOOL_RAG_SYSTEM_PROMPT
from .tools import tools_tool_rag

AGENT_METADATA = {
    "name": "tool_rag_agent",
    "description": "4대 DB 검색 도구를 직접 바인딩한 ReAct 기반 Agentic RAG 에이전트",
}


async def create_agent_executor(checkpointer=None):
    """Tool RAG Agent 팩토리 함수:
    1. LLM 초기화 (gemini-3.8-flash)
    2. SQLite 기반 비동기 체크포인터 설정 (app/database/checkpoints.db)
    3. 4대 검색 도구가 바인딩된 ReAct 에이전트 생성
    """
    # 1. LLM 설정 (창의성 억제 및 정확한 사실 검색을 위해 temperature=0.0)
    llm = init_chat_model(model="gemini-3.8-flash", temperature=0.0)

    # 2. AsyncSqliteSaver 기반 영구 체크포인터 (세션 히스토리 영속화)
    conn = None
    if checkpointer is None:
        db_dir = "app/database"
        os.makedirs(db_dir, exist_ok=True)
        checkpoints_path = os.path.join(db_dir, "checkpoints.db")

        conn = await aiosqlite.connect(checkpoints_path, check_same_thread=False)
        await conn.execute("PRAGMA journal_mode=WAL;")
        await conn.execute("PRAGMA busy_timeout=5000;")
        checkpointer = AsyncSqliteSaver(conn)
        await checkpointer.setup()

    # 3. 4대 검색 도구와 ReAct 시스템 프롬프트를 바인딩한 에이전트 생성
    tool_rag_agent = create_agent(
        model=llm,
        tools=tools_tool_rag,
        system_prompt=TOOL_RAG_SYSTEM_PROMPT,
        checkpointer=checkpointer,
        context_schema=AgentContext,
    )
    tool_rag_agent.checkpointer_conn = conn
    return tool_rag_agent
```

> ⚠️ **주의**: `create_agent_executor()`를 수정한 후에는 **터미널 1의 FastAPI 서버(`server.py`)를 재시작(`Ctrl + C` 후 재실행)**해야 새 에이전트 코드가 서버 런타임에 반영됩니다.

---

### 4단계: 웹 UI에서 단계별 시나리오 검증 (미션 1-3)

터미널 1을 재시작한 후, Chainlit 웹 화면(`http://localhost:8080`)을 새로고침하고 좌측 상단 프로필 선택창에서 **`tool_rag_agent`**를 선택합니다.

아래 5가지 시나리오 질문을 차례로 전송하고, Chainlit 메시지 창 상단에 표시되는 **도구 호출 접기/펼치기 박스(Tool Calls)**를 클릭하여 에이전트의 ReAct 추론 과정을 관찰하세요:

#### 🧪 [시나리오 1] 단일 규정 검색 (`search_company_policy`)
- **질문**: `"팀원이 당일 출장을 가면 일비와 식비는 얼마를 받나요?"`
- **도구 호출 관찰**:
  - `search_company_policy` 1회 호출 (예: `query='당일 출장 일비 식비 팀원 지급 기준'`)
- **기대 답변 핵심** (국내 여비 규정 제15조):
  - 일비: 팀원 기준액 25,000원의 50% → **12,500원**
  - 식비: 당일 출장은 1식 → **12,000원**

#### 🧪 [시나리오 2] 멀티홉 프로젝트 참여자 조회 + 여비 규정 결합 (`search_enterprise_erp` / `graph_*` + `search_company_policy`)
- **질문**: `"인프라엔지니어링팀에서 P-01 프로젝트에 참여 중인 직원은 누구이고, 그 직원의 직급 기준 부산 1박 2일 출장 시 숙박비 한도와 일비 총액은 얼마인가요?"`
- **도구 호출 관찰 (Multi-step ReAct Loop)**:
  1. `search_enterprise_erp` 또는 그래프 탐색(`graph_find_entities` → `graph_neighbors`) ➔ `인프라엔지니어링팀`에서 `P-01` 프로젝트에 참여 중인 직원(`강엔지니어 선임`, `최유진 선임`)과 직급(`선임` = 팀원급) 파악
  2. `search_company_policy` (숙박비 및 일비 기준 검색) ➔ 국내외 출장 및 여비 지급 규정 제14조(숙박비)와 제15조(일비)를 각각 확인
- **기대 답변 핵심**:
  - 참여 직원: **강엔지니어 선임, 최유진 선임** *(ERP 조회 시 2명 전원 확인 / 지식 그래프 단독 조회 시 핵심 파견 인력인 **강엔지니어 선임** 확인 — 모두 인프라엔지니어링팀 `선임` 직급으로 팀원급 기준 동일)*
  - 부산 1박 숙박비 한도: 광역시 팀원(수석/책임/선임/전임) 기준 **1박당 80,000원** (제14조)
  - 1박 2일 일비 총액: 팀원(선임/전임) 1일 25,000원 × 2일 = **50,000원** (제15조)
  - 💡 사내 규정 문서에는 없는 **프로젝트 참여 직원 및 직급 정보**를 먼저 다른 소스(ERP/Graph)에서 찾고, 그 결과(`선임`)를 바탕으로 여비 규정의 직급별 표(제14조, 제15조)를 조회하는 **멀티홉 추론**이 핵심 관찰 포인트입니다.

#### 🧪 [시나리오 3] 아키텍처 영역별 비교 검색 (`search_aws_guides`) 및 정형 ERP 조회 (`search_enterprise_erp`)
- **질문 A (AWS 백서 영역 비교)**: `"AWS Well-Architected 백서에서 성능 효율성(Performance Efficiency) 영역과 비용 최적화(Cost Optimization) 영역의 컴퓨팅 리소스 선택 모범 사례를 각각 찾아 비교해줘."`
  - **도구 호출 관찰**:
    - `search_aws_guides(query='Performance Efficiency 컴퓨팅 리소스 선택 모범 사례')` 호출
    - `search_aws_guides(query='Cost Optimization 컴퓨팅 리소스 선택 비용 최적화 모범 사례')` 호출
    - 👉 아키텍처 영역을 나누어 2번 호출하여 각각의 모범 사례를 검색함을 확인!
- **질문 B (정형 ERP DB Text2SQL 조회)**: `"사내 ERP에서 AgenticAI팀이 수행하는 프로젝트의 총예산과 현재까지 승인된 지출 합계를 조회해줘."`
  - **도구 호출 관찰**:
    - `search_enterprise_erp(query='AgenticAI팀 수행 프로젝트 총예산 및 승인 지출 합계')` 호출
    - 👉 자연어 질문이 SQL(`SELECT ...`)로 변환되어 실행된 결과 표와 수치를 정확히 답변함을 확인!

#### 🧪 [시나리오 4] 세션 맥락 유지 질의 (Conversational Continuity)
- **질문 (시나리오 3의 질문 A에 이어서 같은 대화창에서 전송)**: `"그럼 신뢰성(Reliability) 영역에서는 어떤 설계 원칙을 강조해?"`
- **도구 호출 관찰**:
  - `search_aws_guides(query='Reliability Pillar Design principles 신뢰성 설계 원칙')` 호출
- **기대 답변 핵심**:
  - 사용자가 "AWS Well-Architected 백서"를 생략했지만, 체크포인터에 저장된 직전 대화를 기억하여 **AWS 신뢰성(`Reliability`) 백서**의 설계 원칙을 검색해 답변.

#### 🧪 [시나리오 5] 범용 일상 대화 (Zero-Tool Fallback)
- **질문**: `"안녕! 넌 뭘 할 수 있어?"`
- **도구 호출 관찰**:
  - 도구 호출 전혀 없음 (Zero Tool Calls)
- **기대 답변 핵심**:
  - 불필요한 DB 검색 없이 ReAct 에이전트 시스템 프롬프트와 바인딩된 4대 전문 검색 영역(사내 규정, AWS 아키텍처 가이드, 전사 지식 그래프, 사내 ERP)을 친절하게 소개.

---

### 5단계: 도구 설명(Docstring) 변경 실험 (심화 1-4)

프롬프트 엔지니어링만큼 강력한 **도구 설명(Tool Description)의 파급 효과**를 실험합니다.

`rag/graph/graph_explorer.py` 파일을 열고, `graph_find_entities` 도구의 docstring을 아래처럼 모호한 한 줄로 **임시 변경**해 보세요. 원래 설명에는 "그래프 탐색의 시작점이며, 엔티티 이름이 영문이므로 한국어 이름도 이 도구로 먼저 연결하라"는 지침과 반환 형태(E번호)가 들어 있습니다. (원래 docstring은 메모장에 복사해 두세요.)

```python
# graph_explorer.py - graph_find_entities 내부 (실험용 임시 변경)
"""지식 그래프에서 엔티티를 찾습니다."""
```

1. 터미널 1의 서버를 재시작합니다.
2. Chainlit UI에서 시나리오 2번 질문 또는 `"AgenticAI팀이 총괄하는 프로젝트의 예산과 승인권자는?"`을 전송합니다.
3. **결과 비교 관찰**:
   - 도구 설명에 **언제 이 도구를 먼저 써야 하고 무엇을 돌려받는지(E번호)**가 빠져 있을 때, 에이전트가 엔티티 연결부터 시작하나요, 아니면 한국어 이름을 `graph_neighbors`에 바로 넣었다가 후보 목록을 받고 헤매나요? 도구 호출 횟수를 비교해 보세요.
4. **실험 완료 후**: 삭제했던 docstring을 반드시 원래대로 복구하고 서버를 재시작하세요.

---

## 🔧 트러블슈팅 가이드

| 증상 / 오류 메시지 | 원인 | 해결 방법 |
| :--- | :--- | :--- |
| `Address already in use (:8000 또는 :8080)` | 이전 프로세스가 정상 종료되지 않고 포트를 점유 중 | WSL 터미널에서 `lsof -ti:8000 \| xargs -r kill -9` 또는 포트 번호를 변경하여 실행 (`--port 8001`) |
| `sqlite3.OperationalError: database is locked` | SQLite DB 파일에 동시 접근 락이 걸림 | `pkill -f "python app/server.py"`로 모든 서버 프로세스를 종료한 후, `rm -f app/database/checkpoints.db*` 실행 후 재시작 |
| UI 에이전트 목록에 `tool_rag_agent`가 안 뜸 | `agent.py` 코드 문법 오류 또는 팩토리 함수 미노출 | 터미널 1의 콘솔 로그에 출력된 Traceback을 확인하고, `create_agent_executor` 함수명이 오타 없이 작성되었는지 점검 |
| 도구 호출 결과가 빈 문자열로 나옴 | DB가 아직 빌드되지 않음 | `app/database/chroma_db` 존재 여부 확인 후, `python app/mcp/build_database.py` 실행 |

---

## 🏆 미션 완료 체크리스트

- [ ] `.env` 파일의 필수 API 키 및 시크릿 설정을 확인했다.
- [ ] FastAPI 백엔드(:8000)와 Chainlit UI(:8080)를 가동하여 `chatbot`과의 기본 통신을 검증했다.
- [ ] `app/agents/tool_rag_agent/agent.py`에 `AsyncSqliteSaver`와 검색 도구(`tools_tool_rag`)를 바인딩한 `create_agent_executor()`를 완성했다.
- [ ] UI 에이전트 목록에서 `tool_rag_agent`가 정상 로드되고 선택 가능함을 확인했다.
- [ ] 5가지 테스트 시나리오에서 각 도구의 호출 횟수, 인자, 세션 맥락 기억을 확인했다.
- [ ] (심화) 도구 설명 변경을 통해 LLM의 도구 및 인자 선택 판단 변화를 직접 관찰했다.

수고하셨습니다! 이제 여러분은 단순 질의응답 챗봇을 넘어, **상황에 맞춰 사내 4대 전문 데이터베이스(규정집, 기술 백서, 지식 그래프, ERP)를 스스로 판단하고 호출하는 지능형 ReAct RAG 에이전트 서비스**를 완성했습니다. 🚀
