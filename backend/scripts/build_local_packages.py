"""
Build local package overrides for the three demo scenarios.

Fetches each package from the configured DB (read-only), replaces the
body-only Capital Account Statement emails (e037/e038/e039) with versions
that carry the new table/chart PDF as an attachment (file_id "local::<name>"
resolved from backend/local_packages/files/), and writes
backend/local_packages/<package>.json.

With those JSONs present, session/start serves the modified scenario locally
INSTEAD of the DB — nothing is pushed to Supabase, prod is untouched.

Prereq: python scripts/generate_demo_capital_statements.py
Run from backend/: python scripts/build_local_packages.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

import asyncio
import json
import shutil

BACKEND = Path(__file__).resolve().parent.parent
LOCAL_DIR = BACKEND / "local_packages"
FILES_DIR = LOCAL_DIR / "files"


def _statement_body(as_of: str) -> str:
    return (
        "Dear Limited Partner,\n\n"
        f"Please find attached your Capital Account Statement as of {as_of}.\n\n"
        "Please contact the General Partner with any questions.\n\n"
        "Regards,\n"
        "General Partner\n"
        "10x Growth Fund, L.P."
    )


# email _id -> replacement (body text moves into the attached PDF).
# Subjects are also corrected: the original seed subjects claimed
# "Quarter Ended <future date>" on emails dated BEFORE that quarter end —
# a contradiction that measurably destabilized extraction (6/10 → 10/10
# on e039's statement after aligning the subject with the document dates).
REPLACEMENTS = {
    "e037": {  # mfn_flow — chart variant
        "subject": "Capital Account Statement - As of December 1, 2028",
        "body": _statement_body("December 1, 2028"),
        "attachment": "LP_CAPITAL_ACCOUNT_CHART_DEC2028.pdf",
    },
    "e038": {  # side_letter_flow — table variant
        "subject": "Capital Account Statement - As of December 1, 2028",
        "body": _statement_body("December 1, 2028"),
        "attachment": "LP_CAPITAL_ACCOUNT_STATEMENT_DEC2028.pdf",
    },
    "e039": {  # multi_amendment — table variant
        "subject": "Capital Account Statement - As of June 15, 2030",
        "body": _statement_body("June 15, 2030"),
        "attachment": "LP_CAPITAL_ACCOUNT_STATEMENT_JUN2030.pdf",
    },
}

# Emails whose SUBJECT/BODY stay exactly as the DB has them, but whose
# attachment is served from local_packages/files/ instead of the DB. Used for
# regenerated versions of existing seed PDFs, so local testing picks them up
# without pushing anything to Supabase.
ATTACHMENT_ONLY_OVERRIDES = {
    "e032": "FUND_REALIZATION_Q3_2025.pdf",
}

PACKAGES = ["mfn_flow", "side_letter_flow", "multi_amendment"]


async def _fetch_from_db(package: str) -> list[dict]:
    """Read a package from the database, bypassing the local override.

    main.fetch_seed_emails() consults local_packages/ first, so calling it
    here would make this script read its own previous output instead of the
    database — the JSONs would ossify and never pick up DB changes.
    """
    import os
    from main import _fetch_seed_emails_postgres, _fetch_seed_emails_sqlite, SEED_DB_PATH

    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return await _fetch_seed_emails_postgres(database_url, package)
    return _fetch_seed_emails_sqlite(SEED_DB_PATH, package)


def _localize_attachments(email: dict, missing: list[str]) -> None:
    """Point every attachment at a file in local_packages/files/.

    A local package must not reference database file_ids. push_packages.py
    replaces attachments delete-then-insert, so every push mints new ids and
    any id captured here dies silently — the PDF fails to load, its clauses
    are never extracted, and the scenario produces a plausible but wrong
    answer. Copies the PDF from backend/files/ when it is not already local.
    """
    for att in email.get("attachments") or []:
        fid = att.get("file_id") or ""
        if fid.startswith("local::"):
            continue
        name = att.get("name")
        if not name:
            continue
        dest = FILES_DIR / name
        if not dest.exists():
            src = BACKEND / "files" / name
            if not src.exists():
                missing.append(name)
                continue
            shutil.copy2(src, dest)
        att["file_id"] = f"local::{name}"


async def main():
    # Import from main AFTER load_dotenv so DATABASE_URL is picked up.

    LOCAL_DIR.mkdir(exist_ok=True)
    FILES_DIR.mkdir(parents=True, exist_ok=True)

    # Regenerated versions of existing seed PDFs are written to backend/files/
    # by their generator; copy them into local_packages/files/ so the local
    # server serves the new bytes rather than the DB's old ones.
    for name in ATTACHMENT_ONLY_OVERRIDES.values():
        src = BACKEND / "files" / name
        if not src.exists():
            print(f"Missing source PDF for override: {src}")
            sys.exit(1)
        shutil.copyfile(src, FILES_DIR / name)
        print(f"Copied {name} -> local_packages/files/")

    missing = [r["attachment"] for r in REPLACEMENTS.values()
               if not (FILES_DIR / r["attachment"]).exists()]
    if missing:
        print("Missing PDFs (run generate_demo_capital_statements.py first):")
        for m in missing:
            print(f"  {m}")
        sys.exit(1)

    unresolved: list[str] = []

    for package in PACKAGES:
        emails = await _fetch_from_db(package)
        if not emails:
            print(f"[warn] package {package!r} returned no emails — skipped")
            continue

        out_emails = []
        for e in emails:
            e = dict(e)
            repl = REPLACEMENTS.get(e.get("_id"))
            if repl:
                e["subject"] = repl["subject"]
                e["body"] = repl["body"]
                e["attachments"] = [{
                    "file_id": f"local::{repl['attachment']}",
                    "name": repl["attachment"],
                    "attachment_index": 0,
                }]
            elif e.get("_id") in ATTACHMENT_ONLY_OVERRIDES:
                name = ATTACHMENT_ONLY_OVERRIDES[e["_id"]]
                e["attachments"] = [{
                    "file_id": f"local::{name}",
                    "name": name,
                    "attachment_index": 0,
                }]
            e["date"] = str(e.get("date", ""))
            e["attachments"] = [
                {k: att.get(k) for k in ("file_id", "name", "attachment_index")}
                for att in e.get("attachments", [])
            ]
            # Every attachment must resolve from disk, not from a DB id.
            _localize_attachments(e, unresolved)
            out_emails.append(e)

        out_path = LOCAL_DIR / f"{package}.json"
        out_path.write_text(json.dumps(out_emails, indent=2, default=str),
                            encoding="utf-8")
        n_repl = [e["_id"] for e in out_emails if e["_id"] in REPLACEMENTS]
        print(f"Wrote {out_path.name}: {len(out_emails)} emails, "
              f"replaced {n_repl}")

    if unresolved:
        print("\nWARNING — these PDFs are in no local source, so their emails "
              "will silently lose their attachments:")
        for name in sorted(set(unresolved)):
            print(f"  {name}")


if __name__ == "__main__":
    asyncio.run(main())
