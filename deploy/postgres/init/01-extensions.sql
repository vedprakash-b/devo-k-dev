-- Runs once, when the postgres-data volume is first created.
-- pgvector stores embeddings for episodic memory and document RAG (M6).
CREATE EXTENSION IF NOT EXISTS vector;
