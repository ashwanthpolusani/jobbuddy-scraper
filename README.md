# JobBuddy Scraper

A fast, modular, config-driven job scraper engine targeting company ATS platforms directly (Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Eightfold, Workable, Uber, MyNextHire). 

Extracts early-career tech jobs at high speed, verifies deep job descriptions using Gemini AI, and stores clean opportunities in MongoDB Atlas.

---

## Architecture: Two-Stage Pipeline

```
                       Target Career URLs (MongoDB)
                                    │
                                    ▼
       ┌────────────────────────────────────────────────────────┐
       │             STAGE 1: HIGH-SPEED ATS SWEEP              │
       │                                                        │
       │  • Tier 1: Pure Python ATS Parsers (0 AI cost, ~1s)    │
       │  • Tier 2: Gemini AI Fallback for custom career pages  │
       │  • Skip previously BLOCKED jobs in 1 batch query       │
       │  • Parametric pre-filters (0-1 YOE, junior/senior)     │
       │  • Deterministic category & link_type classification   │
       └────────────────────────────┬───────────────────────────┘
                                    │
                                    ▼
       ┌────────────────────────────────────────────────────────┐
       │                  MONGODB: jobs [STAGE 1]               │
       │         (Status: PENDING, Native BSON TTL)             │
       └────────────────────────────┬───────────────────────────┘
                                    │
                                    ▼
       ┌────────────────────────────────────────────────────────┐
       │         STAGE 2: DEEP EXPERIENCE VERIFICATION          │
       │                                                        │
       │  • Persistent Playwright Chromium session (JDFetcher)  │
       │  • Deep eligibility gate (clearance, visa, citizenship)│
       │  • Gemini AI verification against full JD text         │
       │  • Record 64-byte SHA-256 tombstones for rejected jobs │
       │  • Cleanly delete ineligible jobs from active database │
       └────────────────────────────┬───────────────────────────┘
                                    │
                                    ▼
          Verified Jobs & Active Profile Metadata in MongoDB
                                    │
                                    ▼
      Instant Display on JobBuddy WebApp (Zero Setup or Self-Hosted)
```

---

## Complete Step-by-Step Onboarding Guide

Follow these exact steps to fork this repository, configure your cloud database, and automate your daily job search pipeline:

### Step 1: Fork & Clone the Repository
1. Click **Fork** in the top-right corner of this repository to create your own copy on GitHub.
2. Clone your forked repository locally:
   ```bash
   git clone https://github.com/<your-username>/jobbuddy-scraper.git
   cd jobbuddy-scraper
   ```

