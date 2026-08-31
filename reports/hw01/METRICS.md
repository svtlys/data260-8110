# Metrics — HW1

## Non-Determinism (Part 3)

| Metric | Temp 0.7 | Temp 0.0 |
|---|---|---|
| Distinct tag sets | 15 | 1 |
| Tags in all 20 runs | (none) | Downtown San Jose, Pet-Friendly, Spacious 2BR |
| Tags in exactly 1 run | 2br_apartment, Available Oct 1, Downtown Location, Downtown_San_Jose, In-Unit Laundry, Near Downtown, Off-Street Parking, Pet-Friendly Apartment, Pet_Friendly, San Jose, San Jose Downtown, Updated Kitchen Laundry, Updated_Kitchen, downtown_location, downtown_san_jose, pet_friendly | (none) |
| Latency p50 (ms) | 141834.8 | 147490.3 |
| Latency p95 (ms) | 207289.6 | 169338.6 |
| Latency p99 (ms) | 233505.6 | 179092.4 |

## Discussion

When I ran the pipeline 20 times at temperature 0.7, I got 15 different tag sets out of 20 runs. Basically almost every run gave me slightly different wording for the same idea — things like "Pet_Friendly" vs "Pet-Friendly Apartment" vs "pet_friendly" all showed up for what's really the same tag. Not a single tag showed up in all 20 runs, which means if two people submitted the exact
same listing at temp 0.7, they could easily get completely different tags back.

At temperature 0.0, it was the total opposite — all 20 runs gave me the exact same 3 tags every time ("Downtown San Jose", "Pet-Friendly", "Spacious 2BR"). Only 1 distinct tag set out of 20, so it's fully deterministic. Same input in, same output out, every single time.

Latency-wise the two temperatures were pretty close (p50 around 142-147 seconds either way), but temp 0.7 had a longer tail — p99 was about 233s compared to 179s at temp 0.0. My guess is the higher temperature occasionally makes the model ramble more before landing on an answer, which adds to generation time.

**When run-to-run variation is acceptable**: for something like tagging a listing, I don't think the exact wording matters that much. "Pet-Friendly" vs "pet_friendly" still tells a user the same thing, and honestly having some variety in phrasing isn't necessarily bad — it's just different valid ways of describing the same listing.

**When it is not acceptable**: if this same setup were used for something like classifying a grocery recall notice (like "Class I recall" vs "Class II recall"), I don't think this kind of randomness would be okay at all. That's the kind of thing where the same input needs to give the same answer every time, no matter who's asking or when — so I'd want temperature locked at 0.0 for something like that instead of leaving it as a default that can vary.
