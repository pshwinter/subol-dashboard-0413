import os
import re
import logging
import requests
from bs4 import BeautifulSoup
from datetime import datetime, date, timedelta
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
}

# ─── 계정 정보 (.env) ───────────────────────────────────────
STEELDAILY_ID = os.getenv("STEELDAILY_ID", "")
STEELDAILY_PW = os.getenv("STEELDAILY_PW", "")
SCRAPWATCH_ID = os.getenv("SCRAPWATCH_ID", "")
SCRAPWATCH_PW = os.getenv("SCRAPWATCH_PW", "")


# ─── 회사 / 품종 / 방향 상수 ────────────────────────────────

# 회사명 패턴 → 정규화 이름. 긴 패턴(지점명 포함) 먼저.
COMPANY_PATTERNS: list[tuple[str, str]] = [
    # 세아
    ("세아창원특수강", "세아창원특수강"),
    ("세아창특",       "세아창원특수강"),
    ("세아창원",       "세아창원특수강"),
    ("세아베스틸",     "세아베스틸"),
    ("세아제강",       "세아제강"),
    # 동국제강 – 지점별
    ("동국제강 인천",  "동국제강(인천)"),
    ("동국인천",       "동국제강(인천)"),
    ("동국제강 포항",  "동국제강(포항)"),
    ("동국포항",       "동국제강(포항)"),
    ("동국제강",       "동국제강"),
    # 현대제철 – 벤더/지점별 (벤더는 지점보다 먼저 매칭해야 함)
    ("현대제철 벤더",  "현대제철(벤더)"),
    ("현대 벤더",      "현대제철(벤더)"),
    ("현대제철 인천",  "현대제철(인천)"),
    ("현대 인천",      "현대제철(인천)"),
    ("인천제철소",     "현대제철(인천)"),
    ("현대제철 당진",  "현대제철(당진)"),
    ("현대 당진",      "현대제철(당진)"),
    ("당진제철소",     "현대제철(당진)"),
    ("현대제철 포항",  "현대제철(포항)"),
    ("현대제철",       "현대제철"),
    # 포스코 – 제철소 지명 패턴 포함 (긴 것 먼저)
    ("포스코 포항",    "포스코(포항)"),
    ("POSCO 포항",     "포스코(포항)"),
    ("포항제철소",     "포스코(포항)"),
    ("포스코 광양",    "포스코(광양)"),
    ("POSCO 광양",     "포스코(광양)"),
    ("광양제철소",     "포스코(광양)"),
    ("포스코",         "포스코"),
    ("POSCO",          "포스코"),
    # 기타 국내
    ("대한제강",       "대한제강"),
    ("태웅",           "태웅"),
    ("YK스틸",         "YK스틸"),
    ("와이케이스틸",   "YK스틸"),
    ("한국철강",       "한국철강"),
    ("한국특강",       "한국특강"),
    ("한국제강",       "한국제강"),
    ("고려제강",       "고려제강"),
    ("한일",           "한일"),
    ("환영철강",       "환영"),
    ("환영",           "환영"),
    # 일본 (수입 참고용)
    ("동경제철",       "동경제철(일본)"),
    ("동경스틸",       "동경제철(일본)"),
    ("도쿄스틸",       "동경제철(일본)"),
    ("도쿄제철",       "동경제철(일본)"),
    ("Tokyo Steel",    "동경제철(일본)"),
    ("신다찌",         "신다찌(일본)"),
    ("일본제철",       "일본제철(일본)"),
    ("JFE",            "JFE(일본)"),
]

# 공장 미지정 회사 → 지점별 확장 매핑
MULTI_PLANT_COMPANIES: dict[str, list[str]] = {
    "동국제강": ["동국제강(인천)", "동국제강(포항)"],
    "현대제철": ["현대제철(인천)", "현대제철(당진)", "현대제철(포항)"],
    "포스코":   ["포스코(포항)", "포스코(광양)"],
}

IMPORT_COMPANIES: set[str] = {
    norm for _, norm in COMPANY_PATTERNS if "(일본)" in norm
}

