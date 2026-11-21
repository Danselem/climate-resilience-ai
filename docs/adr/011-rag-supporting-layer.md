# ADR-011 — RAG as a supporting layer: pgvector, local embeddings, one licence exclusion

**Status:** accepted

## Context

The platform has two questions to answer about the same place: *what do the
data show*, and *what do the plans say*. The first is answered by a precomputed
mart (ADR-001) where every value is exact and reproducible. The second cannot
be: a planner's question about the Climate Action Plan has no SQL key.

The direction of travel: RAG is a supporting component, not the analytical
engine. Measurements stay in the mart; prose goes in a vector index.

Three decisions were forced before any code was written.

**1. Documents are inputs, and some cannot be ingested.** GreenBook is
CC BY-NC-SA 3.0 ZA — NonCommercial and ShareAlike. A commercial derived index
would breach it, and ShareAlike would propagate. It is recorded as `excluded`
in `data/catalogue/documents.json` and is never indexed.

**2. Most municipal plans are city-wide.** The Durban Climate Action Plan
contains no ward-level text at all: all 156 extracted chunks are municipal.
A retrieval layer that silently answers "what does the plan say about ward 75"
with a city-wide sentence has fabricated locality.

**3. The two stores answer different questions and must not be merged.** A
nearest-neighbour hit is a similarity judgement; a mart row is a calculation.
Putting them in one table would let the first pass as the second.

## Decision

- **Two stores, one direction of travel.** The mart (`data/mart.db`, SQLite
  locally, Postgres in deployment) holds measurements. The document index
  (pgvector) holds prose. A tool may read either, but no number is ever derived
  from retrieved text.
- **pgvector, not Qdrant.** Qdrant has no managed AWS offering: it would be a
  second stateful service on ECS with its own backup and scaling story, or a
  vendor outside the fixed AWS list. pgvector runs inside the Postgres already
  required for PostGIS. Neither upstream image ships both extensions, so
  `docker/db/Dockerfile` builds one; PostGIS 3.7 and pgvector 0.8.7 are
  verified in the running container.
- **Local embeddings.** `bge-base-en-v1.5`, 768 dimensions, normalised, with
  the retrieval instruction prefix on queries. No per-query cost and document
  text never leaves the machine. The trade is a `torch` dependency and a model
  download, which is stated rather than hidden. `HashingEmbedder` exists for
  offline tests and is never used to measure retrieval quality. (Originally
  `all-MiniLM-L6-v2`; see the amendment below, which explains why the 256-token
  window was a defect rather than a preference.)
- **Docling, with `HybridChunker`.** Municipal plans put targets, budgets and
  ward lists in tables; a flat text split loses them. Headings and page numbers
  travel with every chunk so a citation can name its section.
- **Scope is per chunk.** `municipality` by default; `ward` only when the text
  names wards. Scope filtering admits municipal text alongside the requested
  ward and excludes other wards, and every hit carries its own scope so the
  caller can say which it is.
- **Hybrid retrieval, fused by rank.** Dense cosine for paraphrase, Postgres
  full-text for identifiers ("RCP8.5", a ward number), combined by reciprocal
  rank fusion. A learned weight is not justifiable with ten documents; the
  fusion weight is measured instead (see the amendment). A reranker is deferred
  until retrieval evaluation shows it is needed.
- **Evaluation splits the two halves.** Retrieval metrics (Recall@k, MRR,
  nDCG) apply only to the document index; analytical correctness applies only
  to the mart. Reporting one number for both would hide which half failed.

## Consequences

- The Durban CAP (6.1 MB) produced 156 chunks in about 6 minutes on a laptop
  CPU: Docling layout analysis and OCR dominate, not embedding. That is
  acceptable for a batch ingest of ten documents and unacceptable at query
  time, which is why retrieval reads a prebuilt index.
- A ward-scoped question about the CAP returns municipal text and says so.
  That is the honest answer, and the benchmark must score it as such rather
  than as a retrieval miss.
- The RAG path requires Docker (Postgres). `make data` does not: the mart stays
  SQLite-portable.
- One document is indexed. Retrieval quality is now measured against that one
  document and cannot be generalised to a corpus of ten.

## Amended: retrieval is measured against labelled passages

Recall@5, Recall@10, MRR and nDCG@5 need ground truth, so 23 questions were
labelled against the 156-chunk corpus: 99 passage judgements, written from the
document text before any retrieval was run. `eval-assistant` now reports
retrieval beside answer quality and never blends them.

Measured on the Durban CAP, hybrid dense+BM25 with RRF:

| Metric | Value | Reading |
|---|---|---|
| Recall@5 | 0.503 | half the answering passages are missing from the top five |
| Recall@10 | 0.712 | widening to ten recovers 21 points |
| MRR | 0.777 | when a relevant passage is found, it is usually first |
| nDCG@5 | 0.54 | ranking is mediocre when several passages matter |

