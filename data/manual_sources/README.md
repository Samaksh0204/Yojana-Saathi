# Official documents saved by hand

Put scheme guidelines, circulars or pages you downloaded yourself from an
official government site here (PDF, HTML or plain text), then list each one in
`manifest.json` with the address it came from:

```json
[
  {"file": "pm-kisan-guidelines.pdf", "url": "https://pmkisan.gov.in/...", "saved_on": "2026-11-11"}
]
```

The URL must be https on an official domain (`gov.in`, `nic.in`). Then run:

    python -m scripts.ingest_sources --source manual
    python -m scripts.review list

This is the route for sites whose terms do not allow automated access (see
`scripts/ingest_sources/sources.json`): a person may read and save the page,
and the pipeline works from the saved copy.
