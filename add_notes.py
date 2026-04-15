# -*- coding: utf-8 -*-
"""
PPT 발표자 노트(대본) 삽입 스크립트
총 발표 시간: 약 7분 (동영상 약 3분 포함 → 실제 발표 약 4분)
슬라이드 수: 17장
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

from pptx import Presentation
from pptx.util import Pt
from pptx.dml.color import RGBColor

SRC = r'C:\Users\user\Desktop\260331_project\26-1차 포스코그룹_AI활용전문가_과정_사무계_포스코_박승희.pptx'
DST = r'C:\Users\user\Desktop\260331_project\26-1차 포스코그룹_AI활용전문가_과정_사무계_포스코_박승희_대본.pptx'
PPT = DST  # 저장 경로 (하위 코드 호환)

# ── 슬라이드별 대본 ────────────────────────────────────────────────
# 총 17슬라이드 / 발표 7분 (동영상 3분 포함, 실제 발표 약 4분)
NOTES = [

    # ── Slide 1: 표지 (약 10초) ────────────────────────────────────
    """안녕하세요. 저는 포스코 구매팀에서 철스크랩 구매를 담당하고 있는 박승희입니다.
오늘은 제가 이번 4주 AI 교육을 통해 직접 만든 '철스크랩 구매 대시보드'를 발표하겠습니다.
수불 관리, 시장 가격 모니터링, AI 질의응답을 하나로 통합한 실무 시스템입니다.""",

    # ── Slide 2: 목차 (약 10초) ────────────────────────────────────
    """발표는 크게 네 파트로 구성됩니다.
프로젝트 개요, 시스템 소개와 주요 기능, 개발 진행 과정, 마지막으로 기대효과와 향후 계획 순서로 말씀드리겠습니다.""",

    # ── Slide 3: 섹션 01 — 프로젝트 개요 (약 3초) ───────────────────
    """먼저 이 프로젝트가 시작된 배경입니다.""",

    # ── Slide 4: 문제 정의 (약 35초) ──────────────────────────────
    """철스크랩 구매 담당자로서 매일 반복하던 수작업이 이 프로젝트의 출발점이었습니다.

첫째, 매일 엑셀로 입고·사용·재고를 수동 집계하다 보니 오류 위험과 반복 업무 부담이 컸습니다.
둘째, 내부 수불 데이터와 외부 시장 가격 정보가 따로 관리돼 종합적인 판단이 어려웠습니다.
셋째, 원하는 기간·품목·사소별 즉시 조회가 안 돼 구매 판단이 늦어졌습니다.
넷째, 타사 구매단가 변동을 직접 뉴스 사이트에서 찾아야 해 정보 누락 위험이 있었습니다.

데이터는 있는데, 판단할 수가 없었습니다. 이 경험에서 프로젝트가 시작됐습니다.""",

    # ── Slide 5: 섹션 02 — 시스템 & 대시보드 (약 3초) ──────────────
    """이 문제들을 해결하기 위해 만든 시스템을 소개합니다.""",

    # ── Slide 6: 해결 방향 / 시스템 구조 (약 25초) ──────────────────
    """세 가지 핵심 기능을 하나의 대시보드로 통합했습니다.

수불 현황 시각화, AI 챗봇, 구매단가 자동 모니터링입니다.
Streamlit 기반 웹 앱으로 구현했고, 시각화는 Plotly, 챗봇은 LangGraph와 GPT-4o-mini, 크롤링은 Selenium과 APScheduler를 활용했습니다.
엑셀 파일 업로드부터 보고서 출력까지 전 과정이 자동화돼 있습니다.""",

    # ── Slide 7: 파이프라인 & 시각화 (약 25초) ──────────────────────
    """엑셀 파일을 업로드하면 네 단계가 자동으로 작동합니다.

