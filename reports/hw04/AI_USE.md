# AI Use — HW4

1. **What I used an AI assistant for, and what I did myself:**

I used Claude to generate first drafts of most of the code: the React components and routing, the SQLAlchemy models, database setup and session-based login/CRUD routes, the seed script, the query counter and the naive/fixed list endpoints, the measurement script, rag.py, and the final verification script. It also helped me find a fifth corpus document and drafted the RAG evaluation ratings and analysis. I installed and configured MySQL, Node, and Postman; created and placed the files; ran every script and test; debugged the errors that came up (files in the wrong folders, a models.py edit that dropped the Listing class, a missing query_counter.py that crash-looped the server, and MySQL password handling); took the Postman, database, and terminal screenshots; and checked the ratings and analysis against the printed retrieval output before submitting.

2. **One AI-produced output that was wrong/unsuitable, or one thing I independently verified:**

The first index I was told to add was on listing_events.listing_id. When I ran EXPLAIN before creating it, MySQL was already using an index on that column (the foreign key had created one automatically), so the before and after plans showed no meaningful change and the example did not demonstrate anything. I also independently checked the N+1 measurements by confirming from the raw data that every naive request ran page_size + 1 queries (11, 51, 201) and every fixed request ran exactly 1.

3. **How I detected the problem or verified the result:**

I read the EXPLAIN output before adding the index and saw the key column already filled in (key: listing_id). For the measurements, I checked the query counts recorded in the 180-row raw file against what each endpoint should produce, and verify_hw04.py repeats that check automatically.

4. **What I changed and why it works now:**

I moved to an unindexed column, listings.landlord_name. Before the index EXPLAIN showed [type: ___ , rows: ___]; after CREATE INDEX it showed [type: ___ , rows: ___], so MySQL stopped scanning the whole table and looked up matching rows through the index instead. [Fill in the real values from your two EXPLAIN screenshots.]