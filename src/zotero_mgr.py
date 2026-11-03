import os
import re
import time
import logging
import warnings

# 🛡️ pyzotero 내부 datetime 모듈 DeprecationWarning 로그 스팸 차단
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*WheneverDeprecationWarning.*")

from pyzotero import zotero

logger = logging.getLogger("JCBot")


def _clean_env(key, default=""):
    val = os.environ.get(key, default)
    if val is None:
        return default
    return str(val).strip().strip('"').strip("'").strip()


class ZoteroManager:
    def __init__(self):
        self.user_id = _clean_env("ZOTERO_USER_ID")
        self.api_key = _clean_env("ZOTERO_API_KEY")
        self.library_type = _clean_env("ZOTERO_LIBRARY_TYPE", "user") or "user"
        self.candidates_col_id = _clean_env("ZOTERO_CANDIDATES_ID")

        if (
            not all([self.user_id, self.api_key, self.candidates_col_id])
            or self.user_id.startswith("your_")
            or self.api_key.startswith("your_")
        ):
            logger.info("ℹ️ Zotero 환경변수가 설정되지 않아 Zotero 연동은 건너뜁니다 (로컬/알림 전용 모드).")
            self.zot = None
            return

        try:
            self.zot = zotero.Zotero(self.user_id, self.library_type, self.api_key)
        except Exception as e:
            logger.error(f"❌ Zotero 초기화 실패: {e}")
            self.zot = None

    def _execute_with_retry(self, func, *args, max_retries=3, **kwargs):
        """API Rate limit 방어용 백오프 래퍼"""
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.warning(f"⚠️ Zotero API 일시 오류 (시도 {attempt+1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep((2 ** attempt) * 2)
                else:
                    return None

    def _clean_doi(self, doi):
        if not doi:
            return ""
        return re.sub(r'^https?://(dx\.)?doi\.org/', '', str(doi).strip().lower())

    def add_paper(self, paper):
        """분석 코멘트 없이 논문 메타데이터만 깔끔하게 Zotero에 저장"""
        if not self.zot:
            return False

        try:
            template = self._execute_with_retry(self.zot.item_template, 'journalArticle')
            if not template:
                return False

            template['title'] = str(paper.get('title', 'Unknown Title')).strip()
            template['DOI'] = self._clean_doi(paper.get('doi', ''))
            template['abstractNote'] = str(paper.get('abstract', '')).strip()
            template['publicationTitle'] = str(paper.get('journal', '')).strip()
            template['date'] = str(paper.get('date', '')).strip()
            template['url'] = str(paper.get('link', '')).strip()
            template['extra'] = f"PMID: {paper.get('id', '')}"

            creators = []
            for author in paper.get('raw_authors', []):
                # 1. 저자 정보가 딕셔너리 형태일 때 (PubMed 정상 파싱)
                if isinstance(author, dict):
                    last = str(author.get('LastName', '')).strip()
                    first = str(author.get('ForeName', author.get('Initials', ''))).strip()

                    if last and first:
                        creators.append({'creatorType': 'author', 'lastName': last, 'firstName': first})
                    elif last:  # 🚀 이름 없이 성만 있을 때 Zotero 에러 방지를 위해 단일 이름(name)으로 묶기
                        creators.append({'creatorType': 'author', 'name': last})
                    elif first:
                        creators.append({'creatorType': 'author', 'name': first})

                # 2. 저자 정보가 단순 텍스트일 때 대비
                elif isinstance(author, str):
                    parts = author.strip().split(' ')
                    if len(parts) >= 2:
                        creators.append({'creatorType': 'author', 'lastName': parts[-1], 'firstName': " ".join(parts[:-1])})
                    elif len(parts) == 1 and parts[0]:
                        creators.append({'creatorType': 'author', 'name': parts[0]})

            # 🚀 저자 정보가 아예 없을 때의 최후의 안전장치
            if not creators:
                creators.append({'creatorType': 'author', 'name': 'Unknown Author'})

            template['creators'] = creators
            template['collections'] = [self.candidates_col_id]

            resp = self._execute_with_retry(self.zot.create_items, [template])

            if resp and resp.get('successful'):
                logger.info(f"💾 Zotero 업로드 완료: {template['title'][:30]}...")
                return True
            else:
                error_msg = resp.get('failed') if resp else 'No Response'
                logger.error(f"⚠️ Zotero 업로드 실패: {error_msg}")
                return False
        except Exception as e:
            logger.error(f"⚠️ Zotero 저장 로직 에러: {e}")
            return False
