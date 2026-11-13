# Prompt history

**Tool:** Claude (claude.ai), used in two chat sessions.
**Note on wording:** I wrote my prompts in a mix of Telugu and English. They are summarised here in English and condensed (pasted terminal output and error text are described, not copied). The order is the order in which I sent them.

## How AI was used, at a glance

| Part of the project | What Claude did | What I did |
|---|---|---|
| Understanding the brief, planning | Explained the task, proposed the step order and time estimates | Chose the order given my exam schedule |
| Data dictionary, assumptions | Drafted both documents | Read them, ran the generator against them |
| `generator.py` (master data, transactions, planted patterns) | Wrote the code | Ran it, compared the SHA-256 of `customers.csv` with Claude's own run (identical), committed it |
| `build_triage.py` (rules, alerts, cases, actions, anomalies) | Wrote the code and tested it | Ran it on my machine, got the same numbers |
| `validator.py`, `run_all.py` | Wrote the code, tested it by deliberately corrupting data | Ran it; `RESULT: PASS` with the same counts as Claude's run |
| Streamlit web app | Wrote the first version in a separate session, later restyled it (`ui.py`, theme) | Ran it, checked every page, gave feedback on the look |
| Gap check against the original brief | Compared the repository with the brief and found four gaps | Supplied the brief, ran the fixes |
| SQL/JSON export, tests, README | Wrote them | Ran the tests and the full pipeline, pushed |
| Git, folders, PowerShell | Gave commands | Ran every command, fixed my own file placement mistakes |

## Prompt log

### Phase 1: understanding the brief and the first steps

| # | My prompt (summary) | Outcome |
|---|---|---|
| 1 | Uploaded the problem statement and submission documents without a specific question | Claude read them and summarised the task |
| 2 | Asked Claude to explain the task to me first, in Telugu | Plain-language explanation of the workflow, entities and deliverables |
| 3 | Said I wanted a real, working platform and asked for help | Claude proposed the plan: data dictionary, generator, rules and alerts, validator, web app, documentation |
| 4 | Asked what to do first | Step 1: data dictionary and assumptions |


### Phase 2: schedule and constraints

| # | My prompt (summary) | Outcome |
|---|---|---|
| 5 | Asked whether the whole website would take a lot of time | Time estimate per step, about 3 to 4 hours of my active time, with a schedule before the deadline |
| 6 | Said I have a semester exam tomorrow and want to finish as much as possible today | Claude proposed building the rules, anomalies and validator steps together so I only run one command |
| 7 | Asked what requirements Claude needs to continue and offered the earlier files | Claude read `generator.py` and both documents, asked for the original brief, and pointed out a mismatch between the data dictionary and the generated `ground_truth.csv` values |
| 8 | Asked what I should do now and for the remaining work with time per step | Remaining steps and estimates |

### Phase 3: rules, alerts, cases, anomalies, validator (Steps 3 to 5)

| # | My prompt (summary) | Outcome | What I checked |
|---|---|---|---|
| 9 | Shared my terminal output (repository setup, generator run, pushes) for review | Claude confirmed everything was pushed and the `customers.csv` hash matched its own run | Hash identical on both machines |
| 10 | Asked what I should do now, then asked again which of the remaining steps was mine | Claude said it needed the brief or the word "proceed". With no brief, it built Steps 3 to 5 using the data dictionary as the specification | |
| 11 | Said I would download the five generated files and run the move commands | Claude gave the order of commands and what to check | Files moved |
| 12 | Pasted a PowerShell error | Two commands had been joined on one line; Claude gave them one at a time | Fixed |
| 13 | Pasted the output of `python src/run_all.py` | 607 alerts, 6 of 6 anomalies caught, 0 unexpected, reproducibility PASS. Claude gave the commit and push commands | Same numbers as Claude's run |
| 14 | Pasted several outputs while the updated documents did not appear | Browser had saved the new files as `data_dictionary (1).md` and `assumptions (1).md`; Claude gave the commands to move those | File sizes 12145 and 4756 matched |
| 15 | Showed the prompt log in Notepad (it stopped at prompt 4) | Claude wrote the missing entries | Added to this file |

### Phase 4: web app, brief check, polish

| # | My prompt (summary) | Outcome | What I checked |
|---|---|---|---|
| 16 | Asked what comes next | Claude began a Streamlit app in its own environment | |
| 17 | Uploaded a screen recording and asked what is done and what is left | The recording showed my own Streamlit app already running, so Claude stopped its duplicate and listed the remaining work | App pages and logged actions |
| 18 | Uploaded the repository zip, the submission guidelines and the original brief, plus a screenshot of the submission page | Claude compared the repository with the brief and found four gaps: 607 alerts instead of 1,000, no SQL or JSON export, no tests, a two-line README | Reviewed the gap list |
| 19 | Ran the fixes (wrong folder first, then correctly) and pasted the output | 1,000 alerts, validator PASS, SQL loads with 0 foreign key errors, 15 of 15 tests OK | Output matched Claude's run |
| 20 | Asked for the website to look more professional | Light theme, card-style metrics, status and priority badges, charts, case header (`ui.py`, `.streamlit/config.toml`) | Ran the app and looked at each page |
| 21 | Pasted the push output | Claude noticed `README (1).md` had been committed as a duplicate and gave the fix | |
| 22 | Said the website works and asked what to do next | Final checklist: fresh clone test, README review, prompt log, public repository, submit | |
| 23 | Asked for this prompt log to be more professional | This document | |
| 24 | Pasted the fresh clone test output and asked for the next steps | Claude confirmed 15 tests OK and `RESULT: PASS` on the clone, and gave the README, prompt log, public repository and submission checklist | Fresh clone installs and passes |
| 25 | Pasted git output showing "nothing to commit, working tree clean" | Claude explained the file had no unsaved changes and gave commands to check the tail of the log | Checked the log tail |
| 26 | Pasted the prompt log tail and the placeholder search result | Claude found the leftover placeholder comment and gave the steps to remove it and add the last entries | Placeholder removed |


## Corrections and lessons

- **Brief not followed at first.** Without the brief, Claude built to the data dictionary defaults and produced 607 alerts. Once I supplied the brief, the gap check found the 1,000-alert requirement and the missing SQL export, tests and README, and they were added.
- **Dictionary and data mismatch.** Claude spotted that `ground_truth.csv` used values (`should_alert_then_dismiss`, `pattern_instance_id`, an `analyst_action` entity type) that the data dictionary did not list, and updated the dictionary instead of the generator so the baseline checksums stayed valid.
- **Duplicate files.** A copy of `generator.py` ended up in `docs/` and was removed; two documents and the README were first saved by the browser with `(1)` in the name and had to be renamed. These were mistakes in my file handling, caught by checking file sizes.
- **Trust but verify.** I did not rely on Claude's statements alone: I compared hashes, re-ran the validator and the reproducibility check, and ran the tests on my own machine.
