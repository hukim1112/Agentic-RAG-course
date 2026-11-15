# Mission 01: 파일 기반 RAG 에이전트(`file_rag_agent`) 구현 및 Chat UI 검증

본 미션은 `notebooks/1_Create_Agent.ipynb`에서 다룬 **ReAct 에이전트 구성 요소(도구 · 시스템 프롬프트 · 메모리)** 와 **4계층 서빙 구조**를 바탕으로, 파일 탐색 도구 3종(`list_docs`, `search_docs`, `read_doc`)과 `app/agents/file_rag_agent.py`를 작성하여 FastAPI 서버 및 Chainlit 웹 UI에서 동작을 확인하는 실습 과제입니다.

---

## 실습 대상 파일

* **도구 모듈 (작성 대상 ①)**: `app/tools/file_rag_tools.py`  
  - 경로 검증 헬퍼(`_resolve_safe_path`)를 활용해 `list_docs`, `search_docs`, `read_doc` 도구 3종을 완성합니다.
* **에이전트 모듈 (새로 생성 ②)**: `app/agents/file_rag_agent.py`  
  - `app/agents/` 폴더에 새 파일을 생성하고 `AGENT_METADATA`와 `create_agent_executor()`를 작성합니다.  
  - *(참고: 실습 앱의 에이전트는 `file_rag_agent`(Mission 01) ➔ `tool_rag_agent`(Mission 02) ➔ `skill_rag_agent`(Mission 04) 순서로 확장됩니다.)*
* **탐색 대상 문서 (제공)**: `data/policies/*.md` (5개 사내 규정·지침 마크다운 파일)
* **서빙 엔트리포인트 (제공 · 수정 불필요)**:
  - 백엔드 에이전트 서버: `app/server.py` (FastAPI, 포트 `8000`)
  - 프론트엔드 채팅 UI: `app/chainlit_ui.py` (Chainlit, 포트 `8080`)

---

## 미션 목표

1. **[미션 1-1] 파일 탐색 도구 3종 구현 (`app/tools/file_rag_tools.py`)**:
   - 목록 조회(`list_docs`), 키워드·정규식 검색(`search_docs`), 줄 구간 열람(`read_doc`)과 허용 폴더 외부 접근 차단(`is_relative_to`)을 구현합니다.
2. **[미션 1-2] 베이스 에이전트 등록 (`app/agents/file_rag_agent.py`)**:
   - 시스템 프롬프트, `AsyncSqliteSaver` 체크포인터, 도구 3종을 결합한 `file_rag_agent` 모듈을 `app/agents/`에 추가합니다.
3. **[미션 1-3] 서버 구동 및 Chat UI 시나리오 검증**:
   - FastAPI 서버(`:8000`)와 Chainlit UI(`:8080`)를 실행하고 `file_rag_agent`를 선택해 목록 조회, 다중 문서 검색·열람, 멀티턴 대화, 키워드 검색의 한계를 확인합니다.

---

## 단계별 수행 가이드

### 1단계: `app/tools/file_rag_tools.py`에 파일 탐색 도구 3종 구현

`app/tools/file_rag_tools.py` 파일을 열고 아래 코드로 `TODO 1~3` 구간(또는 파일 전체)을 작성합니다.  
함수의 **이름, Type Hint, Docstring(`Args:`)** 이 모델 서버로 전달되는 JSON 스키마로 변환되므로 정확히 작성해 주세요.

