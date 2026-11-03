"""
읽기 전용 SQL 실행기 (Read-only SQL Executor)

LLM이 생성한 SQL을 2중 가드레일로 검증한 뒤 실행합니다.
(사내 정보보안관리지침: "코드 레벨(정규식 가드레일)과 DB 권한 레벨에서 이중 차단")

1단계 (코드 레벨): 단일 SELECT/WITH 문만 허용, 쓰기·스키마 변경 키워드 차단
2단계 (DB 레벨):   읽기 전용 모드(mode=ro)로 연결 + PRAGMA query_only
그 외:             실행 시간 제한, 반환 행 수 제한 (잘린 경우 전체 행 수를 함께 반환)

오류는 예외로 던지지 않고 ExecutionResult.error 문자열로 돌려줍니다.
Text2SQL 워크플로우가 이 메시지를 LLM에 다시 보여 주어 SQL을 스스로 고치게 합니다.
"""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

_STRING_LITERAL_RE = re.compile(r"'(?:[^']|'')*'")
_COMMENT_RE = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)
_ALLOWED_START_RE = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)
_COUNT_CAP = 10_000  # 잘린 결과의 전체 행 수는 이 값까지만 셉니다
_FORBIDDEN_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|ATTACH|DETACH|PRAGMA|VACUUM|REINDEX|REPLACE\s+INTO)\b",
    re.IGNORECASE,
)


@dataclass
class ExecutionResult:
    """SQL 실행 결과. ok=False이면 error에 LLM이 읽을 수 있는 오류 메시지가 들어 있습니다."""

    ok: bool
    columns: List[str] = field(default_factory=list)
    rows: List[Tuple] = field(default_factory=list)
    truncated: bool = False
    total_rows: int = 0  # 잘리기 전 전체 행 수 (_COUNT_CAP에서 멈춤)
    error: str = ""

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def summary(self) -> str:
        """'3행' 또는 '전체 135행 중 상위 50행 표시'"""
        if not self.truncated:
            return f"{self.row_count}행"
        total = f"{_COUNT_CAP:,}행 이상" if self.total_rows >= _COUNT_CAP else f"{self.total_rows:,}행"
        return f"전체 {total} 중 상위 {self.row_count}행 표시"

    def to_markdown(self) -> str:
        if not self.ok:
            return f"(실행 실패) {self.error}"
        if not self.rows:
            return "(결과 0행)"
        header = "| " + " | ".join(self.columns) + " |"
        divider = "| " + " | ".join("---" for _ in self.columns) + " |"
        body = [
            "| " + " | ".join("" if v is None else str(v) for v in row) + " |"
            for row in self.rows
        ]
        return "\n".join([header, divider, *body])


def connect_readonly(db_path: str | Path) -> sqlite3.Connection:
    """DB 파일을 읽기 전용으로 엽니다. 경로에 공백·한글이 있어도 되도록 file URI로 변환합니다."""
    path = Path(db_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"DB 파일이 없습니다: {path}")
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only = ON")
    return conn


def validate_sql(sql: str) -> Tuple[str, Optional[str]]:
    """(정리된 SQL, 오류 메시지)를 반환합니다. 통과하면 오류 메시지는 None입니다."""
    cleaned = sql.strip().rstrip(";").strip()
    if not cleaned:
        return cleaned, "SQL이 비어 있습니다."

    # 문자열 리터럴('...삭제...')과 주석 안의 단어가 키워드 검사에 걸리지 않도록 지운 뒤 검사합니다.
    skeleton = _COMMENT_RE.sub(" ", _STRING_LITERAL_RE.sub("''", cleaned))
    if not _ALLOWED_START_RE.match(skeleton):
        return cleaned, "SELECT 또는 WITH로 시작하는 조회 문만 실행할 수 있습니다."
    if ";" in skeleton:
        return cleaned, "SQL 문은 한 번에 1개만 실행할 수 있습니다. 세미콜론(;)으로 여러 문장을 잇지 마세요."
    forbidden = _FORBIDDEN_RE.search(skeleton)
    if forbidden:
        return cleaned, f"읽기 전용 실행기에서 허용되지 않는 키워드입니다: {forbidden.group(1).upper()}"
    return cleaned, None


def run_readonly_query(
    db_path: str | Path,
    sql: str,
    max_rows: int = 50,
    timeout_sec: float = 5.0,
) -> ExecutionResult:
    """검증을 통과한 SQL을 읽기 전용 연결로 실행하고, 최대 max_rows행까지 반환합니다."""
    cleaned, error = validate_sql(sql)
    if error:
        return ExecutionResult(ok=False, error=error)

    conn = connect_readonly(db_path)
    deadline = time.monotonic() + timeout_sec
    # SQLite VM 명령 1만 개마다 호출되며, 0이 아닌 값을 반환하면 실행이 중단됩니다.
    conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 10_000)
    try:
        cursor = conn.execute(cleaned)
        columns = [d[0] for d in cursor.description or []]
        rows = cursor.fetchmany(max_rows)
        # 남은 행은 내용을 버리고 개수만 셉니다. 메인 에이전트가 "결과가 잘렸다"는 사실을 알 수 있게 하기 위함입니다.
        total = len(rows)
        while total < _COUNT_CAP:
            chunk = cursor.fetchmany(min(1000, _COUNT_CAP - total))
            if not chunk:
                break
            total += len(chunk)
        return ExecutionResult(
            ok=True,
            columns=columns,
            rows=rows,
            truncated=total > len(rows),
            total_rows=total,
        )
    except sqlite3.OperationalError as e:
        if "interrupted" in str(e):
            return ExecutionResult(ok=False, error=f"실행 시간이 {timeout_sec:.0f}초를 넘어 중단되었습니다. 조인 조건을 확인하세요.")
        return ExecutionResult(ok=False, error=f"SQLite 오류: {e}")
    except sqlite3.Error as e:
        return ExecutionResult(ok=False, error=f"SQLite 오류: {e}")
    finally:
        conn.close()
