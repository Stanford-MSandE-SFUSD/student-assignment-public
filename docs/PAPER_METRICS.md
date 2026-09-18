# Paper metrics ↔ code metric keys

Maps paper table row names to keys emitted by
`student_assignment/evaluation/short_match_evaluator.py`
(`eval_assignment_paper_metrics`) and written into metrics workbooks.


| Paper                                                        | Code metric key                                |
| ------------------------------------------------------------ | ---------------------------------------------- |
| Average distance (miles) / Distance Avg                      | `Distance Av (All Assigned)`                   |
| Distance < 0.5 miles / Dist < 0.5                            | `Distance < 0.5 (All Assigned)`                |
| Distance > 3 miles / Dist > 3                                | `Distance > 3 (All Assigned)`                  |
| #Schools +15% FRL / Schools >15% above district average FRL  | `#Schools above 15% district FRL`              |
| AALPI in +15% FRL / AALPI in schools >15% above district FRL | `AALPI in school with +15% FRL`                |
| Dissimilarity (High FRL)                                     | `Dissimilarity (High FRL)`                     |
| Theil (High FRL)                                             | `Theil (High FRL)`                             |
| Black/White exposure to High FRL                             | `Black/White exposure to high FRL`             |
| #Schools -15% High Income / Schools with <15% High Income    | `#Schools with -15% High Income (95292)`       |
| Dissimilarity (Income < $95292) / Dissimilarity (Low Income) | `Dissimilarity (Income below 95292)`           |
| Unassigned                                                   | `Unassigned`                                   |
| Designated                                                   | `Designated`                                   |
| Unassigned or Designated                                     | sum of `Unassigned` + `Designated`             |
| Top 1 choice / Top Choice                                    | `Prop Top 1 choice (All Assigned)`             |
| Top 3 choice / Top 3 Choices                                 | `Prop Top 3 choice (All Assigned)`             |
| Top 3 choice (In-Zone)                                       | `Top 3 in-zone choice (All Assigned)`          |
| Dist >3 & Rank≥4 / Distance >3 miles & Rank ≥4               | `Prop Distance > 3 and Rank>=4 (All Assigned)` |
| Variance of In-Zone Rank                                     | `Variance of in-zone rank (All Assigned)`      |
| Variance of Distance                                         | `Variance of distance (All Assigned)`          |
| Rank Top 3 (In Zone, non-CTIP)                               | `Top 3 in-zone choice (non-CTIP)`              |


Many metrics also exist for subgroups (`CTIP`, ethnicity, FRL, …).   
Paper policy tables typically use the **All Assigned** (or explicit non-CTIP) variant,  
but some takeaways in the paper look at subgroup outcomes. 