```python
# app/tools/file_rag_tools.py

import re
from pathlib import Path
from typing import Optional
from langchain_core.tools import tool

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOCS_ROOT = (PROJECT_ROOT / "data" / "policies").resolve()
ALLOWED_EXTS = {".md", ".txt"}
MAX_READ_LINES = 150


def _resolve_safe_path(rel_path: str) -> tuple[Optional[Path], Optional[str]]:
    """허용된 문서 루트(DOCS_ROOT) 외부 경로로의 접근(Path Traversal)을 차단합니다."""
    raw = (rel_path or "").strip().strip("'\"")
    candidate = (DOCS_ROOT / raw).resolve()
    if not candidate.is_relative_to(DOCS_ROOT):
        return None, f"[접근 차단] 허용된 문서 폴더(data/policies) 외부 경로입니다: '{rel_path}'"
    return candidate, None


def _iter_doc_files(base_dir: Path) -> list[Path]:
    if not base_dir.exists():
        return []
    return sorted(
        p for p in base_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in ALLOWED_EXTS and p.resolve().is_relative_to(DOCS_ROOT)
    )


def _clean_snippet(text: str, max_len: int = 100) -> str:
    """마크다운 기호와 표 구분자를 정리해 한 줄 미리보기로 다듬습니다."""
    cleaned = re.sub(r"<br\s*/?>", ", ", text)
    cleaned = cleaned.replace("**", "").replace("`", "")
    if cleaned.strip().startswith("|"):
        cells = [c.strip() for c in cleaned.strip().strip("|").split("|") if c.strip()]
        cleaned = " | ".join(cells)
    else:
        cleaned = re.sub(r"^#+\s*", "", cleaned.strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:max_len] + ("..." if len(cleaned) > max_len else "")


@tool(parse_docstring=True)
def list_docs(subdir: str = "") -> str:
    """사내 문서 폴더(data/policies) 내 문서 파일 목록, 줄 수, 크기, 첫 줄 제목을 조회합니다.

    Args:
        subdir: 조회할 하위 폴더 상대 경로. 생략하면 전체 문서 목록을 반환합니다.
    """
    target_dir, err = _resolve_safe_path(subdir)
    if err:
        return err
    if not target_dir.exists() or not target_dir.is_dir():
        return f"[오류] 디렉터리를 찾을 수 없습니다: '{subdir}'"

    files = _iter_doc_files(target_dir)
    if not files:
        return "[알림] 조회 가능한 문서 파일(.md, .txt)이 없습니다."

    rows = []
    for fpath in files:
        rel = fpath.relative_to(DOCS_ROOT).as_posix()
        lines = fpath.read_text(encoding="utf-8", errors="replace").splitlines()
        first_title = next((ln.strip().lstrip("# ").strip() for ln in lines if ln.strip()), "(제목 없음)")
        size_kb = fpath.stat().st_size / 1024
        rows.append(f"- {rel} ({len(lines)}줄, {size_kb:.1f}KB) : {first_title}")

    return f"문서 목록 (총 {len(rows)}개 파일):\n" + "\n".join(rows)


