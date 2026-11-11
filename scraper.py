import os
import re
import sys
import time
import requests

sys.stdout.reconfigure(encoding="utf-8")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
if not SUPABASE_URL or not SUPABASE_KEY:
    print("Missing SUPABASE_URL or SUPABASE_KEY. Set them first (see instructions).")
    sys.exit(1)

BASE = "https://www.eis.gov.lv"
PAGE_URL = BASE + "/EKEIS/Supplier"
API_URL = BASE + "/EKEIS/supplier/searchprocurements"

MAX_PAGES = 10      # test mode: only 3 pages (= 60 listings)
PAGE_SIZE = 20


def start_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36",
    })
    html = session.get(PAGE_URL, timeout=30).text
    match = re.search(r'__RequestVerificationToken[^>]*value="([^"]+)"', html)
    token = match.group(1) if match else None
    return session, token


def fetch_page(session, token, offset):
    payload = {
        "ListMode": 0,
        "Paging": True,
        "IsAllPublishedProcurements": False,
        "FormCode": "SUP.S01",
        "SearchParameters": {
            "IsDynamicProcurementSystemHasBeenApplied": 1,
            "IsDynamicProcurementSystemHasNotBeenApplied": 0,
            "Mode": 1,
            "SearchEventCode": "SUP.810",
            "AdvancedSearch": False,
            "Keywords": None,
            "SearchWithoutGrammaticalCases": False,
            "SearchExactPhrase": False,
            "PublicationDateFrom": "2026-01-01T00:00:00",
            "PublicationDateUntil": None,
            "CpvIdList": [],
            "CpvTable": [],
            "From": offset,
        },
        "Results": [],
        "From": offset,
    }
    headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Origin": BASE,
        "Referer": PAGE_URL,
    }
    if token:
        headers["__RequestVerificationToken"] = token
    r = session.post(API_URL, json=payload, headers=headers, timeout=60)
    r.raise_for_status()
    event = r.json().get("EventData") or {}
    return event.get("Items", []), event.get("Hits")


def to_row(item):
    return {
        "id": item["Id"],
        "identification_number": item.get("ProcurementIdentificationNumber"),
        "title": item.get("ProcurementTitle"),
        "customer_name": item.get("CustomerTitle"),
        "customer_reg_number": item.get("CustomerRegistrationNumber"),
        "status_code": item.get("StatusCode"),
        "status_title": item.get("StatusTitle"),
        "is_poster": item.get("IsPoster"),
        "announced_at": item.get("ProcurementAnnouncementDate"),
        "submission_deadline": item.get("LastStagePlannedProposalSubmissionTime"),
        "last_amended_at": item.get("LastAmendmentsDate"),
    }


def save_rows(rows):
    headers = {
        "apikey": SUPABASE_KEY,
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    if SUPABASE_KEY.startswith("eyJ"):  # old-style keys also need this header
        headers["Authorization"] = "Bearer " + SUPABASE_KEY
    r = requests.post(
        SUPABASE_URL + "/rest/v1/eis_listings?on_conflict=id",
        json=rows, headers=headers, timeout=60,
    )
    if r.status_code >= 300:
        print("Supabase said no:", r.status_code, r.text[:500])
        sys.exit(1)


def main():
    session, token = start_session()
    print("Security token found:", bool(token))
    total_saved = 0
    for page in range(MAX_PAGES):
        offset = page * PAGE_SIZE
        items, hits = fetch_page(session, token, offset)
        if not items:
            print("No more listings, stopping.")
            break
        rows = {row["id"]: row for row in map(to_row, items)}.values()
        save_rows(list(rows))
        total_saved += len(rows)
        print(f"Page {page + 1}: offset {offset}, {len(items)} listings, "
              f"dates {items[0]['ProcurementAnnouncementDate']} -> {items[-1]['ProcurementAnnouncementDate']} "
              f"(Hits: {hits})")
        time.sleep(1)  # be polite to their server
    print("Done. Saved/updated", total_saved, "listings.")


main()
