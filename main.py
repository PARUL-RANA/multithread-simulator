# gui_simulator_final_c.py
"""
Interactive Multithreading Simulator — VERSION C
- Monitor & Semaphore modes
- Neon avatars + buffer (slots change color only; no moving items)
- Improved log panel
- Thread state table
- Simple Gantt-style timeline (blocks)
- Safe GUI updates via queue
"""

import tkinter as tk
from tkinter import ttk, scrolledtext
import threading, time, random, queue, math

# -------------------------
# Helpers
# -------------------------
def rgb_to_hex(rgb):
    if isinstance(rgb, str):
        return rgb
    r, g, b = rgb
    return "#%02x%02x%02x" % (int(r), int(g), int(b))

# -------------------------
# Theme
# -------------------------
NEON = {
    "bg": "#0d1117",
    "panel": "#15181c",
    "slot_empty": "#1f2428",
    "slot_fill": "#238636",
    "text": "#c9d1d9",
    "muted": "#8b949e",
    "producer_neon": (0, 210, 255),
    "consumer_neon": (255, 70, 120),
    "badge_ok": (102, 187, 106),
    "badge_bad": (239, 83, 80),
    "warning": (255, 196, 0)
}

# -------------------------
# Synchronization Models
# -------------------------
class MonitorBuffer:
        """Bounded buffer implemented using monitor-style locking and conditions.

    Producers block when the buffer is full, and consumers block when it is empty.
    This models the classic Producer–Consumer problem using monitors (thread-safe).
    """
    def __init__(self, capacity):
        self.capacity = capacity
        self.q = []
        self.lock = threading.Lock()
        self.not_full = threading.Condition(self.lock)
        self.not_empty = threading.Condition(self.lock)

    def produce(self, item, stop_event):
        with self.lock:
            while len(self.q) == self.capacity:
                if stop_event.is_set(): return False
                self.not_full.wait(timeout=0.2)
            self.q.append(item)
            self.not_empty.notify()
            return True

    def consume(self, stop_event):
        with self.lock:
            while len(self.q) == 0:
                if stop_event.is_set(): return None
                self.not_empty.wait(timeout=0.2)
            item = self.q.pop(0)
            self.not_full.notify()
            return item

class SemaphoreBuffer:
    """Bounded buffer implemented using counting semaphores.

    Uses:
    - empty: counts free slots in the buffer
    - full:  counts filled slots in the buffer
    - mutex: gives mutual exclusion while accessing the queue

    This shows the Producer–Consumer solution using semaphores.
    """
    def __init__(self, capacity):
        self.capacity = capacity
        self.q = []
        self.empty = threading.Semaphore(capacity)
        self.full = threading.Semaphore(0)
        self.mutex = threading.Semaphore(1)

    def produce(self, item, stop_event):
        while not stop_event.is_set():
            if self.empty.acquire(timeout=0.2): break
        else:
            return False

        while not stop_event.is_set():
            if self.mutex.acquire(timeout=0.2): break
        else:
            try: self.empty.release()
            except: pass
            return False

        self.q.append(item)
        try: self.mutex.release()
        except: pass
        self.full.release()
        return True

    def consume(self, stop_event):
        while not stop_event.is_set():
            if self.full.acquire(timeout=0.2): break
        else:
            return None

        while not stop_event.is_set():
            if self.mutex.acquire(timeout=0.2): break
        else:
            try: self.full.release()
            except: pass
            return None

        item = None
        if len(self.q) != 0:
            item = self.q.pop(0)
        try: self.mutex.release()
        except: pass
        self.empty.release()
        return item

