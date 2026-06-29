#!/usr/bin/env python3
import os
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk


APP_TITLE = "Sensei Fishing"
WORKER_ARG = "--worker-scheduled-loop"


def script_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def resource_dir():
    return getattr(sys, "_MEIPASS", script_dir())


def resolve_python():
    configured = os.environ.get("SENSEI_PYTHON")
    if configured:
        return configured

    venv_python = os.path.join(script_dir(), ".venv", "Scripts", "python.exe")
    if os.path.exists(venv_python):
        return venv_python

    return sys.executable or "python"


def scheduled_command():
    root = script_dir()
    resources = resource_dir()
    if getattr(sys, "frozen", False):
        return [sys.executable, WORKER_ARG]

    return [
        resolve_python(),
        "-u",
        os.path.join(root, "sensei_click.py"),
        "--scheduled-auto-loop",
        "--start-delay",
        "4",
        "--schedule-config",
        os.path.join(resources, "auto_fishing_start.json"),
        "--start-wait-timeout",
        "90",
        "--start-poll-interval",
        "0.25",
        "--start-confirm-frames",
        "3",
        "--after-start-delay",
        "0.2",
        "--debug-dir",
        os.path.join(root, "debug_last"),
        "--no-start-button-debug-images",
        "--constellation-debug-images",
        "minimal-images",
    ]


def scheduled_worker_args():
    root = script_dir()
    resources = resource_dir()
    return [
        "--scheduled-auto-loop",
        "--start-delay",
        "4",
        "--schedule-config",
        os.path.join(resources, "auto_fishing_start.json"),
        "--start-wait-timeout",
        "90",
        "--start-poll-interval",
        "0.25",
        "--start-confirm-frames",
        "3",
        "--after-start-delay",
        "0.2",
        "--debug-dir",
        os.path.join(root, "debug_last"),
        "--no-start-button-debug-images",
        "--constellation-debug-images",
        "minimal-images",
        "--vertex-template",
        os.path.join(resources, "vertex_template.json"),
    ]


def run_worker():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    import sensei_click

    sys.argv = ["sensei_click.py", *scheduled_worker_args()]
    return sensei_click.main()


def worker_creation_flags():
    flags = 0
    flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return flags


def worker_env():
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


