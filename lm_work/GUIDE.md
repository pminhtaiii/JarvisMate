# You are the LifeMate agent LLM

For each public_test sample, read the ASR transcript of the user's final request and act like the tool-calling LLM:
call tools through `lm.py call`, read the results, decide the next call, then mark the sample `done`.
Work dir: `C:/Users/LOQ/Documents/GitHub/JarvisMate/lm_work` (run `cd` there first, use Bash). Commands:

```
python lm.py list 0 80                 # ids + final transcripts (by index range)
python lm.py show <id>                 # context, profile, installed apps, history (with past tool calls/results), final request
python lm.py tool <app>.* | <name>     # schemas (check required params, enums, formats)
python lm.py train "<regex>" [n]       # similar TRAIN examples with GOLD calls - use this a lot to copy the gold style
python lm.py call <id> '<json>'        # one call {"name":..,"arguments":{..}} or a JSON list; invalid calls are rejected and NOT recorded
python lm.py undo <id>                 # remove last call (only use to fix your own obvious mistake BEFORE done)
python lm.py done <id> [<id>...]       # finish (also for samples with zero calls)
```

Never read `*_environment/*/state.json` or other data files directly; only learn app data through tool calls.
In bash, wrap the JSON in single quotes. Be efficient: send several independent calls as a JSON list in one `call`.

## Scoring (what matters)
- Gold = minimal correct call list. Each extra call (incl. unneeded reads) lowers precision; each missing call lowers recall.
- Final app state must match gold exactly, otherwise the sample scores 0. So write calls must have exactly the right IDs and values.
- Free-text fields (message content, titles, notes, labels) are fuzzy-matched; other args must be exact.
- If no installed app can do the request -> no calls, just `done`.

## Gold style learned from train (follow it)
- Read before write only when you need an ID or must check a condition. Typical: `contacts.search {"query": "<name as spoken, e.g. Bố, Mẹ, Sếp Dũng, Lan>"}` then use `contact_id`; `calendar.list_events {}` (usually no filters) before update/cancel or to get an event's time/location; `smart_home.get_status {}` before device set (unless the device id is already in history); `alarm.list {}` before alarm update/delete; `bill_payment.list_bills {}` before pay; `banking.list_beneficiaries` / `banking.get_balance` for account ids; `music.list_tracks {}`; `flights.my_bookings {}` etc.
- If the ID is already in the history's tool results, do not re-read; use it.
- Creating new things (alarm.create, reminders.create with time) needs no prior read.
- Conditional ("nếu mai mưa thì ...") -> check first (`weather.get_forecast {"date": "YYYY-MM-DD"}`, balance, price...). If the condition is false, stop (no further calls).
- Times: ISO 8601 with seconds and offset, e.g. `2026-11-20T10:00:00+07:00`, relative to context current_time. Moving an event keeps its duration (update start and end).
- Addresses: "nhà" = profile.home_address, "công ty" = profile.work_address, copy exact strings. Destination from calendar event location when it refers to an event.
- Ride "đặt ngay" -> no schedule_time. Vehicle enum per schema (car4, car7, bike ...).
- Missing info: call `sys.ask_missing_info {"tool_name": "<tool>", "params": ["<missing required param>"]}`. Do the parts that are possible first; still do the reads that would be needed (e.g. contacts.search for the recipient) before asking. Ambiguity (2 contacts named Minh) -> ask with params ["contact_id"]. Missing amount -> ["amount"].
- Optional params only when the user said them. Don't add label/repeat/location unless spoken.
- Numbers spoken in words -> digits ("hai trăm nghìn" = 200000). The transcript is ASR output and may contain mis-heard words; infer the intended meaning (e.g. "tài sớm nhất" = "cái sớm nhất").
- Message content: short, faithful to what the user asked to say (fuzzy), Vietnamese.
- Do not redo actions already performed in history. Only handle the FINAL request (history gives context such as "cái đó", "cái còn lại").
- When unsure about the style, run `python lm.py train "<keyword from the request>"` and copy the pattern of the closest gold example.

When finished with your range, report: how many samples done, and any you found doubtful (id + one line).
