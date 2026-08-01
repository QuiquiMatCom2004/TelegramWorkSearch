# Telegram Job Search Intelligence

An intelligent job search assistant that monitors Telegram job channels, classifies opportunities using LLMs, and builds a company intelligence database to help you land interviews.

## Features

- 📱 **Telegram Integration** - Connect via Telethon (user account) to access private channels
- 🤖 **LLM Classification** - Uses OpenRouter (Claude/GPT) to score job relevance against your profile
- 🏢 **Company Intelligence** - Aggregates problems, tech stacks, hiring patterns from all job postings
- 📊 **Interview Prep** - Generates strategic questions, cover letter points, and application tips
- 🗄️ **PostgreSQL Database** - Persistent storage with full history
- ⏰ **Scheduled Monitoring** - Automatic fetching every 30 minutes (configurable)

## Quick Start

### 1. Prerequisites

- Python 3.11+
- PostgreSQL 14+
- Telegram API credentials (from [my.telegram.org](https://my.telegram.org))
- OpenRouter API key (from [openrouter.ai](https://openrouter.ai/keys))

### 2. Installation

```bash
cd TelegramWorkSearch
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your credentials
```

### 3. Configure Environment

Edit `.env` with your credentials:

```env
TELEGRAM_API_ID=123456
TELEGRAM_API_HASH=your_hash_here
TELEGRAM_PHONE=+1234567890
OPENROUTER_API_KEY=sk-or-v1-...
DATABASE_URL=postgresql+asyncpg://user:pass@localhost/telegram_jobs
JOB_CHANNELS=@remotejobs @golangjobs @pythonjobs
USER_PROFILE=Senior Python/Go backend developer, 5+ years, AWS/K8s, seeking remote with visa sponsorship
```

### 4. Initialize Database

```bash
alembic upgrade head
```

### 5. Run the Monitor

```bash
# One-time fetch from channels
python -m src.telegram.monitor @channel1 @channel2

# Or use CLI for interactive management
python main.py --help
```

## CLI Commands

```bash
# Monitor channels continuously
python main.py monitor @channel1 @channel2

# View top companies by relevant job postings
python main.py companies

# Get interview prep for a company
python main.py prep "Company Name"

# View your candidate profile
python main.py profile

# Database statistics
python main.py stats

# Export company report
python main.py export "Company Name" --format markdown -o report.md
```

## Architecture

```
src/
├── telegram/          # Telegram client & message processing
│   └── monitor.py     # Channel monitoring & job extraction
├── llm/               # LLM integration
│   ├── client.py      # OpenRouter client
│   ├── classifier.py  # Job relevance classification
│   └── company_intelligence.py  # Company analysis
├── db/                # Database layer
│   ├── models.py      # SQLAlchemy models
│   ├── database.py    # Connection management
│   └── repositories.py # Data access layer
├── analysis/          # Analytics & reporting (TODO)
└── cli/               # Command-line interface
    └── main.py        # Typer-based CLI
```

## Database Schema

Key tables:
- **channels** - Monitored Telegram channels
- **companies** - Extracted company profiles
- **jobs** - Classified job postings with relevance scores
- **job_analyses** - Detailed LLM analysis per job
- **company_intelligence** - Aggregated insights per company
- **user_profile** - Your candidate profile for matching
- **messages** - Raw Telegram messages for audit

## How It Works

1. **Fetch** - Connects to Telegram, joins configured channels, fetches new messages
2. **Detect** - Heuristic + LLM identifies job postings
3. **Extract** - Pulls company name, title, requirements, salary, location
4. **Classify** - LLM scores relevance (0-1) against your profile
5. **Analyze** - Deep analysis of relevant jobs: requirements, culture, interview process
6. **Aggregate** - Builds company intelligence: common problems, tech stack, hiring patterns
7. **Advise** - Generates application strategy, cover letter points, interview questions

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `TELEGRAM_API_ID` | Telegram API ID | Required |
| `TELEGRAM_API_HASH` | Telegram API Hash | Required |
| `TELEGRAM_PHONE` | Your phone number | Required |
| `OPENROUTER_API_KEY` | OpenRouter API key | Required |
| `LLM_MODEL` | Model to use | `anthropic/claude-3.5-sonnet` |
| `DATABASE_URL` | PostgreSQL connection | Required |
| `JOB_CHANNELS` | Space-separated channels | Empty |
| `USER_PROFILE` | Your profile for matching | Empty |
| `MIN_RELEVANCE_SCORE` | Minimum score for relevance | 0.7 |
| `FETCH_INTERVAL_SECONDS` | Monitoring interval | 1800 (30 min) |

## Development

```bash
# Run tests
pytest tests/

# Create migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Format code
ruff format src/
ruff check src/
```

## Tips for Best Results

1. **Detailed Profile** - The more specific your `USER_PROFILE`, better the matching
2. **Channel Quality** - Curate high-signal channels (avoid spammy ones)
3. **Regular Monitoring** - Run continuously to build company intelligence over time
4. **Review Classifications** - Check `relevance_level` in DB to tune your profile
5. **Company Research** - Use `prep` command before interviews

## License

MIT