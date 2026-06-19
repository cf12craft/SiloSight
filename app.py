#!/usr/bin/env python3
import os
os.environ["KMP_AFFINITY"] = "disabled"
import sys
import glob
import logging

# Configure logging
log_path = os.path.join(os.getcwd(), "silosite_debug.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_path, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logging.info("SiloSight application starting...")
import time
import sqlite3
import re
import threading
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk
from PIL import Image, ImageTk, ImageOps

# Set CustomTkinter appearance
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

# ==========================================
# 1. Database Manager
# ==========================================
class DBManager:
    def __init__(self, db_path="local_gallery.db"):
        self.db_path = db_path
        self.init_db()

    def get_conn(self):
        return sqlite3.connect(self.db_path)

    def init_db(self):
        with self.get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS gallery (
                    path TEXT PRIMARY KEY,
                    ai_tags TEXT,
                    user_tags TEXT,
                    is_favorite INTEGER DEFAULT 0,
                    timestamp REAL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tracked_directories (
                    path TEXT PRIMARY KEY
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            conn.commit()

    def save_setting(self, key, value):
        with self.get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, str(value))
            )
            conn.commit()

    def get_setting(self, key, default=None):
        with self.get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row[0] if row else default

    def add_tracked_directory(self, path):
        with self.get_conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO tracked_directories (path) VALUES (?)",
                (path,)
            )
            conn.commit()

    def remove_tracked_directory(self, path):
        with self.get_conn() as conn:
            conn.execute(
                "DELETE FROM tracked_directories WHERE path = ?",
                (path,)
            )
            conn.commit()

    def clear_tracked_directories(self):
        with self.get_conn() as conn:
            conn.execute("DELETE FROM tracked_directories")
            conn.commit()

    def get_tracked_directories(self):
        with self.get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT path FROM tracked_directories")
            return [row[0] for row in cursor.fetchall()]

    def is_image_indexed(self, path):
        with self.get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM gallery WHERE path = ?", (path,))
            return cursor.fetchone() is not None

    def add_image(self, path, ai_tags, user_tags="", is_favorite=0, timestamp=None):
        if timestamp is None:
            timestamp = time.time()
        with self.get_conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO gallery (path, ai_tags, user_tags, is_favorite, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                (path, ai_tags, user_tags, is_favorite, timestamp)
            )
            conn.commit()

    def update_user_tags(self, path, user_tags):
        with self.get_conn() as conn:
            conn.execute(
                "UPDATE gallery SET user_tags = ? WHERE path = ?",
                (user_tags, path)
            )
            conn.commit()

    def update_favorite(self, path, is_favorite):
        with self.get_conn() as conn:
            conn.execute(
                "UPDATE gallery SET is_favorite = ? WHERE path = ?",
                (int(is_favorite), path)
            )
            conn.commit()

    def get_all_images(self):
        with self.get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM gallery")
            return cursor.fetchall()

    def get_image(self, path):
        with self.get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM gallery WHERE path = ?", (path,))
            return cursor.fetchone()

    def delete_image(self, path):
        with self.get_conn() as conn:
            conn.execute("DELETE FROM gallery WHERE path = ?", (path,))
            conn.commit()

    def search_gallery(self, query_str, show_favorites_only=False, sort_by="newest"):
        # Split terms by spaces and commas, ignoring empty terms
        terms = [t.strip().lower() for t in re.split(r'[,\s]+', query_str) if t.strip()]
        
        sql = "SELECT path, ai_tags, user_tags, is_favorite, timestamp FROM gallery"
        conditions = []
        params = []
        
        if show_favorites_only:
            conditions.append("is_favorite = 1")
            
        for term in terms:
            # SQLite LIKE is case-insensitive for ASCII. Match term in ai_tags OR user_tags
            conditions.append("(LOWER(ai_tags) LIKE ? OR LOWER(user_tags) LIKE ?)")
            params.extend([f"%{term}%", f"%{term}%"])
            
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
            
        if sort_by == "newest":
            sql += " ORDER BY timestamp DESC"
        else:
            sql += " ORDER BY timestamp ASC"
            
        with self.get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            return cursor.fetchall()


