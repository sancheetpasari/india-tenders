"""Classify a tender into the two groups a CA-cum-consultant cares about.

    'ca'       audit, taxation, accounting, financial advisory  -- the core
    'consult'  every other consulting engagement: PMC/PMU, studies, DPRs,
               market and value-chain analysis, PPP, capacity building
    ''         everything else (works, goods, supply)

Single source of truth. Edit the lists here, then run `python retag.py` to
re-tag existing data without re-scraping. `python sector.py` runs the tests.

Two rules learned the hard way:

* **Match the title only.** Department names are buyers, not the work. "Excise
  and Taxation Department" buying fire extinguishers is not a tax engagement,
  and the "Accountant General" hiring cabs is not an audit.
* **Anchor every pattern with a word boundary.** "auditorium" contains
  "auditor"; unanchored, it pulls in every auditorium construction tender.
"""
from __future__ import annotations

import re

# --- group 1: audit / taxation / accounting ---------------------------------
INCLUDE = [
    # the professions themselves
    r"\bchartered\s+accountan\w*",
    r"\bca\s+firms?\b",
    r"\bca\s*/\s*icwa\b",
    r"\bcost\s+accountan\w*",
    r"\bicwa\b",
    r"\bicai\b",
    r"\bcompany\s+secretar\w*",
    # audit engagements -- never a bare "audit"
    r"\b(?:internal|statutory|concurrent|financial|compliance|revenue|forensic"
    r"|stock|tax|external|special)\s+audits?\b",
    r"\bauditors?\b",
    r"\baudit\s+(?:of\s+accounts?|firms?|services?|report)\b",
    r"\bempanel\w*\s+of\s+(?:chartered|cost\s+accountan|audit)\w*",
    # accounting / bookkeeping
    r"\bbook\s*-?\s*keeping\b",
    r"\baccountancy\b",
    r"\baccounting\s+(?:service|work|support|system|software)\w*",
    r"\bmaintenance\s+of\s+accounts?\b",
    r"\bbank\s+reconciliation\b",
    r"\bpayroll\s+(?:process|service|management)\w*",
    # tax
    r"\btaxation\b",
    r"\btax\s+consultan\w*",
    r"\btax\s+advisor\w*",
    r"\b(?:gst|income\s+tax|tds)\s+(?:return|filing|compliance|consult\w*"
    r"|advisor\w*|matters?|assessment|refund|audit|registration)",
    # advisory / assurance that is unambiguously accountancy
    r"\bdue\s+diligence\b",
    r"\bfinancial\s+(?:advisor\w*|consultan\w*|statements?|reporting)",
    r"\bfinancial\s+management\s+(?:service|consult)\w*",
    r"\bactuarial\b",
    r"\binternal\s+(?:financial\s+)?controls?\b",
]

# --- looks like group 1, isn't ----------------------------------------------
EXCLUDE = [
    r"\bauditorium\b",
    r"\b(?:security|safety|energy|structural|water|infrastructure|green|social"
    r"|medical|clinical|quality|fire|environment\w*|cyber|network|electrical"
    r"|hygiene|sanitation)\s+audits?\b",
    r"\bexcise\s+and\s+taxation\b",          # an office, not an engagement
    # techno-financial audit is consulting on a works contract -> group 2
    r"\btechno\s*-?\s*financial\s+audits?\b",
    # buying a course *about* auditing is not an audit engagement
    r"\baudit\w*\s+training\b",
    r"\btraining\s+(?:course|programme|program)\b",
    # quality-management standards, not CA work
    r"\bas\s*9\d{3}[a-z]?\b",
    r"\biso\s*\d{4,5}\b",
]

# --- group 2: every other consulting engagement -----------------------------
# Deliberately wide. A consultant bids engineering-adjacent work too, so DPRs,
# PMC roles and technical studies belong here rather than being filtered out.
CONSULT = [
    # any consulting engagement, however it is phrased
    r"\bconsultan(?:t|ts|cy|cies)\b",
    r"\bconsulting\s+(?:firm|agency|services?)\b",
    r"\badvisory\s+services?\b",
    r"\badvisor\b",
    r"\bempanel\w*\s+of\s+consultan\w*",
    # retained-expert shapes. "PMC" needs a following noun: Ponda Municipal
    # Corporation writes itself "PMC" in ordinary road-repair tenders.
    r"\bproject\s+management\s+(?:unit|agency|consultan\w*)\b",
    r"\bpmu\b",
    r"\bpmc\s+(?:services?|firm|agency|consultan\w*)\b",
    r"\btransaction\s+advisor\w*",
    r"\btechno\s*-?\s*financial\s+audits?\b",
    # studies, analysis, assessment
    r"\bfeasibility\s+stud\w*", r"\bpre-?feasibility\b",
    r"\bmarket\s+(?:stud\w*|research|assessment|survey)\b",
    r"\bvalue\s+chain\b",
    r"\bdemand[\s-]*(?:and|&)?[\s-]*supply\b",
    r"\bbaseline\s+(?:stud\w*|survey)\b",
    r"\bimpact\s+assessment\b",
    r"\bgap\s+analysis\b",
    r"\bdiagnostic\s+stud\w*",
    r"\bdetailed\s+project\s+report\b",
    r"\b(?:dpr|eoi)\s+preparation\b",
    r"\bmonitoring\s+and\s+evaluation\b",
    r"\bthird\s+party\s+(?:monitoring|verification|inspection)\b",
    # institutional / business
    r"\bcapacity\s+building\b",
    r"\binstitutional\s+strengthening\b",
    r"\bbusiness\s+(?:plan|process|model)\b",
    r"\bprocess\s+re-?engineering\b",
    r"\bchange\s+management\b",
    r"\borgani[sz]ational?\s+restructuring\b",
    r"\bpolicy\s+advisor\w*",
    r"\bpublic\s+private\s+partnership\b",
    r"\bconcession\s+agreement\b",
    r"\bviability\s+gap\b",
    r"\berp\s+(?:implementation|consultan\w*|roll\s*out)\b",
]

