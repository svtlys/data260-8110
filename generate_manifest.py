import hashlib
import json
from pathlib import Path

CORPUS_DIR = Path(__file__).resolve().parent / "corpus"
OUTPUT_PATH = Path(__file__).resolve().parent / "reports/hw03/CORPUS_MANIFEST.json"

manifest = []

for filepath in sorted(CORPUS_DIR.glob("*.txt")):
    data = filepath.read_bytes()
    sha256 = hashlib.sha256(data).hexdigest()
    manifest.append({
        "filename": filepath.name,
        "byte_size": len(data),
        "sha256": sha256,
    })
    print(f"{filepath.name}: {len(data)} bytes, sha256={sha256}")

OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
with open(OUTPUT_PATH, "w") as f:
    json.dump(manifest, f, indent=2)

total_bytes = sum(entry["byte_size"] for entry in manifest)
print(f"\nTotal corpus size: {total_bytes} bytes ({total_bytes / 1024:.1f} KB)")
print(f"Manifest written to {OUTPUT_PATH}")