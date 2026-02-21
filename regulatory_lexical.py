from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from schemas import RagCitation

REG_DOCS_DIR = Path("data/regulations")
REG_INDEX_DB_PATH = Path("data/regulatory_lexical.sqlite")

CASE_DOCUMENTS: Dict[str, List[str]] = {
    "flight": ["eu261_2004.txt"],
    "rail": ["rail_2021_782.txt"],
    "bus_coach": ["bus_181_2011.txt"],
    "sea": ["sea_1177_2010.txt"],
    "parcel_delivery": ["consumer_2011_83.txt"],
    "package_travel": ["package_2015_2302.txt"],
}

ARTICLE_RE = re.compile(r"(?im)^(article\s+\d+[a-z]?(?:\s*[\-:]\s*.*)?)$")
STRUCTURAL_RE = re.compile(r"(?im)^((?:chapter|section|annex)\s+[\w-]+(?:\s*[\-:]\s*.*)?)$")


@dataclass(frozen=True)
class RegSection:
    case_type: str
    doc_name: str
    section_id: str
    article_ref: str
    heading: str
    text: str


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def _tokenize(query: str) -> List[str]:
    return [t for t in re.split(r"[^a-zA-Z0-9]+", (query or "").lower()) if len(t) >= 2]


def _file_fingerprint(path: Path) -> str:
    if not path.exists():
        return "missing"
    content = path.read_text(encoding="utf-8", errors="ignore")
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _split_into_sections(case_type: str, doc_name: str, text: str) -> List[RegSection]:
    raw = text.replace("\r\n", "\n").replace("\r", "\n")
    headings: List[tuple[int, str]] = []
    for m in ARTICLE_RE.finditer(raw):
        headings.append((m.start(), _normalize(m.group(1))))
    for m in STRUCTURAL_RE.finditer(raw):
        headings.append((m.start(), _normalize(m.group(1))))
    headings = sorted(set(headings), key=lambda x: x[0])

    sections: List[RegSection] = []
    if headings:
        for idx, (start, heading) in enumerate(headings):
            end = headings[idx + 1][0] if idx + 1 < len(headings) else len(raw)
            chunk = raw[start:end].strip()
            if len(_normalize(chunk)) < 40:
                continue
            article_ref = heading.split("-")[0].strip()
            sid = f"{case_type}:{doc_name}:{idx+1}"
            sections.append(
                RegSection(
                    case_type=case_type,
                    doc_name=doc_name,
                    section_id=sid,
                    article_ref=article_ref,
                    heading=heading,
                    text=chunk,
                )
            )
        return sections

    # Fallback: paragraph chunks if headings are not detected.
    paragraphs = [p.strip() for p in raw.split("\n\n") if _normalize(p)]
    cur: List[str] = []
    cur_len = 0
    idx = 1
    for p in paragraphs:
        if cur_len + len(p) > 1300 and cur:
            chunk = "\n\n".join(cur)
            sid = f"{case_type}:{doc_name}:{idx}"
            sections.append(
                RegSection(
                    case_type=case_type,
                    doc_name=doc_name,
                    section_id=sid,
                    article_ref=f"Section {idx}",
                    heading=f"Section {idx}",
                    text=chunk,
                )
            )
            idx += 1
            cur = [p]
            cur_len = len(p)
        else:
            cur.append(p)
            cur_len += len(p)
    if cur:
        chunk = "\n\n".join(cur)
        sid = f"{case_type}:{doc_name}:{idx}"
        sections.append(
            RegSection(
                case_type=case_type,
                doc_name=doc_name,
                section_id=sid,
                article_ref=f"Section {idx}",
                heading=f"Section {idx}",
                text=chunk,
            )
        )
    return sections


