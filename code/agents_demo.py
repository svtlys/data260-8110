import json
from langchain_ollama import ChatOllama
 
MODEL_NAME = "qwen3:8b"
TEMPERATURE = 0.7
 
llm = ChatOllama(model=MODEL_NAME, temperature=TEMPERATURE)
 
 
def extract_json(text: str) -> dict:
    """
    Local LLMs sometimes wrap JSON in prose or markdown code fences.
    This pulls out the first {...} block and parses it.
    """
    text = text.strip()
    if text.startswith("```"):
        # strip ```json ... ``` or ``` ... ``` fences
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object found in model output:\n{text}")
    return json.loads(text[start:end + 1])
 
 
def planner(title: str, content: str) -> dict:
    prompt = f"""You are the Planner agent. Given a title and content, propose exactly 3
short topical tags and a one-sentence summary of at most 25 words.
Derive the tags and summary ONLY from the given title/content below -- do not
assume any fixed domain or use predetermined keyword lists.
 
Respond with ONLY a valid JSON object in this exact shape, nothing else:
{{"tags": ["tag1", "tag2", "tag3"], "summary": "..."}}
 
Title: {title}
Content: {content}
"""
    resp = llm.invoke(prompt)
    return extract_json(resp.content)
 
 
def reviewer(draft: dict, title: str, content: str) -> dict:
    prompt = f"""You are the Reviewer agent. Review the draft JSON below for accuracy and
relevance to the source title/content. If the tags or summary are inaccurate,
too generic, or exceed 25 words, fix them. Otherwise keep them as-is.
 
Respond with ONLY a valid JSON object in this exact shape, nothing else:
{{"tags": ["tag1", "tag2", "tag3"], "summary": "..."}}
 
Draft: {json.dumps(draft)}
Title: {title}
Content: {content}
"""
    resp = llm.invoke(prompt)
    return extract_json(resp.content)
 
 
def finalize(reviewed: dict) -> dict:
    """Hard validation before publishing -- fail loudly if the contract is broken."""
    tags = reviewed.get("tags", [])
    summary = reviewed.get("summary", "")
 
    if len(tags) != 3:
        raise ValueError(f"Expected exactly 3 tags, got {len(tags)}: {tags}")
    if len(summary.split()) > 25:
        raise ValueError(f"Summary exceeds 25 words ({len(summary.split())}): {summary}")
 
    return {"tags": tags, "summary": summary}
 
 
if __name__ == "__main__":
    # Sample rental-listing input (domain: Rental Housing Listings, DOMAIN_ID 6)
    title = "Spacious 2BR Near Downtown San Jose"
    content = (
        "Bright 2-bedroom, 1-bath apartment close to light rail, updated kitchen, "
        "in-unit laundry, available October 1st, pet-friendly with deposit. "
        "Walking distance to shops and restaurants, off-street parking included."
    )
 
    print("=== INPUT ===")
    print(f"Title: {title}")
    print(f"Content: {content}\n")
 
    print("=== PLANNER OUTPUT ===")
    draft = planner(title, content)
    print(json.dumps(draft, indent=2))
 
    print("\n=== REVIEWER OUTPUT ===")
    reviewed = reviewer(draft, title, content)
    print(json.dumps(reviewed, indent=2))
 
    print("\n=== FINALIZED / PUBLISH OUTPUT ===")
    final = finalize(reviewed)
    print(json.dumps(final, indent=2))