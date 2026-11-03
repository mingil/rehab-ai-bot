import sys
import os
import time
import argparse
import yaml
import logging
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"), override=True)

from fetcher import PubMedFetcher
from analyzer import PaperAnalyzer
from notifier import Notifier
from zotero_mgr import ZoteroManager
from local_db import LocalDB

LOG_DIR = os.environ.get("LOG_DIR", os.path.join(BASE_DIR, "logs"))
os.makedirs(LOG_DIR, exist_ok=True)

logger = logging.getLogger("JCBot")
logger.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

if not logger.handlers:
    file_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, "system.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=2,
        encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

DEFAULT_SETTINGS_YAML = """# 🏥 대상 저널 (재활의학 핵심 저널)
target_journals:
  - "Archives of physical medicine and rehabilitation"
  - "Annals of rehabilitation medicine"

# 🧠 수집할 AI/ML 핵심 키워드 (리뷰 논문 포함 모든 연구 대상)
target_keywords:
  - "Artificial Intelligence"
  - "Machine Learning"
  - "Deep Learning"
"""


def load_or_init_config(config_path=None):
    """설정 파일을 로드하며, 새 컨테이너 볼륨 마운트로 파일이 없을 경우 기본 설정을 자동 생성"""
    if config_path is None:
        config_path = os.environ.get("CONFIG_PATH", os.path.join(BASE_DIR, "config", "settings.yaml"))

    if not os.path.exists(config_path):
        try:
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            with open(config_path, "w", encoding="utf-8") as f:
                f.write(DEFAULT_SETTINGS_YAML)
            logger.info(f"✨ 기본 설정 파일 자동 생성 완료: {config_path}")
        except Exception as e:
            logger.warning(f"⚠️ 기본 설정 파일 생성 실패 ({e}). 내장 기본값을 사용합니다.")
            return yaml.safe_load(DEFAULT_SETTINGS_YAML)

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    # 환경변수 오버라이드 지원 (TARGET_JOURNALS, TARGET_KEYWORDS)
    env_journals = os.environ.get("TARGET_JOURNALS", "").strip()
    if env_journals:
        config["target_journals"] = [j.strip() for j in env_journals.split(",") if j.strip()]

    env_keywords = os.environ.get("TARGET_KEYWORDS", "").strip()
    if env_keywords:
        config["target_keywords"] = [k.strip() for k in env_keywords.split(",") if k.strip()]

    return config