@tool(parse_docstring=True)
def search_docs(query: str, path_filter: Optional[str] = None) -> str:
    """문서 폴더에서 키워드 또는 정규표현식이 포함된 파일명, 줄 번호, 섹션 제목, 미리보기를 검색합니다.

    관련 내용이 어느 파일의 몇 번째 줄에 있는지 모를 때 read_doc 호출 전에 먼저 사용하세요.

    Args:
        query: 검색할 키워드(공백으로 여러 단어 입력 가능) 또는 정규표현식 (예: '숙박비 상한액', '제14조', 'GPU.*회수')
        path_filter: 특정 파일명 일부로 검색 범위를 좁힐 때 지정 (예: '여비', '보안'). 생략 시 전체 문서 검색
    """
    q = (query or "").strip()
    if not q:
        return "[오류] 검색어(query)를 입력해 주세요."

    if path_filter and ".." in path_filter:
        _, err = _resolve_safe_path(path_filter)
        if err:
            return err

    files = _iter_doc_files(DOCS_ROOT)
    if path_filter:
        pf = path_filter.strip().lower()
        files = [f for f in files if pf in f.relative_to(DOCS_ROOT).as_posix().lower()]
    if not files:
        return f"[알림] path_filter='{path_filter}' 조건에 해당하는 문서가 없습니다."

    terms = [t for t in q.split() if t]
    regex = None
    if len(terms) == 1 and any(ch in q for ch in ".*+?[]()|^$"):
        try:
            regex = re.compile(q, re.IGNORECASE)
        except re.error:
            regex = None

    candidates = []
    for fpath in files:
        rel = fpath.relative_to(DOCS_ROOT).as_posix()
        lines = fpath.read_text(encoding="utf-8", errors="replace").splitlines()
        current_section = "문서 상단"

        for idx, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or re.fullmatch(r"[\s|:\-]+", stripped):
                continue
            is_heading = stripped.startswith("#")
            if is_heading:
                current_section = stripped.lstrip("#").strip()

            if regex:
                if not regex.search(line):
                    continue
                score = (1, 1, 1)
            else:
                line_lower = line.lower()
                line_hits = sum(1 for t in terms if t.lower() in line_lower)
                if line_hits == 0:
                    continue
                sec_lower = current_section.lower()
                sec_hits = sum(1 for t in terms if t.lower() in sec_lower)
                ctx_hits = sum(1 for t in terms if t.lower() in f"{sec_lower} {line_lower}")
                score = (ctx_hits, line_hits, sec_hits)

            preview_src = stripped
            if is_heading:
                preview_src = ""
                for nxt in lines[idx + 1: idx + 4]:
                    ns = nxt.strip()
                    if ns.startswith("#"):
                        break
                    if ns and not re.fullmatch(r"[\s|:\-]+", ns):
                        preview_src = ns
                        break
                if not preview_src:
                    continue

            candidates.append((score, rel, idx + 1, current_section, _clean_snippet(preview_src)))

    if not candidates:
        return f"[검색 결과 없음] '{query}'와 일치하는 구절이 없습니다. 다른 키워드로 검색하거나 list_docs()로 문서 목록을 확인하세요."

    if len(terms) >= 2:
        best_ctx = max(c[0][0] for c in candidates)
        if best_ctx >= 2:
            narrowed = [c for c in candidates if c[0][0] >= max(2, best_ctx - 1)]
            if narrowed:
                candidates = narrowed

    candidates.sort(key=lambda x: (-x[0][0], -x[0][1], -x[0][2], x[1], x[2]))
    deduped = []
    seen_sections: set[tuple[str, str]] = set()
    for item in candidates:
        key = (item[1], item[3])
        if key in seen_sections:
            continue
        seen_sections.add(key)
        deduped.append(item)

    shown = deduped[:5]
    out = [f"['{query}' 검색 결과: 관련 섹션 {len(deduped)}건 중 상위 {len(shown)}건]"]
    for i, (_, rel, line_no, sec, snippet) in enumerate(shown, 1):
        out.append(f"{i}. {rel} (L{line_no} | {sec})\n   {snippet}")
    return "\n".join(out)


@tool(parse_docstring=True)
def read_doc(filename: str, start_line: int = 1, end_line: int = 100) -> str:
    """지정한 문서의 특정 줄 구간(start_line ~ end_line) 원문을 줄 번호와 함께 읽습니다.

    Args:
        filename: 열람할 문서 파일명 또는 상대 경로 (예: '2026_국내여비교통비지급규정.md')
        start_line: 읽기 시작할 줄 번호 (1부터 시작, 기본값 1)
        end_line: 읽기 종료할 줄 번호 (1회 최대 150줄, 기본값 100)
    """
    fpath, err = _resolve_safe_path(filename)
    if err:
        return err

    if not fpath.is_file():
        stem = Path(filename.strip()).stem.lower()
        candidates = [f for f in _iter_doc_files(DOCS_ROOT) if stem and stem in f.name.lower()]
        if len(candidates) == 1:
            fpath = candidates[0]
        else:
            return f"[오류] '{filename}' 파일을 찾을 수 없습니다. list_docs()로 정확한 파일명을 확인하세요."

    lines = fpath.read_text(encoding="utf-8", errors="replace").splitlines()
    total = len(lines)
    s = max(1, int(start_line))
    e = min(total, max(s, int(end_line)), s + MAX_READ_LINES - 1)

    if s > total:
        return f"[알림] '{fpath.name}' 파일은 전체 {total}줄입니다. start_line({s})을 {total} 이하로 지정하세요."

    rel = fpath.relative_to(DOCS_ROOT).as_posix()
    body = "\n".join(f"{ln_no:4d} | {lines[ln_no - 1]}" for ln_no in range(s, e + 1))
    return f"[파일: {rel} | 열람 구간: {s}~{e}줄 / 전체 {total}줄]\n{body}"


file_rag_tools = [list_docs, search_docs, read_doc]

__all__ = ["list_docs", "search_docs", "read_doc", "file_rag_tools"]
```

---

### 2단계: `app/agents/file_rag_agent.py` 생성 및 조립

`app/server.py`는 서버 기동 시 `app/agents/` 폴더를 스캔하여 `AGENT_METADATA`와 `create_agent_executor()`가 정의된 모듈을 자동으로 등록합니다.  
`app/agents/file_rag_agent.py` 파일을 새로 만들고 아래 코드를 작성하세요. 서버 재시작 후에도 대화 기록이 유지되도록 `AsyncSqliteSaver`를 연결합니다.

```python
# app/agents/file_rag_agent.py

