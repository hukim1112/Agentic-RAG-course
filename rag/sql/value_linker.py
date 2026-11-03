"""
값 연결기 (Value Linker)

질문 속 표현을 DB에 실제로 저장된 값에 연결합니다. ("클운팀" → departments.dept_name = '클라우드운영팀')
SQL 생성 모델이 WHERE 조건에 DB에 없는 값을 지어내는 문제를 막기 위한 단계입니다.

색인 대상
  - CHECK 제약 허용값 (자동 추출: '결재대기', '국내출장', '수석' 등)
  - 시멘틱 레이어에서 value_lookup: true로 지정한 컬럼의 DISTINCT 값 (이름, 부서명, 도시 등)

매칭 규칙
  1. DomainDictionary로 약어·동의어를 정식 명칭으로 바꾼 뒤 부분 문자열로 찾습니다.
  2. 긴 값이 짧은 값을 덮으면 긴 값만 남깁니다. ('정수석' 안의 '수석'은 직급이 아니라 이름의 일부)
  3. 같은 값이 여러 컬럼에 있으면 후보를 모두 보여 주고, 어느 컬럼인지는 SQL 생성 모델이 고릅니다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from rag.sql.executor import connect_readonly
from rag.sql.semantic_layer import DatabaseProfile
from rag.vector.retrieval import DomainDictionary

_MIN_VALUE_LEN = 2


@dataclass
class ValueMatch:
    value: str
    columns: List[str]  # "table.column" 목록. 2개 이상이면 어느 컬럼인지 모호함


class ValueLinker:
    def __init__(
        self,
        profile: DatabaseProfile,
        domain_dict: Optional[DomainDictionary] = None,
        max_distinct: int = 500,
    ):
        self.domain_dict = domain_dict or DomainDictionary(profile.synonyms)
        self.index: Dict[str, List[str]] = {}
        conn = connect_readonly(profile.db_path)
        try:
            for table in profile.tables.values():
                for column in table.columns:
                    target = f"{table.name}.{column.name}"
                    values = list(column.allowed_values)
                    if column.value_lookup:
                        values += [
                            row[0]
                            for row in conn.execute(
                                f'SELECT DISTINCT "{column.name}" FROM "{table.name}" '
                                f'WHERE "{column.name}" IS NOT NULL LIMIT {int(max_distinct)}'
                            )
                        ]
                    for value in values:
                        value = str(value)
                        if len(value) >= _MIN_VALUE_LEN and target not in self.index.setdefault(value, []):
                            self.index[value].append(target)
        finally:
            conn.close()

    def link(self, question: str) -> List[ValueMatch]:
        text = self.domain_dict.normalize(question).lower()

        spans: List[Tuple[int, int, str]] = []
        for value in self.index:
            needle = value.lower()
            start = text.find(needle)
            while start != -1:
                spans.append((start, start + len(needle), value))
                start = text.find(needle, start + 1)

        # 긴 값부터 자리를 차지하고, 이미 차지한 구간 안에 완전히 들어가는 짧은 값은 버립니다.
        spans.sort(key=lambda s: s[1] - s[0], reverse=True)
        kept: List[Tuple[int, int, str]] = []
        for start, end, value in spans:
            if not any(k_start <= start and end <= k_end for k_start, k_end, _ in kept):
                kept.append((start, end, value))

        matches: List[ValueMatch] = []
        for _, _, value in sorted(kept):
            if all(m.value != value for m in matches):
                matches.append(ValueMatch(value=value, columns=self.index[value]))
        return matches

    @staticmethod
    def render(matches: List[ValueMatch]) -> str:
        if not matches:
            return "(질문에서 DB 값과 일치하는 표현을 찾지 못했습니다)"
        lines = []
        for m in matches:
            if len(m.columns) == 1:
                lines.append(f"- '{m.value}' → {m.columns[0]}")
            else:
                lines.append(f"- '{m.value}' → 여러 컬럼에 존재: {', '.join(m.columns)} (질문 의도에 맞는 컬럼을 고르세요)")
        return "\n".join(lines)
