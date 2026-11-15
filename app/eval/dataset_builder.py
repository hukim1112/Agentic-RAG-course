"""
app/eval/dataset_builder.py
===========================
시드(Seed) 기반 평가 데이터셋 생성 및 자동 품질 검수 모듈.

초기 서비스 배포 전 사용자 로그가 없을 때, 엔지니어가 정의한 시드(평가 범주, 주제,
구체적 시나리오 지침, 참조 문서, 기대 호출 도구)로부터 평가 문항 초안을 생성하고,
다른 계열의 판사 모델로 근거 일치성·독립성·채점 기준 명확성을 검수합니다.
"""

from __future__ import annotations

import os
import json
import asyncio
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

import pandas as pd
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))


@dataclass
class EvalSeed:
    """평가 문항 1건을 생성하기 위한 시드(Seed) 명세."""

    id: str
    category: str
    topic: str
    scenario: str
    source_files: List[str]
    target_tools: List[str] = field(default_factory=list)
    section_keyword: Optional[str] = None
    max_chars_per_file: int = 3500


class GeneratedCaseSchema(BaseModel):
    """시드로부터 생성된 평가 문항 초안 스키마."""

    question: str = Field(
        description="실제 임직원이 묻는 것처럼 작성한 완결된 질문 ('위 표에서', '동 지침상' 같은 문서 지시어 사용 금지)"
    )
    ground_truth: str = Field(
        description="채점 기준이 되는 정답 (근거 조항 번호, 계산 과정·수치, 비공식 호칭일 경우 가능한 직급 구간과 확인 절차 명시)"
    )
    evidence_quote: str = Field(
        description="정답의 근거가 되는 원천 문서 핵심 구절 요약 또는 확인한 문서 범위"
    )


class CaseQualityVerdict(BaseModel):
    """생성된 평가 문항에 대한 판사 모델 검수 결과."""

    is_grounded: bool = Field(
        description="정답(ground_truth)의 수치·조건·결론이 원천 문서와 정확히 일치하며 임의 추측이 없는가"
    )
    is_standalone: bool = Field(
        description="원천 문서를 보지 않고 질문(question)만 읽어도 대상과 조건이 명확한가"
    )
    is_clear_rubric: bool = Field(
        description="채점자가 일관되게 정오를 판정할 수 있도록 정답 기준이 모호하지 않은가"
    )
    reason: str = Field(description="검수 판정 사유 및 담당자 최종 확인 포인트 (1~2문장)")


_CASE_GEN_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "당신은 사내 AI 에이전트 평가 문항을 작성하는 엔지니어입니다.\n"
        "제공된 [시드 명세]와 [원천 문서 발췌]만을 근거로 평가 문항 1건을 작성하세요.\n\n"
        "작성 원칙:\n"
        "1. 질문 독립성: 질문만 읽어도 조건이 완결되어야 합니다. '위 표에 따르면', '제14조에서'처럼 원문을 보고 있다는 전제의 표현을 쓰지 마세요.\n"
        "2. 원문 근거 엄수: 원천 문서에 적힌 수치·조항·테이블 구조만 사용하세요. 없는 수치나 조건을 추측해 넣지 마세요.\n"
        "3. 유형별 주의사항:\n"
        "   - '존재하지 않는 정보' 유형은 원천 문서에 실제로 없는 제도를 묻고, 정답에는 해당 제도가 규정에서 확인되지 않는다는 점을 명시하세요.\n"
        "   - '용어 불일치' 유형은 사규 공식 직급에 없는 비공식 호칭을 질문에 쓰고, 정답에는 적용 가능한 공식 직급 구간별 금액과 확인 절차를 함께 적으세요.",
    ),
    (
        "human",
        "[시드 명세]\n"
        "- 문항 ID: {seed_id}\n"
        "- 평가 유형: {category}\n"
        "- 주제(Topic): {topic}\n"
        "- 시나리오 지침: {scenario}\n"
        "- 기대 호출 도구: {target_tools}\n\n"
        "[원천 문서 발췌]\n{source_context}",
    ),
])

_CASE_VERIFY_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "당신은 평가 데이터셋 품질 검수자입니다. 생성된 [평가 문항 초안]이 [시드 명세] 및 [원천 문서 발췌]에 부합하는지 검사하세요.\n"
        "- '존재하지 않는 정보' 유형은 원천 문서에 해당 제도가 실제로 없고, 정답이 미존재를 안내하도록 작성되었다면 is_grounded=True입니다.\n"
        "- '용어 불일치' 유형은 비공식 호칭임을 밝히고 가능한 직급별 기준과 확인 절차를 안내하도록 정답이 작성되었다면 is_clear_rubric=True입니다.",
    ),
    (
        "human",
        "[시드 명세]\n"
        "- 평가 유형: {category}\n"
        "- 주제: {topic}\n"
        "- 시나리오 지침: {scenario}\n\n"
        "[원천 문서 발췌]\n{source_context}\n\n"
        "[평가 문항 초안]\n{candidate_json}",
    ),
])


