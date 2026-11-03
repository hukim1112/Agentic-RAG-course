"""
triplet_extractor.py
====================
경량 도메인 온톨로지(Domain Ontology) 기반 지식 그래프(Entity-Relation-Entity) 구조화 추출 모듈

- 왜 도메인 온톨로지 제약(Constraint)이 필요한가?
  LLM에게 제약 없이 트리플렛을 뽑게 하면 '팀장이다', '이끈다', '총괄한다'처럼 관계 어휘가 파편화되고,
  '클운팀', '클라우드운영팀', '김철수', '김철수 수석'처럼 동일 엔티티가 여러 노드로 쪼개져 다중 홉 탐색이 끊어집니다.
  따라서 Pydantic Literal 스키마로 엔티티 유형(EntityType)과 표준 관계 어휘(RelationType)를 명시적으로 제약하고,
  사내 공식 명칭으로 엔티티를 정규화(Entity Resolution)하여 추출합니다.
"""

from typing import List, Literal, Optional
from pydantic import BaseModel, Field

# 1. 엔터프라이즈 도메인 온톨로지: 허용 엔티티 유형 (5대 핵심 클래스)
EntityType = Literal[
    "Person",       # 임직원 (예: 김철수 수석, 박영희 전무, 최책임 책임)
    "Department",   # 본부·부서·위원회 (예: 클라우드사업본부, 클라우드운영팀, 인사위원회)
    "Project",      # 전략 프로젝트 (예: P-01: 클라우드 네이티브 마이그레이션)
    "PolicyOrRule", # 사내 규정·전결 기준·예산 구간 (예: 국내 여비 규정 제21조, 3억 5,000만원)
    "RiskOrGoal",   # 핵심 목표·리스크·기술 인프라 (예: vLLM PagedAttention, 다운타임 최소화)
]

# 2. 엔터프라이즈 도메인 온톨로지: 표준 관계 어휘 (12대 핵심 관계)
RelationType = Literal[
    "산하조직",     # [상위 본부] ──(산하조직)──▶ [하위 팀]
    "본부장",       # [인물] ──(본부장)──▶ [본부]
    "팀장",         # [인물] ──(팀장)──▶ [팀]
    "소속팀원",     # [인물] ──(소속팀원)──▶ [팀]
    "직속보고",     # [하위자/팀장] ──(직속보고)──▶ [상위 결재권자/본부장]
    "주관부서",     # [부서] ──(주관부서)──▶ [프로젝트]
    "총괄PM",       # [인물] ──(총괄PM)──▶ [프로젝트]
    "참여인력",     # [인물] ──(참여인력)──▶ [프로젝트]
    "파견협업",     # [인물/부서] ──(파견협업)──▶ [프로젝트/부서]
    "예산승인권자", # [결재권자] ──(예산승인권자)──▶ [프로젝트/예산구간]
    "사전합의및감사", # [인물/부서] ──(사전합의및감사)──▶ [프로젝트/규정]
    "선후행의존",   # [후행 프로젝트] ──(선후행의존)──▶ [선행 프로젝트/인프라]
]


class Triplet(BaseModel):
    """도메인 온톨로지 제약을 따르는 지식 그래프 단일 트리플렛"""
    subject: str = Field(
        description="출발 엔티티의 공식 명칭 (약어 사용 금지. 예: '클운팀' 대신 '클라우드운영팀', 인물은 '김철수 수석'처럼 성명+직급 표기)"
    )
    subject_type: EntityType = Field(description="출발 엔티티의 온톨로지 분류")
    relation: RelationType = Field(description="표준 도메인 온톨로지 관계명")
    object: str = Field(
        description="도착 엔티티의 공식 명칭 (예: '클라우드사업본부', '박영희 전무', 'P-01: 클라우드 네이티브 마이그레이션')"
    )
    object_type: EntityType = Field(description="도착 엔티티의 온톨로지 분류")
    detail: Optional[str] = Field(
        default=None,
        description="예산 금액, 전결 조건, 리스크 등 관계에 대한 부가 설명 (예: '예산 3억 5,000만원 전결', '클라우드운영팀에서 파견')"
    )


class KnowledgeGraph(BaseModel):
    """텍스트에서 추출된 온톨로지 기반 지식 그래프 트리플렛 모음"""
    triplets: List[Triplet] = Field(description="추출된 지식 그래프 트리플렛 목록")


