# Strategy / metagame notes

Drop any `.md` or `.txt` files in this folder, then run:

    python -m backend.ingest --strategy

Each file is chunked (~1500 chars) and embedded into the `mtg_strategy` Chroma collection so the LLM can pull from it during answers. Typical things to put here:

- Archetype primers ("Esper Pixie in Standard", "Domain Ramp sideboard plan")
- Deck strategy guides
- Sideboard plans and matchup notes
- Tournament reports
- Errata or tournament-policy notes you want the model to know

Anything other than this README is gitignored by default, so private notes stay local.