def run_ai_pipeline(days_override=None, limit=None, dry_run=False):
    logger.info("=" * 60)
    logger.info("🚀 AI/ML 재활 논문 영구 무결점 아카이빙 가동")
    logger.info("=" * 60)

    try:
        config = load_or_init_config()
        journals = config.get("target_journals", [])
        keywords = config.get("target_keywords", [])

        if not journals or not keywords:
            logger.warning("⚠️ target_journals 또는 target_keywords 설정이 비어 있습니다.")
            return

        db = LocalDB()
        fetcher = PubMedFetcher()
        zotero_mgr = ZoteroManager()

        db_count = db.get_count()
        auto_sync_zotero = os.environ.get("ZOTERO_AUTO_SYNC_DB", "true").strip().lower() not in ("0", "false", "no")
        if db_count == 0 and zotero_mgr.zot and auto_sync_zotero:
            existing_zot_items = zotero_mgr.fetch_existing_items()
            if existing_zot_items:
                restored = db.sync_from_zotero(existing_zot_items)
                db_count = db.get_count()
                logger.info(
                    f"🔄 [Zotero 자동 복원] 로컬 DB가 비어있어 Zotero 컬렉션에서 기존 논문 {restored}건을 자동 동기화했습니다!"
                )

        if days_override is not None:
            days_to_fetch = int(days_override)
            logger.info(f"🔧 수동 스캔 범위 지정: 최근 {days_to_fetch}일치 스캔")
        elif db_count == 0:
            logger.info("🌟 [최초 구동 감지] 로컬 DB가 비어있습니다. 역대 모든 논문을 싹쓸이 수집합니다!")
            days_to_fetch = 0
        else:
            default_days = int(os.environ.get("DAYS_TO_FETCH", "60") or 60)
            logger.info(f"✅ 안전망 가동: 이미 {db_count}건이 보관되어 있습니다. 누락 방지를 위해 '최근 {default_days}일치'를 넓게 스캔합니다.")
            days_to_fetch = default_days

        existing_pmids = db.get_all_pmids()

        # [STEP 1] PubMed 검색
        papers = fetcher.fetch_ai_papers(journals, keywords, days_to_fetch, existing_pmids)

        # [STEP 2] DOI 및 제목 기반 2차 필터링
        new_papers = []
        for p in papers:
            pmid = str(p.get("id", "")).strip()
            doi = LocalDB.normalize_doi(p.get("doi", ""))
            title = str(p.get("title", "")).strip()

            if db.is_processed(pmid, doi, title):
                # Zotero에서 복원된 행에 PMID가 비어있었다면 정식 PMID로 업데이트
                db.mark_as_processed(pmid, doi, title)
                continue
            new_papers.append(p)

        if limit and limit > 0:
            new_papers = new_papers[:limit]

        if not new_papers:
            logger.info("💤 새로 업데이트된 논문이 없어 대기 모드로 돌아갑니다.")
            return

        if dry_run:
            logger.info(f"🧪 [Dry-Run 모드] 신규 논문 {len(new_papers)}건 감지됨 (분석 및 발송 생략):")
            for idx, p in enumerate(new_papers, 1):
                logger.info(f"  [{idx}] PMID:{p.get('id')} | {p.get('title')}")
            return

        analyzer = PaperAnalyzer()
        notifier = Notifier()

        logger.info(f"📊 최종 분석 및 Zotero 업로드 대상: {len(new_papers)}건 진행 시작")

        # [STEP 3] 논문 분석 및 Zotero 업로드
        analysis_results = []
        for i, paper in enumerate(new_papers, 1):
            logger.info(f"▶ 처리 중 ({i}/{len(new_papers)}): {paper['title'][:50]}...")
            try:
                analysis_text = analyzer.analyze(paper)
                if not PaperAnalyzer.is_valid_analysis(analysis_text):
                    logger.warning(f"⚠️ AI 분석 실패로 인해 다음 스케줄에서 재시도합니다 (PMID: {paper.get('id')})")
                    continue

                if zotero_mgr.zot:
                    zotero_mgr.add_paper(paper)

                db.mark_as_processed(paper.get('id', ''), paper.get('doi', ''), paper.get('title', ''))
                analysis_results.append({"paper": paper, "analysis": analysis_text})

                time.sleep(5)
            except Exception as e:
                logger.error(f"⚠️ 개별 논문 처리 실패: {e}")
                continue

        # [STEP 4] 알림 발송 및 로컬 아카이빙
        if analysis_results:
            logger.info("📱 결과물 발송 및 로컬 디스크 저장을 시작합니다...")
            # 1. 시놀로지 로컬 디스크에 마크다운 개별 파일 영구 저장
            notifier.save_local_report(analysis_results)
            # 2. 텔레그램/이메일 즉각 알림 발송
            notifier.send_telegram(analysis_results)
            notifier.send_email(analysis_results)

        logger.info("✨ 전체 파이프라인 작업 완료!")

    except Exception as e:
        logger.error(f"❌ 파이프라인 치명적 오류: {e}", exc_info=True)


def print_status():
    config = load_or_init_config()
    db = LocalDB()
    report_dir = os.environ.get("REPORT_DIR", os.path.join(BASE_DIR, "data", "reports"))
    report_files = [f for f in os.listdir(report_dir) if f.endswith(".md")] if os.path.exists(report_dir) else []
    print("=" * 60)
    print("📊 [Rehab AI Bot] 현재 상태 점검 리포트")
    print("=" * 60)
    print(f"• 로컬 DB 보관 논문 수 : {db.get_count()}건 ({db.db_path})")
    print(f"• 로컬 마크다운 리포트 : {len(report_files)}개 ({report_dir})")
    print(f"• 타겟 저널 ({len(config.get('target_journals', []))}종) : {', '.join(config.get('target_journals', []))}")
    print(f"• 타겟 키워드 ({len(config.get('target_keywords', []))}종) : {', '.join(config.get('target_keywords', []))}")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Rehab AI Bot Pipeline Runner")
    parser.add_argument("--status", action="store_true", help="현재 DB 및 리포트 상태 출력")
    parser.add_argument("--dry-run", action="store_true", help="PubMed 신규 논문 검색만 수행 (AI 분석/알림 생략)")
    parser.add_argument("--days", type=int, default=None, help="검색할 과거 일수 수동 지정 (예: --days 30)")
    parser.add_argument("--limit", type=int, default=None, help="최대 처리할 논문 수 제한 (예: --limit 3)")
    args = parser.parse_args()

    if args.status:
        print_status()
    else:
        start_time = time.time()
        run_ai_pipeline(days_override=args.days, limit=args.limit, dry_run=args.dry_run)
        logger.info(f"👋 작업 완료 (소요 시간: {time.time() - start_time:.2f}초).")
