# GitHub Setup Checklist

Your PubMed Search Builder is ready to publish on GitHub! Follow this checklist to push it to your repository.

---

## Pre-Publication Security Check [OK]

Before pushing to GitHub, verify no secrets are being exposed:

### 1. Verify `.env` is NOT committed

```bash
# Check git status
git status

# The .env file should appear as "ignored" or not listed
# Verify .gitignore excludes it
grep "\.env" .gitignore
```

**Expected output**: `.env` should be listed in `.gitignore`

### 2. Double-check for secrets in code

```bash
# Search for any hardcoded API keys
grep -r "YOUR_REAL_NCBI_API_KEY" . --exclude-dir=.git --exclude=.env
grep -r "YOUR_PRIVATE_EMAIL_ADDRESS" . --exclude-dir=.git --exclude=.env

# Replace placeholders with any real values you need to check; these should return no results
```

### 3. Verify example file is in place

```bash
# This should exist and have placeholder values
cat .env.example | grep NCBI_API_KEY
# Should output: NCBI_API_KEY=your_api_key_here
```

---

## GitHub Repository Setup

### Step 1: Create Repository on GitHub

1. Go to https://github.com/new
2. **Repository name**: `pubmed-search-builder`
3. **Description**: High-sensitivity Boolean search strategy development for PubMed
4. **Visibility**: Public (or Private if you prefer)
5. **Initialize**: Do NOT initialize with README, .gitignore, or license (you have these)
6. Click **Create repository**

### Step 2: Push Your Code

Once your repo is created, GitHub will show you instructions. Follow this pattern:

```bash
# Navigate to your local repo
cd pubmed-search-builder

# If not already a git repo, initialize it
git init

# Add all files EXCEPT secrets
git add .

# Verify nothing secret is staged
git status
# Should NOT show: .env, *.key, *.pem files

# Initial commit
git commit -m "Initial commit: PubMed search strategy builder

- Bundled Python tools for MeSH/PubMed E-utilities
- High-sensitivity Boolean search strategy development
- Comprehensive documentation and examples"

# Add GitHub remote (replace YOUR-USERNAME)
git remote add origin https://github.com/YOUR-USERNAME/pubmed-search-builder.git

# Push to main branch
git branch -M main
git push -u origin main
```

### Step 3: Add Topics & Description

On GitHub:

1. Go to your repo's **Settings** -> **About**
2. **Short description**: "High-sensitivity Boolean search strategy development for PubMed"
3. **Topics**: Add these tags (click "Add topics"):
   - `pubmed`
   - `search-strategy`
   - `systematic-review`
   - `evidence-synthesis`
   - `mesh`
   - `information-retrieval`
   - `literature-search`

### Step 4: Enable GitHub Features (Optional)

Recommended settings in **Settings**:

- **General**: Keep "Discussions" enabled
- **Features**:
  - [OK] Issues (enabled by default)
  - [OK] Discussions (for Q&A)
  - [NO] Projects (optional)
  - [NO] Wiki (optional)

---

## Repository Structure

Your GitHub repo will have this structure:

```
pubmed-search-builder/
|-- .github/
|   |-- ISSUE_TEMPLATE/
|   |   |-- bug_report.md
|   |   `-- feature_request.md
|   `-- pull_request_template.md
|-- references/
|   |-- examples.md
|   |-- mesh-and-pubmed-tools.md
|   |-- prisma-s-reporting.md
|   |-- seed-pmid-validation.md
|   |-- tiab-expansion.md
|   |-- validated-methodological-filters-and-hedges.md
|   |-- wildcard-and-truncation.md
|   `-- workflow.md
|-- scripts/
|   |-- hooks_tool.py
|   |-- mesh_tool.py
|   `-- pubmed_tool.py
|-- agents/
|   `-- openai.yaml
|-- .env.example          # <- User copies this to .env locally
|-- .gitignore           # <- MUST exclude .env
|-- .gitattributes
|-- CONTRIBUTING.md
|-- GITHUB_SETUP.md      # <- This file
|-- INSTALL.md
|-- LICENSE
|-- README.md
`-- SKILL.md
```

