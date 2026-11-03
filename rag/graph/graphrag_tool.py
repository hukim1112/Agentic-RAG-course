"""
graphrag_tool.py
================
Microsoft GraphRAG 프로젝트 설정 모듈 (워크스페이스 초기화, 인덱스 경로 해석)

GraphRAG 기본 검색(Local / Global)은 검색 엔진 안에서 LLM이 답변까지 작성하므로 느리고,
답변 생성을 빼면 맥락이 토큰 상한까지 채워져 지나치게 커집니다. 그래서 에이전트에는
GraphRAG 인덱스 산출물을 단계적으로 조회하는 탐색 도구 5종(rag/graph/graph_explorer.py)을 제공합니다.
GraphRAG 기본 검색을 직접 실행해 보려면 CLI를 사용합니다.

    graphrag query "질문" --root app/database/graphrag --method local   # 또는 global

인덱스 위치(root_dir)는 configs/graphrag.config에서 조정합니다.
"""

import copy
import json
import logging
import os
from typing import Any, Dict, Optional

import yaml
from dotenv import load_dotenv

# GraphRAG 및 LiteLLM 내부의 불필요한 경고 로그 억제
for _logger_name in ("graphrag", "LiteLLM"):
    logging.getLogger(_logger_name).setLevel(logging.ERROR)

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ENV_PATH = os.path.join(PROJECT_ROOT, ".env")
if os.path.exists(ENV_PATH):
    load_dotenv(ENV_PATH, override=True)

GRAPHRAG_CONFIG_PATH = os.path.join(PROJECT_ROOT, "configs", "graphrag.config")

# configs/graphrag.config가 없거나 일부 키가 빠졌을 때 쓰는 값
_DEFAULT_SETTINGS: Dict[str, Any] = {
    "root_dir": "./app/database/graphrag",
}


def _resolve_root_dir(root_dir: Optional[str] = None) -> str:
    if root_dir is not None and os.path.exists(root_dir):
        return os.path.abspath(root_dir)
    candidate_paths = [
        os.path.join(PROJECT_ROOT, "app/database/graphrag"),
        os.path.join(PROJECT_ROOT, "data/graphrag"),
        "../app/database/graphrag",
        "../data/graphrag",
        "./app/database/graphrag",
        "./data/graphrag",
    ]
    for p in candidate_paths:
        if os.path.exists(p) and os.path.exists(os.path.join(p, "output")):
            return os.path.abspath(p)
    return os.path.abspath(candidate_paths[0])


def init_graphrag_workspace(
    root_dir: str,
    llm_model: str = "gemini-3.7-flash",
    embedding_model: str = "gemini-embedding-001",
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
                "model_provider": "gemini",
                "model": llm_model,
                "api_key": "${GOOGLE_API_KEY}",
            },
            "default_chat_model": {
                "type": "litellm",
                "model_provider": "gemini",
                "model": llm_model,
                "api_key": "${GOOGLE_API_KEY}",
            },
        },
        "embedding_models": {
            "default_embedding_model": {
                "type": "litellm",
                "model_provider": "gemini",
                "model": embedding_model,
                "api_key": "${GOOGLE_API_KEY}",
            }
        },
        "global_search": {"completion_model_id": "default_completion_model"},
        "local_search": {
            "completion_model_id": "default_chat_model",
            "embedding_model_id": "default_embedding_model",
        },
        "vector_store": {
            "default_vector_store": {
                "type": "lancedb",
                "db_uri": "output/lancedb",
                "container_name": "default",
            }
        },
        "input": {
            "file_type": "text",
            "base_dir": "input",
            "file_pattern": ".*\\.txt",
            "file_encoding": "utf-8",
        },
        "chunking": {"size": 500, "overlap": 50},
    }

    settings_path = os.path.join(root_dir, "settings.yaml")
    with open(settings_path, "w", encoding="utf-8") as f:
        yaml.dump(settings, f, allow_unicode=True, sort_keys=False)

    return settings_path


def load_graphrag_settings(path: str = GRAPHRAG_CONFIG_PATH) -> Dict[str, Any]:
    """configs/graphrag.config를 읽어 기본값 위에 덮어쓴 설정을 반환합니다."""
    settings = copy.deepcopy(_DEFAULT_SETTINGS)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            user_settings = json.load(f)
        for key, value in user_settings.items():
            if isinstance(value, dict) and isinstance(settings.get(key), dict):
                settings[key].update(value)
            else:
                settings[key] = value
    return settings
