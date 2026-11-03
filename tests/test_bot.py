import os
import tempfile
import unittest
from unittest import mock

from local_db import LocalDB
from fetcher import PubMedFetcher
from analyzer import PaperAnalyzer, FAILURE_PREFIX
from zotero_mgr import ZoteroManager
from notifier import Notifier
import main as main_mod


class StringWithAttrs(str):
    def __new__(cls, value, attrs=None):
        obj = super().__new__(cls, value)
        obj.attributes = attrs or {}
        return obj


class TestRehabAIBot(unittest.TestCase):
    def test_local_db_deduplication_and_doi_normalization(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test_papers.db")
            db = LocalDB(db_path=db_path)

            self.assertEqual(db.get_count(), 0)
            self.assertFalse(db.is_processed("12345", "10.1016/j.apmr.2026.01.001"))

            # Save with HTTPS prefix and uppercase DOI
            db.mark_as_processed("12345", "https://doi.org/10.1016/J.APMR.2026.01.001", "Test Paper Title")
            self.assertEqual(db.get_count(), 1)
            self.assertIn("12345", db.get_all_pmids())

            # Match by PMID
            self.assertTrue(db.is_processed("12345", ""))
            # Match by case-insensitive normalized DOI even when PMID differs
            self.assertTrue(db.is_processed("99999", "http://dx.doi.org/10.1016/j.apmr.2026.01.001"))
            self.assertFalse(db.is_processed("99999", "10.1016/j.apmr.2026.99.999"))

    def test_pubmed_fetcher_ignore_invalid_short_ncbi_key(self):
        with mock.patch.dict(os.environ, {"NCBI_API_KEY": '"2"', "EMAIL": '"doctor@hospital.org"'}):
            fetcher = PubMedFetcher()
            self.assertEqual(fetcher.email, "doctor@hospital.org")
            self.assertIsNone(fetcher.sleep_time if fetcher.sleep_time == 0.11 else None)
            self.assertEqual(fetcher.sleep_time, 0.35)

    def test_pubmed_article_xml_parsing(self):
        fetcher = PubMedFetcher()
        sample_article = {
            "MedlineCitation": {
                "PMID": "42703846",
                "Article": {
                    "ArticleTitle": "Deep Learning for Stroke Gait Prediction.",
                    "AuthorList": [
                        {"LastName": "Kim", "ForeName": "Min Gil", "AffiliationInfo": [{"Affiliation": "Dept of PM&R"}]},
                        {"LastName": "Lee", "ForeName": "Jisoo"},
                        {"LastName": "Park", "ForeName": "Hyun"},
                        {"LastName": "Choi", "ForeName": "Yuna"},
                    ],
                    "ELocationID": [
                        StringWithAttrs("10.1016/j.apmr.2026.05.010", {"EIdType": "doi"})
                    ],
                    "Abstract": {
                        "AbstractText": [
                            StringWithAttrs("Stroke gait analysis is important.", {"Label": "OBJECTIVE"}),
                            StringWithAttrs("We trained a transformer model on 500 patients.", {"Label": "METHODS"}),
                        ]
                    },
                    "Journal": {
                        "Title": "Archives of physical medicine and rehabilitation",
                        "JournalIssue": {
                            "PubDate": {"Year": "2026", "Month": "Nov"}
                        }
                    }
                }
            }
        }

        parsed = fetcher._parse_article(sample_article)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["id"], "42703846")
        self.assertEqual(parsed["doi"], "10.1016/j.apmr.2026.05.010")
        self.assertEqual(parsed["authors"], "Kim Min Gil, Lee Jisoo, Park Hyun et al.")
        self.assertIn("**OBJECTIVE**: Stroke gait analysis is important.", parsed["abstract"])
        self.assertEqual(parsed["date"], "2026 Nov")
        self.assertEqual(parsed["link"], "https://pubmed.ncbi.nlm.nih.gov/42703846/")

    @mock.patch("analyzer.genai.Client")
    def test_paper_analyzer_failover_and_validation(self, mock_client_cls):
        mock_client = mock.MagicMock()
        mock_client_cls.return_value = mock_client

        # First model fails across retries, second model succeeds
        resp_ok = mock.MagicMock()
        resp_ok.text = "🎯 **시니어 교수의 한 줄 평**\n실용적인 보행 예측 연구입니다."
        mock_client.models.generate_content.side_effect = [
            RuntimeError("503 UNAVAILABLE"),
            resp_ok,
        ]

        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": '"test_gemini_key"', "GEMINI_MODEL": "gemini-3.8-flash"}):
            analyzer = PaperAnalyzer()
            result = analyzer.analyze(
                {
                    "title": "Test Title",
                    "journal": "Test Journal",
                    "abstract": "Test Abstract",
                    "raw_authors": [{"LastName": "Kim", "ForeName": "MG", "AffiliationInfo": [{"Affiliation": "PMR"}]}],
                },
                max_retries=1,
            )

        self.assertTrue(PaperAnalyzer.is_valid_analysis(result))
        self.assertFalse(PaperAnalyzer.is_valid_analysis(f"{FAILURE_PREFIX}. (API 서버 응답 초과)"))
        self.assertIn("시니어 교수의 한 줄 평", result)

    def test_zotero_manager_graceful_disable_on_missing_or_placeholder_env(self):
        with mock.patch.dict(os.environ, {"ZOTERO_USER_ID": "", "ZOTERO_API_KEY": "", "ZOTERO_CANDIDATES_ID": ""}):
            zm = ZoteroManager()
            self.assertIsNone(zm.zot)
            self.assertFalse(zm.add_paper({"title": "Sample"}))

    def test_pyzotero_whenever_compat_proxy(self):
        import datetime
        import pyzotero._client as _zc

        zdt = _zc.whenever.ZonedDateTime.now("Europe/London")
        dt_legacy = zdt.py_datetime()
        dt_modern = zdt.to_stdlib()
        self.assertIsInstance(dt_legacy, datetime.datetime)
        self.assertIsInstance(dt_modern, datetime.datetime)

    def test_zotero_deduplication_and_db_auto_restore(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test_restore.db")
            db = LocalDB(db_path=db_path)

            with mock.patch.dict(
                os.environ,
                {
                    "ZOTERO_USER_ID": "123456",
                    "ZOTERO_API_KEY": "valid_key",
                    "ZOTERO_CANDIDATES_ID": "COL123",
                },
            ), mock.patch("zotero_mgr.zotero.Zotero") as mock_zot_cls:
                mock_zot = mock.MagicMock()
                mock_zot_cls.return_value = mock_zot
                mock_zot.everything.return_value = [
                    {
                        "data": {
                            "key": "ITEM1",
                            "itemType": "journalArticle",
                            "DOI": "https://doi.org/10.5535/arm.260007",
                            "title": "Digital Health Approaches to Geriatric Rehabilitation.",
                            "extra": "",
                        }
                    }
                ]

                zm = ZoteroManager()
                existing_items = zm.fetch_existing_items()
                self.assertEqual(len(existing_items), 1)

                # Restore to empty local DB
                restored_count = db.sync_from_zotero(existing_items)
                self.assertEqual(restored_count, 1)
                self.assertEqual(db.get_count(), 1)
                self.assertTrue(db.is_processed("42703846", "10.5535/arm.260007", ""))

                # Upgrade temporary ID to real PMID when encountered
                db.mark_as_processed("42703846", "10.5535/arm.260007", "Digital Health Approaches to Geriatric Rehabilitation.")
                self.assertIn("42703846", db.get_all_pmids())

                # Ensure duplicate upload to Zotero is skipped without calling create_items
                res = zm.add_paper(
                    {
                        "id": "42703846",
                        "doi": "10.5535/arm.260007",
                        "title": "Digital Health Approaches to Geriatric Rehabilitation.",
                    }
                )
                self.assertTrue(res)
                mock_zot.create_items.assert_not_called()

    def test_notifier_markdown_archiving_and_telegram_truncation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.dict(
                os.environ,
                {
                    "TELEGRAM_BOT_TOKEN": '"123456:ABC-DEF"',
                    "TELEGRAM_CHAT_ID": '"987654321"',
                    "EMAIL": "dr.rehab1@gmail.com",
                    "EMAIL_TO": "dr.rehab1@gmail.com,dr.rehab2@naver.com",
                },
            ):
                notifier = Notifier(report_dir=tmpdir)
                # Quotes should be stripped and placeholder emails ignored
                self.assertEqual(notifier.tg_token, "123456:ABC-DEF")
                self.assertEqual(notifier.tg_chat_id, "987654321")
                self.assertEqual(notifier.recipients, [])

                long_analysis = "**핵심 요약**\n" + ("매우 긴 임상 분석 내용입니다. " * 400)
                results = [
                    {
                        "paper": {
                            "id": "42700001",
                            "doi": "10.1016/j.apmr.2026.01.001",
                            "title": 'AI in "Stroke" Rehabilitation: A Study?',
                            "journal": "Annals of rehabilitation medicine",
                            "date": "2026 Nov",
                            "link": "https://pubmed.ncbi.nlm.nih.gov/42700001/",
                            "abstract": "Sample abstract text.",
                        },
                        "analysis": long_analysis,
                    }
                ]

                notifier.save_local_report(results)
                saved_files = os.listdir(tmpdir)
                self.assertEqual(len(saved_files), 1)
                self.assertTrue(saved_files[0].startswith("42700001_"))

                with mock.patch("notifier.requests.post") as mock_post, mock.patch("notifier.time.sleep"):
                    mock_post.return_value.status_code = 200
                    notifier.send_telegram(results)
                    self.assertEqual(mock_post.call_count, 2)
                    sent_body = mock_post.call_args_list[1][1]["json"]["text"]
                    self.assertLessEqual(len(sent_body), 4096)

    def test_load_or_init_config_auto_generation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "config", "settings.yaml")
            cfg = main_mod.load_or_init_config(cfg_path)
            self.assertTrue(os.path.exists(cfg_path))
            self.assertIn("Archives of physical medicine and rehabilitation", cfg["target_journals"])
            self.assertIn("Artificial Intelligence", cfg["target_keywords"])


if __name__ == "__main__":
    unittest.main()
