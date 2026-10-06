"""
===============================================================================
[Agentic RAG] Skill RAG Agent — Skills + MCP 점진적 공개 에이전트
===============================================================================
범용 원시 도구 3종(glob_search, file_read, bash_command)만 장착하고, 스킬 카탈로그와
MCP 서버 레지스트리를 스스로 탐색하여 필요한 MCP 도구를 찾아 실행합니다.
tool_rag_agent와 같은 ReAct 루프를 쓰며, 도구를 연결하는 방식만 다릅니다.

패키지 구조:
  app/agents/skill_rag_agent/
   ├── agent.py      (에이전트 조립 및 팩토리)
   ├── prompt.py     (BASE_SKILL_RAG_SYSTEM_PROMPT 및 스킬 카탈로그 빌더)
   └── tools.py      (범용 원시 도구 3종)
===============================================================================
"""

import os
import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langchain.agents import create_agent
from app.utils import init_chat_model
from app.utils.context import AgentContext

from app.middleware import SkillCatalogMiddleware
from .prompt import BASE_SKILL_RAG_SYSTEM_PROMPT, get_skill_prompt_builder
from .tools import tools_skill_rag

AGENT_METADATA = {
    "name": "skill_rag_agent",
    "description": "Skills와 MCP 서버를 점진적으로 탐색하여 사내 데이터를 조회하는 Agentic RAG 에이전트",
}


async def create_agent_executor():
    # 1. LLM 설정
    llm = init_chat_model(model="gemini-3.8-flash", temperature=0.0)

    # 2. AsyncSqliteSaver 기반 체크포인터 (SQLite 영구 메모리)
    db_dir = "app/database"
    os.makedirs(db_dir, exist_ok=True)
    checkpoints_path = os.path.join(db_dir, "checkpoints.db")

    conn = await aiosqlite.connect(checkpoints_path, check_same_thread=False)
    checkpointer = AsyncSqliteSaver(conn)
    await checkpointer.setup()

    # 3. 미들웨어 구성 (SkillCatalogMiddleware: 스킬 카탈로그 동적 주입)
    middleware = [SkillCatalogMiddleware(get_skill_prompt_builder())]

    # 4. 범용 원시 도구 3종만 장착한 Skill RAG 에이전트 구축
    skill_rag_agent = create_agent(
        model=llm,
        tools=tools_skill_rag,
        system_prompt=BASE_SKILL_RAG_SYSTEM_PROMPT,
        middleware=middleware,
        checkpointer=checkpointer,
        context_schema=AgentContext,
    )
    return skill_rag_agent
