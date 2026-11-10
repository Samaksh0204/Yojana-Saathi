Drop official scheme PDFs (guidelines, circulars, FAQs) here and run:

    python -m scripts.ingest

Each PDF is split into overlapping chunks and added to the search index, so the
assistant can answer detailed questions ("what is the last date?", "which form?")
from the source document. Eligibility matching itself uses the structured rules
in `data/schemes/*.json`.
