"""Restore the Supabase emails + attachments tables from a snapshot.

Companion to scripts/backup_supabase.py. Use this when a push_packages.py run
put the wrong documents in prod, or when rolling the code back to a deploy
whose documents differed.

    python scripts/restore_supabase.py --dry-run             # newest snapshot
    python scripts/restore_supabase.py <file> --dry-run      # a specific one
    python scripts/restore_supabase.py <file>                # restore
    python scripts/restore_supabase.py <file> --prune        # exact restore

What a restore does, per email _id present in the snapshot:
  * upsert the email row back to its snapshot content, and
  * delete that email's current attachments and reinsert the snapshot's.

Attachments are replaced wholesale rather than upserted because file_id is
regenerated on every push, so matching by file_id would accumulate orphans.
This also preserves the invariant GET /attachment/{file_id} relies on: bytes
for a given file_id never change.

By default rows that exist in the database but NOT in the snapshot are left
alone and merely reported. --prune deletes them, making the database match
the snapshot exactly.

Safety: the current state is snapshotted before any write (unless
--no-safety-backup), and all writes run in one transaction — an error rolls
back everything rather than leaving prod half-restored.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Reuse the snapshot format, connection handling, and helpers.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from backup_supabase import (  # noqa: E402
    FORMAT_VERSION,
    _connect,
    create_backup,
    decode_value,
    list_backups,
    summarize,
)


def load_snapshot(path: Path) -> dict:
    """Read and validate a snapshot file."""
    try:
        snapshot = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        sys.exit(f"ERROR: {path.name} is not valid JSON: {exc}")

    version = snapshot.get("format_version")
    if version != FORMAT_VERSION:
        sys.exit(
            f"ERROR: {path.name} has format_version={version!r}, this script "
            f"understands {FORMAT_VERSION}. Restore with a matching version."
        )
    for table in ("emails", "attachments"):
        if table not in snapshot.get("tables", {}):
            sys.exit(f"ERROR: {path.name} has no '{table}' table — refusing to restore.")
    return snapshot


def _rows(snapshot: dict, table: str) -> list[dict]:
    return snapshot["tables"][table]["rows"]


def plan(snapshot: dict) -> dict:
    """Compare the snapshot against the live database. Reads only."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT _id FROM emails")
    live_emails = {r[0] for r in cur.fetchall()}
    cur.execute("SELECT email_id, count(*) FROM attachments GROUP BY email_id")
    live_atts = dict(cur.fetchall())
    cur.close()
    conn.close()

    snap_emails = {r["_id"] for r in _rows(snapshot, "emails")}
    snap_atts: dict[str, int] = {}
    for r in _rows(snapshot, "attachments"):
        snap_atts[r["email_id"]] = snap_atts.get(r["email_id"], 0) + 1

    return {
        "restore": sorted(snap_emails & live_emails),
        "reinstate": sorted(snap_emails - live_emails),   # deleted since snapshot
        "extra": sorted(live_emails - snap_emails),       # added since snapshot
        "live_atts": live_atts,
        "snap_atts": snap_atts,
    }


