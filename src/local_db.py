import sqlite3
import os
import re
import logging

logger = logging.getLogger("JCBot")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.environ.get("DB_PATH", os.path.join(BASE_DIR, "data", "papers.db"))


class LocalDB:
    def __init__(self, db_path=None):
        self.db_path = db_path or DEFAULT_DB_PATH
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    @staticmethod
    def normalize_doi(doi):
        if not doi:
            return ""
        cleaned = re.sub(r'^https?://(dx\.)?doi\.org/', '', str(doi).strip().lower())
        return cleaned.strip()

    def _get_conn(self):
        # 🛡️ 시놀로지 디스크 I/O 지연 대비 Lock 방어 (20초 대기)
        conn = sqlite3.connect(self.db_path, timeout=20.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _init_db(self):
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS processed_papers (
                        id TEXT PRIMARY KEY,
                        doi TEXT,
                        title TEXT,
                        processed_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_doi ON processed_papers(doi)")
                conn.commit()
        except Exception as e:
            logger.error(f"❌ DB 초기화 에러: {e}")

    def get_count(self):
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM processed_papers")
                return cursor.fetchone()[0]
        except Exception:
            return 0

    def get_all_pmids(self):
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM processed_papers WHERE id IS NOT NULL AND id != ''")
                return set(str(row[0]).strip() for row in cursor.fetchall())
        except Exception:
            return set()

    def is_processed(self, pmid, doi=""):
        try:
            clean_pmid = str(pmid).strip() if pmid else ""
            clean_doi = self.normalize_doi(doi)
            with self._get_conn() as conn:
                cursor = conn.cursor()
                if clean_pmid:
                    cursor.execute("SELECT 1 FROM processed_papers WHERE id = ?", (clean_pmid,))
                    if cursor.fetchone():
                        return True
                if clean_doi:
                    cursor.execute(
                        "SELECT 1 FROM processed_papers WHERE LOWER(doi) = ?",
                        (clean_doi,)
                    )
                    if cursor.fetchone():
                        return True
            return False
        except Exception:
            return False

    def mark_as_processed(self, pmid, doi, title):
        try:
            clean_pmid = str(pmid).strip()
            clean_doi = self.normalize_doi(doi)
            clean_title = str(title).strip()
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT OR IGNORE INTO processed_papers (id, doi, title) VALUES (?, ?, ?)",
                    (clean_pmid, clean_doi, clean_title)
                )
                conn.commit()
        except Exception as e:
            logger.warning(f"⚠️ DB 저장 중 오류 (PMID: {pmid}): {e}")