Loader에서 데이터를 불러오고, Transform에서 사소구분 통일과 날짜 기준 보정을 합니다.
날짜 기준은 07시를 기점으로 하루를 정의해 교대근무 패턴을 반영했습니다.
Analysis에서 일별 입고·사용·재고를 집계하고, Outcome에서 차트와 전국 지도로 시각화됩니다.
계획 대비 실적 비교, 공급사별·지역별 입고 현황을 한 화면에서 바로 확인할 수 있습니다.""",

    # ── Slide 8: RAG 기반 AI 챗봇 (약 25초) ─────────────────────────
    """수치를 외우지 않아도 그냥 물어보면 됩니다.

LangGraph 라우터가 질문 유형을 자동 판단해 두 경로로 분기합니다.
단순 조회는 RAG 경로로 즉시 답변하고, 날짜나 공급사 조건이 있는 계산 질문은 분석 경로로 GPT가 pandas 코드를 생성해 직접 계산합니다.
수불 데이터에 없는 내용은 절대 추측하지 않고, 데이터가 없으면 없다고 답하도록 설계했습니다.""",

    # ── Slide 9: 시장 구매단가 자동 모니터링 (약 25초) ───────────────
    """매일 아침 뉴스를 직접 찾아보지 않아도 됩니다.

매일 07시와 13시, 두 차례 스틸데일리와 스크랩워치를 자동으로 크롤링합니다.
기사에서 인상·인하·동결을 자동 판단하고 변동폭을 추출해 이력으로 저장합니다.
이 정보는 대시보드 차트와 AI 입고 요약에 자동으로 반영되어, 가격 협상 레버리지로 활용할 수 있습니다.""",

    # ── Slide 10: 주요 화면 시연 (약 10초 + 동영상 3분) ────────────
    """지금까지 설명한 기능들을 실제 화면으로 보겠습니다.

[동영상 재생 — 약 3분]

동영상에서는 수불 시각화, AI 챗봇 질의응답, 구매단가 모니터링 화면을 순서대로 확인하실 수 있습니다.""",

    # ── Slide 11: 섹션 03 — 개발 진행 과정 (약 3초) ─────────────────
    """다음은 이 시스템을 어떻게 만들었는지 개발 과정입니다.""",

    # ── Slide 12: 개발 과정 (약 15초) ──────────────────────────────
    """개발 경험이 없는 업무 담당자가 AI 도구를 활용해 만든 시스템입니다.

메모장으로 요구사항을 정리하고, Cursor로 초기 프로토타입을 만들었습니다.
이후 Claude Superpowers Brainstorming으로 전체 구조를 재설계하고, Claude Code로 LangGraph 챗봇과 크롤링을 반복 구현했습니다.
마지막으로 UI-pro-max 스킬과 Google Stitch를 적용해 화면을 완성했습니다.""",

    # ── Slide 13: 기술 이슈 & 해결 (약 20초) ───────────────────────
    """만들면서 여러 이슈를 만났습니다.

날짜 포함 질문이 RAG로 잘못 분류돼 오답이 반환됐을 때는, 날짜 포함 질문은 무조건 분석 경로로 라우팅하도록 기준을 명시해 해결했습니다.
AI가 없는 수치를 만들어내는 환각 문제는, 코드 실행 결과를 먼저 검증해 실패 시 즉시 "데이터 없음"을 반환하는 방식으로 차단했습니다.
이슈마다 원인을 먼저 파악하고 Claude와 함께 해결 방법을 찾았습니다.""",

    # ── Slide 14: 섹션 04 — 기대효과 & 향후 계획 (약 3초) ──────────
    """마지막으로 기대효과와 앞으로의 계획입니다.""",

    # ── Slide 15: 기대효과 (약 15초) ───────────────────────────────
    """반복 업무는 줄이고, 판단에 집중할 수 있게 됩니다.

일별 수불 집계에 걸리던 30~60분이 수 분 내로 단축되고, 시장 가격 수집은 하루 2회 자동화됩니다.
데이터 조회는 챗봇으로 즉시 가능하고, 계획 대비 실적이 시각화돼 구매 의사결정 근거가 명확해집니다.
비개발자도 AI 도구로 실무 시스템을 직접 구축할 수 있다는 것도 이번에 확인했습니다.""",

    # ── Slide 16: 향후 계획 및 회고 (약 18초) ──────────────────────
    """향후 세 가지 과제가 있습니다.