def apply_restore(snapshot: dict, prune: bool) -> dict:
    """Write the snapshot back. All statements share one transaction."""
    import psycopg2

    email_rows = _rows(snapshot, "emails")
    att_rows = _rows(snapshot, "attachments")
    email_cols = snapshot["tables"]["emails"]["columns"]
    att_cols = snapshot["tables"]["attachments"]["columns"]

    snap_email_ids = [r["_id"] for r in email_rows]
    stats = {"emails": 0, "attachments": 0, "pruned_emails": 0, "cleared_atts": 0}

    conn = _connect()
    conn.autocommit = False
    cur = conn.cursor()
    try:
        # ── Emails: upsert every snapshot row ──────────────────────────
        placeholders = ", ".join(["%s"] * len(email_cols))
        assignments = ", ".join(
            f"{c} = EXCLUDED.{c}" for c in email_cols if c != "_id"
        )
        for row in email_rows:
            cur.execute(
                f"INSERT INTO emails ({', '.join(email_cols)}) "
                f"VALUES ({placeholders}) "
                f"ON CONFLICT (_id) DO UPDATE SET {assignments}",
                [decode_value(row[c]) for c in email_cols],
            )
            stats["emails"] += 1

        # ── Attachments: replace wholesale for every in-scope email ────
        if snap_email_ids:
            cur.execute(
                "DELETE FROM attachments WHERE email_id = ANY(%s)", (snap_email_ids,)
            )
            stats["cleared_atts"] = cur.rowcount

        att_placeholders = ", ".join(["%s"] * len(att_cols))
        for row in att_rows:
            values = []
            for c in att_cols:
                v = decode_value(row[c])
                values.append(psycopg2.Binary(v) if isinstance(v, bytes) else v)
            cur.execute(
                f"INSERT INTO attachments ({', '.join(att_cols)}) "
                f"VALUES ({att_placeholders})",
                values,
            )
            stats["attachments"] += 1

        # ── Prune: drop anything the snapshot does not contain ─────────
        if prune:
            cur.execute("DELETE FROM emails WHERE NOT (_id = ANY(%s))", (snap_email_ids,))
            stats["pruned_emails"] = cur.rowcount
            # Attachments belonging to pruned emails (no FK cascade assumed).
            cur.execute(
                "DELETE FROM attachments WHERE NOT (email_id = ANY(%s))",
                (snap_email_ids,),
            )

        conn.commit()
    except Exception:
        conn.rollback()
        cur.close()
        conn.close()
        raise
    cur.close()
    conn.close()
    return stats


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("snapshot", nargs="?",
                    help="Snapshot filename or path. Default: newest in backups/.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show what would change; write nothing.")
    ap.add_argument("--prune", action="store_true",
                    help="Also delete rows absent from the snapshot (exact restore).")
    ap.add_argument("--yes", action="store_true",
                    help="Skip the confirmation prompt (for non-interactive use).")
    ap.add_argument("--no-safety-backup", action="store_true",
                    help="Do not snapshot current state before writing.")
    args = ap.parse_args()

    # ── Locate the snapshot ────────────────────────────────────────────
    if args.snapshot:
        path = Path(args.snapshot)
        if not path.exists():
            candidate = Path(__file__).resolve().parent.parent / "backups" / args.snapshot
            if not candidate.exists():
                sys.exit(f"ERROR: no such snapshot: {args.snapshot}")
            path = candidate
    else:
        backups = list_backups()
        if not backups:
            sys.exit("ERROR: no snapshots found. Run scripts/backup_supabase.py first.")
        path = backups[0]

    snapshot = load_snapshot(path)

    print("=" * 64)
    print(f"Restoring from: {path.name}")
    print(f"  taken: {snapshot.get('created_at', '?')}")
    print(summarize(snapshot))
    print("=" * 64)

    p = plan(snapshot)
    print("\nAgainst the current database:")
    print(f"  {len(p['restore']):3d} email(s) will be overwritten with snapshot content")
    if p["reinstate"]:
        print(f"  {len(p['reinstate']):3d} email(s) deleted since the snapshot will be "
              f"reinstated: {', '.join(p['reinstate'])}")
    if p["extra"]:
        verb = "DELETED" if args.prune else "left untouched"
        print(f"  {len(p['extra']):3d} email(s) not in the snapshot will be {verb}: "
              f"{', '.join(p['extra'])}")
        if not args.prune:
            print("       (re-run with --prune to make the database match exactly)")

    changed_atts = [
        eid for eid in set(p["live_atts"]) | set(p["snap_atts"])
        if p["live_atts"].get(eid, 0) != p["snap_atts"].get(eid, 0)
    ]
    if changed_atts:
        print(f"\n  attachment counts differ for: {', '.join(sorted(changed_atts))}")
    print("\n  NOTE: attachment rows are replaced for every email in the snapshot, "
          "so\n        PDF bytes revert even where the row count is unchanged.")

    if args.dry_run:
        print("\nDRY RUN — nothing was written.")
        return

    # ── Confirm ────────────────────────────────────────────────────────
    if not args.yes:
        print("\nThis rewrites the production documents.")
        if input("Type 'restore' to proceed: ").strip() != "restore":
            print("Aborted. Nothing was written.")
            return

    # ── Safety snapshot of the pre-restore state ───────────────────────
    if not args.no_safety_backup:
        print("\nSnapshotting current state first…")
        safety = create_backup(label="pre-restore")
        print(f"  saved: {safety.name}")

    print("\nRestoring…")
    try:
        stats = apply_restore(snapshot, prune=args.prune)
    except Exception as exc:
        print(f"\nFAILED — transaction rolled back, database unchanged.\n  {exc}")
        sys.exit(1)

    print(f"  emails upserted:      {stats['emails']}")
    print(f"  attachments cleared:  {stats['cleared_atts']}")
    print(f"  attachments inserted: {stats['attachments']}")
    if args.prune:
        print(f"  emails pruned:        {stats['pruned_emails']}")
    print("\nDone. Restart/redeploy the backend so in-memory sessions pick up "
          "the restored rows.")


if __name__ == "__main__":
    main()
