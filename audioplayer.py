import os
import tkinter as tk
from tkinter import filedialog
import pygame
import threading
import time
from mutagen.mp3 import MP3
import configparser
import keyboard


class HoverTooltip:
    def __init__(self, widget, text, delay=500):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.tipwindow = None
        self.id = None
        self.ignored_indices = set()
        self.widget.bind("<Enter>", self.enter)
        self.widget.bind("<Leave>", self.leave)

    def enter(self, event=None):
        self.schedule()

    def leave(self, event=None):
        self.unschedule()
        self.hidetip()

    def schedule(self):
        self.unschedule()
        self.id = self.widget.after(self.delay, self.showtip)

    def unschedule(self):
        if self.id:
            self.widget.after_cancel(self.id)
            self.id = None

    def showtip(self):
        if self.tipwindow:
            return
        x, y, cx, cy = (0, 0, 0, 0)
        if hasattr(self.widget, "bbox") and self.widget.bbox("insert"):
            x, y, cx, cy = self.widget.bbox("insert")
        x = x + self.widget.winfo_rootx() + 25
        y = y + self.widget.winfo_rooty() + 20
        self.tipwindow = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(tw, text=self.text, justify="left",
                         background="#ffffe0", relief="solid", borderwidth=1,
                         font=("Arial", 9))
        label.pack(ipadx=4, ipady=2)

    def hidetip(self):
        if self.tipwindow:
            self.tipwindow.destroy()
            self.tipwindow = None


