# 기술·보안 공식 백서 및 학술 논문 PDF 데이터셋 (`data/tech_pdfs/`)

본 디렉터리는 **(주)넥스트AI**의 엔터프라이즈 Agentic RAG 아키텍처 실습에서 **비정형 PDF 문서 파싱(`pymupdf`, `pymupdf4llm`), 계층적 목차(TOC/Bookmark) 기반 청킹, 다단 학술 논문 및 복합 표(Table) 추출, 멀티 에이전트 라우팅**을 검증하기 위해 구성된 실제 공개 기술·보안 PDF 코퍼스(총 8종)입니다.

모든 PDF 파일은 `pymupdf`(`len(doc) > 0`, `doc.get_toc()`) 및 `pymupdf4llm.to_markdown()`을 통해 무결성, 북마크 계층 구조, 텍스트/표 추출 품질이 검증되었습니다.

---

## 1. 디렉터리 구조

```text
data/tech_pdfs/
├── README.md                                                     # 데이터셋 명세 및 프로젝트 시나리오 매핑
├── aws_waf_series/                                               # [시리즈 문서] 동일 양식·동일 북마크 구조의 AWS 공식 백서 4권
│   ├── AWS_Well_Architected_Security_Pillar.pdf
│   ├── AWS_Well_Architected_Reliability_Pillar.pdf
│   ├── AWS_Well_Architected_Performance_Efficiency_Pillar.pdf
│   └── AWS_Well_Architected_Cost_Optimization_Pillar.pdf
└── standalone_papers_guides/                                     # [개별 문서] 양식이 서로 다른 핵심 AI 인프라·보안 PDF 4편
    ├── vLLM_PagedAttention_SOSP23.pdf
    ├── NIST_AI_RMF_GenAI_Profile.pdf
    ├── OWASP_LLM_Security_Guide.pdf
    └── MS_GraphRAG_Architecture_2024.pdf
```

---

## 2. 수집 PDF 8종 상세 명세 및 (주)넥스트AI 시나리오 매핑

### A. `aws_waf_series/` — 동일 양식·동일 북마크 구조의 시리즈 백서 (4권)

AWS Well-Architected Framework의 핵심 4대 기둥(Pillar) 공식 영문 백서 시리즈입니다. 4권 모두 동일한 문서 템플릿(표지 → 목차 → Introduction → Design Principles → Definition → Best Practices → Conclusion)과 깊이 있는 PDF 북마크(`doc.get_toc()`) 계층 구조를 갖추고 있어, **동일 포맷 대용량 기술 문서 시리즈에 대한 일괄 TOC 기반 계층적 파싱 및 메타데이터 필터링** 실습에 활용됩니다.

