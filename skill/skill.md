---
name: hermes
description: AI email processing -- fetch emails, classify by intent, generate brand-voice draft replies, validate, and auto-send. Use when the user mentions emails, inbox, email drafts, email responses, or email processing for their business.
---

# Hermes Email Assistant

## Quick Commands

### Run a processing cycle
```bash
hermes cycle
```

### Check inbox status
```bash
hermes status
```

### Review pending drafts
```bash
hermes drafts --status pending_review
```

### First-time setup
```bash
hermes setup
```

### Run database migrations
```bash
hermes migrate
```

### Seed database from config
```bash
hermes seed
```

### Train voice samples
```bash
hermes train
```

## Environment Variables Required
- ANTHROPIC_API_KEY (or OPENAI_API_KEY or MINIMAX_API_KEY)
- SUPABASE_URL
- SUPABASE_SERVICE_ROLE_KEY
- Email provider key (MATON_API_KEY or GOOGLE_CLIENT_ID/SECRET)
