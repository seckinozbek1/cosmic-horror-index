"""
Corpus Loader — Downloads and parses sacred texts from public domain sources.

Handles: HTML scraping (sacred-texts.com, Perseus), plain text (Gutenberg), and manual entry.
Outputs: Standardized JSON per text with metadata.
"""

import json
import re
import time
import logging
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("chi-pipeline.corpus")

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
}


def _get(url: str, timeout: int = 30, retries: int = 2) -> requests.Response:
    """GET with browser headers and simple retry on 429/5xx."""
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, timeout=timeout, headers=BROWSER_HEADERS)
            if resp.status_code == 403:
                raise requests.HTTPError(f"403 Forbidden: {url}", response=resp)
            resp.raise_for_status()
            time.sleep(0.3)  # polite delay
            return resp
        except requests.HTTPError as e:
            if attempt < retries and (resp.status_code in (429, 500, 502, 503)):
                wait = 2 ** attempt * 3
                logger.debug(f"    Retrying {url} in {wait}s (attempt {attempt+1})")
                time.sleep(wait)
                continue
            raise
    raise RuntimeError(f"Failed after {retries} retries: {url}")


class CorpusLoader:
    def __init__(self, config: dict, output_dir: Path):
        self.config = config
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.stats = {"total_texts": 0, "total_chars": 0}

    def load_text(self, corpus_id: str, tradition: str, text_def: dict):
        """Load a single text, dispatching by format."""
        tradition_dir = self.output_dir / tradition
        tradition_dir.mkdir(exist_ok=True)

        output_path = tradition_dir / f"{corpus_id}_{self._slugify(text_def['name'])}.json"

        if output_path.exists():
            existing = json.loads(output_path.read_text(encoding="utf-8"))
            # Skip if already has real content (any non-placeholder passage)
            passages = existing.get("passages", [])
            if passages and any(p.get("type") != "placeholder" for p in passages):
                logger.info(f"  Already exists: {output_path.name} ({len(passages)} passages)")
                self.stats["total_texts"] += 1
                self.stats["total_chars"] += sum(len(p["text"]) for p in passages)
                return

        fmt = text_def.get("format", "manual_entry")

        if fmt == "html_scrape":
            passages = self._scrape_html(text_def)
        elif fmt in ("plain_text", "plaintext_url"):
            passages = self._load_plain(text_def)
        elif fmt == "manual_entry":
            passages = self._manual_placeholder(text_def)
        else:
            logger.warning(f"  Unknown format: {fmt}, creating placeholder")
            passages = self._manual_placeholder(text_def)

        # Validate content matches expected tradition — catches wrong PG IDs
        if self._is_suspicious(tradition, passages):
            logger.warning(
                f"  SUSPICIOUS: {corpus_id}/{text_def['name']} — "
                f"no tradition keywords found in first passages. "
                f"Verify the source URL points to the correct text. "
                f"Run: python tasks.py validate-corpus"
            )

        doc = {
            "corpus_id": corpus_id,
            "tradition": tradition,
            "name": text_def["name"],
            "translation": text_def.get("translation", "unknown"),
            "source": text_def.get("source", ""),
            "chunk_by": text_def.get("chunk_by", "paragraph"),
            "key_sections": text_def.get("key_sections", []),
            "passages": passages
        }

        output_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
        self.stats["total_texts"] += 1
        self.stats["total_chars"] += sum(len(p["text"]) for p in passages)
        logger.info(f"  Saved: {output_path.name} ({len(passages)} passages, "
                    f"{sum(len(p['text']) for p in passages)} chars)")

    # ------------------------------------------------------------------ #
    #  Format dispatchers                                                  #
    # ------------------------------------------------------------------ #

    def _scrape_html(self, text_def: dict) -> list:
        """Scrape text from HTML source."""
        url = text_def["source"]
        if url == "manual_entry" or url.startswith("manual_entry"):
            return self._manual_placeholder(text_def)

        # Try primary URL
        resp = self._try_fetch(url)

        # Try alt_source if primary failed
        if resp is None:
            alt = text_def.get("alt_source", "")
            if alt and not alt.startswith(("manual", "GRETIL")):
                # Strip human-readable prefix like "Project Gutenberg"
                alt_url = re.search(r"https?://\S+", alt)
                if alt_url:
                    alt = alt_url.group(0)
                resp = self._try_fetch(alt)
                if resp is not None:
                    url = alt  # update domain for parser dispatch

        if resp is None:
            return self._manual_placeholder(text_def)

        # Plain-text response (Gutenberg, raw txt)
        content_type = resp.headers.get("Content-Type", "")
        if "text/plain" in content_type or url.endswith(".txt"):
            return self._parse_plaintext(resp.text, text_def)

        soup = BeautifulSoup(resp.content, "html.parser")
        domain = urlparse(url).netloc

        if "sacred-texts.com" in domain:
            return self._parse_sacred_texts(soup, text_def, url)
        elif "perseus.tufts.edu" in domain:
            return self._parse_perseus(soup, text_def)
        elif "suttacentral.net" in domain:
            return self._parse_suttacentral(soup, text_def)
        elif "accesstoinsight.org" in domain:
            return self._parse_accesstoinsight(soup, text_def)
        elif "hplovecraft.com" in domain:
            return self._parse_lovecraft(soup, text_def)
        elif "gnosis.org" in domain:
            return self._parse_gnosis(soup, text_def)
        elif "gutenberg.org" in domain:
            return self._parse_plaintext(resp.text, text_def)
        else:
            return self._parse_generic_html(soup, text_def)

    def _load_plain(self, text_def: dict) -> list:
        """Load from a local plain text file or a remote .txt URL."""
        source = text_def.get("source", "")

        # Remote URL
        if source.startswith("http"):
            resp = self._try_fetch(source)
            if resp is None:
                return self._manual_placeholder(text_def)
            return self._parse_plaintext(resp.text, text_def)

        # Local file
        p = Path(source)
        if not p.exists():
            return self._manual_placeholder(text_def)
        text = p.read_text(encoding="utf-8", errors="replace")
        return self._parse_plaintext(text, text_def)

    # ------------------------------------------------------------------ #
    #  Site-specific parsers                                               #
    # ------------------------------------------------------------------ #

    def _parse_sacred_texts(self, soup, text_def, url) -> list:
        """Parse sacred-texts.com.

        Index pages link to chapters; we follow up to 50 chapter links.
        Single pages are extracted directly.
        """
        passages = []

        links = soup.find_all("a", href=True)
        chapter_links = [
            a for a in links
            if (
                a["href"].endswith(".htm") or a["href"].endswith(".html")
            ) and not a["href"].startswith("http")
            and not a["href"].startswith("#")
            and not a["href"].startswith("mailto")
        ]

        if len(chapter_links) > 3:
            base_url = url.rsplit("/", 1)[0] + "/"
            for link in chapter_links[:50]:
                ch_url = base_url + link["href"]
                try:
                    ch_resp = _get(ch_url, timeout=20, retries=1)
                    ch_soup = BeautifulSoup(ch_resp.content, "html.parser")
                    ch_label = link.get_text(strip=True)
                    ch_passages = self._extract_paragraphs(ch_soup, ch_label)
                    passages.extend(ch_passages)
                except Exception as e:
                    logger.debug(f"    Could not fetch chapter {ch_url}: {e}")
        else:
            passages = self._extract_paragraphs(soup, text_def["name"])

        return passages if passages else self._manual_placeholder(text_def)

    def _parse_perseus(self, soup, text_def) -> list:
        """Parse Perseus Digital Library — look for the poem/text content div."""
        # Try multiple known container selectors
        for selector in [
            ("div", {"id": "text"}),
            ("div", {"class": "text"}),
            ("div", {"class": "text_container"}),
            ("div", {"id": "main"}),
        ]:
            content = soup.find(selector[0], selector[1])
            if content:
                passages = self._extract_paragraphs(content, text_def["name"])
                if passages:
                    return passages
        return self._extract_paragraphs(soup, text_def["name"])

    def _parse_suttacentral(self, soup, text_def) -> list:
        """Parse SuttaCentral — usually a React SPA; fall back to body text."""
        for tag, attrs in [
            ("article", {}),
            ("main", {}),
            ("div", {"id": "text"}),
            ("div", {"class": "text"}),
        ]:
            content = soup.find(tag, attrs)
            if content:
                passages = self._extract_paragraphs(content, text_def["name"])
                if len(passages) > 3:
                    return passages
        return self._extract_paragraphs(soup, text_def["name"])

    def _parse_accesstoinsight(self, soup, text_def) -> list:
        """Parse ATI pages. Index pages link to individual suttas — follow up to 40."""
        url = text_def.get("source", "")
        links = soup.find_all("a", href=True)
        sutta_links = [
            a for a in links
            if (a["href"].endswith(".html") or a["href"].endswith(".htm"))
            and not a["href"].startswith("http")
            and not a["href"].startswith("#")
            and not a["href"].startswith("mailto")
            and "index" not in a["href"]
        ]
        if len(sutta_links) > 2:
            base_url = url.rsplit("/", 1)[0] + "/"
            passages = []
            for link in sutta_links[:40]:
                sutta_url = base_url + link["href"]
                try:
                    resp = _get(sutta_url, timeout=20, retries=1)
                    s = BeautifulSoup(resp.content, "html.parser")
                    content = s.find("div", id="main") or s.find("body")
                    if content:
                        real = [p for p in self._extract_paragraphs(content, text_def["name"])
                                if p.get("type") != "placeholder"]
                        passages.extend(real)
                except Exception as e:
                    logger.debug(f"    Could not fetch sutta {sutta_url}: {e}")
            return passages if passages else self._manual_placeholder(text_def)
        # Single text page
        content = soup.find("div", id="main") or soup.find("body")
        if not content:
            return self._manual_placeholder(text_def)
        return self._extract_paragraphs(content, text_def["name"])

    def _parse_lovecraft(self, soup, text_def) -> list:
        """Parse hplovecraft.com — the story text is in <div class='text'>."""
        content = (
            soup.find("div", class_="text")
            or soup.find("div", id="text")
            or soup.find("div", class_="story")
            or soup.find("body")
        )
        passages = self._extract_paragraphs(content, text_def["name"])
        return passages if passages else self._manual_placeholder(text_def)

    def _parse_gnosis(self, soup, text_def) -> list:
        """Parse gnosis.org Nag Hammadi Library."""
        # Strip navigation / header junk
        for tag in soup.find_all(["a", "hr"]):
            if tag.name == "a" and tag.get_text(strip=True) in ("Next", "Previous", "Index"):
                tag.decompose()
        body = soup.find("body") or soup
        return self._extract_paragraphs(body, text_def["name"])

    def _parse_generic_html(self, soup, text_def) -> list:
        return self._extract_paragraphs(soup, text_def["name"])

    def _parse_plaintext(self, text: str, text_def: dict) -> list:
        """Parse Project Gutenberg or other plain-text sources.

        Strips PG boilerplate and splits on blank lines.
        """
        # Strip PG header/footer
        start_marks = [
            "*** START OF THE PROJECT GUTENBERG",
            "*** START OF THIS PROJECT GUTENBERG",
            "*END*THE SMALL PRINT",
        ]
        end_marks = [
            "*** END OF THE PROJECT GUTENBERG",
            "*** END OF THIS PROJECT GUTENBERG",
            "End of the Project Gutenberg",
        ]
        for mark in start_marks:
            idx = text.find(mark)
            if idx != -1:
                text = text[idx + len(mark):]
                # skip to next newline
                nl = text.find("\n")
                if nl != -1:
                    text = text[nl + 1:]
                break
        for mark in end_marks:
            idx = text.find(mark)
            if idx != -1:
                text = text[:idx]
                break

        paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
        passages = []
        for i, p in enumerate(paragraphs):
            p = re.sub(r"\s+", " ", p).strip()
            if len(p) < 30:
                continue
            if len(p) > 1500:
                sub = self._split_long_text(p, 800)
                for j, s in enumerate(sub):
                    passages.append({
                        "text": s,
                        "source": text_def["name"],
                        "index": f"{i}.{j}",
                        "type": "paragraph"
                    })
            else:
                passages.append({
                    "text": p,
                    "source": text_def["name"],
                    "index": str(i),
                    "type": "paragraph"
                })
        return passages if passages else self._manual_placeholder(text_def)

    # ------------------------------------------------------------------ #
    #  Shared extraction helpers                                           #
    # ------------------------------------------------------------------ #

    def _extract_paragraphs(self, soup_element, source_label: str) -> list:
        """Extract text paragraphs from a BeautifulSoup element."""
        passages = []

        for tag in soup_element.find_all(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        paragraphs = soup_element.find_all(["p", "blockquote"])
        if not paragraphs:
            # Fallback: split body text on blank lines
            raw = soup_element.get_text(separator="\n")
            return self._parse_plaintext(raw, {"name": source_label})

        for i, p in enumerate(paragraphs):
            text = p.get_text(separator=" ", strip=True)
            text = re.sub(r"\s+", " ", text).strip()

            if len(text) < 20:
                continue
            if len(text) > 2000:
                chunks = self._split_long_text(text, 800)
                for j, chunk in enumerate(chunks):
                    passages.append({
                        "text": chunk,
                        "source": source_label,
                        "index": f"{i}.{j}",
                        "type": "paragraph"
                    })
            else:
                passages.append({
                    "text": text,
                    "source": source_label,
                    "index": str(i),
                    "type": "paragraph"
                })

        return passages

    def _split_long_text(self, text: str, max_chars: int) -> list:
        sentences = re.split(r"(?<=[.!?])\s+", text)
        chunks = []
        current = ""
        for sent in sentences:
            if len(current) + len(sent) > max_chars and current:
                chunks.append(current.strip())
                current = sent
            else:
                current = (current + " " + sent).strip()
        if current.strip():
            chunks.append(current.strip())
        return chunks

    def _manual_placeholder(self, text_def: dict) -> list:
        return [{
            "text": f"[PLACEHOLDER: {text_def['name']} — requires manual entry or local file]",
            "source": text_def["name"],
            "index": "0",
            "type": "placeholder",
            "note": text_def.get("note", "Add text content manually to data/raw/{tradition}/")
        }]

    def _try_fetch(self, url: str) -> "requests.Response | None":
        """Fetch URL; return None on failure (logs a warning)."""
        try:
            return _get(url, timeout=30, retries=1)
        except Exception as e:
            logger.warning(f"  Failed to fetch {url}: {e}")
            return None

    def _is_suspicious(self, tradition: str, passages: list) -> bool:
        """Return True if passages contain none of the expected tradition keywords."""
        try:
            from src.corpus.keywords import TRADITION_KEYWORDS
        except ImportError:
            return False
        keywords = [k.lower() for k in TRADITION_KEYWORDS.get(tradition, [])]
        if not keywords:
            return False
        real = [p for p in passages if p.get("type") != "placeholder"]
        if not real:
            return False
        sample = " ".join(p.get("text", "")[:300] for p in real[:7]).lower()
        return not any(kw in sample for kw in keywords)

    def _slugify(self, text: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:60]

    def get_stats(self) -> dict:
        return self.stats
