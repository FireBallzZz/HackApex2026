# Boundary checks (run through POST /api/roster)

| input | HTTP | status | value | diesel | checker | time | note |
|---|---|---|---|---|---|---|---|
| b01_no_outage.json | 200 | ok | 0 | 0.0 | OK | 0.03s |  |
| b02_empty_shop_list.json | 200 | ok | 0 | 0.0 | OK | 0.01s |  |
| b03_budget_exactly_tight_8.00.json | 200 | ok | 84 | 8.0 | OK | 0.03s |  |
| b04_budget_one_hundredth_less_7.99.json | 200 | ok | 79 | 7.6 | OK | 0.02s |  |
| b05_shop_bigger_than_generator_short_blocks.json | 200 | ok | 65 | 6.4 | OK | 0.01s |  |
| b06_shop_bigger_than_generator_3h_block.json | 200 | infeasible | - | - | - | 0.02s | Dark-run vs capacity (rules 3, 6): cold_store needs 12 kW, more than the 10 kW generator, so it is dark all of |
| b07_max_dark_zero.json | 200 | infeasible | - | - | - | 0.01s | Dark-run vs capacity (rules 3, 6): in 12:00-15:00, 17:00-20:00 no choice of shops keeps every normal shop dark |
| b08_mandatory_over_capacity.json | 200 | infeasible | - | - | - | 0.00s | Capacity vs mandatory (rules 3, 5): pharmacy 11 kW = 11 kW > 10 kW generator, in every outage hour (12:00, 13: |
| b09_invalid_three_decimals.json | 400 | invalid_input | - | - | - | 0.00s | fuel_budget_litres: more than two decimal places (8.005) |
| b10_invalid_duplicate_id.json | 400 | invalid_input | - | - | - | 0.00s | shops[1].id: duplicate id 'pharmacy' |
| b11_zero_diesel_no_mandatory.json | 200 | ok | 0 | 0.0 | OK | 0.00s |  |
| b12_all_day_outage_12_shops.json | 200 | ok | 312 | 24.8 | OK | 1.66s |  |
