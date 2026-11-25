"""Regression tests for upgraded FastAPI job lifecycle, observability integration, client, and Chainlit helpers."""

import asyncio
import gc
import inspect
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool

import app.server as server_mod
import app.utils.workspace as workspace_mod
from app.client import AsyncAgentClient
from app.context import AgentContext
from app.middleware.observability import AgentLogTracer


class ServerJobsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.users_root = Path(self.tmp.name) / "users"
        self.users_patch = patch.object(workspace_mod, "USERS_ROOT_DIR", self.users_root)
        self.users_patch.start()
        self.addCleanup(self.users_patch.stop)

    async def test_server_job_cancellation_suppresses_wakeup_and_records_tracer(self):
        """submit_agent_job -> cancel_job 시 태스크 취소, wakeup 억제, Tracer 기록, 경고 없는 cleanup 및 409 재사용 차단을 검증."""
        entered = asyncio.Event()
        sup_calls = 0

        @tool
        async def slow_crawl(url: str) -> str:
            """취소 테스트용 느린 도구."""
            entered.set()
            await asyncio.sleep(10.0)
            return url

        class CancelTestModel(BaseChatModel):
            is_sup: bool = False

            @property
            def _llm_type(self) -> str:
                return "cancel-test"

            def bind_tools(self, tools, **kwargs):
                return self

            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                nonlocal sup_calls
                if self.is_sup:
                    sup_calls += 1
                    return ChatResult(generations=[ChatGeneration(message=AIMessage(content="wakeup"))])
                return ChatResult(
                    generations=[
                        ChatGeneration(
                            message=AIMessage(
                                content="Crawling target",
                                tool_calls=[
                                    {
                                        "name": "slow_crawl",
                                        "args": {"url": "https://example.com"},
                                        "id": "call_slow_1",
                                        "type": "tool_call",
                                    }
                                ],
                            )
                        )
                    ]
                )

            async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
                return self._generate(messages, stop, run_manager, **kwargs)

        tracer = AgentLogTracer(disk_enabled=False)
        sub_executor = create_agent(
            model=CancelTestModel(is_sup=False),
            tools=[slow_crawl],
            middleware=[tracer],
            context_schema=AgentContext,
        )
        sup_executor = create_agent(
            model=CancelTestModel(is_sup=True),
            tools=[],
            context_schema=AgentContext,
        )
        fake_req = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    agents={"tool_rag_agent": sub_executor, "supervisor": sup_executor},
                    load_lock=asyncio.Lock(),
                )
            )
        )

        created_job_ids: list[str] = []
        try:
            with patch.object(
                server_mod,
                "api_list_agents",
                return_value=[
                    {"name": "tool_rag_agent", "roles": ["main", "sub"]},
                    {"name": "supervisor", "roles": ["main"]},
                ],
            ), patch.object(server_mod, "register_subagent_thread", AsyncMock(return_value=None)):
                submitted = await server_mod.submit_agent_job(
                    "tool_rag_agent",
                    server_mod.JobSubmitInput(
                        message="crawl",
                        parent_thread_id="sup_srv_can",
                        callback_agent="supervisor",
                        callback_thread_id="sup_srv_can",
                        user_id="u_can",
                    ),
                    fake_req,
                )
                job_id = submitted["job_id"]
                sub_tid = submitted["sub_thread_id"]
                created_job_ids.append(job_id)

                self.assertIn(job_id, server_mod.job_tasks)
                await asyncio.wait_for(entered.wait(), timeout=3.0)

                status_before = await server_mod.get_job_status(job_id)
                self.assertEqual(status_before["status"], "RUNNING")
                self.assertEqual(status_before["progress"]["phase"], "running_tool")
                self.assertIn("slow_crawl", status_before["progress_report"])

                with self.assertNoLogs("LLMOps_Server", level="WARNING"):
                    cleaned = await server_mod._cleanup_cancelled_subagent_resources("dummy_tid")
                    self.assertEqual(cleaned, 0)
                    cancel_res = await server_mod.cancel_job(
                        job_id,
                        server_mod.JobCancelInput(reason="Stop crawling"),
                    )

                self.assertTrue(cancel_res["cancelled"])
                self.assertEqual(cancel_res["status"], "CANCELLED")
                self.assertEqual(cancel_res["wakeup_status"], "SKIPPED")
                self.assertEqual(sup_calls, 0)

                snap = tracer.get_progress_snapshot(sub_tid)
                self.assertEqual(snap["status"], "CANCELLED")
                self.assertEqual(snap["active_tools"], [])

                with self.assertRaises(HTTPException) as ctx:
                    await server_mod.submit_agent_job(
                        "tool_rag_agent",
                        server_mod.JobSubmitInput(
                            message="retry same cancelled thread",
                            thread_id=sub_tid,
                            parent_thread_id="sup_srv_can",
                            callback_agent="supervisor",
                            callback_thread_id="sup_srv_can",
                            user_id="u_can",
                        ),
                        fake_req,
                    )
                self.assertEqual(ctx.exception.status_code, 409)
        finally:
            for jid in created_job_ids:
                task = server_mod.job_tasks.pop(jid, None)
                if task and not task.done():
                    task.cancel()
                server_mod.job_store.pop(jid, None)

    async def test_server_cancel_ignores_teardown_exception_and_suppresses_failed_wakeup(self):
        """취소 중 도구가 일반 예외를 던져도 CANCELLED를 유지하고 FAILED Wakeup을 억제하는지 검증."""
        entered = asyncio.Event()
        sup_calls = 0

        @tool
        async def teardown_error_tool(url: str) -> str:
            """취소 정리 중 일반 예외를 발생시키는 도구."""
            entered.set()
            try:
                await asyncio.sleep(10.0)
            except asyncio.CancelledError:
                raise RuntimeError("TargetClosedError: page closed during teardown")
            return url

        class TeardownCancelModel(BaseChatModel):
            is_sup: bool = False

            @property
            def _llm_type(self) -> str:
                return "teardown-cancel"

            def bind_tools(self, tools, **kwargs):
                return self

            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                nonlocal sup_calls
                if self.is_sup:
                    sup_calls += 1
                    return ChatResult(generations=[ChatGeneration(message=AIMessage(content="wakeup"))])
                return ChatResult(
                    generations=[
                        ChatGeneration(
                            message=AIMessage(
                                content="Running tool",
                                tool_calls=[
                                    {
                                        "name": "teardown_error_tool",
                                        "args": {"url": "https://example.com"},
                                        "id": "call_td_1",
                                        "type": "tool_call",
                                    }
                                ],
                            )
                        )
                    ]
                )

            async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
                return self._generate(messages, stop, run_manager, **kwargs)

        sub_executor = create_agent(
            model=TeardownCancelModel(is_sup=False),
            tools=[teardown_error_tool],
            context_schema=AgentContext,
        )
        sup_executor = create_agent(
            model=TeardownCancelModel(is_sup=True),
            tools=[],
            context_schema=AgentContext,
        )
        fake_req = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    agents={"tool_rag_agent": sub_executor, "supervisor": sup_executor},
                    load_lock=asyncio.Lock(),
                )
            )
        )

        created_job_ids: list[str] = []
        try:
            with patch.object(
                server_mod,
                "api_list_agents",
                return_value=[
                    {"name": "tool_rag_agent", "roles": ["main", "sub"]},
                    {"name": "supervisor", "roles": ["main"]},
                ],
            ), patch.object(server_mod, "register_subagent_thread", AsyncMock(return_value=None)):
                submitted = await server_mod.submit_agent_job(
                    "tool_rag_agent",
                    server_mod.JobSubmitInput(
                        message="crawl",
                        parent_thread_id="sup_srv_td",
                        callback_agent="supervisor",
                        callback_thread_id="sup_srv_td",
                        user_id="u_td",
                    ),
                    fake_req,
                )
                jid = submitted["job_id"]
                created_job_ids.append(jid)
                await asyncio.wait_for(entered.wait(), timeout=3.0)

                cancel_res = await server_mod.cancel_job(
                    jid,
                    server_mod.JobCancelInput(reason="User cancelled during teardown"),
                )
                self.assertTrue(cancel_res["cancelled"])
                self.assertEqual(cancel_res["status"], "CANCELLED")
                self.assertEqual(server_mod.job_store[jid]["status"], "CANCELLED")
                self.assertEqual(server_mod.job_store[jid]["wakeup_status"], "SKIPPED")
                self.assertIsNone(server_mod.job_store[jid].get("error"))
                self.assertEqual(sup_calls, 0)
        finally:
            for jid in created_job_ids:
                task = server_mod.job_tasks.pop(jid, None)
                if task and not task.done():
                    task.cancel()
                server_mod.job_store.pop(jid, None)

    async def test_server_failed_job_triggers_reactive_wakeup_and_consecutive_failure_guard(self):
        """실패(FAILED) 시 Reactive Wakeup(텔레메트리 포함) 발화 및 연속 3회 초과 실패 억제/성공 후 리셋 검증."""
        should_fail = True
        sup_prompts: list[str] = []

        class FailingSubModel(BaseChatModel):
            @property
            def _llm_type(self) -> str:
                return "failing-sub"

            def bind_tools(self, tools, **kwargs):
                return self

            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                if should_fail:
                    raise RuntimeError("boom network 503")
                return ChatResult(generations=[ChatGeneration(message=AIMessage(content="recovered ok"))])

            async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
                return self._generate(messages, stop, run_manager, **kwargs)

        class SupSpyModel(BaseChatModel):
            @property
            def _llm_type(self) -> str:
                return "sup-spy"

            def bind_tools(self, tools, **kwargs):
                return self

            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                sup_prompts.append(str(messages[-1].content))
                return ChatResult(generations=[ChatGeneration(message=AIMessage(content="handled failure"))])

            async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
                return self._generate(messages, stop, run_manager, **kwargs)

        tracer = AgentLogTracer(disk_enabled=False)
        sub_executor = create_agent(
            model=FailingSubModel(),
            tools=[],
            middleware=[tracer],
            context_schema=AgentContext,
        )
        sup_executor = create_agent(
            model=SupSpyModel(),
            tools=[],
            context_schema=AgentContext,
        )
        fake_app = SimpleNamespace(
            state=SimpleNamespace(
                agents={"tool_rag_agent": sub_executor, "supervisor": sup_executor},
                load_lock=asyncio.Lock(),
            )
        )

        sup_tid = "sup_fail_guard_01"
        job_ids = [f"job_fail_{i}" for i in range(1, 7)]
        try:
            async def _run_one(jid: str, sub_tid: str):
                server_mod.job_store[jid] = {
                    "job_id": jid,
                    "agent_name": "tool_rag_agent",
                    "sub_thread_id": sub_tid,
                    "callback_thread_id": sup_tid,
                    "parent_thread_id": sup_tid,
                    "user_id": "test_u",
                    "status": "SUBMITTED",
                }
                inp = server_mod.JobSubmitInput(
                    message=f"task {jid}",
                    thread_id=sub_tid,
                    parent_thread_id=sup_tid,
                    callback_agent="supervisor",
                    callback_thread_id=sup_tid,
                    user_id="test_u",
                )
                ctx = AgentContext(
                    agent_name="tool_rag_agent",
                    session_id=sub_tid,
                    parent_session_id=sup_tid,
                    user_id="test_u",
                )
                cfg = {"configurable": {"thread_id": sub_tid, "parent_thread_id": sup_tid, "user_id": "test_u"}}
                await server_mod._run_agent_job(jid, "tool_rag_agent", inp, ctx, cfg, fake_app)

            for idx in range(3):
                await _run_one(job_ids[idx], f"{sup_tid}_rag_{idx}")
                self.assertEqual(server_mod.job_store[job_ids[idx]]["status"], "FAILED")
                self.assertEqual(server_mod.job_store[job_ids[idx]]["wakeup_status"], "COMPLETED")

            self.assertEqual(len(sup_prompts), 3)
            self.assertIn("[SYSTEM NOTIFICATION: BACKGROUND TASK FAILED]", sup_prompts[0])
            self.assertIn("Execution Telemetry:", sup_prompts[0])
            self.assertIn("boom network 503", sup_prompts[0])
            self.assertIn("1/3", sup_prompts[0])
            self.assertIn("3/3", sup_prompts[2])

            await _run_one(job_ids[3], f"{sup_tid}_rag_3")
            self.assertEqual(server_mod.job_store[job_ids[3]]["status"], "FAILED")
            self.assertEqual(server_mod.job_store[job_ids[3]]["wakeup_status"], "SKIPPED")
            self.assertIn("Suppressed reactive wakeup", server_mod.job_store[job_ids[3]]["wakeup_error"])
            self.assertEqual(len(sup_prompts), 3)

            should_fail = False
            await _run_one(job_ids[4], f"{sup_tid}_rag_4")
            self.assertEqual(server_mod.job_store[job_ids[4]]["status"], "SUCCESS")
            self.assertEqual(server_mod.job_store[job_ids[4]]["wakeup_status"], "COMPLETED")
            self.assertEqual(len(sup_prompts), 4)

            should_fail = True
            await _run_one(job_ids[5], f"{sup_tid}_rag_5")
            self.assertEqual(server_mod.job_store[job_ids[5]]["status"], "FAILED")
            self.assertEqual(server_mod.job_store[job_ids[5]]["wakeup_status"], "COMPLETED")
            self.assertEqual(len(sup_prompts), 5)
            self.assertIn("1/3", sup_prompts[4])
        finally:
            for jid in job_ids:
                server_mod.job_store.pop(jid, None)

    async def test_server_job_caller_ownership_403_and_ownerless_cli_job(self):
        """다른 세션 caller_thread_id의 403 차단과 소유자 없는 CLI Job 허용 동작을 검증."""
        srv_jid = "job_srv_own_1"
        cli_jid = "job_srv_cli_no_owner"
        server_mod.job_store[srv_jid] = {
            "job_id": srv_jid,
            "agent_name": "tool_rag_agent",
            "sub_thread_id": "session_owner_a_rag_2222",
            "callback_thread_id": "session_owner_a",
            "parent_thread_id": "session_owner_a",
            "user_id": "test_u",
            "status": "RUNNING",
        }
        server_mod.job_store[cli_jid] = {
            "job_id": cli_jid,
            "agent_name": "tool_rag_agent",
            "sub_thread_id": "cli_rag_3333",
            "callback_thread_id": None,
            "parent_thread_id": None,
            "user_id": "test_u",
            "status": "RUNNING",
        }
        try:
            cli_srv = await server_mod.get_job_status(cli_jid, caller_thread_id="session_other_b")
            self.assertEqual(cli_srv["job_id"], cli_jid)

            with self.assertRaises(HTTPException) as ctx_get:
                await server_mod.get_job_status(srv_jid, caller_thread_id="session_other_b")
            self.assertEqual(ctx_get.exception.status_code, 403)

            with self.assertRaises(HTTPException) as ctx_can:
                await server_mod.cancel_job(
                    srv_jid,
                    server_mod.JobCancelInput(reason="steal", caller_thread_id="session_other_b"),
                )
            self.assertEqual(ctx_can.exception.status_code, 403)
            self.assertEqual(server_mod.job_store[srv_jid]["status"], "RUNNING")

            ok_srv = await server_mod.get_job_status(srv_jid, caller_thread_id="session_owner_a")
            self.assertEqual(ok_srv["job_id"], srv_jid)
            ok_srv_can = await server_mod.cancel_job(
                srv_jid,
                server_mod.JobCancelInput(reason="owner", caller_thread_id="session_owner_a"),
            )
            self.assertTrue(ok_srv_can["cancelled"])
        finally:
            server_mod.job_store.pop(srv_jid, None)
            server_mod.job_store.pop(cli_jid, None)

    async def test_same_sub_thread_id_progress_isolated_across_sequential_jobs(self):
        """동일 sub_thread_id 연속/대기 실행 시 각 Job이 자신의 실행 스냅샷만 소유하는지 검증."""
        tracer = AgentLogTracer(disk_enabled=False)
        sup_tid = "sup_seq_iso_01"
        sub_tid = f"{sup_tid}_rag_1111"

        tracer.start_turn(sub_tid, "turn 1")
        t1_ts = tracer._active_runs[sub_tid]["start_time"]

        j1_id = "job_seq_1"
        j2_id = "job_seq_2"
        server_mod.job_store[j1_id] = {
            "job_id": j1_id,
            "agent_name": "tool_rag_agent",
            "sub_thread_id": sub_tid,
            "callback_thread_id": sup_tid,
            "parent_thread_id": sup_tid,
            "user_id": "test_u",
            "status": "RUNNING",
            "created_at_ts": t1_ts - 0.1,
            "execution_started_at_ts": t1_ts - 0.01,
        }
        server_mod.job_store[j2_id] = {
            "job_id": j2_id,
            "agent_name": "tool_rag_agent",
            "sub_thread_id": sub_tid,
            "callback_thread_id": sup_tid,
            "parent_thread_id": sup_tid,
            "user_id": "test_u",
            "status": "RUNNING",
            "created_at_ts": t1_ts + 1.0,
            "execution_started_at_ts": None,
        }
        try:
            # 1) job_1 RUNNING + job_2 락 대기 중: job_1만 턴 1 진행 상황 유지
            e1_running = server_mod._enrich_job_with_progress(server_mod.job_store[j1_id])
            e2_waiting = server_mod._enrich_job_with_progress(server_mod.job_store[j2_id])
            self.assertIn("progress", e1_running)
            self.assertEqual(e1_running["progress"]["status"], "RUNNING")
            self.assertEqual(e1_running["progress"]["turn_id"], 1)
            self.assertNotIn("progress", e2_waiting)

            # 2) 레이지 로딩 경합: job_2가 job_1 락 획득보다 먼저 생성됐더라도 대기 중이면 역전되지 않음
            server_mod.job_store[j2_id]["created_at_ts"] = t1_ts - 0.05
            e1_race = server_mod._enrich_job_with_progress(server_mod.job_store[j1_id])
            e2_race = server_mod._enrich_job_with_progress(server_mod.job_store[j2_id])
            self.assertIn("progress", e1_race)
            self.assertNotIn("progress", e2_race)

            # 3) job_1 SUCCESS + job_2 락 획득 직후 아직 턴 2 시작 전: job_1은 턴 1 유지, job_2는 비어 있음
            tracer.end_turn(final_response="t1 done", session_id=sub_tid)
            server_mod.job_store[j1_id]["status"] = "SUCCESS"
            server_mod.job_store[j2_id]["created_at_ts"] = t1_ts + 1.0
            server_mod.job_store[j2_id]["execution_started_at_ts"] = t1_ts + 1.0

            e1_done = server_mod._enrich_job_with_progress(server_mod.job_store[j1_id])
            e2_before = server_mod._enrich_job_with_progress(server_mod.job_store[j2_id])
            self.assertIn("progress", e1_done)
            self.assertEqual(e1_done["progress"]["status"], "SUCCESS")
            self.assertEqual(e1_done["progress"]["turn_id"], 1)
            self.assertNotIn("progress", e2_before)

            # 4) job_2가 턴 2 시작: 소유권이 job_2로 전환됨
            tracer.start_turn(sub_tid, "turn 2")
            tracer._active_runs[sub_tid]["start_time"] = t1_ts + 2.0

            e1_during_t2 = server_mod._enrich_job_with_progress(server_mod.job_store[j1_id])
            e2_during_t2 = server_mod._enrich_job_with_progress(server_mod.job_store[j2_id])
            self.assertNotIn("progress", e1_during_t2)
            self.assertIn("progress", e2_during_t2)
            self.assertEqual(e2_during_t2["progress"]["status"], "RUNNING")
            self.assertEqual(e2_during_t2["progress"]["turn_id"], 2)
        finally:
            server_mod.job_store.pop(j1_id, None)
            server_mod.job_store.pop(j2_id, None)

    async def test_session_job_list_skips_disk_reads_for_terminal_jobs_while_detail_uses_disk(self):
        """목록 조회(/jobs, /sessions/{tid}/jobs)는 완료 Job에 디스크 폴백을 타지 않고 상세 조회(/jobs/{id})만 읽는지 검증."""
        sup_tid = "sup_disk_skip_01"
        sub_tid = f"{sup_tid}_rag_2222"
        ws = workspace_mod.resolve_session_workspace(
            user_id="u_disk_skip",
            session_id=sub_tid,
            parent_session_id=sup_tid,
            subagent_role="tool_rag_agent",
            ensure_exists=True,
        )

        writer = AgentLogTracer(disk_enabled=True)
        writer.start_turn(sub_tid, "search policy")
        writer._active_runs[sub_tid]["user_id"] = "u_disk_skip"
        writer._active_runs[sub_tid]["parent_session_id"] = sup_tid
        writer._active_runs[sub_tid]["workspace_dir"] = ws.rel_root
        writer.end_turn(final_response="done", session_id=sub_tid)
        writer.flush()
        del writer
        gc.collect()

        jid = "job_disk_term_1"
        server_mod.job_store[jid] = {
            "job_id": jid,
            "agent_name": "tool_rag_agent",
            "sub_thread_id": sub_tid,
            "callback_thread_id": sup_tid,
            "parent_thread_id": sup_tid,
            "user_id": "u_disk_skip",
            "workspace_dir": ws.rel_root,
            "status": "SUCCESS",
        }
        try:
            with patch.object(
                AgentLogTracer,
                "_build_snapshot_from_disk",
                wraps=AgentLogTracer._build_snapshot_from_disk,
            ) as disk_spy:
                sess_jobs = await server_mod.list_session_jobs(sup_tid)
                all_jobs = await server_mod.list_jobs()
                self.assertEqual(disk_spy.call_count, 0)
                self.assertEqual(len(sess_jobs), 1)
                self.assertNotIn("progress", sess_jobs[0])
                matching_all = [j for j in all_jobs if j.get("job_id") == jid]
                self.assertNotIn("progress", matching_all[0])

                detail = await server_mod.get_job_status(jid)
                self.assertGreaterEqual(disk_spy.call_count, 1)
                self.assertIn("progress", detail)
                self.assertTrue(detail["progress"]["found"])
                self.assertEqual(detail["progress"]["source"], "disk")
        finally:
            server_mod.job_store.pop(jid, None)

    async def test_legacy_four_arg_run_agent_job_shim_resolves_context(self):
        """하위 호환: _run_agent_job(job_id, agent, input, app) 4인자 호출도 컨텍스트를 해석해 정상 실행되는지 검증."""
        sub_executor = create_agent(
            model=GenericFakeChatModel(messages=iter([AIMessage(content="[TASK REPORT]\n- Status: SUCCESS")])),
            tools=[],
            context_schema=AgentContext,
        )
        sup_executor = create_agent(
            model=GenericFakeChatModel(messages=iter([AIMessage(content="wakeup handled")])),
            tools=[],
            context_schema=AgentContext,
        )
        fake_app = SimpleNamespace(
            state=SimpleNamespace(
                agents={"tool_rag_agent": sub_executor, "supervisor": sup_executor},
                load_lock=asyncio.Lock(),
            )
        )
        jid = "job_legacy_shim"
        sub_tid = "sup_shim_01_rag_1234"
        server_mod.job_store[jid] = {
            "job_id": jid,
            "agent_name": "tool_rag_agent",
            "sub_thread_id": sub_tid,
            "status": "SUBMITTED",
        }
        try:
            with patch.object(server_mod, "register_subagent_thread", AsyncMock(return_value=None)):
                await server_mod._run_agent_job(
                    jid,
                    "tool_rag_agent",
                    server_mod.JobSubmitInput(
                        message="legacy call",
                        thread_id=sub_tid,
                        callback_thread_id="sup_shim_01",
                        user_id="test_u",
                    ),
                    fake_app,
                )
            job = server_mod.job_store[jid]
            self.assertEqual(job["status"], "SUCCESS")
            self.assertEqual(job["user_id"], "test_u")
            self.assertIsNone(job.get("parent_thread_id"))
            self.assertEqual(job["callback_thread_id"], "sup_shim_01")
            self.assertIn("sup_shim_01", job.get("workspace_dir") or "")
            self.assertEqual(job["wakeup_status"], "COMPLETED")
            self.assertEqual(job["supervisor_response"], "wakeup handled")
        finally:
            server_mod.job_store.pop(jid, None)

    async def test_agentic_rag_server_context_roles_client_and_chainlit_helpers(self):
        """Agentic_RAG 고유 컨텍스트 필드, api_list_agents 역할, 클라이언트 시그니처 및 Chainlit Job 모니터 헬퍼를 검증."""
        import app.chainlit_ui as ui_mod

        def _fake_load_config(path: str, default: dict) -> dict:
            if "logging.config" in path:
                return {"logging_enabled": True, "log_path": "./artifacts/custom.json"}
            return default

        with patch.object(server_mod, "load_config", side_effect=_fake_load_config), patch.dict(
            os.environ, {"LANGCHAIN_TRACING_V2": "true"}
        ):
            ctx = server_mod._create_agent_context(
                session_id="s_ctx_1",
                agent_name="tool_rag_agent",
                user_id="u_ctx_1",
            )
        self.assertTrue(ctx.logging_enabled)
        self.assertEqual(ctx.log_path, "./artifacts/custom.json")
        self.assertTrue(ctx.debug_mode)

        agents = server_mod.api_list_agents()
        by_name = {a["name"]: a for a in agents}
        self.assertIn("tool_rag_agent", by_name)
        self.assertIn("skill_rag_agent", by_name)
        self.assertEqual(by_name["tool_rag_agent"]["roles"], ["main", "sub"])
        self.assertEqual(by_name["skill_rag_agent"]["roles"], ["main", "sub"])
        if (Path(server_mod.project_root) / "app" / "agents" / "file_rag_agent.py").is_file():
            self.assertIn("file_rag_agent", by_name)
            self.assertEqual(by_name["file_rag_agent"]["roles"], ["main"])

        get_job_params = inspect.signature(AsyncAgentClient.get_job).parameters
        cancel_job_params = inspect.signature(AsyncAgentClient.cancel_job).parameters
        self.assertIn("caller_thread_id", get_job_params)
        self.assertIn("reason", cancel_job_params)
        self.assertIn("caller_thread_id", cancel_job_params)

        self.assertTrue(ui_mod._is_job_pending_monitor({"status": "SUBMITTED"}))
        self.assertTrue(ui_mod._is_job_pending_monitor({"status": "RUNNING"}))
        self.assertTrue(ui_mod._is_job_pending_monitor({"status": "FAILED", "wakeup_status": "PENDING"}))
        self.assertTrue(
            ui_mod._is_job_pending_monitor(
                {
                    "status": "SUCCESS",
                    "callback_agent": "supervisor",
                    "supervisor_response": None,
                    "wakeup_status": None,
                }
            )
        )
        self.assertFalse(ui_mod._is_job_pending_monitor({"status": "CANCELLED"}))
        self.assertFalse(
            ui_mod._is_job_pending_monitor(
                {
                    "status": "SUCCESS",
                    "wakeup_status": "COMPLETED",
                    "supervisor_response": "ok",
                }
            )
        )

        test_tid = "cl_seed_tid_01"
        ui_mod._rendered_jobs_by_thread.pop(test_tid, None)
        sample_jobs = [
            {"job_id": "job_term", "status": "SUCCESS", "wakeup_status": "COMPLETED", "supervisor_response": "done"},
            {"job_id": "job_can", "status": "CANCELLED", "wakeup_status": "SKIPPED"},
            {"job_id": "job_pend", "status": "RUNNING", "wakeup_status": "PENDING"},
        ]
        try:
            with patch.object(ui_mod.api_client, "get_session_jobs", AsyncMock(return_value=sample_jobs)):
                await ui_mod._seed_existing_terminal_jobs(test_tid)
            seeded = ui_mod._rendered_jobs_by_thread.get(test_tid, set())
            self.assertEqual(seeded, {"job_term", "job_can"})
        finally:
            ui_mod._rendered_jobs_by_thread.pop(test_tid, None)

    async def test_shared_checkpointer_recovers_after_external_close(self):
        """외부에서 공유 checkpointer 커넥션이 닫혀도 get_shared_checkpointer()가 새 커넥션으로 복구하는지 검증."""
        from app.utils.database import close_shared_checkpointer, get_shared_checkpointer

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "shared_cp.db")
            cp1 = await get_shared_checkpointer(db_path=db_path)
            self.assertTrue(getattr(cp1.conn, "_running", False))

            await cp1.conn.close()
            self.assertFalse(getattr(cp1.conn, "_running", True))

            cp2 = await get_shared_checkpointer(db_path=db_path)
            self.assertIsNot(cp2, cp1)
            self.assertTrue(getattr(cp2.conn, "_running", False))
            await close_shared_checkpointer()

    async def test_shared_checkpointer_lock_serialization_with_close(self):
        """get_shared_checkpointer()와 close_shared_checkpointer() 동시 호출 시 캐시와 커넥션 상태가 일관되게 직렬화되는지 검증."""
        from app.utils.database import session_store
        from app.utils.database.session_store import (
            _is_conn_alive,
            close_shared_checkpointer,
            get_shared_checkpointer,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "race_cp.db")
            abs_db = session_store._resolve_db_path(db_path)
            loop_id = id(asyncio.get_running_loop())
            try:
                cp_raced, _ = await asyncio.gather(
                    get_shared_checkpointer(db_path=db_path),
                    close_shared_checkpointer(),
                )
                cached_conn = session_store._checkpointer_conn_by_key.get((loop_id, abs_db))
                if cached_conn is not None:
                    self.assertTrue(_is_conn_alive(cached_conn))
                    self.assertIs(cp_raced.conn, cached_conn)
                else:
                    self.assertFalse(_is_conn_alive(cp_raced.conn))

                _, cp_live = await asyncio.gather(
                    close_shared_checkpointer(),
                    get_shared_checkpointer(db_path=db_path),
                )
                self.assertTrue(_is_conn_alive(cp_live.conn))
                self.assertIs(
                    session_store._checkpointer_by_key.get((loop_id, abs_db)),
                    cp_live,
                )
            finally:
                await close_shared_checkpointer()
                self.assertEqual(
                    [k for k in session_store._checkpointer_conn_by_key if k[0] == loop_id],
                    [],
                )

    async def test_checkpoints_db_path_patch_unifies_session_crud_and_checkpointer(self):
        """CHECKPOINTS_DB_PATH만 패치해도 세션 CRUD와 공유 Checkpointer가 동일한 임시 DB 경로를 사용하는지 검증."""
        from app.utils.database import session_store
        from app.utils.database.session_store import (
            close_shared_checkpointer,
            create_session,
            get_session,
            get_shared_checkpointer,
        )

        orig_cp_path = session_store.CHECKPOINTS_DB_PATH
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_db = str(Path(tmpdir) / "patched_cp.db")
            abs_temp_db = session_store._resolve_db_path(temp_db)
            try:
                session_store.CHECKPOINTS_DB_PATH = temp_db
                created = await create_session("sess_patch_1", "skill_rag_agent", "Patched DB Session")
                self.assertEqual(created["session_id"], "sess_patch_1")

                fetched = await get_session("sess_patch_1")
                self.assertIsNotNone(fetched)
                self.assertEqual(fetched["title"], "Patched DB Session")

                cp = await get_shared_checkpointer()
                loop_id = id(asyncio.get_running_loop())
                self.assertIn((loop_id, abs_temp_db), session_store._checkpointer_by_key)
                self.assertIs(session_store._checkpointer_by_key[(loop_id, abs_temp_db)], cp)
                self.assertTrue(Path(abs_temp_db).exists())
            finally:
                await close_shared_checkpointer()
                session_store._initialized_db_paths.discard(abs_temp_db)
                session_store.CHECKPOINTS_DB_PATH = orig_cp_path


if __name__ == "__main__":
    unittest.main()
