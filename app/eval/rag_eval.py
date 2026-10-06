"""
app/eval/rag_eval.py
====================
오프라인 평가 하네스 러너 (노트북 4와 CLI 공용)

골든 데이터셋으로 app의 에이전트를 실행하고, 과정(Trajectory)과 결과(Outcome)를 2계층으로 채점한 뒤
실패 유형을 분류합니다. 결과는 artifacts/eval_runs/에 JSON으로 저장되어 다음 실행과 비교할 수 있습니다.

    평가 실행 → 실패 분석 → 도구/프롬프트/인덱스 수정 → 재평가 (회귀 확인)

사용 예:
  python -m app.eval.rag_eval --agent tool_rag_agent
  python -m app.eval.rag_eval --agent tool_rag_agent --ids term-01 bok-01
  python -m app.eval.rag_eval --agent tool_rag_agent --compare artifacts/eval_runs/tool_rag_agent_20261003_101500.json
"""

import os
import re
import sys
import json
import time
import uuid
import asyncio
import argparse
import importlib
from datetime import datetime
from typing import Any, Dict, List, Optional

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"), override=True)

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.errors import GraphRecursionError

from app.middleware.rag_eval_harness import (
    RAGEvalHarnessMiddleware,
    extract_last_ai_answer,
    extract_tool_contexts,
)

GOLDEN_PATH = os.path.join(PROJECT_ROOT, "data/eval/golden_eval_dataset.json")
REPORT_DIR = os.path.join(PROJECT_ROOT, "artifacts/eval_runs")
PASS_THRESHOLD = 0.75
# 채점기는 평가 대상 에이전트(gemini)와 다른 계열의 모델을 써서 자기 답을 후하게 채점하는 편향을 줄입니다.
JUDGE_MODEL = "gpt-5.4-mini"
# 한 문항의 LangGraph 실행 단계 한도 (도구 호출 약 20회). 넘으면 "호출 한도 초과"로 기록하고 다음 문항으로 넘어갑니다.
RECURSION_LIMIT = 40
NO_ANSWER = "(호출 한도 초과로 최종 답변을 생성하지 못함)"


def load_golden(path: str = GOLDEN_PATH, ids: Optional[List[str]] = None) -> List[dict]:
    with open(path, "r", encoding="utf-8") as f:
        cases = json.load(f)
    return [c for c in cases if not ids or c["id"] in ids]


# 청크 앞의 문맥 헤더(문서명 + 전체 목차)는 검색용 정보라, 채점기에 보여 줄 때는 걷어 내고 본문을 보여 줍니다.
_CONTEXT_HEADER = re.compile(r"--- Document Context Header ---.*?-{20,}", re.S)
JUDGE_PREVIEW_CHARS = 1500   # 검색 청크 2~3개(각 500~600자) 본문이 모두 들어가는 길이


def preview_for_judge(text: str, limit: int = JUDGE_PREVIEW_CHARS) -> str:
    """도구 결과를 과정 채점기용 발췌로 만듭니다: 문맥 헤더 제거 → 빈 줄 정리 → 앞 limit자."""
    body = re.sub(r"\n\s*\n+", "\n", _CONTEXT_HEADER.sub("", text)).strip()
    return body if len(body) <= limit else body[:limit] + " …(이하 생략)"


def trajectory_from_messages(messages: list) -> List[Dict[str, Any]]:
    """AIMessage의 tool_calls와 ToolMessage 결과를 짝지어 도구 호출 궤적을 만듭니다.

    response_snippet: 화면 표시용 앞 200자 (출처 헤더 확인용)
    result_preview:   과정 채점기에 넘기는 본문 발췌 (문맥 헤더 제거, 최대 JUDGE_PREVIEW_CHARS자)
    """
    results = {m.tool_call_id: str(m.content) for m in messages if isinstance(m, ToolMessage)}
    trajectory = []
    for m in messages:
        if isinstance(m, AIMessage):
            for tc in m.tool_calls or []:
                raw = results.get(tc.get("id"), "")
                trajectory.append({
                    "tool_name": tc["name"],
                    "arguments": tc["args"],
                    "response_snippet": raw[:200],
                    "result_preview": preview_for_judge(raw),
                })
    return trajectory


