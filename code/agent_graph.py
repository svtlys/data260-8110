import json
import sys
from pathlib import Path
from typing import Any, Dict, TypedDict

from langgraph.graph import END, StateGraph

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from model_client import ModelClient  # noqa: E402


from pydantic import BaseModel, ValidationError, field_validator


class PlannerOutput(BaseModel):
    tags: list[str]
    summary: str

    @field_validator("tags")
    @classmethod
    def check_tags(cls, v):
        if len(v) != 3:
            raise ValueError(f"expected exactly 3 tags, got {len(v)}")
        for tag in v:
            if not (3 <= len(tag) <= 30):
                raise ValueError(f"tag '{tag}' must be 3-30 characters, got {len(tag)}")
        return v

    @field_validator("summary")
    @classmethod
    def check_summary(cls, v):
        word_count = len(v.split())
        if word_count > 25:
            raise ValueError(f"summary has {word_count} words, must be at most 25")
        return v



TURN_CEILING = 10  


class AgentState(TypedDict):
    title: str
    content: str
    email: str
    strict: bool
    task: str
    llm: Any
    planner_proposal: Dict[str, Any]
    reviewer_feedback: Dict[str, Any]
    turn_count: int
    validation_error: str
    validation_retries: int


def extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object found in model output:\n{text}")
    return json.loads(text[start:end + 1])


def planner_node(state: AgentState) -> Dict[str, Any]:
    print("--- NODE: Planner ---")
    client: ModelClient = state["llm"]

    feedback = state.get("reviewer_feedback")
    validation_error = state.get("validation_error")
    feedback_note = ""
    if feedback and feedback.get("has_issues"):
        feedback_note += f"\nThe previous attempt had issues: {feedback.get('notes', '')}\nPlease fix these."
    if validation_error:
        feedback_note += f"\nThe previous attempt FAILED schema validation with this error: {validation_error}\nYou must fix this and follow the schema exactly: exactly 3 tags, each 3-30 characters, summary at most 25 words."

    prompt = f"""You are the Planner agent. Given a title and content, propose exactly 3
short topical tags (each 3-30 characters) and a one-sentence summary of at most 25 words.
Derive the tags and summary ONLY from the given title/content -- do not use any fixed
domain keyword list.{feedback_note}

Respond with ONLY a valid JSON object in this exact shape, nothing else:
{{"tags": ["tag1", "tag2", "tag3"], "summary": "..."}}

Title: {state['title']}
Content: {state['content']}
"""
    client.add_user_message(prompt)
    response = client.complete()
    raw_proposal = extract_json(response.content)

    try:
        validated = PlannerOutput(**raw_proposal)
        print("    validation: PASSED")
        return {
            "planner_proposal": validated.model_dump(),
            "reviewer_feedback": None,
            "validation_error": None,
        }
    except ValidationError as e:
        print(f"    validation: FAILED - {e}")
        return {
            "planner_proposal": None,
            "reviewer_feedback": None,
            "validation_error": str(e),
            "validation_retries": state.get("validation_retries", 0) + 1,
        }


def reviewer_node(state: AgentState) -> Dict[str, Any]:
    print("--- NODE: Reviewer ---")
    client: ModelClient = state["llm"]
    draft = state["planner_proposal"]

    prompt = f"""You are the Reviewer agent. Check the draft JSON below against these rules:
- exactly 3 tags
- each tag is 3-30 characters
- summary is at most 25 words
- tags and summary are relevant to the title/content

Respond with ONLY a valid JSON object in this exact shape, nothing else:
{{"has_issues": true/false, "notes": "short explanation if has_issues is true, else empty string"}}

Draft: {json.dumps(draft)}
Title: {state['title']}
Content: {state['content']}
"""
    client.add_user_message(prompt)
    response = client.complete()
    feedback = extract_json(response.content)
    feedback = {'has_issues': True, 'notes': 'forced for testing'} #TEMP

    return {"reviewer_feedback": feedback}


def supervisor_node(state: AgentState) -> Dict[str, Any]:
    print("--- NODE: Supervisor ---")
    new_count = state.get("turn_count", 0) + 1
    print(f"    turn_count -> {new_count}")
    return {"turn_count": new_count}


def router_logic(state: AgentState) -> str:
    if state.get("turn_count", 0) >= TURN_CEILING:
        print("    router: turn ceiling reached -> END")
        return END

    if not state.get("planner_proposal"):
        print("    router: no proposal yet -> planner")
        return "planner"

    feedback = state.get("reviewer_feedback")
    if feedback is None:
        print("    router: proposal exists, no feedback yet -> reviewer")
        return "reviewer"

    if feedback.get("has_issues"):
        print("    router: reviewer found issues -> planner (retry)")
        return "planner"

    print("    router: no issues -> END")
    return END


def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("supervisor", supervisor_node)
    graph.add_node("planner", planner_node)
    graph.add_node("reviewer", reviewer_node)

    graph.set_entry_point("supervisor")

    graph.add_conditional_edges(
        "supervisor",
        router_logic,
        {"planner": "planner", "reviewer": "reviewer", END: END},
    )

    graph.add_edge("planner", "supervisor")
    graph.add_edge("reviewer", "supervisor")

    return graph.compile()


if __name__ == "__main__":
    app = build_graph()

    client = ModelClient(model="qwen3:8b", temperature=0.7)

    initial_state: AgentState = {
        "title": "Spacious 2BR Near Downtown San Jose",
        "content": (
            "Bright 2-bedroom, 1-bath apartment close to light rail, updated kitchen, "
            "in-unit laundry, available October 1st, pet-friendly with deposit. "
            "Walking distance to shops and restaurants, off-street parking included."
        ),
        "email": "test@example.com",
        "strict": True,
        "task": "tag_and_summarize",
        "llm": client,
        "planner_proposal": None,
        "reviewer_feedback": None,
        "turn_count": 0,
    }

    print("=== STREAMING GRAPH EXECUTION ===\n")
    final_state = None
    for step in app.stream(initial_state):
        for node_name, node_output in step.items():
            print(f">>> {node_name} produced: {node_output}\n")
        final_state = step

    print("=== FINAL STATE ===")
    print(json.dumps(final_state, indent=2, default=str))