# Yojana Saathi · योजना साथी

A multilingual assistant that tells people in India which government schemes,
scholarships and subsidies they can claim. Describe yourself by text or voice in
Hindi, English or another Indian language:

> I'm a farmer in UP with 2 acres and a daughter in Class 10

and it lists the schemes you qualify for (including ones for your children), why,
what each pays, the documents to carry and the official link. It then asks for the
one or two missing facts that would unlock more schemes. Works on a web page and
on WhatsApp.

## How it works

```
 text / voice note
        │  Whisper (speech → text)
        ▼
 ┌─────────────┐   described themself   ┌────────┐   ┌──────────┐
 │ understand  │ ─────────────────────► │ match  │ ► │ compose  │ ► reply
 │ Claude, or  │                        │ rules  │   │ Claude / │
 │ rule-based  │   asked about a scheme ├────────┤   │ template │
 │ fallback    │ ─────────────────────► │retrieve│ ► │ answer   │ ► reply
 └─────────────┘   greeting / reset     └────────┘   └──────────┘
   LangGraph state machine (app/graph.py)
```

- **Understanding** (`app/llm.py`): Claude turns a message in any language into a
  typed profile (age, state, occupation, income, land, children…) using structured
  outputs. Profiles accumulate across turns in SQLite.
- **Eligibility** (`app/rules.py`): a deterministic engine checks the profile
  against structured rules for each scheme. The LLM never decides eligibility, so
  every match is explainable and unit-tested. Each rule is met, not met, or
  *unknown*; unknowns produce "possible" matches and drive the follow-up question.
- **Retrieval** (`app/retriever.py`): hybrid BM25 + Chroma vectors with reciprocal
  rank fusion over the scheme catalogue and any PDFs in `data/pdfs/`, used to
  answer questions such as "PM Kisan ke liye kya documents chahiye?".
- **Reply** (`app/respond.py`, `app/llm.py`): Claude rewrites the matched facts in
  the user's language and is instructed to use only the facts it is given.
- **Offline mode**: with no API key the same graph runs on a rule-based
  English/Hindi/Hinglish extractor and templates, which is what the tests use.

## Run it locally

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows   (Linux/macOS: source .venv/bin/activate)
pip install -r requirements-dev.txt
copy .env.example .env            # then add your keys (all optional)
python -m scripts.ingest          # build the vector index (downloads an 80 MB model once)
uvicorn app.main:app --reload
```

Open http://localhost:8000. Without keys you get offline mode; add keys to `.env`
to switch features on:

| Feature | Key | Notes |
|---|---|---|
| Any-language understanding and replies | `ANTHROPIC_API_KEY` | Model set by `ANTHROPIC_MODEL` (default `claude-opus-5-5`; `claude-haiku-5-5` is far cheaper for high volume) |
| Voice input | `GROQ_API_KEY` (or `OPENAI_API_KEY`) | Whisper large-v3. Or `pip install faster-whisper` and `STT_PROVIDER=local` |
| WhatsApp | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` | See below |

## Tests and accuracy

```bash
pytest -q                          # 44 tests: rules, extraction, API, WhatsApp webhook
ruff check .                       # lint
python -m scripts.evaluate         # accuracy, offline extractor
python -m scripts.evaluate --mode llm --verbose   # accuracy with Claude (uses credits)
```

`eval/testset.json` holds 32 hand-written personas (English, Hindi, Hinglish, plus
Marathi, Bengali, Tamil and Telugu for LLM mode), each with a gold profile and
hand-labelled schemes that must and must not be returned.

Offline (rule-based) extractor on the 28 English/Hindi/Hinglish personas, 73 schemes:

| Metric | Result |
|---|---|
| Hand-labelled include/exclude checks | 92 / 95 (96.8%) |
| Scheme match vs. gold profile (F1) | 98.4% |
| Personas with every scheme right | 26 / 28 (92.9%) |
| Profile field accuracy | 97.6% |

These are development-set numbers: the extractor was debugged against this same
set, so expect lower on unseen phrasing. Add your own personas before quoting a
figure, and run `--mode llm` for the number that reflects the deployed system.

## WhatsApp setup (Twilio sandbox)

1. Create a Twilio account and open **Messaging → Try it out → Send a WhatsApp message**.
2. Join the sandbox from your phone by sending the join code to the sandbox number.
3. Deploy the app (below) and set **When a message comes in** to
   `https://<your-domain>/webhooks/whatsapp` (HTTP POST).
4. Set `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` and `PUBLIC_BASE_URL=https://<your-domain>`.

The webhook verifies Twilio's signature, acknowledges immediately and replies
through the REST API in the background (Twilio only waits 15 seconds). Voice
notes are downloaded, transcribed and handled like text. Send `reset` to delete
your stored profile. For a real number instead of the sandbox you need a WhatsApp
Business sender approved by Meta.

## Deploy

**Render** (simplest): push this repo to GitHub, then in Render choose
**New → Blueprint** and select the repo. `render.yaml` builds the Dockerfile and
asks for the secrets. Add a persistent disk mounted at `/data` if you want
conversations to survive restarts.

**Any Docker host**:

```bash
docker compose up --build -d
```

The image bakes in the vector index, runs as a non-root user and exposes `/health`.

## Adding schemes

Add an entry to `data/schemes/*.json`. Supported rule keys: `occupation`, `gender`,
`min_age`, `max_age`, `max_income`, `caste`, `residence`, `bpl`, `owns_land`,
`max_land_acres`, `is_student`, `education`, `marital`, `no_pucca_house`,
`disability`, `widow`, `pregnant`, `minority`, `exclude` and `any_of`. Then re-run
`python -m scripts.ingest` and add a persona to `eval/testset.json`. Drop official
PDFs into `data/pdfs/` to make their text searchable.

## Safeguards and limits

- **Scheme data must be verified.** The 73 entries were written from general
  knowledge of each scheme, not scraped from official sources. Amounts, income
  ceilings and dates change; check every entry against the linked portal (or
  myscheme.gov.in) before real users rely on it. Every reply tells users to
  confirm on the official site.
- Profiles contain sensitive data (caste, income, disability). Phone numbers are
  stored only as a keyed hash, sessions expire after 30 days, message text is
  never logged and users can delete their data. Set `SESSION_SECRET`.
- The API is rate-limited per IP in memory, which is right for a single
  instance; use Redis or a gateway if you scale out. SQLite likewise.
- Offline mode understands English, Hindi and Hinglish only and shows scheme
  details in English. Other languages need the Claude key.
- Rules capture the main eligibility conditions, not every clause (for example
  merit cut-offs or "one LPG connection per household" appear as notes).
