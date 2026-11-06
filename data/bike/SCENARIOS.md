# Scenario files (made by prepare_bike_data.py, seed 8110)

Source: 202609-capitalbikeshare-tripdata.zip (675685 usable rides).

- bike_membership_wins.csv: 520 real rides from one month, long rides first; real timestamps.
  Costs with the prices in pricing_params.json: pay per use 4585.0, membership 1435.51.
- bike_payperuse_wins.csv: 520 real short rides with DATES RE-ASSIGNED across 364 weeks (time of day and durations unchanged; 84 months, which is long because each ride costs at least about $1.15 against $10/month). Costs: pay per use 734.1, membership 840.0.

Public trip data has no rider id, so treating each file as one rider is an assumption.