class TooltipMP3Player:
    CONFIG_FILE = "player_config.ini"

    def __init__(self, root):
        self.root = root
        self.root.title("Minimalist Audio Player")
        self.root.geometry("940x780")
        self.root.resizable(False, False)

        pygame.mixer.init()

        self.files = []
        self.filtered_indices = []
        self.current_index = None
        self.playing = False
        self.paused = False
        self.song_length = 0
        self.start_time = 0
        self.pause_start = 0
        self.paused_time_accum = 0
        self.updating_slider = False
        self.changing_track = False
        self.current_song_tooltip = "Double-click a song to play"
        self.queue = []


        self.config = configparser.ConfigParser()
        self.load_config()

        self.tooltip_label = tk.Label(root, text=self.current_song_tooltip,
                                      fg="white", bg="gray", font=("Arial", 10))
        self.tooltip_label.pack(fill="x", pady=2)

        select_folder_btn = tk.Button(root, text="Select Folder", command=self.select_folder)
        select_folder_btn.pack(pady=8)
        HoverTooltip(select_folder_btn, "Select a folder containing audio files")

        search_frame = tk.Frame(root)
        search_frame.pack(fill="x", padx=10, pady=5)
        tk.Label(search_frame, text="Search:").pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self.update_search)
        search_entry = tk.Entry(search_frame, textvariable=self.search_var)
        search_entry.pack(side="left", fill="x", expand=True, padx=5)
        HoverTooltip(search_entry, "Type to search/filter songs")

        self.listbox = tk.Listbox(root)
        self.listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.listbox.bind("<Double-1>", self.on_double_click)
        self.listbox.bind("<Button-3>", self.show_context_menu)

        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="Add to Queue", command=self.add_to_queue)
        self.menu.add_command(label="Play Next", command=self.add_to_front_of_queue)

        self.time_label = tk.Label(root, 
            padx=10, pady=15,
            text="00:00 / 00:00")
        self.time_label.pack()

        self.position = tk.DoubleVar()
        self.hotkeys_enabled = tk.BooleanVar(value=True)

        self.hotkey_stop_event = threading.Event()
        self.hotkey_thread = None


        """
        progress slider

        """
        #self.slider = tk.Scale(root, from_=0, to=100, orient="horizontal",
        #                       variable=self.position, command=self.seek, length=380,
        #                       label="Slider")
        #self.slider.pack(pady=5)

        controls = tk.Frame(root)
        controls.pack()
        prev_btn = tk.Button(controls, text="⏮ Previous", command=self.previous_track)
        prev_btn.grid(row=0, column=0, padx=5)
        HoverTooltip(prev_btn, "Play previous track")
        play_btn = tk.Button(controls, text="Play", command=self.play_selected)
        play_btn.grid(row=0, column=1, padx=5)
        HoverTooltip(play_btn, "Play selected song")
        pause_btn = tk.Button(controls, text="Pause/Resume", command=self.pause_resume)
        pause_btn.grid(row=0, column=2, padx=5)
        HoverTooltip(pause_btn, "Pause or resume")
        stop_btn = tk.Button(controls, text="Stop", command=self.stop)
        stop_btn.grid(row=0, column=3, padx=5)
        HoverTooltip(stop_btn, "Stop playback")
        next_btn = tk.Button(controls, text="Next ⏭", command=self.next_track)
        next_btn.grid(row=0, column=4, padx=5)
        HoverTooltip(next_btn, "Play next track")

        queue_controls = tk.Frame(root)
        queue_controls.pack(pady=10)
        add_queue_btn = tk.Button(queue_controls, text="+ Add to Queue", command=self.add_to_queue)
        add_queue_btn.pack()
        HoverTooltip(add_queue_btn, "Add selected song to queue")

        hotkey_checkbox = tk.Checkbutton(
            root,
            text="Enable Global Hotkeys",
            variable=self.hotkeys_enabled,
            command=self.toggle_hotkeys
            )
        hotkey_checkbox.pack(pady=5)


        self.status_label = tk.Label(
            root,
            text="Ctrl + Alt + Left/Right/Up (arrow) for hotkeys",
            font=("Arial", 9, "bold"),
            fg="white",
            bg="darkblue",
            relief="sunken",
            bd=3,
            padx=3, pady=3
        )
        self.status_label.pack(pady=2)

        default_volume = float(self.config.get("Settings", "volume", fallback="0.8"))
        self.volume = tk.DoubleVar(value=default_volume)
        volume_slider = tk.Scale(root, from_=0, to=1, orient="horizontal",
                                 resolution=0.01, label="Volume",
                                 variable=self.volume, command=self.set_volume)
        volume_slider.pack(fill="x", padx=20, pady=10)

        queue_frame = tk.LabelFrame(root, text="Queue (?)", padx=5, pady=5)
        queue_frame.pack(fill="both", padx=10, pady=5)
        HoverTooltip(queue_frame, "Drag items in the queue to reorder them / right click for context menu")

        self.queue_listbox = tk.Listbox(queue_frame, height=6)
        self.queue_listbox.pack(side="left", fill="both", expand=True)

        queue_scroll = tk.Scrollbar(queue_frame, command=self.queue_listbox.yview)
        queue_scroll.pack(side="right", fill="y")
        self.queue_listbox.config(yscrollcommand=queue_scroll.set)
        self.queue_listbox.bind("<Button-3>", self.show_context_menu)

        clear_queue_btn = tk.Button(root, text="Clear Queue", command=self.clear_queue)
        clear_queue_btn.pack(pady=5)
        HoverTooltip(clear_queue_btn, "Remove all items from queue")

        self.update_thread = threading.Thread(target=self.update_slider_loop, daemon=True)
        self.update_thread.start()

        pygame.mixer.music.set_volume(self.volume.get())
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        threading.Thread(target=self.setup_global_hotkeys, daemon=True).start()

    def toggle_hotkeys(self):
        if self.hotkeys_enabled.get():
            if not self.hotkey_thread or not self.hotkey_thread.is_alive():
                self.hotkey_stop_event.clear()
                self.hotkey_thread = threading.Thread(target=self.setup_global_hotkeys, daemon=True)
                self.hotkey_thread.start()
                print("Hotkeys enabled")
        else:
            try:
                self.hotkey_stop_event.set()
                keyboard.unhook_all_hotkeys()
                print("Hotkeys disabled")
            except Exception as e:
                print(f"Failed to unhook hotkeys: {e}")


    def setup_global_hotkeys(self):
        try:
            keyboard.add_hotkey("ctrl+alt+left", self.previous_track)
            keyboard.add_hotkey("ctrl+alt+right", self.next_track)
            keyboard.add_hotkey("ctrl+alt+up", self.pause_resume)
        except Exception as e:
            print(f"Global hotkeys not available: {e}")

        if self.Last_folder and os.path.exists(self.Last_folder):
            self.load_folder(self.Last_folder)

        self.dragging_item = None
        self.drag_current_target = None
        self.drag_window = None
        self.drag_label = None
        self.drag_offset_x = 10
        self.drag_offset_y = 10
        self.queue_listbox.bind("<ButtonPress-1>", self.on_drag_start)
        self.queue_listbox.bind("<B1-Motion>", self.on_drag_motion)
        self.queue_listbox.bind("<ButtonRelease-1>", self.on_drag_end)


    def load_config(self):
        if os.path.exists(self.CONFIG_FILE):
            self.config.read(self.CONFIG_FILE)
        else:
            self.config["Settings"] = {"volume": "0.8"}
        self.Last_folder = self.config.get("Settings", "Last_folder", fallback="")

    def save_config(self):
        if "Settings" not in self.config:
            self.config["Settings"] = {}
        self.config["Settings"]["volume"] = str(self.volume.get())
        if hasattr(self, "Last_folder") and self.Last_folder:
            self.config["Settings"]["Last_folder"] = self.Last_folder
        with open(self.CONFIG_FILE, "w") as f:
            self.config.write(f)

    def on_close(self):
        self.save_config()
        self.root.destroy()

    def load_folder(self, folder):
        self.listbox.delete(0, tk.END)
        self.files = []

        for f in sorted(os.listdir(folder)):
            if f.lower().endswith((".mp3", ".wav", ".ogg", ".flac")):
                file_path = os.path.join(folder, f)
                try:
                    if f.lower().endswith(".mp3"):
                        audio = MP3(file_path)
                        length = audio.info.length
                    else:
                        sound = pygame.mixer.Sound(file_path)
                        length = sound.get_length()
                        del sound
                except Exception as e:
                    self.show_tooltip(f"Error loading {f}: {str(e)}", 5)
                    continue

                self.files.append((file_path, length))
                #self.listbox.insert(tk.END, f)
                self.listbox.insert(tk.END, os.path.splitext(f)[0].replace("_", " "))

        self.filtered_indices = list(range(len(self.files)))
        if self.files:
            self.show_tooltip(f"Loaded {len(self.files)} track(s)", 3)

    def select_folder(self):
        folder = filedialog.askdirectory()
        if not folder:
            return
        self.Last_folder = folder
        self.load_folder(folder)

    def play_file(self, index):
        if not self.files or index >= len(self.files):
            return

        file_path, length = self.files[index]
        try:
            pygame.mixer.music.load(file_path)
            pygame.mixer.music.play()

            self.current_index = index
            self.song_length = length
            self.playing = True
            self.paused = False
            self.paused_time_accum = 0
            self.start_time = time.time()

            self.listbox.select_clear(0, tk.END)
            if index in self.filtered_indices:
                filtered_idx = self.filtered_indices.index(index)
                self.listbox.select_set(filtered_idx)

            self.current_song_tooltip = f"Now playing: {os.path.splitext(os.path.basename(file_path))[0].replace("_", " ")}"
            self.update_top_message(self.current_song_tooltip, permanent=True)

        except Exception as e:
            self.show_tooltip(f"Playback error: {e}", permanent=True)

    def play_selected(self):
        sel = self.listbox.curselection()
        if not sel:
            self.show_tooltip("Select a song first", 2)
            return
        filtered_idx = sel[0]
        actual_idx = self.filtered_indices[filtered_idx]
        self.play_file(actual_idx)

    def pause_resume(self):
        if not self.playing:
            return
        if not self.paused:
            pygame.mixer.music.pause()
            self.paused = True
            self.pause_start = time.time()
            self.update_top_message("Paused", permanent=True)
        else:
            pygame.mixer.music.unpause()
            self.paused = False
            self.paused_time_accum += time.time() - self.pause_start
            self.update_top_message(f"Now playing: {os.path.splitext(os.path.basename(self.files[self.current_index][0]))[0].replace("_", " ")}", permanent=True)

    def stop(self):
        pygame.mixer.music.stop()
        self.playing = False
        self.paused = False
        self.position.set(0)
        self.time_label.config(text="00:00 / 00:00")
        self.update_top_message("Double-click a song to play", permanent=False)
        self.show_tooltip("Select a song to play")

    def refresh_queue_display(self):
        self.queue_listbox.delete(0, tk.END)
        for i in self.queue:
            try:
                name = os.path.basename(self.files[i][0])
                self.queue_listbox.insert(tk.END, name)
            except:
                self.queue_listbox.insert(tk.END, "<Invalid>")

    def clear_queue(self):
        self.queue.clear()
        self.refresh_queue_display()
        self.show_tooltip("Queue cleared", 2)

    def show_context_menu(self, event):
        widget = event.widget
        try:
            if widget == self.listbox:
                idx = self.listbox.nearest(event.y)
                if idx != -1:
                    self.listbox.selection_clear(0, tk.END)
                    self.listbox.selection_set(idx)
            elif widget == self.queue_listbox:
                idx = self.queue_listbox.nearest(event.y)
                if idx != -1:
                    self.queue_listbox.selection_clear(0, tk.END)
                    self.queue_listbox.selection_set(idx)
            self.menu.post(event.x_root, event.y_root)
        except Exception:
            pass

    def add_to_queue(self):
        sel = self.listbox.curselection()
        if sel:
            actual_idx = self.filtered_indices[sel[0]]
            self.queue.append(actual_idx)
            self.refresh_queue_display()
            self.show_tooltip("Added to queue", 2)
        else:
            self.show_tooltip("No song selected", 2)

    def add_to_front_of_queue(self):
        sel = self.listbox.curselection()
        if sel:
            actual_idx = self.filtered_indices[sel[0]]
            self.queue.insert(0, actual_idx)
            self.refresh_queue_display()
            self.show_tooltip("Added to front of queue (next)", 2)
        else:
            self.show_tooltip("No song selected", 2)

    def on_drag_start(self, event):
        idx = self.queue_listbox.nearest(event.y)
        if idx == -1 or idx >= len(self.queue):
            self.dragging_item = None
            return
        self.dragging_item = idx
        self.drag_current_target = idx
        self.queue_listbox.selection_clear(0, tk.END)
        self.queue_listbox.selection_set(idx)
        text = self.queue_listbox.get(idx)
        self.drag_window = tw = tk.Toplevel(self.root)
        tw.wm_overrideredirect(True)
        tw.attributes("-topmost", True)
        try:
            tw.attributes("-alpha", 0.90)
        except:
            pass
        label = tk.Label(tw, text=text, relief="raised", bd=1,
                         font=("Arial", 10), padx=6, pady=2)
        label.pack()
        self.drag_label = label
        self._move_drag_window(event.x_root, event.y_root)

    def _move_drag_window(self, root_x, root_y):
        if self.drag_window:
            x = root_x + self.drag_offset_x
            y = root_y + self.drag_offset_y
            self.drag_window.wm_geometry(f"+{x}+{y}")

    def on_drag_motion(self, event):
        if not self.drag_window or self.dragging_item is None:
            return
        self._move_drag_window(event.x_root, event.y_root)
        try:
            target = self.queue_listbox.nearest(event.y)
        except Exception:
            target = None
        if target is None:
            return
        if target < 0:
            target = 0
        if target >= self.queue_listbox.size():
            target = self.queue_listbox.size() - 1
        if target != self.drag_current_target:
            try:
                self.queue_listbox.selection_clear(0, tk.END)
            except:
                pass
            self.queue_listbox.selection_set(target)
            self.drag_current_target = target

    def on_drag_end(self, event):
        if self.drag_window:
            try:
                self.drag_window.destroy()
            except:
                pass
            self.drag_window = None
            self.drag_label = None
        if self.dragging_item is None:
            self.drag_current_target = None
            return
        try:
            target = self.queue_listbox.nearest(event.y)
        except Exception:
            target = self.dragging_item
        if target < 0:
            target = 0
        if target >= len(self.queue):
            target = len(self.queue) - 1
        orig = self.dragging_item
        dest = target
        if orig != dest and 0 <= orig < len(self.queue) and 0 <= dest < len(self.queue):
            item = self.queue.pop(orig)
            self.queue.insert(dest, item)
            self.refresh_queue_display()
            self.queue_listbox.selection_clear(0, tk.END)
            self.queue_listbox.selection_set(dest)
            self.show_tooltip("Item moved", 1)
        else:
            self.queue_listbox.selection_clear(0, tk.END)
            if 0 <= orig < self.queue_listbox.size():
                self.queue_listbox.selection_set(orig)
        self.dragging_item = None
        self.drag_current_target = None

    def next_track(self):
        if self.queue:
            next_index = self.queue.pop(0)
            self.refresh_queue_display()
        elif self.current_index is not None:
            next_index = (self.current_index + 1) % len(self.files)
        else:
            return
        self.play_file(next_index)

    def previous_track(self):
        if self.current_index is None:
            return
        prev_index = (self.current_index - 1) % len(self.files)
        self.play_file(prev_index)

    def set_volume(self, _=None):
        pygame.mixer.music.set_volume(self.volume.get())
        self.save_config()

    def seek(self, val):
        if not self.playing or self.song_length <= 0:
            return
        pos = (float(val) / 100) * self.song_length
        self.play_file_at_position(pos)

    def play_file_at_position(self, pos):
        file_path, _ = self.files[self.current_index]
        pygame.mixer.music.stop()
        pygame.mixer.music.load(file_path)
        pygame.mixer.music.play()
        try:
            pygame.mixer.music.set_pos(pos)
        except Exception:
            pass
        self.start_time = time.time() - pos
        self.paused_time_accum = 0
        self.paused = False
        self.playing = True

    def update_slider_loop(self):
        while True:
            if self.playing and not self.paused:
                current = time.time() - self.start_time - self.paused_time_accum
                if current >= self.song_length:
                    self.next_track()
                if self.song_length > 0:
                    self.position.set((current / self.song_length) * 100)
                    self.update_time_label(current)
            time.sleep(0.2)

    def on_double_click(self, event):
        sel = self.listbox.curselection()
        if sel:
            filtered_idx = sel[0]
            actual_idx = self.filtered_indices[filtered_idx]
            self.play_file(actual_idx)

    def update_time_label(self, current):
        total = self.song_length
        self.time_label.config(
            text=f"{self.format_time(current)} / {self.format_time(total)}"
        )

    @staticmethod
    def format_time(seconds):
        seconds = int(seconds)
        minutes = seconds // 60
        seconds = seconds % 60
        return f"{minutes:02}:{seconds:02}"

    def show_tooltip(self, text, duration=2, permanent=False):
        self.status_label.config(text=text)
        if permanent:
            return
        if duration:
            def clear():
                time.sleep(duration)
                try:
                    self.status_label.after(0, lambda: self.status_label.config(
                        text="Ctrl + Alt + Left/Right/Up (arrow) for hotkeys"))
                except:
                    pass
            threading.Thread(target=clear, daemon=True).start()

    def update_top_message(self, text, permanent=False, duration=2):
        self.tooltip_label.config(text=text)
        if permanent:
            return
        if duration:
            def clear():
                time.sleep(duration)
                try:
                    self.tooltip_label.after(0, lambda: self.tooltip_label.config(
                        text="Double-click a song to play"))
                except:
                    pass
            threading.Thread(target=clear, daemon=True).start()

    def update_search(self, *args):
        query = self.search_var.get().lower()
        self.listbox.delete(0, tk.END)
        self.filtered_indices = []
        for idx, (file_path, length) in enumerate(self.files):
            filename = os.path.splitext(os.path.basename(file_path))[0].replace("_", " ")
            if query in filename.lower():
                self.listbox.insert(tk.END, filename)
                self.filtered_indices.append(idx)


if __name__ == "__main__":
    root = tk.Tk()
    try:
        root.iconbitmap("resources/music.ico")
    except Exception:
        pass
    app = TooltipMP3Player(root)
    root.mainloop()