# -------------------------
# Main GUI App
# -------------------------
class FullSimulatorC:
    def __init__(self, root):
        self.root = root
        self.root.title("Multithreading Simulator — Mode C (Slots Only)")
        self.root.geometry("1240x720")
        self.root.configure(bg=NEON["bg"])

        # state
        self.capacity = 5
        self.running = False
        self.stop_event = threading.Event()
        self.gui_q = queue.Queue()

        # stats
        self.produced_count = 0
        self.consumed_count = 0
        self.peak_buffer = 0

        # timeline storage
        self.timeline_data = {}
        self.track_positions = {}

        # glow phases
        self.phase_p = 0.0
        self.phase_c = 2.0

        # build UI
        self.build_top_bar()
        self.build_canvas_area()
        self.build_right_panel()    # improved log panel
        self.build_timeline_area()

        # schedule loops
        self.root.after(40, self.pulse_loop)
        self.root.after(50, self.process_gui_queue)

    # -------------------------
    # TOP BAR
    # -------------------------
    def build_top_bar(self):
        top = tk.Frame(self.root, bg=NEON["panel"])
        top.place(x=10, y=10, width=1220, height=62)

        tk.Label(top, text="Mode:", bg=NEON["panel"], fg=NEON["text"]).place(x=8, y=16)
        self.mode_var = tk.StringVar(value="Monitor")
        self.mode_combo = ttk.Combobox(top, textvariable=self.mode_var, values=["Monitor", "Semaphore"], state="readonly", width=12)
        self.mode_combo.place(x=56, y=14)

        tk.Label(top, text="Producers:", bg=NEON["panel"], fg=NEON["text"]).place(x=190, y=16)
        self.p_count = tk.IntVar(value=2)
        ttk.Spinbox(top, from_=1, to=5, width=4, textvariable=self.p_count).place(x=260, y=14)

        tk.Label(top, text="Consumers:", bg=NEON["panel"], fg=NEON["text"]).place(x=320, y=16)
        self.c_count = tk.IntVar(value=2)
        ttk.Spinbox(top, from_=1, to=5, width=4, textvariable=self.c_count).place(x=400, y=14)

        self.start_btn = tk.Button(top, text="Start", bg="#1f6feb", fg="white", command=self.start)
        self.start_btn.place(x=480, y=10, width=58, height=36)
        self.stop_btn = tk.Button(top, text="Stop", bg="#c94c4c", fg="white", command=self.stop)
        self.stop_btn.place(x=545, y=10, width=58, height=36)
        self.reset_btn = tk.Button(top, text="Reset", bg="#777", fg="white", command=self.reset_all)
        self.reset_btn.place(x=610, y=10, width=58, height=36)

        tk.Label(top, text="Prod(ms):", bg=NEON["panel"], fg=NEON["text"]).place(x=700, y=16)
        self.prod_speed = tk.IntVar(value=300)
        ttk.Entry(top, width=6, textvariable=self.prod_speed).place(x=760, y=14)

        tk.Label(top, text="Cons(ms):", bg=NEON["panel"], fg=NEON["text"]).place(x=830, y=16)
        self.cons_speed = tk.IntVar(value=450)
        ttk.Entry(top, width=6, textvariable=self.cons_speed).place(x=890, y=14)

        self.status_badge = tk.Label(top, text="Status: Ready", bg=rgb_to_hex(NEON["badge_ok"]), fg="#000", padx=8, pady=4)
        self.status_badge.place(x=1010, y=12)

        self.done_badge = tk.Label(top, text="", bg="#2b2b2b", fg="white", padx=8)
        self.done_badge.place(x=1100, y=12)

        self.counts_label = tk.Label(top, text="Produced: 0  Consumed: 0  Peak: 0", bg=NEON["panel"], fg=NEON["text"])
        self.counts_label.place(x=950, y=40)

    # -------------------------
    # CANVAS / AVATARS / SLOTS
    # -------------------------
    def build_canvas_area(self):
        card = tk.Frame(self.root, bg=NEON["panel"])
        card.place(x=10, y=82, width=760, height=480)

        self.canvas = tk.Canvas(card, bg=NEON["bg"], highlightthickness=0)
        self.canvas.place(x=8, y=8, width=744, height=464)

        self.prod_pos = (120, 240)
        self.cons_pos = (620, 240)

        # glow + avatars
        self.p_glow = self.canvas.create_oval(self.prod_pos[0]-70, self.prod_pos[1]-70, self.prod_pos[0]+70, self.prod_pos[1]+70, fill="", outline="")
        self.p_avatar = self.canvas.create_oval(self.prod_pos[0]-36, self.prod_pos[1]-36, self.prod_pos[0]+36, self.prod_pos[1]+36, fill="#0d1117")
        self.p_icon = self.canvas.create_oval(self.prod_pos[0]-16, self.prod_pos[1]-16, self.prod_pos[0]+16, self.prod_pos[1]+16, fill=rgb_to_hex(NEON["producer_neon"]))

        self.c_glow = self.canvas.create_oval(self.cons_pos[0]-70, self.cons_pos[1]-70, self.cons_pos[0]+70, self.cons_pos[1]+70, fill="", outline="")
        self.c_avatar = self.canvas.create_oval(self.cons_pos[0]-36, self.cons_pos[1]-36, self.cons_pos[0]+36, self.cons_pos[1]+36, fill="#0d1117")
        self.c_icon = self.canvas.create_rectangle(self.cons_pos[0]-14, self.cons_pos[1]-12, self.cons_pos[0]+14, self.cons_pos[1]+12, fill=rgb_to_hex(NEON["consumer_neon"]))

        # labels
        self.canvas.create_text(self.prod_pos[0], self.prod_pos[1]+58, text="🏭  PRODUCER", fill=NEON["text"], font=("Segoe UI", 10, "bold"))
        self.canvas.create_text(self.cons_pos[0], self.cons_pos[1]+58, text="🧺  CONSUMER", fill=NEON["text"], font=("Segoe UI", 10, "bold"))

        # buffer slots (only color changes; no inner item)
        self.slot_rects = []
        bx = 240; by = 200; w = 68; h = 44; gap = 18
        for i in range(self.capacity):
            x1 = bx + i*(w+gap)
            rect = self.canvas.create_rectangle(x1, by, x1+w, by+h, fill=NEON["slot_empty"], outline="")
            left = self.canvas.create_oval(x1-8, by, x1+16, by+h, fill=NEON["slot_empty"], outline="")
            right = self.canvas.create_oval(x1+w-16, by, x1+w+8, by+h, fill=NEON["slot_empty"], outline="")
            self.slot_rects.append((rect, left, right))

    # -------------------------
    # Improved Log Panel (drop-in)
    # -------------------------
    def build_right_panel(self):
        panel = tk.Frame(self.root, bg=NEON["panel"])
        panel.place(x=780, y=82, width=450, height=480)

        # Title
        title = tk.Label(panel, text=" Activity Logs ", bg=NEON["panel"], fg="#ffffff", font=("Segoe UI", 13, "bold"))
        title.place(x=10, y=6)

        underline = tk.Frame(panel, bg=rgb_to_hex(NEON["producer_neon"]), height=2)
        underline.place(x=10, y=32, width=180)

        # Log area
        self.logbox = scrolledtext.ScrolledText(panel, width=52, height=18, bg="#0F1318", fg=NEON["text"], font=("Consolas", 10), insertbackground="white", bd=0, relief="flat")
        self.logbox.place(x=10, y=45)

        # tags for colors
        self.logbox.tag_config("P", foreground=rgb_to_hex(NEON["producer_neon"]), font=("Consolas", 10, "bold"))
        self.logbox.tag_config("C", foreground=rgb_to_hex(NEON["consumer_neon"]), font=("Consolas", 10, "bold"))
        self.logbox.tag_config("S", foreground="#9AA0A6", font=("Consolas", 10))
        self.logbox.tag_config("W", foreground=rgb_to_hex(NEON["warning"]), font=("Consolas", 10, "bold"))

        # section headers inside log
        self.logbox.insert(tk.END, "─── PRODUCER EVENTS ───\n", "P")
        self.logbox.insert(tk.END, "─── CONSUMER EVENTS ───\n", "C")
        self.logbox.insert(tk.END, "─── SYSTEM EVENTS ───\n", "S")

        # Thread states area
        tk.Label(panel, text="Thread States", bg=NEON["panel"], fg="#ffffff", font=("Segoe UI", 13, "bold")).place(x=10, y=355)
        underline2 = tk.Frame(panel, bg=rgb_to_hex(NEON["consumer_neon"]), height=2)
        underline2.place(x=10, y=378, width=200)

        self.thread_frame = tk.Frame(panel, bg=NEON["panel"])
        self.thread_frame.place(x=10, y=400)

    # -------------------------
    # Timeline area
    # -------------------------
    def build_timeline_area(self):
        area = tk.Frame(self.root, bg=NEON["panel"])
        area.place(x=10, y=570, width=1220, height=130)
        tk.Label(area, text="Timeline (colored = running | grey = waiting)", bg=NEON["panel"], fg=NEON["text"]).place(x=10, y=6)
        self.timeline_canvas = tk.Canvas(area, bg="#0b0f12", highlightthickness=0)
        self.timeline_canvas.place(x=10, y=30, width=1200, height=90)

    # -------------------------
    # Glow animations
    # -------------------------
    def pulse_loop(self):
        self.phase_p += 0.09
        self.phase_c += 0.07
        tp = (math.sin(self.phase_p)+1)/2
        tc = (math.sin(self.phase_c)+1)/2

        p_color = (int(NEON["producer_neon"][0]*(0.5+0.5*tp)),
                   int(NEON["producer_neon"][1]*(0.5+0.5*tp)),
                   int(NEON["producer_neon"][2]*(0.5+0.5*tp)))
        c_color = (int(NEON["consumer_neon"][0]*(0.5+0.5*tc)),
                   int(NEON["consumer_neon"][1]*(0.5+0.5*tc)),
                   int(NEON["consumer_neon"][2]*(0.5+0.5*tc)))

        try:
            self.canvas.itemconfig(self.p_glow, fill=rgb_to_hex(p_color))
            self.canvas.itemconfig(self.c_glow, fill=rgb_to_hex(c_color))
        except:
            pass

        # redraw timeline (simple)
        self.timeline_canvas.delete("ev")
        left = 80
        for name, events in self.timeline_data.items():
            y = self.track_positions.get(name, 6)
            evs = events[-40:]
            x = left
            for ev, ts in evs:
                if ev == "Running":
                    col = "#1ed760"
                elif ev == "Waiting":
                    col = "#f7d33e"
                elif ev == "Stopped":
                    col = "#9a9a9a"
                else:
                    col = "#444"
                self.timeline_canvas.create_rectangle(x, y, x+16, y+12, fill=col, outline='', tags="ev")
                x += 18

        self.root.after(40, self.pulse_loop)

    # -------------------------
    # Start / Stop / Reset
    # -------------------------
    def start(self):
        if self.running:
            return
        self.running = True
        self.stop_event.clear()
        self.clear_log()
        self.log("S", "Simulation started")

        mode = self.mode_var.get()
        self.buffer_model = MonitorBuffer(self.capacity) if mode == "Monitor" else SemaphoreBuffer(self.capacity)

        self.setup_thread_ui()

        self.threads = []
        for i in range(self.p_count.get()):
            t = threading.Thread(target=self.producer_worker, args=(i+1,), daemon=True)
            t.start(); self.threads.append(t)
        for j in range(self.c_count.get()):
            t = threading.Thread(target=self.consumer_worker, args=(j+1,), daemon=True)
            t.start(); self.threads.append(t)

        self.update_badge()

    def stop(self):
        if not self.running:
            return
        self.stop_event.set()
        self.running = False
        self.log("S", "Stopping simulation...")
        self.check_finished()

    def reset_all(self):
        self.stop_event.set()
        time.sleep(0.05)
        self.clear_log()
        self.clear_visuals()
        self.status_badge.configure(text="Status: Ready", bg=rgb_to_hex(NEON["badge_ok"]))
        self.done_badge.configure(text="")
        self.produced_count = 0
        self.consumed_count = 0
        self.peak_buffer = 0
        self.update_counts()

    # -------------------------
    # Producer / Consumer Workers
    # -------------------------
    def producer_worker(self, pid):
        name = f"P{pid}"
        self.thread_state_change(name, "Running")
        item_id = 1
        while not self.stop_event.is_set():
            time.sleep(self.prod_speed.get()/1000.0 + random.uniform(0,0.25))
            label = f"{name}-{item_id}"

            self.gui_q.put(("log", "P", f"{name} trying to produce {label}"))
            self.thread_state_change(name, "Waiting")

            ok = self.buffer_model.produce(label, self.stop_event)
            if not ok:
                break

            self.produced_count += 1
            self.peak_buffer = max(self.peak_buffer, len(self.buffer_model.q))
            self.update_counts()

            # Instead of moving items, just update slot fills
            self.gui_q.put(("log", "P", f"{name} produced {label}"))
            self.gui_q.put(("slot_update", len(self.buffer_model.q)))
            self.thread_state_change(name, "Running")
            item_id += 1

        self.thread_state_change(name, "Stopped")
        self.gui_q.put(("log", "S", f"{name} stopped"))
        self.check_finished()

    def consumer_worker(self, cid):
        name = f"C{cid}"
        self.thread_state_change(name, "Running")
        while not self.stop_event.is_set():
            time.sleep(self.cons_speed.get()/1000.0 + random.uniform(0,0.45))
            self.gui_q.put(("log", "C", f"{name} trying to consume"))
            self.thread_state_change(name, "Waiting")

            item = self.buffer_model.consume(self.stop_event)
            if item is None:
                break

            self.consumed_count += 1
            self.update_counts()

            # update slots only
            self.gui_q.put(("log", "C", f"{name} consumed {item}"))
            self.gui_q.put(("slot_update", len(self.buffer_model.q)))
            self.thread_state_change(name, "Running")

        self.thread_state_change(name, "Stopped")
        self.gui_q.put(("log", "S", f"{name} stopped"))
        self.check_finished()

    # -------------------------
    # GUI queue processing
    # -------------------------
    def process_gui_queue(self):
        processed = 0
        while not self.gui_q.empty() and processed < 200:
            try:
                task = self.gui_q.get_nowait()
            except queue.Empty:
                break
            processed += 1
            cmd = task[0]
            if cmd == "log":
                _, tag, msg = task
                self.log(tag, msg)
            elif cmd == "slot_update":
                _, n = task
                self.update_slots(n)
                self.update_badge()
            elif cmd == "set_thread":
                _, name, state = task
                self.update_thread_label(name, state)
        self.root.after(40, self.process_gui_queue)

    # -------------------------
    # Logging
    # -------------------------
