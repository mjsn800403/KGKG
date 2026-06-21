# parser_gui.py
#
# Friendly desktop front-end for htmlparser_logical.py.
#
# Pick the backend folder (the one with db.sqlite3) and the folder that holds
# your "LEMON *.zip" files, press Start, and watch the progress. No terminal,
# no Python knowledge required.
#
# Run from source:   python parser_gui.py
# Build a .exe:       see build_exe.bat

import sys
import os
import io
import json
import queue
import threading
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

import htmlparser_logical as parser


# --------------------------------------------------------------------- config
def _config_path() -> Path:
    """Remember the last-used folders next to the app (or exe)."""
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) \
        else Path(__file__).resolve().parent
    return base / "parser_gui_config.json"


def load_config() -> dict:
    try:
        return json.loads(_config_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(cfg: dict) -> None:
    try:
        _config_path().write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
    except Exception:
        pass


# ----------------------------------------------------------- stdout -> queue
class QueueWriter(io.TextIOBase):
    """A file-like object that funnels everything the parser prints into a
    thread-safe queue, so the GUI (main thread) can render it safely."""

    def __init__(self, q: "queue.Queue[str]"):
        self.q = q

    def write(self, s: str) -> int:
        if s:
            self.q.put(s)
        return len(s)

    def flush(self) -> None:
        pass


# --------------------------------------------------------------------- app
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("پردازشگر مستندات فنی خودرو — KGtechvault")
        self.geometry("860x640")
        self.minsize(720, 520)

        self.log_q: "queue.Queue[str]" = queue.Queue()
        self.worker: threading.Thread | None = None
        self.cancel_event = threading.Event()   # set -> parser pauses & checkpoints
        cfg = load_config()

        self.backend_var = tk.StringVar(value=cfg.get("backend", ""))
        self.zips_var = tk.StringVar(value=cfg.get("zips", ""))
        self.workers_var = tk.StringVar(value=cfg.get("workers", ""))
        self.force_var = tk.BooleanVar(value=False)   # reprocess completed zips

        self._build_ui()
        self.after(100, self._drain_log)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ----------------------------------------------------------------- layout
    def _build_ui(self) -> None:
        pad = {"padx": 12, "pady": 6}

        header = ttk.Label(
            self, text="🚗  پردازشگر مستندات فنی خودرو",
            font=("Segoe UI", 16, "bold"),
        )
        header.pack(anchor="e", **pad)

        # --- backend folder row
        self._folder_row(
            "📁  پوشه‌ی بک‌اند  (پوشه‌ای که فایل db.sqlite3 در آن است)",
            self.backend_var, self._browse_backend,
        )
        # --- zips folder row
        self._folder_row(
            "📦  پوشه‌ی فایل‌های زیپ  (شامل فایل‌های   *.zip)",
            self.zips_var, self._browse_zips,
        )

        # --- workers row
        wf = ttk.Frame(self)
        wf.pack(fill="x", **pad)
        ttk.Label(wf, text="⚡  تعداد پردازش هم‌زمان (اختیاری):").pack(side="right")
        ttk.Spinbox(wf, from_=1, to=64, width=6,
                    textvariable=self.workers_var, justify="center").pack(side="right", padx=8)

        # Reprocess switch: when on, already-completed zips are regenerated from
        # scratch (use after the parser logic changes).
        ttk.Checkbutton(
            wf, variable=self.force_var,
            text="🔁  پردازش مجدد همه (نادیده‌گرفتن موارد تکمیل‌شده)",
        ).pack(side="right", padx=16)

        # --- log pane
        ttk.Label(self, text="📋  گزارش پردازش:").pack(anchor="e", padx=12)
        self.log = scrolledtext.ScrolledText(
            self, height=18, wrap="word", state="disabled",
            font=("Consolas", 10), background="#0c0c10", foreground="#f4f3ef",
            insertbackground="#ec2348",
        )
        self.log.pack(fill="both", expand=True, padx=12, pady=6)

        # --- bottom bar
        bar = ttk.Frame(self)
        bar.pack(fill="x", **pad)

        self.start_btn = ttk.Button(bar, text="▶  شروع پردازش", command=self._start)
        self.start_btn.pack(side="left")

        # Stop = pause: checkpoints the current car and stops; press Start to resume.
        self.stop_btn = ttk.Button(bar, text="⏸  توقف / مکث",
                                   command=self._stop, state="disabled")
        self.stop_btn.pack(side="left", padx=(8, 0))

        self.progress = ttk.Progressbar(bar, mode="indeterminate")
        self.progress.pack(side="left", fill="x", expand=True, padx=12)

        self.status = ttk.Label(bar, text="آماده", foreground="#92909e")
        self.status.pack(side="right")

    def _folder_row(self, label: str, var: tk.StringVar, cmd) -> None:
        ttk.Label(self, text=label).pack(anchor="e", padx=12, pady=(8, 0))
        row = ttk.Frame(self)
        row.pack(fill="x", padx=12, pady=(0, 2))
        ttk.Button(row, text="انتخاب…", command=cmd).pack(side="right", padx=(8, 0))
        ttk.Entry(row, textvariable=var).pack(side="right", fill="x", expand=True)

    # ----------------------------------------------------------------- browse
    def _browse_backend(self) -> None:
        d = filedialog.askdirectory(title="پوشه‌ی بک‌اند را انتخاب کنید",
                                    initialdir=self.backend_var.get() or os.getcwd())
        if d:
            self.backend_var.set(os.path.normpath(d))

    def _browse_zips(self) -> None:
        d = filedialog.askdirectory(title="پوشه‌ی فایل‌های زیپ را انتخاب کنید",
                                    initialdir=self.zips_var.get() or os.getcwd())
        if d:
            self.zips_var.set(os.path.normpath(d))

    # ----------------------------------------------------------------- logging
    def _append(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _drain_log(self) -> None:
        try:
            while True:
                msg = self.log_q.get_nowait()
                if msg == "<<DONE>>":
                    self._finish()
                else:
                    self._append(msg)
        except queue.Empty:
            pass
        self.after(100, self._drain_log)

    # ----------------------------------------------------------------- run
    def _validate(self) -> "tuple[str, str, int | None] | None":
        backend = self.backend_var.get().strip()
        zips = self.zips_var.get().strip()

        if not backend or not Path(backend).is_dir():
            messagebox.showerror("خطا", "لطفاً پوشه‌ی بک‌اند معتبر را انتخاب کنید.")
            return None
        if not (Path(backend) / "db.sqlite3").exists():
            messagebox.showerror(
                "خطا",
                "در پوشه‌ی بک‌اند فایل  db.sqlite3  پیدا نشد.\n"
                "مطمئن شوید پوشه‌ی درستی را انتخاب کرده‌اید.",
            )
            return None
        if not zips or not Path(zips).is_dir():
            messagebox.showerror("خطا", "لطفاً پوشه‌ی فایل‌های زیپ را انتخاب کنید.")
            return None

        found = list(Path(zips).glob("LEMON *.zip"))
        if not found:
            messagebox.showerror(
                "خطا",
                "در این پوشه هیچ فایلی با الگوی  «LEMON *.zip»  پیدا نشد.\n"
                "نام فایل‌های زیپ باید با  LEMON  شروع شود.",
            )
            return None

        workers_raw = self.workers_var.get().strip()
        workers = int(workers_raw) if workers_raw.isdigit() else None
        return backend, zips, workers

    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        v = self._validate()
        if not v:
            return
        backend, zips, workers = v

        save_config({"backend": backend, "zips": zips,
                     "workers": self.workers_var.get().strip()})

        # clear log
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

        self.cancel_event.clear()
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.progress.start(12)
        self.status.configure(text="در حال پردازش…", foreground="#e8ad3f")

        force = bool(self.force_var.get())
        self.worker = threading.Thread(
            target=self._run, args=(backend, zips, workers, force), daemon=True)
        self.worker.start()

    def _run(self, backend: str, zips: str, workers: "int | None",
             force: bool = False) -> None:
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = QueueWriter(self.log_q)
        try:
            parser.process_all_zips(backend, workers, zips,
                                    cancel_event=self.cancel_event,
                                    force=force)
        except SystemExit as e:
            # the script calls sys.exit() on some errors; surface, don't crash.
            print(f"\n⛔ پردازش متوقف شد (کد: {e.code}).")
        except Exception:
            print("\n❌ خطای غیرمنتظره:\n" + traceback.format_exc())
        finally:
            sys.stdout, sys.stderr = old_out, old_err
            self.log_q.put("<<DONE>>")

    def _stop(self) -> None:
        """Request a clean pause: the parser checkpoints the in-flight car and
        stops starting new ones. Press Start again to resume from the checkpoint."""
        if self.worker and self.worker.is_alive():
            self.cancel_event.set()
            self.stop_btn.configure(state="disabled")
            self.status.configure(text="در حال توقف ایمن…", foreground="#e8ad3f")
            self._append("\n⏸️  درخواست توقف ثبت شد؛ در حال ذخیره‌ی نقطه‌ی ادامه…\n")

    def _finish(self) -> None:
        self.progress.stop()
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        if self.cancel_event.is_set():
            self.status.configure(text="متوقف شد (قابل ادامه) ⏸",
                                  foreground="#e8ad3f")
        else:
            self.status.configure(text="پایان یافت ✓", foreground="#2bb3a3")

    # ----------------------------------------------------------------- close
    def _on_close(self) -> None:
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(
                "در حال پردازش",
                "پردازش هنوز تمام نشده است.\n"
                "با خروج، پردازش متوقف می‌شود اما پیشرفت ذخیره‌شده "
                "از دست نمی‌رود و دفعه‌ی بعد از همان‌جا ادامه می‌یابد.\n\n"
                "آیا می‌خواهید خارج شوید؟"):
                return
            # Ask the parser to checkpoint, then give it a brief moment to flush
            # the current frontier before the process (and its daemon thread) die.
            self.cancel_event.set()
            self._append("\n⏸️  در حال ذخیره‌ی نقطه‌ی ادامه پیش از خروج…\n")
            self.worker.join(timeout=10)
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
