"""
graphrag_tool.py
================
Microsoft GraphRAG CLI/API 연동 및 LangGraph 에이전트 도구 패키징 모듈
(Google GenAI / gemini-3.7-flash 기반)
"""

import os
import subprocess
import yaml
from typing import Optional, Dict, Any
from dotenv import load_dotenv
from langchain_core.tools import tool

# .env 로드
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ENV_PATH = os.path.join(PROJECT_ROOT, ".env")
if os.path.exists(ENV_PATH):
    load_dotenv(ENV_PATH, override=True)

if os.getenv("GOOGLE_API_KEY") and not os.getenv("GEMINI_API_KEY"):
    os.environ["GEMINI_API_KEY"] = os.getenv("GOOGLE_API_KEY")


def init_graphrag_workspace(
    root_dir: str,
    llm_model: str = "gemini/gemini-3.7-flash",
    embedding_model: str = "text-embedding-004"
) -> str:
    """
    Microsoft GraphRAG 프로젝트 디렉토리를 초기화하고 Google GenAI 호환 settings.yaml을 작성합니다.
    """
    os.makedirs(root_dir, exist_ok=True)
    input_dir = os.path.join(root_dir, "input")
    os.makedirs(input_dir, exist_ok=True)

    settings = {
        "completion_models": {
            "default_completion_model": {
                "type": "litellm",
                "model": llm_model,
                "api_key": "${GOOGLE_API_KEY}"
            },
            "default_chat_model": {
                "type": "litellm",
                "model": llm_model,
                "api_key": "${GOOGLE_API_KEY}"
            }
        },
        "embedding_models": {
            "default_embedding_model": {
                "type": "litellm",
                "model": embedding_model,
                "api_key": "${GOOGLE_API_KEY}"
            }
        },
        "global_search": {
            "completion_model_id": "default_completion_model"
        },
        "local_search": {
            "completion_model_id": "default_chat_model",
            "embedding_model_id": "default_embedding_model"
        },
        "vector_store": {
            "default_vector_store": {
                "type": "lancedb",
                "db_uri": "output/lancedb",
                "container_name": "default"
            }
        },
        "input": {
            "type": "file",
            "file_type": "text",
            "base_dir": "input",
            "file_pattern": ".*\\.txt",
            "file_encoding": "utf-8"
        },
        "chunking": {
            "size": 500,
            "overlap": 50
        }
    }

    settings_path = os.path.join(root_dir, "settings.yaml")
    with open(settings_path, "w", encoding="utf-8") as f:
        yaml.dump(settings, f, allow_unicode=True, sort_keys=False)

    return settings_path


def run_graphrag_query(
    query: str,
    method: str = "global",
    root_dir: Optional[str] = None,
    community_level: int = 2
) -> str:
    """
    GraphRAG CLI를 호출하여 Global, Local 또는 Drift 검색을 실행합니다.
    app/database/graphrag 경로를 우선 탐색하고, 없으면 data/graphrag를 참조합니다.
    """
    if root_dir is None:
        candidate_paths = [
            os.path.join(PROJECT_ROOT, "app/database/graphrag"),
            os.path.join(PROJECT_ROOT, "data/graphrag"),
            "../app/database/graphrag",
            "../data/graphrag",
            "./app/database/graphrag",
            "./data/graphrag",
        ]
        for p in candidate_paths:
            if os.path.exists(p) and (os.path.exists(os.path.join(p, "output")) or os.path.exists(os.path.join(p, "settings.yaml"))):
                root_dir = p
                break
        if root_dir is None:
            root_dir = candidate_paths[0]

    abs_root = os.path.abspath(root_dir)

    # 환경 변수 보정
    env = os.environ.copy()
    if "GOOGLE_API_KEY" in env:
        env["GEMINI_API_KEY"] = env["GOOGLE_API_KEY"]

    cmd = [
        "graphrag", "query",
        "--root", abs_root,
        "--method", method
    ]
    if method == "global":
        cmd.extend(["--community-level", str(community_level)])
    cmd.append(query)

    res = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if res.returncode != 0:
        return f"[GraphRAG Query Error]: {res.stderr}\n{res.stdout}"
    
    output = res.stdout
    if "SUCCESS:" in output:
        output = output.split("SUCCESS:")[-1].strip()
    return output.strip()


# ==============================================================================
# LangGraph 호환 에이전트 도구 정의 (Agentic RAG Tools)
# ==============================================================================

@tool
def query_graphrag_global(query: str) -> str:
    """
    [GraphRAG Global Search 도구]
    전사적인 프로젝트 현황, 공통 리스크, 핵심 마일스톤 등 광범위하고 거시적인(Global) 질문에 대해
    Leiden 커뮤니티 계층 리포트를 Map-Reduce로 종합하여 답변합니다.
    """
    return run_graphrag_query(query, method="global")


@tool
def query_graphrag_local(query: str) -> str:
    """
    [GraphRAG Local Search 도구]
    특정 인물, 팀, 개별 프로젝트명, 직급 등 고유명사 중심의 미시적(Local) 질문에 대해
    주변 지식 서브그래프 및 원본 텍스트 청크를 정밀 결합하여 답변합니다.
    """
    return run_graphrag_query(query, method="local")
