# Moby Dick

SalesGlider's prospect research and personalization engine.

Josh Osborn runs SalesGlider. The offer is a meeting guarantee, not a free POC. This project is the tool Cayden uses to pull unique founder and PE lists, then (less often) write a whale gift dossier.

It used to wake on "hey grok" in Slack. It is now a Cursor project with an MCP server Claude can call directly.

Never call it Flowers Engine.

## What it does

**Bulk enriched lists (the main use).** Cayden asks for something like 500 new unique Series A/B SaaS founders or 500 PE partners. Moby Dick pulls them from GetLeads, drops anyone already delivered, fills missing emails, adds emotional research plus a public office mailing address, and writes one CSV.

**Whale gift dossiers.** For one lower-middle-market PE partner with a real public footprint, it recommends a ~$100 personal gift backed by a citable source.

Lists never go into chat. Counts and about 10 sample names only.

## MCP tools

| Tool | What it does |
| --- | --- |
| `build_enriched_list` | Pull, de-dupe, enrich, write a CSV. Long jobs return `job_id`. |
| `whale_dossier` | One-person gift dossier. Cuts bait if the footprint is only LinkedIn. |
| `get_job_status` / `fetch_job_result` / `list_jobs` | Poll long pulls. Result is path + counts + samples. |
| `exclude_add` / `exclude_check` / `exclude_count` / `exclude_import` | Persist the never-again domain list. |
| `list_deliveries` | Paths to past CSVs. |
| `health` | Which connectors are configured. No secrets. |

## Pipeline

1. GetLeads pull (1.5x to 3x the ask). Series A/B default: US HQ, SaaS/software, CEO or Founder, Series A or B, funded since 2024-01-01, require email, one per company. PE default: US partners / principals / independent sponsors. Associates and assistants are out.
2. De-dupe against `data/exclude/*.json` **and same-day delivery files**. The morning file counts.
3. Missing emails: Josh's email-waterfall MCP (`client_tag=salesglider`) plus LeadMagic so the CSV itself gets filled. Waterfall MCP never returns row payloads.
4. Public-source enrichment: company about/contact pages. YouTube talks + transcripts and one Taddy search on whale dossiers. Apify only when the public web is thin.
5. Office mailing address only. Never a home address. Never invent. Blank if none.
6. DQ column for bad fits. Keepers only go in the delivery CSV.
7. New domains are added to the exclude list automatically.

## CSV columns

Series A/B:

`full_name,title,email,linkedin_url,company_name,company_domain,funding_round,funding_amount,funding_date,source_note,company_website,mailing_address,location,why_started,origin_hometown,personal_beliefs_causes,best_emotional_hook,quirky_personal_fact,confidence,dq,sources,research_note`

PE partners:

`first_name,last_name,full_name,email,title,company_name,company_domain,company_website,linkedin_url,location,mailing_address,hometown_or_from,why_got_into_pe,real_story,best_emotional_hook,beliefs_or_causes,firm_type,source_notes,confidence,sources,research_note`

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Put keys in `.env`. Never commit them.

`data/exclude/` already has domains from the #mobydick Slack deliveries we could find (500 Series A/B, 398 PE firms). That is not the full historic 1982-domain list. If you still have `exclude_domains_prior.json` or `pe_exclude_domains_prior.json`, import them so Cayden does not get repeats:

```bash
python -c "from mobydick.store import Store; s=Store(); print(s.exclude_import('exclude_domains_prior.json','series_ab')); print(s.exclude_import('pe_exclude_domains_prior.json','pe_partners'))"
```

Or call `exclude_import` from Claude. Same-day delivery CSVs are also excluded automatically.

## Run the MCP server

Local Cursor / Claude Desktop (stdio):

```bash
python -m mcp_server
```

Cursor MCP config:

```json
{
  "mcpServers": {
    "mobydick": {
      "command": "python",
      "args": ["-m", "mcp_server"],
      "cwd": "/absolute/path/to/mobydick",
      "env": {
        "MCP_TRANSPORT": "stdio"
      }
    }
  }
}
```

Railway / remote Claude connector:

```bash
MCP_TRANSPORT=streamable-http PORT=8000 python -m mcp_server
```

Health: `GET /health`. Connector path: `/mcp`.

## Local CLI

```bash
python -m mobydick.cli build --audience series_ab --count 100
python -m mobydick.cli dossier --name "Jane Partner" --firm "Example Capital"
python -m mobydick.cli exclude-count --list pe_partners
```

## Tests

```bash
pip install -r requirements.txt
pytest -q
```

Tests do not call paid vendors.

## Rules that carry over

- Public sources only. Research only. Never contact prospects.
- Never invent a mailing address or a personal fact.
- Identity signals, not resume items.
- One CSV. No list paste in Slack or chat.
- Soft CTAs. No em dashes. Meeting guarantee, never a free POC.
