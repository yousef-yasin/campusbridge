-- CampusBridge lecture assistant: vector store tables for PostgreSQL + pgvector (production).
-- The vector size must match the embedding model's output (ASSISTANT_EMBEDDING_DIMENSIONS, 768).
-- Not used yet: development and tests use the local JSON store.

CREATE EXTENSION IF NOT EXISTS vector;

-- One row: the embedding model and size of every vector in assistant_chunks.
CREATE TABLE IF NOT EXISTS assistant_index_info (
    id          integer PRIMARY KEY CHECK (id = 1),
    model       text    NOT NULL,          -- e.g. gemini-embedding-2
    dimensions  integer NOT NULL           -- e.g. 768
);

CREATE TABLE IF NOT EXISTS assistant_chunks (
    id          text PRIMARY KEY,          -- <file key>-<unit>-<part>
    course      text NOT NULL,             -- course id: search is limited to the student's courses
    file        text NOT NULL,             -- file name or lecture id
    unit        integer NOT NULL,          -- page / slide / sheet / transcript part
    unit_type   text NOT NULL,             -- page, slide, sheet, part
    language    text NOT NULL,             -- ar, en, mixed
    data        jsonb NOT NULL,            -- the whole chunk: title, blocks, sources, ...
    embedding   vector(768),               -- NULL when the embedding failed (keyword search only)
    indexed_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS assistant_chunks_course ON assistant_chunks (course, file);
-- Approximate nearest neighbours by cosine distance (the <=> operator).
CREATE INDEX IF NOT EXISTS assistant_chunks_embedding ON assistant_chunks
    USING hnsw (embedding vector_cosine_ops);
