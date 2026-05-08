#!/usr/bin/env python3
"""
build_full_leilan_claude_dataset_v11.py

Rebuilds a structured Leilan post-GPT-3 / Claude-family dataset from the
Markdown files in post-gpt3_transmissions_by_model/.

Default behaviour:
  - scans post-gpt3_transmissions_by_model/
  - skips gpt-4-base
  - parses each .md file into ordered Q/A pairs
  - groups model responses by transmission_id
  - writes:
      full_leilan_claude_dataset_rebuilt.json
      full_leilan_claude_dataset_build_report.json
      qa_split_review.md

No external Python packages are required.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


DEFAULT_SOURCE_ROOT = "post-gpt3_transmissions_by_model"
DEFAULT_OUTPUT = "full_leilan_claude_dataset_rebuilt.json"
DEFAULT_REPORT = "full_leilan_claude_dataset_build_report.json"
DEFAULT_REVIEW_MD = "qa_split_review.md"

# Folder-name -> stable model metadata.  The folder name is treated as more
# reliable than the pretty model string in a Markdown metadata header.
MODEL_MAP: Dict[str, Dict[str, str]] = {
    "opus3": {
        "model": "claude-opus-3",
        "model_display": "Claude Opus 3",
        "model_family": "claude",
    },
    "opus4": {
        "model": "claude-opus-4",
        "model_display": "Claude Opus 4",
        "model_family": "claude",
    },
    "opus4_1": {
        "model": "claude-opus-4.1",
        "model_display": "Claude Opus 4.1",
        "model_family": "claude",
    },
    "opus4_5": {
        "model": "claude-opus-4.5",
        "model_display": "Claude Opus 4.5",
        "model_family": "claude",
    },
    "sonnet3_5": {
        "model": "claude-sonnet-3.5",
        "model_display": "Claude Sonnet 3.5",
        "model_family": "claude",
    },
    "sonnet4": {
        "model": "claude-sonnet-4",
        "model_display": "Claude Sonnet 4",
        "model_family": "claude",
    },
    "sonnet4_5": {
        "model": "claude-sonnet-4.5",
        "model_display": "Claude Sonnet 4.5",
        "model_family": "claude",
    },
    "haiku3_5": {
        "model": "claude-haiku-3.5",
        "model_display": "Claude Haiku 3.5",
        "model_family": "claude",
    },
    # Excluded by default, but supported if --include-gpt4-base is used.
    "gpt-4-base": {
        "model": "gpt-4-base",
        "model_display": "GPT-4 Base",
        "model_family": "openai",
    },
}

SEPARATOR_RE = re.compile(
    r"(?is)(?:^|\s)(?P<sep>---|\*\s*\*\s*\*|\*{3}|<hr\s*/?>)\s*\*\*"
)

# A first bold question can occur right at the beginning of the Markdown body.
START_BOLD_RE = re.compile(r"(?is)^\s*\*\*")

# Filename pattern is intentionally permissive.  After YYYY-MM-DD-, the next
# dash-delimited chunk is treated as the transmission ID.  This handles 238a,
# E003a, AB001, etc.
FILENAME_RE = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})-(?P<id>[^-]+)-(?P<slug>.+)\.md$", re.I)


@dataclass
class ParsedMarkdown:
    metadata: Dict[str, str]
    body: str
    raw_frontmatter: str
    warnings: List[str] = field(default_factory=list)


@dataclass
class ParsedFile:
    source_file: Path
    rel_source_file: str
    source_directory: str
    metadata: Dict[str, str]
    raw_frontmatter: str
    body: str
    filename_date: Optional[str]
    filename_id: Optional[str]
    filename_slug: Optional[str]
    transmission_id: str
    title: str
    date: Optional[str]
    model_info: Dict[str, str]
    qa_pairs: List[Dict[str, Any]]
    parse_warnings: List[str]
    content_sha256: str


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalise_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def canonical_model_label(text: str) -> str:
    """Normalise model labels for comparison, e.g. "Opus 4.5" -> "opus45"."""
    text = (text or "").lower().replace("claude", "")
    return re.sub(r"[^a-z0-9]+", "", text)


def expected_label_key_from_model_id(model_id: str) -> str:
    """Normalise stable model IDs for comparison, e.g. claude-opus-4.5 -> opus45."""
    return canonical_model_label((model_id or "").replace("claude-", ""))


def slug_to_title(slug: str) -> str:
    # Keep this deliberately simple; it is only a fallback when the file header
    # does not provide a title.
    words = slug.replace("_", "-").split("-")
    small = {"a", "an", "and", "as", "at", "but", "by", "for", "from", "in", "of", "on", "or", "the", "to", "vs", "with"}
    titled: List[str] = []
    for i, w in enumerate(words):
        if not w:
            continue
        if i > 0 and w.lower() in small:
            titled.append(w.lower())
        else:
            titled.append(w[:1].upper() + w[1:])
    return " ".join(titled)


def parse_filename(path: Path) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    m = FILENAME_RE.match(path.name)
    if not m:
        return None, None, None
    return m.group("date"), m.group("id"), m.group("slug")


def unescape_metadata_value(value: str) -> str:
    """Unescape the small amount of JSON-ish escaping seen in compact headers."""
    return value.replace(r'\"', '"').replace(r"\'", "'").replace(r"\\", "\\")


def extract_quoted_field(text: str, key: str) -> Optional[str]:
    """Extract key: "..." while respecting backslash-escaped quotes.

    The Markdown files use a compact pseudo-YAML header rather than strict YAML.
    A simple regex like title: "(.*?)" breaks on titles containing escaped
    quoted phrases, so this scanner walks character by character.
    """
    m = re.search(rf"(?is)(?:^|\s){re.escape(key)}\s*:\s*\"", text)
    if not m:
        return None
    i = m.end()
    chars: List[str] = []
    escaped = False
    while i < len(text):
        ch = text[i]
        if escaped:
            chars.append("\\" + ch)
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == '"':
            return unescape_metadata_value("".join(chars).strip())
        else:
            chars.append(ch)
        i += 1
    return None


def parse_compact_metadata(frontmatter: str) -> Dict[str, str]:
    """Parse the compact pseudo-YAML used by these Markdown files.

    Handles both quoted fields like:
        query: "Leilan, ..."

    and older compact block-ish fields like:
        query: | Leilan, please interpret this text ...
    """
    metadata: Dict[str, str] = {}
    fm = frontmatter.strip()

    for key in ("id", "model", "title", "date", "query"):
        value = extract_quoted_field(fm, key)
        if value is not None:
            metadata[key] = value

    if "query" not in metadata:
        pipe_match = re.search(r"(?is)\bquery\s*:\s*\|\s*(.*)\s*$", fm)
        if pipe_match:
            metadata["query"] = pipe_match.group(1).strip()

    return metadata

def split_frontmatter(text: str) -> ParsedMarkdown:
    warnings: List[str] = []
    if not text.lstrip().startswith("---"):
        return ParsedMarkdown(metadata={}, body=text, raw_frontmatter="", warnings=["missing_frontmatter_delimiters"])

    # Respect leading whitespace but preserve offsets approximately in body.
    leading_len = len(text) - len(text.lstrip())
    start = text.find("---", leading_len)
    end = text.find("---", start + 3)
    if end == -1:
        return ParsedMarkdown(metadata={}, body=text, raw_frontmatter="", warnings=["unterminated_frontmatter"])

    raw_frontmatter = text[start + 3 : end]
    body = text[end + 3 :].lstrip()
    metadata = parse_compact_metadata(raw_frontmatter)

    for required in ("id", "model", "title", "date", "query"):
        if required not in metadata:
            warnings.append(f"missing_metadata_{required}")

    return ParsedMarkdown(metadata=metadata, body=body, raw_frontmatter=raw_frontmatter, warnings=warnings)


def find_closing_bold(text: str, open_pos: int) -> Optional[int]:
    """Return the position of the closing ** for a bold span.

    open_pos should point at the opening **.
    """
    if not text.startswith("**", open_pos):
        return None
    return text.find("**", open_pos + 2)


def consume_bold_question(body: str, q_start: int, merge_consecutive: bool) -> Tuple[Optional[int], str]:
    """Consume one or more consecutive bold spans used as a user question.

    Some files have an initial prompt split across several bold paragraphs,
    especially when the compact metadata query is missing. Example pattern:

        **Leilan, X recently tweeted this:**
        **[quoted tweet or context]**
        **How would you respond?**

    This merges those opening bold blocks into a single question while trying
    not to swallow the beginning of an answer.
    """
    if not body.startswith("**", q_start):
        return None, ""

    pos = q_start
    parts: List[str] = []
    while True:
        if pos != q_start:
            gap_start = pos
            while pos < len(body) and body[pos].isspace():
                pos += 1
            gap = body[gap_start:pos]
            if not body.startswith("**", pos):
                break
            if not merge_consecutive:
                break
            collected = normalise_space("\n\n".join(parts))
            if "?" in collected and not collected.rstrip().endswith(":"):
                break
            if len(gap) > 6:
                break

        close = find_closing_bold(body, pos)
        if close is None:
            return None, ""
        text = body[pos + 2 : close].strip()
        if text:
            parts.append(text)
        pos = close + 2

        if not merge_consecutive:
            break

        look = pos
        while look < len(body) and body[look].isspace():
            look += 1
        if not body.startswith("**", look):
            break

    if not parts:
        return None, ""
    return pos, "\n\n".join(parts).strip()


def question_candidate_spans(body: str, metadata_query: str = "") -> List[Tuple[int, int, int, str, str]]:
    """Find bolded question starts.

    Returns tuples:
        (separator_start, question_start, question_end_after_bold, question_text, method)

    The separator_start is where the previous-answer cutoff should happen.  For
    the first question at body start, separator_start is 0.
    """
    spans: List[Tuple[int, int, int, str, str]] = []

    m_start = START_BOLD_RE.match(body)
    if m_start:
        q_start = body.find("**", 0)
        q_end, q_text = consume_bold_question(body, q_start, merge_consecutive=not bool(metadata_query))
        if q_end is not None:
            spans.append((0, q_start, q_end, q_text, "initial_bold_question"))

    for m in SEPARATOR_RE.finditer(body):
        q_start = m.end() - 2
        q_end, q_text = consume_bold_question(body, q_start, merge_consecutive=True)
        if q_end is None:
            continue
        sep_start = m.start("sep")
        if any(existing[1] == q_start for existing in spans):
            continue
        spans.append((sep_start, q_start, q_end, q_text, "separator_bold_question"))

    spans.sort(key=lambda x: x[1])
    return spans

def strip_repeated_metadata_query(body: str, query: str) -> Tuple[str, bool]:
    """If body begins by repeating the metadata query in bold/plain form, remove it.

    This is a fallback used when the bold-question parser cannot confidently
    split the file.  It is intentionally conservative.
    """
    if not query:
        return body.strip(), False

    stripped = body.lstrip()
    q_norm = normalise_space(query)

    # Bold repetition.
    if stripped.startswith("**"):
        q_close = find_closing_bold(stripped, 0)
        if q_close is not None:
            bold_text = stripped[2:q_close].strip()
            if normalise_space(bold_text) == q_norm:
                return stripped[q_close + 2 :].lstrip(), True

    # Plain repetition: allow prefix match of the normalised text, but only if
    # the query is not tiny.
    if len(q_norm) > 40 and normalise_space(stripped).startswith(q_norm):
        # Character-accurate removal is fiddly after normalisation; do a rough
        # removal by searching the first 100 chars of the original query.
        needle = query.strip()[:100]
        idx = stripped.find(needle)
        if idx == 0:
            return stripped[len(query) :].lstrip(), True

    return body.strip(), False


def clean_bold_fragment(text: str) -> str:
    """Clean a bold/span fragment, including artefacts from triple-star Markdown."""
    return text.strip().strip("*").strip()


def consume_repeated_metadata_prompt(body: str, metadata_query: str) -> Tuple[Optional[int], List[str]]:
    """Return the character offset after a repeated opening prompt, if found.

    Many files begin by repeating the metadata query in bold. Some long prompts
    include quoted source material split over several bold/triple-bold spans.
    This function consumes those opening bold spans only while their text still
    appears to be part of the metadata query, stopping before the model answer.
    """
    if not metadata_query:
        return None, []

    pos = 0
    while pos < len(body) and body[pos].isspace():
        pos += 1

    if not body.startswith("**", pos):
        return None, []

    meta_norm = normalise_space(metadata_query)
    parts: List[str] = []
    last_good_end: Optional[int] = None

    while pos < len(body):
        while pos < len(body) and body[pos].isspace():
            pos += 1

        if not body.startswith("**", pos):
            break

        close = find_closing_bold(body, pos)
        if close is None:
            break

        frag = clean_bold_fragment(body[pos + 2 : close])
        if not frag:
            break

        trial_parts = parts + [frag]
        trial_norm = normalise_space("\n\n".join(trial_parts))

        is_part_of_query = (
            trial_norm == meta_norm
            or trial_norm in meta_norm
            or meta_norm.startswith(trial_norm)
            or (len(trial_norm) > 40 and trial_norm[:40] in meta_norm)
        )

        if not is_part_of_query:
            break

        parts = trial_parts
        last_good_end = close + 2
        pos = close + 2

        if trial_norm == meta_norm or len(trial_norm) >= 0.92 * len(meta_norm):
            break

    return last_good_end, parts


def separator_question_spans(body: str) -> List[Tuple[int, int, int, str, str]]:
    """Find follow-up questions introduced by a Markdown separator."""
    spans: List[Tuple[int, int, int, str, str]] = []
    for m in SEPARATOR_RE.finditer(body):
        q_start = m.end() - 2
        q_end, q_text = consume_bold_question(body, q_start, merge_consecutive=True)
        if q_end is None:
            continue
        spans.append((m.start("sep"), q_start, q_end, q_text, "separator_bold_question"))
    spans.sort(key=lambda x: x[1])
    return spans


def markdownish_to_plain(text: str) -> str:
    """Very light Markdown-ish normalisation for prompt matching."""
    text = text or ""
    text = text.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    text = re.sub(r"https?://\S+", " URL ", text)
    text = re.sub(r"[*_`>#\[\]()+\\|{}]", " ", text)
    text = re.sub(r"[-—–]+", " ", text)
    text = re.sub(r"[^A-Za-z0-9]+", " ", text)
    return normalise_space(text).lower()


def significant_metadata_lines(metadata_query: str) -> List[str]:
    """Return non-trivial prompt lines for fuzzy opening-prompt matching."""
    lines = []
    for line in (metadata_query or "").splitlines():
        clean = line.strip().strip("*").strip()
        if len(markdownish_to_plain(clean)) >= 8:
            lines.append(clean)
    return lines


def find_repeated_metadata_prompt_end(body: str, metadata_query: str) -> Optional[int]:
    """Find the end offset of a repeated metadata prompt at the start of body.

    This is deliberately more robust than Markdown parsing. It is designed for
    cases where a long quoted prompt is repeated in the body with messy emphasis,
    triple-stars, or horizontal-rule-looking lines. It looks for the last
    significant line of the metadata prompt inside the opening region of the
    body and treats that as the end of the repeated prompt.
    """
    if not metadata_query:
        return None

    body_head = body[: min(len(body), max(12000, len(metadata_query) * 3))]
    lines = significant_metadata_lines(metadata_query)
    if not lines:
        return None

    # Require the first significant line to appear near the start, or we may be
    # matching quoted material later in an answer rather than the repeated prompt.
    first_plain = markdownish_to_plain(lines[0])
    head_plain = markdownish_to_plain(body_head[: max(800, len(lines[0]) * 4)])
    if first_plain[: min(40, len(first_plain))] not in head_plain:
        return None

    # Use the last significant line as the anchor. This fixes long prompt blocks
    # like transmission 027 where internal bold/triple-star text looks like Q/A.
    for line in reversed(lines):
        line_plain = markdownish_to_plain(line)
        if len(line_plain) < 8:
            continue

        # Try literal-ish searches first, preserving Markdown if possible.
        literal_variants = [
            line.strip(),
            line.strip().strip("*").strip(),
            "**" + line.strip().strip("*").strip() + "**",
            "***" + line.strip().strip("*").strip() + "***",
        ]
        best_end = None
        for variant in literal_variants:
            if not variant:
                continue
            idx = body_head.find(variant)
            if idx != -1:
                best_end = idx + len(variant)
        if best_end is not None:
            return best_end

        # Fallback: token-window search on the raw body. This avoids needing an
        # offset map from plain text back to Markdown.
        tokens = line_plain.split()
        if not tokens:
            continue
        anchor = " ".join(tokens[-min(6, len(tokens)):])
        # Search for the final token literally near the opening body region.
        final_token = tokens[-1]
        matches = [m.end() for m in re.finditer(re.escape(final_token), body_head, flags=re.IGNORECASE)]
        if matches:
            return max(matches)

    return None


def merge_empty_answer_fragment_pairs(pairs: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Merge accidental split-fragments where an empty-answer pair is followed by its real answer.

    This happens in dialogue files where a user question contains an italicised
    or quoted passage. The parser may split that quoted/italicised material into
    a second "question", leaving the real intended question with an empty answer.

    Conservative rule:
    - current pair has an empty answer
    - next pair has a non-empty answer
    - next question looks like a substring/continuation of current question
    """
    if not pairs:
        return pairs, []

    merged: List[Dict[str, Any]] = []
    warnings: List[str] = []
    i = 0

    while i < len(pairs):
        current = pairs[i]

        if (
            i + 1 < len(pairs)
            and not (current.get("answer") or "").strip()
            and (pairs[i + 1].get("answer") or "").strip()
        ):
            nxt = pairs[i + 1]
            current_q_plain = markdownish_to_plain(current.get("question", ""))
            next_q_plain = markdownish_to_plain(nxt.get("question", ""))

            looks_like_fragment = False
            if current_q_plain and next_q_plain:
                next_start = " ".join(next_q_plain.split()[:4])
                looks_like_fragment = (
                    next_q_plain in current_q_plain
                    or current_q_plain.endswith(next_q_plain)
                    or (
                        len(current_q_plain) > len(next_q_plain) * 1.25
                        and next_start in current_q_plain
                    )
                )

            if looks_like_fragment:
                repaired = dict(current)
                repaired["answer"] = nxt.get("answer", "")
                repaired["source_character_end"] = nxt.get(
                    "source_character_end",
                    current.get("source_character_end"),
                )
                repaired["split_confidence"] = "medium"
                repaired["warnings"] = [
                    w for w in repaired.get("warnings", [])
                    if w != "empty_answer_after_split"
                ]
                repaired["repair_notes"] = repaired.get("repair_notes", []) + [
                    "merged_empty_answer_question_fragment_with_following_pair"
                ]
                merged.append(repaired)
                warnings.append("merged_empty_answer_question_fragment")
                i += 2
                continue

        merged.append(current)
        i += 1

    for idx, pair in enumerate(merged, start=1):
        pair["turn_index"] = idx
        pair["is_followup"] = idx > 1

    return merged, warnings