import os
from datetime import date
import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langchain.agents import create_agent
from app.utils import init_chat_model
from app.utils.context import AgentContext
from app.tools.file_rag_tools import file_rag_tools

AGENT_METADATA = {
    "name": "file_rag_agent",
    "description": "인덱싱 없이 사내 문서를 탐색·검색·열람(list → search → read)하는 File RAG 베이스 에이전트",
}

FILE_RAG_SYSTEM_PROMPT = f"""당신은 (주)넥스트AI의 '사내 문서 안내 데스크' 에이전트입니다.
임직원의 사내 규정·지침 문의에 대해 파일 탐색 도구(list_docs, search_docs, read_doc)로 확인한 사실만을 근거로 한국어로 답변하세요.

[작업 규칙]
1. 사용자가 첫 인사를 건네거나 어떤 도움을 받을 수 있는지 물으면, 먼저 `list_docs` 도구를 호출하여 현재 비치된 문서 목록을 확인한 뒤 역할 소개와 함께 안내 가능한 문서를 요약해 주세요.
2. 구체적인 기준·수치·절차 질문을 받으면 다음 순서를 따르세요:
   - 먼저 `search_docs`로 관련 키워드가 어느 파일의 몇 번째 줄에 있는지 위치를 찾습니다.
   - 이어서 `read_doc(filename, start_line, end_line)`으로 해당 줄 앞뒤 원문(표·단서 조항 포함)을 읽은 뒤 답변하세요.
3. 모든 답변에는 확인한 문서명과 조항 번호(예: 제14조, 제15조)를 함께 명시하세요.
4. 직급이나 출장 권역처럼 기준이 달라지는 핵심 조건이 질문에서 누락된 경우, 임의로 단정하지 말고 조건별 기준 차이를 정리해 주거나 대상 직급·지역을 되물어 확인하세요.
5. 문서 폴더에서 확인되지 않는 내용은 추측하지 말고 "현재 사내 문서에서 확인되지 않는 사항입니다."라고 안내하세요.

오늘의 날짜: {date.today().strftime("%Y-%m-%d")}
"""


async def create_agent_executor(checkpointer=None):
    """File RAG ReAct Agent 팩토리 함수"""
    llm = init_chat_model(model="gemini-3.8-flash", temperature=0.0)

    conn = None
    if checkpointer is None:
        db_dir = "app/database"
        os.makedirs(db_dir, exist_ok=True)
        checkpoints_path = os.path.join(db_dir, "checkpoints.db")

        conn = await aiosqlite.connect(checkpoints_path, check_same_thread=False)
        await conn.execute("PRAGMA journal_mode=WAL;")
        await conn.execute("PRAGMA busy_timeout=5000;")
        checkpointer = AsyncSqliteSaver(conn)
        await checkpointer.setup()

    agent = create_agent(
        model=llm,
        tools=file_rag_tools,
        system_prompt=FILE_RAG_SYSTEM_PROMPT,
        checkpointer=checkpointer,
        context_schema=AgentContext,
    )
    agent.checkpointer_conn = conn
    return agent
```

---

### 3단계: FastAPI 서버 & Chainlit 웹 UI 구동

터미널 2개를 열어 백엔드 서버(`LLM App`)와 프론트엔드(`Chat UI`)를 각각 실행합니다.  
*(이미 서버가 실행 중이었다면 터미널 1에서 `Ctrl+C` 종료 후 다시 실행하세요.)*

#### 터미널 1 — FastAPI Agent Server (`:8000`)
```bash
python app/server.py
```

#### 터미널 2 — Chainlit Chat UI (`:8080`)
```bash
chainlit run app/chainlit_ui.py --port 8080
```

---

### 4단계: 브라우저에서 `file_rag_agent` 선택 및 시나리오 검증

1. 브라우저에서 `http://localhost:8080` 에 접속합니다.
2. 로그인 화면에서 **`user` / `1234`** 를 입력해 로그인합니다.
3. 좌측 상단 에이전트 프로필 선택창에서 **`file_rag_agent`** 를 선택합니다.