| 파일명 | 출처 (공식 URL) | 용량 / 페이지 수 | 북마크(`get_toc()`) | 레이아웃 및 구조적 특징 | 연결되는 `(주)넥스트AI` 프로젝트 시나리오 |
| :--- | :--- | :---: | :---: | :--- | :--- |
| **`AWS_Well_Architected_Security_Pillar.pdf`** | [AWS Well-Architected Security Pillar](https://docs.aws.amazon.com/pdfs/wellarchitected/latest/security-pillar/wellarchitected-security-pillar.pdf) | 2.72 MB / 240p | 282개 항목 (Depth 1~4) | `[시리즈 표준]` 1단 기술 백서 레이아웃, 보안 설계 원칙·IAM·데이터 보호 베스트 프랙티스 계층 구조 | **[P-01: 클라우드 네이티브 마이그레이션]** (김철수 팀장) 전환 과정 중 금융 보안 규정 준수 및 **[P-03: 차세대 AI 데이터 거버넌스]** (유수석) 실시간 접근 통제 아키텍처 레퍼런스 |
| **`AWS_Well_Architected_Reliability_Pillar.pdf`** | [AWS Well-Architected Reliability Pillar](https://docs.aws.amazon.com/pdfs/wellarchitected/latest/reliability-pillar/wellarchitected-reliability-pillar.pdf) | 6.77 MB / 274p | 272개 항목 (Depth 1~4) | `[시리즈 표준]` 1단 기술 백서 레이아웃, 장애 격리·다중 가용영역(Multi-AZ)·무중단 전환 설계 | **[P-01: 클라우드 네이티브 마이그레이션]** (김철수 팀장, 이선임/강엔지니어) 레거시 온프레미스 → 하이브리드 멀티클라우드 전환 시 핵심 리스크인 **다운타임 최소화 및 고가용성(HA)** 설계 기준 |
| **`AWS_Well_Architected_Performance_Efficiency_Pillar.pdf`** | [AWS Well-Architected Performance Efficiency Pillar](https://docs.aws.amazon.com/pdfs/wellarchitected/latest/performance-efficiency-pillar/wellarchitected-performance-efficiency-pillar.pdf) | 1.32 MB / 124p | 146개 항목 (Depth 1~3) | `[시리즈 표준]` 1단 기술 백서 레이아웃, 컴퓨팅/스토리지/네트워크 선택 및 성능 모니터링 | **[P-01 & P-02 연계]** 클라우드운영팀 파견 인력(최책임)과 AgenticAI팀(홍팀장)이 협업하여 **[P-02: 엔터프라이즈 Agentic RAG 플랫폼]**의 클라우드 GPU/네트워크 인프라 성능 최적화 시 참조 |
| **`AWS_Well_Architected_Cost_Optimization_Pillar.pdf`** | [AWS Well-Architected Cost Optimization Pillar](https://docs.aws.amazon.com/pdfs/wellarchitected/latest/cost-optimization-pillar/wellarchitected-cost-optimization-pillar.pdf) | 1.86 MB / 155p | 206개 항목 (Depth 1~3) | `[시리즈 표준]` 1단 기술 백서 레이아웃, 클라우드 재무 관리(CFM)·리소스 적정 규모 산정 | **[P-01 & P-02 예산/전결 감사 연계]** P-01(예산 3.5억, 박영희 본부장 승인) 및 P-02(예산 4.8억, 송본부장 승인)의 클라우드 인프라 비용 최적화 및 재무관리팀(권팀장) 회계 감사 대응 |

---

### B. `standalone_papers_guides/` — 양식이 서로 다른 개별 AI 인프라·보안 문서 (4편)

학술 2단 논문(SOSP, arXiv), 정부 표준 매트릭스 보고서(NIST), 보안 거버넌스 체크리스트(OWASP) 등 문서마다 레이아웃과 표/다이어그램 구성이 완전히 다른 4편의 개별 PDF입니다. **이종 레이아웃 적응형 파싱(`pymupdf4llm`), 표/수식 보존 마크다운 변환, 기술/보안 복합 질의 에이전트 테스트**에 활용됩니다.

| 파일명 | 출처 (공식 URL) | 용량 / 페이지 수 | 북마크(`get_toc()`) | 레이아웃 및 구조적 특징 | 연결되는 `(주)넥스트AI` 프로젝트 시나리오 |
| :--- | :--- | :---: | :---: | :--- | :--- |
| **`vLLM_PagedAttention_SOSP23.pdf`** | [arXiv:2309.06180 (SOSP '23)](https://arxiv.org/pdf/2309.06180.pdf)<br>*Efficient Memory Management for LLM Serving with PagedAttention* | 1.39 MB / 16p | 32개 항목 (Depth 1~3) | `[개별 양식 1: 2단 학술 논문]` ACM SOSP 2단(Two-column) 레이아웃, 수식, KV 캐시 메모리 다이어그램 및 벤치마크 그래프 다수 포함 | **[P-02: 엔터프라이즈 Agentic RAG 플랫폼 구축]** (홍팀장, 윤에이전트, 장LLM) 핵심 리스크인 **복합 질의 처리 지연시간(Latency) 단축 및 LLM 서빙 처리량 극대화**를 위한 서빙 엔진 기술 근거 |
| **`NIST_AI_RMF_GenAI_Profile.pdf`** | [NIST AI 600-1 공식 표준](https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf)<br>*AI Risk Management Framework: Generative AI Profile (2024)* | 1.12 MB / 64p | 28개 항목 (Depth 1~2) | `[개별 양식 2: 정부 표준 매트릭스]` 다중 열 액션 테이블(GOVERN / MAP / MEASURE / MANAGE 리스크 매핑 표) 중심의 정책 표준 문서 | **[P-03: 차세대 AI 데이터 거버넌스]** (유수석, 임데이터, 조엔지니어) 생성형 AI 고유의 12대 리스크(환각, 데이터 유출, 개인정보 등) 식별 및 법적 컴플라이언스 관리 표준 |
| **`OWASP_LLM_Security_Guide.pdf`** | [OWASP Top 10 for LLM Apps Team 공식 릴리스](https://raw.githubusercontent.com/OWASP/www-project-top-10-for-large-language-model-applications/main/initiatives/llm-top-10-governance-doc/LLM_AI_Security_and_Governance_Checklist-v1.1.pdf)<br>*LLM AI Cybersecurity & Governance Checklist v1.1* | 2.41 MB / 32p | 30개 항목 (Depth 1~3) | `[개별 양식 3: 보안 가이드라인 & 체크리스트]` OWASP Top 10 LLM 위협(Prompt Injection, Data Poisoning 등) 대응 아키텍처 및 단계별 보안 체크리스트 박스 레이아웃 | **[P-02 & P-03 보안/가드레일 연계]** 사내 정보보안관리지침과 연동하여 Agentic RAG 파이프라인의 프롬프트 인젝션 방어, 민감 데이터 실시간 접근 통제 및 보안 감사 체크리스트로 활용 |
| **`MS_GraphRAG_Architecture_2024.pdf`** | [arXiv:2404.16130 (Microsoft Research)](https://arxiv.org/pdf/2404.16130.pdf)<br>*From Local to Global: A GraphRAG Approach to Query-Focused Summarization* | 6.57 MB / 26p | 44개 항목 (Depth 1~3) | `[개별 양식 4: 아키텍처 연구 논문]` 지식 그래프 커뮤니티 탐지(Leiden), Map-Reduce 요약 파이프라인 아키텍처 도식 및 실험 결과 표 포함 | **[P-02: 엔터프라이즈 Agentic RAG 플랫폼 구축]** (홍팀장, 윤에이전트) 사내 정형/비정형/그래프(`org_relationships.txt` 등) 데이터를 통합 연동하고 **이종 데이터 간 환각(Hallucination)을 방지**하기 위한 핵심 아키텍처 레퍼런스 |

---

## 3. `pymupdf` & `pymupdf4llm` 검증 요약

```python
import pymupdf
import pymupdf4llm

doc = pymupdf.open("data/tech_pdfs/aws_waf_series/AWS_Well_Architected_Security_Pillar.pdf")
print("Pages:", len(doc))            # 240
print("TOC:", doc.get_toc()[:3])     # [[1, 'Security Pillar', 1], [1, 'Table of Contents', 3], ...]
md_text = pymupdf4llm.to_markdown(doc, pages=[6, 7, 8])
```

- **무결성 검증**: 8종 전수 `MuPDF` 경고/오류 0건, 정상 오픈(`len(doc) > 0`) 확인 완료
- **북마크(`get_toc()`) 검증**: 8종 전수 계층형 북마크(28개 ~ 282개 항목) 정상 내장 확인 완료
- **마크다운 추출(`pymupdf4llm`) 검증**: 1단 백서, 2단 학술 논문, 다중 열 정책 표 모두 손실 없이 마크다운 변환 가능 확인 완료
