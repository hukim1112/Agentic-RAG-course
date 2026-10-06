# 🎯 Mission 01: Tool RAG Agent 서비스 조립 및 UI 검증

본 미션은 `notebooks/1_Agentic_RAG.ipynb`에서 학습한 ReAct 검색 에이전트를 **프로덕션 서비스 패키지(`app/agents/tool_rag_agent/`)로 직접 조립**하고,  
FastAPI 백엔드 서버와 Chainlit 채팅 UI 환경에서 가동하여 **에이전트의 도구 선택, 멀티스텝 호출 과정, SQLite 영구 기억 유지**를 직접 검증하는 실습 과제입니다.

---

## 📂 실습 대상 및 핵심 파일

* **에이전트 조립 파일 (TODO 작성 대상)**: `app/agents/tool_rag_agent/agent.py`  
  👉 **이 파일의 `create_agent_executor()`를 완성하세요!**
* **4대 검색 도구 (제공)**: `app/agents/tool_rag_agent/tools.py` — 노트북 Part 4에서 다룬 사내 규정, 한국은행 보고서, 조직 지식 그래프, GraphRAG 검색 도구
* **시스템 프롬프트 (제공)**: `app/agents/tool_rag_agent/prompt.py` — ReAct 판단 원칙 및 도구 사용 가이드라인
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
   - Chainlit UI에서 `tool_rag_agent`를 선택하고, 단일 검색, 멀티홉 그래프 추론, 분기별 비교, 대화 맥락 기억(세션 영속성)을 차례로 검증합니다.
4. **[심화 1-4] 도구 설명(Docstring) 변경 실험**:
   - 도구 설명문 한 줄이 에이전트의 자율적 판단과 도구 호출 횟수에 미치는 영향을 직접 관찰합니다.

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


async def create_agent_executor():
    """Tool RAG Agent 팩토리 함수:
    1. LLM 초기화 (gemini-3.8-flash)
    2. SQLite 기반 비동기 체크포인터 설정 (app/database/checkpoints.db)
    3. 4대 검색 도구가 바인딩된 ReAct 에이전트 생성
    """
    # 1. LLM 설정 (창의성 억제 및 정확한 사실 검색을 위해 temperature=0.0)
    llm = init_chat_model(model="gemini-3.8-flash", temperature=0.0)

    # 2. AsyncSqliteSaver 기반 영구 체크포인터 (세션 히스토리 영속화)
    db_dir = "app/database"
    os.makedirs(db_dir, exist_ok=True)
    checkpoints_path = os.path.join(db_dir, "checkpoints.db")

    conn = await aiosqlite.connect(checkpoints_path, check_same_thread=False)
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
    return tool_rag_agent
```

> ⚠️ **주의**: `create_agent_executor()`를 수정한 후에는 **터미널 1의 FastAPI 서버(`server.py`)를 재시작(`Ctrl + C` 후 재실행)**해야 새 에이전트 코드가 서버 런타임에 반영됩니다.

---

### 4단계: 웹 UI에서 단계별 시나리오 검증 (미션 1-3)

터미널 1을 재시작한 후, Chainlit 웹 화면(`http://localhost:8080`)을 새로고침하고 좌측 상단 프로필 선택창에서 **`tool_rag_agent`**를 선택합니다.

아래 5가지 시나리오 질문을 차례로 전송하고, Chainlit 메시지 창 상단에 표시되는 **도구 호출 접기/펼치기 박스(Tool Calls)**를 클릭하여 에이전트의 ReAct 추론 과정을 관찰하세요:

#### 🧪 [시나리오 1] 단일 규정 검색 (Dense Semantic Search)
- **질문**: `"팀원이 당일 출장을 가면 일비와 식비는 얼마를 받나요?"`
- **도구 호출 관찰**:
  - `search_company_policy(query='당일 출장 일비 식비')` 1회 호출
- **기대 답변 핵심**:
  - 국내 여비 규정 제15조에 근거하여, 당일 출장은 일비 50% 감액(10,000원), 식비는 100%(25,000원) 정액 지급됨을 정확한 조항과 함께 설명.

#### 🧪 [시나리오 2] 멀티홉 조직도 탐색 + 규정 결합 (Graph + Policy)
- **질문**: `"클라우드운영팀 김철수 수석의 본부장은 누구이고, 그 본부장의 결재가 필요한 프로젝트 예산 기준은?"`
- **도구 호출 관찰 (Multi-step ReAct Loop)**:
  1. `search_graph_relations(params={'seed_entity': '김철수 수석', 'max_hops': 2})` 호출 ➔ 직속 상위 보고선(클라우드사업본부) 파악
  2. `search_company_policy` 또는 `query_enterprise_graphrag` 호출 ➔ 본부장 전결 예산 기준 검색
- **기대 답변 핵심**:
  - 김철수 수석의 소속 본부 및 보고 체계와 본부장 결재 한도(예: 5천만 원 이상 등 규정 수치)를 유기적으로 종합하여 답변.

#### 🧪 [시나리오 3] 다중 문서 비교 검색 (Iterative Retrieval)
- **질문**: `"2024년 1분기와 3분기의 반도체 수출 동향을 비교해줘."`
- **도구 호출 관찰**:
  - `search_bok_reports(query='2024년 1분기 반도체 수출 동향', quarter=1)` 호출
  - `search_bok_reports(query='2024년 3분기 반도체 수출 동향', quarter=3)` 호출
  - 👉 두 번에 나누어 개별 분기 데이터를 정밀하게 수집함을 확인!