사내 ERP·MES와 연동해 엑셀 없이 실시간 데이터를 반영하고, 구매단가 예측 모델을 추가하고, 사내망 서버에 배포해 팀 전체가 활용하도록 할 계획입니다.

이번에 가장 크게 배운 것은, 업무를 가장 잘 아는 사람이 AI 도구를 활용하면 개발자 없이도 실제 동작하는 시스템을 만들 수 있다는 것입니다.
기술 이름보다, 이 기술이 내 업무의 어떤 문제를 해결하는가를 먼저 생각하는 것이 핵심이었습니다.""",

    # ── Slide 17: 마무리 (약 5초) ──────────────────────────────────
    """데이터를 보는 방식이 바뀌면, 일하는 방식이 바뀝니다.
감사합니다. 질문 있으시면 말씀해 주세요.""",
]


# ── PPT 노트 삽입 ─────────────────────────────────────────────────
prs = Presentation(SRC)
slides = list(prs.slides)

assert len(slides) == len(NOTES), \
    f"슬라이드 수({len(slides)})와 대본 수({len(NOTES)})가 다릅니다."

NSMAP = {
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
}

def set_slide_notes(slide, text):
    """슬라이드 노트란에 텍스트 설정 (플레이스홀더 없으면 생성)"""
    import lxml.etree as etree

    notes_slide = slide.notes_slide
    spTree = notes_slide._element.find(
        './/{http://schemas.openxmlformats.org/presentationml/2006/main}cSld'
        '/{http://schemas.openxmlformats.org/presentationml/2006/main}spTree'
    )
    # p: 네임스페이스
    P = 'http://schemas.openxmlformats.org/presentationml/2006/main'
    A = 'http://schemas.openxmlformats.org/drawingml/2006/main'

    # 기존 노트 placeholder 찾기 (ph type=body idx=1)
    existing = None
    for sp in spTree.findall(f'{{{P}}}sp'):
        nvPr = sp.find(f'.//{{{P}}}ph')
        if nvPr is not None and nvPr.get('idx') == '1':
            existing = sp
            break

    if existing is not None:
        # 기존 txBody 초기화
        txBody = existing.find(f'{{{P}}}txBody')
        if txBody is None:
            txBody = etree.SubElement(existing, f'{{{P}}}txBody')
        # 기존 단락 제거
        for p_elem in txBody.findall(f'{{{A}}}p'):
            txBody.remove(p_elem)
    else:
        # 새 노트 placeholder 생성
        sp_xml = f'''<p:sp xmlns:p="{P}" xmlns:a="{A}">
  <p:nvSpPr>
    <p:cNvPr id="3" name="Notes Placeholder 2"/>
    <p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>
    <p:nvPr><p:ph type="body" idx="1"/></p:nvPr>
  </p:nvSpPr>
  <p:spPr/>
  <p:txBody>
    <a:bodyPr/>
    <a:lstStyle/>
  </p:txBody>
</p:sp>'''
        existing = etree.fromstring(sp_xml)
        spTree.append(existing)
        txBody = existing.find(f'{{{P}}}txBody')

    # 줄별로 단락 추가
    lines = text.strip().split('\n')
    for line in lines:
        p_elem = etree.SubElement(txBody, f'{{{A}}}p')
        if line.strip():
            r_elem = etree.SubElement(p_elem, f'{{{A}}}r')
            rPr = etree.SubElement(r_elem, f'{{{A}}}rPr')
            rPr.set('lang', 'ko-KR')
            rPr.set('dirty', '0')
            t_elem = etree.SubElement(r_elem, f'{{{A}}}t')
            t_elem.text = line
        else:
            # 빈 줄 = 빈 단락
            endParaRPr = etree.SubElement(p_elem, f'{{{A}}}endParaRPr')
            endParaRPr.set('lang', 'ko-KR')


for i, (slide, note_text) in enumerate(zip(slides, NOTES)):
    set_slide_notes(slide, note_text)
    print(f"Slide {i+1}: 노트 입력 완료")

prs.save(DST)
print(f"\n저장 완료: {DST}")
