"""Offline ingestion: official source text -> LLM-extracted candidates -> human review.

Never imported by the chat app. Nothing here writes to data/schemes/; only
`python -m scripts.review approve <id>` does, after a person has looked at it.
"""
