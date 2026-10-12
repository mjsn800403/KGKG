"""Local, DB-grounded RAG + relationship-graph layer (content-deduplicated).

Identical manual content across the fleet is stored and embedded ONCE (a
"blob"); the vehicles/locations it appears in live in an `occurrences` table.
A single unified index (Database_warehouse/_rag/index.rag.db) holds blobs,
occurrences, chunks, int8 vectors, FTS, and a blob-level relationship graph
(semantic / crosslink / labor_time). "Same procedure across brand/model/type"
is just a blob's other occurrences -- exact and free.

The original car databases and db.sqlite3 are only ever opened read-only. Delete
the _rag/ folder to revert the system completely.
"""