# app.py 필터 드롭다운용 (중복 제거 후 순서 유지)
STEEL_COMPANIES = list(dict.fromkeys(norm for _, norm in COMPANY_PATTERNS))

SCRAP_GRADES: dict[str, list[str]] = {
    "생철": ["생철", "신단", "신다찌"],
    "중량": ["중량A", "중량B", "중량C", "중량 A", "중량 B", "중량 C", "HS", "중량"],
    "경량": ["경량", "경량A", "경량B", "압축A", "압축B", "경량 A", "경량 B", "압축 A", "압축 B", "H2"],
    "선반": ["선반", "압축D", "압축 D", "H1"],
}

CHANGE_DIRECTION: dict[str, int] = {
    "인하": -1, "내려": -1, "하락": -1, "낮춰": -1,
    "인상":  1, "올려":  1, "상승":  1, "높여":  1,
    "보합":  0, "동결":  0, "유지":  0,
}


# ─── 필터 키워드 상수 ────────────────────────────────────────

PRICE_KEYWORDS = [
    "구매가격", "구매단가", "스크랩단가", "매입가격", "매입단가",
    "가격 인하", "가격 인상", "가격인하", "가격인상",
    "스크랩 가격", "철 스크랩 가", "특별구매", "유통가격",
    "고시가격", "구매가 ",
]

EXCLUDE_KEYWORDS = [
    "동스크랩", "동 스크랩", "구리스크랩",
    "알루미늄스크랩", "알루미늄 스크랩", "알미늄스크랩",
    "STS스크랩", "STS 스크랩", "스테인리스스크랩",
    "주간시세", "[금주 전망]", "[단기 전망]", "재고]",
    "컬러강판",
]

_SCRAP_CONTEXT_KW = [
    "스크랩", "생철", "중량", "경량", "선반", "특구",
    "단가", "구매", "매입", "인하", "인상", "올려", "내려",
]

# is_price_article 용 — COMPANY_PATTERNS에 없는 단축어만 추가
_ALL_COMPANY_PATTERNS = list(COMPANY_PATTERNS) + [
    ("동국",   "동국제강"),   # "동국제강"보다 짧은 단축어
    ("현대 ",  "현대제철"),   # "현대 XXX" 형태 포괄
]


# ─── 특구 / 운임보조 관련 상수 ──────────────────────────────

_TOKKU_KW   = ("특별구매", "특구")
_UNBAN_KW   = ("운임보조", "운반비 보조", "운임 보조", "운반비보조", "운임 인센티브")
_ALL_GRADE_KW = ("전등급", "전 등급", "모든 등급", "전품종", "전 품종")

# 종료·중단 '행위' 키워드 (단순 명사 "종료 날짜" 등은 제외)
_END_ACT_KW = (
    "종료한다", "종료됩", "종료하기로", "종료했",
    "중단한다", "중단됩", "중단하기로", "중단했",
)

# 기사 본문에서 발행일 추출 패턴 (스틸데일리·스크랩워치: "입력 2026.03.20 10:10")
_PUB_DATE_RE = re.compile(r'입력\s+(\d{4})[.\-](\d{1,2})[.\-](\d{1,2})')

# 기사 목록 HTML에서 기사 링크를 찾는 CSS 선택자 (우선순위 순)
_LIST_ITEM_SELECTORS = [
    "#section-list li",
    "ul.type2 li",
    "ul.type1 li",
    "ul.altlist-webzine li",
    "div.list-block",
    "section.article-list li",
    "div.list-body li",
]

_LIST_LINK_SELECTOR = (
    "h4.titles a[href*='articleView'],"
    "h3 a[href*='articleView'],"
    "h2.altlist-subject a[href*='articleView'],"
    "div.list-titles a[href*='articleView']"
)

_DATE_TAG_SELECTOR = (
    ".list-dated, .dated, time, .date, .byline em, "
    ".altlist-info-item + .altlist-info-item"
)

_BODY_SELECTOR = (
    "#article-view-content-div, .article-veiw-body, "
    ".view-page, .writing-content"
)


