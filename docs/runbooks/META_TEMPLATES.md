# WhatsApp template pack — paste into Meta Business Manager

WABA → Message templates → Create template. Category **UTILITY** for all
four. Create each template TWICE: language **Telugu (te)** and **English
(en)** — the code sends whichever matches the patient (default en).
Buttons are **Quick reply** type; add them in the exact order shown (the
code addresses them by index). Body {{n}} placeholders must stay in order.

Telugu copy below is first-pass (written register) — review before
submitting; Meta review itself typically takes minutes to 2 days.

---

## 1. booking_confirm

Body (en):
```
Your appointment is confirmed at {{1}} with {{2}} on {{3}}.
Location: {{4}}
```
Body (te):
```
{{1}} లో {{2}} గారితో మీ అపాయింట్‌మెంట్ కన్ఫర్మ్ అయింది — {{3}}.
లొకేషన్: {{4}}
```
Quick replies (order): `Reschedule` · `Cancel`

## 2. appt_reminder

Body (en):
```
Reminder: your appointment with {{1}} is today at {{2}}. See you soon!
```
Body (te):
```
గుర్తు చేస్తున్నాం: ఈరోజు {{2}} కి {{1}} గారితో మీ అపాయింట్‌మెంట్ ఉంది. వస్తారు కదా!
```
Quick replies (order): `Reschedule` · `Cancel`

## 3. rating_ask

Body (en):
```
Thank you for visiting {{1}} today. How was your visit?
```
Body (te):
```
ఈరోజు {{1}} కి వచ్చినందుకు ధన్యవాదాలు. మీ విజిట్ ఎలా అనిపించింది?
```
Quick replies (order): `1 ⭐` · `2 ⭐` · `3 ⭐` · `4 ⭐` · `5 ⭐`

## 4. leave_rebook

Body (en):
```
{{1}} is unavailable on {{2}}, so your appointment was cancelled — sorry.
We tried calling you. Tap below and we'll help you rebook.
```
Body (te):
```
{{2}} న {{1}} గారు అందుబాటులో లేరు, అందుకే మీ అపాయింట్‌మెంట్ క్యాన్సల్ అయింది — సారీ.
మీకు కాల్ కూడా చేశాం. కింద నొక్కండి, మళ్ళీ బుక్ చేసుకుందాం.
```
Quick replies (order): `Reschedule`

---

After approval nothing else is needed — the backend already sends by these
names. A REJECTED template silently disables only that flow (RULE 8).