The weakest questions were `cap-drought` (0.0) and `cap-targets` (0.0), both of
which have few relevant passages buried below position five, and
`cap-prioritisation` (0.168), whose content is a multi-row table that chunks
badly. After the amendments below the weakest are `cap-sea-level` (0.131),
`cap-city-profile` (0.151) and `cap-biodiversity` (0.339).

Consequences:

- **No reranker yet.** The metrics identify the failure modes — repeated section
  headings, near-duplicate "Now and the future" sections, and long action
  tables — as chunking and labelling problems more than ranking problems. A
  reranker would be a measured decision, and the measurement says the corpus is
  the binding constraint.
- **The document items in the answer set are weaker than they look.** They pass
  when the right document is cited, which Recall@5 0.50 shows is not the same as
  the right passage being available to answer from.
- **The labels are single-annotator and conservative.** Binary relevance, and
  only passages that clearly answer the question are labelled, so Recall is a
  lower bound. An independent second annotator is the honest next step, not a
  larger question set.

## Amended: the embedding window, the lexical query and the fusion weight

Three defects sat behind the first retrieval measurement. All were configuration,
not the choice of architecture.

**1. The chunks did not fit the model.** Chunking was set to 512 tokens and the
embedder read 256, so 56 of 156 chunks (36%) were embedded with an average of
141 tokens — more than half the chunk — silently truncated. The second half of a
section, where its conclusion usually sits, was never in the vector.

The fix was to change the model rather than the chunks: `bge-base-en-v1.5` has a
512-token window, so existing chunks became valid, and because `chunk_id` is a
hash of the text, **the 99 relevance labels survived**. Re-chunking would have
invalidated them. Dense retrieval on the same labels:

| Model | Window | R@5 | R@10 | MRR | nDCG@5 |
|---|---|---|---|---|---|
| all-MiniLM-L6-v2 | 256 | 0.525 | 0.712 | 0.811 | 0.567 |
| bge-small-en-v1.5 | 512 | 0.557 | 0.695 | 0.822 | 0.588 |
| **bge-base-en-v1.5** | 512 | **0.585** | 0.705 | **0.913** | **0.647** |

Seven chunks still exceed 512 tokens by up to two, because the chunker
tokenizes with a different model. That is 2 tokens against 141.

**2. The lexical query asked for a conjunction.** `plainto_tsquery` ANDs every
surviving term, so "what does the plan say about sea level rise" became
`plan & sea & level & rise` and matched almost nothing (Recall@5 0.047). It also
indexed `text` while 136 chunks carry words that appear only in their headings.
Content words are now OR-ed into `to_tsquery` and headings are indexed. Lexical
Recall@5: 0.047 → 0.383.

**3. Equal weight was expensive.** With a working lexical arm, sweeping the
weight showed RRF had been diluting a much better dense ranking:

| Lexical weight | R@5 | R@10 | MRR | nDCG@5 |
|---|---|---|---|---|
| 0.0 (dense only) | 0.585 | 0.705 | 0.913 | 0.647 |
| 1.0 | 0.502 | 0.678 | 0.737 | 0.525 |
| 0.4 | 0.531 | 0.678 | 0.782 | 0.565 |
| 0.2 | 0.551 | 0.716 | 0.881 | 0.607 |
| **0.1** | 0.570 | **0.734** | 0.887 | 0.620 |

At 0.1 the lexical arm is a wash on ranking against dense-only and adds three
points at Recall@10, so it keeps its place at a weight that reflects its
measured strength rather than an assumption of parity.

**Result: Recall@5 0.503 → 0.570, MRR 0.777 → 0.887, nDCG@5 0.540 → 0.620,
Recall@10 0.712 → 0.734.** Answers stayed at 48/48.

Caveat that belongs here: the weight was chosen on the same 23 questions it is
reported against, so those numbers are optimistic. The direction of the effect
(equal weighting was harmful) is not in doubt; the exact optimum is.

Two related defects were fixed in the same pass, neither of them retrieval
quality:

- **Deactivated documents stayed retrievable.** Ingest replaced the documents it
  was given and never removed one dropped from the catalogue. Ingest now deletes
  chunks of inactive documents. (Version mixing was already handled:
  `replace_document` deletes by document id, so two versions cannot coexist.)
- **`replace_document` deleted by its argument but inserted each chunk's own
  document id.** A caller passing inconsistent objects would have deleted the
  old rows and written replacements under a different document. It now refuses
  and writes the argument.

## Revisit triggers

- The corpus passes ~50,000 chunks: HNSW parameters and fusion weights need
  measuring, and a reranker may earn its latency.
- CSIR grants written permission: GreenBook can be ingested and the exclusion
  reversed, with the licence text updated first.
- A multilingual need appears (isiZulu): swap the embedding model and bump the
  index version, rather than mixing models in one index.
- Ward-level planning documents appear: the municipal default stops being the
  common case and scope extraction should be reviewed.