# ─── 소형 헬퍼 ──────────────────────────────────────────────

def _get_ref_year_month(date_str: str) -> tuple[int, int]:
    """ISO 날짜 문자열에서 (연, 월) 추출. 파싱 실패 시 현재 연월 반환."""
    try:
        dt = datetime.fromisoformat(date_str)
        return dt.year, dt.month
    except (ValueError, TypeError):
        now = datetime.now()
        return now.year, now.month


def _has_keyword(title: str, text: str, keywords: tuple[str, ...], limit: int = 300) -> bool:
    """제목 또는 본문 앞 limit 자 내에 keywords 중 하나라도 포함되면 True."""
    head = text[:limit]
    return any(kw in title or kw in head for kw in keywords)


def _direction_to_action(change: int) -> str:
    """변동값(원/톤)으로 방향 문자열 결정."""
    return "인상" if change > 0 else ("인하" if change < 0 else "보합")


def _normalize_price(value: int) -> int | None:
    """원/톤 또는 원/kg 값을 원/톤으로 정규화. 범위를 벗어나면 None."""
    if value > 50000:
        return value          # 이미 원/톤
    if 100 <= value <= 2000:
        return value * 1000   # 원/kg → 원/톤
    return None


# ─── 유틸리티 ───────────────────────────────────────────────

def is_price_article(title: str) -> bool:
    """제목 기반 가격 기사 여부 판단."""
    if any(kw in title for kw in EXCLUDE_KEYWORDS):
        return False
    if not any(pat in title for pat, _ in _ALL_COMPANY_PATTERNS):
        return False
    return (
        any(kw in title for kw in PRICE_KEYWORDS)
        or any(kw in title for kw in _SCRAP_CONTEXT_KW)
    )


def extract_company(text: str) -> str:
    """텍스트에서 제강사(지점 포함) 추출. 긴 패턴 우선."""
    for pattern, normalized in COMPANY_PATTERNS:
        if pattern in text:
            return normalized
    return ""


def extract_grade(text: str) -> str:
    """텍스트에서 품종 추출."""
    for grade, keywords in SCRAP_GRADES.items():
        if any(kw in text for kw in keywords):
            return grade
    return ""


def extract_price_info(title: str) -> dict:
    """제목에서 회사·품종·방향·변동폭 간이 추출 (목록 파싱용)."""
    result: dict = {
        "company": extract_company(title),
        "action": "",
        "change": None,
        "grade": extract_grade(title),
    }
    for action_str, direction in CHANGE_DIRECTION.items():
        if action_str in title:
            result["action"] = action_str
            m = re.search(r'(\d+)\s*만\s*원', title)
            if m:
                result["change"] = int(m.group(1)) * 10000 * direction
            else:
                m = re.search(r'(\d[\d,]+)\s*원', title)
                if m:
                    result["change"] = int(m.group(1).replace(",", "")) * direction
            break
    return result


def parse_korean_date(date_str: str) -> str:
    """'YYYY.MM.DD' 또는 'YYYY-MM-DD' 형태의 날짜 문자열을 ISO 형식으로 반환."""
    m = re.search(r'(\d{4})[.\-](\d{1,2})[.\-](\d{1,2})', date_str)
    if m:
        return f"{m.group(1)}-{m.group(2).zfill(2)}-{m.group(3).zfill(2)}"
    return date.today().isoformat()


def parse_article_list(html: str, base_url: str, skip_title_filter: bool = False) -> list[dict]:
    """뉴스아이 CMS 기사 목록 파싱 → 가격 관련 기사만 반환."""
    soup = BeautifulSoup(html, "lxml")

    items: list = []
    for selector in _LIST_ITEM_SELECTORS:
        items = soup.select(selector)
        if items:
            break

    articles = []
    for item in items:
        a_tag = item.select_one(_LIST_LINK_SELECTOR)
        if not a_tag:
            for candidate in item.select("a[href*='articleView']"):
                if candidate.get_text(strip=True):
                    a_tag = candidate
                    break
        if not a_tag:
            continue

        title = a_tag.get_text(strip=True)
        if not skip_title_filter and not is_price_article(title):
            continue

        href = a_tag.get("href", "")
        url = href if href.startswith("http") else base_url.rstrip("/") + href

        date_tag = item.select_one(_DATE_TAG_SELECTOR)
        parsed_date = parse_korean_date(
            date_tag.get_text(strip=True) if date_tag else ""
        )

        articles.append({
            "date": parsed_date,
            "title": title,
            "url": url,
            **extract_price_info(title),
        })

    return articles


