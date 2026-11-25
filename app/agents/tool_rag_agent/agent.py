"""
===============================================================================
[Agentic RAG] Tool RAG Agent — 검색 도구를 직접 바인딩한 ReAct 에이전트
===============================================================================
4대 엔터프라이즈 DB 검색 도구(규정·AWS 백서·ERP 3종 + 지식 그래프 탐색 5종)를 `@tool`로 직접 바인딩하여, 에이전트가 질문에 따라
도구를 선택하고 여러 번 호출하며 답을 찾는 가장 기본적인 Agentic RAG 형태입니다.

패키지 구조:
  app/agents/tool_rag_agent/
   ├── agent.py      (에이전트 조립 및 팩토리)   👈 [Mission 02] 이 파일을 완성하세요!
   ├── prompt.py     (TOOL_RAG_SYSTEM_PROMPT)
   └── tools.py      (4대 DB 검색 도구: 사내 규정, AWS 백서, 사내 ERP, 지식 그래프 탐색 5종)
===============================================================================
"""

from langchain.agents import create_agent
from app.utils import init_chat_model
from app.utils.database import get_shared_checkpointer
from app.utils.context import AgentContext

from .prompt import TOOL_RAG_SYSTEM_PROMPT
from .tools import tools_tool_rag

AGENT_METADATA = {
    "name": "tool_rag_agent",
    "description": "4대 DB 검색 도구를 직접 바인딩한 ReAct 기반 Agentic RAG 에이전트",
}


async def create_agent_executor(checkpointer=None):
    # ==========================================================================
    # TODO 1. LLM 설정
    #   - init_chat_model(model="gemini-3.8-flash", temperature=0.0)
    # ==========================================================================

    # ==========================================================================
    # TODO 2. 공유 SQLite 체크포인터 SSOT (AsyncSqliteSaver)
    #   - FastAPI 서버 실행 시에는 공유 checkpointer가 인자로 주입됨
    #   - 단독 실행(checkpointer is None)일 때만 `await get_shared_checkpointer()` 호출
    # ==========================================================================

    # ==========================================================================
    # TODO 3. 검색 도구(tools_tool_rag)를 직접 바인딩한 ReAct 에이전트 생성 후 반환
    #   - create_agent(model, tools=tools_tool_rag, system_prompt=TOOL_RAG_SYSTEM_PROMPT,
    #                  checkpointer, context_schema=AgentContext)
    # ==========================================================================

    raise NotImplementedError("Mission 02: create_agent_executor()를 완성하세요. (missions/02_missions.md 2단계 참고)")
