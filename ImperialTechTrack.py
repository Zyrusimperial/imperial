"""
Imperial Network - TechTrack  (enhanced v3: queue, pull-out, backjob, LCP, completed)
Tkinter Desktop GUI + SQLite Database
Run: py ImperialTechTrack.py
No third-party packages required.

Your existing techtrack.db is upgraded automatically on first run.
"""

import csv
import html
import re
import sqlite3
import tempfile
import tkinter as tk
import webbrowser
from collections import Counter
from datetime import datetime
from pathlib import Path
from tkinter import ttk, messagebox, filedialog

DB = Path(__file__).resolve().with_name("techtrack.db")

NAVY = "#10243e"
BLUE = "#2463eb"
BG = "#f2f5fa"
WHITE = "#ffffff"
GREEN = "#16a34a"
RED = "#dc2626"
ORANGE = "#ea580c"
PURPLE = "#7c3aed"
GREY = "#64748b"

DT_FMT = "%Y-%m-%d %H:%M:%S"
LATE_HOURS = 24  # a job still "Dispatched" after this long is flagged

JOB_TYPES = ["Installation", "Pull-out", "Troubleshooting", "Backjob"]
TICKET_PREFIX = {"Installation": "IN", "Pull-out": "PO", "Troubleshooting": "TS", "Backjob": "BJ"}
REQUEST_PREFIX = {"Installation": "APP", "Pull-out": "PUL", "Backjob": "BKJ"}
REQUEST_STATUSES = ["Waiting LCP", "Ready", "Dispatched", "In Progress", "Completed", "Cancelled"]
OPEN_REQUEST = ("Waiting LCP", "Ready", "Dispatched", "In Progress")
QUEUED = ("Waiting LCP", "Ready")
PRIORITY_RANK = {"Urgent": 0, "High": 1, "Normal": 2}
PULLOUT_REASONS = ["Disconnection", "Non-payment", "Customer request", "Transfer of address",
                   "Defective router", "Other"]
BACKJOB_REASONS = ["No internet / LOS", "Slow speed", "Weak Wi-Fi signal", "Router problem",
                   "Cable relocation / re-route", "Wrong installation", "Other"]
PRIORITIES = ["Normal", "High", "Urgent"]
ROUTER_STATUSES = ["Available", "In Use", "Defective", "Maintenance"]
JOB_STATUSES = ["Dispatched", "In Progress", "Completed", "Cancelled"]
ACTIVE_JOB = ("Dispatched", "In Progress")

STATUS_COLORS = {
    "Available": GREEN, "Completed": GREEN, "Active": GREEN,
    "In Use": BLUE, "Dispatched": BLUE,
    "In Progress": PURPLE,
    "Maintenance": ORANGE,
    "Defective": RED, "Cancelled": RED, "Inactive": RED,
    "Waiting LCP": ORANGE, "Ready": "#0891b2",
    "Coordinated": GREEN, "Not Coordinated": RED,
}

MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}([:-]?[0-9A-Fa-f]{2}){5}$")
PHONE_RE = re.compile(r"^[0-9+()\-\s]{7,20}$")

# Columns that should be left-aligned in tables
LEFT_COLS = {"customer", "address", "details", "name", "router",
             "technician", "action", "installed", "reason", "source",
             "plan", "area", "coordinator", "serial"}


# -------------------------------------------------
# HELPERS
# -------------------------------------------------

def stamp():
    return datetime.now().strftime(DT_FMT)


def parse_dt(text):
    return datetime.strptime(text, DT_FMT)


def tag_name(status):
    return "s_" + status.replace(" ", "_")


def fmt_duration(seconds):
    seconds = max(int(seconds), 0)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def job_duration(status, dispatch, start, end):
    try:
        if status == "Completed" and start and end:
            return fmt_duration((parse_dt(end) - parse_dt(start)).total_seconds())
        if status == "In Progress" and start:
            return fmt_duration((datetime.now() - parse_dt(start)).total_seconds())
        if status == "Dispatched" and dispatch:
            waited = (datetime.now() - parse_dt(dispatch)).total_seconds()
            return fmt_duration(waited) + " waiting"
    except ValueError:
        pass
    return ""


def is_late(status, dispatch):
    try:
        return (status == "Dispatched" and
                (datetime.now() - parse_dt(dispatch)).total_seconds() > LATE_HOURS * 3600)
    except ValueError:
        return False


def normalize_mac(mac):
    """'' -> '' | valid -> AA:BB:CC:DD:EE:FF | invalid -> None"""
    mac = mac.strip()
    if not mac:
        return ""
    if not MAC_RE.match(mac):
        return None
    digits = re.sub(r"[^0-9A-Fa-f]", "", mac).upper()
    return ":".join(digits[i:i + 2] for i in range(0, 12, 2))


class Filter:
    """Search box + up to two dropdowns that sit above a table."""

    def __init__(self, search, status, count, combo=None, status2=None, combo2=None):
        self.search = search
        self.status = status
        self.count = count
        self.combo = combo
        self.status2 = status2
        self.combo2 = combo2

    def accepts(self, values, status=None, extra=None):
        needle = self.search.get().strip().lower()
        if needle and needle not in " ".join(str(v) for v in values).lower():
            return False
        wanted = self.status.get()
        if status is not None:
            if wanted == "Open":
                if status not in OPEN_REQUEST:
                    return False
            elif wanted != "All" and status != wanted:
                return False
        if self.status2 is not None and extra is not None:
            wanted2 = self.status2.get()
            if wanted2 != "All" and extra != wanted2:
                return False
        return True

    def show(self, shown, total):
        self.count.config(text=f"Showing {shown} of {total}")


# -------------------------------------------------
# DATABASE
# -------------------------------------------------

