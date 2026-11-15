"""에이전트 오프라인 평가 패키지 (시드 기반 데이터셋 생성, 조합형 메트릭, 평가 러너)."""

from typing import TYPE_CHECKING

from app.eval.dataset_builder import EvalSeed, generate_from_seeds, verify_generated_cases
from app.eval.metrics import (
    EvalMetric,
    EvalSample,
    PRESET_METRICS,
    answer_correctness,
    answer_relevance,
    context_recall,
    faithfulness,
    metrics_table,
    step_economy,
    tool_selection,
)

if TYPE_CHECKING:
    from app.eval.rag_eval import (
        JUDGE_MODEL,
        NOISE_BAND,
        PASS_THRESHOLD,
        compare_table,
        diagnosis_table,
        evaluate_agent,
        load_golden,
        results_table,
        run_case,
        summary_line,
    )

_RAG_EVAL_EXPORTS = {
    "JUDGE_MODEL",
    "NOISE_BAND",
    "PASS_THRESHOLD",
    "load_golden",
    "run_case",
    "evaluate_agent",
    "summary_line",
    "results_table",
    "diagnosis_table",
    "compare_table",
}


def __getattr__(name: str):
    if name in _RAG_EVAL_EXPORTS:
        from app.eval import rag_eval
        return getattr(rag_eval, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "EvalSeed",
    "generate_from_seeds",
    "verify_generated_cases",
    "EvalMetric",
    "EvalSample",
    "PRESET_METRICS",
    "answer_correctness",
    "faithfulness",
    "context_recall",
    "answer_relevance",
    "tool_selection",
    "step_economy",
    "metrics_table",
    "JUDGE_MODEL",
    "NOISE_BAND",
    "PASS_THRESHOLD",
    "load_golden",
    "run_case",
    "evaluate_agent",
    "summary_line",
    "results_table",
    "diagnosis_table",
    "compare_table",
]
