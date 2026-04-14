import threading
import pandas as pd
from pathlib import Path
from datetime import datetime

DATA_DIR = Path(__file__).parent / "data"
PRICES_CSV = DATA_DIR / "prices.csv"
REVIEW_CSV  = DATA_DIR / "pending_review.csv"

_csv_lock = threading.Lock()

COLUMNS = [
    "date", "source", "category", "company", "grade",
    "price", "change", "action", "title", "url", "crawled_at",
]

REVIEW_COLUMNS = COLUMNS + ["review_status"]   # 대기 / 반영 / 미반영


# ─── prices.csv ────────────────────────────────────────────

def ensure_csv() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    if not PRICES_CSV.exists():
        pd.DataFrame(columns=COLUMNS).to_csv(PRICES_CSV, index=False)


def load_prices() -> pd.DataFrame:
    ensure_csv()
    df = pd.read_csv(PRICES_CSV, dtype={"price": "float64", "change": "float64"})
    if df.empty:
        return pd.DataFrame(columns=COLUMNS)
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df[COLUMNS]


def save_records(records: list[dict]) -> int:
    """신규 레코드 추가. (date, source, url, grade, company) 기준 중복 제거. 추가 건수 반환."""
    if not records:
        return 0
    with _csv_lock:
        ensure_csv()
        existing = load_prices()
        DEDUP = ["date", "source", "url", "grade", "company"]
        new_df = pd.DataFrame(records, columns=COLUMNS)
        combined = pd.concat([existing, new_df], ignore_index=True)
        combined[DEDUP] = combined[DEDUP].fillna("")
        before = len(existing.drop_duplicates(subset=DEDUP))
        combined = combined.drop_duplicates(subset=DEDUP, keep="last")
        has_graded = combined[combined["grade"] != ""][["date", "source", "url"]].drop_duplicates()
        if not has_graded.empty:
            key_set = set(map(tuple, has_graded.values.tolist()))
            drop_mask = (
                combined.apply(lambda r: (r["date"], r["source"], r["url"]), axis=1).isin(key_set)
                & (combined["grade"] == "")
            )
            combined = combined[~drop_mask]
        combined.to_csv(PRICES_CSV, index=False)
        return len(combined) - before


# ─── pending_review.csv ────────────────────────────────────

def _ensure_review_csv() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    if not REVIEW_CSV.exists():
        pd.DataFrame(columns=REVIEW_COLUMNS).to_csv(REVIEW_CSV, index=False)


def load_pending_review() -> pd.DataFrame:
    _ensure_review_csv()
    df = pd.read_csv(REVIEW_CSV, dtype={"price": "float64", "change": "float64"})
    if df.empty:
        return pd.DataFrame(columns=REVIEW_COLUMNS)
    for col in REVIEW_COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df[REVIEW_COLUMNS]


def save_pending_review(records: list[dict]) -> int:
    """갭 레코드 추가. (url, grade) 기준 중복 제거. 추가 건수 반환."""
    if not records:
        return 0
    with _csv_lock:
        _ensure_review_csv()
        existing = load_pending_review()
        DEDUP = ["url", "grade"]
        for r in records:
            r.setdefault("review_status", "대기")
        new_df = pd.DataFrame(records, columns=REVIEW_COLUMNS)
        combined = pd.concat([existing, new_df], ignore_index=True)
        combined[DEDUP] = combined[DEDUP].fillna("")
        before = len(existing.drop_duplicates(subset=DEDUP))
        combined = combined.drop_duplicates(subset=DEDUP, keep="first")
        combined.to_csv(REVIEW_CSV, index=False)
        return len(combined) - before


def update_review_status(url: str, grade: str, status: str) -> None:
    """특정 레코드의 review_status 변경."""
    with _csv_lock:
        df = load_pending_review()
        mask = (df["url"] == url) & (df["grade"].fillna("") == (grade or ""))
        df.loc[mask, "review_status"] = status
        df.to_csv(REVIEW_CSV, index=False)


def approve_review_record(record: dict) -> None:
    """검토 레코드를 prices.csv에 저장하고 status를 '반영'으로 변경."""
    r: dict = {}
    for k in COLUMNS:
        val = record.get(k)
        if hasattr(val, "isoformat"):
            val = val.date().isoformat() if hasattr(val, "date") else val.isoformat()
        r[k] = val
    save_records([r])
    update_review_status(
        str(record.get("url", "")),
        str(record.get("grade") or ""),
        "반영",
    )


# ─── 수동 입력 ─────────────────────────────────────────────

def add_manual_record(
    date: str,
    company: str,
    grade: str,
    price: int,
    change: int,
    source: str = "수동입력",
) -> None:
    action = "인상" if change > 0 else ("인하" if change < 0 else "보합")
    record = {
        "date": date,
        "source": source,
        "company": company,
        "grade": grade,
        "price": price,
        "change": change,
        "action": action,
        "title": f"[수동] {company} {grade} {price:,}원/톤 ({action} {abs(change):,}원)",
        "url": "",
        "crawled_at": datetime.now().isoformat(),
    }
    save_records([record])
