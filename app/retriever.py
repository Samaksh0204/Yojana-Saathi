"""Hybrid retrieval over scheme records and any ingested PDF chunks.

BM25 (keyword) always runs. If a Chroma index has been built with
`python -m scripts.ingest`, dense results are fused in with reciprocal rank fusion.
"""
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from rank_bm25 import BM25Okapi

from .catalog import load_schemes
from .config import get_settings

log = logging.getLogger(__name__)
COLLECTION = "schemes"
_SPLIT = re.compile(r"[\s,.;:!?()\[\]\"'/\-–—|₹*_]+")


@dataclass
class Doc:
    id: str
    text: str
    scheme_id: Optional[str] = None  # set for scheme records, None for PDF chunks
    source: str = "catalog"
    title: str = ""  # scheme name; weighted up in keyword search


_STOPWORDS = set("""the for what how is are do does to of in on and need needed required which tell about
    can get me my please ke liye kya chahiye ka ki ko hai hain mein kaise kaun batao bataiye se
    के लिए क्या चाहिए का की को है हैं में कैसे कौन बताओ बताइए से""".split())


def tokenize(text: str, query: bool = False) -> list[str]:
    tokens = [t for t in _SPLIT.split(text.lower()) if len(t) > 1]
    return [t for t in tokens if t not in _STOPWORDS] if query else tokens


def pdf_chunks(chunk_chars: int = 1200, overlap: int = 150) -> list[Doc]:
    """Split every PDF in data/pdfs into overlapping text chunks."""
    from pypdf import PdfReader

    docs: list[Doc] = []
    for path in sorted((get_settings().data_dir / "pdfs").glob("*.pdf")):
        try:
            text = "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
        except Exception:
            log.exception("Could not read %s", path.name)
            continue
        text = re.sub(r"\s+", " ", text).strip()
        for n, start in enumerate(range(0, len(text), chunk_chars - overlap)):
            piece = text[start:start + chunk_chars]
            if len(piece) > 80:
                docs.append(Doc(id=f"{path.stem}-{n}", text=f"[{path.name}] {piece}", source=path.name))
    return docs


def all_docs() -> list[Doc]:
    docs = [Doc(id=s.id, text=s.as_text() + f"\nOfficial link: {s.url}", scheme_id=s.id,
                title=f"{s.name} {s.name_hi or ''}") for s in load_schemes()]
    return docs + pdf_chunks()


class Retriever:
    def __init__(self) -> None:
        self.docs = all_docs()
        self.by_id = {d.id: d for d in self.docs}
        self.bm25 = BM25Okapi([tokenize(d.title) * 3 + tokenize(d.text) for d in self.docs])
        self.collection = self._open_chroma()

    def _open_chroma(self):
        settings = get_settings()
        if settings.vector_search == "off" or not settings.chroma_dir.exists():
            return None
        try:
            import chromadb

            collection = chromadb.PersistentClient(path=str(settings.chroma_dir)).get_collection(COLLECTION)
            if collection.count() == 0:
                return None
            log.info("Vector index loaded (%d chunks)", collection.count())
            return collection
        except Exception as exc:  # missing index or chromadb not installed: BM25 still works
            log.warning("Vector search unavailable, using BM25 only: %s", exc)
            return None

    def search(self, query: str, k: int = 4) -> list[tuple[Doc, float]]:
        """Top-k documents with a 0..1 confidence score for the best keyword match."""
        tokens = tokenize(query, query=True)
        if not tokens:
            return []
        scores = self.bm25.get_scores(tokens)
        keyword = [i for i in sorted(range(len(scores)), key=lambda i: -scores[i]) if scores[i] > 0][:k * 2]
        fused: dict[str, float] = {}
        for rank, i in enumerate(keyword):
            fused[self.docs[i].id] = fused.get(self.docs[i].id, 0) + 1 / (60 + rank)
        if self.collection is not None:
            try:
                dense = self.collection.query(query_texts=[query], n_results=k * 2)["ids"][0]
                for rank, doc_id in enumerate(dense):
                    if doc_id in self.by_id:
                        fused[doc_id] = fused.get(doc_id, 0) + 1 / (60 + rank)
            except Exception:
                log.exception("Vector query failed; continuing with BM25 results")
        top = sorted(fused, key=fused.get, reverse=True)[:k]
        # Share of query words found in the document: a cheap "did we really find it" signal.
        out = []
        for doc_id in top:
            words = set(tokenize(self.by_id[doc_id].text))
            out.append((self.by_id[doc_id], sum(t in words for t in tokens) / len(tokens)))
        return out


@lru_cache
def get_retriever() -> Retriever:
    return Retriever()