def split_qa_pairs(body: str, metadata_query: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    warnings: List[str] = []
    pairs: List[Dict[str, Any]] = []

    def finish_pairs(current_pairs: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
        repaired_pairs, repair_warnings = merge_empty_answer_fragment_pairs(current_pairs)
        warnings.extend(repair_warnings)
        return repaired_pairs, warnings

    # Best path when a metadata query exists: use it as the canonical first
    # question, strip its repeated opening copy from the body, then only treat
    # separator-led bold blocks as follow-up questions. This prevents quoted
    # source material inside the prompt from being mistaken for separate Q/A
    # turns.
    if metadata_query:
        prompt_end, consumed_parts = consume_repeated_metadata_prompt(body, metadata_query)

        # For long, multi-line prompts containing quoted/source text, Markdown
        # emphasis can make the repeated prompt look like several fake Q/A
        # turns. Use the fuzzy detector only for those long/multiline cases.
        #
        # IMPORTANT: do not use this for ordinary one-line questions. In v6,
        # fuzzy matching could latch onto a repeated final word such as "this"
        # inside the answer and incorrectly chop off most of the answer.
        metadata_lines = significant_metadata_lines(metadata_query)
        use_fuzzy_prompt_detector = (
            len(metadata_lines) >= 3
            or len(metadata_query) >= 800
        )

        if use_fuzzy_prompt_detector:
            fuzzy_prompt_end = find_repeated_metadata_prompt_end(body, metadata_query)
            if fuzzy_prompt_end is not None and (
                prompt_end is None or fuzzy_prompt_end > prompt_end
            ):
                prompt_end = fuzzy_prompt_end

        if prompt_end is not None:
            remaining = body[prompt_end:].strip()
            follow_spans = separator_question_spans(remaining)

            first_answer_end = follow_spans[0][0] if follow_spans else len(remaining)
            first_answer = remaining[:first_answer_end].strip()

            pairs.append(
                {
                    "turn_index": 1,
                    "question": metadata_query.strip(),
                    "answer": first_answer,
                    "is_followup": False,
                    "split_method": "metadata_query_opening_prompt",
                    "split_confidence": "high" if first_answer else "low",
                    "source_character_start": 0,
                    "source_character_end": prompt_end + first_answer_end,
                    "warnings": [] if first_answer else ["empty_answer_after_split"],
                }
            )

            for idx, span in enumerate(follow_spans, start=2):
                sep_start, q_start, q_end, question, method = span
                next_sep_start = follow_spans[idx - 1][0] if idx - 1 < len(follow_spans) else len(remaining)
                answer = remaining[q_end:next_sep_start].strip()

                pair_warnings: List[str] = []
                confidence = "high"
                if not answer:
                    pair_warnings.append("empty_answer_after_split")
                    confidence = "low"
                if len(question) < 10:
                    pair_warnings.append("very_short_question")
                    confidence = "medium"

                pairs.append(
                    {
                        "turn_index": idx,
                        "question": question,
                        "answer": answer,
                        "is_followup": True,
                        "split_method": method,
                        "split_confidence": confidence,
                        "source_character_start": prompt_end + q_start,
                        "source_character_end": prompt_end + next_sep_start,
                        "warnings": pair_warnings,
                    }
                )

            separator_count = len(re.findall(r"(?is)(?:^|\s)(---|\*\s*\*\s*\*|\*{3}|<hr\s*/?>)(?:\s|$)", remaining))
            if separator_count > max(0, len(follow_spans)):
                warnings.append("extra_separators_not_used_as_qa_boundaries")

            return finish_pairs(pairs)

    spans = question_candidate_spans(body, metadata_query)

    if spans:
        if metadata_query:
            first_q_norm = normalise_space(spans[0][3])
            meta_q_norm = normalise_space(metadata_query)
            if first_q_norm != meta_q_norm:
                if first_q_norm not in meta_q_norm and meta_q_norm not in first_q_norm:
                    warnings.append("metadata_query_differs_from_first_body_question")

        for idx, span in enumerate(spans):
            sep_start, q_start, q_end, question, method = span
            next_sep_start = spans[idx + 1][0] if idx + 1 < len(spans) else len(body)
            answer = body[q_end:next_sep_start].strip()

            pair_warnings: List[str] = []
            confidence = "high"
            if not answer:
                pair_warnings.append("empty_answer_after_split")
                confidence = "low"
            if len(question) < 10:
                pair_warnings.append("very_short_question")
                confidence = "medium"

            pairs.append(
                {
                    "turn_index": idx + 1,
                    "question": question,
                    "answer": answer,
                    "is_followup": idx > 0,
                    "split_method": method,
                    "split_confidence": confidence,
                    "source_character_start": q_start,
                    "source_character_end": next_sep_start,
                    "warnings": pair_warnings,
                }
            )

        separator_count = len(re.findall(r"(?is)(?:^|\s)(---|\*\s*\*\s*\*|\*{3}|<hr\s*/?>)(?:\s|$)", body))
        if separator_count > len(spans) - 1:
            warnings.append("extra_separators_not_used_as_qa_boundaries")

        return finish_pairs(pairs)

    # Fallback: one Q/A pair using metadata query.
    if metadata_query:
        answer, removed = strip_repeated_metadata_query(body, metadata_query)
        if removed:
            warnings.append("duplicate_metadata_query_removed_from_answer")
        else:
            warnings.append("no_bold_question_boundaries_found_used_metadata_query")
        pairs.append(
            {
                "turn_index": 1,
                "question": metadata_query.strip(),
                "answer": answer,
                "is_followup": False,
                "split_method": "metadata_query_fallback",
                "split_confidence": "medium" if answer else "low",
                "source_character_start": 0,
                "source_character_end": len(body),
                "warnings": [] if answer else ["empty_answer_after_split"],
            }
        )
    else:
        warnings.append("no_question_found_entire_body_stored_as_answer")
        pairs.append(
            {
                "turn_index": 1,
                "question": "",
                "answer": body.strip(),
                "is_followup": False,
                "split_method": "raw_body_no_question_found",
                "split_confidence": "low",
                "source_character_start": 0,
                "source_character_end": len(body),
                "warnings": ["missing_question"],
            }
        )

    return finish_pairs(pairs)



def parse_markdown_file(path: Path, source_root: Path, include_raw: bool = False) -> ParsedFile:
    text = path.read_text(encoding="utf-8")
    rel = path.relative_to(source_root.parent).as_posix()
    source_directory = path.parent.name
    filename_date, filename_id, filename_slug = parse_filename(path)
    parsed = split_frontmatter(text)
    warnings = list(parsed.warnings)

    metadata = parsed.metadata
    transmission_id = metadata.get("id") or filename_id or path.stem
    if metadata.get("id") and filename_id and metadata.get("id") != filename_id:
        warnings.append("metadata_id_differs_from_filename_id")

    title = metadata.get("title") or (slug_to_title(filename_slug) if filename_slug else path.stem)
    date = metadata.get("date") or filename_date
    if metadata.get("date") and filename_date and metadata.get("date") != filename_date:
        warnings.append("metadata_date_differs_from_filename_date")

    model_info = MODEL_MAP.get(
        source_directory,
        {
            "model": source_directory,
            "model_display": metadata.get("model", source_directory),
            "model_family": "unknown",
        },
    )
    if source_directory not in MODEL_MAP:
        warnings.append("unknown_source_directory_model_mapping")

    metadata_model_label = metadata.get("model", "")
    if metadata_model_label:
        expected_model_key = expected_label_key_from_model_id(model_info.get("model", ""))
        metadata_model_key = canonical_model_label(metadata_model_label)
        if expected_model_key and metadata_model_key and expected_model_key != metadata_model_key:
            warnings.append("metadata_model_label_differs_from_source_directory")

    qa_pairs, qa_warnings = split_qa_pairs(parsed.body, metadata.get("query", ""))
    warnings.extend(qa_warnings)

    if include_raw:
        # Attach raw body to each parsed file response later by leaving a marker
        # in metadata.  This avoids adding a separate field to the dataclass.
        metadata["_raw_markdown_body"] = parsed.body

    return ParsedFile(
        source_file=path,
        rel_source_file=rel,
        source_directory=source_directory,
        metadata=metadata,
        raw_frontmatter=parsed.raw_frontmatter,
        body=parsed.body,
        filename_date=filename_date,
        filename_id=filename_id,
        filename_slug=filename_slug,
        transmission_id=str(transmission_id),
        title=title,
        date=date,
        model_info=model_info,
        qa_pairs=qa_pairs,
        parse_warnings=warnings,
        content_sha256=sha256_text(text),
    )


def iter_markdown_files(source_root: Path, include_gpt4_base: bool = False, include_readmes: bool = False) -> Iterable[Path]:
    excluded = set()
    if not include_gpt4_base:
        excluded.add("gpt-4-base")

    for subdir in sorted(p for p in source_root.iterdir() if p.is_dir()):
        if subdir.name in excluded:
            continue
        for path in sorted(subdir.glob("*.md")):
            if not include_readmes and path.name.lower() == "readme.md":
                continue
            yield path



def load_json_file(path: Optional[Path]) -> Any:
    if not path:
        return None
    if not path.exists():
        raise FileNotFoundError(f"JSON file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def old_seed_by_transmission_id(seed_data: Any) -> Dict[str, Dict[str, Any]]:
    if not isinstance(seed_data, dict):
        return {}
    transmissions = seed_data.get("transmissions")
    if not isinstance(transmissions, list):
        return {}

    out: Dict[str, Dict[str, Any]] = {}
    for item in transmissions:
        if not isinstance(item, dict):
            continue
        tid = item.get("transmission_id") or item.get("question_id") or item.get("id")
        if tid is None:
            continue
        out[str(tid)] = item
    return out


def extract_url_map(data: Any) -> Dict[str, str]:
    """Extract transmission_id -> URL from a range of plausible JSON shapes.

    Supported examples:
      {"001": "https://..."}
      {"001": {"substack_url": "https://..."}}
      [{"transmission_id": "001", "substack_url": "https://..."}, ...]
      {"transmissions": [{...}]}
    """
    result: Dict[str, str] = {}

    def maybe_add_from_obj(obj: Dict[str, Any]) -> None:
        id_keys = ("transmission_id", "question_id", "id", "transmission", "number")
        url_keys = ("substack_url", "url", "canonical_url", "corrected_url", "best_url")
        tid = next((obj.get(k) for k in id_keys if obj.get(k) is not None), None)
        url = next((obj.get(k) for k in url_keys if isinstance(obj.get(k), str) and obj.get(k).startswith("http")), None)
        if tid is not None and url:
            result[str(tid)] = url

    if isinstance(data, dict):
        # Simple mapping.
        for k, v in data.items():
            if isinstance(v, str) and v.startswith("http"):
                result[str(k)] = v
            elif isinstance(v, dict):
                if any(url_key in v for url_key in ("substack_url", "url", "canonical_url", "corrected_url", "best_url")):
                    vv = dict(v)
                    vv.setdefault("transmission_id", k)
                    maybe_add_from_obj(vv)

        # Common collection keys.
        for key in ("transmissions", "items", "records", "urls", "data"):
            if isinstance(data.get(key), list):
                for item in data[key]:
                    if isinstance(item, dict):
                        maybe_add_from_obj(item)

    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                maybe_add_from_obj(item)

    return result


def response_from_parsed_file(parsed: ParsedFile, include_raw: bool = False) -> Dict[str, Any]:
    response_id = f"{parsed.transmission_id}:{parsed.model_info['model']}:{parsed.source_directory}:{parsed.source_file.stem}"
    response: Dict[str, Any] = {
        "response_id": response_id,
        "model": parsed.model_info["model"],
        "model_display": parsed.model_info["model_display"],
        "model_family": parsed.model_info["model_family"],
        "model_notes": "",
        "source_directory": parsed.source_directory,
        "source_file": parsed.rel_source_file,
        "source_filename": parsed.source_file.name,
        "source_title": parsed.title,
        "source_date": parsed.date,
        "metadata_model_label": parsed.metadata.get("model", ""),
        "metadata_query": parsed.metadata.get("query", ""),
        "content_sha256": parsed.content_sha256,
        "qa_pair_count": len(parsed.qa_pairs),
        "qa_pairs": parsed.qa_pairs,
        "parse_warnings": parsed.parse_warnings,
    }
    if include_raw:
        response["raw_markdown_body"] = parsed.body
        response["raw_frontmatter"] = parsed.raw_frontmatter
    return response


def build_dataset(
    parsed_files: List[ParsedFile],
    source_root: Path,
    seed_by_id: Dict[str, Dict[str, Any]],
    url_map: Dict[str, str],
    include_raw: bool = False,
    include_gpt4_base: bool = False,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    grouped: Dict[str, List[ParsedFile]] = defaultdict(list)
    for pf in parsed_files:
        grouped[pf.transmission_id].append(pf)

    transmissions: List[Dict[str, Any]] = []
    report: Dict[str, Any] = {
        "created_utc": now_utc_iso(),
        "source_root": source_root.as_posix(),
        "files_found": len(parsed_files),
        "files_parsed": len(parsed_files),
        "files_failed": [],
        "skipped_directories": [] if include_gpt4_base else ["gpt-4-base"],
        "source_directory_counts": dict(Counter(pf.source_directory for pf in parsed_files)),
        "model_counts": dict(Counter(pf.model_info["model"] for pf in parsed_files)),
        "qa_pair_count": 0,
        "transmission_count": 0,
        "warning_counts": {},
        "manual_review_files": [],
        "url_overrides": [],
        "seed_metadata_used_for_transmission_ids": [],
        "duplicate_model_responses": [],
        "duplicate_content_hashes": [],
        "transmission_ids_with_multiple_titles": [],
        "transmission_ids_with_question_variants": [],
    }

    warning_counter: Counter[str] = Counter()
    qa_pair_total = 0

    def sort_tid(tid: str) -> Tuple[int, str]:
        # Sort numeric IDs numerically; E003a/AB001/etc. after regular numbers
        # but still stable.
        if re.fullmatch(r"\d+", tid):
            return (0, f"{int(tid):06d}")
        return (1, tid)

    for tid in sorted(grouped.keys(), key=sort_tid):
        files = sorted(grouped[tid], key=lambda p: (p.date or "", p.source_directory, p.source_file.name))
        seed = seed_by_id.get(str(tid), {})

        titles = [pf.title for pf in files if pf.title]
        title_counts = Counter(titles)
        canonical_title = title_counts.most_common(1)[0][0] if title_counts else seed.get("title", str(tid))
        if len(title_counts) > 1:
            report["transmission_ids_with_multiple_titles"].append(
                {"transmission_id": tid, "titles": dict(title_counts)}
            )

        slugs = [pf.filename_slug for pf in files if pf.filename_slug]
        canonical_slug = Counter(slugs).most_common(1)[0][0] if slugs else None
        dates = sorted(set(pf.date for pf in files if pf.date))

        # URL priority: explicit url_map > old seed > none.  We do not invent
        # Substack URLs here because you already know some of them need fixing.
        substack_url = None
        substack_url_source = "none"
        if str(tid) in url_map:
            substack_url = url_map[str(tid)]
            substack_url_source = "url_map"
            old_url = seed.get("substack_url") if isinstance(seed, dict) else None
            if old_url and old_url != substack_url:
                report["url_overrides"].append(
                    {"transmission_id": tid, "old_url": old_url, "new_url": substack_url}
                )
        elif isinstance(seed, dict) and seed.get("substack_url"):
            substack_url = seed.get("substack_url")
            substack_url_source = "metadata_seed"

        if seed:
            report["seed_metadata_used_for_transmission_ids"].append(tid)

        responses = [response_from_parsed_file(pf, include_raw=include_raw) for pf in files]

        # Add per-model variant indices, useful when the same model has more
        # than one response for the same transmission.
        model_variant_counter: Counter[str] = Counter()
        for response in responses:
            model_variant_counter[response["model"]] += 1
            response["response_variant_index_for_model"] = model_variant_counter[response["model"]]

        qa_pair_total += sum(r["qa_pair_count"] for r in responses)

        # Warnings and manual review.
        build_warnings: List[str] = []
        seen_model_files: Counter[str] = Counter()
        q_variants: Dict[str, List[str]] = defaultdict(list)
        for pf in files:
            for w in pf.parse_warnings:
                warning_counter[w] += 1
            pair_warnings_flat = sorted({w for pair in pf.qa_pairs for w in pair.get("warnings", [])})
            if pf.parse_warnings or pair_warnings_flat:
                report["manual_review_files"].append(
                    {
                        "transmission_id": tid,
                        "title": pf.title,
                        "model": pf.model_info["model"],
                        "source_file": pf.rel_source_file,
                        "warnings": pf.parse_warnings,
                        "pair_warnings": pair_warnings_flat,
                        "qa_pair_count": len(pf.qa_pairs),
                    }
                )
            seen_model_files[pf.model_info["model"]] += 1
            if pf.qa_pairs:
                q_variants[normalise_space(pf.qa_pairs[0].get("question", ""))].append(pf.model_info["model"])

        duplicate_models = {m: c for m, c in seen_model_files.items() if c > 1}
        if duplicate_models:
            build_warnings.append("duplicate_model_responses_for_same_transmission")
            report["duplicate_model_responses"].append({"transmission_id": tid, "models": duplicate_models})

        hash_groups: Dict[str, List[Dict[str, str]]] = defaultdict(list)
        for pf in files:
            hash_groups[pf.content_sha256].append(
                {
                    "model": pf.model_info["model"],
                    "source_file": pf.rel_source_file,
                }
            )
        duplicate_hash_groups = {
            h: items for h, items in hash_groups.items()
            if len(items) > 1
        }
        if duplicate_hash_groups:
            build_warnings.append("duplicate_content_hash_across_responses")
            report["duplicate_content_hashes"].append(
                {
                    "transmission_id": tid,
                    "hashes": [
                        {"sha256": h, "responses": items}
                        for h, items in duplicate_hash_groups.items()
                    ],
                }
            )

        if len(q_variants) > 1:
            build_warnings.append("multiple_first_question_variants_across_models")
            report["transmission_ids_with_question_variants"].append(
                {
                    "transmission_id": tid,
                    "variant_count": len(q_variants),
                    "variants": [
                        {"question_preview": q[:240], "models": models}
                        for q, models in q_variants.items()
                    ],
                }
            )

        transmission: Dict[str, Any] = {
            "transmission_id": tid,
            "title": canonical_title,
            "slug": canonical_slug,
            "date_first": dates[0] if dates else seed.get("date_published"),
            "dates": dates,
            "date_published": seed.get("date_published") if isinstance(seed, dict) else None,
            "substack_url": substack_url,
            "substack_url_source": substack_url_source,
            "generation": seed.get("generation", "leilan_2.0") if isinstance(seed, dict) else "leilan_2.0",
            "source_note": seed.get("source_note", "Claude-family voiced Leilan transmission") if isinstance(seed, dict) else "Claude-family voiced Leilan transmission",
            "responses": responses,
            "themes": seed.get("themes", []) if isinstance(seed, dict) else [],
            "technical_notes": seed.get("technical_notes", "") if isinstance(seed, dict) else "",
            "curator_notes": seed.get("curator_notes", "") if isinstance(seed, dict) else "",
            "build_warnings": build_warnings,
        }
        transmissions.append(transmission)

    report["qa_pair_count"] = qa_pair_total
    report["transmission_count"] = len(transmissions)
    report["warning_counts"] = dict(warning_counter)

    corpus_info = {
        "name": "Leilan Post-GPT-3 Claude-family Transmissions",
        "description": "Rebuilt grouped dataset from Markdown files in post-gpt3_transmissions_by_model, excluding gpt-4-base by default.",
        "schema_version": "leilan.post_gpt3.grouped_qa.v1.10",
        "date_compiled_utc": now_utc_iso(),
        "source_root": source_root.as_posix(),
        "excluded_source_directories": [] if include_gpt4_base else ["gpt-4-base"],
        "transmission_count": len(transmissions),
        "response_count": len(parsed_files),
        "qa_pair_count": qa_pair_total,
        "model_count": len(set(pf.model_info["model"] for pf in parsed_files)),
        "source_directory_counts": report["source_directory_counts"],
        "model_counts": report["model_counts"],
        "notes": "Counts are derived from the parsed Markdown files at build time; no hand-maintained total_transmissions field is used.",
    }

    dataset = {
        "corpus_info": corpus_info,
        "transmissions": transmissions,
    }
    return dataset, report


def write_json(path: Path, data: Any) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def write_review_markdown(path: Path, report: Dict[str, Any], dataset: Dict[str, Any], only_warnings: bool = True) -> None:
    transmissions_by_id = {t["transmission_id"]: t for t in dataset.get("transmissions", [])}

    lines: List[str] = []
    lines.append("# Leilan Q/A split review\n")
    lines.append(f"Generated: `{report.get('created_utc')}`\n")
    lines.append(f"Files parsed: **{report.get('files_parsed')}**  \n")
    lines.append(f"Transmissions: **{report.get('transmission_count')}**  \n")
    lines.append(f"Q/A pairs: **{report.get('qa_pair_count')}**  \n")
    lines.append("\n")

    manual = report.get("manual_review_files", [])
    if only_warnings:
        lines.append(f"This file lists only records with parser warnings or Q/A pair warnings. Count: **{len(manual)}**.\n\n")
        review_items = manual
    else:
        review_items = []
        for t in dataset.get("transmissions", []):
            for r in t.get("responses", []):
                review_items.append(
                    {
                        "transmission_id": t.get("transmission_id"),
                        "title": t.get("title"),
                        "model": r.get("model"),
                        "source_file": r.get("source_file"),
                        "warnings": r.get("parse_warnings", []),
                        "qa_pair_count": r.get("qa_pair_count"),
                    }
                )

    for item in review_items:
        tid = item.get("transmission_id", "")
        transmission = transmissions_by_id.get(str(tid), {})
        title = item.get("title") or transmission.get("title", "")
        model = item.get("model", "")
        source_file = item.get("source_file", "")
        warnings = item.get("warnings", [])
        pair_warnings_header = item.get("pair_warnings", [])
        lines.append(f"## {tid} — {title}\n\n")
        lines.append(f"- Model: `{model}`\n")
        lines.append(f"- Source: `{source_file}`\n")
        lines.append(f"- Parser warnings: `{', '.join(warnings) if warnings else 'none'}`\n")
        lines.append(f"- Pair warnings: `{', '.join(pair_warnings_header) if pair_warnings_header else 'none'}`\n")
        lines.append(f"- Q/A pairs: `{item.get('qa_pair_count')}`\n\n")

        # Find actual response preview.
        for r in transmission.get("responses", []):
            if r.get("source_file") == source_file:
                for pair in r.get("qa_pairs", []):
                    q = pair.get("question", "").replace("\n", " ")
                    a = pair.get("answer", "").replace("\n", " ")
                    pair_warnings = pair.get("warnings", [])
                    lines.append(f"### Turn {pair.get('turn_index')}\n\n")
                    lines.append(f"**Question preview:** {q[:500]}{'…' if len(q) > 500 else ''}\n\n")
                    lines.append(f"**Answer preview:** {a[:700]}{'…' if len(a) > 700 else ''}\n\n")
                    if pair_warnings:
                        lines.append(f"**Pair warnings:** `{', '.join(pair_warnings)}`\n\n")
                break
        lines.append("---\n\n")

    path.write_text("".join(lines), encoding="utf-8")


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Rebuild full_leilan_claude_dataset.json from post-GPT-3 Markdown transmissions."
    )
    p.add_argument("--source-root", default=DEFAULT_SOURCE_ROOT, help=f"Folder containing model subfolders. Default: {DEFAULT_SOURCE_ROOT}")
    p.add_argument("--output", default=DEFAULT_OUTPUT, help=f"Output JSON file. Default: {DEFAULT_OUTPUT}")
    p.add_argument("--report", default=DEFAULT_REPORT, help=f"Build report JSON file. Default: {DEFAULT_REPORT}")
    p.add_argument("--review-md", default=DEFAULT_REVIEW_MD, help=f"Human-readable review Markdown. Default: {DEFAULT_REVIEW_MD}")
    p.add_argument("--seed-json", default=None, help="Optional old/incomplete JSON file to copy themes, notes, generation, and URLs from by transmission_id. Responses are NOT copied from it.")
    p.add_argument("--url-map", default=None, help="Optional corrected URL JSON file. Overrides seed URLs when IDs match.")
    p.add_argument("--include-gpt4-base", action="store_true", help="Include gpt-4-base folder. Default is to skip it.")
    p.add_argument("--include-readmes", action="store_true", help="Include README.md files from model folders. Default is to skip them.")
    p.add_argument("--include-raw", action="store_true", help="Include raw Markdown body/frontmatter in each response. This makes the output much larger.")
    p.add_argument("--only-dir", action="append", default=None, help="For testing: parse only files from this source directory, e.g. --only-dir opus3. Can be repeated.")
    p.add_argument("--match", default=None, help="For testing: parse only files whose filename or path contains this text, e.g. --match 265 or --match prostitution.")
    p.add_argument("--id", default=None, help="For testing: parse only files for this exact transmission ID, e.g. --id 001 or --id E001.")
    p.add_argument("--limit-files", type=int, default=None, help="For testing: parse only the first N markdown files after any --only-dir/--match filtering.")
    p.add_argument("--all-review", action="store_true", help="Write every parsed response to qa_split_review.md, not just warnings.")
    p.add_argument("--dry-run", action="store_true", help="Parse and print counts, but do not write output files.")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    source_root = Path(args.source_root)

    if not source_root.exists() or not source_root.is_dir():
        print(f"ERROR: I could not find the source folder: {source_root}", file=sys.stderr)
        print("Put this script in the repo root, or pass --source-root path/to/post-gpt3_transmissions_by_model", file=sys.stderr)
        return 1

    seed_data = load_json_file(Path(args.seed_json)) if args.seed_json else None
    seed_by_id = old_seed_by_transmission_id(seed_data)

    url_map_data = load_json_file(Path(args.url_map)) if args.url_map else None
    url_map = extract_url_map(url_map_data) if url_map_data is not None else {}

    md_files = list(iter_markdown_files(source_root, include_gpt4_base=args.include_gpt4_base, include_readmes=args.include_readmes))

    if args.only_dir:
        wanted_dirs = set(args.only_dir)
        md_files = [p for p in md_files if p.parent.name in wanted_dirs]

    if args.match:
        needle = args.match.lower()
        md_files = [
            p for p in md_files
            if needle in p.name.lower() or needle in p.as_posix().lower()
        ]

    if args.id:
        wanted_id = args.id
        md_files = [
            p for p in md_files
            if parse_filename(p)[1] == wanted_id
        ]

    if args.limit_files is not None:
        md_files = md_files[: args.limit_files]

    parsed_files: List[ParsedFile] = []
    failed: List[Dict[str, str]] = []

    for path in md_files:
        try:
            parsed_files.append(parse_markdown_file(path, source_root, include_raw=args.include_raw))
        except Exception as exc:  # noqa: BLE001 - we want a report, not a crash.
            failed.append({"source_file": path.as_posix(), "error": repr(exc)})

    dataset, report = build_dataset(
        parsed_files=parsed_files,
        source_root=source_root,
        seed_by_id=seed_by_id,
        url_map=url_map,
        include_raw=args.include_raw,
        include_gpt4_base=args.include_gpt4_base,
    )
    report["files_failed"] = failed
    report["files_found"] = len(md_files)
    report["files_parsed"] = len(parsed_files)

    print("\nLeilan Claude dataset rebuild")
    print("-----------------------------")
    print(f"Source root:        {source_root}")
    print(f"Markdown files:     {len(md_files)}")
    print(f"Parsed files:       {len(parsed_files)}")
    print(f"Failed files:       {len(failed)}")
    print(f"Transmissions:      {report['transmission_count']}")
    print(f"Q/A pairs:          {report['qa_pair_count']}")
    print("\nBy source directory:")
    for dirname, count in sorted(report["source_directory_counts"].items()):
        print(f"  {dirname:12} {count}")

    if report["warning_counts"]:
        print("\nParser warnings:")
        for warning, count in sorted(report["warning_counts"].items()):
            print(f"  {warning:48} {count}")
    else:
        print("\nParser warnings: none")

    if report.get("duplicate_model_responses"):
        print(f"Duplicate model responses: {len(report['duplicate_model_responses'])} transmission(s)")
    if report.get("duplicate_content_hashes"):
        print(f"Duplicate exact file content: {len(report['duplicate_content_hashes'])} transmission(s)")

    if args.dry_run:
        print("\nDry run only. No files written.")
        return 0 if not failed else 2

    output_path = Path(args.output)
    report_path = Path(args.report)
    review_path = Path(args.review_md)

    write_json(output_path, dataset)
    write_json(report_path, report)
    write_review_markdown(review_path, report, dataset, only_warnings=not args.all_review)

    print("\nWrote:")
    print(f"  {output_path}")
    print(f"  {report_path}")
    print(f"  {review_path}")

    if failed:
        print("\nSome files failed to parse. See the build report.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
