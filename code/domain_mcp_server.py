import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s domain: %(message)s",
)

from mcp.server.fastmcp import FastMCP  # noqa: E402

import domain_tools  # noqa: E402

mcp = FastMCP("domain")


@mcp.tool()
def search_listings(query: str, limit: int = 10) -> dict:
    """Search rental listings whose address contains `query` (case-insensitive).
    `limit` is 1-50. Returns {ok, data: {count, results: [...]}, error}."""
    return domain_tools.search_listings(query, limit)


@mcp.tool()
def get_listing_detail(listing_id: int) -> dict:
    """Look up one listing by its numeric id (>= 1), including its landlord.
    Returns {ok, data, error}."""
    return domain_tools.get_listing_detail(listing_id)


@mcp.tool()
def aggregate_landlord_stats(landlord_id: int) -> dict:
    """Aggregate for one landlord id (>= 1): listing count and total / average
    available units. Returns {ok, data, error}."""
    return domain_tools.aggregate_landlord_stats(landlord_id)


if __name__ == "__main__":
    mcp.run()  # STDIO transport