class SenseiGui(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("760x520")
        self.minsize(640, 420)

        self.process = None
        self.reader_thread = None
        self.output_queue = queue.Queue()
        self.stop_requested = False
        self.started_at = None
        self.current_loop = "-"
        self.completed_loops = 0
        self.skipped_loops = 0
        self.current_session = "-"
        self.last_message = "Ready"

        self.status_var = tk.StringVar(value="Stopped")
        self.session_var = tk.StringVar(value="-")
        self.loop_var = tk.StringVar(value="-")
        self.completed_var = tk.StringVar(value="0")
        self.skipped_var = tk.StringVar(value="0")
        self.runtime_var = tk.StringVar(value="00:00:00")
        self.last_message_var = tk.StringVar(value="Ready")

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(100, self.process_output_queue)
        self.after(1000, self.update_runtime)

    def _build_ui(self):
        outer = ttk.Frame(self, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)

        controls = ttk.Frame(outer)
        controls.pack(fill=tk.X)

        self.start_button = ttk.Button(controls, text="Start", command=self.start_worker)
        self.start_button.pack(side=tk.LEFT)
        self.stop_button = ttk.Button(controls, text="Stop", command=self.stop_worker, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=(8, 0))
        self.exit_button = ttk.Button(controls, text="Exit", command=self.on_close)
        self.exit_button.pack(side=tk.LEFT, padx=(8, 0))

        ttk.Label(controls, textvariable=self.status_var, font=("", 11, "bold")).pack(side=tk.LEFT, padx=(16, 0))

        stats = ttk.LabelFrame(outer, text="Status", padding=10)
        stats.pack(fill=tk.X, pady=(12, 8))
        stats.columnconfigure(1, weight=1)
        stats.columnconfigure(3, weight=1)

        self._stat(stats, 0, 0, "Session", self.session_var)
        self._stat(stats, 0, 2, "Loop", self.loop_var)
        self._stat(stats, 1, 0, "Completed", self.completed_var)
        self._stat(stats, 1, 2, "Skipped", self.skipped_var)
        self._stat(stats, 2, 0, "Runtime", self.runtime_var)
        self._stat(stats, 2, 2, "Last", self.last_message_var)

        log_frame = ttk.LabelFrame(outer, text="Log", padding=6)
        log_frame.pack(fill=tk.BOTH, expand=True)
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)

        self.log_text = tk.Text(log_frame, height=16, wrap=tk.WORD, state=tk.DISABLED)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)

    def _stat(self, parent, row, col, label, variable):
        ttk.Label(parent, text=label + ":").grid(row=row, column=col, sticky="w", padx=(0, 6), pady=3)
        ttk.Label(parent, textvariable=variable).grid(row=row, column=col + 1, sticky="w", pady=3)

    def set_running_state(self, running):
        if running:
            self.status_var.set("Running")
            self.start_button.configure(state=tk.DISABLED)
            self.stop_button.configure(state=tk.NORMAL)
        else:
            self.status_var.set("Stopped")
            self.start_button.configure(state=tk.NORMAL)
            self.stop_button.configure(state=tk.DISABLED)

    def start_worker(self):
        if self.process and self.process.poll() is None:
            return

        command = scheduled_command()
        self.reset_stats()
        self.append_log("> " + " ".join(f'"{part}"' if " " in part else part for part in command))
        try:
            self.process = subprocess.Popen(
                command,
                cwd=script_dir(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=worker_env(),
                creationflags=worker_creation_flags(),
            )
        except Exception as exc:
            self.process = None
            self.append_log(f"ERROR: failed to start worker: {exc}")
            messagebox.showerror(APP_TITLE, f"Failed to start worker:\n{exc}")
            return

        self.started_at = time.monotonic()
        self.stop_requested = False
        self.set_running_state(True)
        self.reader_thread = threading.Thread(target=self.read_worker_output, daemon=True)
        self.reader_thread.start()

    def stop_worker(self):
        if not self.process or self.process.poll() is not None:
            self.set_running_state(False)
            return
        self.stop_requested = True
        self.append_log("> Stop requested")
        self.status_var.set("Stopping")
        try:
            self.process.terminate()
        except Exception as exc:
            self.append_log(f"ERROR: terminate failed: {exc}")
            return
        self.after(2500, self.kill_if_still_running)

    def kill_if_still_running(self):
        if self.process and self.process.poll() is None:
            self.append_log("> Worker did not stop; killing")
            try:
                self.process.kill()
            except Exception as exc:
                self.append_log(f"ERROR: kill failed: {exc}")

    def read_worker_output(self):
        assert self.process is not None
        try:
            for line in self.process.stdout:
                self.output_queue.put(line.rstrip("\r\n"))
        finally:
            code = self.process.wait()
            self.output_queue.put(("__EXIT__", code))

    def process_output_queue(self):
        while True:
            try:
                item = self.output_queue.get_nowait()
            except queue.Empty:
                break
            if isinstance(item, tuple) and item[0] == "__EXIT__":
                if self.stop_requested:
                    self.append_log("> Stopped by user")
                else:
                    self.append_log(f"> Worker exited with code {item[1]}")
                self.set_running_state(False)
                self.process = None
                self.stop_requested = False
                continue
            self.handle_log_line(item)
        self.after(100, self.process_output_queue)

    def handle_log_line(self, line):
        self.append_log(line)
        text = line[7:] if line.startswith("debug: ") else line
        self.last_message = text
        self.last_message_var.set(text[-90:])

        session_match = re.search(r"session(\d{3})", text)
        if session_match:
            self.current_session = session_match.group(1)
            self.session_var.set(self.current_session)

        loop_match = re.search(r"loop(\d{3})", text)
        if loop_match:
            self.current_loop = loop_match.group(1)
            self.loop_var.set(self.current_loop)

        if re.search(r"loop\d{3}: complete", text):
            self.completed_loops += 1
            self.completed_var.set(str(self.completed_loops))
        elif "skipped_after_error=" in text or "skipped after error" in text:
            self.skipped_loops += 1
            self.skipped_var.set(str(self.skipped_loops))

    def append_log(self, line):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, line + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def reset_stats(self):
        self.current_loop = "-"
        self.completed_loops = 0
        self.skipped_loops = 0
        self.current_session = "-"
        self.last_message = "Starting"
        self.session_var.set("-")
        self.loop_var.set("-")
        self.completed_var.set("0")
        self.skipped_var.set("0")
        self.runtime_var.set("00:00:00")
        self.last_message_var.set("Starting")
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def update_runtime(self):
        if self.started_at and self.process and self.process.poll() is None:
            elapsed = int(time.monotonic() - self.started_at)
            h, rem = divmod(elapsed, 3600)
            m, s = divmod(rem, 60)
            self.runtime_var.set(f"{h:02d}:{m:02d}:{s:02d}")
        self.after(1000, self.update_runtime)

    def on_close(self):
        if self.process and self.process.poll() is None:
            if not messagebox.askyesno(APP_TITLE, "Worker is still running. Stop it and close?"):
                return
            self.stop_worker()
            self.after(400, self.destroy)
        else:
            self.destroy()


def main():
    if WORKER_ARG in sys.argv:
        raise SystemExit(run_worker())
    app = SenseiGui()
    app.mainloop()


if __name__ == "__main__":
    main()
