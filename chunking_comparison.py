import json
import time
from pathlib import Path

import numpy as np
import yaml
from llama_index.core import Document, Settings, VectorStoreIndex
from llama_index.core.node_parser import (
    SemanticSplitterNodeParser,
    SentenceWindowNodeParser,
    TokenTextSplitter,
)
from llama_index.embeddings.huggingface import HuggingFaceEmbedding

ROOT = Path(__file__).resolve().parent
CORPUS_DIR = ROOT / "corpus"
QUESTIONS_PATH = ROOT / "reports/hw03/cases/questions.yaml"
RAW_DIR = ROOT / "reports/hw03/raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

TOP_K = 3
EXCLUDE_FILES = {"tiny_shakespeare.txt"}  # warm-up file, not part of the real corpus


embed_model = HuggingFaceEmbedding(model_name="sentence-transformers/all-MiniLM-L6-v2")
Settings.embed_model = embed_model


def load_corpus_documents():
    """Loads every .txt in corpus/ (except the warm-up file) as a Document,
    tagging each with its source filename in metadata."""
    documents = []
    for filepath in sorted(CORPUS_DIR.glob("*.txt")):
        if filepath.name in EXCLUDE_FILES:
            continue
        text = filepath.read_text(errors="ignore")
        documents.append(Document(text=text, metadata={"source_file": filepath.name}))
    return documents


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def build_token_index(documents):
    splitter = TokenTextSplitter(chunk_size=256, chunk_overlap=20)
    nodes = splitter.get_nodes_from_documents(documents)
    index = VectorStoreIndex(nodes)
    return index, nodes


def build_semantic_index(documents):
    splitter = SemanticSplitterNodeParser(
        buffer_size=1, breakpoint_percentile_threshold=95, embed_model=embed_model
    )
    nodes = splitter.get_nodes_from_documents(documents)
    index = VectorStoreIndex(nodes)
    return index, nodes


def build_sentence_window_index(documents):
    splitter = SentenceWindowNodeParser.from_defaults(
        window_size=3,
        window_metadata_key="window",
        original_text_metadata_key="original_text",
    )
    nodes = splitter.get_nodes_from_documents(documents)
    index = VectorStoreIndex(nodes)
    return index, nodes


def retrieve_and_analyze(technique_name, index, query, k=TOP_K):
    """
    Runs retrieval for one query against one technique's index, computing
    cosine similarity explicitly (not just relying on the store's own score),
    and returns a structured result plus prints the required table.
    """
    t0 = time.time()
    retriever = index.as_retriever(similarity_top_k=k)
    results = retriever.retrieve(query)
    latency_ms = (time.time() - t0) * 1000

    query_embedding = np.array(embed_model.get_query_embedding(query))

    print(f"\n=== Technique: {technique_name} | Query: {query!r} ===")
    print(f"Query embedding dim: {query_embedding.shape[0]}")
    print(f"Query embedding first 8 values: {query_embedding[:8].tolist()}")

    doc_embeddings = []
    rows = []
    print(f"\n{'rank':<5}{'store_score':<14}{'cosine_sim':<12}{'chunk_len':<11}preview")
    for rank, node in enumerate(results, start=1):
        chunk_text = node.text
        doc_embedding = np.array(embed_model.get_text_embedding(chunk_text))
        doc_embeddings.append(doc_embedding)

        cos_sim = cosine_similarity(query_embedding, doc_embedding)
        store_score = float(node.score) if node.score is not None else None
        chunk_len = len(chunk_text)
        preview = chunk_text[:160].replace("\n", " ")

        print(f"{rank:<5}{store_score:<14.4f}{cos_sim:<12.4f}{chunk_len:<11}{preview}")

        rows.append({
            "technique": technique_name,
            "query": query,
            "rank": rank,
            "store_score": store_score,
            "cosine_sim": cos_sim,
            "chunk_len": chunk_len,
            "preview": preview,
            "source_file": node.metadata.get("source_file", "unknown"),
            "latency_ms": latency_ms,
        })

    if doc_embeddings:
        doc_matrix = np.stack(doc_embeddings)
        print(f"\nQuery vector shape: {query_embedding.shape}")
        print(f"Stacked doc vectors shape: {doc_matrix.shape}")

    return rows


if __name__ == "__main__":
    print("Loading corpus...")
    documents = load_corpus_documents()
    print(f"Loaded {len(documents)} documents: {[d.metadata['source_file'] for d in documents]}")

    with open(QUESTIONS_PATH) as f:
        questions_data = yaml.safe_load(f)
    questions = [q["question"] for q in questions_data["questions"]]

    print("\nBuilding Token-based index...")
    token_index, token_nodes = build_token_index(documents)
    print(f"Token chunking produced {len(token_nodes)} chunks.")

    print("\nBuilding Semantic index...")
    semantic_index, semantic_nodes = build_semantic_index(documents)
    print(f"Semantic chunking produced {len(semantic_nodes)} chunks.")

    print("\nBuilding Sentence-window index...")
    sw_index, sw_nodes = build_sentence_window_index(documents)
    print(f"Sentence-window chunking produced {len(sw_nodes)} chunks.")

    all_rows = []
    chunk_counts = {"Token": len(token_nodes), "Semantic": len(semantic_nodes), "SentenceWindow": len(sw_nodes)}
    chunk_lengths = {
        "Token": [len(n.text) for n in token_nodes],
        "Semantic": [len(n.text) for n in semantic_nodes],
        "SentenceWindow": [len(n.text) for n in sw_nodes],
    }

    for question in questions:
        all_rows.extend(retrieve_and_analyze("Token", token_index, question))
        all_rows.extend(retrieve_and_analyze("Semantic", semantic_index, question))
        all_rows.extend(retrieve_and_analyze("SentenceWindow", sw_index, question))

    # Save raw results
    json_path = RAW_DIR / "chunking_comparison_results.json"
    with open(json_path, "w") as f:
        json.dump(all_rows, f, indent=2)

    import csv
    csv_path = RAW_DIR / "chunking_comparison_results.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
        writer.writeheader()
        writer.writerows(all_rows)


    stats_path = RAW_DIR / "chunk_stats.json"
    with open(stats_path, "w") as f:
        json.dump({
            "chunk_counts": chunk_counts,
            "avg_chunk_length": {k: sum(v) / len(v) for k, v in chunk_lengths.items()},
        }, f, indent=2)

    print(f"\nRaw results saved to {json_path} and {csv_path}")
    print(f"Chunk stats saved to {stats_path}")
    print("\nChunk counts:", chunk_counts)
    print("Avg chunk lengths:", {k: round(sum(v) / len(v), 1) for k, v in chunk_lengths.items()})