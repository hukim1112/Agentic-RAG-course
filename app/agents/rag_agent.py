"""
app/agents/rag_agent.py
=======================
[Instructor Solution] Enterprise Agentic RAG Frontier Agent

Anthropic Agent Skills 표준과 점진적 공개(Progressive Disclosure) 아키텍처를 기반으로,
3대 범용 도구(glob_search, file_read, bash_command)만을 장착하여
MCP.md 카탈로그와 skills/mcp/ CLI를 자율 탐색 및 실행하는 에이전트입니다.
"""

import os
from langgraph.checkpoint.memory import MemorySaver
from langchain.agents import create_agent
from app.utils import get_llm
from app.tools.common import file_read, glob_search, bash_command
from app.utils.context import AgentContext

AGENT_METADATA = {
    "name": "rag_agent",
    "description": "Anthropic Skills 기반 Enterprise RAG & FastMCP 통합 Frontier 어시스턴트"
}


def create_agent_executor():
    # 1. Google GenAI 최신 모델 로드
    llm = get_llm(model_name="google_genai:gemini-3.7-flash", temperature=0.1)
    
    # 2. RAG_PROMPT.md 로드 (3단계 점진적 탐색 헌법)
    prompt_path = os.path.join(os.path.dirname(__file__), "../prompts/RAG_PROMPT.md")
    with open(prompt_path, "r", encoding="utf-8") as f:
        system_prompt = f.read()
        
    # 3. 3대 범용 원시 도구 바인딩
    primitive_tools = [glob_search, file_read, bash_command]
    
    return create_agent(
        model=llm,
        tools=primitive_tools,
        system_prompt=system_prompt,
        checkpointer=MemorySaver(),
        context_schema=AgentContext
    )
