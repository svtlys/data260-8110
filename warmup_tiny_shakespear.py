import urllib.request
from pathlib import Path

from llama_index.core import VectorStoreIndex, Document
from llama_index.core.node_parser import TokenTextSplitter
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.core import Settings

DATA_URL = "https://raw.githubusercontent.com/karpathy/char-rnn/master/data/tinyshakespeare/input.txt"
LOCAL_PATH = Path(__file__).resolve().parent / "corpus" / "tiny_shakespeare.txt"

# Download if not already present
if not LOCAL_PATH.exists():
    print(f"Downloading Tiny Shakespeare to {LOCAL_PATH}...")
    urllib.request.urlretrieve(DATA_URL, LOCAL_PATH)

text = LOCAL_PATH.read_text()
print(f"Loaded {len(text)} characters.")


print("Loading embedding model (sentence-transformers/all-MiniLM-L6-v2)...")
embed_model = HuggingFaceEmbedding(model_name="sentence-transformers/all-MiniLM-L6-v2")
Settings.embed_model = embed_model


splitter = TokenTextSplitter(chunk_size=256, chunk_overlap=20)
document = Document(text=text)
nodes = splitter.get_nodes_from_documents([document])
print(f"Produced {len(nodes)} chunks.")


index = VectorStoreIndex(nodes)
print("Index built successfully.")


retriever = index.as_retriever(similarity_top_k=3)
query = "What does the king say about betrayal?"
results = retriever.retrieve(query)

print(f"\n=== Retrieval results for: '{query}' ===")
for i, node in enumerate(results):
    print(f"\nRank {i+1} | score={node.score:.4f}")
    print(f"Preview: {node.text[:160]!r}")

print("\nWarm-up complete -- LlamaIndex + embeddings are working.")