- **기대 답변 핵심**:
  - 1분기와 3분기 실적 수치(HBM 메모리 수요 등)를 대조표 또는 항목별로 명확히 비교.

#### 🧪 [시나리오 4] 세션 맥락 유지 질의 (Conversational Continuity)
- **질문 (시나리오 3에 이어서 전송)**: `"그럼 4분기 전망은 어때?"`
- **도구 호출 관찰**:
  - `search_bok_reports(query='2024년 4분기 반도체 수출 전망', quarter=4)` 1회 호출
- **기대 답변 핵심**:
  - 사용자가 "반도체"라는 단어를 생략했음에도 불구하고, SQLite 체크포인터가 직전 대화 맥락을 기억하여 자동으로 반도체 4분기 전망을 검색하여 답변.

#### 🧪 [시나리오 5] 범용 일상 대화 (Zero-Tool Fallback)
- **질문**: `"안녕! 넌 뭘 할 수 있어?"`
- **도구 호출 관찰**:
  - 도구 호출 전혀 없음 (Zero Tool Calls)
- **기대 답변 핵심**:
  - 불필요한 DB 검색 없이 ReAct 에이전트 시스템 프롬프트에 정의된 자신의 정체성과 수행 가능한 4대 전문 영역을 친절하게 소개.

---

### 5단계: 도구 설명(Docstring) 변경 실험 (심화 1-4)

프롬프트 엔지니어링만큼 강력한 **도구 설명(Tool Description)의 파급 효과**를 실험합니다.

`app/agents/tool_rag_agent/tools.py` 파일을 열고, `search_bok_reports` 도구의 docstring에서 아래 가이드라인 문장 2줄을 임시로 주석 처리(`//` 또는 삭제)해 보세요:

```python
# tools.py - search_bok_reports 내부
"""
한 번의 호출에는 '특정 1개 분기'와 '특정 1개 산업'만 검색하세요.
분기 비교나 산업 비교가 필요하면 분기별/산업별로 나누어 여러 번 호출하세요.
"""
```

1. 터미널 1의 서버를 재시작합니다.
2. Chainlit UI에서 다시 시나리오 3번 질문(`"2024년 1분기와 3분기의 반도체 수출 동향을 비교해줘."`)을 전송합니다.
3. **결과 비교 관찰**:
   - 에이전트가 분기를 나누어 2번 호출하나요, 아니면 `"2024년 1분기 3분기 반도체"`라는 하나의 모호한 쿼리로 1번만 대충 검색하고 넘어가나요?
   - 도구 검색 결과의 정확도와 최종 답변의 수치 일치도는 어떻게 달라졌나요?
4. **실험 완료 후**: 주석 처리했던 2줄을 반드시 원래대로 복구하고 서버를 재시작하세요.

---

## 🔧 트러블슈팅 가이드

| 증상 / 오류 메시지 | 원인 | 해결 방법 |
| :--- | :--- | :--- |
| `Address already in use (:8000 또는 :8080)` | 이전 프로세스가 정상 종료되지 않고 포트를 점유 중 | WSL 터미널에서 `lsof -ti:8000 \| xargs -r kill -9` 또는 포트 번호를 변경하여 실행 (`--port 8001`) |
| `sqlite3.OperationalError: database is locked` | SQLite DB 파일에 동시 접근 락이 걸림 | `pkill -f "python app/server.py"`로 모든 서버 프로세스를 종료한 후, `rm -f app/database/checkpoints.db*` 실행 후 재시작 |
| UI 에이전트 목록에 `tool_rag_agent`가 안 뜸 | `agent.py` 코드 문법 오류 또는 팩토리 함수 미노출 | 터미널 1의 콘솔 로그에 출력된 Traceback을 확인하고, `create_agent_executor` 함수명이 오타 없이 작성되었는지 점검 |
| 도구 호출 결과가 빈 문자열로 나옴 | DB가 아직 빌드되지 않음 | `app/database/chroma_db` 존재 여부 확인 후, Mission 02의 `python app/mcp/build_database.py` 실행 |

---

## 🏆 미션 완료 체크리스트

- [ ] `.env` 파일의 필수 API 키 및 시크릿 설정을 확인했다.
- [ ] FastAPI 백엔드(:8000)와 Chainlit UI(:8080)를 가동하여 `chatbot`과의 기본 통신을 검증했다.
- [ ] `app/agents/tool_rag_agent/agent.py`에 `AsyncSqliteSaver`와 4대 도구를 바인딩한 `create_agent_executor()`를 완성했다.
- [ ] UI 에이전트 목록에서 `tool_rag_agent`가 정상 로드되고 선택 가능함을 확인했다.
- [ ] 5가지 테스트 시나리오에서 각 도구의 호출 횟수, 인자, 세션 맥락 기억을 확인했다.
- [ ] (심화) 도구 설명 변경을 통해 LLM의 도구 호출 판단 변화를 직접 관찰했다.

수고하셨습니다! 이제 여러분은 단순 질의응답 챗봇을 넘어, **상황에 맞춰 사내 4대 전문 데이터베이스를 스스로 판단하고 호출하는 지능형 ReAct RAG 에이전트 서비스**를 완성했습니다. 🚀