# ─── 로그인 세션 ────────────────────────────────────────────

def _login(base_url: str, user_id: str, user_pw: str) -> requests.Session | None:
    """뉴스아이 CMS 로그인 → 인증된 Session 반환. 실패 시 None."""
    if not user_id or not user_pw:
        logger.info(f"[{base_url}] 계정 정보 없음 — 비인증 모드로 진행")
        return None

    session = requests.Session()
    session.headers.update(HEADERS)
    login_url = base_url.rstrip("/") + "/member/login.php"

    try:
        resp = session.post(
            login_url,
            data={"user_id": user_id, "user_pw": user_pw, "tokenDel": "N", "device": "W"},
            timeout=10,
            allow_redirects=True,
        )
        resp.raise_for_status()
        text = resp.text
        if "로그아웃" in text or "logout" in text.lower():
            logger.info(f"[{base_url}] 로그인 성공")
            return session
        # location.replace 리다이렉트가 login 페이지가 아니면 성공으로 간주
        if "location.replace" in text and "login" not in text.split("location.replace")[1][:100].lower():
            logger.info(f"[{base_url}] 로그인 성공 (redirect 감지)")
            return session
        logger.warning(f"[{base_url}] 로그인 실패 — ID/PW 확인 필요")
        return None
    except Exception as exc:
        logger.error(f"[{base_url}] 로그인 오류: {exc}")
        return None


# ─── 본문 가격 파싱 헬퍼 ────────────────────────────────────

def _effective_date(text: str, fallback: str) -> str:
    """본문에서 실제 가격 적용일 추출.

    우선순위: 종료/중단 날짜 > N월M일부터 > D일자로 > D일부터
    월 미기재 시 fallback(기사 발행일)의 연월 사용.
    """
    ref_year, ref_month = _get_ref_year_month(fallback)

    patterns = [
        # 최우선: 종료/중단 날짜 ("14일자로 종료한다", "2월 14일 종료")
        (r'(\d{1,2})월\s*(\d{1,2})일\s*(?:자로)?\s*(?:종료|중단)', True),
        (r'(?<!\d)(\d{1,2})일\s*(?:자로)?\s*(?:종료|중단)',          False),
        # 시작 날짜
        (r'(\d{1,2})월\s*(\d{1,2})일\s*(?:입고분|구매분|부터)',       True),
        (r'(\d{1,2})월\s*(\d{1,2})일\s*(?:자로|부로)',                True),
        (r'(?<!\d)(\d{1,2})일\s*(?:자로|부로|부터|입고분|구매분)',     False),
    ]
    for pattern, has_month in patterns:
        m = re.search(pattern, text)
        if not m:
            continue
        try:
            if has_month:
                return f"{ref_year}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
            else:
                return f"{ref_year}-{ref_month:02d}-{int(m.group(1)):02d}"
        except (ValueError, IndexError):
            continue
    return fallback


def _tokku_end_date(text: str, article_date: str = "") -> str | None:
    """특구 종료일 다음날 반환 ('4월 24일까지', '24일까지' 패턴 지원)."""
    ref_year, ref_month = _get_ref_year_month(article_date)

    m = re.search(r'(\d{1,2})월\s*(\d{1,2})일\s*까지', text)
    if m:
        try:
            return (date(ref_year, int(m.group(1)), int(m.group(2))) + timedelta(days=1)).isoformat()
        except ValueError:
            pass

    m = re.search(r'(?<!\d)(\d{1,2})일\s*까지', text)
    if m:
        try:
            return (date(ref_year, ref_month, int(m.group(1))) + timedelta(days=1)).isoformat()
        except ValueError:
            pass

    return None


