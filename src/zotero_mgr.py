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


class _ZonedDateTimeCompat:
    """whenever 구버전(.py_datetime)과 신버전(.to_stdlib)을 모두 호환하는 프록시"""

    def __init__(self, zdt):
        self._zdt = zdt

    def py_datetime(self):
        if hasattr(self._zdt, "py_datetime"):
            return self._zdt.py_datetime()
        return self._zdt.to_stdlib()

    def to_stdlib(self):
        if hasattr(self._zdt, "to_stdlib"):
            return self._zdt.to_stdlib()
        return self._zdt.py_datetime()

    def __getattr__(self, name):
        return getattr(self._zdt, name)


class _ZonedDateTimeClassProxy:
    def __init__(self, orig_cls):
        self._orig_cls = orig_cls

    def now(self, *args, **kwargs):
        return _ZonedDateTimeCompat(self._orig_cls.now(*args, **kwargs))

    def __getattr__(self, name):
        return getattr(self._orig_cls, name)


class _WheneverModuleProxy:
    def __init__(self, orig_mod):
        self._orig_mod = orig_mod
        self.ZonedDateTime = _ZonedDateTimeClassProxy(orig_mod.ZonedDateTime)

    def __getattr__(self, name):
        return getattr(self._orig_mod, name)


def _patch_pyzotero_whenever():
    """pyzotero 내부 _client.whenever의 버전 간 메서드 충돌(py_datetime vs to_stdlib) 원천 방어"""
    try:
        import pyzotero._client as _zc

        if hasattr(_zc, "whenever") and not isinstance(_zc.whenever, _WheneverModuleProxy):
            _zc.whenever = _WheneverModuleProxy(_zc.whenever)
    except Exception:
        pass


_patch_pyzotero_whenever()


def _clean_env(key, default=""):
    val = os.environ.get(key, default)
    if val is None:
        return default
    return str(val).strip().strip('"').strip("'").strip()


class ZoteroManager:
    def __init__(self):
        _patch_pyzotero_whenever()
        self.user_id = _clean_env("ZOTERO_USER_ID")
        self.api_key = _clean_env("ZOTERO_API_KEY")
        self.library_type = _clean_env("ZOTERO_LIBRARY_TYPE", "user") or "user"
        self.candidates_col_id = _clean_env("ZOTERO_CANDIDATES_ID")

        self._cache_loaded = False
        self._existing_dois = set()
        self._existing_pmids = set()
        self._existing_titles = set()

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

    @staticmethod
    def _clean_doi(doi):
        if not doi:
            return ""
        return re.sub(r'^https?://(dx\.)?doi\.org/', '', str(doi).strip().lower()).strip()

    @staticmethod
    def _clean_title(title):
        if not title:
            return ""
        return re.sub(r'\s+', ' ', str(title).strip().lower()).rstrip('.')

    @staticmethod
    def _extract_pmid_from_extra(extra_text):
        if not extra_text:
            return ""
        match = re.search(r'PMID:\s*(\d+)', str(extra_text), re.IGNORECASE)
        return match.group(1).strip() if match else ""

    def fetch_existing_items(self):
        """Zotero 타겟 컬렉션에 이미 저장된 논문 목록을 조회하고 중복 방지 캐시를 갱신"""
        if not self.zot:
            return []

        items = self._execute_with_retry(
            lambda: self.zot.everything(self.zot.collection_items_top(self.candidates_col_id))
        )
        if items is None:
            return []

        parsed_items = []
        self._existing_dois.clear()
        self._existing_pmids.clear()
        self._existing_titles.clear()

        for it in items:
            data = it.get("data", {}) if isinstance(it, dict) else {}
            item_type = data.get("itemType", "")
            if item_type in ("attachment", "note", "annotation"):
                continue

            doi = self._clean_doi(data.get("DOI", ""))
            title = str(data.get("title", "")).strip()
            norm_title = self._clean_title(title)
            pmid = self._extract_pmid_from_extra(data.get("extra", ""))
            key = str(data.get("key", "")).strip()

            if doi:
                self._existing_dois.add(doi)
            if pmid:
                self._existing_pmids.add(pmid)
            if norm_title:
                self._existing_titles.add(norm_title)

            if doi or pmid or norm_title:
                record_id = pmid if pmid else (f"doi:{doi}" if doi else f"zotero:{key}")
                parsed_items.append({
                    "id": record_id,
                    "pmid": pmid,
                    "doi": doi,
                    "title": title,
                })

        self._cache_loaded = True
        return parsed_items

    def is_already_in_zotero(self, paper):
        """해당 논문이 이미 Zotero 컬렉션에 존재하는지 확인"""
        if not self.zot:
            return False
        if not self._cache_loaded:
            self.fetch_existing_items()

        pmid = str(paper.get("id", "")).strip()
        doi = self._clean_doi(paper.get("doi", ""))
        norm_title = self._clean_title(paper.get("title", ""))

        if pmid and pmid in self._existing_pmids:
            return True
        if doi and doi in self._existing_dois:
            return True
        if norm_title and norm_title in self._existing_titles:
            return True
        return False

    def add_paper(self, paper):
        """분석 코멘트 없이 논문 메타데이터만 깔끔하게 Zotero에 저장 (중복 업로드 자동 방지)"""
        if not self.zot:
            return False

        try:
            if self.is_already_in_zotero(paper):
                logger.info(f"⏭️ Zotero 컬렉션에 이미 존재하는 논문입니다 (중복 업로드 건너뜀): {str(paper.get('title', ''))[:30]}...")
                return True

            template = self._execute_with_retry(self.zot.item_template, 'journalArticle')
            if not template:
                return False

            title_str = str(paper.get('title', 'Unknown Title')).strip()
            doi_str = self._clean_doi(paper.get('doi', ''))
            pmid_str = str(paper.get('id', '')).strip()

            template['title'] = title_str
            template['DOI'] = doi_str
            template['abstractNote'] = str(paper.get('abstract', '')).strip()
            template['publicationTitle'] = str(paper.get('journal', '')).strip()
            template['date'] = str(paper.get('date', '')).strip()
            template['url'] = str(paper.get('link', '')).strip()
            template['extra'] = f"PMID: {pmid_str}" if pmid_str else ""

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
                if doi_str:
                    self._existing_dois.add(doi_str)
                if pmid_str:
                    self._existing_pmids.add(pmid_str)
                norm_title = self._clean_title(title_str)
                if norm_title:
                    self._existing_titles.add(norm_title)
                logger.info(f"💾 Zotero 업로드 완료: {template['title'][:30]}...")
                return True
            else:
                error_msg = resp.get('failed') if resp else 'No Response'
                logger.error(f"⚠️ Zotero 업로드 실패: {error_msg}")
                return False
        except Exception as e:
            logger.error(f"⚠️ Zotero 저장 로직 에러: {e}")
            return False
