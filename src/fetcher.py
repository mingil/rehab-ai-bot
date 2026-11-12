import os
import time
import socket
import logging
import datetime
from urllib.error import HTTPError, URLError
import http.client
from Bio import Entrez
import jcr_lookup

logger = logging.getLogger("JCBot")

# 🛡️ 네트워크 무한 대기(Hang) 방지를 위한 전역 소켓 타임아웃 (30초)
socket.setdefaulttimeout(30)


def _clean_env(key, default=""):
    val = os.environ.get(key, default)
    if val is None:
        return default
    return str(val).strip().strip('"').strip("'").strip()


class PubMedFetcher:
    def __init__(self):
        email = _clean_env("EMAIL", "dr.research@hospital.ac.kr")
        if not email or "@" not in email:
            email = "dr.research@hospital.ac.kr"
        self.email = email
        Entrez.email = self.email

        # NCBI API Key 적용 및 Rate Limit 딜레이 방어 (오타나 짧은 더미 값 방어)
        ncbi_api_key = _clean_env("NCBI_API_KEY")
        if ncbi_api_key and len(ncbi_api_key) >= 10 and not ncbi_api_key.startswith("your_"):
            Entrez.api_key = ncbi_api_key
            self.sleep_time = 0.11  # 초당 10회 허용
        else:
            Entrez.api_key = None
            self.sleep_time = 0.35  # 초당 3회 허용 제한

    def _fetch_with_retry(self, func, *args, max_retries=3, **kwargs):
        """API 네트워크 오류 방어용 지수 백오프 로직"""
        for attempt in range(max_retries):
            try:
                time.sleep(self.sleep_time)
                handle = func(*args, **kwargs)
                result = Entrez.read(handle)
                handle.close()
                return result
            except HTTPError as e:
                # 잘못된 NCBI_API_KEY로 인한 HTTP 400/401 발생 시 키 해제 후 즉시 폴백
                if e.code in (400, 401, 403) and getattr(Entrez, "api_key", None):
                    logger.warning(f"⚠️ NCBI_API_KEY 인증 오류(HTTP {e.code}) 감지. API Key 없이 일반 모드로 자동 전환합니다.")
                    Entrez.api_key = None
                    self.sleep_time = 0.35
                    continue
                wait_time = 2 ** attempt
                logger.warning(f"⚠️ NCBI API 연결 지연 ({e}). {wait_time}초 후 재시도 ({attempt + 1}/{max_retries})")
                time.sleep(wait_time)
            except (URLError, http.client.IncompleteRead, TimeoutError, socket.timeout) as e:
                wait_time = 2 ** attempt
                logger.warning(f"⚠️ NCBI 네트워크 지연 ({e}). {wait_time}초 후 재시도 ({attempt + 1}/{max_retries})")
                time.sleep(wait_time)
            except Exception as e:
                logger.error(f"❌ 데이터 파싱 오류: {e}")
                break
        return None

    def _parse_article(self, article):
        """개별 논문 XML 파싱 모듈"""
        pmid = "Unknown"
        try:
            if not isinstance(article, dict):
                return None

            medline = article.get('MedlineCitation', {})
            if not isinstance(medline, dict):
                medline = {}

            article_data = medline.get('Article', {})
            if not isinstance(article_data, dict):
                article_data = {}

            pmid = str(medline.get('PMID', '')).strip()
            if not pmid:
                return None
            title = str(article_data.get('ArticleTitle', 'No Title')).strip()

            # 저자 정보 추출
            authors_list = []
            if 'AuthorList' in article_data and isinstance(article_data['AuthorList'], list):
                for author in article_data['AuthorList']:
                    if isinstance(author, dict):
                        last = str(author.get('LastName', ''))
                        first = str(author.get('ForeName', author.get('Initials', '')))
                        full_name = f"{last} {first}".strip()
                        if full_name:
                            authors_list.append(full_name)

            authors_str = ", ".join(authors_list[:3])
            if len(authors_list) > 3:
                authors_str += " et al."

            # DOI 추출
            doi = ""
            if 'ELocationID' in article_data and isinstance(article_data['ELocationID'], list):
                for eloc in article_data['ELocationID']:
                    if hasattr(eloc, 'attributes') and isinstance(eloc.attributes, dict):
                        if eloc.attributes.get('EIdType') == 'doi':
                            doi = str(eloc).strip()
                            break

            if not doi and 'PubmedData' in article and isinstance(article['PubmedData'], dict):
                article_id_list = article['PubmedData'].get('ArticleIdList', [])
                if isinstance(article_id_list, list):
                    for art_id in article_id_list:
                        if hasattr(art_id, 'attributes') and isinstance(art_id.attributes, dict):
                            if art_id.attributes.get('IdType') == 'doi':
                                doi = str(art_id).strip()
                                break

            # 초록 마크다운 구조화
            abstract_text = "No Abstract Available."
            if 'Abstract' in article_data and isinstance(article_data['Abstract'], dict):
                abs_elements = article_data['Abstract'].get('AbstractText', '')
                if isinstance(abs_elements, list):
                    abs_parts = []
                    for elem in abs_elements:
                        label = getattr(elem, 'attributes', {}).get('Label', '') if hasattr(elem, 'attributes') and isinstance(elem.attributes, dict) else ''
                        text = str(elem).strip()
                        if label and str(label).lower() != 'unlabelled':
                            abs_parts.append(f"**{str(label).upper()}**: {text}")
                        else:
                            abs_parts.append(text)
                    abstract_text = "\n\n".join(abs_parts)
                else:
                    abstract_text = str(abs_elements).strip() or "No Abstract Available."

            # 저널 및 출판일 추출
            journal_data = article_data.get('Journal', {})
            issn = ""
            if isinstance(journal_data, dict):
                journal = str(journal_data.get('Title', 'Unknown Journal'))
                issn = str(journal_data.get('ISSN', '') or '').strip()
                pub_date = journal_data.get('JournalIssue', {}).get('PubDate', {}) if isinstance(journal_data.get('JournalIssue'), dict) else {}
            else:
                journal = "Unknown Journal"
                pub_date = {}

            if isinstance(pub_date, dict):
                date_str = f"{pub_date.get('Year', '')} {pub_date.get('Month', '')}".strip() or str(pub_date.get('MedlineDate', '')).strip() or "Unknown Date"
            else:
                date_str = "Unknown Date"

            linking = str((medline.get('MedlineJournalInfo', {}) or {}).get('ISSNLinking', '') or '').strip() if isinstance(medline, dict) else ""
            return {
                'id': pmid, 'doi': doi, 'title': title, 'abstract': abstract_text,
                'journal': journal, 'date': date_str, 'authors': authors_str,
                'issn': issn, 'jcr': jcr_lookup.lookup(",".join(x for x in (issn, linking) if x), journal),
                'raw_authors': article_data.get('AuthorList', []) if isinstance(article_data.get('AuthorList'), list) else [],
                'link': f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
            }
        except Exception as e:
            logger.warning(f"⚠️ 논문 파싱 중 오류 발생 (PMID: {pmid}): {e}")
            return None

    def fetch_ai_papers(self, journals, keywords, days_back=0, existing_pmids=None):
        """지정된 저널에서 AI/ML 키워드가 포함된 연구를 수집"""
        journal_terms = " OR ".join([f'"{j}"[Journal]' for j in journals])
        keyword_terms = " OR ".join([f'"{k}"[tiab]' for k in keywords])

        days_back = int(days_back)
        if days_back > 0:
            today = datetime.datetime.now()
            start_date = today - datetime.timedelta(days=days_back)
            date_query = f' AND (("{start_date.strftime("%Y/%m/%d")}"[Date - Create] : "{today.strftime("%Y/%m/%d")}"[Date - Create]))'
            logger.info(f"🔍 PubMed 검색 (타겟: 과거 {days_back}일 - 지연 등록분 완벽 방어망)")
        else:
            date_query = ""
            logger.info("🔍 PubMed 검색 (타겟: 🌟저널 창간 이후 전체 기간 무제한 싹쓸이🌟)")

        full_query = f'({journal_terms}) AND ({keyword_terms}){date_query}'

        try:
            search_results = self._fetch_with_retry(
                Entrez.esearch, db="pubmed", term=full_query, retmax=10000, sort="pub_date"
            )

            if not search_results or not isinstance(search_results, dict) or not search_results.get("IdList"):
                logger.info("ℹ️ 조건에 맞는 예비 논문이 없습니다.")
                return []

            id_list = [str(pmid).strip() for pmid in search_results.get("IdList", []) if str(pmid).strip()]
            logger.info(f"📄 1차 검색 완료: 총 {len(id_list)}건의 논문 식별번호(PMID) 발견.")

            # 🚀 [핵심 최적화] 이미 DB에 있는 PMID는 데이터 다운로드 전에 미리 잘라내어 트래픽/메모리 보호
            if existing_pmids:
                id_list = [pmid for pmid in id_list if pmid not in existing_pmids]
                logger.info(f"⚡ 사전 중복 필터링 완료: 👉 실제 새롭게 다운로드할 '순수 신규 논문'은 {len(id_list)}건 입니다.")

            if not id_list:
                return []

            papers = []
            batch_size = 100

            for start in range(0, len(id_list), batch_size):
                batch_ids = id_list[start:start+batch_size]
                articles = self._fetch_with_retry(
                    Entrez.efetch, db="pubmed", id=",".join(batch_ids), rettype="xml", retmode="xml"
                )

                # 🛡️ 대량 파싱 시 NCBI IP 차단(Ban) 방지를 위한 미세 딜레이
                time.sleep(1.0)

                if not articles or not isinstance(articles, dict) or 'PubmedArticle' not in articles:
                    continue

                pubmed_articles = articles['PubmedArticle']
                if not isinstance(pubmed_articles, list):
                    continue

                for article in pubmed_articles:
                    parsed_paper = self._parse_article(article)
                    if parsed_paper:
                        papers.append(parsed_paper)

            logger.info(f"✅ 최종 파싱 완료: 총 {len(papers)}건")
            return papers

        except Exception as e:
            logger.error(f"❌ PubMed 검색 전체 프로세스 에러: {e}")
            return []