def _detect_direction(title: str, text: str) -> tuple[int, str]:
    """기사 제목·본문에서 가격 변동 방향과 액션 문자열 결정.

    우선순위:
    1. 제목에 동결/보합/유지가 있으면 본문 무관하게 0 반환 (최우선)
    2. 명시적 방향 키워드 (인상/인하/보합 등) — 제목 우선, 본문 보조
    3. 운임보조 기사 → 가격 집계 제외 (0 반환)
    4. 특구/특별구매 기사 → 인상(1) 처리
    """
    # 제목에 중립(동결/보합/유지) 키워드가 있으면 본문의 인상/인하를 무시
    for neutral in ("동결", "보합", "유지"):
        if neutral in title:
            return 0, neutral

    for action, direction in CHANGE_DIRECTION.items():
        if action in title or action in text[:300]:
            return direction, action

    is_ending = _has_keyword(title, text, _END_ACT_KW)

    if _has_keyword(title, text, _UNBAN_KW):
        return 0, ""

    if not is_ending and _has_keyword(title, text, _TOKKU_KW, limit=200):
        return 1, "인상"

    return 0, ""


def _apply_tokku(recs: list[dict], title: str, text: str, now: str) -> list[dict]:
    """특구 기사 처리: action='특구' 설정 및 종료일 명시 시 revert 레코드 자동 추가.

    운임보조 기사는 _detect_direction에서 이미 제외되므로 여기선 특구만 처리.
    """
    if _has_keyword(title, text, _UNBAN_KW):
        return recs  # 운임보조: 가격 변동 그대로 유지, action 변경 없음

    if not _has_keyword(title, text, _TOKKU_KW, limit=150):
        return recs

    for r in recs:
        r["action"] = "특구"

    article_date = str(recs[0].get("date", "")) if recs else ""
    revert_date = _tokku_end_date(text, article_date)
    if revert_date:
        for r in recs[:]:  # 슬라이싱으로 복사 — 루프 중 recs에 추가하므로
            ch = r.get("change") or 0
            if ch != 0:
                recs.append({
                    **r,
                    "date": revert_date,
                    "change": -ch,
                    "action": "특구종료",
                    "url": r["url"] + "#종료",
                    "crawled_at": now,
                })
    return recs


def _make_record(
    eff_date: str, source: str, category: str, company: str,
    grade: str, price, change, action: str,
    title: str, url: str, now: str,
) -> dict:
    return {
        "date": eff_date, "source": source, "category": category,
        "company": company, "grade": grade, "price": price,
        "change": change, "action": action,
        "title": title, "url": url, "crawled_at": now,
    }


# ─── 본문 가격 파싱 (메인) ──────────────────────────────────

