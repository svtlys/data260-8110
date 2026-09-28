import json
import sys
import time
from pathlib import Path

from llama_index.core import Document, Settings, VectorStoreIndex
from llama_index.core.node_parser import TokenTextSplitter
from llama_index.embeddings.huggingface import HuggingFaceEmbedding

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from model_client import ModelClient  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = ROOT / "corpus"
RAW_DIR = ROOT / "reports/hw04/raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
TOP_K_DEFAULT = 3
EXCLUDE_FILES = {"tiny_shakespeare.txt"}

embed_model = HuggingFaceEmbedding(model_name="sentence-transformers/all-MiniLM-L6-v2")
Settings.embed_model = embed_model


QUESTIONS = [
    {
        "id": "Q1",
        "kind": "single_chunk",
        "question": "What is the maximum allowable rent increase under San Jose's Apartment Rent Ordinance?",
        "expected_source": "sanjose_tpo.txt",
    },
    {
        "id": "Q2",
        "kind": "two_chunks",
        "question": "Under the Ellis Act process, how much notice must most tenant households receive, and what is the relocation assistance for a 2-bedroom unit?",
        "expected_source": "sanjose_tpo.txt",
    },
    {
        "id": "Q3",
        "kind": "cross_document_similar",
        "question": "What kinds of damage or cleaning can a landlord deduct from a security deposit in California?",
        "expected_source": "ca_security_deposits.txt",  # also appears in ca_tenants_guide.txt
    },
    {
        "id": "Q4",
        "kind": "ambiguous",
        "question": "Is my rental unit covered under rent control?",
        "expected_source": None,  # genuinely ambiguous -- depends on unspecified details
    },
    {
        "id": "Q5",
        "kind": "not_in_documents",
        "question": "What is the current 30-year fixed mortgage interest rate?",
        "expected_source": None,  # must be refused
    },
    {
        "id": "Q6",
        "kind": "unrelated",
        "question": "What is the capital of France?",
        "expected_source": None,  # must be refused
    },
]

GROUNDING_RULES = """You must follow these rules strictly:
- Answer ONLY using the information in the numbered context sources below.
- When you use information from a source, cite it like [1], [2], etc.
- If the context does not contain enough information to answer, respond with
  EXACTLY this sentence and nothing else: "I cannot answer this question from the provided documents."
"""


def load_corpus_documents():
    documents = []
    for filepath in sorted(CORPUS_DIR.glob("*.txt")):
        if filepath.name in EXCLUDE_FILES:
            continue
        text = filepath.read_text(errors="ignore")
        documents.append(Document(text=text, metadata={"source_file": filepath.name}))
    return documents


def build_index(documents):
    splitter = TokenTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
    nodes = splitter.get_nodes_from_documents(documents)
    for i, node in enumerate(nodes):
        node.metadata["chunk_id"] = i
    index = VectorStoreIndex(nodes)
    return index, nodes


def retrieve_chunks(index, query, k=TOP_K_DEFAULT, verbose=True):
    retriever = index.as_retriever(similarity_top_k=k)
    results = retriever.retrieve(query)

    if verbose:
        print(f"\n--- Retrieved top-{k} chunks for: {query!r} ---")
        for rank, node in enumerate(results, start=1):
            source = node.metadata.get("source_file", "unknown")
            chunk_id = node.metadata.get("chunk_id", "?")
            score = node.score if node.score is not None else 0.0
            preview = node.text[:160].replace("\n", " ")
            print(f"  [{rank}] source={source} chunk_id={chunk_id} score={score:.4f}")
            print(f"      preview: {preview}")

    return results


def dedupe_and_filter(nodes, query_embedding=None, min_score=0.35):
    """
    Context engineering step: drop duplicate/near-duplicate chunks (same
    source_file + chunk_id seen twice, or identical text) and drop chunks
    below a minimal relevance score.
    """
    seen_texts = set()
    filtered = []
    for node in nodes:
        text_key = node.text.strip()[:100]
        if text_key in seen_texts:
            continue
        if node.score is not None and node.score < min_score:
            continue
        seen_texts.add(text_key)
        filtered.append(node)
    return filtered


