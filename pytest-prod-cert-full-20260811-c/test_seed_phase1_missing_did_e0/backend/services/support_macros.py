"""Canned support replies. ponytail: a constant list — staff pick one to insert
into a reply. Move to a table only if Vinay needs to edit them without a deploy.
"""

MACROS = [
    {"label": "Ask for details",
     "body": "Thanks for reaching out. Could you tell me a bit more — what were "
             "you trying to do, and what happened instead? That'll help me fix "
             "it faster."},
    {"label": "Call forwarding check",
     "body": "Please check that your clinic line is forwarding to your Vachanam "
             "number, and that call forwarding is switched on with your telecom "
             "provider. Let me know once that's confirmed."},
    {"label": "Billing / plan",
     "body": "You can review and change your plan any time in Settings. Changes "
             "take effect from the next billing cycle so you never lose minutes "
             "you've already paid for. Let me know if you'd like help."},
    {"label": "Escalated",
     "body": "Thanks for your patience — I've escalated this to our engineering "
             "team and will update you here as soon as I hear back."},
    {"label": "Resolved",
     "body": "Glad that's sorted! I'll mark this resolved, but just reply here "
             "if anything comes up again and it'll reopen."},
]
