"""Build the Chroma vector index from data/schemes/*.json and data/pdfs/*.pdf.

    python -m scripts.ingest

The first run downloads Chroma's default embedding model (all-MiniLM-L6-v2, ~80 MB).
Re-run whenever scheme data or PDFs change.
"""
import shutil

import chromadb

from app.config import get_settings
from app.retriever import COLLECTION, all_docs


def main() -> None:
    settings = get_settings()
    docs = all_docs()
    if settings.chroma_dir.exists():
        shutil.rmtree(settings.chroma_dir)
    settings.chroma_dir.mkdir(parents=True)
    collection = chromadb.PersistentClient(path=str(settings.chroma_dir)).create_collection(COLLECTION)
    for start in range(0, len(docs), 64):
        batch = docs[start:start + 64]
        collection.add(ids=[d.id for d in batch], documents=[d.text for d in batch],
                       metadatas=[{"source": d.source, "scheme_id": d.scheme_id or ""} for d in batch])
    schemes = sum(1 for d in docs if d.scheme_id)
    print(f"Indexed {schemes} schemes and {len(docs) - schemes} PDF chunks into {settings.chroma_dir}")


if __name__ == "__main__":
    main()
