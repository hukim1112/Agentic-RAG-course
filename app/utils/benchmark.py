"""
app/utils/benchmark.py
======================
에이전틱 RAG 성능 평가를 위한 고속 병렬(Concurrent) 벤치마크 엔진.
Naive ReAct Agent와 Middleware-Harnessed Agent를 10개 골든 케이스에 대해
스레드 격리 환경에서 동시 실행하고 2계층(Trajectory + RAGAS Outcome) 메트릭을 산출합니다.
"""

import time
from typing import Any, Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd

from langchain_core.messages import ToolMessage
from langchain.agents import create_agent
from langgraph.checkpoint.memory import MemorySaver

from app.utils.context import AgentContext
from app.middleware import (
    RAGToolCorrectionMiddleware,
    RAGSelfCorrectionMiddleware,
    RAGEvalHarnessMiddleware,
)


def evaluate_single_benchmark_case(
    item: Dict[str, Any],
    tools: List[Any],
    llm: Any,
    judge_llm: Any,
    naive_agent: Optional[Any] = None,
) -> Dict[str, Any]:
    """단일 골든 케이스에 대해 Naive vs Harnessed Agent를 실행하고 정량 지표를 채점합니다."""
    q_id = item["id"]
    query = item["question"]
    gt = item["ground_truth"]

    # ── A. Naive Agent 실행 및 평가 ──
    if naive_agent is None:
        naive_agent = create_agent(
            model=llm,
            tools=tools,
            checkpointer=MemorySaver(),
            middleware=[],
            context_schema=AgentContext,
        )

    cfg_naive = {"configurable": {"thread_id": f"bench_naive_{q_id}_{int(time.time()*1000)}"}}
    t0_n = time.time()
    resp_naive = naive_agent.invoke({"messages": [{"role": "user", "content": query}]}, config=cfg_naive)
    naive_dur = int((time.time() - t0_n) * 1000)

    naive_eval_mw = RAGEvalHarnessMiddleware(judge_llm=judge_llm, verbose=False)
    class DummyRuntime: ground_truth = gt
    naive_eval_mw.before_agent({})
    for m in resp_naive["messages"]:
        if isinstance(m, ToolMessage):
            naive_eval_mw.active_trajectory.append({
                "tool_name": getattr(m, "name", "tool"),
                "arguments": {},
                "latency_ms": 100
            })
    naive_eval_mw.after_agent({"messages": resp_naive["messages"]}, runtime=DummyRuntime())
    n_res = naive_eval_mw.last_result

    # ── B. Harnessed Agent 실행 및 평가 (스레드별 독립 미들웨어 인스턴스) ──
    t_mw = RAGToolCorrectionMiddleware(llm=llm, enable_auto_retry=True, max_session_rewrites=3, verbose=False)
    s_mw = RAGSelfCorrectionMiddleware(judge_llm=judge_llm, min_groundedness_score=0.70, max_retries=1, verbose=False)
    e_mw = RAGEvalHarnessMiddleware(judge_llm=judge_llm, verbose=False)

    thread_agent = create_agent(
        model=llm,
        tools=tools,
        checkpointer=MemorySaver(),
        middleware=[t_mw, s_mw, e_mw],
        context_schema=AgentContext,
    )

    cfg_harnessed = {"configurable": {"thread_id": f"bench_harness_{q_id}_{int(time.time()*1000)}"}}
    class HarnessRuntime: ground_truth = gt
    t0_h = time.time()
    resp_harnessed = thread_agent.invoke({"messages": [{"role": "user", "content": query}]}, config=cfg_harnessed)
    h_dur = int((time.time() - t0_h) * 1000)
    h_res = e_mw.last_result

    n_comp = n_res.composite_score if n_res else 0.0
    h_comp = h_res.composite_score if h_res else 0.0

    return {
        "ID": q_id,
        "Domain": item.get("domain", "general"),
        "Naive_Faithfulness": n_res.outcome_eval.faithfulness if n_res else 0.0,
        "Harness_Faithfulness": h_res.outcome_eval.faithfulness if h_res else 0.0,
        "Naive_Relevance": n_res.outcome_eval.answer_relevance if n_res else 0.0,
        "Harness_Relevance": h_res.outcome_eval.answer_relevance if h_res else 0.0,
        "Naive_TrajScore": n_res.trajectory_eval.trajectory_score if n_res else 0.0,
        "Harness_TrajScore": h_res.trajectory_eval.trajectory_score if h_res else 0.0,
        "Naive_Composite": n_comp,
        "Harness_Composite": h_comp,
        "Naive_Latency_ms": naive_dur,
        "Harness_Latency_ms": h_dur,
    }


def run_parallel_benchmark(
    golden_dataset: List[Dict[str, Any]],
    tools: List[Any],
    llm: Any,
    judge_llm: Any,
    max_workers: int = 5,
    naive_agent: Optional[Any] = None,
    verbose: bool = True,
) -> pd.DataFrame:
    """
    골든 데이터셋에 대해 ThreadPoolExecutor 기반의 고속 병렬 벤치마크를 수행하고
    결과 DataFrame을 반환합니다.
    """
    if verbose:
        print(f"🚀 {len(golden_dataset)}개 골든 케이스 고속 병렬 벤치마크 평가 시작 (ThreadPoolExecutor max_workers={max_workers})...\n", flush=True)
    t_bench_start = time.time()

    benchmark_records = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(
                evaluate_single_benchmark_case,
                item=item,
                tools=tools,
                llm=llm,
                judge_llm=judge_llm,
                naive_agent=naive_agent,
            )
            for item in golden_dataset
        ]
        for f in as_completed(futures):
            res = f.result()
            benchmark_records.append(res)
            if verbose:
                delta = "+" if res["Harness_Composite"] > res["Naive_Composite"] else ("-" if res["Harness_Composite"] < res["Naive_Composite"] else "=")
                print(
                    f"  ⚡ [{res['ID']}] 완료 (Composite: Naive {res['Naive_Composite']:.2f} vs Harness {res['Harness_Composite']:.2f} [{delta}])",
                    flush=True
                )

    benchmark_records.sort(key=lambda x: x["ID"])
    df_results = pd.DataFrame(benchmark_records)
    total_bench_dur = time.time() - t_bench_start

    if verbose:
        print(f"\n🎉 {len(golden_dataset)}개 문항 병렬 벤치마크 완료! (총 소요 시간: {total_bench_dur:.1f}초)\n", flush=True)

    return df_results
