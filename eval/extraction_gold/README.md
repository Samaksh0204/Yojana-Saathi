# Extraction gold set

Hand-checked answers for measuring the ingestion extractor. **A person fills
these in from the official text. Do not generate them with a model** - that
would only measure whether the model agrees with itself.

The ten `*.json` files here are empty stubs. For each one:

1. Open the official page or PDF at `source_url` in your browser.
2. Save its text as `sources/<scheme_id>.txt` (or `.pdf` / `.html`) and make sure
   `source_file` points at it.
3. Fill in `expected` from what the document says:
   - `amounts`: every rupee amount of the benefit, as whole rupees (`[6000, 2000]`)
   - `min_age`, `max_age`: whole years, or `null` if the document sets none
   - `max_income`: annual family income ceiling in rupees, or `null`
     (a list if there are alternatives, e.g. `[250000, 200000]`)
   - `occupation`: values from the list in `scripts/ingest_sources/extract.py`
   - `documents`: the documents an applicant must provide
4. Set `verified_by` to your name and `verified_on` to the date.

Then run:

    python -m scripts.evaluate_extraction

Files without `verified_by`, or without their source file, are skipped and
counted as "not yet verified".