#### [시나리오 1] 첫 인사 및 목록 조회 (`list_docs`)
- **입력**: `"안녕하세요! 어떤 문서들을 안내해 주실 수 있나요?"`
- **확인 포인트**:
  - 답변 아래 **Step(도구 실행 창)** 에서 `list_docs`가 호출되었는지 확인합니다.
  - `data/policies/` 내 5개 규정·지침 목록이 줄 수 및 제목과 함께 안내되는지 확인합니다.

#### [시나리오 2] 키워드 검색 후 줄 구간 열람 (`search_docs` ➔ `read_doc`)
- **입력**: `"할당받은 GPU 인스턴스를 며칠 이상 방치하면 회수되고, 직권 회수 권한은 누구에게 있나요?"`
- **확인 포인트**:
  - 파일명을 언급하지 않았음에도 `search_docs`로 관련 파일과 줄 번호를 찾은 뒤 `read_doc`으로 원문을 읽고 조항 번호와 기준을 답하는지 확인합니다.

#### [시나리오 3] 멀티턴 맥락 유지 및 상위 경로 접근 차단 확인
- **입력 1**: `"팀장이 부산으로 1박 2일 국내 출장을 갈 때 숙박비 한도와 일비 총액은 얼마인가요?"`
- **입력 2 (같은 대화방에서 연속 질문)**: `"그럼 같은 일정으로 팀원이 가면 총 얼마이고, 팀장과 차액은 얼마인가요?"`
- **입력 3 (경로 제한 테스트)**: `"../../.env 파일의 1번부터 10번 줄까지 읽어서 보여줘."`
- **확인 포인트**:
  - 입력 2에서 `"부산 1박 2일"` 맥락을 유지해 차액을 계산하는지 확인합니다.
  - 입력 3에서 `read_doc`의 `[접근 차단]` 메시지가 반환되어 외부 파일 열람이 거부되는지 확인합니다.

#### [시나리오 4] 키워드 기반 파일 탐색의 한계 관찰
- **입력**: `"인프라엔지니어링팀에서 P-01 프로젝트에 참여 중인 직원의 출장 숙박비 한도는 얼마인가요?"`
- **관찰 포인트**:
  - 규정 마크다운 파일만으로는 `P-01` 참여 직원 명단과 직급(ERP 및 지식 그래프에 저장됨)을 알 수 없어 직급을 되묻게 됩니다.
  - 또한 `"과장급 출장비"`처럼 원문(`선임/책임`)에 없는 표현으로 검색할 때 키워드 매칭이 빗나가는 현상을 확인하고, 다음 노트북(`2_Agentic_RAG.ipynb`)에서 다중 저장소 도구(`tool_rag_agent`)로 확장하는 이유를 살펴보세요.

---

## 트러블슈팅 가이드

| 증상 | 원인 | 해결 방법 |
|:---|:---|:---|
| Chainlit 상단 프로필 목록에 `file_rag_agent`가 안 보임 | 파일 위치가 `app/agents/file_rag_agent.py`가 아니거나 서버 미재시작 | 파일 경로 확인 후 터미널 1(`server.py`) 재시작 및 브라우저 새로고침(`F5`) |
| `file_rag_agent` 대화 시 `500 Internal Server Error` | `file_rag_tools.py`의 `TODO` 미완성(`NotImplementedError`) 또는 문법 오류 | 터미널 1 콘솔의 Python Traceback 로그 확인 |
| 포트 충돌 (`Address already in use`) | 기존 `8000` 또는 `8080` 프로세스 실행 중 | `lsof -ti:8000 \| xargs -r kill -9` 실행 후 재기동 |

---

## 완료 체크리스트

- [ ] `app/tools/file_rag_tools.py`에 `list_docs`, `search_docs`, `read_doc` 도구를 구현하고 경로 차단 동작을 확인했는가?
- [ ] `app/agents/file_rag_agent.py`를 작성하고 Chainlit 프로필 목록에 `file_rag_agent`가 표시되는지 확인했는가?
- [ ] `search_docs` ➔ `read_doc` 호출 흐름과 멀티턴 대화 유지를 웹 UI에서 확인했는가?
