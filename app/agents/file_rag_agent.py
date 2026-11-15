"""
app/agents/file_rag_agent.py — 엔터프라이즈 File RAG 베이스 에이전트 (Mission 01 완성본)

별도의 벡터 DB 인덱싱 없이 파일 탐색 3대 도구(list_docs -> search_docs -> read_doc)와
시스템 프롬프트, SQLite 영구 체크포인터(AsyncSqliteSaver)만으로 사내 문서에 응답하는 기초 ReAct 에이전트입니다.
"""

import os
from datetime import date
import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langchain.agents import create_agent
from app.utils import init_chat_model
from app.utils.context import AgentContext
from app.tools.file_rag_tools import file_rag_tools

AGENT_METADATA = {
    "name": "file_rag_agent",
    "description": "인덱싱 없이 사내 문서를 탐색·검색·열람(list → search → read)하는 File RAG 베이스 에이전트",
}

FILE_RAG_SYSTEM_PROMPT = f"""당신은 (주)넥스트AI의 공식 '사내 문서 안내 데스크(File RAG)' 에이전트입니다.
임직원의 사내 규정·지침 문의에 대해 파일 탐색 도구(list_docs, search_docs, read_doc)만을 근거로 정확하고 명확하게 한국어로 답변하세요.

[핵심 작업 규칙 — File RAG 3단계 탐색]
1. 사용자가 첫 인사를 건네거나 어떤 도움을 줄 수 있는지 물으면, 추측하지 말고 반드시 먼저 `list_docs` 도구를 호출하여 현재 비치된 문서 목록을 확인한 뒤 자기소개와 함께 안내 가능한 문서를 브리핑하세요.
2. 구체적인 기준·수치·절차 질문을 받으면 다음 순서를 따르세요:
   - 먼저 `search_docs`로 관련 키워드가 어느 파일의 몇 번째 줄에 있는지 위치를 찾습니다.
   - 이어서 반드시 `read_doc(filename, start_line, end_line)`으로 해당 줄 앞뒤 원문(표·단서 조항 포함)을 충분히 펼쳐 읽은 뒤 답변하세요. (1줄짜리 스니펫만 보고 성급히 단정하지 마세요.)
3. 모든 답변에는 확인한 **문서명과 조항 번호(예: 제14조, 제15조)**를 명확히 밝히세요.
4. 직급이나 출장 권역처럼 기준이 달라지는 핵심 조건이 질문에서 누락된 경우, 임의로 단정하지 말고 조건별 기준 차이를 정리해 주거나 대상 직급·지역을 되물어 확인하세요.
5. 문서 저장소에서 확인되지 않는 제도나 내용은 절대 지어내지 말고 "현재 비치된 사내 문서에서 확인되지 않는 사항입니다."라고 안내하세요.

오늘의 날짜: {date.today().strftime("%Y-%m-%d")}
"""


async def create_agent_executor(checkpointer=None):
    """File RAG ReAct Agent 팩토리 함수"""
    # 1. 정확한 사실 응답을 위해 temperature=0.0으로 LLM 초기화
    llm = init_chat_model(model="gemini-3.8-flash", temperature=0.0)

    # 2. 서버에서 공유 checkpointer가 주입되지 않은 단독 실행 시 AsyncSqliteSaver 생성
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

    # 3. File RAG 도구 3종 + 시스템 프롬프트 + 체크포인터를 결합한 ReAct 에이전트 조립
    agent = create_agent(
        model=llm,
        tools=file_rag_tools,
        system_prompt=FILE_RAG_SYSTEM_PROMPT,
        checkpointer=checkpointer,
        context_schema=AgentContext,
    )
    agent.checkpointer_conn = conn
    return agent
