import json
import csv
import os
import uuid
import sys
import shutil
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

APP_TITLE = "Promptocoll"
if getattr(sys, 'frozen', False):
    # läuft als .exe (PyInstaller)
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # läuft als normales Python-Skript
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "log.json")
MEDIA_DIR = os.path.join(BASE_DIR, "Media")
os.makedirs(MEDIA_DIR, exist_ok=True)


MODEL_PRESETS = [
    "Keine Angabe",
    "gpt-5.2",
    "gpt-5.1-instant",
    "gpt-5.1-thinking",
    "gpt-4o",
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-4.1-nano",
    "o4-mini",
    "claude-3.5-sonnet",
    "gemini-1.5-pro",
    "Custom…",
]

def resource_path(relative_path: str) -> str:
    """
    Get absolute path to resource, works for dev and for PyInstaller onefile.
    """
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)  # type: ignore[attr-defined]
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)


def now_local_iso():
    # local time with offset, ISO-like (no microseconds)
    dt = datetime.now().astimezone()
    return dt.replace(microsecond=0).isoformat()


def parse_dt_flexible(s: str):
    """
    Accepts:
      - ISO: 2026-01-09T14:23:10+01:00
      - ISO without offset: 2026-01-09T14:23:10
      - "YYYY-MM-DD HH:MM" or "YYYY-MM-DD HH:MM:SS"
    Returns datetime (aware if offset present; otherwise local).
    """
    s = (s or "").strip()
    if not s:
        raise ValueError("empty")
    # normalize space to T for ISO parse attempt
    try:
        # datetime.fromisoformat handles many variants
        dt = datetime.fromisoformat(s.replace(" ", "T"))
    except Exception:
        raise ValueError("Unbekanntes Datumsformat.")
    if dt.tzinfo is None:
        # assume local timezone if missing
        dt = dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return dt


def dt_display(dt_iso: str):
    try:
        dt = datetime.fromisoformat(dt_iso)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return dt_iso


@dataclass
class LogEntry:
    id: str
    timestamp: str
    model: str
    prompt: str
    response: str
    purpose: str = ""   # Zweck/Task
    section: str = ""   # Kapitel
    project: str = ""   # Projektname
    tags: list = None
    media_prompt: list = None   # Anhänge zum Prompt
    media_response: list = None # Anhänge zur Antwort

    def to_dict(self):
        d = asdict(self)
        if d["tags"] is None:
            d["tags"] = []
        if d.get("media_prompt") is None:
            d["media_prompt"] = []
        if d.get("media_response") is None:
            d["media_response"] = []
        return d


class LogbookApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.minsize(980, 640)
        # Window icon (title bar / taskbar)
        try:
            ico_path = resource_path("favicon.ico")
            if os.path.exists(ico_path):
                self.iconbitmap(ico_path)
        except Exception:
            pass

        try:
            png_path = resource_path("icon.png")  # use a small square icon PNG (32/64)
            if os.path.exists(png_path):
                self._app_icon_img = tk.PhotoImage(file=png_path)
                self.iconphoto(True, self._app_icon_img)
        except Exception:
            pass

        self.entries: list[LogEntry] = []
        self.filtered_ids: list[str] = []
        self.pending_media_prompt: list[str] = []
        self.pending_media_response: list[str] = []

        self._build_ui()
        self._load_data()
        self._refresh_log()

    # ---------------- UI ----------------
    def _build_ui(self):
        self.style = ttk.Style(self)
        self.style.configure("TButton", padding=6)
        self.style.configure("TLabel", padding=(0, 2))
        self.style.configure("Submit.TButton", font=("TkDefaultFont", 10, "bold"), padding=10)

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True)

        self.tab_input = ttk.Frame(notebook, padding=12, width=150)
        self.tab_log = ttk.Frame(notebook, padding=12, width=150)
        notebook.add(self.tab_input, text="Input")
        notebook.add(self.tab_log, text="Log")

        self._build_input_tab()
        self._build_log_tab()

        # footer
        footer = ttk.Frame(self, padding=(12, 0, 12, 10))
        footer.pack(fill="x")
        self.status_var = tk.StringVar(value=f"Datei: {os.path.abspath(DATA_FILE)}")
        ttk.Label(footer, textvariable=self.status_var).pack(side="left")

    def _build_input_tab(self):
        frm = self.tab_input
        logo_path = resource_path("logo.png")
        if os.path.exists(logo_path):
            try:
                self.logo_img = tk.PhotoImage(file=logo_path)
                logo_lbl = ttk.Label(frm, image=self.logo_img)
                logo_lbl.grid(row=0, column=2, rowspan=4, sticky="ne", padx=(10, 0))
            except Exception:
                pass

        # Layout grid
        frm.columnconfigure(0, weight=1)
        frm.columnconfigure(1, weight=1)

        # Model
        ttk.Label(frm, text="KI-Modell").grid(row=0, column=0, sticky="w")
        self.model_var = tk.StringVar(value=MODEL_PRESETS[0])
        self.model_combo = ttk.Combobox(
            frm, textvariable=self.model_var, values=MODEL_PRESETS, state="readonly"
        )
        self.model_combo.grid(row=1, column=0, sticky="ew", padx=(0, 8))
        self.model_combo.bind("<<ComboboxSelected>>", self._on_model_selected)

        self.custom_model_var = tk.StringVar(value="")
        self.custom_model_entry = ttk.Entry(frm, textvariable=self.custom_model_var)
        self.custom_model_entry.grid(row=1, column=1, sticky="ew")
        ttk.Label(frm, text="Custom Modell (nur wenn 'Custom…')").grid(
            row=0, column=1, sticky="w"
        )

        # Timestamp
        ttk.Label(frm, text="Datum/Uhrzeit (leer = jetzt)").grid(row=2, column=0, sticky="w", pady=(10, 0))
        self.ts_var = tk.StringVar(value="")
        self.ts_entry = ttk.Entry(frm, textvariable=self.ts_var)
        self.ts_entry.grid(row=3, column=0, sticky="ew", padx=(0, 8))

        ttk.Label(frm, text="Beispiel: 2026-01-09 14:23 oder ISO").grid(
            row=2, column=1, sticky="w", pady=(10, 0)
        )
        date_btns = ttk.Frame(frm)
        date_btns.grid(row=3, column=1, sticky="ew")
        date_btns.columnconfigure(0, weight=1)

        btn_now = ttk.Button(date_btns, text="Jetzt einsetzen", command=self._fill_now)
        btn_now.pack(side="left")

        self.submit_top = ttk.Button(
            date_btns,
            text="Absenden",
            command=lambda: self.add_entry(),
            style="Submit.TButton"
        )
        self.submit_top.pack(side="right")
        self.toast_var = tk.StringVar(value="")
        self.toast_label = ttk.Label(frm, textvariable=self.toast_var)
        self.toast_label.place_forget()  # erst mal unsichtbar
        self._toast_after_id = None

        # Prompt
        ttk.Label(frm, text="Prompt").grid(row=4, column=0, sticky="w", pady=(10, 0))
        self.prompt_txt = tk.Text(frm, height=10, wrap="word")
        self.prompt_txt.grid(row=5, column=0, columnspan=2, sticky="nsew")
        frm.rowconfigure(5, weight=1)

        # Response
        ttk.Label(frm, text="Antwort").grid(row=6, column=0, sticky="w", pady=(10, 0))
        self.response_txt = tk.Text(frm, height=10, wrap="word")
        self.response_txt.grid(row=7, column=0, columnspan=2, sticky="nsew")
        frm.rowconfigure(7, weight=1)

        # Optional fields
        opt = ttk.LabelFrame(frm, text="Optional (hilft bei Eigenleistung / Struktur)", padding=10)
        opt.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        opt.columnconfigure(0, weight=1)
        opt.columnconfigure(1, weight=1)

        ttk.Label(opt, text="Zweck/Task").grid(row=0, column=0, sticky="w")
        self.purpose_var = tk.StringVar(value="")
        ttk.Entry(opt, textvariable=self.purpose_var).grid(row=1, column=0, sticky="ew", padx=(0, 8))

        ttk.Label(opt, text="Kapitel").grid(row=0, column=1, sticky="w")
        self.section_var = tk.StringVar(value="")
        ttk.Entry(opt, textvariable=self.section_var).grid(row=1, column=1, sticky="ew")

        ttk.Label(opt, text="Tags (kommagetrennt)").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.tags_var = tk.StringVar(value="")
        ttk.Entry(opt, textvariable=self.tags_var).grid(row=3, column=0, sticky="ew")

        ttk.Label(opt, text="Projekt").grid(row=2, column=1, sticky="w", pady=(8, 0))
        self.contrib_var = tk.StringVar(value="")
        ttk.Entry(opt, textvariable=self.contrib_var).grid(row=3, column=1, sticky="ew")

        # Buttons
        btns = ttk.Frame(frm)
        btns.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        btns.columnconfigure(0, weight=1)

        ttk.Button(btns, text="Felder leeren", command=self._clear_input_fields).pack(side="left", padx=8)

        # Paperclip symbol
        paperclip = "📎"
        ttk.Button(btns, text=f"{paperclip} Prompt", command=lambda: self._attach_media("prompt")).pack(side="left", padx=8)
        ttk.Button(btns, text=f"{paperclip} Antwort", command=lambda: self._attach_media("response")).pack(side="left", padx=8)

        self.media_var = tk.StringVar(value="Keine Anhänge")
        ttk.Label(btns, textvariable=self.media_var).pack(side="left", padx=8)

        self._on_model_selected()

    def _build_log_tab(self):
        frm = self.tab_log
        frm.columnconfigure(0, weight=1)
        frm.rowconfigure(2, weight=1)

        # Top controls: search + filter + export
        top = ttk.Frame(frm)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(2, weight=1)

        ttk.Label(top, text="Suche").grid(row=0, column=0, sticky="w")
        self.search_var = tk.StringVar(value="")
        search_entry = ttk.Entry(top, textvariable=self.search_var)
        search_entry.grid(row=0, column=1, sticky="ew", padx=(8, 8))
        search_entry.bind("<KeyRelease>", lambda e: self._refresh_log())

        ttk.Label(top, text="Projekt-Filter").grid(row=0, column=2, sticky="e")
        self.filter_project_var = tk.StringVar(value="(alle)")
        self.filter_combo = ttk.Combobox(top, textvariable=self.filter_project_var, state="readonly")
        self.filter_combo.grid(row=0, column=3, sticky="ew", padx=(8, 8))
        self.filter_combo.bind("<<ComboboxSelected>>", lambda e: self._refresh_log())

        ttk.Button(top, text="CSV Export", command=self.export_csv).grid(row=0, column=4, sticky="e", padx=(8, 0))
        ttk.Button(top, text="MD Export", command=self.export_md).grid(row=0, column=5, sticky="e")

        # Treeview
        columns = ("time", "model", "preview", "tags")
        self.tree = ttk.Treeview(frm, columns=columns, show="headings", height=16)
        self.tree.grid(row=2, column=0, sticky="ns", pady=(10, 0))

        self.tree.heading("time", text="Datum")
        self.tree.heading("model", text="Modell")
        self.tree.heading("preview", text="Prompt (Preview)")
        self.tree.heading("tags", text="Tags")

        self.tree.column("time", width=140, anchor="w", stretch=False)
        self.tree.column("model", width=160, anchor="w", stretch=False)
        self.tree.column("preview", width=900, anchor="w", stretch=False)
        self.tree.column("tags", width=160, anchor="w", stretch=False)

        self.tree.bind("<<TreeviewSelect>>", self._on_select_entry)
        self.tree.bind("<Double-1>", lambda e: self._open_detail_popup())

        # MouseWheel: normal = vertical, Shift+Wheel = horizontal
        self.tree.bind("<MouseWheel>", self._on_mousewheel)
        self.tree.bind("<Button-4>", self._on_mousewheel)
        self.tree.bind("<Button-5>", self._on_mousewheel)

        # Vertical scrollbar
        vsb = ttk.Scrollbar(frm, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.place(in_=self.tree, relx=1.0, rely=0, relheight=1.0, anchor="ne")
        
        # Horizontal scrollbar
        hsb = ttk.Scrollbar(frm, orient="horizontal", command=self.tree.xview)
        self.tree.configure(xscrollcommand=hsb.set)
        hsb.grid(row=3, column=0, sticky="ew")
        
        # Detail box + actions
        bottom = ttk.Frame(frm)
        bottom.grid(row=4, column=0, sticky="ew")
        bottom.columnconfigure(0, weight=1)

        self.detail_txt = tk.Text(bottom, height=10, wrap="word", state="disabled")
        self.detail_txt.grid(row=0, column=0, sticky="ew")

        actions = ttk.Frame(frm)
        actions.grid(row=5, column=0, sticky="ew")
        ttk.Button(actions, text="Detail öffnen (Popup)", command=self._open_detail_popup).pack(side="left")
        ttk.Button(actions, text="Ausgewählten löschen", command=self.delete_selected).pack(side="left", padx=8)
        ttk.Button(actions, text="Aktualisieren", command=self._refresh_log).pack(side="right")

    # ---------------- Logic ----------------
    def _on_model_selected(self, _evt=None):
        is_custom = (self.model_var.get() == "Custom…")
        if is_custom:
            self.custom_model_entry.configure(state="normal")
            self.custom_model_entry.focus_set()
        else:
            self.custom_model_entry.configure(state="disabled")

    def _fill_now(self):
        self.ts_var.set(now_local_iso())

    def _get_model_value(self):
        m = self.model_var.get()
        if m == "Custom…":
            cm = self.custom_model_var.get().strip()
            return cm if cm else "Custom"
        return m

    def _clear_input_fields(self, keep_optional: bool = False):
        self.ts_var.set("")
        self.prompt_txt.delete("1.0", "end")
        self.response_txt.delete("1.0", "end")

        # Zweck/Task soll nach jedem Absenden neu sein
        self.purpose_var.set("")

        if not keep_optional:
            # Optional-Felder komplett leeren (nur beim manuellen "Felder leeren")
            self.section_var.set("")
            self.tags_var.set("")
            self.contrib_var.set("")   # Projekt
            self.pending_media_prompt = []
            self.pending_media_response = []
            self._update_media_label()
        # keep model selection as-is

    def _toast(self, msg: str, ms: int = 5000):
        # Cancel previous timer if any
        if getattr(self, "_toast_after_id", None):
            try:
                self.after_cancel(self._toast_after_id)
            except Exception:
                pass
            self._toast_after_id = None

        if hasattr(self, "toast_var"):
            self.toast_var.set(msg)

        # Position relativ zum Absenden-Button
        self.update_idletasks()  # Größen/Positionen aktualisieren

        btn_x = self.submit_top.winfo_rootx() - self.winfo_rootx()
        btn_y = self.submit_top.winfo_rooty() - self.winfo_rooty()
        btn_h = self.submit_top.winfo_height()

        # Toast links neben dem Button, vertikal mittig
        x = max(10, btn_x + 90)         # rechter Rand vom Toast (10px Abstand)
        y = btn_y + btn_h // 2 - 1       # -1 ist ein kleiner optischer Lift

        self.toast_label.place(
            x=x,
            y=y,
            anchor="e"  # Toast hängt nach links, NICHT nach rechts
        )

        def clear():
            if hasattr(self, "toast_var"):
                self.toast_var.set("")
                self.toast_label.place_forget()
            self._toast_after_id = None

        self._toast_after_id = self.after(ms, clear)

    def _open_media_file(self, filename: str):
        path = os.path.join(MEDIA_DIR, filename)
        if not os.path.exists(path):
            messagebox.showerror("Media", f"Datei nicht gefunden:\n{path}")
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                import subprocess
                subprocess.Popen(["open", path])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            messagebox.showerror("Media öffnen fehlgeschlagen", str(e))

    def _update_media_label(self):
        p = getattr(self, "pending_media_prompt", [])
        r = getattr(self, "pending_media_response", [])
        if not p and not r:
            self.media_var.set("Keine Anhänge")
            return

        parts = []
        if p:
            parts.append(f"Prompt: {len(p)}")
        if r:
            parts.append(f"Antwort: {len(r)}")
        self.media_var.set("Anhänge — " + " | ".join(parts))

    def _attach_media(self, target: str):
        path = filedialog.askopenfilename(
            title="Datei anhängen",
            filetypes=[("Alle Dateien", "*.*")]
        )
        if not path:
            return

        try:
            os.makedirs(MEDIA_DIR, exist_ok=True)
            ext = os.path.splitext(path)[1]
            base = os.path.splitext(os.path.basename(path))[0]
            safe_base = "".join(c for c in base if c.isalnum() or c in ("-", "_"))[:40] or "file"
            fname = f"{safe_base}_{uuid.uuid4().hex[:8]}{ext}"
            dest = os.path.join(MEDIA_DIR, fname)
            shutil.copy2(path, dest)

            if target == "prompt":
                self.pending_media_prompt.append(fname)
            else:
                self.pending_media_response.append(fname)

            self._update_media_label()
            self._toast("✓ Datei angehängt", 2500)
        except Exception as e:
            messagebox.showerror("Anhang fehlgeschlagen", str(e))

    def add_entry(self):
        prompt = self.prompt_txt.get("1.0", "end").strip()
        response = self.response_txt.get("1.0", "end").strip()
        if not prompt:
            messagebox.showwarning("Fehlt", "Bitte einen Prompt eingeben.")
            return
        if not response:
            messagebox.showwarning("Fehlt", "Bitte eine Antwort eingeben.")
            return

        ts_raw = self.ts_var.get().strip()
        if ts_raw:
            try:
                dt = parse_dt_flexible(ts_raw)
                ts = dt.replace(microsecond=0).isoformat()
            except Exception as e:
                messagebox.showerror("Datum/Uhrzeit", f"Kann Datum/Uhrzeit nicht lesen:\n{e}")
                return
        else:
            ts = now_local_iso()

        tags = [t.strip() for t in self.tags_var.get().split(",") if t.strip()]

        entry = LogEntry(
            id=str(uuid.uuid4()),
            timestamp=ts,
            model=self._get_model_value(),
            prompt=prompt,
            response=response,
            purpose=self.purpose_var.get().strip(),
            section=self.section_var.get().strip(),
            project=self.contrib_var.get().strip(),
            tags=tags,
            media_prompt=list(self.pending_media_prompt),
            media_response=list(self.pending_media_response),
        )
        self.entries.append(entry)
        self._save_data()
        self.pending_media_prompt = []
        self.pending_media_response = []
        self._update_media_label()
        self._clear_input_fields(keep_optional=True)
        self._refresh_log()
        self._toast("✓ Eintrag gespeichert", 5000)

    def _save_data(self):
        try:
            data = [e.to_dict() for e in self.entries]
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.status_var.set(f"Gespeichert: {os.path.abspath(DATA_FILE)}  |  Einträge: {len(self.entries)}")
        except Exception as e:
            messagebox.showerror("Speichern fehlgeschlagen", str(e))

    def _load_data(self):
        if not os.path.exists(DATA_FILE):
            self.entries = []
            self._update_filter_projects()
            return
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            self.entries = []
            for item in raw:
                self.entries.append(
                    LogEntry(
                        id=item.get("id", str(uuid.uuid4())),
                        timestamp=item.get("timestamp", now_local_iso()),
                        model=item.get("model", "unknown"),
                        prompt=item.get("prompt", ""),
                        response=item.get("response", ""),
                        purpose=item.get("purpose", ""),
                        section=item.get("section", ""),
                        project=item.get("project", ""),
                        tags=item.get("tags", []) or [],
                        media_prompt=item.get("media_prompt", []) or [],
                        media_response=item.get("media_response", []) or [],
                    )
                )
            self._update_filter_projects()
        except Exception as e:
            messagebox.showerror("Laden fehlgeschlagen", f"{e}")
            self.entries = []
            self._update_filter_projects()

    def _update_filter_projects(self):
        projects = sorted(set((e.project or "").strip() for e in self.entries if (e.project or "").strip()))
        values = ["(alle)"] + projects
        self.filter_combo.configure(values=values)
        if self.filter_project_var.get() not in values:
            self.filter_project_var.set("(alle)")

    def _refresh_log(self):
        # Update filter list (in case new model added)
        self._update_filter_projects()

        q = self.search_var.get().strip().lower()
        project_filter = self.filter_project_var.get()

        def matches(e: LogEntry):
            if project_filter != "(alle)" and (e.project or "") != project_filter:
                return False
            if not q:
                return True
            hay = " ".join([
                e.model or "",
                e.timestamp or "",
                e.purpose or "",
                e.section or "",
                e.project or "",
                " ".join(e.tags or []),
                e.prompt or "",
                e.response or "",
            ]).lower()
            return q in hay

        # Sort by timestamp descending (newest first) when possible
        def sort_key(e: LogEntry):
            try:
                return datetime.fromisoformat(e.timestamp)
            except Exception:
                return datetime.min.replace(tzinfo=timezone.utc)

        filtered = [e for e in self.entries if matches(e)]
        filtered.sort(key=sort_key, reverse=True)

        # Rebuild tree
        for row in self.tree.get_children():
            self.tree.delete(row)

        self.filtered_ids = []
        for e in filtered:
            preview = (e.prompt or "").replace("\n", " ").strip()
            if len(preview) > 90:
                preview = preview[:90] + "…"
            tags = ", ".join(e.tags or [])
            self.tree.insert("", "end", iid=e.id, values=(dt_display(e.timestamp), e.model, preview, tags))
            self.filtered_ids.append(e.id)

        # Clear detail if nothing selected
        self._set_detail_text("Wähle einen Eintrag aus (Doppelklick öffnet Detail-Popup).")
        self.status_var.set(f"Datei: {os.path.abspath(DATA_FILE)}  |  Einträge: {len(self.entries)}  |  Treffer: {len(filtered)}")

    def _find_entry(self, entry_id: str):
        for e in self.entries:
            if e.id == entry_id:
                return e
        return None

    def _render_to_text_widget(self, txt: tk.Text, e: LogEntry):
        """Render entry detail into a Text widget with clickable media links."""
        txt.configure(state="normal")
        txt.delete("1.0", "end")

        def put(line=""):
            txt.insert("end", line + "\n")

        put(f"Datum: {e.timestamp}")
        put(f"Modell: {e.model}")

        if e.project:
            put(f"Projekt: {e.project}")
        if e.purpose:
            put(f"Zweck/Task: {e.purpose}")
        if e.section:
            put(f"Kapitel: {e.section}")
        if e.tags:
            put(f"Tags: {', '.join(e.tags)}")

        # Media: clickable filenames
        def put_media(label: str, files: list):
            if not files:
                return
            put(f"{label}:")
            for fname in files:
                start = txt.index("end-1c")
                txt.insert("end", f"  {fname}\n")
                end = txt.index("end-1c")
                tag = f"media::{fname}"
                txt.tag_add(tag, start, end)
                txt.tag_config(tag, foreground="blue", underline=1)
                txt.tag_bind(tag, "<Button-1>", lambda _ev, f=fname: self._open_media_file(f))
                txt.tag_bind(tag, "<Enter>", lambda _ev: txt.config(cursor="hand2"))
                txt.tag_bind(tag, "<Leave>", lambda _ev: txt.config(cursor=""))

        put("")
        put_media("Media (Prompt)", e.media_prompt or [])
        put_media("Media (Antwort)", e.media_response or [])

        put("")
        put("PROMPT:")
        put(e.prompt or "")
        put("")
        put("ANTWORT:")
        put(e.response or "")

        txt.configure(state="disabled")

    def _render_entry_detail(self, e: LogEntry):
        """Render entry detail in the main detail text box."""
        self._render_to_text_widget(self.detail_txt, e)

    def _on_select_entry(self, _evt=None):
        sel = self.tree.selection()
        if not sel:
            return
        entry_id = sel[0]
        e = self._find_entry(entry_id)
        if not e:
            return
        self._render_entry_detail(e)

    def _set_detail_text(self, text: str):
        self.detail_txt.configure(state="normal")
        self.detail_txt.delete("1.0", "end")
        self.detail_txt.insert("1.0", text)
        self.detail_txt.configure(state="disabled")

    def _format_entry_detail(self, e: LogEntry):
        lines = []
        lines.append(f"Datum: {e.timestamp}")
        lines.append(f"Modell: {e.model}")

        if e.project:
            lines.append(f"Projekt: {e.project}")
        if e.purpose:
            lines.append(f"Zweck/Task: {e.purpose}")
        if e.section:
            lines.append(f"Kapitel: {e.section}")
        if e.tags:
            lines.append(f"Tags: {', '.join(e.tags)}")
        if e.media_prompt:
            lines.append(f"Media (Prompt): {', '.join(e.media_prompt)}")
        if e.media_response:
            lines.append(f"Media (Antwort): {', '.join(e.media_response)}")

        lines.append("")
        lines.append("PROMPT:")
        lines.append(e.prompt or "")
        lines.append("")
        lines.append("ANTWORT:")
        lines.append(e.response or "")
        return "\n".join(lines)

    def _on_mousewheel(self, event):
        # Shift pressed? (Windows/Linux state mask)
        shift_pressed = (event.state & 0x0001) != 0

        # Determine direction
        if getattr(event, "num", None) == 4:
            delta = 1
        elif getattr(event, "num", None) == 5:
            delta = -1
        else:
            # Windows/macOS: event.delta is typically +/-120 multiples
            delta = 1 if event.delta > 0 else -1

        if shift_pressed:
            # horizontal
            self.tree.xview_scroll(-delta, "units")
        else:
            # vertical
            self.tree.yview_scroll(-delta, "units")

        return "break"

    def _open_detail_popup(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Detail", "Bitte erst einen Eintrag auswählen.")
            return
        entry_id = sel[0]
        e = self._find_entry(entry_id)
        if not e:
            return

        win = tk.Toplevel(self)
        win.title("Eintrag – Detail")
        win.minsize(800, 600)

        frm = ttk.Frame(win, padding=12)
        frm.pack(fill="both", expand=True)
        frm.rowconfigure(1, weight=1)
        frm.columnconfigure(0, weight=1)

        header = ttk.Frame(frm)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text=f"{dt_display(e.timestamp)}  |  {e.model}", font=("TkDefaultFont", 11, "bold")).grid(row=0, column=0, sticky="w")

        txt = tk.Text(frm, wrap="word")
        txt.grid(row=1, column=0, sticky="nsew", pady=(10, 10))
        self._render_to_text_widget(txt, e)

        btns = ttk.Frame(frm)
        btns.grid(row=2, column=0, sticky="ew")
        ttk.Button(btns, text="Schließen", command=win.destroy).pack(side="right")

    def delete_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Löschen", "Bitte erst einen Eintrag auswählen.")
            return
        entry_id = sel[0]
        e = self._find_entry(entry_id)
        if not e:
            return
        ok = messagebox.askyesno("Löschen", "Diesen Eintrag wirklich löschen?")
        if not ok:
            return
        self.entries = [x for x in self.entries if x.id != entry_id]
        self._save_data()
        self._refresh_log()

    # ---------------- Export ----------------
    def _get_export_criteria(self):
        # returns dict: {"project": str|None, "model": str|None, "tags": set[str]|None}
        win = tk.Toplevel(self)
        win.title("Export – Filter")
        win.transient(self)
        win.grab_set()
        win.resizable(False, False)

        frm = ttk.Frame(win, padding=12)
        frm.pack(fill="both", expand=True)

        # values
        projects = sorted(set((e.project or "").strip() for e in self.entries if (e.project or "").strip()))
        models = sorted(set((e.model or "").strip() for e in self.entries if (e.model or "").strip()))

        project_var = tk.StringVar(value="(alle)")
        model_var = tk.StringVar(value="(alle)")
        tags_var = tk.StringVar(value="")

        ttk.Label(frm, text="Projekt").grid(row=0, column=0, sticky="w")
        ttk.Combobox(frm, textvariable=project_var, values=["(alle)"] + projects, state="readonly").grid(row=1, column=0, sticky="ew", pady=(0, 8))

        ttk.Label(frm, text="Modell").grid(row=2, column=0, sticky="w")
        ttk.Combobox(frm, textvariable=model_var, values=["(alle)"] + models, state="readonly").grid(row=3, column=0, sticky="ew", pady=(0, 8))

        ttk.Label(frm, text="Tags (kommagetrennt, optional)").grid(row=4, column=0, sticky="w")
        ttk.Entry(frm, textvariable=tags_var).grid(row=5, column=0, sticky="ew", pady=(0, 8))

        frm.columnconfigure(0, weight=1)

        result = {"project": None, "model": None, "tags": None}

        def ok():
            p = project_var.get()
            m = model_var.get()
            t = [x.strip() for x in tags_var.get().split(",") if x.strip()]
            result["project"] = None if p == "(alle)" else p
            result["model"] = None if m == "(alle)" else m
            result["tags"] = None if not t else set(t)
            win.destroy()

        def cancel():
            # None signals "cancel export"
            result.clear()
            win.destroy()

        btns = ttk.Frame(frm)
        btns.grid(row=6, column=0, sticky="e", pady=(8, 0))
        ttk.Button(btns, text="Abbrechen", command=cancel).pack(side="right")
        ttk.Button(btns, text="Exportieren", command=ok).pack(side="right", padx=(0, 8))

        self.wait_window(win)
        return result if result else None

    def _filter_entries_for_export(self, criteria):
        # criteria: dict from _get_export_criteria
        out = []
        for e in self._get_current_view_entries():
            if criteria.get("project") and (e.project or "") != criteria["project"]:
                continue
            if criteria.get("model") and (e.model or "") != criteria["model"]:
                continue
            tags = criteria.get("tags")
            if tags:
                etags = set(e.tags or [])
                if etags.isdisjoint(tags):
                    continue
            out.append(e)
        return out

    def export_csv(self):
        if not self.entries:
            messagebox.showinfo("Export", "Keine Einträge zum Exportieren.")
            return
        criteria = self._get_export_criteria()
        if criteria is None:
            return
        export_entries = self._filter_entries_for_export(criteria)
        if not export_entries:
            messagebox.showinfo("Export", "Keine Einträge passen zu den gewählten Filtern.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            title="CSV Export speichern",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f, delimiter=",")
                writer.writerow([
                    "timestamp", "model", "project", "purpose", "section", "tags",
                    "media_prompt", "media_response",
                    "prompt", "response", "id"
                ])
                for e in export_entries:
                    writer.writerow([
                        e.timestamp,
                        e.model,
                        e.project,
                        e.purpose,
                        e.section,
                        ", ".join(e.tags or []),
                        ", ".join(e.media_prompt or []),
                        ", ".join(e.media_response or []),
                        e.prompt,
                        e.response,
                        e.id,
                    ])
            messagebox.showinfo("Export", f"CSV gespeichert:\n{path}")
        except Exception as e:
            messagebox.showerror("Export fehlgeschlagen", str(e))

    def export_md(self):
        if not self.entries:
            messagebox.showinfo("Export", "Keine Einträge zum Exportieren.")
            return
        criteria = self._get_export_criteria()
        if criteria is None:
            return
        export_entries = self._filter_entries_for_export(criteria)
        if not export_entries:
            messagebox.showinfo("Export", "Keine Einträge passen zu den gewählten Filtern.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".md",
            filetypes=[("Markdown", "*.md")],
            title="Markdown Export speichern",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("# KI-Logbuch Export\n\n")
                f.write(f"_Exportzeitpunkt: {now_local_iso()}_\n\n")
                for i, e in enumerate(export_entries, start=1):
                    f.write(f"## {i}. {dt_display(e.timestamp)} — {e.model}\n\n")
                    meta = []
                    if e.purpose:
                        meta.append(f"**Zweck/Task:** {e.purpose}")
                    if e.section:
                        meta.append(f"**Kapitel:** {e.section}")
                    if e.tags:
                        meta.append(f"**Tags:** {', '.join(e.tags)}")
                    if e.project:
                        meta.append(f"**Projekt:** {e.project}")
                    if e.media_prompt:
                        meta.append(f"**Media (Prompt):** {', '.join(e.media_prompt)}")
                    if e.media_response:
                        meta.append(f"**Media (Antwort):** {', '.join(e.media_response)}")
                    if meta:
                        f.write("\n\n".join(meta) + "\n\n")

                    f.write("### Prompt\n\n")
                    f.write("```text\n")
                    f.write((e.prompt or "").rstrip() + "\n")
                    f.write("```\n\n")

                    f.write("### Antwort\n\n")
                    f.write("```text\n")
                    f.write((e.response or "").rstrip() + "\n")
                    f.write("```\n\n")

                    f.write("---\n\n")
            messagebox.showinfo("Export", f"Markdown gespeichert:\n{path}")
        except Exception as e:
            messagebox.showerror("Export fehlgeschlagen", str(e))

    def _get_current_view_entries(self):
        # Use current tree order, if any; else fallback to all sorted newest-first
        ids = list(self.tree.get_children())
        if ids:
            out = []
            for entry_id in ids:
                e = self._find_entry(entry_id)
                if e:
                    out.append(e)
            return out

        def sort_key(e: LogEntry):
            try:
                return datetime.fromisoformat(e.timestamp)
            except Exception:
                return datetime.min.replace(tzinfo=timezone.utc)

        return sorted(self.entries, key=sort_key, reverse=True)


if __name__ == "__main__":
    app = LogbookApp()
    app.mainloop()