def build_basic_rag_prompt(question, nodes):
    context_block = "\n\n".join(node.text for node in nodes)
    return f"""Answer the question using the context below if it helps.

Context:
{context_block}

Question: {question}
"""


def build_context_engineered_prompt(question, nodes):
    filtered = dedupe_and_filter(nodes)
    labeled_sources = []
    for i, node in enumerate(filtered, start=1):
        source = node.metadata.get("source_file", "unknown")
        labeled_sources.append(f"[{i}] (source: {source})\n{node.text}")
    context_block = "\n\n".join(labeled_sources)

    return f"""{GROUNDING_RULES}

Context sources:
{context_block}

Question: {question}
"""


def run_no_rag(client, question):
    prompt = f"Answer this question directly: {question}"
    client.add_user_message(prompt)
    response = client.complete()
    return response.content


def run_basic_rag(client, question, nodes):
    prompt = build_basic_rag_prompt(question, nodes)
    client.add_user_message(prompt)
    response = client.complete()
    return response.content


def run_context_rag(client, question, nodes):
    prompt = build_context_engineered_prompt(question, nodes)
    client.add_user_message(prompt)
    response = client.complete()
    return response.content


if __name__ == "__main__":
    print("Loading corpus...")
    documents = load_corpus_documents()
    print(f"Loaded {len(documents)} documents: {[d.metadata['source_file'] for d in documents]}")

    print(f"\nChunking (chunk_size={CHUNK_SIZE}, chunk_overlap={CHUNK_OVERLAP}) and indexing...")
    index, nodes = build_index(documents)
    print(f"Produced {len(nodes)} chunks.")

    all_results = []

    print("\n" + "=" * 70)
    print("PART A: Three-configuration comparison across 6 questions")
    print("=" * 70)

    for q in QUESTIONS:
        print(f"\n\n### {q['id']} ({q['kind']}): {q['question']}")

        retrieved = retrieve_chunks(index, q["question"], k=TOP_K_DEFAULT)

        client_a = ModelClient(model="qwen3:8b", temperature=0.0)
        client_b = ModelClient(model="qwen3:8b", temperature=0.0)
        client_c = ModelClient(model="qwen3:8b", temperature=0.0)

        print(f"\n--- (A) No RAG ---")
        answer_a = run_no_rag(client_a, q["question"])
        print(answer_a)

        print(f"\n--- (B) Basic RAG (top-3 raw chunks) ---")
        answer_b = run_basic_rag(client_b, q["question"], retrieved)
        print(answer_b)

        print(f"\n--- (C) Context-engineered RAG ---")
        answer_c = run_context_rag(client_c, q["question"], retrieved)
        print(answer_c)

        all_results.append({
            "question_id": q["id"],
            "kind": q["kind"],
            "question": q["question"],
            "expected_source": q["expected_source"],
            "retrieved_sources": [n.metadata.get("source_file") for n in retrieved],
            "no_rag_answer": answer_a,
            "basic_rag_answer": answer_b,
            "context_rag_answer": answer_c,
        })

    print("\n\n" + "=" * 70)
    print("PART B: top_k sweep on Q1 (single-chunk question)")
    print("=" * 70)

    sweep_results = []
    for k in [1, 3, 5]:
        print(f"\n--- k={k} ---")
        retrieved_k = retrieve_chunks(index, QUESTIONS[0]["question"], k=k)
        client_k = ModelClient(model="qwen3:8b", temperature=0.0)
        answer_k = run_context_rag(client_k, QUESTIONS[0]["question"], retrieved_k)
        print(f"\nAnswer at k={k}:")
        print(answer_k)
        sweep_results.append({
            "k": k,
            "retrieved_sources": [n.metadata.get("source_file") for n in retrieved_k],
            "answer": answer_k,
        })

    # Save raw results
    with open(RAW_DIR / "rag_comparison_results.json", "w") as f:
        json.dump(all_results, f, indent=2)
    with open(RAW_DIR / "rag_topk_sweep_results.json", "w") as f:
        json.dump(sweep_results, f, indent=2)

    print(f"\n\nRaw results saved to {RAW_DIR}/rag_comparison_results.json and rag_topk_sweep_results.json")