# RAUN Interview Scoring App

This is the standalone RAUN app for interview scoring. It shows the logged-in interviewer their assigned interview candidates by default. Admins can deliberately switch to all interviewers.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

Login using your RAUN name and the password configured in `raun_reviewer_workspace/user_config.py`.

## Data

Upload the RAUN Excel/CSV assessment sheet in the app. The app reads candidate details, interview fields, and existing pre-selection scores where available.

Private candidate PDFs can be uploaded in-app or placed in:

```text
data/applicant_documents/
```

## Outputs

- Updated interview Excel workbook
- Candidate PDF report
- Candidate DOCX report
- Optional Google Sheets export tab


## v3 note
This interview app intentionally has no LLM or heuristic assistant. It is a normal interviewer scoring workspace only.
