"""Registry of Indian government e-procurement portals.

Most states run NIC's GePNIC platform, which exposes a captcha-free
"Tenders by Closing Date" page (FrontEndListTendersbyDate). Those are
scrapable by scraper.py. A handful of states run bespoke platforms and
need their own adapters -- they are listed in UNSUPPORTED for visibility.
"""

# state -> (host, context_path)
GEPNIC_PORTALS = {
    "Arunachal Pradesh":   ("arunachaltenders.gov.in",     "nicgep"),
    "Assam":               ("assamtenders.gov.in",         "nicgep"),
    "Chandigarh":          ("etenders.chd.nic.in",         "nicgep"),
    "Delhi":               ("govtprocurement.delhi.gov.in","nicgep"),
    "DNH & Daman Diu":     ("ddtenders.gov.in",            "nicgep"),
    "Goa":                 ("eprocure.goa.gov.in",         "nicgep"),
    "Haryana":             ("etenders.hry.nic.in",         "nicgep"),
    "Himachal Pradesh":    ("hptenders.gov.in",            "nicgep"),
    "Jammu & Kashmir":     ("jktenders.gov.in",            "nicgep"),
    "Jharkhand":           ("jharkhandtenders.gov.in",     "nicgep"),
    "Kerala":              ("etenders.kerala.gov.in",      "nicgep"),
    "Ladakh":              ("jktenders.gov.in",            "nicgep"),
    "Madhya Pradesh":      ("mptenders.gov.in",            "nicgep"),
    "Maharashtra":         ("mahatenders.gov.in",          "nicgep"),
    "Manipur":             ("manipurtenders.gov.in",       "nicgep"),
    "Meghalaya":           ("meghalayatenders.gov.in",     "nicgep"),
    "Mizoram":             ("mizoramtenders.gov.in",       "nicgep"),
    "Nagaland":            ("nagalandtenders.gov.in",      "nicgep"),
    "Odisha":              ("tendersodisha.gov.in",        "nicgep"),
    "Puducherry":          ("pudutenders.gov.in",          "nicgep"),
    "Punjab":              ("eproc.punjab.gov.in",         "nicgep"),
    "Rajasthan":           ("eproc.rajasthan.gov.in",      "nicgep"),
    "Sikkim":              ("sikkimtender.gov.in",         "nicgep"),
    "Tamil Nadu":          ("tntenders.gov.in",            "nicgep"),
    "Tripura":             ("tripuratenders.gov.in",       "nicgep"),
    "Uttar Pradesh":       ("etender.up.nic.in",           "nicgep"),
    "Uttarakhand":         ("uktenders.gov.in",            "nicgep"),
    "West Bengal":         ("wbtenders.gov.in",            "nicgep"),
    "Central (CPPP)":      ("eprocure.gov.in",             "eprocure"),
    # Central organisations that run their own GePNIC instance rather than
    # publishing through CPPP.
    "Defence (MoD)":       ("defproc.gov.in",              "nicgep"),
    "Coal India":          ("coalindiatenders.nic.in",     "nicgep"),
    "NTPC":                ("eprocurentpc.nic.in",         "nicgep"),
    "Central (etenders)":  ("etenders.gov.in",             "eprocure"),
}

# Ladakh shares the J&K GePNIC instance; skip the duplicate fetch by default.
DUPLICATE_OF = {"Ladakh": "Jammu & Kashmir"}

# Central marketplaces / platforms that are NOT covered. Each is a distinct
# system, not GePNIC, and would need its own adapter:
#   IREPS  https://www.ireps.gov.in       robots.txt is "Disallow: /" -- Indian
#                                          Railways asks crawlers not to index
#                                          the site, so we do not scrape it.
#   MSTC   https://www.mstcecommerce.com   mainly forward e-auctions (scrap,
#                                          coal, customs), and its procurement
#                                          side is DSC/PKI-gated with no public
#                                          listing.
NOT_COVERED_CENTRAL = ["IREPS (Railways)", "MSTC"]

# Union territories with no dedicated portal -- their tenders are published
# on the central CPPP portal, which is already scraped.
VIA_CPPP = ["Andaman & Nicobar", "Lakshadweep"]

# Non-GePNIC states reachable over plain HTTP (adapters.py).
# Sources that are not a geography -- their rows get their region from the
# data itself (GeM) or have none (central portals).
CENTRAL_SOURCES = {"Central (CPPP)", "Central (etenders)", "Defence (MoD)",
                   "Coal India", "NTPC", "GeM", "ONGC"}

CUSTOM_SUPPORTED = ["Andhra Pradesh", "Telangana", "Chhattisgarh", "GeM", "ONGC"]

# Non-GePNIC states that need a real browser engine (browser_adapters.py).
BROWSER_SUPPORTED = ["Gujarat", "Bihar"]

# Still uncovered.
UNSUPPORTED = {
    "Karnataka": ("https://kppp.karnataka.gov.in",
                  "KPPP - tender search is captcha-gated; not bypassed by design"),
}

# Closing-window filter -> Tapestry submit name on FrontEndListTendersbyDate
WINDOWS = {
    "today": "tabByClosingToday",
    "7":     "LinkSubmit_0",
    "14":    "LinkSubmit_1",
}


def active_portals(include_duplicates=False):
    for state, (host, ctx) in GEPNIC_PORTALS.items():
        if not include_duplicates and state in DUPLICATE_OF:
            continue
        yield state, host, ctx
