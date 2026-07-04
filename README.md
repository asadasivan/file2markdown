# Token Saver

Token Saver converts local documents into Markdown and removes mechanical noise so the result can be used as lower-token LLM context.

It is designed for internal-document workflows where the default security posture should be local-only and conservative.

## What It Does

1. Converts a local file to Markdown using [Microsoft MarkItDown](https://github.com/microsoft/markitdown).
2. Disables MarkItDown plugins.
3. Uses MarkItDown's local-file conversion API.
4. Removes common mechanical noise:
   - page numbers
   - repeated headers and footers
   - standalone classification banners
   - empty Markdown links/images
   - broken hyphenated line wraps
   - excessive blank lines
5. Writes a `.md` file that can be used as LLM context.
6. Prints a rough context-size reduction estimate.

## Security Boundary

Token Saver is intentionally local-only.

It does not configure or use:

- Azure Document Intelligence
- Azure Content Understanding
- MarkItDown plugins
- LLM image-description clients
- remote URL conversion

The script calls:

```python
MarkItDown(enable_plugins=False).convert_local(file_path)
```

Do not use this tool on documents unless your local machine, Python environment, and installed dependencies are approved for that document classification.

## Install

Token Saver depends on [microsoft/markitdown](https://github.com/microsoft/markitdown) for local document-to-Markdown conversion.

Use a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

## Usage

Convert a file and create `<input-name>.token-saver.md`:

```bash
python3 token_saver.py input.pdf
```

Write to a specific Markdown file:

```bash
python3 token_saver.py input.docx -o context.md
```

Save raw MarkItDown output for review:

```bash
python3 token_saver.py input.pptx --save-raw-md raw.md -o context.md
```

Keep standalone classification labels:

```bash
python3 token_saver.py input.pdf --keep-classification
```

Remove an additional repeated header/footer line:

```bash
python3 token_saver.py input.pdf --drop-line-regex '^Document ID:.*$'
```

## Output

The output file must end in `.md` or `.markdown`.

Example:

```text
Wrote cleaned Markdown: /path/to/input.token-saver.md
Estimated context reduction: 12,400 -> 8,900 tokens (28% reduction)
```

The token count is an estimate based on character length. Actual token counts vary by model.

## When MarkItDown May Not Be Enough

MarkItDown is a good default for Office files, text-based PDFs, structured text, and many common document formats.

Review the generated Markdown before sending it to an LLM. Use a different extraction workflow or manually curate excerpts if:

- scanned PDFs produce missing or garbled text
- tables become unreadable
- diagrams contain important security architecture details
- screenshots contain dense small text
- critical sections are missing from the Markdown

For sensitive internal documents, prefer a better source file or manually selected excerpts before adding external OCR or cloud-based extraction services.

## GitHub Setup

Initialize and push to your personal GitHub repo:

```bash
git init
git add README.md requirements.txt .gitignore token_saver.py
git commit -m "Initial token saver utility"
git branch -M main
git remote add origin git@github.com:<your-user>/<your-repo>.git
git push -u origin main
```