class RegulatoryLexicalRetriever:
    def __init__(self) -> None:
        self._ensure_index()

    def _collect_sections(self) -> List[RegSection]:
        out: List[RegSection] = []
        for case_type, docs in CASE_DOCUMENTS.items():
            for doc_name in docs:
                path = REG_DOCS_DIR / doc_name
                if not path.exists():
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
                out.extend(_split_into_sections(case_type, doc_name, text))
        return out

    def _current_fingerprint(self) -> str:
        pieces: List[str] = []
        for _, docs in CASE_DOCUMENTS.items():
            for doc_name in docs:
                pieces.append(f"{doc_name}:{_file_fingerprint(REG_DOCS_DIR / doc_name)}")
        return "|".join(pieces)

    def _ensure_index(self) -> None:
        REG_INDEX_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(REG_INDEX_DB_PATH) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reg_sections (
                    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                    section_id TEXT UNIQUE NOT NULL,
                    case_type TEXT NOT NULL,
                    doc_name TEXT NOT NULL,
                    article_ref TEXT NOT NULL,
                    heading TEXT NOT NULL,
                    text TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")

            fp = self._current_fingerprint()
            row = conn.execute("SELECT value FROM meta WHERE key='fingerprint'").fetchone()
            cached = row[0] if row else None
            if cached == fp:
                return

            sections = self._collect_sections()
            conn.execute("DELETE FROM reg_sections")
            conn.execute("DROP TABLE IF EXISTS reg_sections_fts")
            conn.execute(
                """
                CREATE VIRTUAL TABLE reg_sections_fts
                USING fts5(heading, text, content='reg_sections', content_rowid='rowid')
                """
            )

            for s in sections:
                cur = conn.execute(
                    """
                    INSERT INTO reg_sections (section_id, case_type, doc_name, article_ref, heading, text)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (s.section_id, s.case_type, s.doc_name, s.article_ref, s.heading, s.text),
                )
                rowid = cur.lastrowid
                conn.execute(
                    "INSERT INTO reg_sections_fts(rowid, heading, text) VALUES (?, ?, ?)",
                    (rowid, s.heading, s.text),
                )

            conn.execute(
                "INSERT INTO meta (key, value) VALUES ('fingerprint', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (fp,),
            )
            conn.commit()

    def retrieve(self, case_type: str, query: str, k: int = 4) -> List[RagCitation]:
        tokens = _tokenize(query)
        fts_query = " OR ".join(tokens[:18]) if tokens else "delay OR compensation OR refund"
        out: List[RagCitation] = []
        with sqlite3.connect(REG_INDEX_DB_PATH) as conn:
            try:
                rows = conn.execute(
                    """
                    SELECT s.section_id, s.doc_name, s.article_ref, s.heading, s.text, bm25(reg_sections_fts) AS bm25_score
                    FROM reg_sections_fts
                    JOIN reg_sections s ON s.rowid = reg_sections_fts.rowid
                    WHERE s.case_type = ? AND reg_sections_fts MATCH ?
                    ORDER BY bm25_score
                    LIMIT ?
                    """,
                    (case_type, fts_query, int(k)),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = conn.execute(
                    """
                    SELECT section_id, doc_name, article_ref, heading, text, 9.0 AS bm25_score
                    FROM reg_sections
                    WHERE case_type = ? AND (lower(heading) LIKE ? OR lower(text) LIKE ?)
                    LIMIT ?
                    """,
                    (case_type, f"%{query.lower()}%", f"%{query.lower()}%", int(k)),
                ).fetchall()

        for section_id, doc_name, article_ref, heading, text, bm25_score in rows:
            score = 1.0 / (1.0 + abs(float(bm25_score)))
            title = f"{doc_name} | {article_ref} | {heading}"
            out.append(RagCitation(chunk_id=str(section_id), title=title, text=str(text), score=score))
        return out


def infer_article_reference(citation: RagCitation) -> Optional[str]:
    m = re.search(r"\b(Article\s+\d+[a-z]?)\b", citation.title, flags=re.IGNORECASE)
    if m:
        return _normalize(m.group(1)).title()
    m2 = re.search(r"\b(Section\s+\d+)\b", citation.title, flags=re.IGNORECASE)
    if m2:
        return _normalize(m2.group(1)).title()
    return None
