"""
app/eval/metrics.py
===================
조합 가능한(Composable) 평가 메트릭 인터페이스 및 기본 제공 메트릭 모음.

기본 제공 메트릭(answer_correctness, context_recall, tool_selection, step_economy 등)과
사용자가 직접 작성한 커스텀 채점 함수(동기 Python 함수 또는 비동기 LLM 체인)를
`EvalMetric`으로 감싸 하나의 리스트(`metrics=[...]`)로 묶어 `evaluate_agent`에 전달할 수 있습니다.
"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import pandas as pd

from app.middleware.rag_eval_harness import (
    OutcomeEvaluation,
    RAGEvalHarnessMiddleware,
    TrajectoryEvaluation,
)


@dataclass
class EvalSample:
    """단일 평가 문항에 대한 에이전트 실행 기록과 정답 라벨."""

    id: str
    category: str
    question: str
    ground_truth: str
    target_tools: List[str]
    answer: str
    contexts: List[str]
    trajectory: List[Dict[str, Any]]
    duration_s: float = 0.0
    hit_limit: bool = False
    _cache: Dict[str, Any] = field(default_factory=dict, repr=False)
    _lock: Optional[asyncio.Lock] = field(default=None, repr=False)

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    @property
    def tool_calls(self) -> int:
        return len(self.trajectory)

    @property
    def tools(self) -> List[str]:
        return [t["tool_name"] for t in self.trajectory]

    async def get_trajectory_eval(self, harness: RAGEvalHarnessMiddleware) -> TrajectoryEvaluation:
        """기본 과정(Trajectory) 평가 결과를 문항당 1회만 호출해 캐시합니다."""
        async with self._get_lock():
            if "trajectory_eval" not in self._cache:
                self._cache["trajectory_eval"] = await asyncio.to_thread(
                    harness.evaluate_trajectory,
                    self.question,
                    self.target_tools,
                    self.trajectory,
                    self.answer,
                )
            return self._cache["trajectory_eval"]

    async def get_outcome_eval(self, harness: RAGEvalHarnessMiddleware) -> OutcomeEvaluation:
        """기본 결과(Outcome) 평가 결과를 문항당 1회만 호출해 캐시합니다."""
        async with self._get_lock():
            if "outcome_eval" not in self._cache:
                self._cache["outcome_eval"] = await asyncio.to_thread(
                    harness.evaluate_outcome,
                    self.question,
                    self.ground_truth,
                    self.contexts,
                    self.answer,
                )
            return self._cache["outcome_eval"]


class EvalMetric:
    """단일 평가 지표를 나타내는 래퍼 클래스.

    `fn`에는 일반 Python 함수(`def`)와 비동기 함수(`async def`)를 모두 넣을 수 있으며,
    함수 시그니처의 인자 이름(`answer`, `contexts`, `question`, `ground_truth`,
    `target_tools`, `trajectory`, `tool_calls`, `judge_llm`, `sample` 등)에 맞춰
    필요한 값만 자동으로 주입됩니다.
    """

    def __init__(
        self,
        name: str,
        fn: Callable[..., Any],
        label: Optional[str] = None,
        weight: float = 0.0,
        threshold: Optional[float] = None,
        diagnosis: Optional[str] = None,
        suspect_layer: str = "",
        kind: str = "custom",
        mode: Optional[str] = None,
    ):
        self.name = name
        self.fn = fn
        self.label = label or name
        self.weight = weight
        self.threshold = threshold
        self.diagnosis = diagnosis or self.label
        self.suspect_layer = suspect_layer
        self.kind = kind
        self.mode = mode or ("LLM 체인" if inspect.iscoroutinefunction(fn) else "Python 코드")

    def with_config(
        self,
        *,
        label: Optional[str] = None,
        weight: Optional[float] = None,
        threshold: Optional[float] = None,
        diagnosis: Optional[str] = None,
        suspect_layer: Optional[str] = None,
    ) -> "EvalMetric":
        """기존 메트릭의 가중치나 임계값만 바꾼 사본을 반환합니다."""
        return EvalMetric(
            name=self.name,
            fn=self.fn,
            label=self.label if label is None else label,
            weight=self.weight if weight is None else weight,
            threshold=self.threshold if threshold is None else threshold,
            diagnosis=self.diagnosis if diagnosis is None else diagnosis,
            suspect_layer=self.suspect_layer if suspect_layer is None else suspect_layer,
            kind=self.kind,
            mode=self.mode,
        )

    def to_spec(self) -> Dict[str, Any]:
        """리포트 저장 및 결과 테이블 구성을 위한 JSON 직렬화 가능 메타데이터."""
        return {
            "name": self.name,
            "label": self.label,
            "weight": self.weight,
            "threshold": self.threshold,
            "diagnosis": self.diagnosis,
            "suspect_layer": self.suspect_layer,
            "kind": self.kind,
            "mode": self.mode,
        }

    async def aevaluate(
        self,
        sample: EvalSample,
        judge_llm: Any = None,
        harness: Optional[RAGEvalHarnessMiddleware] = None,
    ) -> Tuple[float, Dict[str, Any]]:
        """단일 문항(EvalSample)에 대해 지표를 실행하고 (정규화 점수, 부가 정보)를 반환합니다."""
        available = {
            "sample": sample,
            "id": sample.id,
            "case_id": sample.id,
            "category": sample.category,
            "question": sample.question,
            "ground_truth": sample.ground_truth,
            "target_tools": sample.target_tools,
            "answer": sample.answer,
            "contexts": sample.contexts,
            "trajectory": sample.trajectory,
            "tool_calls": sample.tool_calls,
            "tools": sample.tools,
            "duration_s": sample.duration_s,
            "hit_limit": sample.hit_limit,
            "judge_llm": judge_llm,
            "harness": harness,
        }

        sig = inspect.signature(self.fn)
        kwargs: Dict[str, Any] = {}
        accepts_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())

        for pname, param in sig.parameters.items():
            if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                continue
            if pname in available:
                kwargs[pname] = available[pname]
            elif param.default is inspect.Parameter.empty and len(sig.parameters) == 1:
                kwargs[pname] = sample

        if accepts_var_kw and not kwargs:
            kwargs = available

        if inspect.iscoroutinefunction(self.fn):
            raw = await self.fn(**kwargs)
        else:
            raw = await asyncio.to_thread(self.fn, **kwargs)

        details: Dict[str, Any] = {}
        if isinstance(raw, (int, float, bool)):
            score = float(raw)
        elif isinstance(raw, dict):
            score = float(raw["score"])
            details = {k: v for k, v in raw.items() if k != "score"}
        elif hasattr(raw, "score"):
            score = float(raw.score)
        else:
            raise ValueError(f"Metric '{self.name}' returned unsupported value: {type(raw)}")

        score = round(max(0.0, min(1.0, score)), 2)
        return score, details


# ---------------------------------------------------------------------------
# 기본 제공(Preset) 메트릭 정의 (문항당 캐시된 Trajectory / Outcome 판정 공유)
# ---------------------------------------------------------------------------

async def _score_answer_correctness(sample: EvalSample, harness: RAGEvalHarnessMiddleware) -> float:
    out = await sample.get_outcome_eval(harness)
    return out.answer_correctness


async def _score_faithfulness(sample: EvalSample, harness: RAGEvalHarnessMiddleware) -> float:
    out = await sample.get_outcome_eval(harness)
    return out.faithfulness


async def _score_context_recall(sample: EvalSample, harness: RAGEvalHarnessMiddleware) -> float:
    out = await sample.get_outcome_eval(harness)
    return out.context_recall


async def _score_answer_relevance(sample: EvalSample, harness: RAGEvalHarnessMiddleware) -> float:
    out = await sample.get_outcome_eval(harness)
    return out.answer_relevance


async def _score_tool_selection(sample: EvalSample, harness: RAGEvalHarnessMiddleware) -> float:
    traj = await sample.get_trajectory_eval(harness)
    return traj.tool_selection_accuracy


async def _score_step_economy(sample: EvalSample, harness: RAGEvalHarnessMiddleware) -> float:
    traj = await sample.get_trajectory_eval(harness)
    return traj.step_economy_score


answer_correctness = EvalMetric(
    name="correctness",
    label="정답 일치",
    fn=_score_answer_correctness,
    weight=0.30,
    threshold=0.7,
    diagnosis="오답",
    suspect_layer="검색 결과 해석, 수치 계산·비교 지침",
    kind="preset",
    mode="LLM 판사",
)

faithfulness = EvalMetric(
    name="faithfulness",
    label="근거 충실",
    fn=_score_faithfulness,
    weight=0.20,
    threshold=0.7,
    diagnosis="근거 없는 생성",
    suspect_layer="답변 원칙, 출처 인용 지침",
    kind="preset",
    mode="LLM 판사",
)

context_recall = EvalMetric(
    name="recall",
    label="검색 재현",
    fn=_score_context_recall,
    weight=0.15,
    threshold=0.6,
    diagnosis="검색 품질",
    suspect_layer="검색 쿼리, 인덱스(청킹·헤더), 도구 인자",
    kind="preset",
    mode="LLM 판사",
)

answer_relevance = EvalMetric(
    name="relevance",
    label="질문 관련성",
    fn=_score_answer_relevance,
    weight=0.10,
    threshold=0.7,
    diagnosis="질문 이해",
    suspect_layer="용어 사전, 질의 재작성",
    kind="preset",
    mode="LLM 판사",
)

tool_selection = EvalMetric(
    name="tool_selection",
    label="도구 선택",
    fn=_score_tool_selection,
    weight=0.15,
    threshold=0.6,
    diagnosis="도구 선택",
    suspect_layer="도구 설명(Docstring), 시스템 프롬프트",
    kind="preset",
    mode="LLM 판사",
)

step_economy = EvalMetric(
    name="step_economy",
    label="호출 효율",
    fn=_score_step_economy,
    weight=0.10,
    threshold=0.6,
    diagnosis="비효율 호출",
    suspect_layer="도구 반환 형식, 호출 중단 지침",
    kind="preset",
    mode="LLM 판사",
)

PRESET_METRICS: List[EvalMetric] = [
    answer_correctness,
    faithfulness,
    context_recall,
    answer_relevance,
    tool_selection,
    step_economy,
]


def metrics_table(metrics: Sequence[EvalMetric]) -> pd.DataFrame:
    """벤치마크에 등록된 메트릭 리스트 구성을 요약 표(DataFrame)로 반환합니다."""
    total_w = sum(m.weight for m in metrics if m.weight > 0) or 1.0
    rows = []
    for m in metrics:
        norm_w = (m.weight / total_w) if m.weight > 0 else 0.0
        rows.append({
            "지표 키": m.name,
            "결과 표 컬럼명": m.label,
            "구분": "기본 제공" if m.kind == "preset" else "커스텀",
            "채점 방식": m.mode,
            "반영 비중": f"{norm_w:.0%}" if m.weight > 0 else "참고",
            "진단 기준": f"< {m.threshold}" if m.threshold is not None else "-",
            "의심할 계층": m.suspect_layer or "-",
        })
    return pd.DataFrame(rows)
