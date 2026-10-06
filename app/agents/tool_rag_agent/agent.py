"""
===============================================================================
[Agentic RAG] Tool RAG Agent — 검색 도구를 직접 바인딩한 ReAct 에이전트
===============================================================================
4대 엔터프라이즈 DB 검색 도구를 `@tool`로 직접 바인딩하여, 에이전트가 질문에 따라
도구를 선택하고 여러 번 호출하며 답을 찾는 가장 기본적인 Agentic RAG 형태입니다.

패키지 구조:
  app/agents/tool_rag_agent/
   ├── agent.py      (에이전트 조립 및 팩토리)   👈 [Mission 01] 이 파일을 완성하세요!
   ├── prompt.py     (TOOL_RAG_SYSTEM_PROMPT)
   └── tools.py      (4대 DB 검색 도구: 사내 규정, BOK 보고서, 조직 그래프, GraphRAG)
===============================================================================
"""

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
    # ==========================================================================
    # TODO 1. LLM 설정
    #   - init_chat_model(model="gemini-3.8-flash", temperature=0.0)
    # ==========================================================================

    # ==========================================================================
    # TODO 2. AsyncSqliteSaver 기반 체크포인터 (SQLite 영구 메모리)
    #   - 저장 위치: app/database/checkpoints.db (폴더가 없으면 생성)
    #   - aiosqlite.connect(..., check_same_thread=False)로 연결
    #   - AsyncSqliteSaver(conn) 생성 후 반드시 `await checkpointer.setup()` 호출
    # ==========================================================================

    # ==========================================================================
    # TODO 3. 검색 도구 4종을 직접 바인딩한 ReAct 에이전트 생성 후 반환
    #   - create_agent(model, tools=tools_tool_rag, system_prompt=TOOL_RAG_SYSTEM_PROMPT,
    #                  checkpointer, context_schema=AgentContext)
    # ==========================================================================

    raise NotImplementedError("Mission 01: create_agent_executor()를 완성하세요. (missions/01_missions.md 3단계 참고)")
