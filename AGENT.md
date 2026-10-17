# AGENT.md - instructions for the assistant (DATA260, SID4 8110)

## Project description
- [P1] This repo is the DATA260 (SJSU) coursework for student SID4 8110: a Rental Housing Listings service (DOMAIN_ID 6, PORT_BASE 8010, prefix s8110).
- [P2] Shared code lives in code/ and reports live in reports/hwNN/; never copy code into per-homework folders.

## Technology stack
- [T1] Python 3.11 with FastAPI and Pydantic v2; MongoDB (PyMongo) for documents and agent memory; MySQL (SQLAlchemy) for relational data.
- [T2] The local model is qwen3:8b served by Ollama and is called only through ModelClient in src/model_client.py.

## Coding conventions
- [C1] Give every function parameter and return value a type hint.
- [C2] Give every non-test function a docstring that starts with a one-line summary.
- [C3] Use snake_case names and keep every function at most 30 lines long.
- [C4] Use the logging module for diagnostics; never call print() inside a function that is not a test.

## Testing approach
- [X1] Write at least three pytest-style tests named test_<behavior> for every new function, including one error case or edge case.

## Prohibited actions
- [N1] Never hard-code passwords, tokens or API keys; read secrets from environment variables.
- [N2] Never use eval(), exec(), or a bare "except:".
- [N3] Never delete or overwrite files outside the project folder.

## Code review responses
- [R1] When asked to review code, respond using ONLY bullet points. Do not write any prose paragraphs, introductions, or conclusions: every line of the response must be a bullet starting with "- ". Each bullet covers exactly one issue, suggestion, or observation. If there is nothing to critique, respond with a single bullet stating that.