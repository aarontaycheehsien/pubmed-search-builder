# Installation & Setup Guide

## Prerequisites

- Python 3.7 or later (3.10+ recommended)
- Git
- Internet connection (for NCBI and NLM APIs)
- An NCBI email address (recommended)
- (Optional) NCBI API key for higher rate limits

## Step-by-Step Installation

### 1. Clone the Repository

```bash
git clone https://github.com/YOUR-USERNAME/pubmed-search-builder.git
cd pubmed-search-builder
```

### 2. Verify Python Installation

```bash
python --version
# Should output Python 3.7 or later, e.g. Python 3.10.2
```

### 3. Create Environment File

Copy the example configuration:

```bash
cp .env.example .env
```

### 4. Configure NCBI Access

Edit `.env` with your text editor:

```bash
# On Windows (PowerShell)
notepad .env

# On Mac/Linux
nano .env
```

**Recommended fields:**

```
NCBI_EMAIL=your.email@example.com
```

**Optional fields:**

```
NCBI_TOOL=codex-search-strategy-check
NCBI_API_KEY=your_api_key_if_you_have_one
```

### 5. Test Installation

```bash
python scripts/pubmed_tool.py doctor
```

Expected output:

```json
{
  "ok": true,
  "checks": {
    "email_configured": true,
    "api_key_present": false,
    "rate_limit_per_second": 3,
    "test_query": "asthma[tiab]",
    "test_count": 12345
  }
}
```

If you see errors or warnings:
- **`email_configured: false`**: Add your email to `.env` if you want NCBI contact metadata included
- **`HTTP 400`**: Your query may be malformed (the `doctor` command shouldn't be - please report)
- **Network error**: Check your internet connection and NCBI API availability

---

## Getting an NCBI Email

If you don't have one:

1. Visit https://www.ncbi.nlm.nih.gov/account/
2. Click "Sign in" or "Register"
3. Create an account using any valid email address
4. Copy that email to `.env` as `NCBI_EMAIL`

---

## Getting an NCBI API Key (Optional)

Higher rate limits (10 requests/second vs 3 requests/second) require an API key.

1. Log in to https://www.ncbi.nlm.nih.gov/account/
2. Go to **Account Settings** (click your name in top right)
3. Scroll to **API Key Management**
4. Click **Create an API Key**
5. Copy the key to `.env` as `NCBI_API_KEY`

**Important**: Never share your API key. It grants programmatic access to your NCBI account.

---

## Common Issues

### "Command not found: python"

On some systems, you may need to use `python3`:

```bash
python3 scripts/pubmed_tool.py doctor
```

Or create an alias:

```bash
alias python=python3
```

### `email_configured: false`

Ensure your `.env` file exists and has a properly formatted email:

```bash
grep NCBI_EMAIL .env
# Should output: NCBI_EMAIL=your.email@example.com
```

### "HTTP 429 Too Many Requests"

You've exceeded the rate limit (3 req/sec without API key, 10 req/sec with key). Either:
- Wait a few seconds and retry
- Obtain an NCBI API key
- Batch multiple queries to reduce request frequency

### "MeSH lookup returns no results"

This is usually a network issue or a typo in the concept. Try:

```bash
# Test connectivity
python scripts/mesh_tool.py lookup --label "Diabetes" --match exact

# If this fails, check your internet connection and NLM availability
```

---

## Updating

To update to the latest version:

```bash
git pull origin main
```

Your `.env` file will not be affected (it's in `.gitignore`).

---

## Uninstalling

Simply delete the repository directory:

```bash
cd ..
rm -rf pubmed-search-builder
```

---

## Next Steps

1. Read [README.md](README.md) for an overview
2. Review [SKILL.md](SKILL.md) for complete documentation
3. Try the [Quick Start examples](README.md#quick-start)
4. Work through [references/workflow.md](references/workflow.md) for a real project

---

## Getting Help

- **Tool help**: `python scripts/pubmed_tool.py --help`
- **MeSH tool help**: `python scripts/mesh_tool.py --help`
- **QA tool help**: `python scripts/hooks_tool.py --help`
- **Documentation**: See [references/](references/) for detailed guides
- **Issues**: Open a GitHub issue if you encounter problems

---

## Environment Variable Reference

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `NCBI_EMAIL` | Recommended | (none) | Email for NCBI E-utilities compliance |
| `NCBI_TOOL` | No | `codex-search-strategy-check` | Tool name in NCBI API requests |
| `NCBI_API_KEY` | No | (none) | API key for higher rate limits (10 req/sec) |

---

## System-Specific Notes

### Windows

Use backslash paths and `python` or `python3`:

```bash
python scripts\pubmed_tool.py doctor
# or
python -m scripts.pubmed_tool doctor
```

### Mac/Linux

Use forward slashes and `python` or `python3`:

```bash
python scripts/pubmed_tool.py doctor
# or
python3 scripts/pubmed_tool.py doctor
```

### WSL (Windows Subsystem for Linux)

Follow Linux instructions above. Your `.env` should be in the WSL filesystem.
