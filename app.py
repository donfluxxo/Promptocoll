import json
import csv
import os
import uuid
import sys
import shutil
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Optional, List, Dict
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path

APP_TITLE = "Promptocoll"
BASE_DIR = Path(sys.executable if getattr(sys, 'frozen', False) else __file__).parent
DATA_FILE = BASE_DIR / "log.json"
MEDIA_DIR = BASE_DIR / "Media"
MEDIA_DIR.mkdir(exist_ok=True)

MODEL_PRESETS = [
    "Keine Angabe", "gpt-5.2", "gpt-5.1-instant", "gpt-5.1-thinking",
    "gpt-4o", "gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano", "o4-mini",
    "claude-3.5-sonnet", "claude-4.5-sonnet", "gemini-1.5-pro", "Custom…"
]


def resource_path(relative_path: str) -> Path:
    """Get absolute path to resource, works for dev and PyInstaller."""
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS) / relative_path
    return BASE_DIR / relative_path


def now_local_iso() -> str:
    """Return current local time as ISO string without microseconds."""
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def parse_dt_flexible(s: str) -> datetime:
    """Parse flexible datetime formats (ISO or 'YYYY-MM-DD HH:MM(:SS)')."""
    s = (s or "").strip()
    if not s:
        raise ValueError("Leerer Zeitstempel")
    
    try:
        dt = datetime.fromisoformat(s.replace(" ", "T"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
        return dt
    except Exception:
        raise ValueError("Unbekanntes Datumsformat")


def dt_display(dt_iso: str) -> str:
    """Format datetime for display."""
    try:
        return datetime.fromisoformat(dt_iso).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return dt_iso


@dataclass
class LogEntry:
    id: str
    timestamp: str
    model: str
    prompt: str
    response: str
    purpose: str = ""
    section: str = ""
    project: str = ""
    tags: List[str] = field(default_factory=list)
    media_prompt: List[str] = field(default_factory=list)
    media_response: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> 'LogEntry':
        """Create LogEntry from dict with defaults for missing fields."""
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            timestamp=data.get("timestamp", now_local_iso()),
            model=data.get("model", "unknown"),
            prompt=data.get("prompt", ""),
            response=data.get("response", ""),
            purpose=data.get("purpose", ""),
            section=data.get("section", ""),
            project=data.get("project", ""),
            tags=data.get("tags") or [],
            media_prompt=data.get("media_prompt") or [],
            media_response=data.get("media_response") or []
        )
    
    def matches_search(self, query: str) -> bool:
        """Check if entry matches search query."""
        if not query:
            return True
        haystack = " ".join([
            self.model, self.timestamp, self.purpose, self.section,
            self.project, " ".join(self.tags), self.prompt, self.response
        ]).lower()
        return query in haystack
    
    def sort_key(self) -> datetime:
        """Return datetime for sorting (newest first)."""
        try:
            return datetime.fromisoformat(self.timestamp)
        except Exception:
            return datetime.min.replace(tzinfo=timezone.utc)


class LogbookApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.minsize(980, 640)
        
        self._load_icons()
        self.entries: List[LogEntry] = []
        self.filtered_ids: List[str] = []
        self.pending_media_prompt: List[str] = []
        self.pending_media_response: List[str] = []
        self._toast_after_id: Optional[str] = None
        
        self._build_ui()
        self._load_data()
        self._refresh_log()

    def _load_icons(self):
        """Load application icons."""
        try:
            ico_path = resource_path("favicon.ico")
            if ico_path.exists():
                self.iconbitmap(str(ico_path))
        except Exception:
            pass
        
        try:
            png_path = resource_path("icon.png")
            if png_path.exists():
                self._app_icon_img = tk.PhotoImage(file=str(png_path))
                self.iconphoto(True, self._app_icon_img)
        except Exception:
            pass

    def _build_ui(self):
        """Build main UI structure."""
        self.style = ttk.Style(self)
        self.style.configure("TButton", padding=6)
        self.style.configure("TLabel", padding=(0, 2))
        self.style.configure("Submit.TButton", font=("TkDefaultFont", 10, "bold"), padding=10)

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True)

        self.tab_input = ttk.Frame(notebook, padding=12)
        self.tab_log = ttk.Frame(notebook, padding=12)
        notebook.add(self.tab_input, text="Input")
        notebook.add(self.tab_log, text="Log")

        self._build_input_tab()
        self._build_log_tab()

        # Footer
        footer = ttk.Frame(self, padding=(12, 0, 12, 10))
        footer.pack(fill="x")
        self.status_var = tk.StringVar(value=f"Datei: {DATA_FILE}")
        ttk.Label(footer, textvariable=self.status_var).pack(side="left")

    def _build_input_tab(self):
        """Build input form tab."""
        frm = self.tab_input
        frm.columnconfigure(0, weight=1)
        frm.columnconfigure(1, weight=1)

        # Logo
        logo_path = resource_path("logo.png")
        if logo_path.exists():
            try:
                self.logo_img = tk.PhotoImage(file=str(logo_path))
                ttk.Label(frm, image=self.logo_img).grid(
                    row=0, column=2, rowspan=4, sticky="ne", padx=(10, 0)
                )
            except Exception:
                pass

        # Model selection
        ttk.Label(frm, text="KI-Modell").grid(row=0, column=0, sticky="w")
        self.model_var = tk.StringVar(value=MODEL_PRESETS[0])
        self.model_combo = ttk.Combobox(
            frm, textvariable=self.model_var, 
            values=MODEL_PRESETS, state="readonly"
        )
        self.model_combo.grid(row=1, column=0, sticky="ew", padx=(0, 8))
        self.model_combo.bind("<<ComboboxSelected>>", self._on_model_selected)

        ttk.Label(frm, text="Custom Modell (nur wenn 'Custom…')").grid(
            row=0, column=1, sticky="w"
        )
        self.custom_model_var = tk.StringVar()
        self.custom_model_entry = ttk.Entry(frm, textvariable=self.custom_model_var)
        self.custom_model_entry.grid(row=1, column=1, sticky="ew")

        # Timestamp
        ttk.Label(frm, text="Datum/Uhrzeit (leer = jetzt)").grid(
            row=2, column=0, sticky="w", pady=(10, 0)
        )
        self.ts_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.ts_var).grid(
            row=3, column=0, sticky="ew", padx=(0, 8)
        )

        ttk.Label(frm, text="Beispiel: 2026-01-09 14:23 oder ISO").grid(
            row=2, column=1, sticky="w", pady=(10, 0)
        )
        date_btns = ttk.Frame(frm)
        date_btns.grid(row=3, column=1, sticky="ew")
        
        ttk.Button(date_btns, text="Jetzt einsetzen", 
                   command=lambda: self.ts_var.set(now_local_iso())).pack(side="left")
        
        self.submit_top = ttk.Button(
            date_btns, text="Absenden",
            command=self.add_entry, style="Submit.TButton"
        )
        self.submit_top.pack(side="right")

        # Toast notification label
        self.toast_var = tk.StringVar()
        self.toast_label = ttk.Label(frm, textvariable=self.toast_var)
        self.toast_label.place_forget()

        # Text fields
        ttk.Label(frm, text="Prompt").grid(row=4, column=0, sticky="w", pady=(10, 0))
        self.prompt_txt = tk.Text(frm, height=10, wrap="word")
        self.prompt_txt.grid(row=5, column=0, columnspan=2, sticky="nsew")
        frm.rowconfigure(5, weight=1)

        ttk.Label(frm, text="Antwort").grid(row=6, column=0, sticky="w", pady=(10, 0))
        self.response_txt = tk.Text(frm, height=10, wrap="word")
        self.response_txt.grid(row=7, column=0, columnspan=2, sticky="nsew")
        frm.rowconfigure(7, weight=1)

        # Optional fields
        opt = ttk.LabelFrame(frm, text="Optional (hilft bei Eigenleistung / Struktur)", padding=10)
        opt.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        opt.columnconfigure(0, weight=1)
        opt.columnconfigure(1, weight=1)

        fields = [
            ("Zweck/Task", "purpose_var", 0),
            ("Kapitel", "section_var", 1),
            ("Tags (kommagetrennt)", "tags_var", 0),
            ("Projekt", "contrib_var", 1)
        ]
        
        for i, (label, var_name, col) in enumerate(fields):
            row = i // 2 * 2
            ttk.Label(opt, text=label).grid(
                row=row, column=col, sticky="w", 
                pady=(8 if i >= 2 else 0, 0)
            )
            setattr(self, var_name, tk.StringVar())
            ttk.Entry(opt, textvariable=getattr(self, var_name)).grid(
                row=row + 1, column=col, sticky="ew",
                padx=(0, 8 if col == 0 else 0)
            )

        # Action buttons
        btns = ttk.Frame(frm)
        btns.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        
        ttk.Button(btns, text="Felder leeren", 
                   command=self._clear_input_fields).pack(side="left", padx=8)
        ttk.Button(btns, text="📎 Prompt", 
                   command=lambda: self._attach_media("prompt")).pack(side="left", padx=8)
        ttk.Button(btns, text="📎 Antwort", 
                   command=lambda: self._attach_media("response")).pack(side="left", padx=8)
        
        self.media_var = tk.StringVar(value="Keine Anhänge")
        ttk.Label(btns, textvariable=self.media_var).pack(side="left", padx=8)

        self._on_model_selected()

    def _build_log_tab(self):
        """Build log view tab."""
        frm = self.tab_log
        frm.columnconfigure(0, weight=1)
        frm.rowconfigure(2, weight=1)

        # Search and filter controls
        top = ttk.Frame(frm)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(2, weight=1)

        ttk.Label(top, text="Suche").grid(row=0, column=0, sticky="w")
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(top, textvariable=self.search_var)
        search_entry.grid(row=0, column=1, sticky="ew", padx=(8, 8))
        search_entry.bind("<KeyRelease>", lambda e: self._refresh_log())

        ttk.Label(top, text="Projekt-Filter").grid(row=0, column=2, sticky="e")
        self.filter_project_var = tk.StringVar(value="(alle)")
        self.filter_combo = ttk.Combobox(
            top, textvariable=self.filter_project_var, state="readonly"
        )
        self.filter_combo.grid(row=0, column=3, sticky="ew", padx=(8, 8))
        self.filter_combo.bind("<<ComboboxSelected>>", lambda e: self._refresh_log())

        ttk.Button(top, text="CSV Export", command=self.export_csv).grid(
            row=0, column=4, sticky="e", padx=(8, 0)
        )
        ttk.Button(top, text="MD Export", command=self.export_md).grid(
            row=0, column=5, sticky="e"
        )

        # Treeview
        columns = ("time", "model", "preview", "tags")
        self.tree = ttk.Treeview(frm, columns=columns, show="headings", height=16)
        self.tree.grid(row=2, column=0, sticky="nsew", pady=(10, 0))

        col_config = [
            ("time", "Datum", 140),
            ("model", "Modell", 160),
            ("preview", "Prompt (Preview)", 900),
            ("tags", "Tags", 160)
        ]
        
        for col_id, heading, width in col_config:
            self.tree.heading(col_id, text=heading)
            self.tree.column(col_id, width=width, anchor="w", stretch=False)

        self.tree.bind("<<TreeviewSelect>>", self._on_select_entry)
        self.tree.bind("<Double-1>", lambda e: self._open_detail_popup())
        self.tree.bind("<MouseWheel>", self._on_mousewheel)
        self.tree.bind("<Button-4>", self._on_mousewheel)
        self.tree.bind("<Button-5>", self._on_mousewheel)

        # Scrollbars
        vsb = ttk.Scrollbar(frm, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.place(in_=self.tree, relx=1.0, rely=0, relheight=1.0, anchor="ne")
        
        hsb = ttk.Scrollbar(frm, orient="horizontal", command=self.tree.xview)
        self.tree.configure(xscrollcommand=hsb.set)
        hsb.grid(row=3, column=0, sticky="ew")

        # Detail view
        self.detail_txt = tk.Text(frm, height=10, wrap="word", state="disabled")
        self.detail_txt.grid(row=4, column=0, sticky="ew")

        # Action buttons
        actions = ttk.Frame(frm)
        actions.grid(row=5, column=0, sticky="ew")
        ttk.Button(actions, text="Detail öffnen (Popup)", 
                   command=self._open_detail_popup).pack(side="left")
        ttk.Button(actions, text="Ausgewählten löschen", 
                   command=self.delete_selected).pack(side="left", padx=8)
        ttk.Button(actions, text="Aktualisieren", 
                   command=self._refresh_log).pack(side="right")

    def _on_model_selected(self, _evt=None):
        """Handle model selection change."""
        is_custom = self.model_var.get() == "Custom…"
        state = "normal" if is_custom else "disabled"
        self.custom_model_entry.configure(state=state)
        if is_custom:
            self.custom_model_entry.focus_set()

    def _get_model_value(self) -> str:
        """Get selected model name."""
        model = self.model_var.get()
        if model == "Custom…":
            custom = self.custom_model_var.get().strip()
            return custom if custom else "Custom"
        return model

    def _clear_input_fields(self, keep_optional: bool = False):
        """Clear input fields."""
        self.ts_var.set("")
        self.prompt_txt.delete("1.0", "end")
        self.response_txt.delete("1.0", "end")
        self.purpose_var.set("")

        if not keep_optional:
            self.section_var.set("")
            self.tags_var.set("")
            self.contrib_var.set("")
            self.pending_media_prompt = []
            self.pending_media_response = []
            self._update_media_label()

    def _toast(self, msg: str, ms: int = 5000):
        """Show temporary notification."""
        if self._toast_after_id:
            try:
                self.after_cancel(self._toast_after_id)
            except Exception:
                pass

        self.toast_var.set(msg)
        self.update_idletasks()

        btn_x = self.submit_top.winfo_rootx() - self.winfo_rootx()
        btn_y = self.submit_top.winfo_rooty() - self.winfo_rooty()
        btn_h = self.submit_top.winfo_height()

        self.toast_label.place(
            x=max(10, btn_x + 90),
            y=btn_y + btn_h // 2 - 1,
            anchor="e"
        )

        self._toast_after_id = self.after(ms, self._clear_toast)

    def _clear_toast(self):
        """Clear toast notification."""
        self.toast_var.set("")
        self.toast_label.place_forget()
        self._toast_after_id = None

    def _update_media_label(self):
        """Update media attachment label."""
        p_count = len(self.pending_media_prompt)
        r_count = len(self.pending_media_response)
        
        if not p_count and not r_count:
            self.media_var.set("Keine Anhänge")
            return

        parts = []
        if p_count:
            parts.append(f"Prompt: {p_count}")
        if r_count:
            parts.append(f"Antwort: {r_count}")
        self.media_var.set("Anhänge — " + " | ".join(parts))

    def _attach_media(self, target: str):
        """Attach media file to prompt or response."""
        path = filedialog.askopenfilename(
            title="Datei anhängen",
            filetypes=[("Alle Dateien", "*.*")]
        )
        if not path:
            return

        try:
            src = Path(path)
            ext = src.suffix
            base = "".join(c for c in src.stem if c.isalnum() or c in ("-", "_"))[:40] or "file"
            fname = f"{base}_{uuid.uuid4().hex[:8]}{ext}"
            dest = MEDIA_DIR / fname
            
            shutil.copy2(src, dest)

            if target == "prompt":
                self.pending_media_prompt.append(fname)
            else:
                self.pending_media_response.append(fname)

            self._update_media_label()
            self._toast("✓ Datei angehängt", 2500)
        except Exception as e:
            messagebox.showerror("Anhang fehlgeschlagen", str(e))

    def _open_media_file(self, filename: str):
        """Open media file with system default application."""
        path = MEDIA_DIR / filename
        if not path.exists():
            messagebox.showerror("Media", f"Datei nicht gefunden:\n{path}")
            return

        try:
            if sys.platform.startswith("win"):
                os.startfile(str(path))
            elif sys.platform == "darwin":
                import subprocess
                subprocess.Popen(["open", str(path)])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as e:
            messagebox.showerror("Media öffnen fehlgeschlagen", str(e))

    def add_entry(self):
        """Add new log entry."""
        prompt = self.prompt_txt.get("1.0", "end").strip()
        response = self.response_txt.get("1.0", "end").strip()
        
        if not prompt:
            messagebox.showwarning("Fehlt", "Bitte einen Prompt eingeben.")
            return
        if not response:
            messagebox.showwarning("Fehlt", "Bitte eine Antwort eingeben.")
            return

        # Parse timestamp
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
            media_response=list(self.pending_media_response)
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
        """Save entries to JSON file."""
        try:
            data = [e.to_dict() for e in self.entries]
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.status_var.set(
                f"Gespeichert: {DATA_FILE}  |  Einträge: {len(self.entries)}"
            )
        except Exception as e:
            messagebox.showerror("Speichern fehlgeschlagen", str(e))

    def _load_data(self):
        """Load entries from JSON file."""
        if not DATA_FILE.exists():
            self.entries = []
            self._update_filter_projects()
            return

        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            self.entries = [LogEntry.from_dict(item) for item in raw]
            self._update_filter_projects()
        except Exception as e:
            messagebox.showerror("Laden fehlgeschlagen", str(e))
            self.entries = []
            self._update_filter_projects()

    def _update_filter_projects(self):
        """Update project filter dropdown."""
        projects = sorted(set(
            e.project.strip() for e in self.entries 
            if e.project.strip()
        ))
        values = ["(alle)"] + projects
        self.filter_combo.configure(values=values)
        
        if self.filter_project_var.get() not in values:
            self.filter_project_var.set("(alle)")

    def _refresh_log(self):
        """Refresh log view with current filters."""
        self._update_filter_projects()

        query = self.search_var.get().strip().lower()
        project_filter = self.filter_project_var.get()

        # Filter entries
        filtered = [
            e for e in self.entries
            if (project_filter == "(alle)" or e.project == project_filter)
            and e.matches_search(query)
        ]
        
        # Sort by timestamp (newest first)
        filtered.sort(key=lambda e: e.sort_key(), reverse=True)

        # Rebuild tree
        for row in self.tree.get_children():
            self.tree.delete(row)

        self.filtered_ids = []
        for e in filtered:
            preview = e.prompt.replace("\n", " ").strip()
            if len(preview) > 90:
                preview = preview[:90] + "…"
            
            self.tree.insert("", "end", iid=e.id, values=(
                dt_display(e.timestamp),
                e.model,
                preview,
                ", ".join(e.tags)
            ))
            self.filtered_ids.append(e.id)

        self._set_detail_text("Wähle einen Eintrag aus (Doppelklick öffnet Detail-Popup).")
        self.status_var.set(
            f"Datei: {DATA_FILE}  |  Einträge: {len(self.entries)}  |  Treffer: {len(filtered)}"
        )

    def _find_entry(self, entry_id: str) -> Optional[LogEntry]:
        """Find entry by ID."""
        return next((e for e in self.entries if e.id == entry_id), None)

    def _render_to_text_widget(self, txt: tk.Text, e: LogEntry):
        """Render entry detail into Text widget with clickable media."""
        txt.configure(state="normal")
        txt.delete("1.0", "end")

        def put(line=""):
            txt.insert("end", line + "\n")

        # Metadata
        put(f"Datum: {e.timestamp}")
        put(f"Modell: {e.model}")
        
        for field, label in [
            ("project", "Projekt"), ("purpose", "Zweck/Task"),
            ("section", "Kapitel")
        ]:
            value = getattr(e, field)
            if value:
                put(f"{label}: {value}")
        
        if e.tags:
            put(f"Tags: {', '.join(e.tags)}")

        # Media attachments (clickable)
        def put_media(label: str, files: List[str]):
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
                txt.tag_bind(tag, "<Button-1>", 
                            lambda _ev, f=fname: self._open_media_file(f))
                txt.tag_bind(tag, "<Enter>", 
                            lambda _ev: txt.config(cursor="hand2"))
                txt.tag_bind(tag, "<Leave>", 
                            lambda _ev: txt.config(cursor=""))

        put("")
        put_media("Media (Prompt)", e.media_prompt)
        put_media("Media (Antwort)", e.media_response)

        # Prompt and response
        put("")
        put("PROMPT:")
        put(e.prompt)
        put("")
        put("ANTWORT:")
        put(e.response)

        txt.configure(state="disabled")

    def _on_select_entry(self, _evt=None):
        """Handle entry selection in tree."""
        sel = self.tree.selection()
        if not sel:
            return
        
        entry = self._find_entry(sel[0])
        if entry:
            self._render_to_text_widget(self.detail_txt, entry)

    def _set_detail_text(self, text: str):
        """Set detail text box content."""
        self.detail_txt.configure(state="normal")
        self.detail_txt.delete("1.0", "end")
        self.detail_txt.insert("1.0", text)
        self.detail_txt.configure(state="disabled")

    def _on_mousewheel(self, event):
        """Handle mousewheel scrolling (Shift for horizontal)."""
        shift_pressed = (event.state & 0x0001) != 0

        # Determine scroll direction
        if hasattr(event, "num"):
            delta = 1 if event.num == 4 else -1
        else:
            delta = 1 if event.delta > 0 else -1

        if shift_pressed:
            self.tree.xview_scroll(-delta, "units")
        else:
            self.tree.yview_scroll(-delta, "units")

        return "break"

    def _open_detail_popup(self):
        """Open detail view in popup window."""
        sel = self