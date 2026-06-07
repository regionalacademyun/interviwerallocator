# Build notes

This version is built as a modular Streamlit package with two reviewer-facing apps:

1. Pre-selection reviewer grading app.
2. Interview scoring app.

The parser has been tested against the supplied `RAUN 2026 pre-selection sheet.xlsx` and detects the useful header row automatically. For that file it detects the header at Excel row 3 and loads 90 applicant rows.

The app intentionally writes clean export tabs/workbooks rather than overwriting the original raw Google Forms sheet by default. This is safer for deployment and avoids destroying formulas, formatting, or duplicate header structures.

Candidate PDFs are not bundled in the package because they are private and can be large. Upload PDFs inside the app or place them in `data/applicant_documents/` in a private deployment.


## v3 update
- Expanded the opening dashboard with programme, gender, scholarship, country, university, age, research-area, map, progress, decision and score-distribution charts.
- Candidate information now includes every original Excel/Google Forms cell with the `Excel:` prefix, including blank cells, so reviewers can inspect the complete source row.
- Removed all LLM and heuristic assistant UI/imports from the interview app; interview scoring is manual only.