def log(self, tag, msg):
    # Shorter time + visible icon for each log type
    ts = time.strftime("%H:%M:%S")
    icon = {"P": "🟦", "C": "🟥", "S": "ℹ️", "W": "⚠️"}.get(tag, "•")
    full_msg = f"{icon} [{ts}] {msg}"

        try:
            self.logbox.insert(tk.END, f"{full_msg}\n", tag)
            
            self.logbox.see(tk.END)
        except:
            self.logbox.insert(tk.END, f"{full_msg}\n")
            self.logbox.see(tk.END)

    def clear_log(self):
        try:
            self.logbox.delete("1.0", tk.END)
            # re-insert headers
            self.logbox.insert(tk.END, "─── PRODUCER EVENTS ───\n", "P")
            self.logbox.insert(tk.END, "─── CONSUMER EVENTS ───\n", "C")
            self.logbox.insert(tk.END, "─── SYSTEM EVENTS ───\n", "S")
        except:
            pass

    # -------------------------
    # Slot updates (ONLY color changes)
    # -------------------------
    def update_slots(self, n):
        for i in range(self.capacity):
            rect, l, r = self.slot_rects[i]
            if i < n:
                color = NEON["slot_fill"]
            else:
                color = NEON["slot_empty"]
            try:
                self.canvas.itemconfig(rect, fill=color)
                self.canvas.itemconfig(l, fill=color)
                self.canvas.itemconfig(r, fill=color)
            except:
                pass

    # -------------------------
    # Thread UI & timeline
    # -------------------------
    def setup_thread_ui(self):
        for child in self.thread_frame.winfo_children():
            child.destroy()
        self.thread_labels = {}
        self.thread_states = {}

        self.timeline_canvas.delete("all")
        self.timeline_data.clear()
        self.track_positions.clear()

        y = 6
        spacing = 18
        for i in range(self.p_count.get()):
            name = f"P{i+1}"
            lbl = tk.Label(self.thread_frame, text=f"{name}: Ready", bg=NEON["panel"], fg=NEON["muted"], anchor="w")
            lbl.pack(fill="x")
            self.thread_labels[name] = lbl
            self.thread_states[name] = "Ready"
            self.timeline_canvas.create_text(10, y+6, text=name, fill=NEON["text"])
            self.track_positions[name] = y
            self.timeline_data[name] = []
            y += spacing

        for j in range(self.c_count.get()):
            name = f"C{j+1}"
            lbl = tk.Label(self.thread_frame, text=f"{name}: Ready", bg=NEON["panel"], fg=NEON["muted"], anchor="w")
            lbl.pack(fill="x")
            self.thread_labels[name] = lbl
            self.thread_states[name] = "Ready"
            self.timeline_canvas.create_text(10, y+6, text=name, fill=NEON["text"])
            self.track_positions[name] = y
            self.timeline_data[name] = []
            y += spacing

    def thread_state_change(self, name, state):
        self.thread_states[name] = state
        # record timeline event
        now = time.time()
        self.timeline_data.setdefault(name, []).append((state, now))
        self.gui_q.put(("set_thread", name, state))

    def update_thread_label(self, name, state):
        lbl = self.thread_labels.get(name)
        if not lbl:
            return
        color_map = {"Running":"#1ed760", "Waiting":"#f7d33e", "Stopped":"#9a9a9a"}
        try:
            lbl.configure(text=f"{name}: {state}", fg=color_map.get(state, NEON["muted"]))
        except:
            pass

    # -------------------------
    # Badge / Counters / Finished
    # -------------------------
    def update_counts(self):
        try:
            self.counts_label.configure(text=f"Produced: {self.produced_count}  Consumed: {self.consumed_count}  Peak: {self.peak_buffer}")
        except:
            pass

    def update_badge(self):
        if not hasattr(self, "buffer_model"):
            status = "Ready"; color = NEON["badge_ok"]
        else:
            n = len(self.buffer_model.q)
            if n == 0:
                status = "Empty"; color = NEON["badge_ok"]
            elif n == self.buffer_model.capacity:
                status = "Full"; color = NEON["badge_bad"]
            else:
                status = "Available"; color = NEON["badge_ok"]
        try:
            self.status_badge.configure(text=f"Status: {status}", bg=rgb_to_hex(color))
        except:
            pass
        self.update_counts()

    def check_finished(self):
        if not hasattr(self, "thread_states"):
            return
        all_stopped = all(s == "Stopped" for s in self.thread_states.values())
        buffer_empty = (len(self.buffer_model.q) == 0) if hasattr(self, "buffer_model") else True
        if all_stopped and buffer_empty:
            self.done_badge.configure(text="✔ Simulation Finished")
            self.log("S", "Simulation finished")
        else:
            self.done_badge.configure(text="")

    # -------------------------
    # Clear visuals
    # -------------------------
    def clear_visuals(self):
        for i in range(self.capacity):
            rect, l, r = self.slot_rects[i]
            try:
                self.canvas.itemconfig(rect, fill=NEON["slot_empty"])
                self.canvas.itemconfig(l, fill=NEON["slot_empty"])
                self.canvas.itemconfig(r, fill=NEON["slot_empty"])
            except:
                pass
        self.timeline_canvas.delete("all")
        self.timeline_data.clear()

# -------------------------
# Run
# -------------------------
if __name__ == "__main__":
    root = tk.Tk()
    app = FullSimulatorC(root)
    root.mainloop()
