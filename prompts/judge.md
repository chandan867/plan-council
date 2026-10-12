STAGE: judge

Several models each wrote a plan for the same request without seeing each other. You are the judge. The candidates are labelled by letter and you do not know which model wrote which.

Working directory: {{cwd}}
You are read-only. Check the candidates' factual claims in the directory where it matters to the ranking. Do not create or edit files.

## Request

{{request}}

## Rubric

{{rubric}}

## Candidates

{{candidates}}

## How to judge

- Read every candidate to the end before scoring.
- Score each candidate on each rubric criterion from 1 to 5. Judge criterion by criterion, not on overall feel.
- Pick the base: the candidate that is right about the most important thing and that the others can most easily be folded into. A longer or more polished candidate is not better for that reason.
- List the grafts: specific parts of the other candidates that the base lacks and should take. Usually one or two per candidate.
- If the candidates agree on the shape, say so: agreement between independent models is evidence. If they diverge wildly, say what in the request was read differently.

## Output

Reply with one JSON object and nothing else:

{"scores": [{"candidate": "A", "total": 0, "notes": "criterion by criterion, one line each"}],
 "base": "A",
 "grafts": [{"from": "B", "what": "the part to take", "why": "what it fixes in the base"}],
 "reason": "why this base, and whether the candidates converged"}
