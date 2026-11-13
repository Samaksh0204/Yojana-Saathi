# Architecture and design decisions

## The request path

```
message (text or voice note)
   │  app/speech.py      Whisper turns audio into text
   ▼
understand               app/graph.py → app/llm.py or app/extract.py
   │  free text → UserProfile (age, state, work, income, land, children…)
   │  merged with what earlier turns already established (SQLite, app/sessions.py)
   ▼
route on intent
   ├─ eligibility ──► match    app/rules.py     profile × 73 rule sets → eligible / possible
   │                  compose  app/respond.py   cards + text; Claude rewrites if available
   ├─ scheme question ──► retrieve  app/retriever.py  BM25 + vectors, fused
   │                      answer    grounded in the retrieved scheme text
   ├─ greeting ──► welcome
   └─ reset ──► delete the stored profile
```

The graph is a LangGraph state machine (`app/graph.py`). The same `run_agent()`
function serves the web API, the WhatsApp webhook and the terminal chat.

## Decisions and their trade-offs

### 1. Rules decide, the model translates

Eligibility is computed by `app/rules.py` from structured rules in
`data/schemes/*.json`. The model's only jobs are extraction (text → profile) and
rewriting (facts → the user's language).

- **Why:** an LLM asked "is this person eligible?" will sometimes be confidently
  wrong, cannot show its working, and changes its answer between runs. Rules are
  deterministic, unit-tested and reviewable by someone who knows the scheme.
- **Cost:** every scheme has to be encoded by hand, and conditions that do not
  fit a rule key (merit cut-offs, "one LPG connection per household") are carried
  as notes rather than enforced.

### 2. Three-valued rules

Each rule evaluates to met, not met or unknown (`_check` returns `True`, `False`
or `None`). A scheme is *eligible* when nothing is unknown, *possible* when at
most two facts are missing, and dropped otherwise.

- **Why:** people give partial information. Treating unknown as "no" hides
  schemes; treating it as "yes" over-promises. Unknowns also tell the agent which
  question is worth asking next (`follow_up_fields` picks the facts that would
  settle the most schemes).
- **Detail worth knowing:** a few facts default to "no" when unmentioned
  (disability, widowhood, pregnancy, minority community), because people state
  these when they apply. A "possible" match that hinges on occupation is used to
  choose a question but not shown, since it is a guess.

### 3. Family members as candidates

Many schemes are claimed on a child's behalf. The engine evaluates each scheme
against the user and against each child (who inherits household facts such as
state, income and caste), and labels the result "for your daughter".

### 4. Never trust model output

`app/llm.py` asks for JSON and validates it with Pydantic. Invalid output gets
one corrective retry that names the failing fields without echoing their values;
after that the offline extractor takes over. Extra keys a model might invent,
such as a list of "eligible schemes", are not part of the schema and are ignored.

### 5. An offline mode that is a real mode

`app/extract.py` is a rule-based extractor for English, Hindi and Hinglish.

- **Why:** the app keeps working through an outage or with no key, the test
  suite needs no network or credits, and it gives a baseline to compare the
  model against.
- **Cost:** it is regex-based and brittle on unseen phrasing. Its accuracy
  figures are development-set numbers.

### 6. Hybrid retrieval

Scheme questions use BM25 and Chroma vectors fused with reciprocal rank fusion
(`app/retriever.py`). Scheme names are weighted up in the keyword index.

- **Why:** people ask by name ("PM Kisan"), where keyword search is exact, and
  by need ("money for cooking gas"), where vectors help.
- **Honest scope:** with 73 short records this is more machinery than the data
  needs today. It earns its place once PDFs are ingested.

### 7. Ingestion with a human gate

`scripts/ingest_sources/` fetches only where a site's terms allow it, respects
robots.txt, and limits itself to one request per second. Every extracted rule
must come with a sentence found word for word in the source. Proposals wait in
`storage/proposals/` until `scripts/review.py approve` merges them.

- **Why:** this is the path by which wrong facts would enter the catalogue, and
  source text is untrusted (it may contain instructions aimed at the model).
- **Constraint found along the way:** myScheme's terms prohibit bots, so the
  pipeline ships with that source disabled and a manual-download route instead.

### 8. Privacy by default

Profiles include caste, income and disability. Phone numbers are stored only as
a keyed hash, sessions expire after 30 days, message text is never logged, and
users can delete their data from the web page or by sending `reset`.

## What would change at scale

- SQLite and the in-memory rate limiter assume one process. Several instances
  need Postgres or Redis.
- The catalogue is English. Scheme text in each language should be stored, not
  translated on every reply.
- Rule coverage should be measured against official text: `eval/extraction_gold/`
  exists for that and is still empty.
- Claude-mode accuracy has not been measured. The persona set in `eval/` and
  `scripts/evaluate.py --mode llm` are ready for it.