# 진단 규칙: (진단명, 점수 위치, 지표, 기준, 의심할 계층)
# 순서는 에이전트 처리 흐름(도구 선택 → 검색 → 생성)을 따릅니다.
# 여러 항목이 동시에 걸릴 수 있으며(다중 진단), 순서는 "먼저 살펴볼 곳"을 정할 때만 씁니다.
DIAGNOSTIC_RULES = [
    ("도구 선택",     "trajectory", "tool_selection_accuracy", 0.6, "도구 설명(description), 시스템 프롬프트"),
    ("검색 품질",     "outcome",    "context_recall",          0.6, "검색 쿼리, 인덱스(청킹/헤더/메타데이터), 도구 인자"),
    ("근거 없는 생성", "outcome",    "faithfulness",            0.7, "답변 원칙, 출처 인용 지침"),
    ("오답",         "outcome",    "answer_correctness",      0.7, "검색 결과 해석, 계산/비교 지침"),
    ("질문 이해",     "outcome",    "answer_relevance",        0.7, "용어 사전, 질의 재작성"),
    ("비효율 호출",   "trajectory", "step_economy_score",      0.6, "도구 설명의 호출 지침, 도구 인자"),
]


def diagnose(traj, outcome) -> List[str]:
    """기준에 못 미친 진단 항목을 모두 반환합니다 (다중 진단).

    통과한 문항이라도 기준 미달 지표가 있으면 표시합니다. 첫 항목은 처리 흐름상 가장 앞단이므로
    "먼저 살펴볼 곳"이지만, 가장 중요한 원인이라는 뜻은 아닙니다.
    """
    scores = {"trajectory": traj, "outcome": outcome}
    return [name for name, where, metric, threshold, _ in DIAGNOSTIC_RULES
            if getattr(scores[where], metric) < threshold]


async def run_case(agent, case: dict) -> dict:
    """에이전트를 한 문항에 대해 실행하고 궤적, 답변, 컨텍스트를 수집합니다.

    에이전트가 헛돌아 실행 한도(RECURSION_LIMIT)에 걸려도 평가 전체를 멈추지 않습니다.
    체크포인터에 남은 대화로 지금까지의 궤적을 채점하고, 답변은 없는 것으로 처리합니다.
    """
    started = time.time()
    config = {"configurable": {"thread_id": f"eval-{case['id']}-{uuid.uuid4().hex[:6]}"}, "recursion_limit": RECURSION_LIMIT}
    hit_limit = False
    try:
        result = await agent.ainvoke({"messages": [HumanMessage(content=case["question"])]}, config)
        messages = result["messages"]
    except GraphRecursionError:
        hit_limit = True
        try:
            state = await agent.aget_state(config)
            messages = state.values.get("messages", [])
        except Exception:   # 체크포인터가 없으면 궤적을 복원할 수 없음
            messages = []
    return {
        "trajectory": trajectory_from_messages(messages),
        "answer": NO_ANSWER if hit_limit else extract_last_ai_answer(messages),
        "contexts": extract_tool_contexts(messages),
        "duration_s": round(time.time() - started, 1),
        "hit_limit": hit_limit,
    }


def score_case(case: dict, record: dict, harness: RAGEvalHarnessMiddleware) -> dict:
    """2계층(과정 40% + 결과 60%)으로 채점하고 실패 유형을 붙입니다."""
    traj = harness.evaluate_trajectory(case["question"], case["target_tools"], record["trajectory"], record["answer"])
    outcome = harness.evaluate_outcome(case["question"], case["ground_truth"], record["contexts"], record["answer"])
    composite = round(0.40 * traj.trajectory_score + 0.60 * outcome.outcome_score, 3)
    return {
        "id": case["id"],
        "category": case["category"],
        "composite": composite,
        "passed": composite >= PASS_THRESHOLD,
        "trajectory": round(traj.trajectory_score, 2),
        "outcome": round(outcome.outcome_score, 2),
        "correctness": round(outcome.answer_correctness, 2),
        "faithfulness": round(outcome.faithfulness, 2),
        "relevance": round(outcome.answer_relevance, 2),
        "recall": round(outcome.context_recall, 2),
        "tool_selection": round(traj.tool_selection_accuracy, 2),
        "step_economy": round(traj.step_economy_score, 2),
        "tool_calls": len(record["trajectory"]),
        "tools": [t["tool_name"] for t in record["trajectory"]],
        "duration_s": record["duration_s"],
        "diagnoses": diagnose(traj, outcome) + (["호출 한도 초과"] if record.get("hit_limit") else []),
        "critique": traj.critique,
        "question": case["question"],
        "answer": record["answer"],
    }