def _extract_prices_from_body(
    html: str, title: str, url: str, source: str, article_date: str
) -> list[dict]:
    """기사 본문에서 철스크랩 구매가격 변동 추출.

    방법 1 → HTML 테이블
    방법 2 → "X원에서 Y원으로" 절대가격 변동
    방법 3 → 품종별 다단계 텍스트 파싱 (전등급 포함)
    방법 4 → 단일 kg당 변동 fallback
    """
    soup = BeautifulSoup(html, "lxml")
    body = soup.select_one(_BODY_SELECTOR)
    if not body:
        return []

    now  = datetime.now().isoformat()
    text = body.get_text(separator="\n")

    # 본문 페이지에서 실제 발행일 추출 (목록 페이지 날짜보다 우선)
    pub = _PUB_DATE_RE.search(soup.get_text())
    if pub:
        article_date = f"{pub.group(1)}-{int(pub.group(2)):02d}-{int(pub.group(3)):02d}"
    elif article_date == date.today().isoformat():
        # 목록 페이지 날짜 파싱도 실패해 today() 폴백이 된 경우:
        # _effective_date가 현재 월을 기준으로 잘못된 날짜를 만드는 것을 방지.
        # 본문에서 발행일을 찾지 못했으므로 article_date는 그대로 두되
        # _effective_date는 건너뛰고 article_date 자체를 사용한다.
        article_date = date.today().isoformat()

    # 회사명: 제목 우선, 본문에 더 구체적인 지점명이 있으면 교체
    co_title = extract_company(title)
    co_body  = extract_company(text[:300])
    if co_title and co_body and co_body != co_title and co_body.startswith(co_title):
        company = co_body  # 예: 제목 "포스코" + 본문 "포스코(광양)" → 포스코(광양)
    else:
        company = co_title or co_body

    category = "수입" if company in IMPORT_COMPANIES else "국내"
    # article_date가 today() 폴백이면 _effective_date 사용 금지 (날짜 오염 방지)
    eff_date = (
        _effective_date(text, article_date)
        if article_date != date.today().isoformat()
        else article_date
    )
    article_direction, article_action = _detect_direction(title, text)
    fallback_grade        = extract_grade(title) or extract_grade(text[:300])

    results: list[dict] = []

    # ── 방법 1: HTML 테이블 ──────────────────────────────────
    for table in body.select("table"):
        col_grade = col_price = col_change = None

        for row in table.select("tr"):
            cells = [td.get_text(strip=True) for td in row.select("td, th")]
            if not cells:
                continue

            joined = " ".join(cells)
            if any(kw in joined for kw in ["품종", "규격", "구분", "생철", "중량", "경량"]):
                for i, c in enumerate(cells):
                    if any(kw in c for kw in ["품종", "규격", "구분"]):
                        col_grade = i
                    elif any(kw in c for kw in ["가격", "단가", "시세"]):
                        col_price = i
                    elif any(kw in c for kw in ["변동", "증감", "전주"]):
                        col_change = i
                continue

            grade_cell = cells[col_grade] if col_grade is not None and col_grade < len(cells) else cells[0]
            grade = next((g for g, kws in SCRAP_GRADES.items() if any(kw in grade_cell for kw in kws)), "")
            if not grade:
                continue

            price = change = None

            if col_price is not None and col_price < len(cells):
                m = re.search(r'(\d[\d,]+)', cells[col_price])
                if m:
                    price = _normalize_price(int(m.group(1).replace(",", "")))

            if col_change is not None and col_change < len(cells):
                m = re.search(r'([+\-▲▼]?\s*\d[\d,]+)', cells[col_change])
                if m:
                    raw = m.group(1).replace(",", "").replace("▲", "+").replace("▼", "-").replace(" ", "")
                    try:
                        v = int(raw)
                        change = v * 1000 if abs(v) <= 500 else v
                    except ValueError:
                        pass

            if price is None:
                for cell in cells[1:]:
                    m = re.search(r'(\d[\d,]+)', cell)
                    if m:
                        price = _normalize_price(int(m.group(1).replace(",", "")))
                        if price is not None:
                            break

            if price or change:
                action = article_action
                if change is not None:
                    action = _direction_to_action(change)
                results.append(_make_record(
                    eff_date, source, category, company,
                    grade, price, change, action, title, url, now,
                ))

    if results:
        return _apply_tokku(results, title, text, now)

    # ── 방법 2: "X원에서 Y원으로" (per-kg 절대가격 변동) ─────
    m = re.search(r'(\d{3,4})원에서\s*(\d{3,4})원으로', text)
    if m:
        from_kg, to_kg = int(m.group(1)), int(m.group(2))
        if 100 <= from_kg <= 2000 and 100 <= to_kg <= 2000:
            change_kg = to_kg - from_kg
            action = _direction_to_action(change_kg)
            results.append(_make_record(
                eff_date, source, category, company,
                fallback_grade, to_kg * 1000, change_kg * 1000, action, title, url, now,
            ))
            return _apply_tokku(results, title, text, now)

    # ── 방법 3: 품종별 다단계 텍스트 파싱 ───────────────────
    # 전략: 각 가격(N원) 앞 구간(최대 150자)에서 품종·전등급 키워드 탐색
    grade_change_map: dict[str, int] = {}
    all_grade_change: int | None = None

    price_spans = [
        (m.start(), m.end(), int(m.group(1)))
        for m in re.finditer(r'(\d+)\s*원(?:씩)?', text)
        if 1 <= int(m.group(1)) <= 100
    ]
    for pi, (pstart, pend, kg_val) in enumerate(price_spans):
        prev_end = price_spans[pi - 1][1] if pi > 0 else 0
        clause   = text[max(prev_end, pstart - 150): pstart]
        after    = text[pend: pend + 120]

        direction = article_direction
        for act, d in CHANGE_DIRECTION.items():
            if act in clause[-50:] or act in after[:30]:
                direction = d
                break
        if direction == 0:
            if article_direction == 0:
                continue
            direction = article_direction

        change = kg_val * 1000 * direction

        if any(kw in clause or kw in after for kw in _ALL_GRADE_KW):
            all_grade_change = change
            continue

        for grade, keywords in SCRAP_GRADES.items():
            if any(kw in clause for kw in keywords):
                grade_change_map[grade] = change

    if all_grade_change is not None:
        for grade in SCRAP_GRADES:
            if grade not in grade_change_map:
                grade_change_map[grade] = all_grade_change

    if grade_change_map:
        for g, ch in grade_change_map.items():
            results.append(_make_record(
                eff_date, source, category, company,
                g, None, ch, _direction_to_action(ch), title, url, now,
            ))
        return _apply_tokku(results, title, text, now)

    # ── 방법 4: 단일 kg당 변동 fallback ─────────────────────
    kg_m = (
        re.search(r'kg당\s*(\d+)\s*원', text, re.IGNORECASE)
        or re.search(r'(\d+)\s*원\s*(?:씩|/kg|\(kg\))', text, re.IGNORECASE)
    )
    if kg_m:
        kg_val = int(kg_m.group(1))
        if 1 <= kg_val <= 500 and article_direction != 0:
            change = kg_val * 1000 * article_direction
            if any(kw in text for kw in _ALL_GRADE_KW):
                for g in SCRAP_GRADES:
                    results.append(_make_record(
                        eff_date, source, category, company,
                        g, None, change, article_action, title, url, now,
                    ))
            else:
                results.append(_make_record(
                    eff_date, source, category, company,
                    fallback_grade, None, change, article_action, title, url, now,
                ))

    return _apply_tokku(results, title, text, now)


