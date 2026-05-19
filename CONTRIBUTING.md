# Contributing

Thank you for your interest in contributing to **PubMed Search Builder**!

## How to Contribute

We welcome contributions in these areas:

### 1. **New Methodological Filters & Hedges**

If you've validated a new search filter (diagnostic accuracy, prognosis, qualitative studies, etc.), please add it to `references/validated-methodological-filters-and-hedges.md` with:
- Filter name and source (Cochrane, McMaster HIRU, PubMed Clinical Queries, etc.)
- PubMed syntax
- Version (sensitivity-maximising, specificity-maximising, balanced)
- Link to published validation study
- Example use case

### 2. **Documentation & Examples**

- New search strategy examples for different evidence types
- Improved tutorials or workflow documentation
- Translations of key concepts to other languages
- Clarifications on ambiguous sections

### 3. **Tool Improvements**

- Bug fixes in `pubmed_tool.py`, `mesh_tool.py`, or `hooks_tool.py`
- Performance improvements
- Better error messages
- New command-line options or features
- Test coverage

### 4. **Bug Reports**

Found a bug? Please open a GitHub issue with:
- Python version
- Operating system
- The exact command that failed
- Full error message (output from `--help` first, then your command)
- Steps to reproduce
- What you expected to happen

### 5. **Feature Requests**

Have an idea? Open a GitHub issue describing:
- The problem you're trying to solve
- Your proposed solution
- Why this would be useful to others
- Alternative approaches you considered

## Getting Started

1. **Fork the repository** on GitHub
2. **Clone your fork** locally:
   ```bash
   git clone https://github.com/YOUR-USERNAME/pubmed-search-builder.git
   cd pubmed-search-builder
   ```
3. **Create a feature branch**:
   ```bash
   git checkout -b feature/your-feature-name
   ```
4. **Make your changes**
5. **Test your changes** (see below)
6. **Commit with clear messages**:
   ```bash
   git commit -m "Add support for [feature]" -m "Description of the change"
   ```
7. **Push to your fork**:
   ```bash
   git push origin feature/your-feature-name
   ```
8. **Open a Pull Request** on GitHub

## Development Setup

1. Clone the repository (see above)
2. Install Python 3.7+ (3.10+ recommended)
3. Create a `.env` file with your NCBI credentials (see [INSTALL.md](INSTALL.md))
4. Test your setup:
   ```bash
   python scripts/pubmed_tool.py doctor
   ```

## Testing Your Changes

### For Tool Changes

If you modify `pubmed_tool.py`, `mesh_tool.py`, or `hooks_tool.py`:

1. **Syntax check**:
   ```bash
   python -m py_compile scripts/pubmed_tool.py
   python -m py_compile scripts/mesh_tool.py
   python -m py_compile scripts/hooks_tool.py
   ```

2. **Run the tool**:
   ```bash
   python scripts/pubmed_tool.py doctor
   python scripts/mesh_tool.py lookup --label "Asthma"
   python scripts/hooks_tool.py final-qa --strategy-file /tmp/test.txt
   ```

3. **Test with real queries**:
   ```bash
   # Count-test a simple query
   python scripts/pubmed_tool.py search "asthma[Mesh]" --retmax 0

   # Fetch a known PMID
   python scripts/pubmed_tool.py fetch --pmids 24102982
   ```

### For Documentation Changes

1. Check for typos and clarity
2. Verify any code examples work (test in isolation if possible)
3. Ensure links and file paths are correct

## Code Style

### Python

- Follow PEP 8 (readable, indented with 4 spaces)
- Use type hints where possible
- Add docstrings to functions
- Avoid hard-coded API keys or credentials
- Never print sensitive information

Example:

```python
def example_function(param: str) -> dict:
    """
    Short description.

    Args:
        param: Description of param.

    Returns:
        Dictionary with results.
    """
    result = {}
    # Your code here
    return result
```

### Markdown

- Use clear headings (`#`, `##`, `###`)
- Include code blocks with language tags:
  ```bash
  # Good
  ```
- Link to related docs
- Keep line length ~80 characters for readability

## Commit Message Guidelines

Write clear, descriptive commit messages:

```
Short description of the change (50 chars max)

Longer explanation if needed. Explain the *why*, not the *what*.
Wrap at ~72 characters.

Related to issue #123
```

## Pull Request Guidelines

1. **Keep it focused**: One feature or fix per PR
2. **Add description**: Explain what you changed and why
3. **Link issues**: Reference any related GitHub issues
4. **Test**: Confirm your changes work (especially for tools)
5. **Document**: Update relevant documentation if needed

Example PR description:

```
## Summary
Add support for [feature].

## Changes
- Modified `pubmed_tool.py` to [brief description]
- Added example to `references/examples.md`

## Testing
Tested with:
- `python scripts/pubmed_tool.py [command]`
- Query: "asthma[Mesh]" -> count = 12345 (as expected)

Closes #123
```

## License

By contributing, you agree that your contributions are licensed under the MIT License (see [LICENSE](LICENSE)).

## Questions?

Open a GitHub issue or discussion. We're here to help!

---

Thank you for making PubMed Search Builder better!
