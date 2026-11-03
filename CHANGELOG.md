# 📝 Changelog

All notable changes to **Rehab AI Bot** are documented in this file.

## [2.0.1] - 2026-11-03

### Fixed
- **Zotero `whenever.ZonedDateTime.py_datetime` Compatibility Fix (`requirements.txt`, `src/zotero_mgr.py`):** Upgraded `pyzotero` to `1.16.0` (with pinned `whenever==0.11.0`) and added a bidirectional `_ZonedDateTimeCompat` shim so both `.py_datetime()` and `.to_stdlib()` calls succeed across all `pyzotero`/`whenever` versions.
- **Zotero Collection Deduplication & Empty Local DB Auto-Restore (`src/zotero_mgr.py`, `src/local_db.py`, `src/main.py`):** When starting a fresh container with an empty `papers.db`, the bot now automatically checks the target Zotero collection first, restores existing papers into `papers.db`, and skips duplicate uploads to Zotero.

---

## [2.0.0] - 2026-11-03

### Added
- **3-Tier Gemini AI Failover Engine (`src/analyzer.py`):** Upgraded default AI model to **Google Gemini 3.8 Flash** (`gemini-3.8-flash`) with automatic multi-tier fallback (`gemini-3.8-flash` -> `gemini-3.6-flash` -> `gemini-3.5-flash-lite` -> `gemini-2.5-flash`) and customizable `GEMINI_MODEL` environment variable.
- **Docker Hub & GHCR Automated CI/CD (`.github/workflows/docker-publish.yml`):** Added automated `pytest` verification and dual-registry image publishing (`kimmingil/rehab-ai-bot:latest` and `ghcr.io/mingil/rehab-ai-bot:latest`) with automatic README synchronization to Docker Hub.
- **Zero-Touch Config Initialization (`src/main.py`):** Automatically generates default `config/settings.yaml` when a fresh user mounts an empty `./config` volume, and supports direct `.env` overrides (`TARGET_JOURNALS`, `TARGET_KEYWORDS`, `SCHEDULE_TIME`, `DAYS_TO_FETCH`).
- **Container Healthcheck & Scheduler Timeout (`Dockerfile`, `src/run.py`):** Added heartbeat-based Docker `HEALTHCHECK` and a 1-hour execution timeout guard on child processes.
- **CLI Diagnostic & Dry-Run Mode (`src/main.py`):** Added `--status`, `--dry-run`, `--days`, and `--limit` CLI flags for instant container inspection and testing.
- **Comprehensive Unit Test Suite (`tests/test_bot.py`):** Added 12 automated unit tests covering SQLite deduplication, PubMed XML parsing, Gemini failover, Zotero formatting, Markdown/Telegram/Email rendering, and pipeline fault tolerance.

### Fixed
- **Environment Variable Sanitization (`src/*.py`):** Automatically loads `.env` (`load_dotenv(override=True)`), strips accidental surrounding quotes (`"..."`) or whitespace from tokens, and ignores placeholder values (`your_telegram_bot_token`, invalid short `NCBI_API_KEY`, etc.) that previously caused Telegram 404 or NCBI 400 errors.
- **AI Analysis Failure Poisoning Prevention (`src/main.py`):** Prevents failed AI analyses (during total API outages) from being permanently marked as processed in `papers.db`, ensuring automatic retry on the next run.
- **Case-Insensitive DOI Deduplication & SQLite WAL Mode (`src/local_db.py`):** Normalized DOI strings (`https://doi.org/` removal + lowercase) across both read and write operations and enabled SQLite WAL mode for Synology NAS I/O stability.
- **Telegram 4096-Character Limit Guard (`src/notifier.py`):** Added automatic safe truncation when long AI briefings exceed Telegram's maximum message length.
- **Clean Distribution Volume Mounts (`compose.yaml`):** Removed host `./src:/app/src` bind mount from `compose.yaml` so Docker Hub image updates (`docker compose pull && docker compose up -d` or Watchtower) apply immediately for all users.

---

## [1.0.0] - 2026-08-23

### Added
- Initial release of **Rehab AI Bot** (`pmr-ai-paper-bot`).
- Automated daily PubMed harvesting for AI/ML/DL papers in Rehabilitation Medicine (*Archives of PM&R*, *Annals of Rehabilitation Medicine*).
- Clinical EBM critical appraisal using Google Gemini API.
- Automated Zotero reference upload, Obsidian-compatible local Markdown archiving (`data/reports/`), HTML Email reports, and Telegram notifications.
