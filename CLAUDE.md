# 철스크랩 수불현황 대시보드 — 프로젝트 가이드

## 실행 방법

```bash
cd C:\Users\user\Desktop\260331_project\0413 project
python -m streamlit run dashboard/app.py --server.port 8502
```

브라우저: http://localhost:8502

---

## 프로젝트 구조

```
0403_new/
├── dashboard/
│   ├── app.py          # Streamlit 메인 앱 (전체 UI + 렌더링 로직)
│   └── charts.py       # Plotly 차트 함수 (make_monthly_chart, make_receipt_detail_bar, make_supplier_bar)
├── pipeline/
│   ├── loader.py       # Excel 파일 로드 + 구분 분류 유틸 (build_gubun_classifier, classify_gubun_series)
│   ├── transform.py    # 데이터 표준화 (standardize_movement_df, standardize_expected_df, SITE_MAP)
│   ├── metrics.py      # 일별 입고/사용/재고 집계 (bucket_metrics → daily_recv_use_inv)
│   ├── supplier.py     # 공급사별 입고량 집계 (build_supplier_summary)
│   ├── rag.py          # 하이브리드 RAG (BM25+TF-IDF+RRF) 인덱서 및 검색
│   └── graph.py        # LangGraph 라우터 (RAG/분석 분기) + 코드 실행 에이전트
├── report/
│   └── exporter.py     # Excel 보고서 출력 (export_workbook_bytes)
├── korea_provinces.geojson  # 한국 17개 시도 GeoJSON (choropleth용)
└── run.py              # 진입점 (streamlit run 실행)
```

---

## 데이터 파일 (사용자 업로드)

| 파일 | 시트 | 설명 |
|------|------|------|
| 수불 데이터 (.xlsx) | 입고 | 실적 입고 데이터 |
| | 사용 | 실적 사용 데이터 |
| | 예상입고량 | 계획 입고 (Wide 형식: 날짜별 컬럼) |
| | 예상사용량 | 계획 사용 (Wide 형식) |
| | 기초재고 | 기초재고 (Wide 형식: 날짜별 컬럼) |
| 기준정보 (.xlsx) | 기준정보 | 공급사별 구분 O 표시 |
| | 기준정보2 | 등급 → 구분 매핑 |
| | 등급구분 | 등급 → 등급대분류 매핑 |
| | 지역구분 | 공급사 → 지역대구분/소구분 |

---

## 핵심 데이터 흐름

```
Excel 업로드
  → load_workbooks() [loader.py]
  → bucket_metrics() → daily_recv_use_inv() [metrics.py]
      : 일별 입고/사용/재고 + is_actual 컬럼 생성
      : 기초재고 기반 누적 재고 계산
  → build_supplier_summary() [supplier.py]
  → load_all() 캐시 [app.py]

입고 상세 섹션:
  receipt_raw → _preprocess_receipt()
      : 사소구분 매핑 (SITE_MAP)
      : 날짜 = 입하일시 - 7시간 (비즈니스 일자)
      : 등급대분류 매핑 (grade_lookup)
      : 구분 분류 (classify_gubun_series)
      : 지역 병합 (region_ref)
```

---

## 주요 설계 결정

### 사소구분 (SITE_MAP)
`광양/광양소 → 광양소`, `포항/포항소 → 포항소`

### 날짜 기준
- **실적**: `입하일시 - 7시간` → 당일 07:00~익일 06:59 = 당일
- **계획**: 원본 날짜 그대로 (오프셋 없음)

### 구분 분류 우선순위 (`classify_gubun_series`)
1. 기준정보에 없는 공급사 → 유통
2. 회수 표시 공급사 → 등급 무관 전부 회수
3. 수입 표시 공급사 → 수입
4. 기준정보2에서 해당 등급 매칭 구분 → 해당 구분
5. 매칭 없음 → 유통

### 캐시 무효화
`_LOAD_VERSION = "v9"` — 코드 변경 시 버전 올리면 `@st.cache_data` 강제 갱신

### 공급사 필터 합계 vs 전체
- **전체 선택 (select all)**: 공급사별로 각각 분리된 막대 표시
- **합계 선택**: `collapse_supplier=True` → 모든 공급사를 "합계" 하나로 묶어 합산 막대

### 주차 계산
`_week_start(d)`: 해당 날짜가 속한 **일요일~토요일** 주의 일요일 반환
```python
d - timedelta(days=(d.weekday() + 1) % 7)
```

---

## 섹션 구성 (app.py render())

1. **월간 추이**: 탭A(단일 월 심층 — 실적/계획/KPI 박스) / 탭B(멀티 월 나란히 비교 그룹 막대)
2. **입고 상세**: 기간/사소/구분/공급사/품목/등급 필터 → 단일 기간 또는 A vs B 기간 비교 모드
3. **구분별 가격정책 신호**: 구분별(유통/MOU/전용야드) 입고량 변화율 + 정책 신호 자동 감지 (전월/전주 대비)
4. **지역별 입고 현황 + AI 챗봇**: 좌우 2컬럼 배치
   - 지역 지도: Choropleth (연한→진한 파랑)
   - AI 챗봇: LangGraph (RAG 조회 / 데이터 분석 자동 라우팅, gubun_summary 포함)

---

## 지도 (Choropleth)

- **GeoJSON**: `korea_provinces.geojson` — `name_eng` 속성으로 지역 매핑
- **색상**: `#dbeafe`(연한 파랑) → `#1e3a8a`(진한 파랑), 최대값 기준 선형 보간
- **ENG_TO_REGION 매핑**: Seoul/Incheon/Gyeonggi-do → 경인, Busan/Ulsan/Gyeongsangnam-do → 경남, 등
- folium + branca Figure로 렌더링, Streamlit `st_html`로 삽입

---

## AI 챗봇 (LangGraph)

`pipeline/graph.py` — `build_graph(daily, supplier_df, retriever, api_key, gubun_summary)`:
- **라우터**: 질문을 RAG 또는 분석(코드 실행) 경로로 자동 분류
- **RAG 경로**: BM25+TF-IDF 하이브리드 서치 → RRF 리랭킹 → GPT 답변
- **분석 경로**: GPT가 pandas 코드 생성 → exec() 실행 → 결과 해석

RAG 인덱스: `@st.cache_resource`로 세션 내 1회만 빌드

---

## 메일 발송

`_send_gmail()` — Gmail SMTP SSL (포트 465)
- 크롤링 스케줄: 매일 07:00, 13:00 (Asia/Seoul)
- 법인 네트워크 환경에서는 외부 SMTP 차단으로 발송 불가
- 내부 SMTP 서버 정보 확인 필요 (현재 미해결)

---

## 알려진 이슈 / 미완 항목

| 항목 | 상태 | 비고 |
|------|------|------|
| 메일 발송 | 미해결 | 법인 방화벽이 외부 SMTP(Gmail 465/587) 차단. 내부 SMTP 서버 정보 필요 |
| `use_container_width` 경고 | 무시 가능 | Streamlit 버전 이슈, 2025-12-31 이후 deprecated. `width='stretch'`로 교체 예정 |

---

## 코드 변경 시 체크리스트

- `_LOAD_VERSION` 버전 올리기 (캐시 무효화)
- `loader.py`의 `LoadedData` 필드 추가 시 `load_all()` 반환값도 수정
- 새 시트 추가 시 `loader.py`의 `load_workbooks()`에 `try/except` 패턴으로 추가
- GeoJSON 지역 매핑 변경 시 `ENG_TO_REGION` dict 수정 (`_render_region_map` 내부)
