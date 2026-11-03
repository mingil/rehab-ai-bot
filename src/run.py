import time
import schedule
import subprocess
import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"), override=True)

LOG_DIR = os.environ.get("LOG_DIR", os.path.join(BASE_DIR, "logs"))
os.makedirs(LOG_DIR, exist_ok=True)
HEARTBEAT_FILE = os.environ.get("HEARTBEAT_FILE", "/tmp/rehab_ai_bot_heartbeat")

logger = logging.getLogger("Scheduler")
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


def update_heartbeat():
    try:
        with open(HEARTBEAT_FILE, "w", encoding="utf-8") as f:
            f.write(str(int(time.time())))
    except Exception:
        pass


def run_job():
    update_heartbeat()
    logger.info("\n🚀 [스케줄러] 무결점 아카이빙 파이프라인 가동!")
    main_script = os.path.join(BASE_DIR, "src", "main.py")
    try:
        subprocess.run([sys.executable, main_script], cwd=BASE_DIR, timeout=3600, check=False)
    except subprocess.TimeoutExpired:
        logger.error("⚠️ [스케줄러] 파이프라인 실행 시간이 1시간(3600초)을 초과하여 안전 종료되었습니다.")
    except Exception as e:
        logger.error(f"❌ [스케줄러] 파이프라인 호출 오류: {e}")
    update_heartbeat()
    logger.info("💤 [스케줄러] 작업 완료! 메모리를 100% 반환하고 초경량 대기 모드로 돌아갑니다.\n")


if __name__ == "__main__":
    schedule_time = os.environ.get("SCHEDULE_TIME", "08:00").strip().strip('"').strip("'") or "08:00"
    logger.info("🤖 [Rehab AI Bot] 도커 스케줄러 가동 (영구 무결점 아카이빙 모드)")
    update_heartbeat()

    # 1. 🚀 도커 기동 시 즉시 실행 (main.py가 알아서 최초 실행인지 감지함)
    run_job()

    # 2. 🛡️ 매일 지정 시각(기본 아침 8시) 정기 스캔 가동
    schedule.every().day.at(schedule_time).do(run_job)

    logger.info(f"⏳ 스케줄 등록 완료 (매일 {schedule_time}). 백그라운드에서 숨죽여 대기합니다...")

    while True:
        update_heartbeat()
        schedule.run_pending()
        time.sleep(60)