async def evaluate_agent(agent, cases: List[dict], judge_llm=None, concurrency: int = 3, verbose: bool = True) -> List[dict]:
    """골든 문항들을 동시에 실행/채점합니다. 채점 LLM 오류는 고정 점수로 숨기지 않고 그대로 드러냅니다."""
    if judge_llm is None:
        from app.utils import init_chat_model
        judge_llm = init_chat_model(model=JUDGE_MODEL, temperature=0.0)
    harness = RAGEvalHarnessMiddleware(judge_llm=judge_llm, verbose=False, strict=True)
    semaphore = asyncio.Semaphore(concurrency)

    async def one(case):
        async with semaphore:
            record = await run_case(agent, case)
            row = await asyncio.to_thread(score_case, case, record, harness)
            if verbose:
                verdict = "통과" if row["passed"] else "미달"
                print(f"  ✔ {row['id']:<8} 종합 {row['composite']:.2f} ({verdict}) | 도구 호출 {row['tool_calls']}회")
            return row

    rows = await asyncio.gather(*(one(c) for c in cases))
    return sorted(rows, key=lambda r: r["composite"])


async def load_app_agent(name: str):
    """app/agents/<name> 패키지의 팩토리로 서비스용 에이전트를 만듭니다."""
    module = importlib.import_module(f"app.agents.{name}")
    return await module.create_agent_executor()


# 결과 표의 컬럼: (행 키, 표시 이름)
RESULT_COLUMNS = [
    ("id", "문항"),
    ("category", "유형"),
    ("composite", "종합"),
    ("trajectory", "과정"),
    ("outcome", "결과"),
    ("correctness", "정답 일치"),
    ("faithfulness", "근거 충실"),
    ("recall", "검색 재현"),
    ("tool_selection", "도구 선택"),
    ("step_economy", "호출 효율"),
    ("tool_calls", "호출 수"),
    ("duration_s", "소요(s)"),
    ("verdict", "판정"),
    ("diagnosis", "진단 (기준 미달 지표)"),
]


def summary_line(rows: List[dict]) -> str:
    """평가 전체를 한 줄로 요약합니다."""
    n = len(rows)
    passed = sum(r["passed"] for r in rows)
    mean = lambda k: sum(r[k] for r in rows) / n
    return (f"평균 종합 점수 {mean('composite'):.3f} | 통과 {passed}/{n} (기준 {PASS_THRESHOLD}) | "
            f"평균 도구 호출 {mean('tool_calls'):.1f}회 | 평균 소요 {mean('duration_s'):.1f}s")


def results_table(rows: List[dict]):
    """문항별 점수 표 (DataFrame). 점수가 낮은 문항부터 정렬합니다."""
    import pandas as pd
    df = pd.DataFrame(rows).sort_values("composite")
    df["verdict"] = df["passed"].map({True: "통과", False: "미달"})
    df["diagnosis"] = df["diagnoses"].map(lambda d: ", ".join(d) if d else "-")
    keys, names = zip(*RESULT_COLUMNS)
    return df[list(keys)].rename(columns=dict(RESULT_COLUMNS)).reset_index(drop=True)


