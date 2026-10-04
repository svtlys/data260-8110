import logging
import sys

import httpx
from mcp.server.fastmcp import FastMCP

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s meals: %(message)s",
)
logger = logging.getLogger("meals")

API_BASE = "https://www.themealdb.com/api/json/v1/1"
TIMEOUT_SECONDS = 10.0
MIN_LIMIT, MAX_LIMIT = 1, 25

mcp = FastMCP("meals")


def _get(path: str, params: dict | None = None) -> dict:
    """Call TheMealDB; turn network / HTTP / JSON failures into one clean error."""
    url = f"{API_BASE}/{path}"
    logger.info("GET %s params=%s", url, params)
    try:
        response = httpx.get(url, params=params, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.json()
    except httpx.TimeoutException as exc:
        raise RuntimeError(f"TheMealDB request timed out after {TIMEOUT_SECONDS}s") from exc
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(f"TheMealDB returned HTTP {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Network error contacting TheMealDB: {exc}") from exc
    except ValueError as exc:
        raise RuntimeError("TheMealDB returned invalid JSON") from exc


def _check_limit(limit: int) -> int:
    if not isinstance(limit, int) or isinstance(limit, bool) or not (MIN_LIMIT <= limit <= MAX_LIMIT):
        raise ValueError(f"limit must be an integer between {MIN_LIMIT} and {MAX_LIMIT}")
    return limit


def _no_matches(message: str) -> dict:
    return {"results": [], "message": message}


def _full_meal(meal: dict) -> dict:
    ingredients = []
    for i in range(1, 21):
        name = (meal.get(f"strIngredient{i}") or "").strip()
        measure = (meal.get(f"strMeasure{i}") or "").strip()
        if name:
            ingredients.append({"name": name, "measure": measure})
    return {
        "id": meal.get("idMeal"),
        "name": meal.get("strMeal"),
        "category": meal.get("strCategory"),
        "area": meal.get("strArea"),
        "instructions": meal.get("strInstructions"),
        "image": meal.get("strMealThumb"),
        "source": meal.get("strSource"),
        "youtube": meal.get("strYoutube"),
        "ingredients": ingredients,
    }


@mcp.tool()
def search_meals_by_name(query: str, limit: int = 5):
    """Search TheMealDB by meal name. Returns up to `limit` (1-25) meals as
    {id, name, area, category, thumb}."""
    limit = _check_limit(limit)
    if not query or not query.strip():
        raise ValueError("query must be a non-empty string")

    data = _get("search.php", {"s": query.strip()})
    meals = data.get("meals")
    if not meals:
        return _no_matches(f"no matches for '{query.strip()}'")

    return [
        {
            "id": m.get("idMeal"),
            "name": m.get("strMeal"),
            "area": m.get("strArea"),
            "category": m.get("strCategory"),
            "thumb": m.get("strMealThumb"),
        }
        for m in meals[:limit]
    ]


@mcp.tool()
def meals_by_ingredient(ingredient: str, limit: int = 12):
    """Filter TheMealDB by main ingredient. Returns up to `limit` (1-25) small
    cards as {id, name, thumb}."""
    limit = _check_limit(limit)
    if not ingredient or not ingredient.strip():
        raise ValueError("ingredient must be a non-empty string")

    data = _get("filter.php", {"i": ingredient.strip()})
    meals = data.get("meals")
    if not meals:
        return _no_matches(f"no matches for ingredient '{ingredient.strip()}'")

    return [
        {"id": m.get("idMeal"), "name": m.get("strMeal"), "thumb": m.get("strMealThumb")}
        for m in meals[:limit]
    ]


@mcp.tool()
def meal_details(id: str | int):
    """Look up one meal by its TheMealDB id and return the full recipe:
    {id, name, category, area, instructions, image, source, youtube,
    ingredients: [{name, measure}]}."""
    meal_id = str(id).strip()
    if not meal_id.isdigit():
        raise ValueError("id must be a numeric meal id, e.g. 52772")

    data = _get("lookup.php", {"i": meal_id})
    meals = data.get("meals")
    if not meals:
        return _no_matches(f"no meal found with id {meal_id}")
    return _full_meal(meals[0])


@mcp.tool()
def random_meal():
    """Return one random meal in the same shape as meal_details."""
    data = _get("random.php")
    meals = data.get("meals")
    if not meals:
        return _no_matches("TheMealDB returned no random meal")
    return _full_meal(meals[0])


if __name__ == "__main__":
    mcp.run()  # STDIO transport