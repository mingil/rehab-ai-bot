import os
import re
import time
import requests
import jcr_lookup
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formatdate, make_msgid
import logging
import html
from datetime import datetime

logger = logging.getLogger("JCBot")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_REPORT_DIR = os.environ.get("REPORT_DIR", os.path.join(BASE_DIR, "data", "reports"))


def _clean_env(key, default=""):
    val = os.environ.get(key, default)
    if val is None:
        return default
    return str(val).strip().strip('"').strip("'").strip()


class Notifier:
    def __init__(self, report_dir=None):
        self.email = _clean_env("EMAIL")
        self.password = _clean_env("EMAIL_PASSWORD")
        raw_recipients = _clean_env("EMAIL_TO", self.email)

        placeholder_emails = {"dr.rehab1@gmail.com", "dr.rehab2@naver.com", "your_email@gmail.com"}
        self.recipients = [
            e.strip().strip('"').strip("'")
            for e in str(raw_recipients).split(',')
            if e.strip() and e.strip() not in placeholder_emails
        ]

        tg_token = _clean_env("TELEGRAM_BOT_TOKEN")
        tg_chat_id = _clean_env("TELEGRAM_CHAT_ID")
        self.tg_token = "" if tg_token.startswith("your_") else tg_token
        self.tg_chat_id = "" if tg_chat_id.startswith("your_") else tg_chat_id

        # 📂 로컬 아카이빙 폴더 설정 (볼륨 매핑된 data/reports 폴더)
        self.report_dir = report_dir or DEFAULT_REPORT_DIR
        os.makedirs(self.report_dir, exist_ok=True)

    def _clean_markdown_for_html(self, text, is_email=False):
        if not text:
            return ""
        text = html.escape(str(text))
        # 마크다운 헤더(### 등) 제거 후 굵은 글씨 처리
        text = re.sub(r'^#{1,6}\s*(.+)$', r'<b>\1</b>', text, flags=re.MULTILINE)
        text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
        if is_email:
            text = text.replace('\n', '<br>')
        return text

    def _sanitize_filename(self, filename):
        """파일 이름에 사용할 수 없는 특수문자를 안전하게 제거"""
        clean_name = re.sub(r'[\\/*?:"<>|\n\r]', "", str(filename))
        clean_name = clean_name.replace(" ", "_")
        return clean_name[:100]  # 너무 긴 파일명 방지 (최대 100자)

    # --- 💾 로컬 마크다운 아카이빙 로직 ---
    def save_local_report(self, results):
        if not results:
            return

        saved_count = 0
        for res in results:
            p = res.get('paper', {})
            analysis_text = res.get('analysis', '분석 결과 없음')
            pmid = str(p.get('id', 'Unknown')).strip()
            title = str(p.get('title', '제목 없음')).strip()

            # 파일명 규칙: PMID_논문제목앞부분.md
            safe_title = self._sanitize_filename(title)
            filename = f"{pmid}_{safe_title}.md"
            filepath = os.path.join(self.report_dir, filename)

            # 마크다운 템플릿 구성 (옵시디언/노션 호환형 YAML 프론트매터 포함)
            today_str = datetime.now().strftime("%Y-%m-%d")
            safe_yaml_title = title.replace('"', "'")  # YAML 따옴표 에러 방지

            md_content = f"""---
title: "{safe_yaml_title}"
journal: "{p.get('journal', 'N/A')}"
jcr: "{jcr_lookup.label(p)}"
date: "{p.get('date', 'N/A')}"
pmid: "{pmid}"
doi: "{p.get('doi', '')}"
archived_date: "{today_str}"
tags:
  - Rehab_AI
---

# 📄 {title}

- **저널:** {p.get('journal', 'N/A')} ({p.get('date', 'N/A')}){(" — " + jcr_lookup.label(p)) if jcr_lookup.label(p) else ""}
- **원문 링크:** [PubMed 보기]({p.get('link', '#')})

---

## 👨‍⚕️ 시니어 AI 교수 브리핑
{analysis_text}

---

## 📝 Abstract (초록 원문)
{p.get('abstract', 'N/A')}
"""
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(md_content)
                saved_count += 1
            except Exception as e:
                logger.error(f"❌ 마크다운 파일 저장 실패 (PMID: {pmid}): {e}")

        if saved_count > 0:
            logger.info(f"📂 로컬 아카이빙 완료: 총 {saved_count}건의 마크다운 파일이 data/reports/ 에 저장되었습니다.")

    # --- 텔레그램 발송 로직 ---
    def send_telegram(self, results):
        if not self.tg_token or not self.tg_chat_id:
            logger.info("ℹ️ 텔레그램 토큰 또는 Chat ID가 설정되지 않아 텔레그램 발송을 건너뜁니다.")
            return

        url = f"https://api.telegram.org/bot{self.tg_token}/sendMessage"

        if len(results) > 15:
            summary_msg = (
                f"🏥 <b>[재활 AI 대규모 아카이빙 완료]</b>\n\n"
                f"총 <b>{len(results)}건</b>의 연구가 Zotero와 로컬에 백업되었습니다!\n\n"
                f"⚠️ <i>텔레그램 스팸 밴 방지를 위해 개별 알림은 생략합니다. 세부 브리핑은 <b>이메일</b>을 확인해 주세요.</i>"
            )
            self._send_tg_msg(url, summary_msg)
            return

        summary_msg = f"🏥 <b>의국 AI/ML 최신 논문 브리핑</b>\n\n총 <b>{len(results)}건</b>의 신규 연구가 포착되었습니다. 👇"
        self._send_tg_msg(url, summary_msg)

        for idx, res in enumerate(results, 1):
            p = res.get('paper', {})
            a = res.get('analysis', '')

            clean_analysis = self._clean_markdown_for_html(a, is_email=False)
            safe_title = html.escape(p.get('title', '제목 없음'))
            safe_journal = html.escape(p.get('journal', 'N/A') + ((" · " + jcr_lookup.label(p)) if jcr_lookup.label(p) else ""))
            safe_date = html.escape(p.get('date', 'N/A'))
            safe_link = html.escape(p.get('link', '#'), quote=True)

            header = (
                f"📄 <b>[{idx}/{len(results)}] {safe_title}</b>\n"
                f"📚 <i>{safe_journal}</i> | 📅 {safe_date}\n"
                f"━━━━━━━━━━━━━━━━━━\n"
            )
            footer = (
                f"\n━━━━━━━━━━━━━━━━━━\n"
                f"🔗 <a href='{safe_link}'>PubMed 원문 보기</a>"
            )

            # 🛡️ 텔레그램 최대 글자수(4096자) 초과 시 안전 절삭
            max_body_len = 3900 - len(header) - len(footer)
            if len(clean_analysis) > max_body_len:
                clean_analysis = html.escape(str(a)[:max_body_len - 100]) + "\n\n<i>... (전문은 이메일 및 로컬 리포트 참조)</i>"

            msg = f"{header}{clean_analysis}{footer}"

            self._send_tg_msg(url, msg)
            time.sleep(2.5)

    def _send_tg_msg(self, url, text):
        payload = {
            "chat_id": self.tg_chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        try:
            resp = requests.post(url, json=payload, timeout=15)
            if resp.status_code != 200:
                logger.error(f"❌ 텔레그램 전송 실패: {resp.text}")
        except Exception as e:
            logger.error(f"❌ 텔레그램 API 통신 에러: {e}")

    # --- 이메일 발송 로직 ---
    def send_email(self, results):
        if not self.email or not self.password or not self.recipients:
            logger.info("ℹ️ 이메일 설정이 불완전하여 이메일 발송은 건너뜁니다.")
            return

        subject = f"[Rehab AI Bot] 최신 인공지능 재활 연구 브리핑 ({len(results)}건)"

        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #1f2937; background-color: #f3f4f6; margin: 0; padding: 20px;">
            <div style="max-width: 800px; margin: 0 auto; background-color: #ffffff; padding: 30px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05);">
                <h2 style="color: #2563eb; margin-top: 0; border-bottom: 2px solid #eff6ff; padding-bottom: 10px;">🏥 의국 저널클럽 AI/ML 브리핑</h2>
                <p style="font-size: 16px; color: #4b5563;">총 <b>{len(results)}건</b>의 최신 인공지능 재활 연구가 팩트체크 되었습니다.</p>
        """

        for idx, res in enumerate(results, 1):
            p = res.get('paper', {})
            a_html = self._clean_markdown_for_html(res.get('analysis', ''), is_email=True)
            safe_title = html.escape(p.get('title', '제목 없음'))
            safe_journal = html.escape(p.get('journal', 'N/A') + ((" · " + jcr_lookup.label(p)) if jcr_lookup.label(p) else ""))
            safe_date = html.escape(p.get('date', 'N/A'))
            safe_link = html.escape(p.get('link', '#'), quote=True)

            html_body += f"""
                <div style="margin-top: 30px; border: 1px solid #e5e7eb; border-radius: 10px; overflow: hidden;">
                    <div style="background-color: #f8fafc; padding: 15px 20px; border-bottom: 1px solid #e5e7eb;">
                        <h3 style="margin: 0; font-size: 18px; line-height: 1.4;">
                            <a href="{safe_link}" style="color: #111827; text-decoration: none;">[{idx}] {safe_title}</a>
                        </h3>
                        <p style="margin: 5px 0 0 0; color: #64748b; font-size: 14px;">
                            📚 <b>{safe_journal}</b> | 📅 {safe_date}
                        </p>
                    </div>
                    <div style="padding: 20px; background-color: #ffffff; font-size: 15px; color: #334155;">
                        {a_html}
                    </div>
                </div>
            """

        html_body += """
            </div>
            <div style="text-align: center; color: #9ca3af; font-size: 12px; margin-top: 20px;">
                Generated by Rehab AI Bot (Dockerized on Synology NAS)
            </div>
        </body>
        </html>
        """

        try:
            msg = MIMEMultipart('alternative')
            msg['From'] = f"Rehab AI Bot <{self.email}>"
            msg['To'] = ", ".join(self.recipients)
            msg['Subject'] = subject
            msg['Date'] = formatdate(localtime=True)
            msg['Message-ID'] = make_msgid()
            msg.attach(MIMEText(html_body, 'html', 'utf-8'))

            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as server:
                server.login(self.email, self.password)
                server.send_message(msg)
            logger.info("📧 이메일 리포트 발송 완료!")
        except Exception as e:
            logger.error(f"❌ 이메일 발송 에러: {e}")