def load_seed_context(seed: EvalSeed, project_root: str = PROJECT_ROOT) -> str:
    """시드에 지정된 원천 파일들에서 관련 구간을 읽어 하나의 참조 문자열로 묶습니다."""
    excerpts = []
    for rel_path in seed.source_files:
        abs_path = rel_path if os.path.isabs(rel_path) else os.path.join(project_root, rel_path)
        with open(abs_path, "r", encoding="utf-8") as f:
            raw = f.read()

        if seed.section_keyword and seed.section_keyword in raw:
            pos = max(0, raw.find(seed.section_keyword) - 150)
            snippet = raw[pos : pos + seed.max_chars_per_file]
        else:
            snippet = raw[: seed.max_chars_per_file]

        excerpts.append(f"[{os.path.basename(rel_path)} 발췌]\n{snippet.strip()}")
    return "\n\n".join(excerpts)


async def generate_from_seeds(
    seeds: Sequence[EvalSeed],
    llm=None,
    concurrency: int = 4,
    project_root: str = PROJECT_ROOT,
) -> List[dict]:
    """시드 목록으로부터 평가 문항 초안을 병렬 생성합니다."""
    if llm is None:
        from app.utils import init_chat_model
        llm = init_chat_model(model="gemini-3.8-flash", temperature=0.0)

    chain = _CASE_GEN_PROMPT | llm.with_structured_output(GeneratedCaseSchema)
    semaphore = asyncio.Semaphore(concurrency)

    async def _one(seed: EvalSeed) -> dict:
        async with semaphore:
            source_context = load_seed_context(seed, project_root=project_root)
            generated: GeneratedCaseSchema = await chain.ainvoke({
                "seed_id": seed.id,
                "category": seed.category,
                "topic": seed.topic,
                "scenario": seed.scenario,
                "target_tools": ", ".join(seed.target_tools),
                "source_context": source_context,
            })
            return {
                "id": seed.id,
                "category": seed.category,
                "topic": seed.topic,
                "question": generated.question,
                "ground_truth": generated.ground_truth,
                "evidence_quote": generated.evidence_quote,
                "target_tools": list(seed.target_tools),
            }

    return list(await asyncio.gather(*(_one(s) for s in seeds)))


async def verify_generated_cases(
    cases: Sequence[dict],
    seeds: Sequence[EvalSeed],
    judge_llm=None,
    concurrency: int = 4,
    project_root: str = PROJECT_ROOT,
) -> Tuple[pd.DataFrame, List[dict]]:
    """생성된 문항 초안을 판사 모델로 검수하고 (검수 요약 표, 통과 문항 리스트)를 반환합니다."""
    if judge_llm is None:
        from app.utils import init_chat_model
        from app.eval.rag_eval import JUDGE_MODEL
        judge_llm = init_chat_model(model=JUDGE_MODEL, temperature=0.0)

    seed_map = {s.id: s for s in seeds}
    chain = _CASE_VERIFY_PROMPT | judge_llm.with_structured_output(CaseQualityVerdict)
    semaphore = asyncio.Semaphore(concurrency)

    async def _check(case: dict) -> Tuple[dict, Optional[dict]]:
        async with semaphore:
            seed = seed_map[case["id"]]
            source_context = load_seed_context(seed, project_root=project_root)
            verdict: CaseQualityVerdict = await chain.ainvoke({
                "category": seed.category,
                "topic": seed.topic,
                "scenario": seed.scenario,
                "source_context": source_context,
                "candidate_json": json.dumps(
                    {
                        "question": case["question"],
                        "ground_truth": case["ground_truth"],
                        "evidence_quote": case.get("evidence_quote", ""),
                        "target_tools": case["target_tools"],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            })
            passed = verdict.is_grounded and verdict.is_standalone and verdict.is_clear_rubric
            row = {
                "문항 ID": case["id"],
                "유형": case["category"],
                "시드 주제": case.get("topic", seed.topic),
                "생성된 질문": case["question"],
                "기대 도구": case["target_tools"],
                "검수 판정": "통과" if passed else "보완 필요",
                "검수 의견": verdict.reason,
            }
            accepted = (
                {
                    "id": case["id"],
                    "category": case["category"],
                    "question": case["question"],
                    "ground_truth": case["ground_truth"],
                    "target_tools": case["target_tools"],
                }
                if passed
                else None
            )
            return row, accepted

    checked = await asyncio.gather(*(_check(c) for c in cases))
    summary_rows = [r for r, _ in checked]
    accepted_cases = [a for _, a in checked if a is not None]
    return pd.DataFrame(summary_rows), accepted_cases
