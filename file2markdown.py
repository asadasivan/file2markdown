#!/usr/bin/env python3
"""
Local-only Markdown conversion and mechanical noise cleaner for internal documents.

Preferred flow:
1. Convert the input file to Markdown with Microsoft MarkItDown.
2. Remove mechanical noise that wastes LLM context tokens.
3. Write an LLM-ready Markdown file.

This script is intentionally local-only:
- MarkItDown is called with plugins disabled.
- Azure Document Intelligence / Content Understanding are not configured.
- LLM clients are not configured.
- Remote URI conversion is blocked by requiring MarkItDown's local-file API.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from collections import Counter
from pathlib import Path


# Keep these patterns conservative. They remove standalone classification
# labels/banners, not sentences that merely contain these words.
CLASSIFICATION_PATTERNS = [
    r"^\s*(?:[A-Z][A-Z0-9&.,'()/-]*\s+){0,4}PUBLIC\s*$",
    r"^\s*(?:[A-Z][A-Z0-9&.,'()/-]*\s+){0,4}INTERNAL\s*$",
    r"^\s*(?:[A-Z][A-Z0-9&.,'()/-]*\s+){0,4}INTERNAL\s+USE\s+ONLY\s*$",
    r"^\s*(?:[A-Z][A-Z0-9&.,'()/-]*\s+){0,4}CONFIDENTIAL\s*$",
    r"^\s*(?:[A-Z][A-Z0-9&.,'()/-]*\s+){0,4}RESTRICTED\s*$",
    r"^\s*(?:[A-Z][A-Z0-9&.,'()/-]*\s+){0,4}HIGHLY\s+RESTRICTED\s*$",
    r"^\s*(?:[A-Z][A-Z0-9&.,'()/-]*\s+){0,4}SECRET\s*$",
    r"^\s*(?:[A-Z][A-Z0-9&.,'()/-]*\s+){0,4}TOP\s+SECRET\s*$",
    r"^\s*(?:[A-Z][A-Z0-9&.,'()/-]*\s+){0,4}PROPRIETARY\s*$",
    r"^\s*(?:[A-Z][A-Z0-9&.,'()/-]*\s+){0,4}PRIVATE\s*$",
    r"^\s*(?:[A-Z][A-Z0-9&.,'()/-]*\s+){0,4}SENSITIVE\s*$",
    r"^\s*(?:[A-Z][A-Z0-9&.,'()/-]*\s+){0,4}CONTROLLED\s*$",
    r"^\s*(?:[A-Z][A-Z0-9&.,'()/-]*\s+){0,4}UNCLASSIFIED\s*$",
    r"^\s*(?:[A-Z][A-Z0-9&.,'()/-]*\s+){0,4}FOR\s+OFFICIAL\s+USE\s+ONLY\s*$",
    r"^\s*(?:[A-Z][A-Z0-9&.,'()/-]*\s+){0,4}LIMITED\s+DISTRIBUTION\s*$",
    r"^\s*TLP\s*:\s*(?:CLEAR|WHITE|GREEN|AMBER|AMBER\+STRICT|RED)\s*$",
]

NOISE_LINE_PATTERNS = [
    r"^\s*Page\s+\d+\s+of\s+\d+\s*$",
    r"^\s*Page\s+\d+\s*$",
    r"^\s*p\.\s*\d+\s*$",
    r"^\s*\d+\s*/\s*\d+\s*$",
    r"^\s*-\s*\d+\s*-\s*$",
    r"^\s*\d+\s*$",
    r"^\s*Copyright\b.*$",
    r"^\s*All\s+rights\s+reserved\.?\s*$",
]


def convert_with_markitdown(input_path: Path) -> str:
    if importlib.util.find_spec("markitdown") is None:
        raise RuntimeError(
            "Python package not found: markitdown. Install locally with: "
            "python3 -m pip install 'markitdown[pdf,docx,pptx,xlsx]'"
        )

    from markitdown import MarkItDown  # type: ignore

    converter = MarkItDown(enable_plugins=False)
    if not hasattr(converter, "convert_local"):
        raise RuntimeError(
            "Installed MarkItDown does not expose convert_local(). "
            "Upgrade MarkItDown before using file2markdown.py."
        )
    result = converter.convert_local(str(input_path))

    text_content = getattr(result, "text_content", None)
    if text_content is None:
        raise RuntimeError("MarkItDown did not return text_content.")
    return str(text_content)


def normalize_ocr_text(text: str) -> str:
    # Normalize common Unicode whitespace and control characters from OCR/PDF tools.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[\u200b-\u200d\ufeff]", "", text)
    return text


def remove_pattern_lines(text: str, extra_patterns: list[str]) -> str:
    patterns = [re.compile(p, re.IGNORECASE) for p in CLASSIFICATION_PATTERNS]
    patterns += [re.compile(p, re.IGNORECASE) for p in NOISE_LINE_PATTERNS]
    patterns += [re.compile(p, re.IGNORECASE) for p in extra_patterns]

    kept_lines: list[str] = []
    for line in text.splitlines():
        compact = re.sub(r"\s+", " ", line).strip()
        if not compact:
            kept_lines.append("")
            continue
        if any(pattern.match(compact) for pattern in patterns):
            continue
        kept_lines.append(line.rstrip())
    return "\n".join(kept_lines)


def remove_repeated_lines(text: str, min_count: int) -> str:
    if min_count <= 1:
        return text

    lines = text.splitlines()
    normalized = [re.sub(r"\s+", " ", line).strip() for line in lines]
    counts = Counter(line for line in normalized if len(line) >= 6)

    kept_lines: list[str] = []
    for original, key in zip(lines, normalized):
        if key and counts[key] >= min_count:
            continue
        kept_lines.append(original)
    return "\n".join(kept_lines)


def remove_markdown_noise(text: str) -> str:
    # Drop empty Markdown links/images that sometimes appear after conversion.
    text = re.sub(r"(?m)^\s*!?\[\s*\]\([^)]*\)\s*$", "", text)

    # Collapse tables made only of separators or empty cells.
    text = re.sub(r"(?m)^\s*\|?[\s|:-]{3,}\|?\s*$", "", text)
    return text


def fix_line_breaks(text: str) -> str:
    # Join hyphenated words broken across lines: "auth-\norization" -> "authorization".
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)

    # Join conservative mid-sentence line wraps while preserving headings/lists.
    text = re.sub(r"([a-z0-9,;:])\n([a-z0-9])", r"\1 \2", text)
    return text


def normalize_spacing(text: str) -> str:
    lines = [re.sub(r"[ \t]+$", "", line) for line in text.splitlines()]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def estimated_tokens(text: str) -> int:
    # Rough LLM-context estimate. Actual tokenization depends on the model.
    return max(1, round(len(text) / 4)) if text else 0


def clean_text(
    text: str,
    repeated_line_min_count: int,
    extra_patterns: list[str],
    keep_classification: bool,
) -> str:
    text = normalize_ocr_text(text)

    if keep_classification:
        global CLASSIFICATION_PATTERNS
        original_patterns = CLASSIFICATION_PATTERNS
        CLASSIFICATION_PATTERNS = []
        try:
            text = remove_pattern_lines(text, extra_patterns)
        finally:
            CLASSIFICATION_PATTERNS = original_patterns
    else:
        text = remove_pattern_lines(text, extra_patterns)

    text = remove_repeated_lines(text, repeated_line_min_count)
    text = remove_markdown_noise(text)
    text = fix_line_breaks(text)
    return normalize_spacing(text)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convert a local file to Markdown, then remove mechanical noise "
            "to reduce LLM context tokens."
        )
    )
    parser.add_argument("input", type=Path, help="Input file to convert and clean")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output Markdown file. Defaults to <input-stem>.file2markdown.md",
    )
    parser.add_argument(
        "--save-raw-md",
        type=Path,
        help="Optional path to save the raw MarkItDown Markdown before cleanup.",
    )
    parser.add_argument(
        "--repeated-line-min-count",
        type=int,
        default=3,
        help="Remove exact repeated lines appearing at least this many times. Default: 3",
    )
    parser.add_argument(
        "--keep-classification",
        action="store_true",
        help="Do not remove standalone classification labels.",
    )
    parser.add_argument(
        "--drop-line-regex",
        action="append",
        default=[],
        help=(
            "Additional full-line regex to remove. Can be repeated. "
            "Example: --drop-line-regex '^Document ID:.*$'"
        ),
    )
    return parser.parse_args()


def resolve_markdown_output(input_path: Path, output_path: Path | None) -> Path:
    if output_path is None:
        resolved = input_path.with_name(f"{input_path.stem}.file2markdown.md")
    else:
        resolved = output_path.expanduser().resolve()

    if resolved.suffix.lower() not in {".md", ".markdown"}:
        raise ValueError("Output must be a Markdown file ending in .md or .markdown.")
    return resolved


def main() -> int:
    args = parse_args()
    input_path = args.input.expanduser().resolve()

    if not input_path.exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        return 2

    try:
        output_path = resolve_markdown_output(input_path, args.output)
        raw_text = convert_with_markitdown(input_path)
        if args.save_raw_md:
            raw_md_path = args.save_raw_md.expanduser().resolve()
            raw_md_path.write_text(raw_text)

        cleaned = clean_text(
            raw_text,
            repeated_line_min_count=args.repeated_line_min_count,
            extra_patterns=args.drop_line_regex,
            keep_classification=args.keep_classification,
        )
        output_path.write_text(cleaned)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    raw_tokens = estimated_tokens(raw_text)
    cleaned_tokens = estimated_tokens(cleaned)
    reduction = 0
    if raw_tokens:
        reduction = round((raw_tokens - cleaned_tokens) / raw_tokens * 100)

    print(f"Wrote cleaned Markdown: {output_path}")
    print(
        f"Estimated context reduction: {raw_tokens:,} -> "
        f"{cleaned_tokens:,} tokens ({reduction}% reduction)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
