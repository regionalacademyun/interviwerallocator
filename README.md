# RAUN Interview Allocation Studio

Separate interview-allocation app using the same UI pattern as the RAUN preselection allocator.

## Key behaviour

- Reads the interview-allocation/preselection assessment Excel or Google Sheet where the real header row contains `Reviewer 1`, `Reviewer 2`, applicant details, and two `Invitation to interview?` columns.
- Derives the first-review result using RAUN logic:
  - Yes + Yes = Yes
  - No + No = No
  - Maybe + Maybe = Maybe
  - Maybe + Yes = Maybe+Yes
  - anything else with at least one decision = Maybe+No
  - no decisions yet = No decision yet
- Default interview-pool policy is conservative: **everyone is included unless the combined result is explicitly No**.
- Allocates interviews while preferring one of the two original preselection reviewers where possible.
- Candidate and interviewer availability are optional. If not provided, the app supports manual email coordination.
- Offline upload and connected Google Sheet modes are both supported.

## Run locally

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```
