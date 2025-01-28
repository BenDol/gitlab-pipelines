import tkinter as tk
from tkinter import ttk, messagebox
import ctypes
import sys
import requests
import os
import time
import json
import asyncio
import webbrowser

if sys.platform == "win32":
  dwmapi = ctypes.WinDLL("dwmapi")
  DWMWA_USE_IMMERSIVE_DARK_MODE = 20  # For Win10 1809+; sometimes 19 is used on earlier builds

# internal imports
import util
settings = util.load_json("settings.json")
util.DEBUG_ENABLED = settings.get("debug", False)
from tray.trayapp import TrayApp
from notification import Notification
from event import EventBus

# If you need image scaling, install Pillow (pip install pillow).
try:
  from PIL import Image, ImageTk
  # For Pillow 10+, Resampling.LANCZOS is the modern equivalent of ANTIALIAS
  from PIL import Image as PILImage
  RESAMPLE = PILImage.Resampling.LANCZOS
except ImportError:
  Image = None
  ImageTk = None
  RESAMPLE = None

APP_NAME = "GitLab Pipelines"
GITLAB_API_URL = settings.get("gitlab_api_url", "https://gitlab.com/api/v4")
GROUP_NAME = settings.get("group_name", "insurance-insight")
CACHE_FILE = "cache.json"
CACHE_REFRESH_SECONDS = settings.get("cache_refresh_seconds", 10 * 60)
REFRESH_RATE_SECONDS = settings.get("refresh_rate_seconds", 5 * 60)
IGNORED_GROUPS = settings.get("ignored_groups", [ "10926345", "6622675" ])
BRANCHES = {
  "4241428": ["2.0-SNAPSHOT", "2.0.0-SNAPSHOT", "1.0-SNAPSHOT", "1.0.0-SNAPSHOT"]
}
DARK_MODE = settings.get("dark_mode", True)

