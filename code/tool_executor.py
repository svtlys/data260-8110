import inspect
import json
import logging

logger = logging.getLogger("tool_executor")

TOOL_NAMES = ("search_listings", "get_listing_detail", "aggregate_landlord_stats")

SAFETY_PREFIX = "blocked by safety rule"
WILDCARD_CHARS = "%_*"
MIN_TERM_CHARS = 3


def default_registry() -> dict:
    """The three real domain tools (imported lazily so tests with a fake
    registry never need the database modules)."""
    import domain_tools5 as tools

    return {name: getattr(tools, name) for name in TOOL_NAMES}


def _envelope(ok: bool, data=None, error=None) -> dict:
    return {"ok": ok, "data": data, "error": error}


def _fail(message: str) -> dict:
    logger.warning("execute_tool rejected: %s", message)
    return _envelope(False, None, message)


def _check_inputs(fn, inputs):
    """Return an error message if `inputs` doesn't fit the tool, else None."""
    if not isinstance(inputs, dict):
        return "inputs must be a JSON object mapping argument names to values"
    if "db" in inputs:
        return "'db' is not an allowed input"

    parameters = {
        name: p for name, p in inspect.signature(fn).parameters.items() if name != "db"
    }
    unexpected = sorted(set(inputs) - set(parameters))
    if unexpected:
        return f"unexpected input(s): {', '.join(unexpected)}"
    missing = sorted(
        name
        for name, p in parameters.items()
        if p.default is inspect.Parameter.empty and name not in inputs
    )
    if missing:
        return f"missing required input(s): {', '.join(missing)}"
    return None


def _safety_violation(tool_name: str, inputs: dict):
    """Domain safety rule. Return an error message if the call is not allowed."""
    if tool_name == "search_listings":
        query = inputs.get("query")
        if isinstance(query, str) and any(ch in query for ch in WILDCARD_CHARS):
            other_chars = [ch for ch in query if ch not in WILDCARD_CHARS and not ch.isspace()]
            if len(other_chars) < MIN_TERM_CHARS:
                return (
                    f"{SAFETY_PREFIX}: a search term with a wildcard needs at least "
                    f"{MIN_TERM_CHARS} other characters, so the whole listing table cannot be dumped"
                )
    return None


def _run_tool(name, inputs, db, registry) -> dict:
    tool_name = name.strip() if isinstance(name, str) else name
    if tool_name not in registry:
        return _fail(f"unknown tool: {name!r}; available tools: {', '.join(sorted(registry))}")
    fn = registry[tool_name]

    problem = _check_inputs(fn, inputs)
    if problem:
        return _fail(problem)

    violation = _safety_violation(tool_name, inputs)
    if violation:
        return _fail(violation)

    try:
        result = fn(**inputs, db=db) if db is not None else fn(**inputs)
    except Exception as exc:  # a tool crashed; the caller must still get an envelope
        logger.error("tool %s raised %s: %s", tool_name, type(exc).__name__, exc)
        return _fail(f"internal error while running {tool_name}: {type(exc).__name__}")

    valid_shape = (
        isinstance(result, dict)
        and set(result) == {"ok", "data", "error"}
        and isinstance(result["ok"], bool)
    )
    if not valid_shape:
        return _fail(f"tool {tool_name} returned an invalid result")
    return result


def execute_tool(name, inputs, *, db=None, registry=None) -> str:
    """Run one tool and return its {ok, data, error} envelope as a JSON string."""
    try:
        registry = registry if registry is not None else default_registry()
        envelope = _run_tool(name, inputs, db, registry)
    except Exception as exc:  # last-resort guard so nothing ever escapes
        logger.error("execute_tool failed unexpectedly: %s: %s", type(exc).__name__, exc)
        envelope = _envelope(False, None, f"internal error: {type(exc).__name__}")

    try:
        return json.dumps(envelope, default=str)
    except (TypeError, ValueError):
        return json.dumps(_envelope(False, None, "result could not be serialized to JSON"))