### Step 2: Create a Free MongoDB Atlas Database
1. Go to [MongoDB Atlas](https://www.mongodb.com/cloud/atlas) and sign up for a free account.
2. Click **Create Deployment** and choose the **M0 (Free Cluster)** tier.
3. Select your preferred cloud provider (e.g. AWS) and the region closest to you (e.g. `ap-south-1` Mumbai or `us-east-1` N. Virginia).
4. Set Cluster Name to `jobbuddy-cluster` and click **Create Deployment**.
5. The default database name used by JobBuddy is `job_aggregator`.

### Step 3: Configure Network Access (`0.0.0.0/0`)
> **Important:** GitHub Actions cloud runners and Netlify serverless functions use dynamically rotating IP addresses. Whitelisting `0.0.0.0/0` is mandatory so your scraper and webapp can connect without firewall blocks.

1. In MongoDB Atlas left sidebar, click **Security > Network Access**.
2. Click **+ Add IP Address**.
3. Click **Allow Access from Anywhere** (this enters `0.0.0.0/0` into the CIDR box).
4. Enter comment `Allow GitHub Actions and WebApp` and click **Confirm**.

### Step 4: Create Two Database Users (Security Best Practice)
To prevent your database credentials from ever being abused, create **two distinct database users**:

#### User 1: Scraper Engine (Read / Write)
- In the left sidebar, click **Security > Database Access > Add New Database User**.
- Authentication Method: **Password**.
- Username: `scraper_admin`
- Password: Click **Autogenerate Secure Password** and copy it somewhere safe.
- Database User Privileges: Select **Built-in Role > Read and write to any database** (or `readWrite` on database `job_aggregator`).
- Click **Add User**.

#### User 2: WebApp Frontend (Read-Only)
- Click **Add New Database User** again.
- Username: `webapp_reader`
- Password: Click **Autogenerate Secure Password** and copy it.
- Database User Privileges: Choose **Built-in Role > Only read any database** (or `read` on database `job_aggregator`).
- Click **Add User**.

> **Security Note:** The `scraper_admin` connection string has write permissions and belongs only in your private GitHub Actions Secrets. The `webapp_reader` string is strictly read-only and is safe to use in the frontend "Connect DB" modal. Even if someone inspects the browser, they cannot modify or delete your data.

### Step 5: Get a Free Google Gemini API Key
1. Go to [Google AI Studio](https://aistudio.google.com/).
2. Sign in with your Google account.
3. Click **Get API key** in the left sidebar, then click **Create API key**.
4. Copy your generated key (starts with `AIzaSy...`).
*Note: Google AI Studio provides 15 requests/min (RPM) and 1,500 requests/day for free, which is more than enough to verify 200+ jobs daily.*

### Step 6: Configure GitHub Actions Secrets
1. In your forked GitHub repository, click **Settings > Secrets and variables > Actions**.
2. Under **Repository secrets**, click **New repository secret**:
   - **Secret 1:**
     - Name: `MONGODB_URI`
     - Value: `mongodb+srv://scraper_admin:<PASSWORD>@jobbuddy-cluster.xxxxx.mongodb.net/job_aggregator?retryWrites=true&w=majority`
     *(Replace `<PASSWORD>` and your cluster host).*
   - **Secret 2:**
     - Name: `GEMINI_API_KEY`
     - Value: `<Your Gemini API Key from Step 5>`

### Step 7: Push Career URLs & Run the Pipeline
1. Ingest company career portals into your database:
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   
   # Add your target company career URLs (one per line)
   python cli.py push-urls --file urls.txt
   ```
2. **Trigger Your First Run on GitHub:**
   - Go to your repository's **Actions** tab on GitHub.
   - Select **JobBuddy Scraper Pipeline** on the left.
   - Click **Run workflow** > select branch `master` > click **Run workflow**.
   - The workflow runs Stage 1 (Fast ATS sweep) and Stage 2 (Gemini verification).
3. **Automated Daily Runs:**
   - The pipeline runs automatically every day at **08:30 AM IST (03:00 UTC)** via `.github/workflows/scraper.yml`.

---

## Viewing Your Jobs: Frontend Options

### Option A: Use Our Hosted JobBuddy Site (Instant Plug & Play - Zero Setup)
You do **not** need to deploy any frontend! You can use our hosted platform:

1. Open **[https://buddyjob.netlify.app/](https://buddyjob.netlify.app/)**.
2. Click the **"⚙️ Connect DB"** button in the header.
3. Paste your **Read-Only MongoDB Connection String** (from Step 4, User 2):
   ```
   mongodb+srv://webapp_reader:<PASSWORD>@jobbuddy-cluster.xxxxx.mongodb.net/job_aggregator?retryWrites=true&w=majority
   ```
4. Click **Connect Database**.
5. **What happens automatically:**
   - Badge turns **🟢 Custom DB**.
   - Your private scraped jobs load directly into the feed.
   - Category tabs automatically update to match your scraped tracks (e.g., Software Engineering, Data/AI, or Analyst).
   - Your configured cities appear as 1-click filter pills.
   - The connection string is saved only in your local browser `localStorage` and sent over an encrypted HTTPS header (`x-mongo-uri`). It is never stored on our server.

### Option B: Fork & Deploy Your Own Frontend
If you want your own custom domain or custom branding:
1. Fork the frontend repository: [https://github.com/ashwanthpolusani/scrapperbuddy](https://github.com/ashwanthpolusani/scrapperbuddy).
2. Connect the repository to [Netlify](https://www.netlify.com/).
3. Set environment variable `MONGODB_URI` = `<Your Read-Only Connection String>`.
4. Deploy! Netlify automatically serves the site and serverless API functions.

---

## Adapting for Your Own Profile (Example)

The default configuration is tuned for an **Indian tech fresher (0-1 YOE)**. If you (or an AI assistant like Copilot, Cursor, or Claude Code) are adapting this for a different profile—such as a **5-year experienced Software Analyst targeting Hyderabad and Remote**—you only need to update a few lines in `scraper.config.json`:

```json
{
  "locations": {
    "allowed_cities": ["Hyderabad"],
    "remote_rules": {
      "allow_worldwide_remote": true
    }
  },
  "experience": {
    "target_level": "mid_senior",
    "min_years": 4,
    "max_years": 7,
    "exclude_junior_roles": true
  },
  "skills": {
    "role_title": "Software Analyst / Systems Analyst",
    "target_skills": ["SQL", "Python", "Systems Analysis", "Requirements Analysis"]
  }
}
```

### What Happens Automatically:
1. **Locations:** Matches jobs in **Hyderabad** AND any **Worldwide Remote** roles. Rejects other domestic cities (e.g. Pune, Bengaluru).
2. **Experience Filtering:** Pre-filters automatically discard junior, fresher, and intern listings (`min_years >= 4`), while keeping Senior and Mid-level Analyst postings.
3. **Stage 2 Verification:** Gemini evaluates the full JD against your 4–7 YOE target. The threshold automatically scales to ensure only matching opportunities are saved.
4. **Metadata Sync:** The scraper publishes your new profile, categories, and allowed cities to MongoDB `meta` collection, so the frontend UI dynamically mirrors your new profile.

---

## Configuration Reference (`scraper.config.json`)

The entire scraping logic is parametrically controlled by `scraper.config.json`, divided into 9 clear sections:

```
scraper.config.json
├── 1. locations             ──► Primary country (India), allowed cities, remote & visa rules
├── 2. experience            ──► Target level (fresher/intern), min/max years (0-1), senior exclusions
├── 3. skills                ──► Role title, target tech stack skills, excluded technologies
├── 4. categories            ──► Enabled tracks (software_engineering, data_ml, etc.)
├── 5. compensation          ──► Require disclosed salary toggle, salary floors (USD / INR LPA)
├── 6. hard_rejection_rules  ──► Rejection toggles for clearance, citizenship, non-English titles
├── 7. ai_models             ──► Gemini model pool, rate limits, and Stage 1 AI fallback toggle
├── 8. database              ──► MongoDB collection names and BSON TTL retention days
└── 9. runner                ──► Runtime limits and polite request delays
```

### Zero-Crash Architecture
Missing or deleted keys in `scraper.config.json` automatically fall back to safe memory defaults via `deep_merge()`. The scraper will never crash with a `KeyError`.

---

## Master CLI Commands (`cli.py`)

| Command | Description |
| :--- | :--- |
| `python cli.py run` | Runs Stage 1 fast sweep followed by Stage 2 deep verification. |
| `python cli.py validate` | Validates `scraper.config.json` against current schema and environment. |
| `python cli.py push-urls --file urls.txt` | Ingests company URLs into MongoDB `target_urls` collection. |
| `python cli.py discover --prompt "fintech startups in India"` | Discovers new company ATS career pages using Gemini + web probing. |
| `python cli.py list-presets` | Lists available candidate presets (`india_fresher`, `indian_internships`). |
| `python cli.py use-preset <name>` | Activates a preset into `scraper.config.json` with an automatic backup. |

---

## Supported ATS Platforms

| Platform | Extraction Method | Sample URL |
| :--- | :--- | :--- |
| **Greenhouse** | Public Boards REST API + EU fallback | `boards-api.greenhouse.io/v1/boards/{company}/jobs` |
| **Lever** | Public Postings API (JSON mode) | `api.lever.co/v0/postings/{company}` |
| **Ashby** | Public Posting API | `jobs.ashbyhq.com/{company}` |
| **Workday** | Direct CXS JSON API (Dynamic pagination) | `*.myworkdayjobs.com/*` |
| **Eightfold** | Paginated Search API (300ms pacing) | `*.eightfold.ai/careers` |
| **SmartRecruiters** | Public Postings API | `api.smartrecruiters.com/v1/companies/{company}/postings` |
| **Workable** | Widget Accounts API | `apply.workable.com/api/v1/widget/accounts/{company}` |
| **MyNextHire** | Career Endpoints | `*.mynexthire.com` |
| **Uber Careers** | Public Opportunities API | `uber.com/careers` |
| **Custom / Unknown** | Intelligent Gemini AI Fallback | Any HTML career portal |

---

## Data Integrity & Storage Efficiency

- **Native BSON UTC Dates:** All dates are stored as BSON `Date` objects (`datetime.now(timezone.utc)`), enabling MongoDB native TTL auto-cleanup:
  - `jobs`: Auto-expires after 30 days (`expireAfterSeconds: 2592000`).
  - `site_stats`: Auto-expires after 14 days (`expireAfterSeconds: 1209600`).
  - `blocked_hashes`: Auto-expires after 90 days (`expireAfterSeconds: 7776000`).
- **64-Byte SHA-256 Tombstones:** Rejected jobs are stored as SHA-256 hashes (`company:job_id:title`) in `blocked_hashes`. Stage 1 checks these in a single batch query, skipping ineligible jobs forever at $0 AI cost.
- **Atomic Upserts:** Uses `$setOnInsert` for immutable `first_seen` timestamps and `$set` for live status.
- **Thread Safety:** MongoDB connection singleton is guarded by a `threading.Lock()` to prevent race conditions during multithreaded ATS sweeps.

---

## Testing

Run the automated test suite covering regex caching, eligibility filters, ATS parsers, and config schemas:

```bash
python -m unittest discover -v -s tests -p "test_*.py"
```

---

## Future Roadmap: Expanded Platform Resources

For candidates using our platform, we are rolling out dedicated career companion modules:
1. **Interview Prep Hub (`/interview-prep`):** Curated 75 core DSA patterns, fresher System Design concepts, role-specific question banks (SQL, Python, Cloud), and behavioral STAR method templates.
2. **Resume Optimizer & ATS Explainer (`/resume-guide`):** Breakdown of corporate ATS resume parsers, high-impact action verb cheat-sheets, and formatting rules to pass automated filters.
3. **Application Tracker (`/tracker`):** A zero-backend, `localStorage`-driven Kanban board directly linked to the live job feed to track applications from initial click to interview offer.