# ─── 인증 크롤러 공통 ────────────────────────────────────────

def _crawl_with_session(
    session: requests.Session | None,
    list_url: str,
    base_url: str,
    source: str,
    skip_title_filter: bool = False,
    body_only: bool = False,
    max_pages: int = 1,
) -> list[dict]:
    """기사 목록 크롤링 → (인증 시) 각 기사 본문에서 가격 추출."""
    http = session or requests.Session()
    if session is None:
        http.headers.update(HEADERS)

    articles: list[dict] = []
    seen_urls: set[str] = set()

    for page in range(1, max_pages + 1):
        paged_url = f"{list_url}&page={page}" if page > 1 else list_url
        try:
            resp = http.get(paged_url, timeout=10)
            resp.raise_for_status()
            resp.encoding = "utf-8"
        except Exception as exc:
            logger.error(f"목록 크롤링 실패 [{source} p{page}]: {exc}")
            break

        page_articles = parse_article_list(resp.text, base_url, skip_title_filter=skip_title_filter)
        new_count = 0
        for art in page_articles:
            if art["url"] not in seen_urls:
                seen_urls.add(art["url"])
                articles.append(art)
                new_count += 1
        if new_count == 0:
            break

    now = datetime.now().isoformat()
    results = []

    for art in articles:
        art["source"] = source
        art["crawled_at"] = now
        art.setdefault("price", None)
        art.setdefault("category", "수입" if art.get("company", "") in IMPORT_COMPANIES else "국내")

        if session is not None:
            try:
                body_resp = session.get(art["url"], timeout=10)
                body_resp.encoding = "utf-8"
                body_records = _extract_prices_from_body(
                    body_resp.text, art["title"], art["url"], source, art["date"]
                )
                if body_records:
                    results.extend(body_records)
                    continue
            except Exception as exc:
                logger.warning(f"본문 크롤링 실패 [{art['url']}]: {exc}")

        if not body_only:
            results.append(art)

    return results