class PipelineCheckerApp(tk.Tk):
  def __init__(self, notif_icon_path="assets/images/notification", event_loop=asyncio.get_event_loop()):
    super().__init__()
    self.geometry("690x820")
    self._offsetx = 0
    self._offsety = 0
    self.event_loop = event_loop
    self.title(APP_NAME)
    self.iconbitmap("assets/images/logo.ico") 
    self.minsize(width=690, height=200)
    self.notification = Notification(
      app_name=APP_NAME,
      title=APP_NAME, 
      message="", 
      icon=notif_icon_path + ".png", 
      on_dismissed=self.on_notification_dismissed, 
      event_loop=self.event_loop
    )
    self.notifications = []

    self.after(10, self.try_dark_title_bar)
    self.protocol("WM_DELETE_WINDOW", self.on_closing)

    util.debug("Initializing main app window.")
    self.loaded = False

    # Load token from environment
    self.token_var = tk.StringVar()
    self.token_var.set(os.getenv("GITLAB_TOKEN", ""))

    def pipeline_status_changed(project_id, project_name, old_status, new_status):
      if old_status != "fetched":
        self.show_notification(
          f"Pipeline status changed for {project_name}",
          f"Status: {old_status} -> {new_status}"
        )
    
    self.event_bus = EventBus()
    self.event_bus.subscribe("pipeline_status_changed", pipeline_status_changed)

    # Increase font and row size in Treeview
    style = ttk.Style(self)
    style.theme_use("clam")
    style.configure("Treeview", font=("Arial", 14), rowheight=30)

    if DARK_MODE:
      style.configure(
        "Treeview",
        background="#2E2E2E",       # Tree body background
        foreground="white",        # Text color
        fieldbackground="#2E2E2E", # Background color for cells
        bordercolor="#2E2E2E",
        borderwidth=1
      )

      style.configure(
        "Treeview.Heading",
        background="#3A3A3A",       # Header background
        foreground="white",        # Header text color
        relief="flat"             # Remove 3D effect if desired
      )             

      # Change the color of selected rows
      style.map(
        "Treeview",
        background=[("selected", "#525252")],
        foreground=[("selected", "white")]
      )

      style.layout("Treeview",
        [
          ("Treeview.treearea", {"sticky": "nswe"})
        ]
      )

    # --- Layout ---
    #self.build_top_panel()

    input_frame = ttk.Frame(self, relief="flat")
    input_frame.configure(borderwidth=0)
    input_frame.pack(padx=10, pady=10, fill="x")

    ttk.Label(input_frame, text="Personal Access Token:", font=("Arial", 12)).pack(side="left")
    self.token_entry = ttk.Entry(input_frame, textvariable=self.token_var, width=50, show="*")
    self.token_entry.bind("<Return>", lambda e: self.on_token_enterkey())
    self.token_entry.bind("<FocusOut>", lambda e: self.on_token_enterkey())
    self.token_entry.pack(side="left", padx=5)

    load_button = ttk.Button(input_frame, text="Reset Groups", command=self.load_root_group)
    load_button.pack(side="left", padx=5)

    refresh_button = ttk.Button(input_frame, text="Refresh", command=self.refresh_groups)
    refresh_button.pack(side="left", padx=5)

    # Tree frame
    tree_frame = ttk.Frame(self)
    tree_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    if DARK_MODE:
      tree_frame.configure(borderwidth=0, relief="flat")

    self.tree = ttk.Treeview(tree_frame, show="tree")
    self.tree.pack(side="left", fill="both", expand=True)

    scrollbar = ttk.Scrollbar(
      tree_frame, 
      orient="vertical", 
      command=self.tree.yview,
      style="Vertical.TScrollbar"
    )
    scrollbar.pack(side="right", fill="y")
    self.tree.config(yscrollcommand=scrollbar.set)

    self.tree.bind("<<TreeviewOpen>>", self.on_tree_open)
    self.tree.bind("<<TreeviewClose>>", self.on_tree_close)
    self.tree.bind("<Double-1>", self.on_tree_double_click)
    self.tree.bind("<Button-3>", self.on_tree_right_click)

    # A label at the bottom to indicate "Loading..."
    self.loading_label = ttk.Label(self, text="", foreground="blue")
    self.loading_label.pack(side="left", pady=5, padx=7)

    self.last_refresh_label = ttk.Label(self, text="", foreground="black")
    self.last_refresh_label.pack(side="right", pady=5, padx=7)

    if DARK_MODE:
      self.loading_label.configure(background="#2e2e2e", foreground="#62afff")
      self.last_refresh_label.configure(background="#2e2e2e", foreground="#62afff")

    # Tags to color rows
    self.tree.tag_configure("success_tag", foreground="green")
    self.tree.tag_configure("fail_tag", foreground="red")
    self.tree.tag_configure("skipped_tag", foreground="grey")

    # Try loading and resizing images
    self.success_img = None
    self.failed_img = None
    self.skipped_img = None
    if Image and ImageTk:
      try:
        util.debug("Loading success.png.")
        success_raw = Image.open("assets/images/success.png")
        if RESAMPLE:
          success_raw = success_raw.resize((20, 20), RESAMPLE)
        else:
          success_raw = success_raw.resize((20, 20), Image.ANTIALIAS)
        self.success_img = ImageTk.PhotoImage(success_raw)
      except Exception as e:
        util.debug(f"Cannot load success.png: {e}")

      try:
        util.debug("Loading failed.png.")
        failed_raw = Image.open("assets/images/failed.png")
        if RESAMPLE:
          failed_raw = failed_raw.resize((20, 20), RESAMPLE)
        else:
          failed_raw = failed_raw.resize((20, 20), Image.ANTIALIAS)
        self.failed_img = ImageTk.PhotoImage(failed_raw)
      except Exception as e:
        util.debug(f"Cannot load failed.png: {e}")

      try:
        util.debug("Loading skipped.png.")
        skipped_raw = Image.open("assets/images/skipped.png")
        if RESAMPLE:
          skipped_raw = skipped_raw.resize((20, 20), RESAMPLE)
        else:
          skipped_raw = skipped_raw.resize((20, 20), Image.ANTIALIAS)
        self.skipped_img = ImageTk.PhotoImage(skipped_raw)
      except Exception as e:
        util.debug(f"Cannot load skipped.png: {e}")

    if DARK_MODE:
      # Main window background
      self.configure(bg="#2e2e2e")

      # Frame background
      style.configure(
        "TFrame",
        background="#2e2e2e",
        borderwidth=1,
        relief="flat"
      )

      # Label styling
      style.configure(
        "TLabel", 
        background="#2e2e2e", 
        foreground="#ffffff"
      )

      # Button styling
      style.configure(
        "TButton",
        background="#3e3e3e",
        foreground="#ffffff",
        bordercolor="#555555",
        relief="flat",
        borderwidth=1
      )
      style.map(
        "TButton",
        background=[("active", "#555555")],
        foreground=[("active", "#ffffff")]
      )

      # Entry styling
      style.configure(
        "TEntry",
        fieldbackground="#3e3e3e",
        foreground="#ffffff",
        insertcolor="#ffffff",
        bordercolor="#2e2e2e",
        relief="flat"
      )

      # Scrollbar styling
      style.configure(
        "Vertical.TScrollbar",
        background="#3e3e3e",
        troughcolor="#2e2e2e",
        bordercolor="#2e2e2e",
        arrowcolor="#ffffff",
        borderwidth=0,
        relief="flat"
      )
      style.map(
        "Vertical.TScrollbar",
        background=[("active", "#555555"), ("!disabled", "#3e3e3e")],
        arrowcolor=[("active", "#ffffff"), ("!disabled", "#ffffff")]
      )
      style.layout("Vertical.TScrollbar", [
        ("Vertical.Scrollbar.trough", {"sticky": "nswe"}),
        ("Vertical.Scrollbar.thumb",  {"sticky": "nswe"}),
      ])

      self.loading_label.configure(background="#2e2e2e", foreground="#62afff")
      self.last_refresh_label.configure(background="#2e2e2e", foreground="#62afff")

      self.tree.tag_configure("success_tag", foreground="#9cff9c")  # pastel green
      self.tree.tag_configure("fail_tag", foreground="#ff8080")     # pastel red
      self.tree.tag_configure("skipped_tag", foreground="#cccccc")  # lighter gray

    # Check for cached JSON at startup
    if os.path.exists(CACHE_FILE):
      util.debug("Cached tree file found. Loading from JSON...")
      mtime = os.path.getmtime(CACHE_FILE)
      age_in_seconds = time.time() - mtime
      if self.load_tree_from_json(CACHE_FILE):
        util.debug(f"age_in_seconds: {age_in_seconds}")
        if age_in_seconds >= CACHE_REFRESH_SECONDS:
          self.loaded = True
          self.refresh_groups(save_json=True)
      else:
        self.load_root_group()
    else:
      # If no cache, load root group from GitLab
      self.load_root_group()

    # Create a Menu for right-click actions
    self.group_menu = tk.Menu(self, tearoff=0)
    self.group_menu.add_command(label="Refresh", command=self.menu_refresh_group)
    self.group_menu.add_command(label="Open in Browser", command=self.menu_open_in_browser)

    self.project_menu = tk.Menu(self, tearoff=0)
    self.project_menu.add_command(label="Refresh", command=self.menu_refresh_project)
    self.project_menu.add_command(label="Open in Browser", command=self.menu_open_in_browser)
    self.project_menu.add_separator()
    self.project_menu.add_command(label="Retry Pipeline", command=self.menu_retry_pipeline)
    self.project_menu.add_command(label="Create Pipeline", command=self.menu_create_pipeline)

    # Start the refresh loop
    util.execute_after_delay(REFRESH_RATE_SECONDS, self.refresh_loop)

    self.loaded = True
    
  # -------------------------------------------------------------------------
  #  UI functionalities
  # -------------------------------------------------------------------------

  def set_dark_title_bar(self, hwnd):
    """
    Attempt to enable Windows 10/11 dark title bar on a given hwnd.
    Only works on newer Windows builds that support the 'immersive dark mode' attribute.
    """
    if sys.platform == "win32":
      rendering_policy = ctypes.c_int(1)  # 1 = enabled, 0 = disabled
      dwmapi.DwmSetWindowAttribute(
        ctypes.c_void_p(hwnd),
        ctypes.c_uint(DWMWA_USE_IMMERSIVE_DARK_MODE),
        ctypes.byref(rendering_policy),
        ctypes.sizeof(rendering_policy)
      )

  def try_dark_title_bar(self):
    """
    Get the underlying Win32 HWND for this Tk window, then call set_dark_title_bar.
    """
    # On Windows, .winfo_id() returns the HWND for the root window in Python 3.x
    if sys.platform == "win32":
      hwnd = self.winfo_id()
      self.set_dark_title_bar(hwnd)

  def build_top_panel(self):
    self.overrideredirect(True)

    self.title_bar = tk.Frame(self, bg="#2e2e2e" if DARK_MODE else None, height=32)
    self.title_bar.pack(fill="x")

    # A label to show your window's title (or icons, etc.)
    self.title_label = tk.Label(
      self.title_bar,
      text=APP_NAME,
      bg="#2e2e2e" if DARK_MODE else None,
      fg="#ffffff" if DARK_MODE else "#000000",
    )
    self.title_label.pack(side="left", padx=10)

    # A close button on the right side
    self.close_button = tk.Button(
      self.title_bar,
      text=" X ",
      bg="#2e2e2e" if DARK_MODE else "#ff0000",
      fg="#ffffff" if DARK_MODE else "#000000",
      bd=0,
      command=self.on_close
    )
    self.close_button.pack(side="right", padx=5)

    # (Optional) Minimize button example
    self.min_button = tk.Button(
      self.title_bar,
      text="_",
      bg="#2e2e2e" if DARK_MODE else "#00ff00",
      fg="#ffffff" if DARK_MODE else "#000000",
      bd=0,
      command=self.on_minimize
    )
    self.min_button.pack(side="right", padx=5)

    # Bind mouse events so we can drag the window around
    self.title_bar.bind("<Button-1>", self.start_move)
    self.title_bar.bind("<B1-Motion>", self.on_move)

  # -------------------------------------------------------------------------
  #  Core functionalities
  # -------------------------------------------------------------------------
  
  def start_move(self, event):
    """
    Remember the mouse offset so we can move the window
    relative to the current position.
    """
    self._offsetx = event.x
    self._offsety = event.y

  def on_move(self, event):
    """
    Move the window by the mouse delta.
    """
    x = self.winfo_x() + (event.x - self._offsetx)
    y = self.winfo_y() + (event.y - self._offsety)
    self.geometry(f"+{x}+{y}")

  def on_close(self):
    """
    Handler for the close button.
    """
    # I need to signal a close the same way windows or linux does
    self.event_bus.publish("on_close")

  def on_minimize(self):
    """
    Minimal example of how to 'iconify' (minimize) a window.
    Note that because we used overrideredirect(True),
    you won't see it as a typical icon on the taskbar in some OSes.
    """
    self.iconify()
  
  def refresh_loop(self):
    """Start a refresh loop that runs every REFRESH_RATE_SECONDS."""
    self.refresh_groups()
    util.execute_after_delay(REFRESH_RATE_SECONDS, self.refresh_loop)

  def show_notification(self, title, message, duration=5):
    """
    Display a system notification with the given title and message.
    """
    util.debug(f"Showing notification: {title}|{message}")
    self.notification.show(title, message, duration, threaded=True)

  def on_notification_dismissed(self, args):
    """
    Callback when a notification is dismissed.
    """
    sender = args.sender
    reason = args.reason
    util.debug(f"Notification dismissed {sender}: {reason}")
    util.debug(f"Notifications current: {len(self.notifications)}")
    #self.notifications.remove(sender)
    util.debug(f"Notifications remaining: {len(self.notifications)}")

  def on_token_enterkey(self):
    """Handler for pressing Enter in the token entry field."""
    token_clean = self.token_var.get().strip()
    util.debug(f"Trying to save token")
    if token_clean is None or len(token_clean) == 0:
      messagebox.showerror("Error", "Please provide a valid token.")
      return

    if util.get_env_var("GITLAB_TOKEN") != token_clean:
      token = token_clean
      if token:
        util.debug("Token entered. Loading root group.")
        util.set_env_var('GITLAB_TOKEN', token)
        self.load_root_group()
      else:
        messagebox.showerror("Error", "Please provide a valid token.")

  def load_root_group(self):
    """Fetch the root group from GitLab and populate the tree."""
    util.debug("load_root_group called.")
    self.tree.delete(*self.tree.get_children())
    token = self.token_var.get().strip()
    if not token:
      messagebox.showerror("Error", "Please provide a valid token.")
      util.debug("No token provided. Aborting load_root_group.")
      return

    # Show "Loading..." label
    self.loading_label.config(text="Loading root group...")
    self.update_idletasks()

    try:
      util.debug(f"Getting group ID for {GROUP_NAME}.")
      gid = self.get_group_id(token, GROUP_NAME)
      util.debug(f"Root group ID is {gid}. Inserting into tree.")
      root_node = self.tree.insert(
        "",
        "end",
        text=f"Group: {GROUP_NAME}",
        values=(gid, "group", "unfetched", "", ""),  # (id, type, fetched-status, web_url)
        open=False
      )
      # Dummy child so we can expand
      self.tree.insert(root_node, "end", text="Loading...")
    except Exception as ex:
      util.debug(f"Error loading root group: {ex}")
      messagebox.showerror("Error", str(ex))
    finally:
      # Hide loading label
      self.loading_label.config(text="")

  def on_tree_open(self, event):
    """Handler triggered when user expands a node in the TreeView."""
    if not self.loaded:
      util.debug("on_tree_open: Not loaded yet")
      return

    util.debug("Tree node expanded.")
    item_id = self.tree.focus()
    vals = self.tree.item(item_id, "values")
    if len(vals) < 3:
      util.debug(f"on_tree_open: Node has insufficient values to process. ({vals})")
      return
    node_type = vals[1]
    status_flag = vals[2]
    if node_type == "group":
      if status_flag == "unfetched":
        util.debug(f"Expanding a group node that hasn't been fetched yet ({item_id}).")
        self.fetch_subgroups_and_projects(item_id, vals[0])
      elif status_flag == "refresh":
        util.debug("Refreshing a group node.")
        self.refresh_all_project_pipelines_below(item_id)

      util.execute_after_delay(0.05, self.save_tree_to_json)

  def on_tree_close(self, event):
    """Handler triggered when user collapses a node in the TreeView."""
    if not self.loaded:
      util.debug("on_tree_close: Not loaded yet")
      return
    
    util.debug("Tree node collapsed.")
    self.save_tree_to_json()

  def on_tree_double_click(self, event):
    """
    Callback for double-click on a Treeview row.
    """
    # Identify which row was double-clicked
    item_id = self.tree.focus()
    
    if not item_id:
      return  # No valid item was clicked

    # You can get the row text or values. For example:
    row_text = self.tree.item(item_id, "text")
    row_values = self.tree.item(item_id, "values")

    # row_values is typically (id, type, pipeline_status) from your code
    if len(row_values) < 2:
      return
    
    node_type = row_values[1]
    
    if node_type == "project":
      pipeline = row_values[5]
      webbrowser.open(row_values[3] + "/-/pipelines" + ("/" + str(pipeline) if pipeline else ""))
  
  def on_tree_right_click(self, event):
    """
    Handler for right-click in the Treeview: 
    1) Select the clicked row. 
    2) Show the context menu.
    """
    # Identify the row under the pointer
    row_id = self.tree.identify_row(event.y)
    if not row_id:
      return  # clicked outside rows
    
    util.debug(f"Right-clicked row ID: {row_id}")
    
    row_values = self.tree.item(row_id, "values")
    if len(row_values) < 2:
      return
    
    util.debug(f"Row values: {row_values}")
    
    node_type = row_values[1]

    # Select the row so it's highlighted
    self.tree.selection_set(row_id)
    self.tree.focus(row_id)

    # Store the "current" item in some attribute if you want
    self.current_item_id = row_id

    if node_type == "project":
      self.project_menu.tk_popup(event.x_root, event.y_root)
    elif node_type == "group":
      self.group_menu.tk_popup(event.x_root, event.y_root)

  def get_single_project_pipeline_info(self, token, group_id, project):
    """
    Common logic to fetch the pipeline status for a single project.
    'project' can be a GitLab project dict with at least:
      {
        "id": <project_id>,
        "web_url": "...",
        "name": "...",
        ...
      }
    Returns (pstatus, pweb, pref, pipeline_id).

    If you have branches configured in BRANCHES for that group_id,
    it tries get_branches_pipeline_status; otherwise get_latest_pipeline_status.
    """
    pid = project["id"]
    pweb = project.get("web_url", "")
    pname = project.get("name", "")
    
    # Check if we have custom branches
    branches = BRANCHES.get(str(group_id), None)
    if branches:
      pstatus, pref, pipeline_id = self.get_branches_pipeline_status(token, pid, branches)
    else:
      # Call get_latest_pipeline_status with optional branch=None
      pstatus, pref, pipeline_id = self.get_latest_pipeline_status(token, pid, None)

    return (pstatus, pweb, pref, pipeline_id)


  def fetch_pipeline_info_for_projects(self, token, group_id, projects):
    """
    Common logic to gather pipeline info for multiple projects at once.
    Returns a *sorted* list of (project, pstatus, pweb, pref, pipeline_id),
    with failed/canceled first, then success/manual, etc.
    """
    projects_with_status = []

    for proj in projects:
      # Use the single-project helper above
      pstatus, pweb, pref, pipeline_id = self.get_single_project_pipeline_info(token, group_id, proj)

      if pstatus == "No pipeline found":
        # Decide if you want to *skip* these or still include them
        # For now, we'll skip them just like in your original code
        continue

      projects_with_status.append((proj, pstatus, pweb, pref, pipeline_id))

    # Define priority so failed/canceled appear first
    def get_priority(status: str):
      ps_lower = status.lower()
      if ps_lower in ("running", "pending"):
        return 0
      elif ps_lower in ("failed", "canceled"):
        return 1
      elif ps_lower in ("success", "manual"):
        return 2
      else:
        # for "skipped", etc.
        return 3

    # Sort by priority
    projects_with_status.sort(key=lambda x: get_priority(x[1]))

    return projects_with_status

  def fetch_subgroups_and_projects(self, tree_item_id, group_id):
    """Fetch child subgroups/projects for a group, removing any dummy children."""
    # Show loading label
    self.loading_label.config(text="Loading subgroups and projects...")
    self.update_idletasks()

    try:
      util.debug(f"Fetching subgroups/projects for group_id={group_id}. Removing dummy child.")
      for child in self.tree.get_children(tree_item_id):
        self.tree.delete(child)

      old_vals = list(self.tree.item(tree_item_id, "values"))
      node_id = old_vals[0]
      old_vals[2] = "fetched"
      old_status = old_vals[2]
      # Mark it as 'fetched' now
      self.tree.item(tree_item_id, values=tuple(old_vals))
      

      token = self.token_var.get().strip()
      util.debug("Getting subgroups.")
      subgroups = self.get_subgroups(token, group_id)
      util.debug("Getting projects.")
      projects = self.get_group_projects(token, group_id)

      util.debug(f"Found {len(subgroups)} subgroups and {len(projects)} projects in group {group_id}.")

      group_name = self.tree.item(tree_item_id, "text").replace("Group: ", "")
      util.debug(f"Group name: {group_name}")

      # --------------------------------------------------------------------
      # Insert subgroups (unmodified):
      # --------------------------------------------------------------------
      for sg in subgroups:
        sid = sg["id"]
        if str(sid) in IGNORED_GROUPS:
          util.debug(f"Ignoring group {sid}.")
          continue
        sname = sg["full_name"].replace(f"{group_name} / ", "")
        sweb = sg.get("web_url", "")
        sub_node_id = self.tree.insert(
          tree_item_id,
          "end",
          text=f"Group: {sname}",
          values=(sid, "group", "unfetched", sweb, group_name),
          open=False
        )
        # Insert a dummy child so it can be expanded
        self.tree.insert(sub_node_id, "end", text="Loading...")

      # --------------------------------------------------------------------
      # Build a list of (project, pipeline_status), then sort so failed
      # pipelines appear at the top.
      # --------------------------------------------------------------------
      projects_with_status = self.fetch_pipeline_info_for_projects(token, group_id, projects)

      # --------------------------------------------------------------------
      # Now insert the projects in sorted order
      # --------------------------------------------------------------------
      for proj, pstatus, pweb, pref, pipeline in projects_with_status:
        pid = proj["id"]
        pname = proj["name"]
        pname_clean = pname.split(" Project: ", 1)[-1].split(" (")[0].strip()
        ps_lower = pstatus.lower()

        if old_status != pstatus:
          # Fire event on change
          self.event_bus.publish(
            "pipeline_status_changed",
            project_id=node_id,
            project_name=pname_clean,
            old_status=old_status,
            new_status=pstatus
          )

        icon = None
        tag = ""
        if ps_lower in ("success", "manual"):
          icon = self.success_img
          tag = "success_tag"
        elif ps_lower in ("failed", "canceled"):
          icon = self.failed_img
          tag = "fail_tag"
        elif ps_lower in ("skipped", "running", "pending"):
          icon = self.skipped_img
          tag = "skipped_tag"

        text = f" Project: {pname} ({pstatus})" # - Pipeline: {pstatus}
        util.debug(f"Inserting project node with text='{text}'.")

        self.tree.insert(
          tree_item_id,
          "end",
          text=text,
          image=icon,
          values=(pid, "project", pstatus, pweb, pref, pipeline, pname),
          tags=(tag,)
        )

    except Exception as e:
      util.debug(f"Error fetching subgroups/projects: {e}")
      messagebox.showerror("Error", str(e))
      raise e
    finally:
      # Hide loading label
      self.loading_label.config(text="")

  def refresh_project(self, item_id, save_json=False):
    """Refresh the clicked project node."""
    values = self.tree.item(item_id, "values")
    if len(values) < 4:
      # Not enough data (id, type, status, web_url, branch, pipeline_id)
      util.debug(f"refresh_project: Node {item_id} has insufficient values to process. ({values})")
      return

    node_id = values[0]
    node_type = values[1]

    if node_type == "project":
      old_status = values[2]
      util.debug(f"Refreshing project node {node_id}, old status={old_status}")
      # Build a minimal project dict so we can call our helper method
      pname = self.tree.item(item_id, "text")  
      # "Project: SomeName - Pipeline: X" => we just want "SomeName"
      pname_clean = pname.split(" Project: ", 1)[-1].split(" (")[0].strip()
      
      project = {
        "id": node_id,
        "web_url": values[3],  # existing
        "name": pname_clean
      }

      # If we need the group_id for branches:
      group_id = self.get_parent_group_id(item_id)

      token = self.token_var.get().strip()
      pstatus, pweb, pref, pipeline_id = self.get_single_project_pipeline_info(token, group_id, project)

      if old_status != pstatus:
        # Fire event on change
        self.event_bus.publish(
          "pipeline_status_changed",
          project_id=node_id,
          project_name=pname_clean,
          old_status=old_status,
          new_status=pstatus
        )

      # Determine new icon/tag
      ps_lower = pstatus.lower()
      if ps_lower in ("success", "manual"):
        icon = self.success_img
        tag = "success_tag"
      elif ps_lower in ("failed", "canceled"):
        icon = self.failed_img
        tag = "fail_tag"
      elif ps_lower in ("skipped", "running", "pending"):
        icon = self.skipped_img
        tag = "skipped_tag"
      else:
        icon = ""
        tag = ""

      new_text = f" Project: {pname_clean} ({pstatus})"# - Pipeline: {pstatus}

      # Update the node
      self.tree.item(
        item_id,
        text=new_text,
        image=icon,
        tags=(tag,),
        values=(node_id, "project", pstatus, pweb, pref, pipeline_id, pname_clean)
      )
      
    if save_json:
      util.execute_after_delay(0.05, self.save_tree_to_json)

  def refresh_all_project_pipelines_below(self, parent_id):
    """
    Recursively walk the tree from parent_id.
    If a node is a 'project', re-fetch its pipeline and update the node.
    If a node is a 'group', recurse into its children.
    """
    children = self.tree.get_children(parent_id)

    old_vals = list(self.tree.item(parent_id, "values"))
    old_vals[2] = "fetched"
    # Mark it as 'fetched' now
    self.tree.item(parent_id, values=tuple(old_vals))

    util.debug(f"refresh_all_project_pipelines_below: {parent_id} ({len(children)}) ({old_vals})")

    for child_id in children:
      values = self.tree.item(child_id, "values")
      if len(values) < 4:
        util.debug(f"Node {child_id} has insufficient values to process. ({values})")
        continue

      node_type = values[1]
      if node_type == "project":
        self.refresh_project(child_id)
      elif node_type == "group":
        util.debug(f"Refreshing a group node {child_id}")
        self.refresh_all_project_pipelines_below(child_id)

  def get_parent_group_id(self, item_id):
    """
    Walk upwards until we find a parent node whose 'type' is 'group',
    then return that group's ID (as string).
    """
    parent = self.tree.parent(item_id)
    while parent:
      vals = self.tree.item(parent, "values")
      if len(vals) >= 2 and vals[1] == "group":
        # The group's ID is vals[0]
        return str(vals[0])
      parent = self.tree.parent(parent)
    return ""

  # -------------------------------------------------------------------------
  #  Cache / JSON save & load
  # -------------------------------------------------------------------------

  def save_tree_to_json(self, filename=CACHE_FILE):
    """Save the entire tree structure to JSON, including open/closed states
    and pipeline statuses."""
    if not self.loaded:
      return

    util.debug(f"Saving tree structure to {filename}...")
    # Build a recursive structure from the root items
    root_items = self.tree.get_children("")
    data_list = [self.build_node_dict(item_id) for item_id in root_items]

    with open(filename, "w", encoding="utf-8") as f:
      json.dump(data_list, f, indent=2)

  def build_node_dict(self, item_id):
    """Recursively build a dictionary describing this node and its children."""
    item_text = self.tree.item(item_id, "text")
    if item_text == "Loading...":
      return None
    
    item_values = self.tree.item(item_id, "values")  # tuple: (id, type, status, web_url, branch)
    is_open = self.tree.item(item_id, "open")
    util.debug(f"Building node dict for {item_text} is_open={bool(is_open)}")

    node_data = {
      "text": item_text,
      "values": list(item_values),
      "is_open": bool(is_open),
      "children": []
    }

    # Recurse into children
    children_ids = self.tree.get_children(item_id)
    for cid in children_ids:
      child_node = self.build_node_dict(cid)
      if child_node:
        node_data["children"].append(child_node)

    return node_data

  def load_tree_from_json(self, filename=CACHE_FILE):
    """Load the entire tree from a JSON file and rebuild the TreeView."""
    util.debug(f"Loading tree structure from {filename}...")

    # Clear any existing tree items
    self.tree.delete(*self.tree.get_children())

    try:
      with open(filename, "r", encoding="utf-8") as f:
        data_list = json.load(f)
    except Exception as e:
      util.debug(f"Could not load {filename}: {e}")
      messagebox.showerror("Error", f"Could not load {filename}: {e}")
      return False

    # Rebuild the tree
    for node_data in data_list:
      self.insert_node_from_dict("", node_data)

    return True

  def insert_node_from_dict(self, parent_id, node_data):
    """Recursively insert a node and its children from a node_data dict."""
    # node_data is something like:
    # {
    #   "text": "...",
    #   "values": [...],
    #   "is_open": True/False,
    #   "children": [...]
    # }

    text = node_data.get("text", "Unknown")
    vals = node_data.get("values", [])
    is_open = node_data.get("is_open", False)
    children = node_data.get("children", [])

    # Check length of vals:
    # Expect: [some_id, "group"/"project", pipeline_status_or_flag]
    if len(vals) < 2:
      # This means we can't safely do vals[1]
      # You can skip, or you can default them:
      util.debug(f"Warning: Node '{text}' has invalid 'values': {vals}. Skipping or using defaults.")
      # For example, skip entirely:
      return

    node_id = vals[0]
    node_type = vals[1]  # "group" or "project"

    # If there's a third item, treat it as pipeline status; else use empty string
    pipeline_status = vals[2] if len(vals) >= 3 else ""

    # Decide if we should show an icon or color tag
    icon = None
    tags = ()
    if node_type == "project":
      ps_lower = pipeline_status.lower()
      if ps_lower in ("success", "manual"):
        icon = self.success_img
        tags = ("success_tag",)
      elif ps_lower in ("failed", "canceled"):
        icon = self.failed_img
        tags = ("fail_tag",)
      elif ps_lower in ("skipped", "running", "pending"):
        icon = self.skipped_img
        tags = ("skipped_tag",)

    # Build insert kwargs
    insert_kwargs = {
      "text": text,
      "values": tuple(vals),
      "tags": tags
    }
    if icon is not None:
      insert_kwargs["image"] = icon

    # Insert the node (do NOT include open=... here)
    item_id = self.tree.insert(parent_id, "end", **insert_kwargs)

    # Now set open state
    util.debug(f"Node {text} is_open={bool(is_open)}")
    self.tree.item(item_id, open=bool(is_open))

    if node_type == "group":
      if not children or len(children) == 0:
        # No children, just insert this node
        self.tree.insert(item_id, "end", text="Loading...")

    # Recurse into children
    for child_data in children:
      self.insert_node_from_dict(item_id, child_data)

  def refresh_groups(self, save_json=True):
    """
    After loading from JSON, this method finds all group nodes that
    are 'open' and re-fetches them from GitLab, so the 'currently
    showing' projects are refreshed.
    """
    util.debug("Refreshing open group nodes from GitLab...")
    self.loading_label.config(text="Refreshing groups...")
    self.update_idletasks()
    root_items = self.tree.get_children("")
    for item_id in root_items:
      util.debug(f"refresh_groups: Refreshing {item_id}")
      self.refresh_group(item_id)

    self.loading_label.config(text="")

    # Record the time we finished the refresh
    now = time.strftime("%Y-%m-%d %I:%M:%S %p")
    self.last_refresh_label.config(text=f"Last refresh: {now}")

    if save_json:
      util.execute_after_delay(0.05, self.save_tree_to_json)

  def refresh_group(self, item_id, save_json=False):
    """Recursively refresh this group if it is open, then check children."""
    is_open = self.tree.item(item_id, "open")
    text = self.tree.item(item_id, "text")
    children = self.tree.get_children(item_id)
    vals = list(self.tree.item(item_id, "values"))
    if len(vals) < 4:
      return

    node_id = vals[0]
    node_type = vals[1]

    if node_type == "group":
      # Re-fetch from GitLab (this will delete old children and insert fresh ones)
      if not children or len(children) == 0:
        self.tree.insert(item_id, "end", text="Loading...")
      elif bool(is_open):
        self.refresh_all_project_pipelines_below(item_id)
      else:
        vals[2] = "refresh"
        self.tree.item(item_id, values=tuple(vals))
    else:
      # If it's not an open group, just recurse to children
      # (In case you have subgroups under projects, typically not, but just in case)
      for child_id in self.tree.get_children(item_id):
        self.refresh_group(child_id)

    if save_json:
      util.execute_after_delay(0.05, self.save_tree_to_json)

  # -------------------------------------------------------------------------
  #  GitLab helpers
  # -------------------------------------------------------------------------

  def get_group_id(self, token, group_name):
    util.debug("get_group_id called.")
    if group_name.isdigit():
      util.debug("Group name is numeric, using directly.")
      return group_name
    headers = {"Private-Token": token}
    r = requests.get(f"{GITLAB_API_URL}/groups", headers=headers, params={"search": group_name})
    r.raise_for_status()
    groups = r.json()
    util.debug(f"{len(groups)} groups returned from search.")
    for g in groups:
      # Compare either 'name' or 'path' to group_name, ignoring case
      if g["name"].lower() == group_name.lower() or g["path"].lower() == group_name.lower():
        util.debug(f"Matched group ID {g['id']}.")
        return g["id"]
    raise ValueError(f"Group not found: {group_name}")

  def get_subgroups(self, token, group_id):
    util.debug(f"get_subgroups called for group_id={group_id}.")
    headers = {"Private-Token": token}
    subgroups = []
    page = 1
    while True:
      r = requests.get(
        f"{GITLAB_API_URL}/groups/{group_id}/subgroups",
        headers=headers,
        params={"page": page, "per_page": 100}
      )
      r.raise_for_status()
      data = r.json()
      if not data:
        util.debug("No more subgroups found.")
        break
      util.debug(f"Found {len(data)} subgroups on page {page}.")
      subgroups.extend(data)
      page += 1
    return subgroups

  def get_group_projects(self, token, group_id):
    util.debug(f"get_group_projects called for group_id={group_id}.")
    headers = {"Private-Token": token}
    projects = []
    page = 1
    while True:
      r = requests.get(
        f"{GITLAB_API_URL}/groups/{group_id}/projects",
        headers=headers,
        params={"page": page, "per_page": 100, "include_subgroups": "false"}
      )
      r.raise_for_status()
      page_projects = r.json()
      if not page_projects:
        util.debug("No more projects on this page.")
        break
      util.debug(f"Found {len(page_projects)} projects on page {page}.")
      projects.extend(page_projects)
      page += 1
    return projects
  
  def get_branches_pipeline_status(self, token, project_id, branches):
    for branch in branches:
      status, ref, pipeline_id = self.get_latest_pipeline_status(token, project_id, branch)

      if pipeline_id != "":
        util.debug(f"Branch {branch} status: {status}")
        return status, ref, pipeline_id

    return "No pipeline found", "", ""

  def get_latest_pipeline_status(self, token, project_id, branch=None):
    """
    Returns the status of the pipeline that truly finished last,
    among the specified branches.
    """
    headers = {"Private-Token": token}

    params = {}
    if branch:
      util.debug(f"Getting latest pipeline for branch {branch}.")
      params["ref"] = branch
    
    r = requests.get(
      f"{GITLAB_API_URL}/projects/{project_id}/pipelines/latest",
      headers=headers,
      params=params
    )

    try:
      r.raise_for_status()
    except requests.exceptions.HTTPError as e:
      if r.status_code in (403, 404):
        return "No pipeline found", "", ""
      else:
        raise e

    pipeline = r.json()
    if not pipeline:
      return "No pipeline found", "", ""
  
    #util.debug(f"Latest pipeline: {pipeline}")
    return pipeline["status"], pipeline["ref"], pipeline["id"]
    
  def retry_pipeline(self, token, project_id, pipeline_id):
    headers = {"Private-Token": token}
    url = f"{GITLAB_API_URL}/projects/{project_id}/pipelines/{pipeline_id}/retry"
    r = requests.post(url, headers=headers)
    r.raise_for_status()
    return r.json()
  
  def create_pipeline(self, token, project_id, ref="development"):
    headers = {"Private-Token": token}
    data = {"ref": ref}
    url = f"{GITLAB_API_URL}/projects/{project_id}/pipeline"
    r = requests.post(url, headers=headers, json=data)
    r.raise_for_status()
    return r.json()
  
  def menu_create_pipeline(self):
    """Create a new pipeline (e.g. on 'main') for the clicked project."""
    if not hasattr(self, "current_item_id"):
      return
    row_id = self.current_item_id

    row_values = self.tree.item(row_id, "values")
    if len(row_values) < 4:
      return

    project_id = row_values[0]
    node_type = row_values[1]
    branch = row_values[4]

    if node_type != "project":
      messagebox.showinfo("Not a Project", "This menu action only applies to projects.")
      return

    # For demonstration, let's always create a pipeline on 'main'
    try:
      created = self.create_pipeline(self.token_var.get(), project_id, branch)
      new_pid = created.get("id")
      #messagebox.showinfo("Pipeline Created", f"New pipeline (ID={new_pid}) on '{branch}'")
      self.show_notification("Pipeline Created", f"New pipeline (ID={new_pid}) on '{branch}'")
    except Exception as e:
      messagebox.showerror("Error", str(e))

  def menu_retry_pipeline(self):
    """Retry the last pipeline for the clicked project (if possible)."""
    if not hasattr(self, "current_item_id"):
      return
    row_id = self.current_item_id

    row_values = self.tree.item(row_id, "values")
    # e.g. (project_id, "project", "failed", "https://gitlab.com/...", pipeline_id)
    util.debug(f"Row values: {row_values}")
    if len(row_values) < 5:
      messagebox.showerror("Error", "Cannot retry pipeline: not enough info stored.")
      return
    
    project_id = row_values[0]
    node_type = row_values[1]
    pipeline_id = row_values[5]
    project_name = row_values[6]

    if node_type != "project":
      messagebox.showinfo("Not a Project", "This menu action only applies to projects.")
      return

    # Here use a helper function to call GitLab's /retry endpoint
    try:
      util.debug(f"Retrying pipeline {pipeline_id} for project {project_name} ({project_id}).")
      info = self.retry_pipeline(self.token_var.get(), project_id, pipeline_id)
      #util.debug(f"Retry info: {info}")
      #messagebox.showinfo("Retry Successful", f"Pipeline {pipeline_id} for project '{project_name}' was retried.")
      self.show_notification(f"Retrying Pipeline", f"Pipeline {pipeline_id} retried for '{project_name}'.")
      
      util.execute_after_delay(3, self.refresh_project, row_id, save_json=True)
    except Exception as e:
      messagebox.showerror("Error", str(e))
  
  def menu_open_in_browser(self):
    """Open the clicked row's GitLab URL in a browser."""
    if not hasattr(self, "current_item_id"):
      return
    row_id = self.current_item_id

    row_values = self.tree.item(row_id, "values")
    if len(row_values) < 3:
      return

    node_type = row_values[1]
    web_url = row_values[3]
    
    if node_type == "group":
      if web_url:
        webbrowser.open(web_url)
      else:
        messagebox.showinfo("No URL", "This item does not have a valid web_url.")
    elif node_type == "project":
      if web_url:
        pipeline = row_values[5]
        util.debug(f"Opening pipeline {pipeline} for project {row_values[0]} in browser.")
        if pipeline:
          webbrowser.open(web_url + "/-/pipelines/" + str(pipeline))
        else:
          webbrowser.open(web_url + "/-/pipelines")
      else:
        messagebox.showinfo("No URL", "This item does not have a valid web_url.")

  def menu_refresh_group(self):
    """Refresh the clicked group node."""
    if not hasattr(self, "current_item_id"):
      return
    row_id = self.current_item_id

    row_values = self.tree.item(row_id, "values")
    if len(row_values) < 2:
      return
    
    row_text = self.tree.item(row_id, "text")
    self.loading_label.config(text=f"Refreshing {row_text}...")
    self.update_idletasks()

    node_type = row_values[1]
    if node_type == "group":
      self.refresh_group(row_id, save_json=True)

    self.loading_label.config(text="")

  def menu_refresh_project(self):
    """Refresh the clicked project node."""
    if not hasattr(self, "current_item_id"):
      return
    row_id = self.current_item_id

    row_values = self.tree.item(row_id, "values")
    if len(row_values) < 2:
      return

    row_text = self.tree.item(row_id, "text")
    self.loading_label.config(text=f"Refreshing {row_text}...")
    self.update_idletasks()

    node_type = row_values[1]
    if node_type == "project":
      self.refresh_project(row_id, save_json=True)

    self.loading_label.config(text="")

  def on_closing(self):
    """Handler for the window close event."""
    try:
      util.debug("main app: on_closing called.")
      util.cancel_delay_timers()
      self.notification.shutdown()
      self.destroy()
    except Exception as e:
      util.debug(f"Error in on_closing: {e}")

# -----------------------------------------------------------------------------

def main():
  loop = asyncio.get_event_loop()
  app = TrayApp(PipelineCheckerApp(event_loop=loop))
  app.run()

if __name__ == "__main__":
  try:
    main()
  except KeyboardInterrupt:
      print("Application interrupted by user.")
