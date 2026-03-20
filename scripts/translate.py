#!/usr/bin/env python3
"""
Auto-translate Hugo blog posts using DeepL API.

Convention:
  post.md       = English (default)
  post.zh.md    = Chinese

Behavior:
  - For each post.md without a post.zh.md -> translate EN to ZH
  - For each post.zh.md without a post.md -> translate ZH to EN
  - Skips files that already have a translation

Usage:
  export DEEPL_API_KEY=your_key
  python scripts/translate.py
  python scripts/translate.py --dry-run
"""

import os
import re
import sys
import argparse
from pathlib import Path

import deepl
import frontmatter


CONTENT_DIR = Path(__file__).parent.parent / "content"
POST_DIRS = ["posts"]

TRANSLATABLE_FIELDS = {"title", "description"}

# Fields to add to auto-translated files
AUTO_TRANSLATE_TAG = "auto_translated"


def protect_code_blocks(text: str) -> tuple[str, dict]:
    """Replace code blocks with placeholders to prevent DeepL from mangling them."""
    placeholders = {}
    counter = [0]

    def replace(match):
        key = f"CODEBLOCK{counter[0]}ENDCODE"
        placeholders[key] = match.group(0)
        counter[0] += 1
        return key

    # Fenced code blocks (``` or ~~~)
    protected = re.sub(r"```[\s\S]*?```|~~~[\s\S]*?~~~", replace, text)
    # Inline code
    protected = re.sub(r"`[^`\n]+`", replace, protected)

    return protected, placeholders


def restore_code_blocks(text: str, placeholders: dict) -> str:
    for key, value in placeholders.items():
        text = text.replace(key, value)
    return text


def translate_text(translator: deepl.Translator, text: str, source_lang: str, target_lang: str) -> str:
    if not text or not text.strip():
        return text

    protected, placeholders = protect_code_blocks(text)
    result = translator.translate_text(
        protected,
        source_lang=source_lang,
        target_lang=target_lang,
        preserve_formatting=True,
    )
    return restore_code_blocks(result.text, placeholders)


def translate_post(translator: deepl.Translator, source_path: Path, target_path: Path,
                   source_lang: str, target_lang: str, dry_run: bool = False):
    post = frontmatter.load(str(source_path))

    # Translate frontmatter fields
    translated_metadata = dict(post.metadata)
    for field in TRANSLATABLE_FIELDS:
        if field in translated_metadata and isinstance(translated_metadata[field], str):
            translated_metadata[field] = translate_text(
                translator, translated_metadata[field], source_lang, target_lang
            )

    # Mark as auto-translated
    translated_metadata[AUTO_TRANSLATE_TAG] = True

    # Translate body
    translated_body = translate_text(translator, post.content, source_lang, target_lang)

    if dry_run:
        print(f"  [dry-run] Would write: {target_path}")
        return

    translated_post = frontmatter.Post(translated_body, **translated_metadata)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with open(target_path, "w", encoding="utf-8") as f:
        f.write(frontmatter.dumps(translated_post))

    print(f"  Wrote: {target_path}")


def find_translation_pairs(content_dir: Path, post_dirs: list[str]):
    """
    Yields (source_path, target_path, source_lang, target_lang) for posts missing a translation.
    """
    for dir_name in post_dirs:
        post_dir = content_dir / dir_name
        if not post_dir.exists():
            continue

        for md_file in sorted(post_dir.glob("*.md")):
            name = md_file.name

            # Skip already-translated files as source
            if re.search(r"\.[a-z]{2}\.md$", name):
                # This is a translated file (e.g. post.zh.md)
                # Check if the English version exists
                base = re.sub(r"\.[a-z]{2}\.md$", ".md", name)
                en_path = post_dir / base
                if not en_path.exists():
                    lang_code = re.search(r"\.([a-z]{2})\.md$", name).group(1)
                    yield (md_file, en_path, lang_code.upper(), "EN-US")
            else:
                # This is an English file — check if ZH exists
                base = md_file.stem
                zh_path = post_dir / f"{base}.zh.md"
                if not zh_path.exists():
                    yield (md_file, zh_path, "EN", "ZH")


def main():
    parser = argparse.ArgumentParser(description="Auto-translate Hugo blog posts via DeepL")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be translated without writing files")
    args = parser.parse_args()

    api_key = os.environ.get("DEEPL_API_KEY")
    if not api_key:
        print("Error: DEEPL_API_KEY environment variable not set.", file=sys.stderr)
        sys.exit(1)

    translator = deepl.Translator(api_key)

    pairs = list(find_translation_pairs(CONTENT_DIR, POST_DIRS))

    if not pairs:
        print("Nothing to translate — all posts have translations.")
        return

    print(f"Found {len(pairs)} post(s) to translate:")
    for source, target, src_lang, tgt_lang in pairs:
        print(f"  {source.name} -> {target.name}  ({src_lang} -> {tgt_lang})")

    if args.dry_run:
        print("\nDry run — no files written.")
        return

    print()
    for source, target, src_lang, tgt_lang in pairs:
        print(f"Translating: {source.name}")
        try:
            translate_post(translator, source, target, src_lang, tgt_lang, dry_run=args.dry_run)
        except Exception as e:
            print(f"  ERROR: {e}", file=sys.stderr)

    usage = translator.get_usage()
    print(f"\nDeepL usage: {usage.character.count:,} / {usage.character.limit:,} characters")


if __name__ == "__main__":
    main()