# ─── 신문사별 크롤러 ─────────────────────────────────────────

def crawl_steeldaily() -> list[dict]:
    """스틸데일리 — 시황/가격(SRN14) 섹션 10페이지까지 수집."""
    session = _login("https://www.steeldaily.co.kr", STEELDAILY_ID, STEELDAILY_PW)
    return _crawl_with_session(
        session,
        list_url=(
            "https://www.steeldaily.co.kr/news/articleList.html"
            "?sc_section_code=S1N1&sc_sub_section_code=S2N1"
            "&sc_serial_code=SRN14&view_type=sm"
        ),
        base_url="https://www.steeldaily.co.kr",
        source="스틸데일리",
        max_pages=10,
    )


def crawl_scrapwatch() -> list[dict]:
    """스크랩워치 — 뉴스/가격(S2N39) 5페이지까지."""
    session = _login("https://www.scrapwatch.co.kr", SCRAPWATCH_ID, SCRAPWATCH_PW)
    return _crawl_with_session(
        session,
        list_url="https://www.scrapwatch.co.kr/news/articleList.html?sc_sub_section_code=S2N39&view_type=sm",
        base_url="https://www.scrapwatch.co.kr",
        source="스크랩워치",
        max_pages=5,
    )


def crawl_snmnews() -> list[dict]:
    """철강금속신문 — HTTP only, 비인증."""
    return _crawl_with_session(
        None,
        "http://www.snmnews.com/news/articleList.html?sc_section_code=S1N5&view_type=sm",
        "http://www.snmnews.com",
        "철강금속신문",
    )


# ─── 후처리 ──────────────────────────────────────────────────

def _expand_plants(records: list[dict]) -> list[dict]:
    """공장 미지정 회사 레코드를 지점별 레코드로 확장.

    company='동국제강' → '동국제강(인천)', '동국제강(포항)' 각각 복사.
    이미 지점이 지정된 경우('(' 포함)는 그대로 유지.
    """
    expanded: list[dict] = []
    for rec in records:
        plants = MULTI_PLANT_COMPANIES.get(rec.get("company", ""))
        if plants:
            for plant in plants:
                expanded.append({**rec, "company": plant})
        else:
            expanded.append(rec)
    return expanded


def _find_gaps(
    sd_records: list[dict],
    sw_records: list[dict],
    window_days: int = 14,
) -> list[dict]:
    """스크랩워치에서 스틸데일리에 없는 가격변동 기록 반환.

    같은 (company, grade) 조합이 ±window_days 이내에 없으면 갭으로 판단.
    """
    def to_date(val) -> date | None:
        try:
            return datetime.fromisoformat(str(val)).date()
        except (ValueError, TypeError):
            return None

    gaps: list[dict] = []
    for sw in sw_records:
        sw_company = sw.get("company", "")
        sw_grade   = sw.get("grade") or ""
        sw_date    = to_date(sw.get("date"))
        if sw_date is None:
            continue

        def matches_sd(sd: dict) -> bool:
            if sd.get("company") != sw_company:
                return False
            sd_grade = sd.get("grade") or ""
            if sw_grade and sd_grade and sw_grade != sd_grade:
                return False
            sd_date = to_date(sd.get("date"))
            return sd_date is not None and abs((sd_date - sw_date).days) <= window_days

        if not any(matches_sd(sd) for sd in sd_records):
            gaps.append(sw)
    return gaps


def crawl_all() -> tuple[list[dict], list[dict]]:
    """(스틸데일리 레코드, 검토 대기 레코드) 반환.

    스틸데일리 데이터만 prices.csv에 저장,
    스크랩워치 중 스틸데일리에 없는 것은 pending_review.csv로 분리.
    """
    sd_records  = _expand_plants(crawl_steeldaily())
    sw_records  = _expand_plants(crawl_scrapwatch())
    gap_records = _find_gaps(sd_records, sw_records)
    return sd_records, gap_records