class Store:
    def __init__(self, path=DB):
        self.c = sqlite3.connect(path)
        self.c.row_factory = sqlite3.Row
        self.c.execute("PRAGMA foreign_keys=ON")

        self.c.executescript("""
        CREATE TABLE IF NOT EXISTS technicians(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT DEFAULT '',
            active INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS routers(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            brand TEXT NOT NULL,
            model TEXT NOT NULL,
            serial TEXT NOT NULL UNIQUE,
            mac TEXT DEFAULT '',
            status TEXT DEFAULT 'Available'
        );

        CREATE TABLE IF NOT EXISTS jobs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket TEXT,
            customer TEXT NOT NULL,
            contact TEXT,
            address TEXT NOT NULL,
            technician_id INTEGER NOT NULL,
            router_id INTEGER NOT NULL,
            job_type TEXT NOT NULL,
            status TEXT NOT NULL,
            dispatch_time TEXT NOT NULL,
            start_time TEXT DEFAULT '',
            end_time TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            priority TEXT DEFAULT 'Normal',
            request_id INTEGER,
            FOREIGN KEY(technician_id) REFERENCES technicians(id),
            FOREIGN KEY(router_id) REFERENCES routers(id)
        );

        CREATE TABLE IF NOT EXISTS logs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_time TEXT,
            technician TEXT,
            action TEXT,
            details TEXT
        );

        CREATE TABLE IF NOT EXISTS lcps(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            area TEXT DEFAULT '',
            capacity INTEGER DEFAULT 16,
            coordinated INTEGER DEFAULT 0,
            coordinated_on TEXT DEFAULT '',
            coordinator TEXT DEFAULT '',
            notes TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS requests(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ref TEXT UNIQUE,
            kind TEXT NOT NULL,
            customer TEXT NOT NULL,
            contact TEXT DEFAULT '',
            address TEXT NOT NULL,
            plan TEXT DEFAULT '',
            lcp_id INTEGER,
            router_id INTEGER,
            source_job_id INTEGER,
            reason TEXT DEFAULT '',
            status TEXT NOT NULL,
            priority TEXT DEFAULT 'Normal',
            queued_at TEXT NOT NULL,
            job_id INTEGER,
            notes TEXT DEFAULT '',
            FOREIGN KEY(lcp_id) REFERENCES lcps(id),
            FOREIGN KEY(router_id) REFERENCES routers(id)
        );
        """)

        self._migrate()

        if not self.c.execute("SELECT 1 FROM technicians LIMIT 1").fetchone():
            self.c.executemany(
                "INSERT INTO technicians(name,phone) VALUES(?,?)",
                [
                    ("Juan Dela Cruz", "09171234567"),
                    ("Maria Santos", "09981234567"),
                    ("Pedro Reyes", "09221234567"),
                ],
            )

        if not self.c.execute("SELECT 1 FROM routers LIMIT 1").fetchone():
            self.c.executemany(
                "INSERT INTO routers(brand,model,serial,mac) VALUES(?,?,?,?)",
                [
                    ("TP-Link", "Archer C6", "TPL-10001", "00:11:22:33:44:01"),
                    ("Huawei", "HG8145V5", "HW-10002", "00:11:22:33:44:02"),
                    ("ZTE", "F670L", "ZTE-10003", "00:11:22:33:44:03"),
                ],
            )

        if not self.c.execute("SELECT 1 FROM lcps LIMIT 1").fetchone():
            # sample LCPs - edit or delete them in the LCP Coordination tab
            self.c.executemany(
                "INSERT INTO lcps(code,area,capacity,coordinated,coordinated_on,coordinator) "
                "VALUES(?,?,?,?,?,?)",
                [
                    ("LCP-001", "Poblacion", 16, 1, stamp(), "Barangay Office"),
                    ("LCP-002", "San Antonio", 16, 0, "", ""),
                    ("LCP-003", "Sta. Cruz", 32, 1, stamp(), ""),
                ],
            )

        self.c.commit()

    def _migrate(self):
        """Upgrade databases created by the older version."""
        cols = [r["name"] for r in self.c.execute("PRAGMA table_info(jobs)")]
        if "priority" not in cols:
            self.c.execute("ALTER TABLE jobs ADD COLUMN priority TEXT DEFAULT 'Normal'")
        if "request_id" not in cols:
            self.c.execute("ALTER TABLE jobs ADD COLUMN request_id INTEGER")
        self.c.executescript("""
        CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
        CREATE INDEX IF NOT EXISTS idx_jobs_router ON jobs(router_id);
        CREATE INDEX IF NOT EXISTS idx_jobs_tech   ON jobs(technician_id);
        CREATE INDEX IF NOT EXISTS idx_req_kind    ON requests(kind, status);
        CREATE INDEX IF NOT EXISTS idx_req_lcp     ON requests(lcp_id);
        """)

    # NOTE: log() does not commit. Call it inside with self.db.c: so the
    # change and its log entry are saved together (or rolled back together).
    def log(self, tech, action, detail):
        self.c.execute(
            "INSERT INTO logs(event_time,technician,action,details) VALUES(?,?,?,?)",
            (stamp(), tech, action, detail),
        )

    def next_ticket(self, job_type):
        prefix = TICKET_PREFIX.get(job_type, "JB")
        day = datetime.now().strftime("%y%m%d")
        n = self.c.execute(
            "SELECT COUNT(*) FROM jobs WHERE ticket LIKE ?",
            (f"{prefix}-{day}-%",),
        ).fetchone()[0] + 1
        while True:
            ticket = f"{prefix}-{day}-{n:03d}"
            if not self.c.execute("SELECT 1 FROM jobs WHERE ticket=?", (ticket,)).fetchone():
                return ticket
            n += 1

    def job(self, job_id):
        return self.c.execute("""
            SELECT j.*, t.name AS tech_name,
                   r.brand || ' ' || r.model AS router_name,
                   r.serial AS serial, r.mac AS mac
            FROM jobs j
            JOIN technicians t ON j.technician_id=t.id
            JOIN routers r ON j.router_id=r.id
            WHERE j.id=?
        """, (job_id,)).fetchone()

    def release_installation_router(self, router_id):
        """Free a router unless another active installation still holds it."""
        busy = self.c.execute(
            "SELECT 1 FROM jobs WHERE router_id=? AND job_type='Installation' "
            "AND status IN ('Dispatched','In Progress') LIMIT 1",
            (router_id,),
        ).fetchone()
        if not busy:
            self.c.execute(
                "UPDATE routers SET status='Available' WHERE id=? AND status='In Use'",
                (router_id,),
            )

    def scalar(self, sql, args=()):
        return self.c.execute(sql, args).fetchone()[0]

    # ---- queue / request logic (call inside with self.c:) ----------

    def next_ref(self, kind):
        prefix = REQUEST_PREFIX.get(kind, "REQ")
        day = datetime.now().strftime("%y%m%d")
        n = self.c.execute("SELECT COUNT(*) FROM requests WHERE ref LIKE ?",
                           (f"{prefix}-{day}-%",)).fetchone()[0] + 1
        while True:
            ref = f"{prefix}-{day}-{n:03d}"
            if not self.c.execute("SELECT 1 FROM requests WHERE ref=?", (ref,)).fetchone():
                return ref
            n += 1

    def lcp_state(self, lcp_id):
        if not lcp_id:
            return False
        row = self.c.execute("SELECT coordinated FROM lcps WHERE id=?", (lcp_id,)).fetchone()
        return bool(row and row[0])

    def queue_status(self, kind, lcp_id):
        """Installations wait for their LCP to be coordinated; other kinds are ready."""
        if kind == "Installation" and not self.lcp_state(lcp_id):
            return "Waiting LCP"
        return "Ready"

    def apply_lcp_state(self, lcp_id):
        """Move queued installations when an LCP is (un)coordinated. Returns rows changed."""
        if self.lcp_state(lcp_id):
            cur = self.c.execute("UPDATE requests SET status='Ready' WHERE lcp_id=? "
                                 "AND kind='Installation' AND status='Waiting LCP'", (lcp_id,))
        else:
            cur = self.c.execute("UPDATE requests SET status='Waiting LCP' WHERE lcp_id=? "
                                 "AND kind='Installation' AND status='Ready'", (lcp_id,))
        return cur.rowcount

    def add_request(self, kind, customer, contact, address, plan="", lcp_id=None,
                    router_id=None, source_job_id=None, reason="", priority="Normal", notes=""):
        ref = self.next_ref(kind)
        cur = self.c.execute("""
            INSERT INTO requests(ref,kind,customer,contact,address,plan,lcp_id,router_id,
                                 source_job_id,reason,status,priority,queued_at,notes)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (ref, kind, customer, contact, address, plan, lcp_id, router_id, source_job_id,
              reason, self.queue_status(kind, lcp_id), priority, stamp(), notes))
        return cur.lastrowid, ref

    def sync_request(self, job_id, job_status):
        """Keep the queue record in step with its job."""
        req = self.c.execute("SELECT id, kind, lcp_id FROM requests WHERE job_id=?",
                             (job_id,)).fetchone()
        if not req:
            return
        if job_status in ("Dispatched", "In Progress", "Completed"):
            self.c.execute("UPDATE requests SET status=? WHERE id=?", (job_status, req["id"]))
        elif job_status == "Cancelled":
            # back into the queue so it can be assigned again
            status = self.queue_status(req["kind"], req["lcp_id"])
            if req["kind"] == "Installation":
                self.c.execute("UPDATE requests SET status=?, job_id=NULL, router_id=NULL "
                               "WHERE id=?", (status, req["id"]))
            else:
                self.c.execute("UPDATE requests SET status=?, job_id=NULL WHERE id=?",
                               (status, req["id"]))

    def detach_job(self, job_id, requeue):
        """Called before a job is deleted."""
        if requeue:
            self.sync_request(job_id, "Cancelled")
        else:
            self.c.execute("UPDATE requests SET job_id=NULL WHERE job_id=?", (job_id,))

    def lcp_overflow(self, rows):
        over = []
        for lcp_id, n in Counter(r["lcp_id"] for r in rows if r["lcp_id"]).items():
            lcp = self.c.execute("SELECT code, capacity FROM lcps WHERE id=?",
                                 (lcp_id,)).fetchone()
            used = self.scalar(
                "SELECT COUNT(*) FROM requests WHERE lcp_id=? AND kind='Installation' "
                "AND status IN ('Dispatched','In Progress','Completed')", (lcp_id,))
            if lcp and used + n > lcp["capacity"]:
                over.append(f"{lcp['code']} ({used + n}/{lcp['capacity']})")
        return over

    def assign_requests(self, kind, rows, tech_ids):
        """Create one job per Ready request, balancing load across tech_ids."""
        marks = ",".join("?" * len(tech_ids))
        names, load = {}, {}
        for t in self.c.execute(
            f"SELECT id, name, (SELECT COUNT(*) FROM jobs j WHERE j.technician_id=technicians.id "
            f"AND j.status IN ('Dispatched','In Progress')) AS busy "
            f"FROM technicians WHERE id IN ({marks})", tuple(tech_ids)
        ):
            names[t["id"]] = t["name"]
            load[t["id"]] = t["busy"]

        routers = []
        if kind == "Installation":
            routers = self.c.execute(
                "SELECT id FROM routers WHERE status='Available' ORDER BY id").fetchall()
            if len(routers) < len(rows):
                raise ValueError(f"{len(rows)} installation(s) need a router but only "
                                 f"{len(routers)} are Available.")

        made = []
        for i, r in enumerate(rows):
            current = self.c.execute("SELECT status FROM requests WHERE id=?",
                                     (r["id"],)).fetchone()
            if not current or current[0] != "Ready":
                continue
            router_id = routers[i]["id"] if kind == "Installation" else r["router_id"]
            if router_id is None:
                raise ValueError(f"{r['customer']} has no router recorded.")

            tid = min(load, key=lambda k: (load[k], k))
            load[tid] += 1
            ticket = self.next_ticket(kind)
            note = "\n".join(x for x in (r["reason"], r["notes"]) if x)

            cur = self.c.execute("""
                INSERT INTO jobs(ticket, customer, contact, address, technician_id, router_id,
                                 job_type, status, dispatch_time, notes, priority, request_id)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """, (ticket, r["customer"], r["contact"], r["address"], tid, router_id, kind,
                  "Dispatched", stamp(), note, r["priority"], r["id"]))
            self.c.execute("UPDATE requests SET status='Dispatched', job_id=?, router_id=? "
                           "WHERE id=?", (cur.lastrowid, router_id, r["id"]))
            if kind == "Installation":
                self.c.execute("UPDATE routers SET status='In Use' WHERE id=?", (router_id,))
            self.log("Administrator", "Job Dispatched",
                     f"{ticket} - {r['customer']} [{names[tid]}]")
            made.append({"request_id": r["id"], "ticket": ticket, "tech": names[tid]})
        return made


# -------------------------------------------------
# QUEUE, PULL-OUT, BACKJOB, LCP, COMPLETED, PRINTING
# -------------------------------------------------

REQUEST_SQL = """
    SELECT q.*, l.code AS lcp_code, l.area AS lcp_area,
           r.brand || ' ' || r.model AS router_name, r.serial AS serial, r.mac AS mac,
           t.name AS tech, j.ticket AS ticket, j.dispatch_time AS dispatched,
           sj.ticket AS source_ticket
    FROM requests q
    LEFT JOIN lcps l ON q.lcp_id=l.id
    LEFT JOIN routers r ON q.router_id=r.id
    LEFT JOIN jobs j ON q.job_id=j.id
    LEFT JOIN technicians t ON j.technician_id=t.id
    LEFT JOIN jobs sj ON q.source_job_id=sj.id
"""

LAST_INSTALL_SQL = """
    SELECT j.customer, j.contact, j.address, q.lcp_id, q.plan
    FROM jobs j LEFT JOIN requests q ON j.request_id=q.id
    WHERE j.router_id=? AND j.job_type='Installation'
      AND j.status IN ('Dispatched','In Progress','Completed')
    ORDER BY j.id DESC LIMIT 1
"""

QUEUE_CFG = {
    "Installation": {
        "tab": "Install Queue",
        "title": "Installation Queue Monitoring",
        "sub": "Applicants waiting to be installed. Tick the names, then assign them to a technician.",
        "cols": ("id", "chk", "pos", "ref", "customer", "contact", "address", "lcp",
                 "plan", "technician", "priority", "status", "queued"),
        "heads": ("ID", "Pick", "Queue #", "Application No.", "Customer Name", "Contact",
                  "Address", "LCP", "Plan", "Technician", "Priority", "Status", "Date Queued"),
        "widths": (40, 40, 62, 125, 150, 100, 190, 80, 90, 120, 65, 95, 135),
    },
    "Pull-out": {
        "tab": "Pull-out List",
        "title": "Pull-out List",
        "sub": "Routers to be retrieved from customers. Tick the names, then assign them to a technician.",
        "cols": ("id", "chk", "ref", "customer", "contact", "address", "router",
                 "reason", "technician", "priority", "status", "queued"),
        "heads": ("ID", "Pick", "Pull-out No.", "Customer Name", "Contact", "Address",
                  "Router", "Reason", "Technician", "Priority", "Status", "Date Queued"),
        "widths": (40, 40, 125, 150, 100, 190, 200, 130, 120, 65, 95, 135),
    },
    "Backjob": {
        "tab": "Backjobs",
        "title": "Backjob Monitoring",
        "sub": "Return visits for work that has to be redone or fixed. Tick the names, then assign them.",
        "cols": ("id", "chk", "ref", "customer", "contact", "address", "source",
                 "reason", "technician", "priority", "status", "queued"),
        "heads": ("ID", "Pick", "Backjob No.", "Customer Name", "Contact", "Address",
                  "Original Ticket", "Reason", "Technician", "Priority", "Status", "Date Queued"),
        "widths": (40, 40, 125, 150, 100, 190, 125, 170, 120, 65, 95, 135),
    },
}

PRINT_CSS = """
body{font-family:'Segoe UI',Arial,sans-serif;color:#10243e;margin:0}
.page{padding:28px 38px;page-break-after:always}
.page:last-child{page-break-after:auto}
.brand{font-size:11px;letter-spacing:2px;color:#2463eb;font-weight:bold}
h1{font-size:21px;margin:2px 0 14px}
h2{font-size:15px;margin:18px 0 6px}
table{width:100%;border-collapse:collapse}
td,th{border:1px solid #8a94a6;padding:7px 9px;font-size:13px;text-align:left;vertical-align:top}
th{background:#eef2f8;width:28%}
table.list th{width:auto}
ul.chk{padding:0;margin:6px 0}
ul.chk li{list-style:none;margin:7px 0;font-size:14px}
.sig{display:inline-block;width:44%;border-top:1px solid #000;margin:48px 3% 0 0;
     text-align:center;font-size:12px;padding-top:4px}
.bar{padding:10px 38px;background:#f2f5fa}
.bar button{padding:6px 16px;font-size:13px}
@media print{.bar{display:none}}
"""

CHECKLISTS = {
    "Installation": ["Valid ID of customer presented", "Fiber drop cable installed",
                     "Router installed and powered on", "Signal / light levels checked",
                     "Speed test done", "Customer briefed on Wi-Fi name and password"],
    "Pull-out": ["Customer informed of the pull-out", "Router retrieved",
                 "Power adapter and accessories retrieved", "Fiber drop cable removed / secured",
                 "Router condition checked (Good / Defective)"],
    "Backjob": ["Customer complaint verified", "Cause of problem identified",
                "Problem fixed / part replaced", "Speed and signal test done",
                "Customer confirmed service is working"],
}

FORM_TITLES = {"Installation": "Installation Application Form",
               "Pull-out": "Router Pull-out Form",
               "Backjob": "Backjob (Return Visit) Form"}


def in_period(end_text, period):
    if period == "All time":
        return True
    try:
        end = parse_dt(end_text)
    except (ValueError, TypeError):
        return False
    now = datetime.now()
    if period == "Today":
        return end.date() == now.date()
    if period == "Last 7 days":
        return (now - end).days < 7
    if period == "This month":
        return (end.year, end.month) == (now.year, now.month)
    return True


class QueueMixin:

    # -------------------------------------------------
    # GENERIC QUEUE TAB (Installation / Pull-out / Backjob)
    # -------------------------------------------------

    def make_queue(self, kind):
        cfg = QUEUE_CFG[kind]
        parent = self.tabs[cfg["tab"]]
        self.heading(parent, cfg["title"], cfg["sub"])

        if kind == "Installation":
            first = [("Add Applicant", self.applicant_form, True),
                     ("Edit", self.edit_applicant)]
        elif kind == "Pull-out":
            first = [("Add Pull-outs", self.pullout_form, True)]
        else:
            first = [("New Backjob", self.backjob_form, True)]

        self.button_row(parent, first + [
            ("Assign to Technician", lambda: self.assign_queue(kind), True),
            ("Print Forms", lambda: self.print_selected_forms(kind)),
            ("Print List", lambda: self.print_queue_list(kind)),
            ("Select All", lambda: self.select_all(kind)),
            ("Clear Ticks", lambda: self.clear_ticks(kind)),
            ("Remove", lambda: self.remove_request(kind)),
            ("Refresh", lambda: self.refresh_queue(kind)),
        ])

        info = ttk.Frame(parent)
        info.pack(fill="x", pady=(0, 6))
        summary = ttk.Label(info, text="", font=("Segoe UI", 10, "bold"))
        summary.pack(side="left")
        picked = ttk.Label(info, text="Picked: 0", foreground=BLUE,
                           font=("Segoe UI", 10, "bold"))
        picked.pack(side="right")

        flt = self.filter_bar(parent, lambda: self.refresh_queue(kind),
                              REQUEST_STATUSES, default="Open", extra=("Open",))
        tree = self.create_tree(parent, cfg["cols"], cfg["heads"], cfg["widths"])

        self.queue_trees[kind] = tree
        self.queue_filters[kind] = flt
        self.queue_labels[kind] = (summary, picked)

        tree.bind("<Button-1>", lambda e: self.queue_click(kind, e))
        tree.bind("<space>", lambda e: self.queue_space(kind))

        if kind == "Installation":
            def on_double(event):
                if (tree.identify_region(event.x, event.y) == "cell"
                        and tree.identify_column(event.x) != "#2"):
                    self.edit_applicant()
            tree.bind("<Double-1>", on_double)

    def queue_values(self, kind, r, pos):
        if r["status"] in QUEUED:
            chk = "\u2611" if r["id"] in self.checked[kind] else "\u2610"
        else:
            chk = ""
        tech = r["tech"] or ""
        tail = (r["priority"], r["status"], r["queued_at"])
        if kind == "Installation":
            return (r["id"], chk, pos.get(r["id"], ""), r["ref"], r["customer"],
                    r["contact"], r["address"], r["lcp_code"] or "-", r["plan"],
                    tech) + tail
        head = (r["id"], chk, r["ref"], r["customer"], r["contact"], r["address"])
        if kind == "Pull-out":
            router = f"{r['router_name']} ({r['serial']})" if r["serial"] else ""
            return head + (router, r["reason"], tech) + tail
        return head + (r["source_ticket"] or "", r["reason"], tech) + tail

    def refresh_queue(self, kind):
        tree = self.queue_trees[kind]
        flt = self.queue_filters[kind]
        summary, picked = self.queue_labels[kind]

        rows = self.db.c.execute(REQUEST_SQL + " WHERE q.kind=?", (kind,)).fetchall()

        waiting = sorted((r for r in rows if r["status"] in QUEUED),
                         key=lambda r: (PRIORITY_RANK.get(r["priority"], 2), r["id"]))
        pos = {r["id"]: n for n, r in enumerate(waiting, 1)}

        rows.sort(key=lambda r: (0, pos[r["id"]]) if r["status"] in QUEUED
                  else (1, -r["id"]))

        self.checked[kind] &= {r["id"] for r in rows if r["status"] in QUEUED}

        shown = []
        for r in rows:
            values = self.queue_values(kind, r, pos)
            if flt.accepts(values, r["status"]):
                shown.append((values, tag_name(r["status"])))

        self.fill_tree(tree, shown)
        flt.show(len(shown), len(rows))

        counts = Counter(r["status"] for r in rows)
        summary.config(text="   ".join(
            f"{s}: {counts.get(s, 0)}" for s in REQUEST_STATUSES if s != "Cancelled"))
        picked.config(text=f"Picked: {len(self.checked[kind])}")

    def toggle_check(self, kind, iid):
        tree = self.queue_trees[kind]
        values = tree.item(iid, "values")
        if not values or str(values[1]) == "":
            return
        rid = int(values[0])
        self.checked[kind].symmetric_difference_update({rid})
        tree.set(iid, "chk", "\u2611" if rid in self.checked[kind] else "\u2610")
        self.queue_labels[kind][1].config(text=f"Picked: {len(self.checked[kind])}")

    def queue_click(self, kind, event):
        tree = self.queue_trees[kind]
        if tree.identify_region(event.x, event.y) != "cell":
            return
        if tree.identify_column(event.x) != "#2":
            return
        iid = tree.identify_row(event.y)
        if iid:
            self.toggle_check(kind, iid)

    def queue_space(self, kind):
        for iid in self.queue_trees[kind].selection():
            self.toggle_check(kind, iid)
        return "break"

    def select_all(self, kind):
        tree = self.queue_trees[kind]
        for iid in tree.get_children():
            values = tree.item(iid, "values")
            if str(values[1]) != "":
                self.checked[kind].add(int(values[0]))
                tree.set(iid, "chk", "\u2611")
        self.queue_labels[kind][1].config(text=f"Picked: {len(self.checked[kind])}")

    def clear_ticks(self, kind):
        self.checked[kind].clear()
        self.refresh_queue(kind)

    def queue_targets(self, kind):
        """Ticked names, or the highlighted row when nothing is ticked."""
        if self.checked[kind]:
            return sorted(self.checked[kind])
        selected = self.queue_trees[kind].selection()
        if selected:
            return [int(self.queue_trees[kind].item(selected[0], "values")[0])]
        return []

    def fetch_requests(self, ids):
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        return self.db.c.execute(
            REQUEST_SQL + f" WHERE q.id IN ({marks}) ORDER BY q.id", tuple(ids)).fetchall()

    def remove_request(self, kind):
        ids = self.queue_targets(kind)
        if not ids:
            messagebox.showwarning("Nothing Selected", "Tick or select the names to remove.")
            return
        rows = [r for r in self.fetch_requests(ids) if r["status"] in QUEUED]
        if not rows:
            messagebox.showwarning("Cannot Remove",
                                   "Only names still waiting in the queue can be removed.\n"
                                   "Dispatched jobs must be cancelled in Job Monitoring.")
            return
        if not messagebox.askyesno("Remove from Queue",
                                   f"Remove {len(rows)} name(s) from the {kind} list?"):
            return
        with self.db.c:
            for r in rows:
                self.db.c.execute("UPDATE requests SET status='Cancelled' WHERE id=?",
                                  (r["id"],))
                self.db.log("Administrator", f"{kind} Removed",
                            f"{r['ref']} - {r['customer']}")
        self.checked[kind].clear()
        self.refresh_all()

    # -------------------------------------------------
    # ASSIGN (dispatch from the queue)
    # -------------------------------------------------

    def assign_queue(self, kind):
        ids = sorted(self.checked[kind])
        if not ids:
            messagebox.showwarning("Nothing Ticked",
                                   "Tick the checkbox beside the names you want to assign.")
            return

        rows = self.fetch_requests(ids)
        ready = [r for r in rows if r["status"] == "Ready"]
        waiting = [r for r in rows if r["status"] == "Waiting LCP"]
        if not ready:
            messagebox.showwarning(
                "Nothing to Assign",
                "None of the ticked names are Ready.\n\nInstallations become Ready once "
                "their LCP is coordinated (see the LCP Coordination tab).")
            return

        techs = self.db.c.execute("""
            SELECT t.id, t.name,
                   (SELECT COUNT(*) FROM jobs j WHERE j.technician_id=t.id
                    AND j.status IN ('Dispatched','In Progress')) AS busy
            FROM technicians t WHERE t.active=1 ORDER BY busy, t.name
        """).fetchall()
        if not techs:
            messagebox.showerror("No Technician", "There are no active technicians available.")
            return

        if kind == "Installation":
            free = self.db.scalar("SELECT COUNT(*) FROM routers WHERE status='Available'")
            if free < len(ready):
                messagebox.showerror(
                    "Not Enough Routers",
                    f"{len(ready)} installation(s) need a router but only {free} are Available.\n"
                    "Untick some names or add routers in Router Inventory.")
                return

        win = self.modal(f"Assign {kind} Jobs", 620, 640)
        form = ttk.Frame(win, padding=20)
        form.pack(fill="both", expand=True)

        ttk.Label(form, text="Assign to Technician", style="Title.TLabel").pack(anchor="w")
        ttk.Label(form, text=f"{len(ready)} {kind.lower()} job(s) will be created:"
                  ).pack(anchor="w", pady=(8, 4))

        names = ttk.Treeview(form, columns=("customer", "address"), show="headings",
                             height=min(max(len(ready), 3), 8))
        names.heading("customer", text="Customer Name")
        names.heading("address", text="Address")
        names.column("customer", width=200)
        names.column("address", width=360)
        for r in ready:
            names.insert("", "end", values=(r["customer"], r["address"]))
        names.pack(fill="x")

        if waiting:
            ttk.Label(form, foreground=RED, wraplength=560,
                      text="Skipped (LCP not coordinated yet): "
                           + ", ".join(r["customer"] for r in waiting)).pack(anchor="w", pady=6)

        ttk.Label(form, text="Technician").pack(anchor="w", pady=(12, 2))
        tech_box = ttk.Combobox(form, state="readonly",
                                values=[f"{t['name']}  ({t['busy']} active)" for t in techs])
        tech_box.pack(fill="x")
        tech_box.current(0)

        auto_var = tk.BooleanVar(value=False)
        print_var = tk.BooleanVar(value=True)

        def sync_state():
            tech_box.config(state="disabled" if auto_var.get() else "readonly")

        ttk.Checkbutton(form, variable=auto_var, command=sync_state,
                        text="Spread evenly among all active technicians"
                        ).pack(anchor="w", pady=(10, 0))
        ttk.Checkbutton(form, variable=print_var,
                        text="Print the application forms after assigning"
                        ).pack(anchor="w", pady=(6, 0))

        def go():
            if kind == "Installation":
                over = self.db.lcp_overflow(ready)
                if over and not messagebox.askyesno(
                    "LCP Capacity",
                    "These LCPs would go over their port capacity:\n" + ", ".join(over)
                    + "\n\nAssign anyway?", parent=win
                ):
                    return

            tech_ids = ([t["id"] for t in techs] if auto_var.get()
                        else [techs[tech_box.current()]["id"]])
            try:
                with self.db.c:
                    made = self.db.assign_requests(kind, ready, tech_ids)
            except (ValueError, sqlite3.Error) as error:
                messagebox.showerror("Assign Failed", str(error), parent=win)
                return

            self.checked[kind].clear()
            self.refresh_all()
            win.destroy()

            per_tech = Counter(m["tech"] for m in made)
            messagebox.showinfo(
                "Assigned",
                f"{len(made)} job(s) dispatched.\n\n"
                + "\n".join(f"{n}: {c}" for n, c in per_tech.items()))
            if print_var.get():
                self.print_forms([m["request_id"] for m in made])

        row = ttk.Frame(form)
        row.pack(pady=20)
        ttk.Button(row, text="Assign & Dispatch", style="Accent.TButton",
                   command=go).pack(side="left", padx=5)
        ttk.Button(row, text="Cancel", command=win.destroy).pack(side="left", padx=5)

    # -------------------------------------------------
    # ADD / EDIT: applicant, pull-outs, backjob
    # -------------------------------------------------

    def edit_applicant(self):
        rid = self.selected_id(self.queue_trees["Installation"], "applicant")
        if rid is not None:
            self.applicant_form(rid)

    def applicant_form(self, request_id=None):
        row = None
        if request_id is not None:
            row = self.db.c.execute("SELECT * FROM requests WHERE id=?",
                                    (request_id,)).fetchone()
            if not row:
                self.refresh_all()
                return
            if row["status"] not in QUEUED:
                messagebox.showwarning("Locked", "Only names still waiting in the queue can be edited.")
                return

        lcps = self.db.c.execute("SELECT * FROM lcps ORDER BY code").fetchall()
        lcp_labels = ["-- Not yet assigned --"] + [
            f"{l['code']} - {l['area']}  ({'coordinated' if l['coordinated'] else 'NOT coordinated'})"
            for l in lcps]

        win = self.modal("Applicant", 500, 620)
        form = ttk.Frame(win, padding=20)
        form.pack(fill="both", expand=True)
        ttk.Label(form, text="Installation Applicant", style="Title.TLabel").pack(pady=(0, 6))

        fields = {}
        for text, key in (("Customer Name", "customer"), ("Contact Number", "contact"),
                          ("Installation Address", "address"), ("Plan / Package", "plan")):
            ttk.Label(form, text=text).pack(anchor="w", pady=(8, 2))
            entry = ttk.Entry(form)
            entry.pack(fill="x")
            if row:
                entry.insert(0, row[key] or "")
            fields[key] = entry
        fields["customer"].focus_set()

        ttk.Label(form, text="LCP").pack(anchor="w", pady=(8, 2))
        lcp_box = ttk.Combobox(form, state="readonly", values=lcp_labels)
        lcp_box.pack(fill="x")
        lcp_box.current(0)
        if row and row["lcp_id"]:
            for i, l in enumerate(lcps, 1):
                if l["id"] == row["lcp_id"]:
                    lcp_box.current(i)

        ttk.Label(form, text="Priority").pack(anchor="w", pady=(8, 2))
        priority = ttk.Combobox(form, state="readonly", values=PRIORITIES)
        priority.pack(fill="x")
        priority.set(row["priority"] if row else "Normal")

        ttk.Label(form, text="Notes").pack(anchor="w", pady=(8, 2))
        notes = tk.Text(form, height=4, width=40)
        notes.pack(fill="x")
        if row:
            notes.insert("1.0", row["notes"] or "")

        def save():
            customer = fields["customer"].get().strip()
            contact = fields["contact"].get().strip()
            address = fields["address"].get().strip()
            if not customer or not address:
                messagebox.showerror("Missing Information",
                                     "Customer name and address are required.", parent=win)
                return
            if contact and not PHONE_RE.match(contact):
                messagebox.showerror("Invalid Number", "Contact number looks invalid.", parent=win)
                return

            lcp_id = lcps[lcp_box.current() - 1]["id"] if lcp_box.current() > 0 else None

            dup = self.db.c.execute(
                "SELECT 1 FROM requests WHERE kind='Installation' AND lower(customer)=lower(?) "
                "AND lower(address)=lower(?) AND status IN ('Waiting LCP','Ready','Dispatched',"
                "'In Progress') AND id<>?", (customer, address, row["id"] if row else 0)
            ).fetchone()
            if dup and not messagebox.askyesno(
                "Possible Duplicate",
                "This customer and address is already in the queue.\nAdd anyway?", parent=win
            ):
                return

            with self.db.c:
                if row:
                    self.db.c.execute("""
                        UPDATE requests SET customer=?, contact=?, address=?, plan=?,
                               lcp_id=?, priority=?, notes=?, status=? WHERE id=?
                    """, (customer, contact, address, fields["plan"].get().strip(), lcp_id,
                          priority.get(), notes.get("1.0", "end").strip(),
                          self.db.queue_status("Installation", lcp_id), row["id"]))
                    self.db.log("Administrator", "Applicant Updated", f"{row['ref']} - {customer}")
                else:
                    _, ref = self.db.add_request(
                        "Installation", customer, contact, address,
                        plan=fields["plan"].get().strip(), lcp_id=lcp_id,
                        priority=priority.get(), notes=notes.get("1.0", "end").strip())
                    self.db.log("Administrator", "Applicant Queued", f"{ref} - {customer}")
            self.refresh_all()
            win.destroy()

        ttk.Button(form, text="Save Applicant", style="Accent.TButton",
                   command=save).pack(pady=15)

    def pullout_form(self):
        routers = self.db.c.execute("""
            SELECT id, brand, model, serial FROM routers
            WHERE status='In Use'
              AND id NOT IN (SELECT router_id FROM requests
                             WHERE kind='Pull-out' AND router_id IS NOT NULL
                               AND status IN ('Waiting LCP','Ready','Dispatched','In Progress'))
            ORDER BY serial
        """).fetchall()
        if not routers:
            messagebox.showinfo("Nothing to Pull Out",
                                "There are no installed (In Use) routers that are not already "
                                "on the pull-out list.")
            return

        info = {r["id"]: self.db.c.execute(LAST_INSTALL_SQL, (r["id"],)).fetchone()
                for r in routers}
        lcp_codes = {l["id"]: l["code"] for l in self.db.c.execute("SELECT id, code FROM lcps")}

        win = self.modal("Add Pull-outs", 880, 620, resizable=True)
        ttk.Label(win, text="Add Pull-outs", style="Title.TLabel").pack(anchor="w", padx=15, pady=(12, 0))
        ttk.Label(win, text="Tick the installed routers to retrieve, then add them to the pull-out list."
                  ).pack(anchor="w", padx=15)

        controls = ttk.Frame(win, padding=(15, 10))
        controls.pack(fill="x")
        ttk.Label(controls, text="Reason:").pack(side="left")
        reason_box = ttk.Combobox(controls, values=PULLOUT_REASONS, width=26)
        reason_box.pack(side="left", padx=(6, 14))
        reason_box.current(0)
        ttk.Label(controls, text="Priority:").pack(side="left")
        priority = ttk.Combobox(controls, values=PRIORITIES, state="readonly", width=10)
        priority.pack(side="left", padx=6)
        priority.current(0)

        bottom = ttk.Frame(win, padding=15)
        bottom.pack(side="bottom", fill="x")
        count = ttk.Label(bottom, text="Picked: 0", font=("Segoe UI", 10, "bold"))
        count.pack(side="left")

        holder = ttk.Frame(win, padding=(15, 0))
        holder.pack(fill="both", expand=True)
        tree = self.create_tree(
            holder, ("chk", "serial", "router", "customer", "address", "lcp"),
            ("Pick", "Serial No.", "Router", "Customer Name", "Address", "LCP"),
            (45, 120, 170, 170, 260, 80))

        picked = set()
        for r in routers:
            last = info[r["id"]]
            tree.insert("", "end", iid=str(r["id"]), values=(
                "\u2610", r["serial"], f"{r['brand']} {r['model']}",
                last["customer"] if last else "(unknown)",
                last["address"] if last else "",
                lcp_codes.get(last["lcp_id"], "-") if last else "-"))

        def refresh_count():
            count.config(text=f"Picked: {len(picked)}")

        def toggle(iid):
            rid = int(iid)
            picked.symmetric_difference_update({rid})
            tree.set(iid, "chk", "\u2611" if rid in picked else "\u2610")
            refresh_count()

        def click(event):
            if tree.identify_region(event.x, event.y) == "cell" \
                    and tree.identify_column(event.x) == "#1":
                iid = tree.identify_row(event.y)
                if iid:
                    toggle(iid)

        tree.bind("<Button-1>", click)

        def select_all():
            for iid in tree.get_children():
                picked.add(int(iid))
                tree.set(iid, "chk", "\u2611")
            refresh_count()

        def clear():
            picked.clear()
            for iid in tree.get_children():
                tree.set(iid, "chk", "\u2610")
            refresh_count()

        def add():
            if not picked:
                messagebox.showwarning("Nothing Ticked", "Tick at least one router.", parent=win)
                return
            reason = reason_box.get().strip() or "Pull-out"
            with self.db.c:
                for rid in sorted(picked):
                    last = info[rid]
                    self.db.add_request(
                        "Pull-out",
                        last["customer"] if last else "(unknown customer)",
                        (last["contact"] or "") if last else "",
                        last["address"] if last else "(unknown address)",
                        plan=(last["plan"] or "") if last else "",
                        lcp_id=last["lcp_id"] if last else None,
                        router_id=rid, reason=reason, priority=priority.get())
                self.db.log("Administrator", "Pull-outs Queued",
                            f"{len(picked)} router(s) - {reason}")
            self.refresh_all()
            win.destroy()

        ttk.Button(bottom, text="Add to Pull-out List", style="Accent.TButton",
                   command=add).pack(side="right", padx=4)
        ttk.Button(bottom, text="Clear", command=clear).pack(side="right", padx=4)
        ttk.Button(bottom, text="Select All", command=select_all).pack(side="right", padx=4)

    def backjob_from_completed(self):
        job_id = self.selected_id(self.completed_tree, "completed job")
        if job_id is not None:
            self.backjob_form(job_id)

    def backjob_form(self, source_job_id=None):
        jobs = self.db.c.execute("""
            SELECT j.* FROM jobs j
            WHERE j.status='Completed' AND j.job_type<>'Pull-out'
            ORDER BY j.id DESC
        """).fetchall()
        if not jobs:
            messagebox.showinfo("No Completed Jobs",
                                "A backjob is created from a completed installation. "
                                "There are none yet.")
            return
        if source_job_id is not None and source_job_id not in {j["id"] for j in jobs}:
            messagebox.showwarning("Not Allowed",
                                   "Backjobs can only be created from completed "
                                   "installation, troubleshooting or backjob visits.")
            return

        win = self.modal("New Backjob", 580, 640)
        form = ttk.Frame(win, padding=20)
        form.pack(fill="both", expand=True)
        ttk.Label(form, text="New Backjob", style="Title.TLabel").pack(pady=(0, 6))

        ttk.Label(form, text="Find original job (ticket, name or address)").pack(anchor="w", pady=(8, 2))
        needle = tk.StringVar()
        ttk.Entry(form, textvariable=needle).pack(fill="x")

        ttk.Label(form, text="Original completed job").pack(anchor="w", pady=(8, 2))
        job_box = ttk.Combobox(form, state="readonly")
        job_box.pack(fill="x")
        detail = ttk.Label(form, text="", foreground=GREY, wraplength=520)
        detail.pack(anchor="w", pady=(4, 0))

        view = []

        def show(event=None):
            if job_box.current() >= 0 and view:
                j = view[job_box.current()]
                detail.config(text=f"{j['customer']}  |  {j['contact'] or '-'}  |  "
                                   f"{j['address']}  |  finished {j['end_time']}")
            else:
                detail.config(text="")

        def reload(*_):
            text = needle.get().strip().lower()
            view[:] = [j for j in jobs
                       if text in f"{j['ticket']} {j['customer']} {j['address']}".lower()]
            job_box["values"] = [f"{j['ticket']} | {j['customer']} | {j['address'][:32]}"
                                 for j in view]
            if view:
                job_box.current(0)
            else:
                job_box.set("")
            show()

        needle.trace_add("write", reload)
        job_box.bind("<<ComboboxSelected>>", show)
        reload()
        if source_job_id is not None:
            for i, j in enumerate(view):
                if j["id"] == source_job_id:
                    job_box.current(i)
            show()

        ttk.Label(form, text="Reason for backjob").pack(anchor="w", pady=(10, 2))
        reason = ttk.Combobox(form, values=BACKJOB_REASONS)
        reason.pack(fill="x")
        reason.current(0)

        ttk.Label(form, text="Priority").pack(anchor="w", pady=(8, 2))
        priority = ttk.Combobox(form, state="readonly", values=PRIORITIES)
        priority.pack(fill="x")
        priority.current(1)

        ttk.Label(form, text="Details / customer complaint").pack(anchor="w", pady=(8, 2))
        notes = tk.Text(form, height=4, width=40)
        notes.pack(fill="x")

        def save():
            if not view or job_box.current() < 0:
                messagebox.showerror("No Job", "Select the original completed job.", parent=win)
                return
            why = reason.get().strip()
            if not why:
                messagebox.showerror("Missing Reason", "Enter the reason for the backjob.", parent=win)
                return
            src = view[job_box.current()]

            if self.db.c.execute(
                "SELECT 1 FROM requests WHERE kind='Backjob' AND source_job_id=? AND status "
                "IN ('Waiting LCP','Ready','Dispatched','In Progress')", (src["id"],)
            ).fetchone() and not messagebox.askyesno(
                "Backjob Exists", "This job already has an open backjob.\nCreate another?",
                parent=win
            ):
                return

            origin = (self.db.c.execute("SELECT lcp_id, plan FROM requests WHERE id=?",
                                        (src["request_id"],)).fetchone()
                      if src["request_id"] else None)
            with self.db.c:
                _, ref = self.db.add_request(
                    "Backjob", src["customer"], src["contact"] or "", src["address"],
                    plan=(origin["plan"] or "") if origin else "",
                    lcp_id=origin["lcp_id"] if origin else None,
                    router_id=src["router_id"], source_job_id=src["id"], reason=why,
                    priority=priority.get(), notes=notes.get("1.0", "end").strip())
                self.db.log("Administrator", "Backjob Queued",
                            f"{ref} - {src['customer']} ({src['ticket']}): {why}")
            self.refresh_all()
            win.destroy()

        ttk.Button(form, text="Create Backjob", style="Accent.TButton",
                   command=save).pack(pady=15)

    # -------------------------------------------------
    # LCP COORDINATION
    # -------------------------------------------------

    def make_lcp(self):
        parent = self.tabs["LCP Coordination"]
        self.heading(parent, "LCP Coordination",
                     "List of LCPs and whether they are coordinated. Applicants stay in "
                     "'Waiting LCP' until their LCP is coordinated.")

        self.button_row(parent, [
            ("Add LCP", self.lcp_form, True),
            ("Edit LCP", self.edit_lcp),
            ("Mark Coordinated / Not", self.toggle_lcp, True),
            ("Delete LCP", self.delete_lcp),
            ("Print List", self.print_lcp_list),
            ("Refresh", self.refresh_lcp),
        ])

        self.lcp_filter = self.filter_bar(parent, self.refresh_lcp,
                                          ["Coordinated", "Not Coordinated"],
                                          label="Coordination")
        self.lcp_tree = self.create_tree(
            parent,
            ("id", "code", "area", "state", "on", "coordinator", "capacity",
             "used", "free", "queued"),
            ("ID", "LCP Code", "Area / Barangay", "Coordination", "Coordinated On",
             "Coordinated With", "Ports", "Used", "Free", "Waiting in Queue"),
            (45, 100, 170, 120, 140, 150, 60, 60, 60, 120),
        )
        self.bind_open(self.lcp_tree, self.edit_lcp)

    def refresh_lcp(self):
        rows = self.db.c.execute("""
            SELECT l.*,
              (SELECT COUNT(*) FROM requests q WHERE q.lcp_id=l.id AND q.kind='Installation'
                 AND q.status IN ('Dispatched','In Progress','Completed')) AS used,
              (SELECT COUNT(*) FROM requests q WHERE q.lcp_id=l.id AND q.kind='Installation'
                 AND q.status IN ('Waiting LCP','Ready')) AS queued
            FROM lcps l ORDER BY l.coordinated DESC, l.code
        """).fetchall()

        shown = []
        for r in rows:
            state = "Coordinated" if r["coordinated"] else "Not Coordinated"
            values = (r["id"], r["code"], r["area"], state, r["coordinated_on"],
                      r["coordinator"], r["capacity"], r["used"],
                      r["capacity"] - r["used"], r["queued"])
            if self.lcp_filter.accepts(values, state):
                shown.append((values, tag_name(state)))
        self.fill_tree(self.lcp_tree, shown)
        self.lcp_filter.show(len(shown), len(rows))

    def edit_lcp(self):
        lcp_id = self.selected_id(self.lcp_tree, "LCP")
        if lcp_id is not None:
            self.lcp_form(lcp_id)

    def lcp_form(self, lcp_id=None):
        row = None
        if lcp_id is not None:
            row = self.db.c.execute("SELECT * FROM lcps WHERE id=?", (lcp_id,)).fetchone()
            if not row:
                self.refresh_all()
                return

        win = self.modal("LCP Information", 460, 470)
        ttk.Label(win, text="LCP Information", style="Title.TLabel").pack(pady=12)
        form = ttk.Frame(win, padding=15)
        form.pack(fill="both", expand=True)

        entries = {}
        for i, (text, key) in enumerate((("LCP Code", "code"), ("Area / Barangay", "area"),
                                         ("Capacity (ports)", "capacity"),
                                         ("Coordinated With", "coordinator"),
                                         ("Notes", "notes"))):
            ttk.Label(form, text=text).grid(row=i, column=0, sticky="w", pady=8)
            entry = ttk.Entry(form, width=30)
            entry.grid(row=i, column=1, padx=10, pady=8)
            if row:
                entry.insert(0, row[key] if row[key] is not None else "")
            elif key == "capacity":
                entry.insert(0, "16")
            entries[key] = entry
        entries["code"].focus_set()

        coordinated = tk.BooleanVar(value=bool(row and row["coordinated"]))
        ttk.Checkbutton(form, text="This LCP is coordinated", variable=coordinated
                        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=8)

        def save():
            code = entries["code"].get().strip()
            if not code:
                messagebox.showerror("Missing Code", "LCP code is required.", parent=win)
                return
            try:
                capacity = int(entries["capacity"].get().strip())
                if capacity < 1:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Invalid Capacity",
                                     "Capacity must be a whole number of 1 or more.", parent=win)
                return

            coord = 1 if coordinated.get() else 0
            was = row["coordinated"] if row else 0
            on = (row["coordinated_on"] if (row and was and coord) else
                  stamp() if coord else "")
            values = (code, entries["area"].get().strip(), capacity, coord, on,
                      entries["coordinator"].get().strip(), entries["notes"].get().strip())
            try:
                with self.db.c:
                    if row:
                        self.db.c.execute("""UPDATE lcps SET code=?, area=?, capacity=?,
                            coordinated=?, coordinated_on=?, coordinator=?, notes=?
                            WHERE id=?""", (*values, row["id"]))
                        saved_id = row["id"]
                    else:
                        saved_id = self.db.c.execute(
                            "INSERT INTO lcps(code,area,capacity,coordinated,coordinated_on,"
                            "coordinator,notes) VALUES(?,?,?,?,?,?,?)", values).lastrowid
                    self.db.apply_lcp_state(saved_id)
                    self.db.log("Administrator", "LCP Saved",
                                f"{code} ({'Coordinated' if coord else 'Not coordinated'})")
            except sqlite3.IntegrityError:
                messagebox.showerror("Duplicate", "That LCP code already exists.", parent=win)
                return
            self.refresh_all()
            win.destroy()

        win.bind("<Return>", lambda e: save())
        ttk.Button(form, text="Save LCP", style="Accent.TButton",
                   command=save).grid(row=6, column=0, columnspan=2, pady=16)

    def toggle_lcp(self):
        lcp_id = self.selected_id(self.lcp_tree, "LCP")
        if lcp_id is None:
            return
        row = self.db.c.execute("SELECT * FROM lcps WHERE id=?", (lcp_id,)).fetchone()
        new = 0 if row["coordinated"] else 1
        with self.db.c:
            self.db.c.execute("UPDATE lcps SET coordinated=?, coordinated_on=? WHERE id=?",
                              (new, stamp() if new else "", lcp_id))
            moved = self.db.apply_lcp_state(lcp_id)
            self.db.log("Administrator", "LCP Coordinated" if new else "LCP Un-coordinated",
                        row["code"])
        self.refresh_all()
        messagebox.showinfo(
            "LCP Updated",
            f"{row['code']} is now {'coordinated' if new else 'NOT coordinated'}.\n"
            f"{moved} applicant(s) moved to {'Ready' if new else 'Waiting LCP'}.")

    def delete_lcp(self):
        lcp_id = self.selected_id(self.lcp_tree, "LCP")
        if lcp_id is None:
            return
        row = self.db.c.execute("SELECT code FROM lcps WHERE id=?", (lcp_id,)).fetchone()
        if not messagebox.askyesno("Confirm Delete", f"Delete {row['code']}?"):
            return
        try:
            with self.db.c:
                self.db.c.execute("DELETE FROM lcps WHERE id=?", (lcp_id,))
                self.db.log("Administrator", "LCP Deleted", row["code"])
            self.refresh_all()
        except sqlite3.IntegrityError:
            messagebox.showerror("Cannot Delete",
                                 "Applicants are linked to this LCP, so it cannot be deleted.")

    # -------------------------------------------------
    # COMPLETED MONITORING
    # -------------------------------------------------

    def make_completed(self):
        parent = self.tabs["Completed"]
        self.heading(parent, "Completed Monitoring",
                     "Finished installations, pull-outs, backjobs and troubleshooting visits.")

        self.button_row(parent, [
            ("Job Details", lambda: self.open_job(self.completed_tree), True),
            ("Create Backjob", self.backjob_from_completed),
            ("Export CSV", self.export_completed),
            ("Print Report", self.print_completed),
            ("Refresh", self.refresh_completed),
        ])

        self.comp_summary = ttk.Label(parent, text="", font=("Segoe UI", 10, "bold"))
        self.comp_summary.pack(anchor="w", pady=(0, 6))

        self.comp_vars = {"search": tk.StringVar(), "type": tk.StringVar(value="All"),
                          "tech": tk.StringVar(value="All"),
                          "period": tk.StringVar(value="All time")}

        bar = ttk.Frame(parent)
        bar.pack(fill="x", pady=(0, 8))
        ttk.Label(bar, text="Search:").pack(side="left")
        ttk.Entry(bar, textvariable=self.comp_vars["search"], width=24
                  ).pack(side="left", padx=(6, 12))

        def combo(text, key, values, width):
            ttk.Label(bar, text=text).pack(side="left")
            box = ttk.Combobox(bar, textvariable=self.comp_vars[key], values=values,
                               state="readonly", width=width)
            box.pack(side="left", padx=(6, 12))
            box.bind("<<ComboboxSelected>>", lambda e: self.refresh_completed())
            return box

        combo("Type:", "type", ["All", *JOB_TYPES], 14)
        self.comp_tech_box = combo("Technician:", "tech", ["All"], 18)
        combo("Period:", "period", ["All time", "Today", "Last 7 days", "This month"], 12)

        def clear():
            self.comp_vars["search"].set("")
            self.comp_vars["type"].set("All")
            self.comp_vars["tech"].set("All")
            self.comp_vars["period"].set("All time")
            self.refresh_completed()

        ttk.Button(bar, text="Clear", command=clear).pack(side="left")
        self.comp_count = ttk.Label(bar, text="", foreground=GREY)
        self.comp_count.pack(side="right")
        self.comp_vars["search"].trace_add("write", lambda *a: self.refresh_completed())

        self.completed_rows = []
        self.completed_tree = self.create_tree(
            parent,
            ("id", "ticket", "type", "customer", "address", "lcp", "technician",
             "router", "start", "end", "duration"),
            ("ID", "Ticket", "Job Type", "Customer", "Address", "LCP", "Technician",
             "Router", "Start Time", "Completed", "Duration"),
            (45, 115, 105, 140, 180, 75, 120, 150, 135, 135, 80),
        )
        self.bind_open(self.completed_tree, lambda: self.open_job(self.completed_tree))

    def refresh_completed(self):
        names = [r[0] for r in self.db.c.execute("SELECT name FROM technicians ORDER BY name")]
        self.comp_tech_box["values"] = ["All", *names]

        rows = self.db.c.execute("""
            SELECT j.id, j.ticket, j.job_type, j.customer, j.address,
                   l.code AS lcp, t.name AS tech,
                   r.brand || ' ' || r.model || ' (' || r.serial || ')' AS router,
                   j.start_time, j.end_time, j.dispatch_time
            FROM jobs j
            JOIN technicians t ON j.technician_id=t.id
            JOIN routers r ON j.router_id=r.id
            LEFT JOIN requests q ON j.request_id=q.id
            LEFT JOIN lcps l ON q.lcp_id=l.id
            WHERE j.status='Completed'
            ORDER BY j.end_time DESC, j.id DESC
        """).fetchall()

        needle = self.comp_vars["search"].get().strip().lower()
        want_type = self.comp_vars["type"].get()
        want_tech = self.comp_vars["tech"].get()
        period = self.comp_vars["period"].get()

        shown, seconds = [], []
        for r in rows:
            if want_type != "All" and r["job_type"] != want_type:
                continue
            if want_tech != "All" and r["tech"] != want_tech:
                continue
            if not in_period(r["end_time"], period):
                continue
            duration = job_duration("Completed", r["dispatch_time"], r["start_time"],
                                    r["end_time"])
            values = (r["id"], r["ticket"], r["job_type"], r["customer"], r["address"],
                      r["lcp"] or "-", r["tech"], r["router"], r["start_time"],
                      r["end_time"], duration)
            if needle and needle not in " ".join(str(v) for v in values).lower():
                continue
            shown.append((values, tag_name("Completed")))
            try:
                seconds.append((parse_dt(r["end_time"]) - parse_dt(r["start_time"])).total_seconds())
            except (ValueError, TypeError):
                pass

        self.completed_rows = [v for v, _ in shown]
        self.fill_tree(self.completed_tree, shown)
        self.comp_count.config(text=f"Showing {len(shown)} of {len(rows)}")

        kinds = Counter(v[2] for v in self.completed_rows)
        text = f"Completed: {len(shown)}"
        for kind in JOB_TYPES:
            if kinds.get(kind):
                text += f"   |   {kind}: {kinds[kind]}"
        if seconds:
            text += f"   |   Average time on site: {fmt_duration(sum(seconds) / len(seconds))}"
        self.comp_summary.config(text=text)

    def export_completed(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV Files", "*.csv")],
            initialfile=f"completed_{datetime.now():%Y%m%d}.csv")
        if not path:
            return
        header = ["ID", "Ticket", "Job Type", "Customer", "Address", "LCP", "Technician",
                  "Router", "Start Time", "Completed", "Duration"]
        if self.write_csv(path, header, self.completed_rows):
            messagebox.showinfo("Export Complete", "Completed jobs exported successfully.")

    def print_completed(self):
        if not self.completed_rows:
            messagebox.showinfo("Nothing to Print", "There are no completed jobs in this view.")
            return
        e = html.escape
        head = ("Ticket", "Job Type", "Customer", "Address", "LCP", "Technician",
                "Completed", "Duration")
        body = "".join(
            "<tr>" + "".join(f"<td>{e(str(v[i]))}</td>" for i in (1, 2, 3, 4, 5, 6, 9, 10))
            + "</tr>" for v in self.completed_rows)
        page = (f"<div class='page'><div class='brand'>IMPERIAL NETWORK</div>"
                f"<h1>Completed Jobs Report</h1><p>{e(self.comp_summary.cget('text'))}<br>"
                f"Printed {stamp()}</p><table class='list'><tr>"
                + "".join(f"<th>{h}</th>" for h in head) + f"</tr>{body}</table></div>")
        self.open_printable("Completed Jobs Report", page)

    # -------------------------------------------------
    # DISPATCH EXTRAS
    # -------------------------------------------------

    def set_tech_filter(self, flt):
        if flt.combo2 is not None:
            flt.combo2["values"] = ["All", *[r[0] for r in self.db.c.execute(
                "SELECT name FROM technicians ORDER BY name")]]

    def reassign_job(self, tree):
        job_id = self.selected_id(tree, "job")
        if job_id is None:
            return
        job = self.db.job(job_id)
        if job["status"] not in ACTIVE_JOB:
            messagebox.showwarning("Cannot Reassign", "Only active jobs can be reassigned.")
            return

        techs = self.db.c.execute("""
            SELECT t.id, t.name,
                   (SELECT COUNT(*) FROM jobs j WHERE j.technician_id=t.id
                    AND j.status IN ('Dispatched','In Progress')) AS busy
            FROM technicians t WHERE t.active=1 ORDER BY t.name
        """).fetchall()
        labels = [f"{t['name']}  ({t['busy']} active)" for t in techs]
        current = next((i for i, t in enumerate(techs) if t["id"] == job["technician_id"]), 0)
        choice = self.ask_choice("Reassign Job",
                                 f"Assign {job['ticket']} ({job['customer']}) to:",
                                 labels, default=current)
        if choice is None:
            return
        new = techs[labels.index(choice)]
        if new["id"] == job["technician_id"]:
            return
        with self.db.c:
            self.db.c.execute("UPDATE jobs SET technician_id=? WHERE id=?", (new["id"], job_id))
            self.db.log("Administrator", "Job Reassigned",
                        f"{job['ticket']}: {job['tech_name']} -> {new['name']}")
        self.refresh_all()

    def print_job_form(self, tree):
        job_id = self.selected_id(tree, "job")
        if job_id is None:
            return
        job = self.db.job(job_id)
        if not job["request_id"]:
            messagebox.showinfo("No Application Record",
                                "This job was created with the manual New Dispatch, so it has "
                                "no application form. Use the queue tabs to print forms.")
            return
        self.print_forms([job["request_id"]])

    # -------------------------------------------------
    # PRINTING (opens the browser's print dialog automatically)
    # -------------------------------------------------

    def open_printable(self, title, body, auto_print=True):
        onload = ' onload="window.print()"' if auto_print else ""
        doc = (f"<!doctype html><html><head><meta charset='utf-8'>"
               f"<title>{html.escape(title)}</title><style>{PRINT_CSS}</style></head>"
               f"<body{onload}><div class='bar'><button onclick='window.print()'>Print</button>"
               f"</div>{body}</body></html>")
        path = Path(tempfile.gettempdir()) / f"techtrack_print_{datetime.now():%Y%m%d_%H%M%S}.html"
        try:
            path.write_text(doc, encoding="utf-8")
            if not webbrowser.open(path.as_uri()):
                messagebox.showinfo("Print", f"Open this file in your browser to print:\n{path}")
        except OSError as error:
            messagebox.showerror("Print Failed", str(error))

    def form_page(self, r):
        e = html.escape
        kind = r["kind"]

        def cell(value):
            return e(str(value or "")).replace("\n", "<br>")

        fields = [("Application No.", r["ref"]), ("Date Queued", r["queued_at"]),
                  ("Job Ticket", r["ticket"]), ("Customer Name", r["customer"]),
                  ("Contact No.", r["contact"]), ("Address", r["address"])]
        if kind == "Installation":
            lcp = f"{r['lcp_code']} - {r['lcp_area']}" if r["lcp_code"] else ""
            fields += [("Plan / Package", r["plan"]), ("LCP", lcp)]
        else:
            fields.append(("Reason", r["reason"]))
        if kind == "Backjob":
            fields.append(("Original Ticket", r["source_ticket"]))
        if r["serial"]:
            fields.append(("Router", f"{r['router_name']}  |  S/N {r['serial']}  |  MAC {r['mac']}"))
        fields += [("Priority", r["priority"]), ("Assigned Technician", r["tech"]),
                   ("Notes", r["notes"])]

        rows = "".join(f"<tr><th>{e(k)}</th><td>{cell(v)}</td></tr>" for k, v in fields)
        checks = "".join(f"<li>&#9744; {e(c)}</li>" for c in CHECKLISTS[kind])
        return (f"<div class='page'><div class='brand'>IMPERIAL NETWORK</div>"
                f"<h1>{FORM_TITLES[kind]}</h1><table>{rows}</table>"
                f"<h2>Technician Checklist</h2><ul class='chk'>{checks}</ul>"
                f"<span class='sig'>Customer signature over printed name / date</span>"
                f"<span class='sig'>Technician signature / date</span></div>")

    def print_forms(self, ids):
        rows = self.fetch_requests(ids)
        if not rows:
            messagebox.showwarning("Nothing to Print", "No application records were found.")
            return
        self.open_printable(f"Application Forms ({len(rows)})",
                            "".join(self.form_page(r) for r in rows))

    def print_selected_forms(self, kind):
        ids = self.queue_targets(kind)
        if not ids:
            messagebox.showwarning("Nothing Selected",
                                   "Tick the names (or highlight a row) to print their forms.")
            return
        self.print_forms(ids)

    def print_queue_list(self, kind):
        tree = self.queue_trees[kind]
        ids = [int(tree.item(i, "values")[0]) for i in tree.get_children()]
        if self.checked[kind]:
            ids = [i for i in ids if i in self.checked[kind]]
        by_id = {r["id"]: r for r in self.fetch_requests(ids)}
        rows = [by_id[i] for i in ids if i in by_id]
        if not rows:
            messagebox.showinfo("Nothing to Print", "There are no names in this list.")
            return

        e = html.escape
        if kind == "Installation":
            head = ("LCP", "Plan")
        elif kind == "Pull-out":
            head = ("Router", "Reason")
        else:
            head = ("Original Ticket", "Reason")

        def extra(r):
            if kind == "Installation":
                return r["lcp_code"] or "-", r["plan"]
            if kind == "Pull-out":
                return (f"{r['router_name']} ({r['serial']})" if r["serial"] else ""), r["reason"]
            return r["source_ticket"], r["reason"]

        body = ""
        for n, r in enumerate(rows, 1):
            a, b = extra(r)
            body += ("<tr>" + "".join(f"<td>{e(str(v or ''))}</td>" for v in (
                n, "\u2610", r["customer"], r["contact"], r["address"], a, b,
                r["tech"], r["status"])) + "</tr>")
        page = (f"<div class='page'><div class='brand'>IMPERIAL NETWORK</div>"
                f"<h1>{e(QUEUE_CFG[kind]['title'])}</h1><p>Printed {stamp()}  |  "
                f"{len(rows)} name(s)</p><table class='list'><tr>"
                + "".join(f"<th>{h}</th>" for h in ("No.", "", "Customer Name", "Contact",
                                                     "Address", head[0], head[1],
                                                     "Technician", "Status"))
                + f"</tr>{body}</table></div>")
        self.open_printable(f"{kind} List", page)

    def print_lcp_list(self):
        rows = self.db.c.execute("SELECT * FROM lcps ORDER BY coordinated DESC, code").fetchall()
        if not rows:
            messagebox.showinfo("Nothing to Print", "There are no LCPs yet.")
            return
        e = html.escape
        body = "".join(
            "<tr>" + "".join(f"<td>{e(str(v or ''))}</td>" for v in (
                r["code"], r["area"], "Coordinated" if r["coordinated"] else "NOT coordinated",
                r["coordinated_on"], r["coordinator"], r["capacity"])) + "</tr>"
            for r in rows)
        page = (f"<div class='page'><div class='brand'>IMPERIAL NETWORK</div>"
                f"<h1>List of LCP Coordination</h1><p>Printed {stamp()}</p>"
                f"<table class='list'><tr>"
                + "".join(f"<th>{h}</th>" for h in ("LCP", "Area", "Status", "Coordinated On",
                                                     "Coordinated With", "Ports"))
                + f"</tr>{body}</table></div>")
        self.open_printable("LCP Coordination List", page)


# -------------------------------------------------
# APPLICATION
# -------------------------------------------------

class App(QueueMixin, tk.Tk):

    def __init__(self):
        super().__init__()

        self.db = Store()

        self.title("Imperial Network | TechTrack")
        self.geometry("1320x800")
        self.minsize(1000, 640)
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.setup_style()
        self.setup_menu()
        self.setup_header()
        self.setup_statusbar()
        self.setup_tabs()

        self.queue_trees, self.queue_filters, self.queue_labels = {}, {}, {}
        self.checked = {kind: set() for kind in QUEUE_CFG}

        self.make_dashboard()
        for kind in QUEUE_CFG:
            self.make_queue(kind)
        self.make_lcp()
        self.make_dispatch()
        self.make_monitor()
        self.make_completed()
        self.make_inventory()
        self.make_techs()
        self.make_logs()

        self.bind("<F5>", lambda e: self.refresh_all())
        self.bind("<Control-n>", lambda e: self.new_dispatch())

        self.refresh_all()

    def on_close(self):
        try:
            self.db.c.close()
        finally:
            self.destroy()

    # -------------------------------------------------
    # STYLE / CHROME
    # -------------------------------------------------

    def setup_style(self):
        st = ttk.Style(self)
        st.theme_use("clam")

        st.configure("TFrame", background=BG)
        st.configure("TLabel", background=BG, foreground=NAVY, font=("Segoe UI", 10))
        st.configure("Title.TLabel", font=("Segoe UI", 21, "bold"))
        st.configure("Treeview", rowheight=28, font=("Segoe UI", 9))
        st.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))
        st.configure("TButton", padding=7)
        st.configure("Accent.TButton", background=BLUE, foreground=WHITE,
                     font=("Segoe UI", 9, "bold"))
        st.map("Accent.TButton",
               background=[("pressed", "#173f9e"), ("active", "#1d4fc4")])

    def setup_menu(self):
        bar = tk.Menu(self)

        file_menu = tk.Menu(bar, tearoff=0)
        file_menu.add_command(label="Back up database...", command=self.backup_db)
        file_menu.add_separator()
        file_menu.add_command(label="Export jobs (CSV)...", command=self.export_jobs)
        file_menu.add_command(label="Export logs (CSV)...", command=self.export_logs)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_close)
        bar.add_cascade(label="File", menu=file_menu)

        help_menu = tk.Menu(bar, tearoff=0)
        help_menu.add_command(label="Tips & shortcuts", command=self.show_tips)
        bar.add_cascade(label="Help", menu=help_menu)

        self.config(menu=bar)

    def show_tips(self):
        messagebox.showinfo(
            "Tips & shortcuts",
            "F5\t\tRefresh everything\n"
            "Ctrl+N\t\tNew dispatch\n"
            "Double-click\tEdit a router / technician, open job details\n"
            "Click a column heading to sort the table\n"
            "Use the Search box and dropdown above each table to filter\n\n"
            "Queues: tick the Pick column (or press Space) to choose names,\n"
            "then use Assign to Technician. Forms print automatically.\n\n"
            "Router rules:\n"
            "- Installation uses an Available router and marks it In Use\n"
            "- Pull-out uses an In Use router; on completion you choose its new status\n"
            "- Troubleshooting never changes router status"
        )

    def setup_header(self):
        header = tk.Frame(self, bg=NAVY, height=82)
        header.pack(fill="x")
        header.pack_propagate(False)

        tk.Label(header, text="IMPERIAL NETWORK", bg=NAVY, fg="#9db9e6",
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=22, pady=(10, 0))

        tk.Label(header, text="TECHTRACK  |  Technician & Inventory Monitoring",
                 bg=NAVY, fg=WHITE,
                 font=("Segoe UI", 19, "bold")).pack(anchor="w", padx=22)

    def setup_statusbar(self):
        bar = tk.Frame(self, bg=NAVY)
        bar.pack(side="bottom", fill="x")

        tk.Label(bar, text=f"Database: {DB}", bg=NAVY, fg="#9db9e6",
                 font=("Segoe UI", 8)).pack(side="left", padx=12, pady=3)

        self.clock = tk.Label(bar, text="", bg=NAVY, fg=WHITE, font=("Segoe UI", 8))
        self.clock.pack(side="right", padx=12)
        self.tick()

    def tick(self):
        self.clock.config(text=datetime.now().strftime("%A, %B %d, %Y   %I:%M:%S %p"))
        self.after(1000, self.tick)

    def setup_tabs(self):
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=18, pady=15)

        self.tabs = {}
        names = ["Dashboard", "Install Queue", "Pull-out List", "Backjobs",
                 "LCP Coordination", "Dispatch", "Job Monitoring", "Completed",
                 "Router Inventory", "Technicians", "Activity Logs"]

        for name in names:
            frame = ttk.Frame(self.nb, padding=12)
            self.nb.add(frame, text=name)
            self.tabs[name] = frame

    # -------------------------------------------------
    # COMMON WIDGET HELPERS
    # -------------------------------------------------

    def heading(self, parent, title, subtitle=None):
        ttk.Label(parent, text=title, style="Title.TLabel").pack(anchor="w", pady=(0, 5))
        if subtitle:
            ttk.Label(parent, text=subtitle).pack(anchor="w", pady=(0, 10))

    def button_row(self, parent, buttons):
        """buttons: list of (text, command, accent?)"""
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(0, 8))
        for text, command, *accent in buttons:
            ttk.Button(row, text=text, command=command,
                       style="Accent.TButton" if accent and accent[0] else "TButton"
                       ).pack(side="left", padx=3)
        return row

    def filter_bar(self, parent, callback, options=None, label="Status",
                   default="All", extra=(), options2=None, label2=""):
        bar = ttk.Frame(parent)
        bar.pack(fill="x", pady=(0, 8))

        ttk.Label(bar, text="Search:").pack(side="left")
        search = tk.StringVar()
        ttk.Entry(bar, textvariable=search, width=28).pack(side="left", padx=(6, 14))

        status = tk.StringVar(value=default)
        combo = None
        if options is not None:
            ttk.Label(bar, text=f"{label}:").pack(side="left")
            combo = ttk.Combobox(bar, textvariable=status, values=["All", *extra, *options],
                                 state="readonly", width=18)
            combo.pack(side="left", padx=6)
            combo.bind("<<ComboboxSelected>>", lambda e: callback())

        status2 = tk.StringVar(value="All")
        combo2 = None
        if options2 is not None:
            ttk.Label(bar, text=f"{label2}:").pack(side="left", padx=(10, 0))
            combo2 = ttk.Combobox(bar, textvariable=status2, values=["All", *options2],
                                  state="readonly", width=20)
            combo2.pack(side="left", padx=6)
            combo2.bind("<<ComboboxSelected>>", lambda e: callback())

        def clear():
            search.set("")
            status.set(default)
            status2.set("All")
            callback()

        ttk.Button(bar, text="Clear", command=clear).pack(side="left", padx=6)

        count = ttk.Label(bar, text="", foreground=GREY)
        count.pack(side="right")

        search.trace_add("write", lambda *a: callback())
        return Filter(search, status, count, combo, status2, combo2)

    def create_tree(self, parent, columns, headings, widths=None):
        container = ttk.Frame(parent)
        container.pack(fill="both", expand=True)

        tree = ttk.Treeview(container, columns=columns, show="headings",
                            selectmode="browse")

        for i, (col, title) in enumerate(zip(columns, headings)):
            tree.heading(col, text=title, command=lambda c=col: self.sort_tree(tree, c))
            tree.column(col, width=widths[i] if widths else 120, minwidth=50,
                        anchor="w" if col in LEFT_COLS else "center")

        vbar = ttk.Scrollbar(container, orient="vertical", command=tree.yview)
        hbar = ttk.Scrollbar(container, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set)

        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)
        tree.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")
        hbar.grid(row=1, column=0, sticky="ew")

        for status, colour in STATUS_COLORS.items():
            tree.tag_configure(tag_name(status), foreground=colour)
        tree.tag_configure("late", foreground=ORANGE)

        tree.sort_state = {}
        return tree

    def sort_tree(self, tree, col):
        reverse = tree.sort_state.get(col, False)
        items = [(tree.set(i, col), i) for i in tree.get_children("")]

        def key(item):
            try:
                return (0, float(item[0]), "")
            except ValueError:
                return (1, 0.0, str(item[0]).lower())

        items.sort(key=key, reverse=reverse)
        for index, (_, iid) in enumerate(items):
            tree.move(iid, "", index)
        tree.sort_state = {col: not reverse}

    def fill_tree(self, tree, rows):
        """rows: iterable of (values, tag). Keeps the current selection."""
        keep = {str(tree.item(i, "values")[0]) for i in tree.selection()}
        for item in tree.get_children():
            tree.delete(item)
        for values, tag in rows:
            iid = tree.insert("", "end", values=values, tags=(tag,) if tag else ())
            if str(values[0]) in keep:
                tree.selection_set(iid)

    def selected_id(self, tree, what="record"):
        selected = tree.selection()
        if not selected:
            messagebox.showwarning("Nothing Selected", f"Please select a {what} first.")
            return None
        return int(tree.item(selected[0], "values")[0])

    def bind_open(self, tree, handler):
        def on_double(event):
            if tree.identify_region(event.x, event.y) == "cell":
                handler()
        tree.bind("<Double-1>", on_double)
        tree.bind("<Return>", lambda e: handler())

    def modal(self, title, width, height, resizable=False):
        win = tk.Toplevel(self)
        win.title(title)
        win.configure(bg=BG)
        win.transient(self)
        x = self.winfo_x() + (self.winfo_width() - width) // 2
        y = self.winfo_y() + (self.winfo_height() - height) // 2
        win.geometry(f"{width}x{height}+{max(x, 0)}+{max(y, 0)}")
        win.resizable(resizable, resizable)
        win.bind("<Escape>", lambda e: win.destroy())
        win.update_idletasks()
        try:
            win.grab_set()
        except tk.TclError:
            pass
        return win

    def ask_choice(self, title, prompt, options, default=0):
        win = self.modal(title, 380, 200)
        result = {"value": None}

        ttk.Label(win, text=prompt, wraplength=340).pack(padx=20, pady=(20, 10), anchor="w")
        box = ttk.Combobox(win, values=options, state="readonly")
        box.current(default)
        box.pack(fill="x", padx=20)

        def ok():
            result["value"] = box.get()
            win.destroy()

        row = ttk.Frame(win)
        row.pack(pady=18)
        ttk.Button(row, text="OK", style="Accent.TButton", command=ok).pack(side="left", padx=5)
        ttk.Button(row, text="Cancel", command=win.destroy).pack(side="left", padx=5)

        self.wait_window(win)
        return result["value"]

    def write_csv(self, path, header, rows):
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as file:
                writer = csv.writer(file)
                writer.writerow(header)
                writer.writerows(tuple(r) for r in rows)
            return True
        except OSError as error:
            messagebox.showerror("Export Failed", str(error))
            return False

    def refresh_all(self):
        self.refresh_dashboard()
        for kind in QUEUE_CFG:
            self.refresh_queue(kind)
        self.refresh_lcp()
        self.refresh_dispatch()
        self.refresh_monitor()
        self.refresh_completed()
        self.refresh_inventory()
        self.refresh_techs()
        self.refresh_logs()

    # -------------------------------------------------
    # DASHBOARD
    # -------------------------------------------------

    def make_dashboard(self):
        parent = self.tabs["Dashboard"]

        self.heading(parent, "Dashboard",
                     "Overview of Imperial Network operations and monitoring.")

        self.button_row(parent, [
            ("Delete Selected Job",
             lambda: self.delete_job_from_tree(self.dashboard_tree)),
            ("Refresh", self.refresh_all),
        ])

        cards = ttk.Frame(parent)
        cards.pack(fill="x", pady=8)

        self.dashboard_values = {}
        card_data = [
            ("Install Queue", "queued", ORANGE),
            ("Open Pull-outs", "pullouts", PURPLE),
            ("Open Backjobs", "backjobs", RED),
            ("Active Jobs", "jobs", BLUE),
            ("Completed Jobs", "completed", GREEN),
            ("Routers Available", "available", GREEN),
            ("Routers In Use", "in_use", BLUE),
            ("Needs Attention", "attention", RED),
        ]

        for title, key, colour in card_data:
            card = tk.Frame(cards, bg=WHITE, highlightbackground="#dce3ee",
                            highlightthickness=1)
            card.pack(side="left", fill="both", expand=True, padx=4, ipady=10)

            tk.Label(card, text=title, bg=WHITE, fg=GREY,
                     font=("Segoe UI", 9)).pack(pady=(8, 4))

            value = tk.Label(card, text="0", bg=WHITE, fg=colour,
                             font=("Segoe UI", 20, "bold"))
            value.pack(pady=(0, 8))
            self.dashboard_values[key] = value

        body = ttk.Frame(parent)
        body.pack(fill="both", expand=True, pady=(14, 0))

        left = ttk.Frame(body)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))
        right = ttk.Frame(body)
        right.pack(side="left", fill="both", padx=(8, 0))

        ttk.Label(left, text="Recent Dispatch Activities",
                  font=("Segoe UI", 13, "bold")).pack(anchor="w", pady=(0, 8))
        self.dashboard_tree = self.create_tree(
            left,
            ("id", "ticket", "customer", "technician", "type", "status", "date"),
            ("ID", "Ticket", "Customer", "Technician", "Job Type", "Status", "Dispatch Date"),
            (45, 115, 150, 130, 105, 90, 140),
        )

        ttk.Label(right, text="Technician Workload",
                  font=("Segoe UI", 13, "bold")).pack(anchor="w", pady=(0, 8))
        self.workload_tree = self.create_tree(
            right,
            ("name", "active", "done"),
            ("Technician", "Active", "Completed"),
            (150, 65, 85),
        )

    def refresh_dashboard(self):
        db = self.db
        open_sql = "('Waiting LCP','Ready','Dispatched','In Progress')"
        values = {
            "queued": db.scalar("SELECT COUNT(*) FROM requests WHERE kind='Installation' "
                                "AND status IN ('Waiting LCP','Ready')"),
            "pullouts": db.scalar("SELECT COUNT(*) FROM requests WHERE kind='Pull-out' "
                                  f"AND status IN {open_sql}"),
            "backjobs": db.scalar("SELECT COUNT(*) FROM requests WHERE kind='Backjob' "
                                  f"AND status IN {open_sql}"),
            "jobs": db.scalar(
                "SELECT COUNT(*) FROM jobs WHERE status IN ('Dispatched','In Progress')"),
            "completed": db.scalar("SELECT COUNT(*) FROM jobs WHERE status='Completed'"),
            "available": db.scalar("SELECT COUNT(*) FROM routers WHERE status='Available'"),
            "in_use": db.scalar("SELECT COUNT(*) FROM routers WHERE status='In Use'"),
            "attention": db.scalar(
                "SELECT COUNT(*) FROM routers WHERE status IN ('Defective','Maintenance')"),
        }
        for key, value in values.items():
            self.dashboard_values[key].config(text=str(value))

        rows = db.c.execute("""
            SELECT jobs.id, jobs.ticket, jobs.customer, technicians.name,
                   jobs.job_type, jobs.status, jobs.dispatch_time
            FROM jobs
            JOIN technicians ON jobs.technician_id=technicians.id
            ORDER BY jobs.id DESC LIMIT 12
        """).fetchall()
        self.fill_tree(self.dashboard_tree,
                       [(tuple(r), tag_name(r["status"])) for r in rows])

        load = db.c.execute("""
            SELECT t.id, t.name,
                   COALESCE(SUM(CASE WHEN j.status IN ('Dispatched','In Progress')
                                     THEN 1 ELSE 0 END), 0) AS active_jobs,
                   COALESCE(SUM(CASE WHEN j.status='Completed' THEN 1 ELSE 0 END), 0) AS done
            FROM technicians t
            LEFT JOIN jobs j ON j.technician_id=t.id
            WHERE t.active=1
            GROUP BY t.id
            ORDER BY active_jobs DESC, t.name
        """).fetchall()
        # first column is used for selection tracking, so keep the name there
        self.fill_tree(self.workload_tree,
                       [((r["name"], r["active_jobs"], r["done"]), None) for r in load])

    # -------------------------------------------------
    # ROUTER INVENTORY
    # -------------------------------------------------

    def make_inventory(self):
        parent = self.tabs["Router Inventory"]

        self.heading(parent, "Router Inventory",
                     "Manage router equipment and inventory records.")

        self.button_row(parent, [
            ("Add Router", self.add_router, True),
            ("Edit Router", self.edit_router),
            ("Delete Router", self.delete_router),
            ("Router History", self.router_history),
            ("Import CSV", self.import_routers),
            ("Refresh", self.refresh_inventory),
        ])

        self.inv_filter = self.filter_bar(parent, self.refresh_inventory, ROUTER_STATUSES)

        self.inventory_tree = self.create_tree(
            parent,
            ("id", "brand", "model", "serial", "mac", "status", "installed"),
            ("ID", "Brand", "Model", "Serial Number", "MAC Address", "Status", "Installed At"),
            (50, 110, 130, 140, 150, 100, 200),
        )
        self.bind_open(self.inventory_tree, self.edit_router)

    def refresh_inventory(self):
        rows = self.db.c.execute("""
            SELECT r.*,
                   (SELECT j.customer FROM jobs j
                    WHERE j.router_id=r.id AND j.job_type='Installation'
                      AND j.status IN ('Dispatched','In Progress','Completed')
                    ORDER BY j.id DESC LIMIT 1) AS customer
            FROM routers r ORDER BY r.id DESC
        """).fetchall()

        shown = []
        for r in rows:
            where = (r["customer"] or "") if r["status"] == "In Use" else ""
            values = (r["id"], r["brand"], r["model"], r["serial"], r["mac"],
                      r["status"], where)
            if self.inv_filter.accepts(values, r["status"]):
                shown.append((values, tag_name(r["status"])))

        self.fill_tree(self.inventory_tree, shown)
        self.inv_filter.show(len(shown), len(rows))

    def add_router(self):
        self.router_form()

    def edit_router(self):
        router_id = self.selected_id(self.inventory_tree, "router")
        if router_id is not None:
            self.router_form(router_id)

    def router_form(self, router_id=None):
        row = None
        if router_id is not None:
            row = self.db.c.execute("SELECT * FROM routers WHERE id=?",
                                    (router_id,)).fetchone()
            if not row:
                messagebox.showerror("Not Found", "That router no longer exists.")
                self.refresh_all()
                return

        win = self.modal("Router Information", 440, 440)

        ttk.Label(win, text="Router Information", style="Title.TLabel").pack(pady=15)
        form = ttk.Frame(win, padding=15)
        form.pack(fill="both", expand=True)

        fields = [("Brand", "brand"), ("Model", "model"),
                  ("Serial Number", "serial"), ("MAC Address", "mac")]
        entries = {}

        for i, (label, key) in enumerate(fields):
            ttk.Label(form, text=label).grid(row=i, column=0, sticky="w", pady=10)
            entry = ttk.Entry(form, width=30)
            entry.grid(row=i, column=1, pady=10, padx=10)
            if row:
                entry.insert(0, row[key] or "")
            entries[key] = entry
        entries["brand"].focus_set()

        ttk.Label(form, text="Status").grid(row=4, column=0, sticky="w", pady=10)
        status = ttk.Combobox(form, values=ROUTER_STATUSES, state="readonly", width=27)
        status.grid(row=4, column=1, pady=10, padx=10)
        status.set(row["status"] if row else "Available")

        def save():
            brand = entries["brand"].get().strip()
            model = entries["model"].get().strip()
            serial = entries["serial"].get().strip()
            mac = normalize_mac(entries["mac"].get())

            if not (brand and model and serial):
                messagebox.showerror("Missing Information",
                                     "Brand, model and serial number are required.",
                                     parent=win)
                return
            if mac is None:
                messagebox.showerror("Invalid MAC",
                                     "MAC address must look like AA:BB:CC:DD:EE:FF.",
                                     parent=win)
                return

            try:
                with self.db.c:
                    if row:
                        self.db.c.execute("""
                            UPDATE routers
                            SET brand=?, model=?, serial=?, mac=?, status=?
                            WHERE id=?
                        """, (brand, model, serial, mac, status.get(), row["id"]))
                        self.db.log("Administrator", "Router Updated",
                                    f"{serial} ({status.get()})")
                    else:
                        self.db.c.execute("""
                            INSERT INTO routers(brand,model,serial,mac,status)
                            VALUES(?,?,?,?,?)
                        """, (brand, model, serial, mac, status.get()))
                        self.db.log("Administrator", "Router Added", serial)
            except sqlite3.IntegrityError:
                messagebox.showerror("Duplicate Serial",
                                     "This serial number already exists.", parent=win)
                return

            self.refresh_all()
            win.destroy()

        win.bind("<Return>", lambda e: save())
        ttk.Button(form, text="Save Router", style="Accent.TButton",
                   command=save).grid(row=5, column=0, columnspan=2, pady=20)

    def delete_router(self):
        router_id = self.selected_id(self.inventory_tree, "router")
        if router_id is None:
            return

        row = self.db.c.execute("SELECT * FROM routers WHERE id=?", (router_id,)).fetchone()
        if not row:
            self.refresh_all()
            return

        if not messagebox.askyesno("Confirm Delete", f"Delete router {row['serial']}?"):
            return

        try:
            with self.db.c:
                self.db.c.execute("DELETE FROM routers WHERE id=?", (router_id,))
                self.db.log("Administrator", "Router Deleted", row["serial"])
            self.refresh_all()
        except sqlite3.IntegrityError:
            messagebox.showerror(
                "Cannot Delete",
                "This router is linked to a job and cannot be deleted.\n"
                "Set its status to Defective or Maintenance instead."
            )

    def router_history(self):
        router_id = self.selected_id(self.inventory_tree, "router")
        if router_id is None:
            return

        router = self.db.c.execute("SELECT * FROM routers WHERE id=?",
                                   (router_id,)).fetchone()
        rows = self.db.c.execute("""
            SELECT j.id, j.ticket, j.job_type, j.customer, t.name, j.status,
                   j.dispatch_time, j.end_time
            FROM jobs j JOIN technicians t ON j.technician_id=t.id
            WHERE j.router_id=? ORDER BY j.id DESC
        """, (router_id,)).fetchall()

        win = self.modal(f"History - {router['serial']}", 860, 420, resizable=True)
        ttk.Label(win, text=f"{router['brand']} {router['model']}  ({router['serial']})",
                  font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=15, pady=(15, 5))
        ttk.Label(win, text=f"Current status: {router['status']}").pack(anchor="w", padx=15)

        holder = ttk.Frame(win, padding=15)
        holder.pack(fill="both", expand=True)
        tree = self.create_tree(
            holder,
            ("id", "ticket", "type", "customer", "technician", "status", "date", "end"),
            ("ID", "Ticket", "Job Type", "Customer", "Technician", "Status",
             "Dispatched", "Ended"),
            (45, 115, 105, 150, 120, 85, 135, 135),
        )
        self.fill_tree(tree, [(tuple(r), tag_name(r["status"])) for r in rows])
        if not rows:
            ttk.Label(win, text="No jobs recorded for this router yet.").pack(pady=(0, 10))

    def import_routers(self):
        path = filedialog.askopenfilename(
            title="Import routers",
            filetypes=[("CSV Files", "*.csv")]
        )
        if not path:
            return

        added = duplicates = invalid = 0
        try:
            with open(path, newline="", encoding="utf-8-sig") as file:
                reader = csv.DictReader(file)
                with self.db.c:
                    for raw in reader:
                        row = {k.strip().lower(): (v or "").strip()
                               for k, v in raw.items() if k}
                        brand = row.get("brand", "")
                        model = row.get("model", "")
                        serial = row.get("serial", "") or row.get("serial number", "")
                        mac = normalize_mac(row.get("mac", "") or row.get("mac address", ""))
                        status = row.get("status", "") or "Available"
                        if status not in ROUTER_STATUSES:
                            status = "Available"

                        if not (brand and model and serial) or mac is None:
                            invalid += 1
                            continue

                        cur = self.db.c.execute(
                            "INSERT OR IGNORE INTO routers(brand,model,serial,mac,status) "
                            "VALUES(?,?,?,?,?)",
                            (brand, model, serial, mac, status)
                        )
                        if cur.rowcount:
                            added += 1
                        else:
                            duplicates += 1

                    self.db.log("Administrator", "Routers Imported",
                                f"{added} added from {Path(path).name}")
        except (OSError, csv.Error, UnicodeDecodeError) as error:
            messagebox.showerror("Import Failed", str(error))
            return

        self.refresh_all()
        messagebox.showinfo(
            "Import Complete",
            f"Added: {added}\nDuplicate serials skipped: {duplicates}\n"
            f"Invalid rows skipped: {invalid}\n\n"
            "Expected columns: brand, model, serial, mac, status (mac/status optional)."
        )

    # -------------------------------------------------
    # TECHNICIANS
    # -------------------------------------------------

    def make_techs(self):
        parent = self.tabs["Technicians"]

        self.heading(parent, "Technicians",
                     "Manage technician information and availability.")

        self.button_row(parent, [
            ("Add Technician", self.add_tech, True),
            ("Edit Technician", self.edit_tech),
            ("Activate / Deactivate", self.toggle_tech),
            ("Refresh", self.refresh_techs),
        ])

        self.tech_filter = self.filter_bar(parent, self.refresh_techs, ["Active", "Inactive"])

        self.tech_tree = self.create_tree(
            parent,
            ("id", "name", "phone", "status", "active", "done"),
            ("ID", "Technician Name", "Contact Number", "Status", "Active Jobs",
             "Completed Jobs"),
            (50, 220, 140, 90, 100, 120),
        )
        self.bind_open(self.tech_tree, self.edit_tech)

    def refresh_techs(self):
        rows = self.db.c.execute("""
            SELECT t.id, t.name, t.phone, t.active,
                   (SELECT COUNT(*) FROM jobs j WHERE j.technician_id=t.id
                    AND j.status IN ('Dispatched','In Progress')) AS active_jobs,
                   (SELECT COUNT(*) FROM jobs j WHERE j.technician_id=t.id
                    AND j.status='Completed') AS done
            FROM technicians t ORDER BY t.active DESC, t.name
        """).fetchall()

        shown = []
        for r in rows:
            label = "Active" if r["active"] else "Inactive"
            values = (r["id"], r["name"], r["phone"], label, r["active_jobs"], r["done"])
            if self.tech_filter.accepts(values, label):
                shown.append((values, tag_name(label)))

        self.fill_tree(self.tech_tree, shown)
        self.tech_filter.show(len(shown), len(rows))

    def add_tech(self):
        self.tech_form()

    def edit_tech(self):
        tech_id = self.selected_id(self.tech_tree, "technician")
        if tech_id is not None:
            self.tech_form(tech_id)

    def tech_form(self, tech_id=None):
        row = None
        if tech_id is not None:
            row = self.db.c.execute("SELECT * FROM technicians WHERE id=?",
                                    (tech_id,)).fetchone()
            if not row:
                self.refresh_all()
                return

        win = self.modal("Technician Information", 420, 300)
        form = ttk.Frame(win, padding=20)
        form.pack(fill="both", expand=True)

        ttk.Label(form, text="Technician Information",
                  style="Title.TLabel").pack(pady=10)

        ttk.Label(form, text="Full Name").pack(anchor="w")
        name = ttk.Entry(form, width=40)
        name.pack(fill="x", pady=5)
        name.focus_set()

        ttk.Label(form, text="Contact Number").pack(anchor="w")
        phone = ttk.Entry(form, width=40)
        phone.pack(fill="x", pady=5)

        if row:
            name.insert(0, row["name"])
            phone.insert(0, row["phone"] or "")

        def save():
            n = name.get().strip()
            p = phone.get().strip()

            if not n:
                messagebox.showerror("Error", "Name is required.", parent=win)
                return
            if p and not PHONE_RE.match(p):
                messagebox.showerror("Invalid Number",
                                     "Contact number should contain digits only "
                                     "(+, -, spaces and brackets are allowed).",
                                     parent=win)
                return

            dup = self.db.c.execute(
                "SELECT 1 FROM technicians WHERE lower(name)=lower(?) AND id<>?",
                (n, row["id"] if row else 0)
            ).fetchone()
            if dup:
                messagebox.showerror("Duplicate", "A technician with that name already exists.",
                                     parent=win)
                return

            with self.db.c:
                if row:
                    self.db.c.execute("UPDATE technicians SET name=?, phone=? WHERE id=?",
                                      (n, p, row["id"]))
                    self.db.log("Administrator", "Technician Updated", n)
                else:
                    self.db.c.execute("INSERT INTO technicians(name,phone) VALUES(?,?)",
                                      (n, p))
                    self.db.log("Administrator", "Technician Added", n)

            self.refresh_all()
            win.destroy()

        win.bind("<Return>", lambda e: save())
        ttk.Button(form, text="Save Technician", style="Accent.TButton",
                   command=save).pack(pady=15)

    def toggle_tech(self):
        tech_id = self.selected_id(self.tech_tree, "technician")
        if tech_id is None:
            return

        tech = self.db.c.execute("SELECT * FROM technicians WHERE id=?",
                                 (tech_id,)).fetchone()
        new_status = 0 if tech["active"] else 1

        if not new_status:
            active_jobs = self.db.scalar(
                "SELECT COUNT(*) FROM jobs WHERE technician_id=? "
                "AND status IN ('Dispatched','In Progress')", (tech_id,))
            if active_jobs and not messagebox.askyesno(
                "Active Jobs",
                f"{tech['name']} still has {active_jobs} active job(s).\n"
                "Deactivate anyway? (Existing jobs stay assigned.)"
            ):
                return

        with self.db.c:
            self.db.c.execute("UPDATE technicians SET active=? WHERE id=?",
                              (new_status, tech_id))
            self.db.log("Administrator",
                        "Technician Activated" if new_status else "Technician Deactivated",
                        tech["name"])
        self.refresh_all()

    # -------------------------------------------------
    # DISPATCH
    # -------------------------------------------------

    def make_dispatch(self):
        parent = self.tabs["Dispatch"]

        self.heading(parent, "Job Dispatch",
                     "Create and assign installation, pull-out or troubleshooting jobs.")

        self.button_row(parent, [
            ("New Dispatch", self.new_dispatch, True),
            ("Job Details", lambda: self.open_job(self.dispatch_tree)),
            ("Reassign", lambda: self.reassign_job(self.dispatch_tree)),
            ("Print Form", lambda: self.print_job_form(self.dispatch_tree)),
            ("Export CSV", self.export_jobs),
            ("Delete Selected", lambda: self.delete_job_from_tree(self.dispatch_tree)),
            ("Refresh", self.refresh_dispatch),
        ])

        self.dispatch_filter = self.filter_bar(parent, self.refresh_dispatch, JOB_STATUSES,
                                               options2=[], label2="Technician")

        self.dispatch_tree = self.create_tree(
            parent,
            ("id", "ticket", "customer", "address", "technician", "router",
             "type", "priority", "status", "date"),
            ("ID", "Ticket", "Customer", "Address", "Technician", "Router",
             "Job Type", "Priority", "Status", "Dispatch Time"),
            (45, 115, 130, 190, 120, 130, 100, 70, 85, 135),
        )
        self.bind_open(self.dispatch_tree, lambda: self.open_job(self.dispatch_tree))

    def refresh_dispatch(self):
        self.set_tech_filter(self.dispatch_filter)
        rows = self.db.c.execute("""
            SELECT jobs.id, jobs.ticket, jobs.customer, jobs.address,
                   technicians.name,
                   routers.brand || ' ' || routers.model,
                   jobs.job_type, jobs.priority, jobs.status, jobs.dispatch_time
            FROM jobs
            JOIN technicians ON jobs.technician_id=technicians.id
            JOIN routers ON jobs.router_id=routers.id
            ORDER BY jobs.id DESC
        """).fetchall()

        shown = []
        for r in rows:
            values = tuple(r)
            if self.dispatch_filter.accepts(values, r["status"], r["name"]):
                tag = "late" if is_late(r["status"], r["dispatch_time"]) else tag_name(r["status"])
                shown.append((values, tag))

        self.fill_tree(self.dispatch_tree, shown)
        self.dispatch_filter.show(len(shown), len(rows))

    def open_job(self, tree):
        job_id = self.selected_id(tree, "job")
        if job_id is not None:
            self.job_details(job_id)

    def new_dispatch(self):
        techs = self.db.c.execute("""
            SELECT t.id, t.name,
                   (SELECT COUNT(*) FROM jobs j WHERE j.technician_id=t.id
                    AND j.status IN ('Dispatched','In Progress')) AS busy
            FROM technicians t WHERE t.active=1 ORDER BY busy, t.name
        """).fetchall()

        if not techs:
            messagebox.showerror("No Technician",
                                 "There are no active technicians available.")
            return

        win = self.modal("New Dispatch", 520, 740)
        form = ttk.Frame(win, padding=20)
        form.pack(fill="both", expand=True)

        ttk.Label(form, text="Create New Dispatch", style="Title.TLabel").pack(pady=(0, 6))

        fields = {}
        auto = {}          # remembers values we auto-filled for pull-outs
        router_rows = []   # routers currently listed in the combobox

        def label(text):
            ttk.Label(form, text=text).pack(anchor="w", pady=(8, 2))

        label("Job Type")
        type_box = ttk.Combobox(form, state="readonly", values=JOB_TYPES)
        type_box.pack(fill="x")
        type_box.current(0)

        for text, key in (("Customer Name", "customer"), ("Contact Number", "contact"),
                          ("Installation Address", "address")):
            label(text)
            entry = ttk.Entry(form)
            entry.pack(fill="x")
            fields[key] = entry
        fields["customer"].focus_set()

        label("Assigned Technician")
        tech_box = ttk.Combobox(
            form, state="readonly",
            values=[f"{t['name']}  ({t['busy']} active)" for t in techs]
        )
        tech_box.pack(fill="x")
        tech_box.current(0)

        label("Assigned Router")
        router_box = ttk.Combobox(form, state="readonly")
        router_box.pack(fill="x")
        hint = ttk.Label(form, text="", foreground=RED)
        hint.pack(anchor="w")

        label("Priority")
        priority_box = ttk.Combobox(form, state="readonly", values=PRIORITIES)
        priority_box.pack(fill="x")
        priority_box.current(0)

        label("Notes")
        notes = tk.Text(form, height=4, width=40)
        notes.pack(fill="x")

        def fill_from_install():
            """For pull-outs, pre-fill customer details from the router's last install."""
            if type_box.get() != "Pull-out" or router_box.current() < 0 or not router_rows:
                return
            last = self.db.c.execute("""
                SELECT customer, contact, address FROM jobs
                WHERE router_id=? AND job_type='Installation' AND status='Completed'
                ORDER BY id DESC LIMIT 1
            """, (router_rows[router_box.current()]["id"],)).fetchone()
            if not last:
                return
            for key in ("customer", "contact", "address"):
                current = fields[key].get().strip()
                if not current or current == auto.get(key):
                    value = last[key] or ""
                    fields[key].delete(0, "end")
                    fields[key].insert(0, value)
                    auto[key] = value

        def load_routers(event=None):
            job_type = type_box.get()
            if job_type == "Installation":
                where = "status='Available'"
            elif job_type == "Pull-out":
                where = "status='In Use'"
            else:
                where = "1=1"

            router_rows[:] = self.db.c.execute(
                f"SELECT id,brand,model,serial,status FROM routers WHERE {where} "
                "ORDER BY brand, model, serial"
            ).fetchall()

            labels = []
            for r in router_rows:
                text = f"{r['brand']} {r['model']} ({r['serial']})"
                if job_type == "Troubleshooting":
                    text += f" - {r['status']}"
                labels.append(text)

            router_box.config(values=labels)
            if labels:
                router_box.current(0)
                hint.config(text="")
            else:
                router_box.set("")
                hint.config(text="No router available for this job type.")
            fill_from_install()

        type_box.bind("<<ComboboxSelected>>", load_routers)
        router_box.bind("<<ComboboxSelected>>", lambda e: fill_from_install())
        load_routers()

        def save():
            customer = fields["customer"].get().strip()
            contact = fields["contact"].get().strip()
            address = fields["address"].get().strip()
            job_type = type_box.get()

            if not customer or not address:
                messagebox.showerror("Missing Information",
                                     "Customer name and address are required.", parent=win)
                return
            if contact and not PHONE_RE.match(contact):
                messagebox.showerror("Invalid Number",
                                     "Contact number looks invalid.", parent=win)
                return
            if not router_rows or router_box.current() < 0:
                messagebox.showerror("No Router",
                                     "There is no router available for this job type.",
                                     parent=win)
                return

            tech = techs[tech_box.current()]
            router_id = router_rows[router_box.current()]["id"]

            if job_type == "Pull-out" and self.db.c.execute(
                "SELECT 1 FROM jobs WHERE router_id=? AND job_type='Pull-out' "
                "AND status IN ('Dispatched','In Progress')", (router_id,)
            ).fetchone():
                messagebox.showerror("Already Dispatched",
                                     "This router already has an active pull-out job.",
                                     parent=win)
                return

            try:
                with self.db.c:
                    ticket = self.db.next_ticket(job_type)
                    self.db.c.execute("""
                        INSERT INTO jobs(
                            ticket, customer, contact, address,
                            technician_id, router_id, job_type,
                            status, dispatch_time, notes, priority
                        )
                        VALUES(?,?,?,?,?,?,?,?,?,?,?)
                    """, (ticket, customer, contact, address, tech["id"], router_id,
                          job_type, "Dispatched", stamp(),
                          notes.get("1.0", "end").strip(), priority_box.get()))

                    if job_type == "Installation":
                        self.db.c.execute(
                            "UPDATE routers SET status='In Use' WHERE id=?", (router_id,))

                    self.db.log("Administrator", "Job Dispatched",
                                f"{ticket} - {customer} [{tech['name']}]")
            except sqlite3.Error as error:
                messagebox.showerror("Database Error", str(error), parent=win)
                return

            self.refresh_all()
            win.destroy()
            messagebox.showinfo("Dispatch Successful", f"Job {ticket} has been dispatched.")

        ttk.Button(form, text="Create Dispatch", style="Accent.TButton",
                   command=save).pack(pady=15)

    def job_details(self, job_id):
        job = self.db.job(job_id)
        if not job:
            messagebox.showerror("Not Found", "That job no longer exists.")
            self.refresh_all()
            return

        editable = job["status"] in ACTIVE_JOB
        win = self.modal(f"Job {job['ticket']}", 580, 700, resizable=True)
        frame = ttk.Frame(win, padding=20)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text=job["ticket"], style="Title.TLabel").pack(anchor="w")

        grid = ttk.Frame(frame)
        grid.pack(fill="x", pady=10)

        info = [
            ("Status", job["status"]),
            ("Priority", job["priority"] or "Normal"),
            ("Job Type", job["job_type"]),
            ("Customer", job["customer"]),
            ("Contact", job["contact"] or "-"),
            ("Address", job["address"]),
            ("Router", f"{job['router_name']} ({job['serial']})"),
            ("MAC", job["mac"] or "-"),
            ("Dispatched", job["dispatch_time"]),
            ("Started", job["start_time"] or "-"),
            ("Ended", job["end_time"] or "-"),
            ("Duration", job_duration(job["status"], job["dispatch_time"],
                                      job["start_time"], job["end_time"]) or "-"),
        ]
        for i, (key, value) in enumerate(info):
            ttk.Label(grid, text=f"{key}:", font=("Segoe UI", 10, "bold")
                      ).grid(row=i, column=0, sticky="nw", padx=(0, 12), pady=2)
            ttk.Label(grid, text=value, wraplength=380
                      ).grid(row=i, column=1, sticky="w", pady=2)

        row = len(info)
        ttk.Label(grid, text="Technician:", font=("Segoe UI", 10, "bold")
                  ).grid(row=row, column=0, sticky="nw", padx=(0, 12), pady=6)

        techs = self.db.c.execute(
            "SELECT id,name FROM technicians WHERE active=1 OR id=? ORDER BY name",
            (job["technician_id"],)
        ).fetchall()
        tech_box = ttk.Combobox(grid, state="readonly" if editable else "disabled",
                                values=[t["name"] for t in techs], width=28)
        tech_box.grid(row=row, column=1, sticky="w", pady=6)
        for i, t in enumerate(techs):
            if t["id"] == job["technician_id"]:
                tech_box.current(i)

        ttk.Label(frame, text="Notes:", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        notes = tk.Text(frame, height=6, width=50)
        notes.pack(fill="both", expand=True, pady=(2, 10))
        notes.insert("1.0", job["notes"] or "")

        def save():
            new_tech = techs[tech_box.current()]
            new_notes = notes.get("1.0", "end").strip()
            with self.db.c:
                self.db.c.execute(
                    "UPDATE jobs SET notes=?, technician_id=? WHERE id=?",
                    (new_notes, new_tech["id"], job_id))
                if new_tech["id"] != job["technician_id"]:
                    self.db.log("Administrator", "Job Reassigned",
                                f"{job['ticket']}: {job['tech_name']} -> {new_tech['name']}")
                elif new_notes != (job["notes"] or ""):
                    self.db.log(job["tech_name"], "Job Notes Updated", job["ticket"])
            self.refresh_all()
            win.destroy()

        buttons = ttk.Frame(frame)
        buttons.pack()
        ttk.Button(buttons, text="Save Changes", style="Accent.TButton",
                   command=save).pack(side="left", padx=5)
        ttk.Button(buttons, text="Close", command=win.destroy).pack(side="left", padx=5)

    def export_jobs(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV Files", "*.csv")],
            initialfile=f"jobs_{datetime.now():%Y%m%d}.csv"
        )
        if not path:
            return

        rows = self.db.c.execute("""
            SELECT jobs.ticket, jobs.customer, jobs.contact,
                   jobs.address, technicians.name,
                   routers.brand, routers.model, routers.serial,
                   jobs.job_type, jobs.priority, jobs.status, jobs.dispatch_time,
                   jobs.start_time, jobs.end_time, jobs.notes
            FROM jobs
            JOIN technicians ON jobs.technician_id=technicians.id
            JOIN routers ON jobs.router_id=routers.id
            ORDER BY jobs.id DESC
        """).fetchall()

        header = ["Ticket", "Customer", "Contact", "Address", "Technician",
                  "Router Brand", "Router Model", "Serial Number", "Job Type",
                  "Priority", "Status", "Dispatch Time", "Start Time", "End Time", "Notes"]
        if self.write_csv(path, header, rows):
            messagebox.showinfo("Export Complete", "CSV file exported successfully.")

    # -------------------------------------------------
    # INSTALLATION / PULL-OUT MONITORING
    # -------------------------------------------------

    def make_monitor(self):
        parent = self.tabs["Job Monitoring"]

        self.heading(parent, "Installation / Pull-out Monitoring",
                     "Track technician job progress and completion.")

        self.button_row(parent, [
            ("Start Job", self.start_job, True),
            ("Complete Job", self.complete_job),
            ("Cancel Job", self.cancel_job),
            ("Job Details", lambda: self.open_job(self.monitor_tree)),
            ("Reassign", lambda: self.reassign_job(self.monitor_tree)),
            ("Delete Selected", lambda: self.delete_job_from_tree(self.monitor_tree)),
            ("Refresh", self.refresh_monitor),
        ])

        self.monitor_filter = self.filter_bar(parent, self.refresh_monitor, JOB_STATUSES,
                                              options2=[], label2="Technician")

        self.monitor_tree = self.create_tree(
            parent,
            ("id", "ticket", "customer", "technician", "type", "status",
             "start", "end", "duration"),
            ("ID", "Ticket", "Customer", "Technician", "Job Type", "Status",
             "Start Time", "End Time", "Duration"),
            (45, 115, 150, 130, 105, 85, 135, 135, 110),
        )
        self.bind_open(self.monitor_tree, lambda: self.open_job(self.monitor_tree))

    def refresh_monitor(self):
        self.set_tech_filter(self.monitor_filter)
        rows = self.db.c.execute("""
            SELECT jobs.id, jobs.ticket, jobs.customer,
                   technicians.name, jobs.job_type, jobs.status,
                   jobs.start_time, jobs.end_time, jobs.dispatch_time
            FROM jobs
            JOIN technicians ON jobs.technician_id=technicians.id
            ORDER BY jobs.id DESC
        """).fetchall()

        shown = []
        for r in rows:
            duration = job_duration(r["status"], r["dispatch_time"],
                                    r["start_time"], r["end_time"])
            values = (r["id"], r["ticket"], r["customer"], r["name"], r["job_type"],
                      r["status"], r["start_time"], r["end_time"], duration)
            if self.monitor_filter.accepts(values, r["status"], r["name"]):
                tag = "late" if is_late(r["status"], r["dispatch_time"]) else tag_name(r["status"])
                shown.append((values, tag))

        self.fill_tree(self.monitor_tree, shown)
        self.monitor_filter.show(len(shown), len(rows))

    def delete_job_from_tree(self, tree):
        job_id = self.selected_id(tree, "job")
        if job_id is None:
            return

        job = self.db.job(job_id)
        if not job:
            messagebox.showerror("Not Found", "Hindi na makita ang napiling dispatch.")
            self.refresh_all()
            return

        if not messagebox.askyesno(
            "Confirm Delete",
            f"Sigurado ka bang buburahin ang job {job['ticket']} - {job['customer']}?\n"
            "Hindi na ito maibabalik."
        ):
            return

        try:
            with self.db.c:
                self.db.detach_job(job_id, job["status"] in ACTIVE_JOB)
                self.db.c.execute("DELETE FROM jobs WHERE id=?", (job_id,))
                if job["job_type"] == "Installation" and job["status"] in ACTIVE_JOB:
                    self.db.release_installation_router(job["router_id"])
                self.db.log(job["tech_name"], "Job Deleted",
                            f"{job['ticket']} - {job['customer']}")
            self.refresh_all()
            messagebox.showinfo("Deleted", "Matagumpay na nabura ang napiling job.")
        except sqlite3.Error as error:
            messagebox.showerror("Database Error", str(error))

    def start_job(self):
        job_id = self.selected_id(self.monitor_tree, "job")
        if job_id is None:
            return
        job = self.db.job(job_id)

        if job["status"] != "Dispatched":
            messagebox.showwarning("Invalid Status", "Only dispatched jobs can be started.")
            return

        with self.db.c:
            self.db.c.execute("UPDATE jobs SET status='In Progress', start_time=? WHERE id=?",
                              (stamp(), job_id))
            self.db.sync_request(job_id, "In Progress")
            self.db.log(job["tech_name"], "Job Started", job["ticket"])
        self.refresh_all()

    def complete_job(self):
        job_id = self.selected_id(self.monitor_tree, "job")
        if job_id is None:
            return
        job = self.db.job(job_id)

        if job["status"] != "In Progress":
            messagebox.showwarning("Invalid Status", "Start the job before completing it.")
            return

        new_router_status = None
        if job["job_type"] == "Pull-out":
            new_router_status = self.ask_choice(
                "Router Condition",
                f"Router {job['serial']} was pulled out.\nSet its new status:",
                ["Available", "Defective", "Maintenance"]
            )
            if new_router_status is None:
                return

        with self.db.c:
            self.db.c.execute("UPDATE jobs SET status='Completed', end_time=? WHERE id=?",
                              (stamp(), job_id))
            self.db.sync_request(job_id, "Completed")
            detail = job["ticket"]
            if new_router_status:
                self.db.c.execute("UPDATE routers SET status=? WHERE id=?",
                                  (new_router_status, job["router_id"]))
                detail += f" - router {job['serial']} set to {new_router_status}"
            self.db.log(job["tech_name"], "Job Completed", detail)

        self.refresh_all()
        messagebox.showinfo("Completed", "Job marked as completed successfully.")

    def cancel_job(self):
        job_id = self.selected_id(self.monitor_tree, "job")
        if job_id is None:
            return
        job = self.db.job(job_id)

        if job["status"] in ("Completed", "Cancelled"):
            messagebox.showwarning("Invalid Status", "This job cannot be cancelled.")
            return

        if not messagebox.askyesno("Cancel Job", f"Cancel job {job['ticket']}?"):
            return

        with self.db.c:
            self.db.c.execute("UPDATE jobs SET status='Cancelled', end_time=? WHERE id=?",
                              (stamp(), job_id))
            self.db.sync_request(job_id, "Cancelled")
            # Only an installation reserves a router, so only it releases one.
            if job["job_type"] == "Installation":
                self.db.release_installation_router(job["router_id"])
            self.db.log(job["tech_name"], "Job Cancelled", job["ticket"])

        self.refresh_all()

    # -------------------------------------------------
    # ACTIVITY LOGS
    # -------------------------------------------------

    def make_logs(self):
        parent = self.tabs["Activity Logs"]

        self.heading(parent, "Activity Logs", "Monitor and review system activities.")

        self.button_row(parent, [
            ("Refresh Logs", self.refresh_logs),
            ("Delete Selected", self.delete_selected_log),
            ("Erase All Logs", self.erase_all_logs),
            ("Export Logs", self.export_logs),
        ])

        self.log_filter = self.filter_bar(parent, self.refresh_logs, [], label="Action")

        self.logs_tree = self.create_tree(
            parent,
            ("id", "time", "technician", "action", "details"),
            ("ID", "Date & Time", "Technician", "Action", "Details"),
            (50, 150, 140, 160, 480),
        )

    def refresh_logs(self):
        total = self.db.scalar("SELECT COUNT(*) FROM logs")
        rows = self.db.c.execute("SELECT * FROM logs ORDER BY id DESC LIMIT 3000").fetchall()

        actions = sorted({r["action"] for r in rows if r["action"]})
        if self.log_filter.combo is not None:
            self.log_filter.combo["values"] = ["All", *actions]

        shown = []
        for r in rows:
            values = (r["id"], r["event_time"], r["technician"], r["action"], r["details"])
            if self.log_filter.accepts(values, r["action"]):
                shown.append((values, None))

        self.fill_tree(self.logs_tree, shown)
        self.log_filter.show(len(shown), total)

    def delete_selected_log(self):
        log_id = self.selected_id(self.logs_tree, "activity log")
        if log_id is None:
            return

        if not messagebox.askyesno(
            "Confirm Delete",
            f"Buburahin ang activity log ID {log_id}?\nHindi na ito maibabalik."
        ):
            return

        try:
            with self.db.c:
                self.db.c.execute("DELETE FROM logs WHERE id=?", (log_id,))
            self.refresh_logs()
            messagebox.showinfo("Deleted", "Napiling activity log ay nabura na.")
        except sqlite3.Error as error:
            messagebox.showerror("Database Error", str(error))

    def erase_all_logs(self):
        count = self.db.scalar("SELECT COUNT(*) FROM logs")
        if count == 0:
            messagebox.showinfo("No Logs", "Walang activity logs na buburahin.")
            return

        if not messagebox.askyesno(
            "Erase All Logs",
            f"Buburahin ang lahat ng {count} activity logs?\nHindi na ito maibabalik.\n\n"
            "Tip: use File > Export logs first if you need a copy."
        ):
            return

        try:
            with self.db.c:
                self.db.c.execute("DELETE FROM logs")
            self.refresh_logs()
            messagebox.showinfo("Erased", "Lahat ng activity logs ay nabura na.")
        except sqlite3.Error as error:
            messagebox.showerror("Database Error", str(error))

    def export_logs(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV Files", "*.csv")],
            initialfile=f"logs_{datetime.now():%Y%m%d}.csv"
        )
        if not path:
            return

        rows = self.db.c.execute("SELECT * FROM logs ORDER BY id DESC").fetchall()
        if self.write_csv(path, ["ID", "Date & Time", "Technician", "Action", "Details"], rows):
            messagebox.showinfo("Export Complete", "Activity logs exported successfully.")

    # -------------------------------------------------
    # BACKUP
    # -------------------------------------------------

    def backup_db(self):
        path = filedialog.asksaveasfilename(
            title="Back up database",
            defaultextension=".db",
            initialfile=f"techtrack_backup_{datetime.now():%Y%m%d_%H%M%S}.db",
            filetypes=[("SQLite Database", "*.db")]
        )
        if not path:
            return

        if Path(path).resolve() == DB:
            messagebox.showerror("Backup Failed",
                                 "Choose a different file than the live database.")
            return

        try:
            dest = sqlite3.connect(path)
            try:
                self.db.c.backup(dest)
            finally:
                dest.close()
            with self.db.c:
                self.db.log("Administrator", "Database Backup", Path(path).name)
            self.refresh_logs()
            messagebox.showinfo("Backup Complete", f"Database saved to:\n{path}")
        except (OSError, sqlite3.Error) as error:
            messagebox.showerror("Backup Failed", str(error))


# -------------------------------------------------
# RUN APPLICATION
# -------------------------------------------------

if __name__ == "__main__":
    try:
        app = App()
        app.mainloop()

    except Exception:
        import traceback
        traceback.print_exc()
        input("\nAn error occurred. Press Enter to exit...")
