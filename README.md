# Hermes

AI-powered email assistant for any business. Hermes fetches your emails, classifies them by intent, generates brand-voice draft replies, validates quality, and optionally auto-sends — so you can respond faster without losing your personal touch.

## How It Works

```
Email Inbox → Fetch → Classify → Extract Details → Generate Draft → Validate → Auto-Send / Queue
```

1. **Fetch** — Pulls unread emails from one or more Gmail accounts (via Maton gateway or direct OAuth)
2. **Classify** — Categorizes each email using regex patterns + AI fallback into your custom categories
3. **Extract** — AI pulls structured details: names, dates, questions, goals, experience level
4. **Generate** — Creates a reply in your brand voice using category-specific templates
5. **Validate** — Quality checks: detail coverage, hallucination detection, tone enforcement, length
6. **Send** — Auto-sends high-confidence drafts or queues for your review

## Quick Start

```bash
pip install hermes-email
hermes setup
```

The setup wizard walks you through:
- Business identity (name, owner, location)
- Email accounts to monitor
- Email provider (Gmail OAuth or Maton)
- Custom categories with auto-send rules
- AI provider (Anthropic Claude, OpenAI, or MiniMax)
- Supabase database connection
- Brand voice generation
- Category template generation

Then run your first cycle:

```bash
hermes cycle
```

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────┐
│   Gmail      │────▶│ Maton / OAuth │────▶│ Hermes  │
│  (N accounts)│     └──────────────┘     │ Pipeline │
└─────────────┘                           └────┬────┘
                                               │
                    ┌──────────────┐       ┌────▼────┐
                    │Claude / GPT  │◀──────│Draft Gen│
                    │  / MiniMax   │       └─────────┘
                    └──────────────┘            │
                                          ┌────▼────┐
                    ┌──────────────┐      │Supabase │
                    │  Dashboard   │◀─────│Database │
                    │  (Vercel)    │      └─────────┘
                    └──────────────┘
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `hermes setup` | Interactive first-time setup wizard |
| `hermes cycle` | Run one email processing cycle |
| `hermes status` | Show inbox counts per account |
| `hermes drafts` | List pending drafts (with `--status` filter) |
| `hermes train` | Refresh voice samples from sent history |
| `hermes migrate` | Run database migrations |
| `hermes seed` | Populate database from config |
| `hermes install-skill` | Install as Claude Code skill |

## Configuration

Hermes uses two files:

**`hermes.yaml`** — Business identity, email accounts, categories, AI settings:

```yaml
business:
  name: "Your Business Name"
  owner_name: "Your Name"
  location: "City, State"
  website: "https://yourbusiness.com"

email:
  provider: "gmail_oauth"  # or "maton"
  accounts:
    - address: "info@yourbusiness.com"
      role: "primary"
  reply_from: "info@yourbusiness.com"

categories:
  - slug: "inquiry"
    display_name: "General Inquiry"
    patterns: ["interested", "information", "question"]
    auto_send_enabled: false
  - slug: "billing"
    display_name: "Billing"
    patterns: ["invoice", "payment", "refund"]
    requires_review: true

ai:
  primary_provider: "anthropic"
```

**`.env`** — API keys (secrets only):

```
ANTHROPIC_API_KEY=sk-ant-...
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJ...
```

See `hermes.example.yaml` for all available options.

## Custom Categories

Define any categories that match your business. Each category gets:
- **Patterns** — Regex patterns for classification
- **Template** — A markdown file guiding draft generation
- **Auto-send rules** — Whether high-confidence drafts send automatically
- **Review requirements** — Whether human review is always required

```yaml
categories:
  - slug: "appointment"
    display_name: "Appointment Request"
    patterns: ["appointment", "schedule", "book(ing)?", "available"]
    auto_send_enabled: true
    min_confidence: 0.9
  - slug: "complaint"
    display_name: "Complaint"
    patterns: ["unhappy", "disappointed", "complaint", "problem"]
    requires_review: true
```

## Email Providers

### Gmail via Maton (Recommended)
Maton provides a simple API gateway to Gmail. Sign up at [maton.ai](https://maton.ai), connect your Gmail accounts, and paste the connection IDs during setup.

### Gmail via OAuth
For direct Gmail API access, create an OAuth Client ID in [Google Cloud Console](https://console.cloud.google.com) and run:
```bash
hermes setup  # select "Gmail via OAuth" in step 3
```

## AI Providers

| Provider | Models | Best For |
|----------|--------|----------|
| **Anthropic** | Claude Sonnet, Haiku | High-quality drafts, nuanced tone |
| **OpenAI** | GPT-4, GPT-3.5 | Fast, cost-effective |
| **MiniMax** | M2.7 | Budget-friendly alternative |

## Database

Hermes uses [Supabase](https://supabase.com) (free tier available) with these tables:

| Table | Purpose |
|-------|---------|
| `hermes_drafts` | Email records + generated drafts |
| `hermes_config` | Per-category settings |
| `hermes_templates` | Anchor text + voice samples |
| `hermes_audit_log` | Action history |
| `hermes_sender_history` | Repeat sender tracking |
| `hermes_sender_blacklist` | Blocked senders |

## Scheduling

### macOS (launchd)
```bash
hermes schedule --platform macos --interval 600
```

### Linux (cron)
```bash
hermes schedule --platform linux --interval 10
```

## Claude Code Integration

Install as a Claude Code skill:

```bash
hermes install-skill
```

Then Claude Code can run `hermes cycle`, `hermes status`, etc. when you mention emails.

## Forwarded Email Detection

If you have emails auto-forwarded from another account (e.g., a virtual assistant, booking system notifications, or form submissions), Hermes can detect the original sender and reply to them directly instead of the forwarder.

```yaml
email:
  forwarding_accounts:
    - "assistant@mycompany.com"
    - "notifications@mybookingsystem.com"
```

When an email arrives from a forwarding account, Hermes extracts the real sender using multiple patterns:
1. **Booking systems** (Wodify, etc.) — Extracts from "Contact Info" + `mailto:` links
2. **Form submissions** (Gravity Forms, WordPress) — Extracts from "Email:" fields
3. **Gmail forwarded headers** — Parses `From: Name <email>` in the body
4. **Fallback** — Finds any non-system email in the body

System/noreply addresses (`noreply@`, `notifications@`, etc.) are automatically skipped during extraction.

## Safety

- Configurable categories can require human review (billing by default)
- Hallucination detection blocks unauthorized financial commitments
- Banned phrase list prevents off-brand tone
- Follow-up emails in existing threads block auto-send
- Sender blacklist filters spam
- All actions are audit-logged

## Project Structure

```
hermes/
├── hermes/
│   ├── config.py              # YAML config loader
│   ├── cli.py                 # Click CLI
│   ├── pipeline/              # Email processing pipeline
│   │   ├── fetch.py           # Email fetching + dedup
│   │   ├── classify.py        # Intent classification
│   │   ├── extract.py         # Detail extraction
│   │   ├── generate.py        # Draft generation
│   │   ├── validate.py        # Quality validation
│   │   ├── send.py            # Email sending
│   │   └── cycle.py           # Orchestrator
│   ├── providers/             # Email + AI provider adapters
│   ├── wizard/                # Setup wizard + generators
│   └── scheduler/             # launchd/cron generators
├── supabase/                  # Database migrations
├── skill/                     # Claude Code skill wrapper
├── templates/                 # Category response templates
└── hermes.example.yaml        # Example configuration
```

## License

MIT
