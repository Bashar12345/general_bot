# Attribution Changes

## What changed

I added the answer attribution flow so the bot now returns traceable source evidence instead of only a plain answer.

### Indexing and metadata
- Chunked URL, PDF, and static FAQ content with per-chunk metadata.
- Stored `source_file`, `source_link`, `source_type`, `source_id`, `title`, `section_heading`, `page_number`, `char_start`, `char_end`, `chunk_index`, and `indexed_at` on each chunk.
- Split PDFs page-by-page so page numbers can be preserved in citations.
- Kept the existing index rebuild bookkeeping after rebuilding the vector store.

### Retrieval and answer formatting
- Numbered retrieved chunks so the LLM can reference them with inline markers like `[1]`.
- Updated the prompt to require citations for factual claims.
- Returned structured `citations` and `source_documents` alongside the answer.
- Added retrieval score and similarity metadata to each source payload.

### Excerpts and logging
- Added a short excerpt extractor so each citation includes a relevant passage preview.
- Logged cited attribution events to `attribution_events.jsonl` for later analytics or dashboarding.

### CLI output
- Updated the shell UI to print the cited sources and excerpts under each answer.

## Files changed
- `loader.py`
- `chain.py`
- `shell.py`

## Validation
- Parsed the edited Python files with `ast.parse` to confirm they are syntactically valid.