# 사내 부서 약어 및 프로젝트 명칭 정규화 사전 (Entity Resolution 후처리용)
ENTITY_CANONICAL_MAP = {
    "클운팀": "클라우드운영팀",
    "인프라팀": "인프라엔지니어링팀",
    "에이팀": "AgenticAI팀",
    "데플팀": "데이터플랫폼팀",
    "데이터팀": "데이터플랫폼팀",
    "인사팀": "인사기획팀",
    "재무팀": "재무관리팀",
    "재무회계팀": "재무관리팀",
    "보안팀": "정보보안팀",
    "AI랩": "인공지능연구소",
    "김철수": "김철수 수석",
    "김철수 팀장": "김철수 수석",
    "박영희": "박영희 전무",
    "박영희 본부장": "박영희 전무",
    "송본부장": "송본부장 상무",
    "한본부장": "한본부장 전무",
    "강보안": "강보안 상무",
    "정수석": "정수석 수석",
    "홍팀장": "홍팀장 수석",
    "유수석": "유수석 수석",
    "오팀장": "오팀장 수석",
    "권팀장": "권팀장 수석",
    "윤에이전트": "윤에이전트 책임",
    "최책임": "최책임 책임",
    "임데이터": "임데이터 책임",
    "조엔지니어": "조엔지니어 책임",
    "이선임": "이선임 선임",
    "강엔지니어": "강엔지니어 선임",
    "장LLM": "장LLM 선임",
    "P-01": "P-01: 클라우드 네이티브 마이그레이션",
    "프로젝트 P-01": "P-01: 클라우드 네이티브 마이그레이션",
    "P-02": "P-02: 엔터프라이즈 Agentic RAG 플랫폼 구축",
    "프로젝트 P-02": "P-02: 엔터프라이즈 Agentic RAG 플랫폼 구축",
    "P-03": "P-03: 차세대 AI 데이터 거버넌스",
    "프로젝트 P-03": "P-03: 차세대 AI 데이터 거버넌스",
    "P-04": "P-04: 금융권 생성형 AI 보안 가드레일 구축",
    "프로젝트 P-04": "P-04: 금융권 생성형 AI 보안 가드레일 구축",
    "P-05": "P-05: 멀티클라우드 GPU 추론 클러스터 고도화",
    "프로젝트 P-05": "P-05: 멀티클라우드 GPU 추론 클러스터 고도화",
    "P-06": "P-06: 사내 ERP Text2SQL 통합 파이프라인 구축",
    "프로젝트 P-06": "P-06: 사내 ERP Text2SQL 통합 파이프라인 구축",
}


def canonicalize_entity(name: str) -> str:
    """약어나 축약 호칭을 사내 표준 엔티티 명칭으로 정규화(Entity Resolution)합니다."""
    cleaned = name.strip().strip("[]")
    if cleaned in ENTITY_CANONICAL_MAP:
        return ENTITY_CANONICAL_MAP[cleaned]
    for prefix in ("P-01", "P-02", "P-03", "P-04", "P-05", "P-06"):
        if cleaned.startswith(prefix) and prefix in ENTITY_CANONICAL_MAP:
            return ENTITY_CANONICAL_MAP[prefix]
    return cleaned


def get_default_llm(model: str = "gemini-3.8-flash", temperature: float = 0.0):
    """앱 공통 Chat Model Factory로 Gemini LLM 인스턴스를 초기화합니다."""
    from app.utils import init_chat_model as app_init_chat_model
    return app_init_chat_model(model=model, temperature=temperature)


def extract_triplets(
    text: str,
    llm=None,
    instruction: Optional[str] = None,
) -> KnowledgeGraph:
    """
    비정형 텍스트에서 도메인 온톨로지(EntityType, RelationType) 제약을 준수하는
    Entity-Relation-Entity 트리플렛을 추출하고 엔티티 명칭을 정규화합니다.
    """
    if llm is None:
        llm = get_default_llm()

    structured_llm = llm.with_structured_output(KnowledgeGraph)

    prompt = (
        "당신은 엔터프라이즈 지식 그래프 온톨로지 설계 및 구축 전문가입니다.\n"
        "제공된 텍스트에서 전사 조직 구조, 본부장/팀장/팀원 소속, 직속 보고선, 6대 전략 프로젝트(P-01~P-06)의 "
        "주관부서·총괄PM·참여인력·파견협업·예산승인권자·사전합의·선후행의존 관계를 빠짐없이 추출하세요.\n\n"
        "[온톨로지 및 엔티티 정규화 규칙]:\n"
        "1. 부서명은 약어('클운팀', '에이팀' 등) 대신 반드시 공식 명칭('클라우드운영팀', 'AgenticAI팀')으로 통일하세요.\n"
        "2. 인물명은 반드시 '성명 + 공식 직급'(예: '김철수 수석', '박영희 전무', '최책임 책임')으로 통일하세요.\n"
        "3. 프로젝트명은 'P-01: 클라우드 네이티브 마이그레이션' 형식의 전체 공식 명칭으로 통일하세요.\n"
        "4. 각 프로젝트(P-01~P-06)마다 총괄PM, 주관부서, 예산승인권자(detail에 예산액 기재), 선후행의존 관계를 반드시 포함하세요.\n\n"
        f"[원본 텍스트]:\n{text}"
    )
    if instruction:
        prompt += f"\n\n[추가 지시사항]:\n{instruction}"

    result: KnowledgeGraph = structured_llm.invoke(prompt)

    # 사후 엔티티 정규화(Entity Resolution) 및 중복 제거
    deduped: List[Triplet] = []
    seen = set()
    for t in result.triplets:
        t.subject = canonicalize_entity(t.subject)
        t.object = canonicalize_entity(t.object)
        key = (t.subject, t.relation, t.object)
        if key not in seen and t.subject != t.object:
            seen.add(key)
            deduped.append(t)

    return KnowledgeGraph(triplets=deduped)
