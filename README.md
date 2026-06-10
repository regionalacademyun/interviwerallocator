# RAUN Interview Allocation Studio

Interview allocation app with controlled availability-template generation and final date/time matching.

## Core workflow

1. Load the RAUN interview-allocation Excel/Google Sheet.
2. Parse Reviewer 1 and Reviewer 2 assessment decisions to build the interview pool.
3. Generate two clean availability templates from dates/times selected in the app:
   - interviewer availability template
   - candidate availability template
4. Send the templates out and ask people to fill only `Yes`, `No`, or `Under reserve`.
5. Upload the completed templates back into the app.
6. Generate final interview matching.

## Matching logic

The matching algorithm uses shared date/time availability.

Priority order:

1. Match candidate with Preselection Reviewer 1 if they share a date/time slot.
2. Match candidate with Preselection Reviewer 2 if they share a date/time slot.
3. If neither original reviewer works, match with another available RAUN team member.
4. If no shared slot exists, leave the candidate unmatched and flag the exception.

The same interviewer cannot be assigned to two candidates in the same date/time slot.

## Output

The main downloadable Excel includes:

- `Final Matching`
- `Interview Allocation Detail`
- `Interviewer Loads`
- `Interview Exceptions`
- `Interview Pool`
- parsed availability sheets

The `Final Matching` sheet has the simple sharing format:

- Interviewer
- Candidate
- Date
- Time
- Email address
- Interview email sent
- Interviewee confirmed

## Run locally

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```
