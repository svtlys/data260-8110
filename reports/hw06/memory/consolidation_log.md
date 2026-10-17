# Consolidation log

Run at 2026-10-17T14:42:56-07:00

- Facts before: 44; after: 22
- Duplicates merged away: 18
- Contradiction pairs detected: 7
- Resolved: 4; needing human review: 1

## Merged duplicates

| kept | all merged lines (original line numbers) |
|---|---|
| [2026-09-05] The user's name is Alex. | L5: [2026-09-05] The user's name is Alex. ; L11: The user's name is Alex. |
| [2026-09-20] Alex works night shifts at a hospital in San Jose. | L6: [2026-09-05] Alex works night shifts at a hospital in San Jose. ; L12: [2026-09-20] ALEX WORKS NIGHT SHIFTS AT A HOSPITAL IN SAN JOSE |
| [2026-10-03] Alex owns two cats named Miso and Pickles. | L7: [2026-09-06] Alex owns two cats named Miso and Pickles. ; L13: [2026-09-20] Alex owns two cats, Miso and Pickles. ; L14: [2026-10-03] Alex owns two cats named Miso and Pickles. |
| [2026-09-27] Alex commutes by Caltrain and prefers to live near a station. | L8: [2026-09-06] Alex commutes by Caltrain and prefers to live near a station. ; L15: [2026-09-27] Alex commutes by Caltrain and prefers to live near a station! |
| [2026-09-13] Needs to move in by December 1. | L22: [2026-09-13] Needs to move in by December 1. ; L29: Needs to move in by December 1. |
| [2026-09-30] Refuses carpet and wants hard flooring because of the cats. | L23: [2026-09-13] Refuses carpet and wants hard flooring because of the cats. ; L30: [2026-09-21] Refuses carpet and wants hard flooring because of the cats. ; L31: [2026-09-30] Refuses carpet; wants hard flooring because of the cats. |
| [2026-09-14] Wants in-unit laundry. | L24: [2026-09-14] Wants in-unit laundry. ; L32: Wants in-unit laundry! |
| [2026-09-29] Wants a quiet building because of a night-shift sleep schedule. | L25: [2026-09-14] Wants a quiet building because of a night-shift sleep schedule. ; L33: [2026-09-29] Wants a QUIET building because of a night-shift sleep schedule. |
| [2026-09-24] Pet policy: the apartment must allow cats. | L26: [2026-09-18] Pet policy: the apartment must allow cats. ; L34: [2026-09-24] Pet policy: the apartment must allow cats. |
| [2026-09-16] Wants replies in at most three sentences. | L39: [2026-09-16] Wants replies in at most three sentences. ; L42: Wants replies in at most three sentences. |
| [2026-10-01] Wants costs shown in US dollars per month. | L40: [2026-09-16] Wants costs shown in US dollars per month. ; L43: [2026-10-01] Wants costs shown in US dollars per month! |
| [2026-09-26] Likes a friendly but brief tone. | L41: [2026-09-17] Likes a friendly but brief tone. ; L44: [2026-09-26] Likes a friendly but brief tone. |
| [2026-10-04] Homework repo is data260-8110 on GitHub. (NEEDS REVIEW: conflicts with another entry; dates unclear) | L47: [2026-09-28] Homework repo is data260-8110 on GitHub. ; L51: [2026-10-04] Homework repo is data260-8110 on GitHub. |
| [2026-10-04] Local model is qwen3:8b via Ollama. (NEEDS REVIEW: conflicts with another entry; dates unclear) | L48: [2026-09-28] Local model is qwen3:8b via Ollama. ; L52: [2026-10-04] Local model is qwen3:8b via Ollama. |
| [2026-10-04] MongoDB database is s8110_doc. (NEEDS REVIEW: conflicts with another entry; dates unclear) | L49: [2026-09-29] MongoDB database is s8110_doc. ; L53: [2026-10-04] MongoDB database is s8110_doc. |
| [2026-10-04] API port is 8010. (NEEDS REVIEW: conflicts with another entry; dates unclear) | L50: [2026-09-30] API port is 8010. ; L54: [2026-10-04] API port is 8010. |

## Contradictions

| outcome | winner | loser | rule |
|---|---|---|---|
| resolved | KEPT: [2026-10-05] Maximum rent budget is $2,900 per month. | SUPERSEDED: [2026-09-12] Maximum rent budget is $2,400 per month. | newest date wins |
| resolved | KEPT: [2026-10-02] Prefers the Japantown neighborhood. | SUPERSEDED: [2026-09-12] Prefers the Willow Glen neighborhood. | newest date wins |
| resolved | KEPT: [2026-10-08] Prefers answers as short paragraphs with no bullet points. | SUPERSEDED: [2026-09-15] Prefers answers formatted as bullet points. | newest date wins |
| resolved | KEPT: [2026-10-01] Wants costs shown in US dollars per month. | SUPERSEDED: [2026-09-16] Wants replies in at most three sentences. | newest date wins |
| NEEDS REVIEW | [2026-10-04] Homework repo is data260-8110 on GitHub. (NEEDS REVIEW: conflicts with another entry; dates unclear) ; [2026-10-04] Local model is qwen3:8b via Ollama. (NEEDS REVIEW: conflicts with another entry; dates unclear) ; [2026-10-04] MongoDB database is s8110_doc. (NEEDS REVIEW: conflicts with another entry; dates unclear) ; [2026-10-04] API port is 8010. (NEEDS REVIEW: conflicts with another entry; dates unclear) | | missing or tied dates; both kept |
