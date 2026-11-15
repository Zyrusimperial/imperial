"""
Imperial Network - TechTrack
Tkinter Desktop GUI + SQLite Database
Run: py ImperialTechTrack.py
No third-party packages required.
"""

import csv
import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime
from pathlib import Path

DB = Path(__file__).resolve().with_name("techtrack.db")

NAVY = "#10243e"
BLUE = "#2463eb"
BG = "#f2f5fa"
WHITE = "#ffffff"
GREEN = "#16a34a"
RED = "#dc2626"
ORANGE = "#ea580c"


def stamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Store:
    def __init__(self):
        self.c = sqlite3.connect(DB)
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
        """)

        if not self.c.execute(
            "SELECT 1 FROM technicians LIMIT 1"
        ).fetchone():
            self.c.executemany(
                "INSERT INTO technicians(name,phone) VALUES(?,?)",
                [
                    ("Juan Dela Cruz", "09171234567"),
                    ("Maria Santos", "09981234567"),
                    ("Pedro Reyes", "09221234567")
                ]
            )

        if not self.c.execute(
            "SELECT 1 FROM routers LIMIT 1"
        ).fetchone():
            self.c.executemany(
                "INSERT INTO routers(brand,model,serial,mac) VALUES(?,?,?,?)",
                [
                    ("TP-Link", "Archer C6", "TPL-10001", "00:11:22:33:44:01"),
                    ("Huawei", "HG8145V5", "HW-10002", "00:11:22:33:44:02"),
                    ("ZTE", "F670L", "ZTE-10003", "00:11:22:33:44:03")
                ]
            )

        self.c.commit()

    def log(self, tech, action, detail):
        self.c.execute(
            "INSERT INTO logs(event_time,technician,action,details) VALUES(?,?,?,?)",
            (stamp(), tech, action, detail)
        )
        self.c.commit()


class App(tk.Tk):

    def __init__(self):
        super().__init__()

        self.db = Store()

        self.title("Imperial Network | TechTrack")
        self.geometry("1180x740")
        self.minsize(950, 600)
        self.configure(bg=BG)

        self.setup_style()
        self.setup_header()
        self.setup_tabs()

        self.make_dashboard()
        self.make_inventory()
        self.make_techs()
        self.make_dispatch()
        self.make_monitor()
        self.make_logs()

        self.refresh_all()

    # -------------------------------------------------
    # STYLE
    # -------------------------------------------------

    def setup_style(self):
        st = ttk.Style(self)
        st.theme_use("clam")

        st.configure("TFrame", background=BG)
        st.configure(
            "TLabel",
            background=BG,
            foreground=NAVY,
            font=("Segoe UI", 10)
        )

        st.configure(
            "Title.TLabel",
            font=("Segoe UI", 21, "bold")
        )

        st.configure(
            "Treeview",
            rowheight=28,
            font=("Segoe UI", 9)
        )

        st.configure(
            "Treeview.Heading",
            font=("Segoe UI", 9, "bold")
        )

        st.configure("TButton", padding=7)

        st.configure(
            "Accent.TButton",
            background=BLUE,
            foreground=WHITE,
            font=("Segoe UI", 9, "bold")
        )

    # -------------------------------------------------
    # HEADER
    # -------------------------------------------------

    def setup_header(self):
        header = tk.Frame(self, bg=NAVY, height=82)
        header.pack(fill="x")
        header.pack_propagate(False)

        tk.Label(
            header,
            text="IMPERIAL NETWORK",
            bg=NAVY,
            fg="#9db9e6",
            font=("Segoe UI", 9, "bold")
        ).pack(anchor="w", padx=22, pady=(10, 0))

        tk.Label(
            header,
            text="TECHTRACK  |  Technician & Inventory Monitoring",
            bg=NAVY,
            fg=WHITE,
            font=("Segoe UI", 19, "bold")
        ).pack(anchor="w", padx=22)

    # -------------------------------------------------
    # TABS
    # -------------------------------------------------

    def setup_tabs(self):
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=18, pady=15)

        self.tabs = {}

        names = [
            "Dashboard",
            "Router Inventory",
            "Technicians",
            "Dispatch",
            "Installation / Pull-out",
            "Activity Logs"
        ]

        for name in names:
            frame = ttk.Frame(self.nb, padding=12)
            self.nb.add(frame, text=name)
            self.tabs[name] = frame

    # -------------------------------------------------
    # COMMON FUNCTIONS
    # -------------------------------------------------

    def heading(self, parent, title, subtitle=None):
        ttk.Label(
            parent,
            text=title,
            style="Title.TLabel"
        ).pack(anchor="w", pady=(0, 5))

        if subtitle:
            ttk.Label(
                parent,
                text=subtitle
            ).pack(anchor="w", pady=(0, 15))

    def create_tree(self, parent, columns, headings):
        container = ttk.Frame(parent)
        container.pack(fill="both", expand=True)

        tree = ttk.Treeview(
            container,
            columns=columns,
            show="headings"
        )

        for col, title in zip(columns, headings):
            tree.heading(col, text=title)
            tree.column(col, width=120, anchor="center")

        scrollbar = ttk.Scrollbar(
            container,
            orient="vertical",
            command=tree.yview
        )

        tree.configure(yscrollcommand=scrollbar.set)

        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        return tree

    def clear_tree(self, tree):
        for item in tree.get_children():
            tree.delete(item)

    def refresh_all(self):
        self.refresh_dashboard()
        self.refresh_inventory()
        self.refresh_techs()
        self.refresh_dispatch()
        self.refresh_monitor()
        self.refresh_logs()

    # -------------------------------------------------
    # DASHBOARD
    # -------------------------------------------------

    def make_dashboard(self):
        parent = self.tabs["Dashboard"]

        self.heading(
            parent,
            "Dashboard",
            "Overview of Imperial Network operations and monitoring."
        )

        dashboard_buttons = ttk.Frame(parent)
        dashboard_buttons.pack(fill="x", pady=5)

        ttk.Button(
            dashboard_buttons,
            text="Delete Selected",
            command=lambda: self.delete_job_from_tree(self.dashboard_tree)
        ).pack(side="left", padx=3)

        ttk.Button(
            dashboard_buttons,
            text="Refresh",
            command=self.refresh_dashboard
        ).pack(side="left", padx=3)

        cards = ttk.Frame(parent)
        cards.pack(fill="x", pady=10)

        self.dashboard_values = {}

        card_data = [
            ("Total Routers", "routers"),
            ("Available Routers", "available"),
            ("Technicians", "technicians"),
            ("Active Jobs", "jobs"),
            ("Completed Jobs", "completed")
        ]

        for title, key in card_data:
            card = tk.Frame(
                cards,
                bg=WHITE,
                highlightbackground="#dce3ee",
                highlightthickness=1
            )

            card.pack(
                side="left",
                fill="both",
                expand=True,
                padx=5,
                ipady=15
            )

            tk.Label(
                card,
                text=title,
                bg=WHITE,
                fg="#64748b",
                font=("Segoe UI", 9)
            ).pack(pady=(10, 5))

            value = tk.Label(
                card,
                text="0",
                bg=WHITE,
                fg=BLUE,
                font=("Segoe UI", 23, "bold")
            )

            value.pack(pady=(0, 10))

            self.dashboard_values[key] = value

        ttk.Label(
            parent,
            text="Recent Dispatch Activities",
            font=("Segoe UI", 13, "bold")
        ).pack(anchor="w", pady=(25, 10))

        self.dashboard_tree = self.create_tree(
            parent,
            ("id", "ticket", "customer", "technician", "type", "status", "date"),
            ("ID", "Ticket", "Customer", "Technician", "Job Type", "Status", "Dispatch Date")
        )

    def refresh_dashboard(self):
        c = self.db.c

        values = {
            "routers": c.execute(
                "SELECT COUNT(*) FROM routers"
            ).fetchone()[0],

            "available": c.execute(
                "SELECT COUNT(*) FROM routers WHERE status='Available'"
            ).fetchone()[0],

            "technicians": c.execute(
                "SELECT COUNT(*) FROM technicians WHERE active=1"
            ).fetchone()[0],

            "jobs": c.execute(
                "SELECT COUNT(*) FROM jobs WHERE status IN ('Dispatched','In Progress')"
            ).fetchone()[0],

            "completed": c.execute(
                "SELECT COUNT(*) FROM jobs WHERE status='Completed'"
            ).fetchone()[0]
        }

        for key, value in values.items():
            self.dashboard_values[key].config(text=str(value))

        self.clear_tree(self.dashboard_tree)

        rows = c.execute("""
            SELECT jobs.id, jobs.ticket, jobs.customer, technicians.name,
                   jobs.job_type, jobs.status, jobs.dispatch_time
            FROM jobs
            JOIN technicians ON jobs.technician_id=technicians.id
            ORDER BY jobs.id DESC LIMIT 10
        """).fetchall()

        for row in rows:
            self.dashboard_tree.insert("", "end", values=tuple(row))

    # -------------------------------------------------
    # ROUTER INVENTORY
    # -------------------------------------------------

    def make_inventory(self):
        parent = self.tabs["Router Inventory"]

        self.heading(
            parent,
            "Router Inventory",
            "Manage router equipment and inventory records."
        )

        buttons = ttk.Frame(parent)
        buttons.pack(fill="x", pady=10)

        ttk.Button(
            buttons,
            text="Add Router",
            style="Accent.TButton",
            command=self.add_router
        ).pack(side="left", padx=3)

        ttk.Button(
            buttons,
            text="Edit Router",
            command=self.edit_router
        ).pack(side="left", padx=3)

        ttk.Button(
            buttons,
            text="Delete Router",
            command=self.delete_router
        ).pack(side="left", padx=3)

        ttk.Button(
            buttons,
            text="Refresh",
            command=self.refresh_inventory
        ).pack(side="left", padx=3)

        self.inventory_tree = self.create_tree(
            parent,
            ("id", "brand", "model", "serial", "mac", "status"),
            ("ID", "Brand", "Model", "Serial Number", "MAC Address", "Status")
        )

    def refresh_inventory(self):
        self.clear_tree(self.inventory_tree)

        rows = self.db.c.execute(
            "SELECT * FROM routers ORDER BY id DESC"
        ).fetchall()

        for row in rows:
            self.inventory_tree.insert(
                "",
                "end",
                values=(
                    row["id"],
                    row["brand"],
                    row["model"],
                    row["serial"],
                    row["mac"],
                    row["status"]
                )
            )

    def add_router(self):
        self.router_form()

    def edit_router(self):
        selected = self.inventory_tree.selection()

        if not selected:
            messagebox.showwarning("Select Router", "Please select a router.")
            return

        values = self.inventory_tree.item(selected[0], "values")
        self.router_form(values)

    def router_form(self, values=None):
        win = tk.Toplevel(self)
        win.title("Router Information")
        win.geometry("420x430")
        win.configure(bg=BG)
        win.transient(self)
        win.grab_set()

        fields = [
            ("Brand", "brand"),
            ("Model", "model"),
            ("Serial Number", "serial"),
            ("MAC Address", "mac")
        ]

        entries = {}

        ttk.Label(
            win,
            text="Router Information",
            style="Title.TLabel"
        ).pack(pady=15)

        form = ttk.Frame(win, padding=15)
        form.pack(fill="both", expand=True)

        for i, (label, key) in enumerate(fields):
            ttk.Label(form, text=label).grid(
                row=i, column=0, sticky="w", pady=10
            )

            entry = ttk.Entry(form, width=30)
            entry.grid(row=i, column=1, pady=10, padx=10)

            entries[key] = entry

            if values:
                entry.insert(0, values[i + 1])

        ttk.Label(form, text="Status").grid(
            row=4, column=0, sticky="w", pady=10
        )

        status = ttk.Combobox(
            form,
            values=["Available", "In Use", "Defective", "Maintenance"],
            state="readonly",
            width=27
        )

        status.grid(row=4, column=1, pady=10, padx=10)
        status.set(values[5] if values else "Available")

        def save():
            data = [
                entries["brand"].get().strip(),
                entries["model"].get().strip(),
                entries["serial"].get().strip(),
                entries["mac"].get().strip()
            ]

            if not all(data[:3]):
                messagebox.showerror(
                    "Missing Information",
                    "Brand, model and serial number are required."
                )
                return

            try:
                if values:
                    self.db.c.execute("""
                        UPDATE routers
                        SET brand=?, model=?, serial=?, mac=?, status=?
                        WHERE id=?
                    """, (*data, status.get(), values[0]))
                else:
                    self.db.c.execute("""
                        INSERT INTO routers(brand,model,serial,mac,status)
                        VALUES(?,?,?,?,?)
                    """, (*data, status.get()))

                self.db.c.commit()
                self.db.log("Administrator", "Router Saved", data[2])

                self.refresh_all()
                win.destroy()

            except sqlite3.IntegrityError:
                messagebox.showerror(
                    "Duplicate Serial",
                    "This serial number already exists."
                )

        ttk.Button(
            form,
            text="Save Router",
            style="Accent.TButton",
            command=save
        ).grid(row=5, column=0, columnspan=2, pady=20)

    def delete_router(self):
        selected = self.inventory_tree.selection()

        if not selected:
            messagebox.showwarning("Select Router", "Select a router first.")
            return

        values = self.inventory_tree.item(selected[0], "values")

        if not messagebox.askyesno(
            "Confirm Delete",
            f"Delete router {values[3]}?"
        ):
            return

        try:
            self.db.c.execute(
                "DELETE FROM routers WHERE id=?",
                (values[0],)
            )
            self.db.c.commit()
            self.db.log("Administrator", "Router Deleted", values[3])
            self.refresh_all()

        except sqlite3.IntegrityError:
            messagebox.showerror(
                "Cannot Delete",
                "This router is linked to a job and cannot be deleted."
            )

    # -------------------------------------------------
    # TECHNICIANS
    # -------------------------------------------------

    def make_techs(self):
        parent = self.tabs["Technicians"]

        self.heading(
            parent,
            "Technicians",
            "Manage technician information and availability."
        )

        buttons = ttk.Frame(parent)
        buttons.pack(fill="x", pady=10)

        ttk.Button(
            buttons,
            text="Add Technician",
            style="Accent.TButton",
            command=self.add_tech
        ).pack(side="left", padx=3)

        ttk.Button(
            buttons,
            text="Edit Technician",
            command=self.edit_tech
        ).pack(side="left", padx=3)

        ttk.Button(
            buttons,
            text="Activate / Deactivate",
            command=self.toggle_tech
        ).pack(side="left", padx=3)

        self.tech_tree = self.create_tree(
            parent,
            ("id", "name", "phone", "status"),
            ("ID", "Technician Name", "Contact Number", "Status")
        )

    def refresh_techs(self):
        self.clear_tree(self.tech_tree)

        rows = self.db.c.execute(
            "SELECT * FROM technicians ORDER BY id DESC"
        ).fetchall()

        for row in rows:
            self.tech_tree.insert(
                "",
                "end",
                values=(
                    row["id"],
                    row["name"],
                    row["phone"],
                    "Active" if row["active"] else "Inactive"
                )
            )

    def add_tech(self):
        self.tech_form()

    def edit_tech(self):
        selected = self.tech_tree.selection()

        if not selected:
            messagebox.showwarning("Select Technician", "Select a technician.")
            return

        values = self.tech_tree.item(selected[0], "values")
        self.tech_form(values)

    def tech_form(self, values=None):
        win = tk.Toplevel(self)
        win.title("Technician Information")
        win.geometry("400x280")
        win.configure(bg=BG)
        win.transient(self)
        win.grab_set()

        form = ttk.Frame(win, padding=20)
        form.pack(fill="both", expand=True)

        ttk.Label(
            form,
            text="Technician Information",
            style="Title.TLabel"
        ).pack(pady=10)

        ttk.Label(form, text="Full Name").pack(anchor="w")

        name = ttk.Entry(form, width=40)
        name.pack(fill="x", pady=5)

        ttk.Label(form, text="Contact Number").pack(anchor="w")

        phone = ttk.Entry(form, width=40)
        phone.pack(fill="x", pady=5)

        if values:
            name.insert(0, values[1])
            phone.insert(0, values[2])

        def save():
            n = name.get().strip()
            p = phone.get().strip()

            if not n:
                messagebox.showerror("Error", "Name is required.")
                return

            if values:
                self.db.c.execute(
                    "UPDATE technicians SET name=?, phone=? WHERE id=?",
                    (n, p, values[0])
                )
            else:
                self.db.c.execute(
                    "INSERT INTO technicians(name,phone) VALUES(?,?)",
                    (n, p)
                )

            self.db.c.commit()
            self.db.log(n, "Technician Saved", p)

            self.refresh_all()
            win.destroy()

        ttk.Button(
            form,
            text="Save Technician",
            style="Accent.TButton",
            command=save
        ).pack(pady=15)

    def toggle_tech(self):
        selected = self.tech_tree.selection()

        if not selected:
            messagebox.showwarning("Select Technician", "Select a technician.")
            return

        values = self.tech_tree.item(selected[0], "values")
        tech_id = values[0]

        current = self.db.c.execute(
            "SELECT active FROM technicians WHERE id=?",
            (tech_id,)
        ).fetchone()[0]

        new_status = 0 if current else 1

        self.db.c.execute(
            "UPDATE technicians SET active=? WHERE id=?",
            (new_status, tech_id)
        )

        self.db.c.commit()
        self.db.log(
            values[1],
            "Technician Status Changed",
            "Active" if new_status else "Inactive"
        )

        self.refresh_all()

    # -------------------------------------------------
    # DISPATCH
    # -------------------------------------------------

    def make_dispatch(self):
        parent = self.tabs["Dispatch"]

        self.heading(
            parent,
            "Job Dispatch",
            "Create and assign installation or pull-out jobs."
        )

        buttons = ttk.Frame(parent)
        buttons.pack(fill="x", pady=10)

        ttk.Button(
            buttons,
            text="New Dispatch",
            style="Accent.TButton",
            command=self.new_dispatch
        ).pack(side="left", padx=3)

        ttk.Button(
            buttons,
            text="Export CSV",
            command=self.export_jobs
        ).pack(side="left", padx=3)

        ttk.Button(
            buttons,
            text="Delete Selected",
            command=lambda: self.delete_job_from_tree(self.dispatch_tree)
        ).pack(side="left", padx=3)

        ttk.Button(
            buttons,
            text="Refresh",
            command=self.refresh_dispatch
        ).pack(side="left", padx=3)

        self.dispatch_tree = self.create_tree(
            parent,
            ("id", "ticket", "customer", "address", "technician",
             "router", "type", "status", "date"),
            ("ID", "Ticket", "Customer", "Address", "Technician",
             "Router", "Job Type", "Status", "Dispatch Time")
        )

    def refresh_dispatch(self):
        self.clear_tree(self.dispatch_tree)

        rows = self.db.c.execute("""
            SELECT jobs.id, jobs.ticket, jobs.customer, jobs.address,
                   technicians.name,
                   routers.brand || ' ' || routers.model,
                   jobs.job_type, jobs.status, jobs.dispatch_time
            FROM jobs
            JOIN technicians ON jobs.technician_id=technicians.id
            JOIN routers ON jobs.router_id=routers.id
            ORDER BY jobs.id DESC
        """).fetchall()

        for row in rows:
            self.dispatch_tree.insert(
                "",
                "end",
                values=tuple(row)
            )

    def new_dispatch(self):
        technicians = self.db.c.execute(
            "SELECT id,name FROM technicians WHERE active=1"
        ).fetchall()

        routers = self.db.c.execute(
            "SELECT id,brand,model,serial FROM routers WHERE status='Available'"
        ).fetchall()

        if not technicians:
            messagebox.showerror(
                "No Technician",
                "There are no active technicians available."
            )
            return

        if not routers:
            messagebox.showerror(
                "No Router",
                "There are no available routers."
            )
            return

        win = tk.Toplevel(self)
        win.title("New Dispatch")
        win.geometry("500x610")
        win.configure(bg=BG)
        win.transient(self)
        win.grab_set()

        form = ttk.Frame(win, padding=20)
        form.pack(fill="both", expand=True)

        ttk.Label(
            form,
            text="Create New Dispatch",
            style="Title.TLabel"
        ).pack(pady=10)

        fields = {}

        def add_field(label, key):
            ttk.Label(form, text=label).pack(anchor="w", pady=(8, 2))
            entry = ttk.Entry(form)
            entry.pack(fill="x")
            fields[key] = entry

        add_field("Customer Name", "customer")
        add_field("Contact Number", "contact")
        add_field("Installation Address", "address")

        ttk.Label(form, text="Assigned Technician").pack(
            anchor="w", pady=(8, 2)
        )

        tech_box = ttk.Combobox(
            form,
            state="readonly",
            values=[
                f"{t['id']} - {t['name']}"
                for t in technicians
            ]
        )
        tech_box.pack(fill="x")
        tech_box.current(0)

        ttk.Label(form, text="Assigned Router").pack(
            anchor="w", pady=(8, 2)
        )

        router_box = ttk.Combobox(
            form,
            state="readonly",
            values=[
                f"{r['id']} - {r['brand']} {r['model']} ({r['serial']})"
                for r in routers
            ]
        )
        router_box.pack(fill="x")
        router_box.current(0)

        ttk.Label(form, text="Job Type").pack(
            anchor="w", pady=(8, 2)
        )

        type_box = ttk.Combobox(
            form,
            state="readonly",
            values=["Installation", "Pull-out", "Troubleshooting"]
        )
        type_box.pack(fill="x")
        type_box.current(0)

        ttk.Label(form, text="Notes").pack(
            anchor="w", pady=(8, 2)
        )

        notes = tk.Text(form, height=4, width=40)
        notes.pack(fill="x")

        def save():
            customer = fields["customer"].get().strip()
            contact = fields["contact"].get().strip()
            address = fields["address"].get().strip()

            if not customer or not address:
                messagebox.showerror(
                    "Missing Information",
                    "Customer name and address are required."
                )
                return

            tech_id = int(tech_box.get().split(" - ")[0])
            router_id = int(router_box.get().split(" - ")[0])
            job_type = type_box.get()

            ticket = "IN-" + datetime.now().strftime("%y%m%d%H%M%S")

            try:
                self.db.c.execute("""
                    INSERT INTO jobs(
                        ticket, customer, contact, address,
                        technician_id, router_id, job_type,
                        status, dispatch_time, notes
                    )
                    VALUES(?,?,?,?,?,?,?,?,?,?)
                """, (
                    ticket,
                    customer,
                    contact,
                    address,
                    tech_id,
                    router_id,
                    job_type,
                    "Dispatched",
                    stamp(),
                    notes.get("1.0", "end").strip()
                ))

                self.db.c.execute(
                    "UPDATE routers SET status='In Use' WHERE id=?",
                    (router_id,)
                )

                self.db.c.commit()

                self.db.log(
                    "Administrator",
                    "Job Dispatched",
                    f"{ticket} - {customer}"
                )

                self.refresh_all()
                win.destroy()

                messagebox.showinfo(
                    "Dispatch Successful",
                    f"Job {ticket} has been dispatched."
                )

            except sqlite3.Error as e:
                messagebox.showerror("Database Error", str(e))

        ttk.Button(
            form,
            text="Create Dispatch",
            style="Accent.TButton",
            command=save
        ).pack(pady=15)

    def export_jobs(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV Files", "*.csv")]
        )

        if not path:
            return

        rows = self.db.c.execute("""
            SELECT jobs.ticket, jobs.customer, jobs.contact,
                   jobs.address, technicians.name,
                   routers.brand, routers.model, routers.serial,
                   jobs.job_type, jobs.status, jobs.dispatch_time,
                   jobs.start_time, jobs.end_time, jobs.notes
            FROM jobs
            JOIN technicians ON jobs.technician_id=technicians.id
            JOIN routers ON jobs.router_id=routers.id
            ORDER BY jobs.id DESC
        """).fetchall()

        with open(path, "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file)
            writer.writerow([
                "Ticket", "Customer", "Contact", "Address",
                "Technician", "Router Brand", "Router Model",
                "Serial Number", "Job Type", "Status",
                "Dispatch Time", "Start Time", "End Time", "Notes"
            ])

            for row in rows:
                writer.writerow(tuple(row))

        messagebox.showinfo("Export Complete", "CSV file exported successfully.")

    # -------------------------------------------------
    # INSTALLATION / PULL-OUT MONITORING
    # -------------------------------------------------

    def make_monitor(self):
        parent = self.tabs["Installation / Pull-out"]

        self.heading(
            parent,
            "Installation / Pull-out Monitoring",
            "Track technician job progress and completion."
        )

        buttons = ttk.Frame(parent)
        buttons.pack(fill="x", pady=10)

        ttk.Button(
            buttons,
            text="Start Job",
            style="Accent.TButton",
            command=self.start_job
        ).pack(side="left", padx=3)

        ttk.Button(
            buttons,
            text="Complete Job",
            command=self.complete_job
        ).pack(side="left", padx=3)

        ttk.Button(
            buttons,
            text="Cancel Job",
            command=self.cancel_job
        ).pack(side="left", padx=3)

        ttk.Button(
            buttons,
            text="Delete Selected",
            command=lambda: self.delete_job_from_tree(self.monitor_tree)
        ).pack(side="left", padx=3)

        ttk.Button(
            buttons,
            text="Refresh",
            command=self.refresh_monitor
        ).pack(side="left", padx=3)

        self.monitor_tree = self.create_tree(
            parent,
            ("id", "ticket", "customer", "technician",
             "type", "status", "start", "end"),
            ("ID", "Ticket", "Customer", "Technician",
             "Job Type", "Status", "Start Time", "End Time")
        )

    def refresh_monitor(self):
        self.clear_tree(self.monitor_tree)

        rows = self.db.c.execute("""
            SELECT jobs.id, jobs.ticket, jobs.customer,
                   technicians.name, jobs.job_type, jobs.status,
                   jobs.start_time, jobs.end_time
            FROM jobs
            JOIN technicians ON jobs.technician_id=technicians.id
            ORDER BY jobs.id DESC
        """).fetchall()

        for row in rows:
            self.monitor_tree.insert(
                "",
                "end",
                values=tuple(row)
            )

    def delete_job_from_tree(self, tree):
        selected = tree.selection()

        if not selected:
            messagebox.showwarning(
                "Select Job",
                "Pumili muna ng record na ide-delete."
            )
            return

        values = tree.item(selected[0], "values")
        job_id = values[0]

        job = self.db.c.execute(
            "SELECT ticket, customer, technician_id, router_id, job_type, status "
            "FROM jobs WHERE id=?",
            (job_id,)
        ).fetchone()

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
            self.db.c.execute("DELETE FROM jobs WHERE id=?", (job_id,))

            # Release an installation router only when no other active job uses it.
            if job["job_type"] != "Pull-out" and job["status"] in ("Dispatched", "In Progress"):
                other_active = self.db.c.execute(
                    "SELECT 1 FROM jobs WHERE router_id=? "
                    "AND status IN ('Dispatched','In Progress') LIMIT 1",
                    (job["router_id"],)
                ).fetchone()
                if not other_active:
                    self.db.c.execute(
                        "UPDATE routers SET status='Available' WHERE id=?",
                        (job["router_id"],)
                    )

            tech = self.db.c.execute(
                "SELECT name FROM technicians WHERE id=?",
                (job["technician_id"],)
            ).fetchone()
            tech_name = tech["name"] if tech else "Administrator"

            self.db.c.commit()
            self.db.log(
                tech_name,
                "Job Deleted",
                f"{job['ticket']} - {job['customer']}"
            )
            self.refresh_all()
            messagebox.showinfo("Deleted", "Matagumpay na nabura ang napiling job.")
        except sqlite3.Error as error:
            self.db.c.rollback()
            messagebox.showerror("Database Error", str(error))

    def get_selected_job(self):
        selected = self.monitor_tree.selection()

        if not selected:
            messagebox.showwarning(
                "Select Job",
                "Please select a job first."
            )
            return None

        return self.monitor_tree.item(selected[0], "values")

    def start_job(self):
        values = self.get_selected_job()

        if not values:
            return

        if values[5] != "Dispatched":
            messagebox.showwarning(
                "Invalid Status",
                "Only dispatched jobs can be started."
            )
            return

        self.db.c.execute("""
            UPDATE jobs
            SET status='In Progress', start_time=?
            WHERE id=?
        """, (stamp(), values[0]))

        self.db.c.commit()

        self.db.log(
            values[3],
            "Job Started",
            values[1]
        )

        self.refresh_all()

    def complete_job(self):
        values = self.get_selected_job()

        if not values:
            return

        if values[5] != "In Progress":
            messagebox.showwarning(
                "Invalid Status",
                "Start the job before completing it."
            )
            return

        self.db.c.execute("""
            UPDATE jobs
            SET status='Completed', end_time=?
            WHERE id=?
        """, (stamp(), values[0]))

        job_type = values[4]

        job = self.db.c.execute(
            "SELECT router_id FROM jobs WHERE id=?",
            (values[0],)
        ).fetchone()

        if job_type == "Pull-out":
            self.db.c.execute(
                "UPDATE routers SET status='Available' WHERE id=?",
                (job["router_id"],)
            )

        self.db.c.commit()

        self.db.log(
            values[3],
            "Job Completed",
            values[1]
        )

        self.refresh_all()

        messagebox.showinfo(
            "Completed",
            "Job marked as completed successfully."
        )

    def cancel_job(self):
        values = self.get_selected_job()

        if not values:
            return

        if values[5] in ("Completed", "Cancelled"):
            messagebox.showwarning(
                "Invalid Status",
                "This job cannot be cancelled."
            )
            return

        if not messagebox.askyesno(
            "Cancel Job",
            f"Cancel job {values[1]}?"
        ):
            return

        job = self.db.c.execute(
            "SELECT router_id FROM jobs WHERE id=?",
            (values[0],)
        ).fetchone()

        self.db.c.execute("""
            UPDATE jobs SET status='Cancelled', end_time=?
            WHERE id=?
        """, (stamp(), values[0]))

        self.db.c.execute(
            "UPDATE routers SET status='Available' WHERE id=?",
            (job["router_id"],)
        )

        self.db.c.commit()

        self.db.log(
            values[3],
            "Job Cancelled",
            values[1]
        )

        self.refresh_all()

    # -------------------------------------------------
    # ACTIVITY LOGS
    # -------------------------------------------------

    def make_logs(self):
        parent = self.tabs["Activity Logs"]

        self.heading(
            parent,
            "Activity Logs",
            "Monitor and review system activities."
        )

        buttons = ttk.Frame(parent)
        buttons.pack(fill="x", pady=10)

        ttk.Button(
            buttons,
            text="Refresh Logs",
            command=self.refresh_logs
        ).pack(side="left", padx=3)

        ttk.Button(
            buttons,
            text="Delete Selected",
            command=self.delete_selected_log
        ).pack(side="left", padx=3)

        ttk.Button(
            buttons,
            text="Erase All Logs",
            command=self.erase_all_logs
        ).pack(side="left", padx=3)

        ttk.Button(
            buttons,
            text="Export Logs",
            command=self.export_logs
        ).pack(side="left", padx=3)

        self.logs_tree = self.create_tree(
            parent,
            ("id", "time", "technician", "action", "details"),
            ("ID", "Date & Time", "Technician", "Action", "Details")
        )

    def refresh_logs(self):
        self.clear_tree(self.logs_tree)

        rows = self.db.c.execute(
            "SELECT * FROM logs ORDER BY id DESC"
        ).fetchall()

        for row in rows:
            self.logs_tree.insert(
                "",
                "end",
                values=(
                    row["id"],
                    row["event_time"],
                    row["technician"],
                    row["action"],
                    row["details"]
                )
            )

    def delete_selected_log(self):
        selected = self.logs_tree.selection()

        if not selected:
            messagebox.showwarning("Select Log", "Pumili muna ng activity log na buburahin.")
            return

        values = self.logs_tree.item(selected[0], "values")
        if not messagebox.askyesno(
            "Confirm Delete",
            f"Buburahin ang activity log ID {values[0]}?\nHindi na ito maibabalik."
        ):
            return

        try:
            self.db.c.execute("DELETE FROM logs WHERE id=?", (values[0],))
            self.db.c.commit()
            self.refresh_logs()
            messagebox.showinfo("Deleted", "Napiling activity log ay nabura na.")
        except sqlite3.Error as error:
            self.db.c.rollback()
            messagebox.showerror("Database Error", str(error))

    def erase_all_logs(self):
        count = self.db.c.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
        if count == 0:
            messagebox.showinfo("No Logs", "Walang activity logs na buburahin.")
            return

        if not messagebox.askyesno(
            "Erase All Logs",
            f"Buburahin ang lahat ng {count} activity logs?\nHindi na ito maibabalik."
        ):
            return

        try:
            self.db.c.execute("DELETE FROM logs")
            self.db.c.commit()
            self.refresh_logs()
            messagebox.showinfo("Erased", "Lahat ng activity logs ay nabura na.")
        except sqlite3.Error as error:
            self.db.c.rollback()
            messagebox.showerror("Database Error", str(error))

    def export_logs(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV Files", "*.csv")]
        )

        if not path:
            return

        rows = self.db.c.execute(
            "SELECT * FROM logs ORDER BY id DESC"
        ).fetchall()

        with open(path, "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file)

            writer.writerow([
                "ID",
                "Date & Time",
                "Technician",
                "Action",
                "Details"
            ])

            for row in rows:
                writer.writerow(tuple(row))

        messagebox.showinfo(
            "Export Complete",
            "Activity logs exported successfully."
        )


# -------------------------------------------------
# RUN APPLICATION
# -------------------------------------------------

if __name__ == "__main__":
    try:
        app = App()
        app.mainloop()

    except Exception as error:
        import traceback
        traceback.print_exc()
        input("\nAn error occurred. Press Enter to exit...")

        
