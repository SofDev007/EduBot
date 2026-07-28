```
                                ███████╗██████╗ ██╗   ██╗██████╗  ██████╗ ████████╗
                                ██╔════╝██╔══██╗██║   ██║██╔══██╗██╔═══██╗╚══██╔══╝
                                █████╗  ██║  ██║██║   ██║██████╔╝██║   ██║   ██║
                                ██╔══╝  ██║  ██║██║   ██║██╔══██╗██║   ██║   ██║
                                ███████╗██████╔╝╚██████╔╝██████╔╝╚██████╔╝   ██║
                                ╚══════╝╚═════╝  ╚═════╝ ╚═════╝  ╚═════╝    ╚═╝
```

<div align="center">

# 🤖 EduBot — Adaptive AI Quiz Engine

**An intelligent exam-prep platform that generates its own question banks and adapts to every student in real time.**

![Python](https://img.shields.io/badge/Python-3.10-3776AB?logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.1-000000?logo=flask&logoColor=white)
![AI](https://img.shields.io/badge/AI-NVIDIA%20NIM-76B900?logo=nvidia&logoColor=white)
![Database](https://img.shields.io/badge/DB-SQLite%20%7C%20Postgres%20%7C%20MySQL-336791?logo=postgresql&logoColor=white)
![License](https://img.shields.io/badge/License-Proprietary-red)
![Status](https://img.shields.io/badge/status-active-success)

[![Launch Live Demo](https://img.shields.io/badge/Launch%20Live%20Demo-edubot--y4sk.onrender.com-00C853?style=for-the-badge&logo=render&logoColor=white&labelColor=1F2937)](https://edubot-y4sk.onrender.com/auth/login)

<sub>◤ Powered by NVIDIA NIM · Flask · SQLAlchemy ◢</sub>

</div>

---

## What is EduBot?

EduBot is a full-stack adaptive learning system. An admin uploads a subject syllabus; the platform uses a large language model to **auto-generate a bank of multiple-choice questions**. Students then take a quiz that **adapts to their performance question-by-question** — climbing to harder questions when they succeed, retreating and flagging *weak topics* when they struggle. At the end, each student gets a personalized breakdown of strong vs. weak topics and a **downloadable, QR-shareable certificate**.

> **In one line:** upload a syllabus → AI builds the questions → students take an adaptive quiz → everyone gets a smart, personalized result.

---

## 🧠 How the Adaptive Engine Thinks

```
┌─ Easy question asked
├─ ✓ CORRECT → Hard question (same topic)
│   ├─ ✓ CORRECT → New topic (marks STRONG) → easy question
│   └─ ✗ WRONG  → 2nd hard question (same topic)
│       └─ ✗ WRONG → New topic (marks WEAK) → easy question
└─ ✗ WRONG → skip hard → New topic → easy question
```
> Hard topic missed twice → **weak topic**. Easy topic cleared → **strong topic**. The final report is built from exactly these signals.

---

## Core Systems

| System | What it does |
|---|---|
| 🧠 **Adaptive Engine** | Easy → Hard branching per topic. Two failed hard questions flag a *weak topic*; a passed easy question marks a *strong topic*. |
| 🤖 **AI Question Generation** | Feeds the syllabus to NVIDIA NIM models and generates a de-duplicated MCQ bank in parallel batches. |
| 📊 **Full Topic Coverage** | Selection guarantees ≥1 question from every topic, then spreads the rest — no repeats within a session. |
| 🏆 **Certificates + QR** | Auto-generated certificate of achievement, downloadable and scannable to a phone via QR code. |
| 🎛️ **Admin Portal** | Create/edit subjects, upload syllabi, monitor generation progress, view reports, manage students & password-reset issues. |
| 🔐 **Auth & Security** | Bcrypt-hashed passwords, email verification, forced temp-password rotation, CORS allow-list, CSP + security headers, HSTS in production. |

---

## 🧬 Tech Stack

| Layer | Technology |
|---|---|
| **Backend** | Python 3.10 · Flask 3.1 · Flask-SQLAlchemy · Flask-Login · Flask-Bcrypt |
| **AI** | NVIDIA NIM (`meta/llama-3.1-8b-instruct` · `nvidia/nemotron-3-ultra`) via the OpenAI-compatible client |
| **Database** | SQLite (dev) · PostgreSQL / MySQL (production) |
| **Frontend** | Server-rendered Jinja2 templates · vanilla JS · animated card-deck UI |
| **Server** | Gunicorn (gthread) · Render blueprint included |

---

## Launch Sequence

### 1 · Prerequisites
- **Python 3.10.x** (pinned to `3.10.12`)
- **Git**
- An **NVIDIA NIM API key** → https://build.nvidia.com (needed for AI question generation)

### 2 · Get the code
```bash
git clone <your-repo-url> EduBot
cd EduBot
```

### 3 · Create & activate a virtual environment

**🪟 Windows — PowerShell**
```powershell
python -m venv venv
venv\Scripts\Activate.ps1
```
> If activation is blocked: run `Set-ExecutionPolicy -Scope Process RemoteSigned` first, then retry.

**🪟 Windows — Command Prompt**
```bat
python -m venv venv
venv\Scripts\activate.bat
```

**🐧 Linux / 🍎 macOS**
```bash
python3 -m venv venv
source venv/bin/activate
```

### 4 · Install dependencies
```bash
pip install -r requirements.txt
```

### 5 · Configure environment
Copy the template and fill in your values:

```bash
# Windows
copy .env.example .env
# Linux / macOS
cp .env.example .env
```

Minimum to run locally — edit `.env`:
```ini
SECRET_KEY=<a-long-random-string>
NVIDIA_API_KEY=nvapi-your-key-here
ADMIN_PASSWORD=<pick-a-strong-admin-password>
DB_TYPE=sqlite
```
> The admin account is **auto-created on first launch** using `ADMIN_USERNAME` (default `admin`) + `ADMIN_PASSWORD`. Tables are created automatically too — no manual migration needed.

### 6 · Launch 

**🪟 Windows** — double-click `run.bat`, or from a terminal:
```bat
run.bat
```

**🐧 Linux / 🍎 macOS**
```bash
chmod +x run.sh   # first time only
./run.sh
```

**Any OS (direct)** — works everywhere Python runs:
```bash
python app.py
```
> `run.bat` / `run.sh` just activate the `venv` and start the server. `python start.py` runs the same server behind a pre-flight self-check (imports, DB, API endpoints).

### 7 · Enter EduBot
| Portal | 🖥️ Local | 🌐 Live |
|---|---|---|
| 👨‍🎓 **Student** | http://localhost:5000 | **https://edubot-y4sk.onrender.com** |
| 🛠️ **Admin** | http://localhost:5000/auth/login?role=admin | **https://edubot-y4sk.onrender.com/auth/login?role=admin** |

> 💡 The live site runs on Render's free tier — the first request after it's been idle can take ~30–60s to wake, then it's fast.

**First run:** log in as admin → *Create Subject* → *Upload Syllabus* → wait for AI generation → students register and start quizzing.

---

##  Environment Reference

| Variable | Purpose | Default |
|---|---|---|
| `SECRET_KEY` | Flask session signing key (**required** in production) | random (dev only) |
| `NVIDIA_API_KEY` | NVIDIA NIM key for AI question generation | — |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | Seeds the first admin on startup | `admin` / — |
| `DB_TYPE` | `sqlite` \| `mysql` (ignored if `DATABASE_URL` is set) | `sqlite` |
| `DATABASE_URL` | Postgres connection string (takes priority) | — |
| `FLASK_ENV` / `FLASK_DEBUG` | `production` / `0` recommended | `development` / `0` |
| `APP_BASE_URL` · `CORS_ORIGINS` | Public URL & trusted CORS origins | `http://localhost:5000` |
| `SMTP_*` · `MAIL_FROM` | Email for password-reset notifications | — |
| `TZ_NAME` | Display timezone | `Asia/Kolkata` |

---

##  Deploy

- **Render (1-click):** push to GitHub → *New +* → *Blueprint* → pick the repo (`render.yaml` is included). Set `DATABASE_URL`, `ADMIN_PASSWORD`, and `NVIDIA_API_KEY` as dashboard secrets. &nbsp;→&nbsp; **Live instance:** <https://edubot-y4sk.onrender.com>
- **Any Unix host:**
  ```bash
  gunicorn "app:create_app()" --workers 1 --threads 16 --worker-class gthread --timeout 120 --bind 0.0.0.0:$PORT
  ```
  > Single worker on purpose — question generation uses an in-process thread + shared progress state. Concurrency comes from the 16 threads (a quiz is I/O-bound).
  > ⚠️ **Windows:** Gunicorn is Unix-only. For production on Windows use `waitress-serve` or run behind WSL.

---

## 🔐 License & Copyright

> **© 2026 Arnav Jaiswal. All Rights Reserved.**

This project is released under a **Proprietary License** — see [`LICENSE`](LICENSE). No permission is granted to use, copy, modify, distribute, or deploy this software, in whole or in part, without the **prior written consent of the author**. Viewing the repository does not grant any rights.

**"Registering" your ownership — how the no-copy protection actually works:**
1. **Copyright is automatic.** Under the Berne Convention, you own the copyright the moment you create the work — no filing required. The `LICENSE` + this notice make that ownership explicit and enforceable.
2. **The proprietary `LICENSE`** is the enforceable mechanism that legally prohibits others from copying or reusing the code.
3. **Optional formal registration** (a separate legal step you file yourself) strengthens enforcement in some jurisdictions — e.g. the [Indian Copyright Office](https://copyright.gov.in) or the [U.S. Copyright Office](https://www.copyright.gov). This repo can't file that for you, but the code above is what a registration would protect.

<div align="center">
<sub>Built  by <b>Arnav Jaiswal</b> · EduBot © 2026</sub>
</div>
