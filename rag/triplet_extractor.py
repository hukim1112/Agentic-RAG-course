"""
triplet_extractor.py
====================
Pydantic 및 Vertex AI Gemini 기반 지식 그래프(Entity-Relation-Entity) 구조화 추출 모듈
"""

import os
from typing import List, Optional
from pydantic import BaseModel, Field
from langchain.chat_models import init_chat_model


class Triplet(BaseModel):
    """지식 그래프 단일 트리플렛: (주어, 관계, 목적어)"""
    subject: str = Field(description="출발 엔티티 (예: 김철수 수석, 클라우드운영팀, P-01 프로젝트)")
    relation: str = Field(description="엔티티 간의 구체적 관계명 (예: 소속됨, 총괄PM, 보고함, 승인함, 투입됨, 의존함)")
    object: str = Field(description="도착 엔티티 (예: 클라우드사업본부, 박영희 전무, 3억 5000만원)")


class KnowledgeGraph(BaseModel):
    """텍스트에서 추출된 지식 그래프 트리플렛 모음"""
    triplets: List[Triplet] = Field(description="추출된 지식 그래프 트리플렛 목록")


def get_default_llm(
    model: str = "gemini-3.7-flash",
    project: str = "project-5f90a776-f598-4b87-b9c",
    location: str = "global",
    temperature: float = 0.0
):
    """Vertex AI Gemini LLM 인스턴스를 초기화합니다."""
    return init_chat_model(
        model=model,
        model_provider="google_genai",
        location=location,
        project=project,
        temperature=temperature
    )


def extract_triplets(
    text: str,
    llm = None,
    instruction: Optional[str] = None
) -> KnowledgeGraph:
    """
    비정형 텍스트에서 Entity-Relation-Entity 트리플렛을 구조화하여 추출합니다.
    """
    if llm is None:
        llm = get_default_llm()

    structured_llm = llm.with_structured_output(KnowledgeGraph)

    prompt = (
        "당신은 엔터프라이즈 지식 그래프 구축 전문가입니다.\n"
        "제공된 텍스트에서 조직 구조, 보고 체계, 결재 승인선, 프로젝트 참여 인력, 예산, 리스크, 부서 간 의존성 관계를 "
        "모두 포괄하는 정확하고 구체적인 지식 그래프 트리플렛(Subject, Relation, Object)을 추출하세요.\n\n"
        f"[원본 텍스트]:\n{text}"
    )
    if instruction:
        prompt += f"\n\n[추가 지시사항]:\n{instruction}"

    return structured_llm.invoke(prompt)
