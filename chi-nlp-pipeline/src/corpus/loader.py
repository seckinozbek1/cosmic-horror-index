"""
Corpus Loader — Downloads and parses sacred texts from public domain sources.

Handles: HTML scraping (sacred-texts.com, Perseus), plain text, and manual entry.
Outputs: Standardized JSON per text with metadata.
"""

import json
import re
import logging
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("chi-pipeline.corpus")


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
            logger.info(f"  Already exists: {output_path.name}")
            existing = json.loads(output_path.read_text())
            self.stats["total_texts"] += 1
            self.stats["total_chars"] += sum(len(p["text"]) for p in existing.get("passages", []))
            return

        fmt = text_def.get("format", "manual_entry")

        if fmt == "html_scrape":
            passages = self._scrape_html(text_def)
        elif fmt == "plain_text":
            passages = self._load_plain(text_def)
        elif fmt == "manual_entry":
            passages = self._manual_placeholder(text_def)
        else:
            logger.warning(f"  Unknown format: {fmt}, creating placeholder")
            passages = self._manual_placeholder(text_def)

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

        output_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False))
        self.stats["total_texts"] += 1
        self.stats["total_chars"] += sum(len(p["text"]) for p in passages)
        logger.info(f"  Saved: {output_path.name} ({len(passages)} passages, "
                     f"{sum(len(p['text']) for p in passages)} chars)")

    def _scrape_html(self, text_def: dict) -> list:
        """Scrape text from HTML source (sacred-texts.com, Perseus, etc.)."""
        url = text_def["source"]
        if url.startswith("manual_entry"):
            return self._manual_placeholder(text_def)

        try:
            resp = requests.get(url, timeout=30, headers={
                "User-Agent": "CHI-NLP-Pipeline/1.0 (academic research)"
            })
            resp.raise_for_status()
        except Exception as e:
            logger.warning(f"  Failed to fetch {url}: {e}")
            # Try alt_source if available
            alt = text_def.get("alt_source")
            if alt and not alt.startswith("manual"):
                try:
                    resp = requests.get(alt, timeout=30)
                    resp.raise_for_status()
                except Exception as e2:
                    logger.warning(f"  Alt source also failed: {e2}")
                    return self._manual_placeholder(text_def)
            else:
                return self._manual_placeholder(text_def)

        soup = BeautifulSoup(resp.text, "html.parser")

        # Detect source type and extract accordingly
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
        else:
            return self._parse_generic_html(soup, text_def)

    def _parse_sacred_texts(self, soup, text_def, url) -> list:
        """Parse sacred-texts.com format.
        
        These are typically index pages linking to chapters.
        We need to follow links and extract chapter content.
        """
        passages = []

        # Check if this is an index page (has links to chapters)
        links = soup.find_all("a")
        chapter_links = [
            a for a in links
            if a.get("href") and not a["href"].startswith("http")
            and a["href"].endswith(".htm")
        ]

        if chapter_links and len(chapter_links) > 3:
            # This is an index page — follow chapter links
            base_url = url.rsplit("/", 1)[0] + "/"
            for link in chapter_links[:50]:  # cap at 50 chapters
                ch_url = base_url + link["href"]
                try:
                    ch_resp = requests.get(ch_url, timeout=20)
                    ch_soup = BeautifulSoup(ch_resp.text, "html.parser")
                    ch_passages = self._extract_paragraphs(ch_soup, link.get_text(strip=True))
                    passages.extend(ch_passages)
                except Exception as e:
                    logger.debug(f"    Could not fetch chapter {ch_url}: {e}")
        else:
            # Single page — extract directly
            passages = self._extract_paragraphs(soup, text_def["name"])

        return passages

    def _parse_perseus(self, soup, text_def) -> list:
        """Parse Perseus Digital Library format."""
        content = soup.find("div", class_="text_container") or soup.find("body")
        if not content:
            return self._manual_placeholder(text_def)
        return self._extract_paragraphs(content, text_def["name"])

    def _parse_suttacentral(self, soup, text_def) -> list:
        """Parse SuttaCentral format."""
        content = soup.find("article") or soup.find("main") or soup.find("body")
        if not content:
            return self._manual_placeholder(text_def)
        return self._extract_paragraphs(content, text_def["name"])

    def _parse_accesstoinsight(self, soup, text_def) -> list:
        """Parse Access to Insight format."""
        content = soup.find("div", id="main") or soup.find("body")
        if not content:
            return self._manual_placeholder(text_def)
        return self._extract_paragraphs(content, text_def["name"])

    def _parse_lovecraft(self, soup, text_def) -> list:
        """Parse hplovecraft.com format."""
        content = soup.find("div", class_="text") or soup.find("body")
        if not content:
            return self._manual_placeholder(text_def)
        return self._extract_paragraphs(content, text_def["name"])

    def _parse_gnosis(self, soup, text_def) -> list:
        """Parse gnosis.org Nag Hammadi library format."""
        content = soup.find("body")
        if not content:
            return self._manual_placeholder(text_def)
        return self._extract_paragraphs(content, text_def["name"])

    def _parse_generic_html(self, soup, text_def) -> list:
        """Fallback: extract all text paragraphs from body."""
        return self._extract_paragraphs(soup, text_def["name"])

    def _extract_paragraphs(self, soup_element, source_label: str) -> list:
        """Extract text paragraphs from a BeautifulSoup element."""
        passages = []
        
        # Remove script, style, nav elements
        for tag in soup_element.find_all(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        paragraphs = soup_element.find_all(["p", "blockquote", "div"])
        
        for i, p in enumerate(paragraphs):
            text = p.get_text(separator=" ", strip=True)
            # Clean up whitespace
            text = re.sub(r"\s+", " ", text).strip()
            
            if len(text) < 20:  # Skip very short fragments
                continue
            if len(text) > 2000:  # Split very long paragraphs
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
        """Split long text at sentence boundaries."""
        sentences = re.split(r"(?<=[.!?])\s+", text)
        chunks = []
        current = ""
        for sent in sentences:
            if len(current) + len(sent) > max_chars and current:
                chunks.append(current.strip())
                current = sent
            else:
                current = current + " " + sent if current else sent
        if current.strip():
            chunks.append(current.strip())
        return chunks

    def _load_plain(self, text_def: dict) -> list:
        """Load from a plain text file."""
        source = text_def.get("source", "")
        if not Path(source).exists():
            return self._manual_placeholder(text_def)
        text = Path(source).read_text()
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        return [
            {"text": p, "source": text_def["name"], "index": str(i), "type": "paragraph"}
            for i, p in enumerate(paragraphs) if len(p) > 20
        ]

    def _manual_placeholder(self, text_def: dict) -> list:
        """Create a placeholder for texts that need manual entry."""
        return [{
            "text": f"[PLACEHOLDER: {text_def['name']} — requires manual entry or local file]",
            "source": text_def["name"],
            "index": "0",
            "type": "placeholder",
            "note": text_def.get("note", "Add text content manually to data/raw/{tradition}/")
        }]

    def _slugify(self, text: str) -> str:
        """Convert text to filesystem-safe slug."""
        return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:60]

    def get_stats(self) -> dict:
        return self.stats
