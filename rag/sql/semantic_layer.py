"""
DB 프로필과 시멘틱 레이어 (Database Profile & Semantic Layer)

DB 1개에 대한 모든 메타정보를 DatabaseProfile 하나로 묶고, LLM이 읽을 카드 텍스트로 렌더링합니다.

    자동 추출 (sqlite_master / PRAGMA): 컬럼·타입·PK, FK(조인 경로), CHECK 허용값, 샘플 행
    사람이 작성 (semantic_layer.yaml):   설명, 동의어, 비즈니스 규칙, 지표(metric) 정의

렌더링 결과는 두 층으로 쓰입니다.
    overview()      DB 마스터 정보. 짧아서 SQL 생성 프롬프트에 항상 넣습니다.
    table_card()    테이블 상세 카드. 스키마 검색기가 질문에 맞는 카드만 골라 넣습니다.
    metric_card()   지표 카드. "집행률"처럼 컬럼이 아닌 계산 규칙을 정의합니다.

DB가 늘어나면 DB마다 yaml을 하나 두고 DatabaseProfile을 하나씩 더 로드합니다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from rag.sql.executor import connect_readonly

_CHECK_IN_RE = re.compile(r"CHECK\s*\(\s*(\w+)\s+IN\s*\(([^)]*)\)", re.IGNORECASE)
_QUOTED_RE = re.compile(r"'((?:[^']|'')*)'")
_SAMPLE_VALUE_MAX_LEN = 30


@dataclass
class ForeignKey:
    column: str
    ref_table: str
    ref_column: str


@dataclass
class ColumnInfo:
    name: str
    type: str
    primary_key: bool = False
    description: str = ""
    allowed_values: List[str] = field(default_factory=list)
    value_lookup: bool = False  # True이면 ValueLinker가 DISTINCT 값을 색인합니다 (이름, 부서명 등)


@dataclass
class TableInfo:
    name: str
    description: str = ""
    synonyms: List[str] = field(default_factory=list)
    rules: List[str] = field(default_factory=list)
    columns: List[ColumnInfo] = field(default_factory=list)
    foreign_keys: List[ForeignKey] = field(default_factory=list)
    sample_rows: List[Dict] = field(default_factory=list)


@dataclass
class MetricInfo:
    key: str
    name: str
    expression: str
    tables: List[str]
    description: str = ""
    synonyms: List[str] = field(default_factory=list)
    join_hint: str = ""


@dataclass
class DatabaseProfile:
    name: str
    title: str
    description: str
    dialect: str
    db_path: Path
    global_rules: List[str] = field(default_factory=list)
    synonyms: Dict[str, str] = field(default_factory=dict)
    tables: Dict[str, TableInfo] = field(default_factory=dict)
    metrics: Dict[str, MetricInfo] = field(default_factory=dict)

    # ------------------------------------------------------------------ 로드
    @classmethod
    def load(
        cls,
        semantic_layer_path: str | Path,
        db_path: Optional[str | Path] = None,
        sample_rows: int = 2,
    ) -> "DatabaseProfile":
        """yaml 시멘틱 레이어와 DB 구조를 합쳐 프로필을 만듭니다.

        db_path를 생략하면 yaml의 database.db_file을 yaml 파일 기준 상대 경로로 해석합니다.
        yaml에 적힌 테이블·컬럼이 실제 DB에 없으면 ValueError로 알려 줍니다
        (DB 스키마가 바뀌었는데 시멘틱 레이어를 고치지 않은 경우를 잡기 위함).
        """
        semantic_layer_path = Path(semantic_layer_path)
        with open(semantic_layer_path, "r", encoding="utf-8") as f:
            spec = yaml.safe_load(f) or {}

        db_spec = spec.get("database", {})
        resolved_db = Path(db_path) if db_path else semantic_layer_path.parent / db_spec["db_file"]
        profile = cls(
            name=db_spec.get("name", resolved_db.stem),
            title=db_spec.get("title", resolved_db.stem),
            description=db_spec.get("description", ""),
            dialect=db_spec.get("dialect", "SQLite"),
            db_path=resolved_db,
            global_rules=spec.get("global_rules", []),
            synonyms=spec.get("synonyms", {}),
        )
        profile.tables = _introspect_tables(resolved_db, sample_rows)
        _apply_table_spec(profile.tables, spec.get("tables", {}))
        profile.metrics = _load_metrics(profile.tables, spec.get("metrics", {}))
        return profile

    # ------------------------------------------------------------------ 조인 경로
    def parents(self, table: str) -> List[str]:
        """FK로 참조하는 상위 테이블 목록 (자기참조 제외). 예: expense_transactions → projects, employees"""
        seen: List[str] = []
        for fk in self.tables[table].foreign_keys:
            if fk.ref_table != table and fk.ref_table not in seen:
                seen.append(fk.ref_table)
        return seen

    # ------------------------------------------------------------------ 렌더링
    def overview(self) -> str:
        """DB 마스터 정보: 개요, 테이블 한 줄 요약, 공통 규칙"""
        lines = [f"# {self.title} ({self.dialect})", self.description.strip(), "", "테이블 목록:"]
        for t in self.tables.values():
            lines.append(f"- {t.name}: {t.description.strip() or '(설명 없음)'}")
        if self.global_rules:
            lines += ["", "공통 규칙:"]
            lines += [f"- {r}" for r in self.global_rules]
        return "\n".join(lines)

    def table_card(self, table: str) -> str:
        t = self.tables[table]
        lines = [f"### 테이블 {t.name}"]
        if t.description:
            lines.append(f"설명: {t.description.strip()}")
        if t.synonyms:
            lines.append(f"동의어: {', '.join(t.synonyms)}")
        lines.append("컬럼:")
        for c in t.columns:
            tags = [c.type or "ANY"] + (["PK"] if c.primary_key else [])
            line = f"- {c.name} ({', '.join(tags)})"
            if c.description:
                line += f": {c.description.strip()}"
            if c.allowed_values:
                line += " [허용값: " + ", ".join(f"'{v}'" for v in c.allowed_values) + "]"
            lines.append(line)
        if t.foreign_keys:
            lines.append("조인 경로(FK):")
            lines += [f"- {t.name}.{fk.column} → {fk.ref_table}.{fk.ref_column}" for fk in t.foreign_keys]
        if t.rules:
            lines.append("규칙:")
            lines += [f"- {r}" for r in t.rules]
        if t.sample_rows:
            lines.append("샘플 행:")
            for row in t.sample_rows:
                lines.append("- " + ", ".join(f"{k}={_short(v)}" for k, v in row.items()))
        return "\n".join(lines)

    def metric_card(self, key: str) -> str:
        m = self.metrics[key]
        lines = [f"### 지표 {m.key}: {m.name}"]
        if m.synonyms:
            lines.append(f"동의어: {', '.join(m.synonyms)}")
        if m.description:
            lines.append(f"설명: {m.description.strip()}")
        lines.append(f"SQL 식: {m.expression.strip()}")
        lines.append(f"필요 테이블: {', '.join(m.tables)}")
        if m.join_hint:
            lines.append(f"조인: {m.join_hint.strip()}")
        return "\n".join(lines)


# ---------------------------------------------------------------------- 내부 함수
def _short(value) -> str:
    text = "NULL" if value is None else str(value)
    return text if len(text) <= _SAMPLE_VALUE_MAX_LEN else text[:_SAMPLE_VALUE_MAX_LEN] + "…"


def _introspect_tables(db_path: Path, sample_rows: int) -> Dict[str, TableInfo]:
    """sqlite_master와 PRAGMA로 컬럼, PK, FK, CHECK 허용값, 샘플 행을 자동 추출합니다."""
    conn = connect_readonly(db_path)
    try:
        tables: Dict[str, TableInfo] = {}
        ddl_rows = conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY rowid"
        ).fetchall()
        for name, ddl in ddl_rows:
            allowed = {
                col: [v.replace("''", "'") for v in _QUOTED_RE.findall(values)]
                for col, values in _CHECK_IN_RE.findall(ddl or "")
            }
            columns = [
                ColumnInfo(name=col, type=col_type, primary_key=bool(pk), allowed_values=allowed.get(col, []))
                for _, col, col_type, _, _, pk in conn.execute(f'PRAGMA table_info("{name}")')
            ]
            foreign_keys = [
                ForeignKey(column=row[3], ref_table=row[2], ref_column=row[4])
                for row in conn.execute(f'PRAGMA foreign_key_list("{name}")')
            ]
            foreign_keys.sort(key=lambda fk: [c.name for c in columns].index(fk.column))
            cursor = conn.execute(f'SELECT * FROM "{name}" LIMIT {int(sample_rows)}')
            col_names = [d[0] for d in cursor.description]
            samples = [dict(zip(col_names, row)) for row in cursor.fetchall()]
            tables[name] = TableInfo(name=name, columns=columns, foreign_keys=foreign_keys, sample_rows=samples)
        return tables
    finally:
        conn.close()


def _apply_table_spec(tables: Dict[str, TableInfo], table_spec: Dict) -> None:
    """yaml의 테이블·컬럼 의미 정보를 자동 추출 결과 위에 덮어씁니다."""
    for table_name, t_spec in (table_spec or {}).items():
        if table_name not in tables:
            raise ValueError(f"시멘틱 레이어의 테이블 '{table_name}'이(가) DB에 없습니다.")
        table = tables[table_name]
        t_spec = t_spec or {}
        table.description = t_spec.get("description", "")
        table.synonyms = t_spec.get("synonyms", [])
        table.rules = t_spec.get("rules", [])
        columns = {c.name: c for c in table.columns}
        for col_name, c_spec in (t_spec.get("columns") or {}).items():
            if col_name not in columns:
                raise ValueError(f"시멘틱 레이어의 컬럼 '{table_name}.{col_name}'이(가) DB에 없습니다.")
            c_spec = c_spec if isinstance(c_spec, dict) else {"description": c_spec}
            column = columns[col_name]
            column.description = c_spec.get("description", "")
            column.value_lookup = bool(c_spec.get("value_lookup", False))
            if "values" in c_spec:  # CHECK 제약이 없는 컬럼의 허용값을 사람이 지정
                column.allowed_values = list(c_spec["values"])


def _load_metrics(tables: Dict[str, TableInfo], metric_spec: Dict) -> Dict[str, MetricInfo]:
    metrics: Dict[str, MetricInfo] = {}
    for key, m_spec in (metric_spec or {}).items():
        unknown = [t for t in m_spec.get("tables", []) if t not in tables]
        if unknown:
            raise ValueError(f"지표 '{key}'가 참조하는 테이블이 DB에 없습니다: {unknown}")
        metrics[key] = MetricInfo(
            key=key,
            name=m_spec.get("name", key),
            expression=m_spec["expression"],
            tables=m_spec.get("tables", []),
            description=m_spec.get("description", ""),
            synonyms=m_spec.get("synonyms", []),
            join_hint=m_spec.get("join_hint", ""),
        )
    return metrics