---

## After Publication

### 1. Add to GitHub README Badge (Optional)

Add this to the top of `README.md` to show repo status:

```markdown
[![GitHub release](https://img.shields.io/github/v/release/YOUR-USERNAME/pubmed-search-builder)](https://github.com/YOUR-USERNAME/pubmed-search-builder/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.7+](https://img.shields.io/badge/python-3.7+-blue.svg)](https://www.python.org/downloads/)
```

### 2. Create a Release

When you're ready to tag a version:

```bash
git tag -a v1.0.0 -m "Initial release"
git push origin v1.0.0
```

On GitHub, it will create a Release automatically.

### 3. Link from Other Sources

Update any links to point to your GitHub repo:

- Add to your personal portfolio
- Link from academic profiles
- Update any documentation that references this tool

### 4. Consider Pinning Repo

On your GitHub profile, you can "Pin" this repo to show it prominently.

---

## Troubleshooting

### Git Push Rejected

```bash
# If you get "fatal: remote origin already exists"
git remote -v  # See what remotes are configured
git remote remove origin
git remote add origin https://github.com/YOUR-USERNAME/pubmed-search-builder.git
git push -u origin main
```

### API Key Accidentally Committed

WARNING: **If you accidentally committed your `.env` with API key:**

```bash
# DO NOT JUST DELETE IT
# Instead, remove it from git history:
git filter-branch --tree-filter 'rm -f .env' HEAD

# Then force push (dangerous - coordinate with team first)
git push origin main --force

# Rotate your API key immediately on NCBI website
```

### README Not Showing Properly

- Ensure `README.md` is in the repository root (not in a subdirectory)
- Check for YAML frontmatter or syntax errors
- GitHub renders Markdown; verify locally with `python -m markdown README.md`

---

## Next Steps

### 1. Verify Everything Works

Run your tools one final time on GitHub (using your local clone that's now synced):

```bash
python scripts/pubmed_tool.py doctor
python scripts/mesh_tool.py lookup --label "Asthma" --match exact
```

### 2. Add to Your Profile

- Update GitHub profile bio to mention this project
- Add link in your GitHub repository list
- Share on social media if you'd like visibility

### 3. Monitor for Issues

- Watch your GitHub notifications for issues and pull requests
- Respond to questions from users
- Track any bug reports

### 4. Plan Updates

Consider scheduling periodic updates for:
- New methodological filters (as they're published)
- Tool improvements based on feedback
- Documentation updates

---

## GitHub Features You Can Use

### Discussions

Enable Discussions for Q&A-style conversations about the toolkit:

1. Settings -> Features -> enable "Discussions"
2. Users can ask "How do I..." questions without opening issues

### Wiki

Optional: Create a GitHub Wiki for extended tutorials:

1. Go to **Wiki** tab
2. Create pages for:
   - Quick start guide
   - Troubleshooting
   - User testimonials

### GitHub Pages

Optional: Host documentation at `https://YOUR-USERNAME.github.io/pubmed-search-builder/`

See https://docs.github.com/en/pages for setup.

---

## File Permissions

Make sure scripts are executable:

```bash
chmod +x scripts/pubmed_tool.py
chmod +x scripts/mesh_tool.py
chmod +x scripts/hooks_tool.py
```

On Windows, this is automatic; on Unix systems, it ensures shebang lines work.

---

## Congratulations!

Your PubMed Search Builder is now published on GitHub. Share the link:

```
https://github.com/YOUR-USERNAME/pubmed-search-builder
```

---

## Questions?

Check GitHub's official guides:
- [Creating a repository](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-new-repository)
- [Managing remotes](https://docs.github.com/en/get-started/getting-started-with-git/managing-remote-repositories)
- [Pushing changes](https://docs.github.com/en/get-started/using-git/pushing-commits-to-a-remote-repository)

Good luck!
