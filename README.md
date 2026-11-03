<div align="center">

# 🏥 Rehab AI Bot (`pmr-ai-paper-bot`)

**Automated PubMed AI/ML Literature Harvesting, Clinical EBM Fact-Checking & Zotero/Obsidian Archiving Bot for Physical Medicine & Rehabilitation (PM&R)**

[![Python 3.11](https://img.shields.io/badge/Python-3.11-3776AB.svg?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Docker Hub](https://img.shields.io/badge/Docker_Hub-kimmingil%2Frehab--ai--bot-2496ED.svg?style=flat-square&logo=docker&logoColor=white)](https://hub.docker.com/r/kimmingil/rehab-ai-bot)
[![Gemini](https://img.shields.io/badge/Google_Gemini-3.8_Flash-8E75B2.svg?style=flat-square&logo=google&logoColor=white)](https://ai.google.dev/)
[![PubMed](https://img.shields.io/badge/NCBI-PubMed_Entrez-326599.svg?style=flat-square)](https://pubmed.ncbi.nlm.nih.gov/)
[![Zotero](https://img.shields.io/badge/Reference-Zotero_API-CC2936.svg?style=flat-square&logo=zotero&logoColor=white)](https://www.zotero.org/)
[![SQLite3](https://img.shields.io/badge/SQLite-WAL_Mode-003B57.svg?style=flat-square&logo=sqlite&logoColor=white)](https://www.sqlite.org/)

<br>

**[ 📖 View Update History (Changelog) ](./CHANGELOG.md)**

</div>

---

## 🌟 Overview

**Rehab AI Bot** is a lightweight, zero-maintenance Docker container built for **Physical Medicine and Rehabilitation (PM&R)** clinicians and medical AI researchers. Every morning (default `08:00 AM`), it scans **PubMed (NCBI Entrez)** for newly published Artificial Intelligence, Machine Learning, and Deep Learning studies in target rehabilitation journals, critically evaluates each paper from a **Senior PM&R Professor & EBM (Evidence-Based Medicine)** perspective using **Google Gemini**, and automatically archives the results across **4 channels**:

1. **📂 Local Obsidian Markdown Vault (`data/reports/*.md`):** Saves permanent, YAML-frontmatter Markdown notes ready for Obsidian or Notion.
2. **📚 Zotero Library Sync:** Uploads clean bibliographic metadata, abstracts, and DOIs directly into your designated Zotero collection.
3. **✈️ Telegram Instant Briefing:** Sends mobile-optimized HTML summaries with direct PubMed links to your Telegram chat or department channel.
4. **📧 Responsive HTML Email Newsletter:** Delivers a clean journal-club style HTML briefing to one or multiple recipients.

---

## ✨ Key Features

- **🛡️ Zero-Omission Archiving Engine:**
  - **First Run:** Automatically harvests the **entire historical archive** of matching AI/ML papers from your target journals since their inception.
  - **Daily Runs:** Scans a rolling **60-day window** (`DAYS_TO_FETCH=60`) to catch delayed PubMed indexing while filtering out already-processed papers via **PMID + DOI dual deduplication** in local SQLite (`WAL` mode) before downloading XML payloads.
- **🧠 3-Tier Gemini AI Failover (`gemini-3.8-flash`):**
  - Uses **Google Gemini 3.8 Flash** by default and automatically fails over to `gemini-3.6-flash` $\rightarrow$ `gemini-3.5-flash-lite` $\rightarrow$ `gemini-2.5-flash` if Google API servers experience temporary `503/500` spikes.
  - **Clinical EBM Persona:** Evaluates every study on **(1) Senior Professor's One-Line Verdict**, **(2) AI Model & Dataset Specs**, **(3) Clinical Innovation vs. Red Flags (overfitting, lack of external validation)**, and **(4) Real-World Rehab Department Adoption Scenario (Adopt / Wait & See / Reject)**.
- **💤 Ultra-Low Memory Subprocess Architecture:**
  - The master scheduler (`src/run.py`) spawns the analysis pipeline (`src/main.py`) in an isolated child process once a day and returns **100% of memory** back to the OS immediately upon completion (capped at `512MB` in `compose.yaml` for Synology NAS safety).
- **📦 Plug-and-Play Docker Image (`kimmingil/rehab-ai-bot:latest`):**
  - Automatically generates `config/settings.yaml` on first boot if mounting an empty `./config` folder.
  - Fully compatible with **Synology Container Manager**, **Portainer**, and **Watchtower** automatic image updates.

---

## 🚀 Quick Start (Docker Hub — Recommended for All Users)

You do **not** need to clone the source code to run **Rehab AI Bot**. Anyone can deploy and update the pre-built image directly from **Docker Hub** (`kimmingil/rehab-ai-bot:latest`) or **GitHub Container Registry** (`ghcr.io/mingil/rehab-ai-bot:latest`).

### 1. Create a Project Folder & `.env` File

Create a folder on your server or Synology NAS (e.g., `/volume1/docker/rehab-ai-bot`) and create two files: **`compose.yaml`** and **`.env`**.

#### `compose.yaml`
```yaml
services:
  rehab-ai-bot:
    image: kimmingil/rehab-ai-bot:latest
    container_name: pmr-ai-paper-bot
    restart: on-failure:5
    init: true
    user: "1026:100"          # Adjust to your NAS PUID:PGID (or omit on standard Linux)
    deploy:
      resources:
        limits:
          memory: 512M
    env_file:
      - .env
    environment:
      - TZ=Asia/Seoul
      - PYTHONUNBUFFERED=1
    volumes:
      - ./config:/app/config
      - ./logs:/app/logs
      - ./data:/app/data
```

#### `.env`
```env
# --- 🤖 AI Configuration (Required) ---
GEMINI_API_KEY=your_google_gemini_api_key
GEMINI_MODEL=gemini-3.8-flash

# --- 📧 Email Notification (Optional - Gmail App Password) ---
EMAIL=your_email@gmail.com
EMAIL_PASSWORD=your_16_digit_app_password
EMAIL_TO=recipient1@gmail.com,recipient2@hospital.org

# --- ✈️ Telegram Notification (Optional) ---
TELEGRAM_BOT_TOKEN=1234567890:AAH_your_bot_token
TELEGRAM_CHAT_ID=123456789

# --- 📚 Zotero Integration (Optional) ---
ZOTERO_USER_ID=your_zotero_user_id
ZOTERO_API_KEY=your_zotero_api_key
ZOTERO_LIBRARY_TYPE=user
ZOTERO_CANDIDATES_ID=your_collection_key

# --- 🔍 PubMed API & Schedule Settings (Optional) ---
NCBI_API_KEY=your_ncbi_api_key
SCHEDULE_TIME=08:00
DAYS_TO_FETCH=60
```

### 2. Start the Container
```bash
docker compose up -d
```

### 3. Updating to the Latest Version
Whenever a new version is published to Docker Hub, simply pull the updated image and restart:
```bash
docker compose pull
docker compose up -d
```
*(In Synology Container Manager: go to **Registry** $\rightarrow$ search **`kimmingil/rehab-ai-bot`** $\rightarrow$ right-click **Download `latest`** $\rightarrow$ **Project / Container Reset**).*

---

## ⚙️ Customizing Target Journals & Keywords

On first launch, the container automatically creates `./config/settings.yaml` if it does not exist:

```yaml
# 🏥 Target Journals (PubMed Full Title or Medline Abbreviation)
target_journals:
  - "Archives of physical medicine and rehabilitation"
  - "Annals of rehabilitation medicine"

# 🧠 Target AI/ML Keywords (Searched in Title/Abstract [tiab])
target_keywords:
  - "Artificial Intelligence"
  - "Machine Learning"
  - "Deep Learning"
```

You can edit `./config/settings.yaml` at any time — changes take effect automatically on the next daily scan without rebuilding the container! You can also override them via `.env` variables (`TARGET_JOURNALS` and `TARGET_KEYWORDS`, comma-separated).

---

## 🛠️ CLI Diagnostic & Manual Control Commands

You can inspect the bot's database status or run a dry-run test at any time:

```bash
# 1. Check current DB count, saved Markdown reports, and active configuration
docker exec -it pmr-ai-paper-bot python src/main.py --status

# 2. Dry-Run (Check if new papers exist on PubMed without calling Gemini or sending alerts)
docker exec -it pmr-ai-paper-bot python src/main.py --dry-run --days 30

# 3. Trigger an immediate manual run (limit to 3 papers)
docker exec -it pmr-ai-paper-bot python src/main.py --days 30 --limit 3
```

---

## 📂 Project Structure

```plaintext
📦 rehab-ai-bot
 ┣ 📂 .github/workflows/
 ┃ ┗ 📜 docker-publish.yml   # Automated Pytest + Docker Hub & GHCR CI/CD pipeline
 ┣ 📂 config/
 ┃ ┗ 📜 settings.yaml        # Target PubMed journals & AI/ML keywords
 ┣ 📂 src/
 ┃ ┣ 📜 run.py               # Lightweight daily scheduler & heartbeat monitor
 ┃ ┣ 📜 main.py              # Core orchestration pipeline & CLI diagnostics
 ┃ ┣ 📜 fetcher.py           # NCBI Entrez PubMed API harvester with retry/backoff
 ┃ ┣ 📜 analyzer.py          # 3-Tier Gemini AI EBM clinical analyzer
 ┃ ┣ 📜 zotero_mgr.py        # Zotero API bibliographic uploader
 ┃ ┣ 📜 notifier.py          # Obsidian Markdown, Telegram HTML & Email dispatcher
 ┃ ┗ 📜 local_db.py          # SQLite WAL deduplication store (PMID + DOI)
 ┣ 📂 tests/
 ┃ ┗ 📜 test_bot.py          # Automated unit test suite (pytest)
 ┣ 📂 data/                  # Persistent volume: papers.db & reports/*.md
 ┣ 📂 logs/                  # Persistent volume: rotating system.log
 ┣ 📜 Dockerfile             # Production Python 3.11 slim image with HEALTHCHECK
 ┣ 📜 compose.yaml           # Docker Compose deployment configuration
 ┣ 📜 requirements.txt       # Pinned Python dependencies
 ┣ 📜 .env.example           # Environment variable template
 ┣ 📜 CHANGELOG.md           # Version history
 ┗ 📜 LICENSE                # MIT License
```

---

## 📜 License & Disclaimer

Released under the **MIT License**.

*Disclaimer: AI-generated critical appraisals are intended to assist medical professionals in literature screening and journal club preparation, and do not substitute for independent clinical judgment.*