def diagnosis_table(rows: List[dict]):
    """진단 항목별로 기준 미달 문항을 집계합니다 (DataFrame).

    한 문항이 여러 항목에 동시에 걸릴 수 있으므로 문항 수의 합은 전체 문항 수와 다를 수 있습니다.
    통과한 문항의 기준 미달 지표도 포함합니다.
    """
    import pandas as pd
    table = []
    for name, where, metric, threshold, layer in DIAGNOSTIC_RULES:
        hits = [r["id"] for r in sorted(rows, key=lambda x: x["id"]) if name in r["diagnoses"]]
        table.append({"진단": name, "지표 (기준)": f"{metric} < {threshold}", "해당 문항 수": len(hits),
                      "해당 문항": ", ".join(hits) or "-", "의심할 계층": layer})
    hits = [r["id"] for r in sorted(rows, key=lambda x: x["id"]) if "호출 한도 초과" in r["diagnoses"]]
    table.append({"진단": "호출 한도 초과", "지표 (기준)": f"실행 단계 > {RECURSION_LIMIT}", "해당 문항 수": len(hits),
                  "해당 문항": ", ".join(hits) or "-", "의심할 계층": "도구 인자, 호출 지침 (같은 검색 반복)"})
    return pd.DataFrame(table)


def summarize(rows: List[dict]) -> str:
    """CLI 출력용 텍스트 요약 (노트북에서는 results_table / diagnosis_table을 display로 보는 것을 권장)."""
    return (summary_line(rows) + "\n\n" + results_table(rows).to_string(index=False)
            + "\n\n" + diagnosis_table(rows).to_string(index=False))


def compare_table(before: List[dict], after: List[dict]):
    """두 실행의 문항별 종합 점수, 호출 수, 소요 시간을 비교합니다 (DataFrame). 개선과 회귀를 함께 봅니다."""
    import pandas as pd
    prev = {r["id"]: r for r in before}
    table = []
    for r in sorted(after, key=lambda x: x["id"]):
        if r["id"] not in prev:
            continue
        p = prev[r["id"]]
        delta = round(r["composite"] - p["composite"], 2)
        table.append({
            "문항": r["id"],
            "종합 (전)": p["composite"], "종합 (후)": r["composite"], "변화": delta,
            "호출 수 (전)": p["tool_calls"], "호출 수 (후)": r["tool_calls"],
            "소요(s) (전)": p["duration_s"], "소요(s) (후)": r["duration_s"],
            "판정": "개선" if delta >= 0.05 else ("회귀 ⚠️" if delta <= -0.05 else "유지"),
        })
    return pd.DataFrame(table)


def save_report(rows: List[dict], agent_name: str) -> str:
    os.makedirs(REPORT_DIR, exist_ok=True)
    path = os.path.join(REPORT_DIR, f"{agent_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"agent": agent_name, "created_at": datetime.now().isoformat(), "rows": rows}, f, ensure_ascii=False, indent=2)
    return path


def compare_reports(previous_path: str, rows: List[dict]) -> str:
    """저장된 이전 리포트와 비교한 표를 텍스트로 반환합니다 (CLI용)."""
    with open(previous_path, "r", encoding="utf-8") as f:
        before = json.load(f)["rows"]
    return compare_table(before, rows).to_string(index=False)


async def _main(args):
    cases = load_golden(ids=args.ids)
    print(f"🧪 {args.agent} 평가 시작: {len(cases)}문항")
    agent = await load_app_agent(args.agent)
    try:
        rows = await evaluate_agent(agent, cases, concurrency=args.concurrency)
    finally:
        conn = getattr(getattr(agent, "checkpointer", None), "conn", None)
        if conn is not None:
            await conn.close()

    print("\n" + summarize(rows))
    path = save_report(rows, args.agent)
    print(f"\n💾 리포트 저장: {os.path.relpath(path, PROJECT_ROOT)}")
    if args.compare:
        print("\n📊 이전 실행과 비교\n" + compare_reports(args.compare, rows))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Agentic RAG offline evaluation harness")
    parser.add_argument("--agent", default="tool_rag_agent", help="app/agents/ 아래 에이전트 이름")
    parser.add_argument("--ids", nargs="*", default=None, help="평가할 문항 id (생략 시 전체)")
    parser.add_argument("--concurrency", type=int, default=3, help="동시 실행 문항 수")
    parser.add_argument("--compare", default=None, help="비교할 이전 리포트 JSON 경로")
    asyncio.run(_main(parser.parse_args()))