_INC = [re.compile(p, re.I) for p in INCLUDE]
_EXC = [re.compile(p, re.I) for p in EXCLUDE]
_CON = [re.compile(p, re.I) for p in CONSULT]


def match(title):
    """Matched phrase if this is group 1 (audit / tax / accounting), else ''."""
    text = title or ""
    for p in _EXC:
        if p.search(text):
            return ""
    for p in _INC:
        m = p.search(text)
        if m:
            return m.group(0)
    return ""


def match_consult(title):
    """Matched phrase if this is group 2 (any other consulting work)."""
    text = title or ""
    for p in _CON:
        m = p.search(text)
        if m:
            return m.group(0)
    return ""


def tag(tender):
    """'ca', 'consult', or '' -- group 1 wins when a title fits both."""
    title = tender.get("title", "")
    if match(title):
        return "ca"
    if match_consult(title):
        return "consult"
    return ""


# --------------------------------------------------------------------- tests

CASES = [
    # group 1 -- audit / taxation / accounting
    ("Appointment of Chartered Accountant Firms as Internal Auditor", "ca"),
    ("Selection of CA Firm for GST and Taxation matters", "ca"),
    ("Financial Audit Services - Review of Financial Statements", "ca"),
    ("Appointment of Concurrent Auditors for RBI Bhopal", "ca"),
    ("For Outsourcing of CA / ICWA firm for the revenue audit", "ca"),
    ("Engagement of Company Secretary services", "ca"),
    ("Appointment of CA firm for maintenance of accounts", "ca"),
    ("Consultancy services to carry out due diligence and bid advisory", "ca"),
    # group 2 -- consulting of every other kind
    ("Hiring of a Consulting Firm for Livestock and Fishery Value Chain "
     "Analysis and Market Demand-Supply Study", "consult"),
    ("Consultancy services for DPR preparation of 32 bridges", "consult"),
    ("Project Management Consultancy for Decentralized Sewage Treatment", "consult"),
    ("Providing PMC services for construction of road", "consult"),
    ("Selection of PMU for Kerala Fibre Optic Network", "consult"),
    ("Appointment of Engineering Consultant for lignite power plant", "consult"),
    ("Comprehensive Feasibility study for solid waste management", "consult"),
    ("Capacity Building of district officials", "consult"),
    ("Selection of Transaction Advisor for EWS Housing", "consult"),
    ("Techno Financial Audit of the work of EWS Site development", "consult"),
    ("Environment Impact Assessment for the irrigation canal", "consult"),
    ("Third Party Inspection of works", "consult"),
    # neither
    ("Repairs to road side in ward no. 3 of PMC of Ponda Constituency", ""),
    ("Construction of 500 seater Auditorium", ""),
    ("AS 9110C AWARENESS & INTERNAL AUDITOR TRAINING COURSE", ""),
    ("ISO 9001 Certification and Surveillance Audit of Privacy", ""),
    ("Servicing of fire extinguishers at Excise and Taxation office", ""),
    ("Security audit of the state data centre", ""),
    ("Energy audit of municipal street lighting", ""),
    ("Laying of CC road near Income Tax colony", ""),
    ("Supply of Spiral Exchanger with GST", ""),
    ("Construction of Building-less PHC under XV-Finance Commission", ""),
]


def _selftest():
    bad = 0
    for title, want in CASES:
        got = tag({"title": title})
        if got != want:
            bad += 1
            print(f"  FAIL  {title[:62]!r} -> {got!r}, wanted {want!r}")
    # a \b must never end up written as a literal backspace byte
    for p in INCLUDE + EXCLUDE + CONSULT:
        if any(ord(c) < 32 for c in p):
            bad += 1
            print(f"  FAIL  control character in pattern {p!r}")
    print(f"{len(CASES)} cases, {bad} failure(s)")
    return bad


if __name__ == "__main__":
    raise SystemExit(1 if _selftest() else 0)
