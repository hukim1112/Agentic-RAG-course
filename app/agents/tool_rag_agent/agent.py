"""
===============================================================================
[Agentic RAG] Tool RAG Agent — 검색 도구를 직접 바인딩한 ReAct 에이전트
===============================================================================
4대 엔터프라이즈 DB 검색 도구를 `@tool`로 직접 바인딩하여, 에이전트가 질문에 따라
도구를 선택하고 여러 번 호출하며 답을 찾는 가장 기본적인 Agentic RAG 형태입니다.

패키지 구조:
  app/agents/tool_rag_agent/
   ├── agent.py      (에이전트 조립 및 팩토리)
   ├── prompt.py     (TOOL_RAG_SYSTEM_PROMPT)
   └── tools.py      (4대 DB 검색 도구: 사내 규정, AWS 백서, 지식 그래프, 사내 ERP)
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
    # 1. LLM 설정
    llm = init_chat_model(model="gemini-3.8-flash", temperature=0.0)

    # 2. 공유 SQLite 체크포인터 SSOT (AsyncSqliteSaver)
    if checkpointer is None:
        checkpointer = await get_shared_checkpointer()

    # 3. 검색 도구 3종(규정·AWS 백서·ERP) + 그래프 탐색 도구 5종을 직접 바인딩한 ReAct 에이전트 구축
    return create_agent(
        model=llm,
        tools=tools_tool_rag,
        system_prompt=TOOL_RAG_SYSTEM_PROMPT,
        checkpointer=checkpointer,
        context_schema=AgentContext,
    )