# ==========================================
# 2. Main Application Class
# ==========================================
class SiloSightApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.title("SiloSight - Visual Asset Management Engine")
        self.geometry("1300x850")
        self.minsize(1100, 700)
        
        # Initialize DB and config
        self.db = DBManager()
        self.volatile_directories = []
        self.classifier = None
        
        # Global states
        self.scanning_active = False
        self.current_results = []  # Holds current list of search results tuples
        self.selected_indices = [] # Holds current listbox selected indices
        self.thumbnail_cache = {}  # Caches Pillow Images to prevent garbage collection
        
        # Initialize Privacy Setting
        # Privacy state: 1 (Enabled) = Save directories, 0 (Disabled) = Privacy Mode active (Volatile memory only)
        privacy_val = self.db.get_setting("save_directories_across_sessions", "1")
        self.save_dirs_var = tk.StringVar(value=privacy_val)
        
        # Initialize AI settings
        ai_model_val = self.db.get_setting("ai_model_id", "microsoft/resnet-50")
        self.ai_model_var = tk.StringVar(value=ai_model_val)
        
        threshold_val = float(self.db.get_setting("ai_confidence_threshold", "0.1"))
        self.ai_threshold_var = tk.DoubleVar(value=threshold_val)
        
        # Setup base layouts
        self.setup_layout()
        
        # Load directory list
        self.refresh_directory_ui()
        
        # Initial search run to populate layout
        self.run_search()

    # ==========================================
    # 3. Layout Setup
    # ==========================================
    def setup_layout(self):
        # Master grid configuration:
        # Col 0 (Left Panel - 300px), Col 1 (Middle Panel - Weight 1), Col 2 (Right Panel - 350px)
        # Row 0 (Content - Weight 1), Row 1 (Status bar - Weight 0)
        self.grid_columnconfigure(0, weight=0, minsize=320)
        self.grid_columnconfigure(1, weight=1, minsize=400)
        self.grid_columnconfigure(2, weight=0, minsize=380)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)

        # ------------------------------------------
        # LEFT PANEL: Settings & Directory Tracker
        # ------------------------------------------
        left_panel = ctk.CTkFrame(self, corner_radius=0, border_width=1, border_color="#2b2b2b")
        left_panel.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)
        
        left_panel.grid_rowconfigure(4, weight=1) # The directory scrollable list gets weight
        
        title_left = ctk.CTkLabel(left_panel, text="Settings & Tracks", font=("Segoe UI", 18, "bold"))
        title_left.grid(row=0, column=0, sticky="w", padx=15, pady=(15, 10))
        
        # Settings frame
        settings_frame = ctk.CTkFrame(left_panel, fg_color="transparent")
        settings_frame.grid(row=1, column=0, sticky="ew", padx=15, pady=(0, 15))
        settings_frame.grid_columnconfigure(0, weight=1)
        
        privacy_toggle = ctk.CTkSwitch(
            settings_frame, 
            text="Save directories across sessions",
            variable=self.save_dirs_var,
            onvalue="1",
            offvalue="0",
            command=self.toggle_privacy_mode
        )
        privacy_toggle.grid(row=0, column=0, sticky="w", pady=5)
        
        model_lbl = ctk.CTkLabel(settings_frame, text="AI Classifier Model", font=("Segoe UI", 11, "bold"), text_color="#aaaaaa")
        model_lbl.grid(row=1, column=0, sticky="w", pady=(8, 2))
        
        model_dropdown = ctk.CTkOptionMenu(
            settings_frame, 
            values=["microsoft/resnet-50", "google/vit-base-patch16-224", "Salesforce/blip-image-captioning-base"],
            variable=self.ai_model_var,
            command=self.on_model_change,
            height=28,
            font=("Segoe UI", 11)
        )
        model_dropdown.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        
        self.ai_threshold_lbl = ctk.CTkLabel(settings_frame, text=f"AI Tag Threshold: {int(self.ai_threshold_var.get() * 100)}%", font=("Segoe UI", 11, "bold"), text_color="#aaaaaa")
        self.ai_threshold_lbl.grid(row=3, column=0, sticky="w", pady=(8, 2))
        
        threshold_slider = ctk.CTkSlider(
            settings_frame, 
            from_=0.01, 
            to=0.99, 
            variable=self.ai_threshold_var, 
            command=self.on_threshold_change,
            height=16
        )
        threshold_slider.grid(row=4, column=0, sticky="ew", pady=(0, 5))
        
        # Separator line
        sep1 = ctk.CTkFrame(left_panel, height=2, fg_color="#333333")
        sep1.grid(row=2, column=0, sticky="ew", padx=15, pady=5)
        
        # Managed directories header
        dir_header_frame = ctk.CTkFrame(left_panel, fg_color="transparent")
        dir_header_frame.grid(row=3, column=0, sticky="ew", padx=15, pady=(10, 5))
        
        dir_label = ctk.CTkLabel(dir_header_frame, text="Tracked Folders", font=("Segoe UI", 14, "bold"))
        dir_label.grid(row=0, column=0, sticky="w")
        
        add_dir_btn = ctk.CTkButton(
            dir_header_frame, 
            text="+ Add Folder", 
            width=90, 
            height=28,
            font=("Segoe UI", 11, "bold"),
            command=self.add_directory_dialog
        )
        add_dir_btn.grid(row=0, column=1, sticky="e", padx=(40, 0))
        
        # Managed directories scrollable frame
        self.dir_list_frame = ctk.CTkScrollableFrame(
            left_panel, 
            fg_color="#1a1a1a", 
            border_width=1, 
            border_color="#2b2b2b"
        )
        self.dir_list_frame.grid(row=4, column=0, sticky="nsew", padx=15, pady=(5, 10))
        
        # Maintenance panel (Prune utility)
        maintenance_frame = ctk.CTkFrame(left_panel, fg_color="transparent")
        maintenance_frame.grid(row=5, column=0, sticky="ew", padx=15, pady=(5, 15))
        
        prune_btn = ctk.CTkButton(
            maintenance_frame,
            text="Prune Dead Files",
            fg_color="#aa3333",
            hover_color="#882222",
            height=35,
            font=("Segoe UI", 12, "bold"),
            command=self.prune_dead_files
        )
        prune_btn.grid(row=0, column=0, sticky="ew")
        maintenance_frame.grid_columnconfigure(0, weight=1)

        # ------------------------------------------
        # MIDDLE PANEL: Search & Results
        # ------------------------------------------
        middle_panel = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        middle_panel.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        
        middle_panel.grid_rowconfigure(2, weight=1) # Search results list gets weight
        middle_panel.grid_columnconfigure(0, weight=1)
        
        # Search & controls bar
        search_control_frame = ctk.CTkFrame(middle_panel, fg_color="#1c1d21", border_width=1, border_color="#2b2b2b")
        search_control_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        search_control_frame.grid_columnconfigure(0, weight=1)
        
        # Search Entry & Button Row
        search_input_frame = ctk.CTkFrame(search_control_frame, fg_color="transparent")
        search_input_frame.grid(row=0, column=0, columnspan=3, sticky="ew", padx=12, pady=(12, 6))
        search_input_frame.grid_columnconfigure(0, weight=1)
        
        self.search_entry = ctk.CTkEntry(
            search_input_frame, 
            placeholder_text="Search tags (e.g. dog, park)...",
            height=36,
            font=("Segoe UI", 12)
        )
        self.search_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.search_entry.bind("<KeyRelease>", lambda event: self.run_search())
        
        search_btn = ctk.CTkButton(
            search_input_frame, 
            text="Search", 
            width=80, 
            height=36,
            font=("Segoe UI", 12, "bold"),
            command=self.run_search
        )
        search_btn.grid(row=0, column=1)

        # Filters Row (Sort dropdown, Favorites checkbox, Scan action)
        filters_frame = ctk.CTkFrame(search_control_frame, fg_color="transparent")
        filters_frame.grid(row=1, column=0, columnspan=3, sticky="ew", padx=12, pady=(6, 12))
        
        sort_label = ctk.CTkLabel(filters_frame, text="Sort by:", font=("Segoe UI", 11))
        sort_label.grid(row=0, column=0, sticky="w")
        
        self.sort_menu = ctk.CTkOptionMenu(
            filters_frame,
            values=["Newest First", "Oldest First"],
            width=120,
            height=28,
            font=("Segoe UI", 11),
            command=lambda choice: self.run_search()
        )
        self.sort_menu.grid(row=0, column=1, padx=(5, 15), sticky="w")
        self.sort_menu.set("Newest First")
        
        self.favorites_only_var = tk.BooleanVar(value=False)
        self.favorites_only_chk = ctk.CTkCheckBox(
            filters_frame,
            text="Favorites Only",
            variable=self.favorites_only_var,
            font=("Segoe UI", 11),
            command=self.run_search
        )
        self.favorites_only_chk.grid(row=0, column=2, padx=(0, 20), sticky="w")
        
        # Scan & Index action button (anchored right)
        self.scan_btn = ctk.CTkButton(
            filters_frame,
            text="Scan & Index Folders",
            fg_color="#2b8a3e",
            hover_color="#237032",
            height=28,
            font=("Segoe UI", 11, "bold"),
            command=self.start_background_scan
        )
        self.scan_btn.grid(row=0, column=3, sticky="e")
        filters_frame.grid_columnconfigure(3, weight=1)

        # Results header count
        self.results_count_lbl = ctk.CTkLabel(
            middle_panel, 
            text="Gallery Assets (0 found)", 
            font=("Segoe UI", 14, "bold"),
            anchor="w"
        )
        self.results_count_lbl.grid(row=1, column=0, sticky="w", pady=(0, 5))

        # Main Listbox Frame
        listbox_outer = ctk.CTkFrame(middle_panel, fg_color="#18181a", border_width=1, border_color="#2b2b2b")
        listbox_outer.grid(row=2, column=0, sticky="nsew")
        listbox_outer.grid_rowconfigure(0, weight=1)
        listbox_outer.grid_columnconfigure(0, weight=1)

        # tk.Listbox styled beautifully inside the dark frame
        self.listbox = tk.Listbox(
            listbox_outer,
            selectmode=tk.EXTENDED,
            bg="#141416",
            fg="#e0e0e0",
            selectbackground="#2c3e50",
            selectforeground="#ffffff",
            highlightthickness=0,
            bd=0,
            font=("Consolas" if sys.platform.startswith("win") else "Courier", 11)
        )
        self.listbox.grid(row=0, column=0, sticky="nsew", padx=(5, 0), pady=5)
        
        # Add ctk scrollbar
        scrollbar = ctk.CTkScrollbar(listbox_outer, orientation="vertical", command=self.listbox.yview)
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 5), pady=5)
        self.listbox.configure(yscrollcommand=scrollbar.set)
        
        # Bind events
        self.listbox.bind("<<ListboxSelect>>", self.on_listbox_select)
        self.listbox.bind("<Double-1>", self.on_listbox_double_click)

        # ------------------------------------------
        # RIGHT PANEL: Preview & Metadata Editor
        # ------------------------------------------
        right_panel = ctk.CTkFrame(self, corner_radius=0, border_width=1, border_color="#2b2b2b")
        right_panel.grid(row=0, column=2, sticky="nsew", padx=2, pady=2)
        
        right_panel.grid_rowconfigure(1, weight=1) # Editor frame gets weight
        right_panel.grid_columnconfigure(0, weight=1)
        
        title_right = ctk.CTkLabel(right_panel, text="Asset Details", font=("Segoe UI", 18, "bold"))
        title_right.grid(row=0, column=0, sticky="w", padx=15, pady=(15, 10))
        
        # Editor content frame
        self.editor_frame = ctk.CTkFrame(right_panel, fg_color="transparent")
        self.editor_frame.grid(row=1, column=0, sticky="nsew", padx=15, pady=(0, 15))
        self.editor_frame.grid_columnconfigure(0, weight=1)

        # Initial placeholder when nothing is selected
        self.setup_empty_editor_view()

        # ------------------------------------------
        # BOTTOM PANEL: Dynamic Status Bar
        # ------------------------------------------
        self.status_bar_frame = ctk.CTkFrame(self, height=26, corner_radius=0, fg_color="#18181a")
        self.status_bar_frame.grid(row=1, column=0, columnspan=3, sticky="ew")
        
        self.status_lbl = ctk.CTkLabel(
            self.status_bar_frame, 
            text="Ready", 
            font=("Segoe UI", 11),
            anchor="w"
        )
        self.status_lbl.pack(side="left", padx=15, fill="x", expand=True)

    # ==========================================
    # 4. Settings & Directory Operations
    # ==========================================
    def toggle_privacy_mode(self):
        mode = self.save_dirs_var.get()
        self.db.save_setting("save_directories_across_sessions", mode)
        
        if mode == "0":
            # Purge the directory database entries immediately, copy to volatile memory
            tracked = self.db.get_tracked_directories()
            for t in tracked:
                if t not in self.volatile_directories:
                    self.volatile_directories.append(t)
            self.db.clear_tracked_directories()
            self.set_status("Privacy Mode Enabled: Tracked directories will not be stored across sessions.")
        else:
            # Commit whatever volatile directories we currently have back into the DB
            for folder in self.volatile_directories:
                self.db.add_tracked_directory(folder)
            self.volatile_directories.clear()
            self.set_status("Privacy Mode Disabled: Tracked directories saved database-side.")
            
        self.refresh_directory_ui()

    def on_threshold_change(self, value):
        val = round(float(value), 2)
        self.ai_threshold_lbl.configure(text=f"AI Tag Threshold: {int(val * 100)}%")
        self.db.save_setting("ai_confidence_threshold", str(val))

    def on_model_change(self, choice):
        self.db.save_setting("ai_model_id", choice)
        self.classifier = None
        logging.info(f"AI classification model changed to: {choice}")
        self.set_status(f"AI Model changed to: {choice} (will load on next scan)")

    def get_active_directories(self):
        if self.save_dirs_var.get() == "1":
            return self.db.get_tracked_directories()
        else:
            return self.volatile_directories

    def refresh_directory_ui(self):
        # Clear existing widgets inside dir_list_frame
        for widget in self.dir_list_frame.winfo_children():
            widget.destroy()
            
        dirs = self.get_active_directories()
        
        if not dirs:
            empty_lbl = ctk.CTkLabel(
                self.dir_list_frame, 
                text="No tracked folders.\nClick '+ Add Folder' above.",
                font=("Segoe UI", 11, "italic"),
                text_color="#888888"
            )
            empty_lbl.pack(pady=20, fill="x")
            return
            
        for path in dirs:
            row_frame = ctk.CTkFrame(self.dir_list_frame, fg_color="#222224", height=32)
            row_frame.pack(fill="x", pady=2, padx=2)
            row_frame.pack_propagate(False)
            
            # Shorten display path if it's too long
            display_path = path
            if len(display_path) > 30:
                display_path = "..." + display_path[-27:]
                
            path_lbl = ctk.CTkLabel(
                row_frame, 
                text=display_path, 
                font=("Segoe UI", 11),
                anchor="w"
            )
            path_lbl.pack(side="left", fill="x", expand=True, padx=(10, 5))
            
            # Remove button
            remove_btn = ctk.CTkButton(
                row_frame,
                text="✕",
                width=24,
                height=24,
                fg_color="#aa3333",
                hover_color="#882222",
                font=("Segoe UI", 10, "bold"),
                command=lambda p=path: self.remove_directory(p)
            )
            remove_btn.pack(side="right", padx=(5, 5))

    def add_directory_dialog(self):
        folder = filedialog.askdirectory(title="Select Local Directory to Index")
        if folder:
            # Normalize path
            folder = os.path.abspath(folder)
            active_dirs = self.get_active_directories()
            if folder in active_dirs:
                messagebox.showinfo("Folder Already Tracked", "This folder is already in the tracked directories list.")
                return
                
            if self.save_dirs_var.get() == "1":
                self.db.add_tracked_directory(folder)
            else:
                self.volatile_directories.append(folder)
                
            self.refresh_directory_ui()
            self.set_status(f"Added tracked directory: {folder}")

    def remove_directory(self, path):
        if self.save_dirs_var.get() == "1":
            self.db.remove_tracked_directory(path)
        else:
            if path in self.volatile_directories:
                self.volatile_directories.remove(path)
                
        self.refresh_directory_ui()
        self.set_status(f"Removed tracked directory: {path}")

    # ==========================================
    # 5. Background Scanning & Indexing
    # ==========================================
    def start_background_scan(self):
        if self.scanning_active:
            messagebox.showwarning("Scan Running", "A scan is already in progress.")
            return
            
        active_dirs = self.get_active_directories()
        if not active_dirs:
            messagebox.showwarning("No Folders", "Please add at least one tracked folder to scan.")
            return
            
        self.scan_btn.configure(state="disabled", text="Scanning...")
        self.scanning_active = True
        
        # Spin up daemon scanning thread
        scan_thread = threading.Thread(target=self.scan_worker_thread, daemon=True)
        scan_thread.start()
        
        # Start GUI polling loop
        self.poll_indexing_status()

    def scan_worker_thread(self):
        logging.info("Starting background scan worker thread...")
        self.scan_msg = "Gathering image files..."
        self.scan_total = 0
        self.scan_current = 0
        self.scan_new_indexed = 0
        
        active_dirs = self.get_active_directories()
        logging.info(f"Active tracked directories to scan: {active_dirs}")
        supported_exts = (".jpg", ".jpeg", ".png", ".webp", ".jfif", ".bmp", ".tiff", ".gif")
        
        # Traverse directories and identify all images
        all_image_paths = []
        for folder in active_dirs:
            if not os.path.isdir(folder):
                logging.warning(f"Tracked path is not a valid directory: {folder}")
                continue
            logging.info(f"Walking directory: {folder}")
            for root, dirs, files in os.walk(folder):
                for file in files:
                    if file.lower().endswith(supported_exts):
                        full_path = os.path.abspath(os.path.join(root, file))
                        all_image_paths.append(full_path)
                        logging.debug(f"Found image candidate: {full_path}")
                        
        self.scan_total = len(all_image_paths)
        logging.info(f"Total image candidates found: {self.scan_total}")
        if self.scan_total == 0:
            logging.info("No images matching supported extensions (.jpg, .jpeg, .png) were found.")
            self.scan_msg = "No images found in tracked directories."
            self.scanning_active = False
            return

        # Determine pipeline type from model ID
        model_id = self.ai_model_var.get()
        if "blip" in model_id.lower() or "git-" in model_id.lower() or "caption" in model_id.lower():
            pipeline_type = "image-to-text"
        else:
            pipeline_type = "image-classification"

        # Load pipeline (offline AI model)
        try:
            self.scan_msg = f"Loading offline model ({model_id})..."
            logging.info(f"Loading offline Hugging Face pipeline/model for model: {model_id}...")
            import torch
            device = 0 if torch.cuda.is_available() else -1
            logging.info(f"Torch device selected: {device} (CUDA available: {torch.cuda.is_available()})")
            
            if "blip" in model_id.lower():
                from transformers import BlipProcessor, BlipForConditionalGeneration
                device_name = "cuda" if torch.cuda.is_available() else "cpu"
                logging.info(f"Loading BLIP processor & model directly on device: {device_name}")
                self.blip_processor = BlipProcessor.from_pretrained(model_id)
                self.classifier = BlipForConditionalGeneration.from_pretrained(model_id).to(device_name)
            else:
                from transformers import pipeline
                try:
                    self.classifier = pipeline(pipeline_type, model=model_id, device=device)
                except KeyError as ke:
                    if pipeline_type == "image-to-text":
                        logging.info("Fallback: 'image-to-text' task not supported, attempting 'image-text-to-text'...")
                        pipeline_type = "image-text-to-text"
                        self.classifier = pipeline(pipeline_type, model=model_id, device=device)
                    else:
                        raise ke
            logging.info("Classifier/model initialized successfully.")
        except Exception as e:
            err_msg = f"Failed to initialize Hugging Face model {model_id}: {str(e)}"
            logging.error(err_msg, exc_info=True)
            self.scan_msg = err_msg
            self.scanning_active = False
            return
            
        # Process images one by one
        for filepath in all_image_paths:
            self.scan_current += 1
            
            # Check if already indexed
            if self.db.is_image_indexed(filepath):
                logging.info(f"Image already indexed, skipping: {filepath}")
                continue
                
            self.scan_msg = f"Indexing image {self.scan_current}/{self.scan_total}: {os.path.basename(filepath)}"
            logging.info(f"Processing image {self.scan_current}/{self.scan_total}: {filepath}")
            
            try:
                # Open image and verify
                with Image.open(filepath) as img:
                    img.verify()
                logging.info(f"Pillow verification successful for: {filepath}")
                
                # Get modified timestamp
                timestamp = os.path.getmtime(filepath)
                
                # Predict tags
                logging.info(f"Running classifier on image: {filepath}")
                if "blip" in model_id.lower():
                    # Direct BLIP inference
                    with Image.open(filepath).convert("RGB") as raw_img:
                        device_name = "cuda" if torch.cuda.is_available() else "cpu"
                        inputs = self.blip_processor(images=raw_img, return_tensors="pt").to(device_name)
                        outputs = self.classifier.generate(**inputs, max_new_tokens=50)
                        caption = self.blip_processor.decode(outputs[0], skip_special_tokens=True)
                    logging.info(f"Generated caption: '{caption}'")
                    
                    # Stopwords to filter out
                    stopwords = {
                        "a", "an", "the", "in", "on", "at", "of", "to", "for", "with", "by", 
                        "is", "are", "was", "were", "and", "or", "but", "about", "showing", 
                        "holding", "standing", "sitting", "lying", "playing", "using", "front", 
                        "back", "background", "foreground", "photo", "picture", "image", "close", 
                        "view", "shot", "look", "looking", "there", "has", "have", "some", "many",
                        "this", "that", "these", "those", "it", "its", "of", "from"
                    }
                    
                    # Extract words
                    words = re.findall(r'\b[a-zA-Z]{2,}\b', caption.lower())
                    tags = [w for w in words if w not in stopwords]
                    ai_tags_str = ", ".join(sorted(list(set(tags))))
                elif pipeline_type in ("image-to-text", "image-text-to-text"):
                    predictions = self.classifier(filepath)
                    caption = predictions[0]['generated_text']
                    logging.info(f"Generated caption: '{caption}'")
                    
                    # Stopwords to filter out
                    stopwords = {
                        "a", "an", "the", "in", "on", "at", "of", "to", "for", "with", "by", 
                        "is", "are", "was", "were", "and", "or", "but", "about", "showing", 
                        "holding", "standing", "sitting", "lying", "playing", "using", "front", 
                        "back", "background", "foreground", "photo", "picture", "image", "close", 
                        "view", "shot", "look", "looking", "there", "has", "have", "some", "many",
                        "this", "that", "these", "those", "it", "its", "of", "from"
                    }
                    
                    # Extract words
                    words = re.findall(r'\b[a-zA-Z]{2,}\b', caption.lower())
                    tags = [w for w in words if w not in stopwords]
                    ai_tags_str = ", ".join(sorted(list(set(tags))))
                else:
                    predictions = self.classifier(filepath)
                    threshold = self.ai_threshold_var.get()
                    tags = [pred['label'] for pred in predictions if pred['score'] > threshold]
                    ai_tags_str = ", ".join(tags)
                logging.info(f"Generated tags: {ai_tags_str}")
                
                # Commit to Database
                self.db.add_image(filepath, ai_tags=ai_tags_str, timestamp=timestamp)
                self.scan_new_indexed += 1
                logging.info(f"Successfully indexed and committed: {filepath}")
                
            except Exception as e:
                logging.error(f"Error processing image {filepath}: {str(e)}", exc_info=True)
                
        completion_msg = f"Indexing completed. Indexed {self.scan_new_indexed} new image(s)."
        logging.info(completion_msg)
        self.scan_msg = completion_msg
        self.scanning_active = False

    def poll_indexing_status(self):
        if hasattr(self, 'scan_msg'):
            self.set_status(self.scan_msg)
            
        if self.scanning_active:
            # Poll every 150ms
            self.after(150, self.poll_indexing_status)
        else:
            # Enable button and refresh Middle panel results list
            self.scan_btn.configure(state="normal", text="Scan & Index Folders")
            self.run_search()

    # ==========================================
    # 6. Database Pruning
    # ==========================================
    def prune_dead_files(self):
        # Runs a validation loop over all db rows to delete nonexistent paths
        records = self.db.get_all_images()
        if not records:
            messagebox.showinfo("Pruning Complete", "Database is currently empty; nothing to prune.")
            return
            
        self.set_status("Pruning database: Validating file paths on local disk...")
        
        pruned_count = 0
        for row in records:
            path = row[0]
            if not os.path.exists(path):
                self.db.delete_image(path)
                pruned_count += 1
                
        self.run_search()
        self.set_status(f"Prune Complete: Removed {pruned_count} dead/missing entries from the database.")
        messagebox.showinfo("Pruning Complete", f"Successfully pruned {pruned_count} dead/missing file(s) from the database.")

    # ==========================================
    # 7. Search & Results Engine
    # ==========================================
    def run_search(self):
        query = self.search_entry.get()
        show_favorites = self.favorites_only_var.get()
        
        # Sort option mapping
        sort_choice = self.sort_menu.get()
        sort_mode = "newest" if sort_choice == "Newest First" else "oldest"
        
        # Perform query on DB
        self.current_results = self.db.search_gallery(query, show_favorites_only=show_favorites, sort_by=sort_mode)
        
        # Update search results listbox
        self.listbox.delete(0, tk.END)
        for row in self.current_results:
            filepath = row[0]
            filename = os.path.basename(filepath)
            fav_indicator = "★ " if row[3] == 1 else "  "
            
            # Format nicely
            self.listbox.insert(tk.END, f"{fav_indicator}{filename}  |  {filepath}")
            
        # Update stats text
        total_images = len(self.db.get_all_images())
        match_count = len(self.current_results)
        self.results_count_lbl.configure(text=f"Gallery Assets ({match_count} found)")
        
        # Update status bar stats
        self.set_status(f"Matches: {match_count}  |  Database Size: {total_images} image(s) indexed")

    # ==========================================
    # 8. Selection & Editor Views
    # ==========================================
    def on_listbox_select(self, event):
        # We need to extract the selected indices from listbox
        selections = self.listbox.curselection()
        if not selections:
            self.selected_indices = []
            self.setup_empty_editor_view()
            return
            
        self.selected_indices = list(selections)
        
        if len(self.selected_indices) == 1:
            # Single select mode
            self.setup_single_editor_view(self.selected_indices[0])
        else:
            # Batch select mode
            self.setup_batch_editor_view()

    def on_listbox_double_click(self, event):
        selections = self.listbox.curselection()
        if not selections:
            return
            
        index = selections[0]
        filepath = self.current_results[index][0]
        
        if os.path.exists(filepath):
            self.set_status(f"Opening image: {filepath}")
            try:
                # Open with native photo viewer on Windows / OS
                if hasattr(os, 'startfile'):
                    os.startfile(filepath)
                else:
                    import subprocess
                    if sys.platform.startswith('darwin'):
                        subprocess.run(['open', filepath])
                    else:
                        subprocess.run(['xdg-open', filepath])
            except Exception as e:
                messagebox.showerror("Error Opening File", f"Failed to launch native file viewer:\n{str(e)}")
        else:
            messagebox.showerror("File Not Found", f"The image path does not exist on disk:\n{filepath}\n\nConsider running 'Prune Dead Files'.")

    # ------------------------------------------
    # Editor Layout Generation
    # ------------------------------------------
    def setup_empty_editor_view(self):
        # Clear editor pane
        for widget in self.editor_frame.winfo_children():
            widget.destroy()
            
        self.editor_frame.grid_rowconfigure(0, weight=1)
        
        empty_lbl = ctk.CTkLabel(
            self.editor_frame, 
            text="No image selected.\n\nSelect an item in the search results\nto view details and manage tags.",
            font=("Segoe UI", 12, "italic"),
            text_color="#888888"
        )
        empty_lbl.grid(row=0, column=0, sticky="nsew", pady=40)

    def setup_single_editor_view(self, result_index):
        # Clear editor pane
        for widget in self.editor_frame.winfo_children():
            widget.destroy()
            
        # Get item data
        path, ai_tags, user_tags, is_favorite, timestamp = self.current_results[result_index]
        
        # Configure layout row weights
        self.editor_frame.grid_rowconfigure(0, weight=0) # Thumbnail row
        self.editor_frame.grid_rowconfigure(1, weight=1) # Scrollable info controls
        
        # Thumbnail rendering (Pillow aspect-ratio preserved max 200x200)
        thumb_frame = ctk.CTkFrame(self.editor_frame, fg_color="#18181a", border_width=1, border_color="#2b2b2b")
        thumb_frame.grid(row=0, column=0, sticky="ew", pady=(0, 15))
        thumb_frame.grid_columnconfigure(0, weight=1)
        thumb_frame.grid_rowconfigure(0, weight=1)
        
        preview_lbl = ctk.CTkLabel(thumb_frame, text="[Loading Preview...]")
        preview_lbl.grid(row=0, column=0, padx=10, pady=10)
        
        # Generate thumbnail
        self.render_thumbnail(path, preview_lbl)

        # Scrollable form for metadata fields
        form_scroll = ctk.CTkScrollableFrame(self.editor_frame, fg_color="transparent")
        form_scroll.grid(row=1, column=0, sticky="nsew")
        form_scroll.grid_columnconfigure(0, weight=1)
        
        # 1. File path display
        path_lbl = ctk.CTkLabel(form_scroll, text="File Path", font=("Segoe UI", 11, "bold"), anchor="w")
        path_lbl.grid(row=0, column=0, sticky="w", pady=(0, 2))
        
        path_text = ctk.CTkTextbox(form_scroll, height=45, font=("Consolas", 10))
        path_text.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        path_text.insert("1.0", path)
        path_text.configure(state="disabled")
        
        # 2. Date created/modified
        dt = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
        date_lbl = ctk.CTkLabel(form_scroll, text=f"Modified Date: {dt}", font=("Segoe UI", 11), anchor="w")
        date_lbl.grid(row=2, column=0, sticky="w", pady=(0, 10))
        
        # 3. AI Tags (Read-only)
        ai_tags_lbl = ctk.CTkLabel(form_scroll, text="AI Auto-Tags (Read-Only)", font=("Segoe UI", 11, "bold"), anchor="w")
        ai_tags_lbl.grid(row=3, column=0, sticky="w", pady=(0, 2))
        
        ai_tags_box = ctk.CTkTextbox(form_scroll, height=55, font=("Segoe UI", 11))
        ai_tags_box.grid(row=4, column=0, sticky="ew", pady=(0, 10))
        ai_tags_box.insert("1.0", ai_tags if ai_tags else "(No AI tags generated)")
        ai_tags_box.configure(state="disabled")
        
        # 4. User tags (Editable)
        user_tags_lbl = ctk.CTkLabel(form_scroll, text="Custom User Tags", font=("Segoe UI", 11, "bold"), anchor="w")
        user_tags_lbl.grid(row=5, column=0, sticky="w", pady=(0, 2))
        
        self.user_tags_entry = ctk.CTkEntry(form_scroll, height=32, font=("Segoe UI", 12))
        self.user_tags_entry.grid(row=6, column=0, sticky="ew", pady=(0, 5))
        self.user_tags_entry.insert(0, user_tags if user_tags else "")
        
        # Save tags button
        save_tags_btn = ctk.CTkButton(
            form_scroll,
            text="Save Custom Tags",
            height=28,
            font=("Segoe UI", 11, "bold"),
            command=lambda p=path: self.save_user_tags(p)
        )
        save_tags_btn.grid(row=7, column=0, sticky="ew", pady=(0, 15))
        
        # 5. Favorite Control Toggle
        fav_btn_text = "★ Unfavorite" if is_favorite == 1 else "☆ Favorite"
        fav_btn_color = "#3a4f7c" if is_favorite == 1 else "#1f538d"
        fav_btn = ctk.CTkButton(
            form_scroll,
            text=fav_btn_text,
            fg_color=fav_btn_color,
            height=32,
            font=("Segoe UI", 12, "bold"),
            command=lambda p=path, f=is_favorite: self.toggle_image_favorite(p, f)
        )
        fav_btn.grid(row=8, column=0, sticky="ew", pady=(5, 15))

    def setup_batch_editor_view(self):
        # Clear editor pane
        for widget in self.editor_frame.winfo_children():
            widget.destroy()
            
        num_selected = len(self.selected_indices)
        
        self.editor_frame.grid_rowconfigure(0, weight=0) # Header info
        self.editor_frame.grid_rowconfigure(1, weight=1) # Controls layout
        
        # Header showing batch count
        header_frame = ctk.CTkFrame(self.editor_frame, fg_color="#1c1d21", border_width=1, border_color="#2b2b2b")
        header_frame.grid(row=0, column=0, sticky="ew", pady=(0, 15))
        header_lbl = ctk.CTkLabel(
            header_frame, 
            text=f"Bulk Action Mode\n({num_selected} items selected)", 
            font=("Segoe UI", 13, "bold"),
            pady=10
        )
        header_lbl.pack(fill="x")
        
        scroll_controls = ctk.CTkScrollableFrame(self.editor_frame, fg_color="transparent")
        scroll_controls.grid(row=1, column=0, sticky="nsew")
        scroll_controls.grid_columnconfigure(0, weight=1)
        
        # Batch User Tags input
        tag_lbl = ctk.CTkLabel(scroll_controls, text="Batch Custom Tags", font=("Segoe UI", 11, "bold"), anchor="w")
        tag_lbl.grid(row=0, column=0, sticky="w", pady=(0, 2))
        
        self.batch_tags_entry = ctk.CTkEntry(
            scroll_controls, 
            placeholder_text="Enter tags (e.g., vacation, nature)...",
            height=32,
            font=("Segoe UI", 12)
        )
        self.batch_tags_entry.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        
        # Two buttons for bulk tags action: Overwrite vs Append
        btn_frame = ctk.CTkFrame(scroll_controls, fg_color="transparent")
        btn_frame.grid(row=2, column=0, sticky="ew", pady=(0, 15))
        btn_frame.grid_columnconfigure(0, weight=1)
        btn_frame.grid_columnconfigure(1, weight=1)
        
        append_btn = ctk.CTkButton(
            btn_frame,
            text="Append Tags",
            font=("Segoe UI", 11),
            command=lambda: self.apply_batch_tags(overwrite=False)
        )
        append_btn.grid(row=0, column=0, padx=(0, 5), sticky="ew")
        
        overwrite_btn = ctk.CTkButton(
            btn_frame,
            text="Overwrite Tags",
            font=("Segoe UI", 11),
            command=lambda: self.apply_batch_tags(overwrite=True)
        )
        overwrite_btn.grid(row=0, column=1, padx=(5, 0), sticky="ew")

        # Favorites bulk toggle buttons
        fav_header_lbl = ctk.CTkLabel(scroll_controls, text="Favorites Bulk Update", font=("Segoe UI", 11, "bold"), anchor="w")
        fav_header_lbl.grid(row=3, column=0, sticky="w", pady=(5, 2))
        
        fav_btn_frame = ctk.CTkFrame(scroll_controls, fg_color="transparent")
        fav_btn_frame.grid(row=4, column=0, sticky="ew", pady=(0, 15))
        fav_btn_frame.grid_columnconfigure(0, weight=1)
        fav_btn_frame.grid_columnconfigure(1, weight=1)
        
        bulk_fav_btn = ctk.CTkButton(
            fav_btn_frame,
            text="★ Favorite All",
            fg_color="#2b8a3e",
            hover_color="#237032",
            font=("Segoe UI", 11, "bold"),
            command=lambda: self.apply_batch_favorite(favorite_val=1)
        )
        bulk_fav_btn.grid(row=0, column=0, padx=(0, 5), sticky="ew")
        
        bulk_unfav_btn = ctk.CTkButton(
            fav_btn_frame,
            text="☆ Unfavorite All",
            fg_color="#aa3333",
            hover_color="#882222",
            font=("Segoe UI", 11, "bold"),
            command=lambda: self.apply_batch_favorite(favorite_val=0)
        )
        bulk_unfav_btn.grid(row=0, column=1, padx=(5, 0), sticky="ew")

    # ------------------------------------------
    # Action Handlers for Tags and Favorites
    # ------------------------------------------
    def save_user_tags(self, path):
        tags = self.user_tags_entry.get().strip()
        self.db.update_user_tags(path, tags)
        self.run_search() # Update list to capture modifications if any
        self.set_status(f"Saved custom tags for: {os.path.basename(path)}")

    def toggle_image_favorite(self, path, current_fav):
        new_fav = 0 if current_fav == 1 else 1
        self.db.update_favorite(path, new_fav)
        self.run_search()
        
        # Find path index in current listbox to preserve selection highlight if possible
        self.restore_selection_by_path(path)
        self.set_status(f"Updated favorite status for: {os.path.basename(path)}")

    def apply_batch_tags(self, overwrite=False):
        new_tags_input = self.batch_tags_entry.get().strip()
        if not new_tags_input:
            messagebox.showwarning("Empty Tags", "Please enter one or more tags to apply.")
            return
            
        # Extract selected paths
        paths_to_update = [self.current_results[idx][0] for idx in self.selected_indices]
        
        for path in paths_to_update:
            if overwrite:
                # Replace completely
                self.db.update_user_tags(path, new_tags_input)
            else:
                # Append to existing
                current_item = self.db.get_image(path)
                if current_item:
                    existing_user_tags = current_item[2] # user_tags column
                    if existing_user_tags:
                        # Split existing tags by commas to check duplicates
                        existing_list = [t.strip() for t in existing_user_tags.split(",") if t.strip()]
                        new_list = [t.strip() for t in new_tags_input.split(",") if t.strip()]
                        for t in new_list:
                            if t not in existing_list:
                                existing_list.append(t)
                        combined_tags = ", ".join(existing_list)
                    else:
                        combined_tags = new_tags_input
                    self.db.update_user_tags(path, combined_tags)
                    
        self.run_search()
        # Restore selection highlights
        for idx in self.selected_indices:
            self.listbox.select_set(idx)
            
        self.set_status(f"Batch updated custom tags for {len(paths_to_update)} image(s).")
        messagebox.showinfo("Batch Update", f"Successfully updated tags for {len(paths_to_update)} image(s).")

    def apply_batch_favorite(self, favorite_val=1):
        paths_to_update = [self.current_results[idx][0] for idx in self.selected_indices]
        
        for path in paths_to_update:
            self.db.update_favorite(path, favorite_val)
            
        self.run_search()
        # Restore selections
        for idx in self.selected_indices:
            self.listbox.select_set(idx)
            
        action = "favorited" if favorite_val == 1 else "unfavorited"
        self.set_status(f"Batch {action} {len(paths_to_update)} image(s).")
        messagebox.showinfo("Batch Update", f"Successfully {action} {len(paths_to_update)} image(s).")

    def restore_selection_by_path(self, target_path):
        for idx, row in enumerate(self.current_results):
            if row[0] == target_path:
                self.listbox.select_clear(0, tk.END)
                self.listbox.select_set(idx)
                self.listbox.activate(idx)
                self.listbox.see(idx)
                # Manually trigger listbox select event to load single preview again
                self.on_listbox_select(None)
                break

    # ------------------------------------------
    # Thumbnail Renderer (Async Helper)
    # ------------------------------------------
    def render_thumbnail(self, path, label_widget):
        # We spawn a helper thread to open and scale the image so the UI stays responsive
        def worker():
            try:
                if not os.path.exists(path):
                    self.update_widget_text(label_widget, "[File Not Found]")
                    return
                    
                img = Image.open(path)
                img = ImageOps.exif_transpose(img) # Rotate according to orientation EXIF tag
                
                # Scale thumbnail maintaining aspect ratio
                img.thumbnail((200, 200), Image.Resampling.LANCZOS)
                photo_img = ImageTk.PhotoImage(img)
                
                # Cache photo image globally to prevent garbage collection
                self.thumbnail_cache[path] = photo_img
                
                # Update UI in main thread
                self.after(0, lambda: label_widget.configure(image=photo_img, text=""))
            except Exception as e:
                self.update_widget_text(label_widget, f"[Preview Error:\n{str(e)[:40]}]")
                
        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def update_widget_text(self, widget, text):
        self.after(0, lambda: widget.configure(text=text))

    # ==========================================
    # 9. UI Utility Utilities
    # ==========================================
    def set_status(self, text):
        self.status_lbl.configure(text=text)


# ==========================================
# 10. Execution Entrance
# ==========================================
if __name__ == "__main__":
    app = SiloSightApp()
    app.mainloop()
