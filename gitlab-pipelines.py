import tkinter as tk
from tkinter import ttk, messagebox
import requests
import os
import json
import pathlib
import threading
import time

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

DEBUG_ENABLED = True
def debug(msg):
  if DEBUG_ENABLED:
    print(f"[DEBUG] {msg}")

GITLAB_API_URL = "https://gitlab.com/api/v4"
GROUP_NAME = "insurance-insight"
CACHE_FILE = "cached_tree.json"

def execute_after_delay(seconds, my_event):
  timer = threading.Timer(seconds, my_event)
  timer.start()
  return timer

class PipelineCheckerApp(tk.Tk):
  def __init__(self):
    super().__init__()
    self.title("GitLab Groups & Pipelines")
    self.minsize(width=690, height=820)

    # Debug print
    debug("Initializing main app window.")
    self.loaded = False

    # Load token from environment
    self.token_var = tk.StringVar()
    self.token_var.set(os.getenv("GITLAB_TOKEN", ""))

    # Increase font and row size in Treeview
    style = ttk.Style(self)
    style.configure("Treeview", font=("Arial", 14), rowheight=30)

    # Top input frame
    input_frame = ttk.Frame(self)
    input_frame.pack(padx=10, pady=10, fill="x")

    ttk.Label(input_frame, text="Personal Access Token:").pack(side="left")
    self.token_entry = ttk.Entry(input_frame, textvariable=self.token_var, width=50, show="*")
    self.token_entry.pack(side="left", padx=5)

    load_button = ttk.Button(input_frame, text="Reset Groups", command=self.load_root_group)
    load_button.pack(side="left", padx=5)

    # Button to save tree to JSON
    #save_button = ttk.Button(input_frame, text="Save Tree to JSON", command=self.save_tree_to_json)
    #save_button.pack(side="left", padx=5)

    # Tree frame
    tree_frame = ttk.Frame(self)
    tree_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    self.tree = ttk.Treeview(tree_frame)
    self.tree.pack(side="left", fill="both", expand=True)

    scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
    scrollbar.pack(side="right", fill="y")
    self.tree.config(yscrollcommand=scrollbar.set)

    self.tree.bind("<<TreeviewOpen>>", self.on_tree_open)
    self.tree.bind("<<TreeviewClose>>", self.on_tree_close)

    # A label at the bottom to indicate "Loading..."
    self.loading_label = ttk.Label(self, text="", foreground="blue")
    self.loading_label.pack(side="bottom", pady=5)

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
        debug("Loading success.png.")
        success_raw = Image.open("assets/images/success.png")
        if RESAMPLE:
          success_raw = success_raw.resize((20, 20), RESAMPLE)
        else:
          success_raw = success_raw.resize((20, 20), Image.ANTIALIAS)
        self.success_img = ImageTk.PhotoImage(success_raw)
      except Exception as e:
        debug(f"Cannot load success.png: {e}")

      try:
        debug("Loading failed.png.")
        failed_raw = Image.open("assets/imagesfailed.png")
        if RESAMPLE:
          failed_raw = failed_raw.resize((20, 20), RESAMPLE)
        else:
          failed_raw = failed_raw.resize((20, 20), Image.ANTIALIAS)
        self.failed_img = ImageTk.PhotoImage(failed_raw)
      except Exception as e:
        debug(f"Cannot load failed.png: {e}")

      try:
        debug("Loading skipped.png.")
        skipped_raw = Image.open("assets/imagesskipped.png")
        if RESAMPLE:
          skipped_raw = skipped_raw.resize((20, 20), RESAMPLE)
        else:
          skipped_raw = skipped_raw.resize((20, 20), Image.ANTIALIAS)
        self.skipped_img = ImageTk.PhotoImage(skipped_raw)
      except Exception as e:
        debug(f"Cannot load skipped.png: {e}")

    # Check for cached JSON at startup
    if os.path.exists(CACHE_FILE):
      debug("Cached tree file found. Loading from JSON...")
      if not self.load_tree_from_json(CACHE_FILE):
        self.load_root_group()
      else:
        # After loading, refresh any group that was open
        self.refresh_open_groups()
    else:
      # If no cache, load root group from GitLab
      self.load_root_group()

    self.loaded = True

  # -------------------------------------------------------------------------
  #  Core functionalities
  # -------------------------------------------------------------------------

  def load_root_group(self):
    """Fetch the root group from GitLab and populate the tree."""
    debug("load_root_group called.")
    self.tree.delete(*self.tree.get_children())
    token = self.token_var.get().strip()
    if not token:
      messagebox.showerror("Error", "Please provide a valid token.")
      debug("No token provided. Aborting load_root_group.")
      return

    # Show "Loading..." label
    self.loading_label.config(text="Loading root group...")
    self.update_idletasks()

    try:
      debug(f"Getting group ID for {GROUP_NAME}.")
      gid = self.get_group_id(token, GROUP_NAME)
      debug(f"Root group ID is {gid}. Inserting into tree.")
      root_node = self.tree.insert(
        "",
        "end",
        text=f"Group: {GROUP_NAME}",
        values=(gid, "group", "unfetched"),  # (id, type, fetched-status)
        open=False
      )
      # Dummy child so we can expand
      self.tree.insert(root_node, "end", text="Loading...")
    except Exception as ex:
      debug(f"Error loading root group: {ex}")
      messagebox.showerror("Error", str(ex))
    finally:
      # Hide loading label
      self.loading_label.config(text="")

  def on_tree_open(self, event):
    """Handler triggered when user expands a node in the TreeView."""
    if not self.loaded:
      debug("on_tree_open: Not loaded yet")
      return

    debug("Tree node expanded.")
    item_id = self.tree.focus()
    vals = self.tree.item(item_id, "values")
    if len(vals) < 3:
      debug("Node has insufficient values to process.")
      return
    node_type = vals[1]
    status_flag = vals[2]
    if node_type == "group":
      if status_flag == "unfetched":
        debug("Expanding a group node that hasn't been fetched yet.")
        self.fetch_subgroups_and_projects(item_id, vals[0])

      execute_after_delay(0.05, self.save_tree_to_json)

  def on_tree_close(self, event):
    """Handler triggered when user collapses a node in the TreeView."""
    if not self.loaded:
      debug("on_tree_close: Not loaded yet")
      return
    
    debug("Tree node collapsed.")
    self.save_tree_to_json()

  def fetch_subgroups_and_projects(self, tree_item_id, group_id):
    """Fetch child subgroups/projects for a group, removing any dummy children."""
    # Show loading label
    self.loading_label.config(text="Loading subgroups and projects...")
    self.update_idletasks()

    try:
      debug(f"Fetching subgroups/projects for group_id={group_id}. Removing dummy child.")
      for child in self.tree.get_children(tree_item_id):
        self.tree.delete(child)

      old_vals = self.tree.item(tree_item_id, "values")
      # Mark it as 'fetched' now
      self.tree.item(tree_item_id, values=(old_vals[0], old_vals[1], "fetched"))

      token = self.token_var.get().strip()
      debug("Getting subgroups.")
      subgroups = self.get_subgroups(token, group_id)
      debug("Getting projects.")
      projects = self.get_group_projects(token, group_id)

      debug(f"Found {len(subgroups)} subgroups and {len(projects)} projects in group {group_id}.")

      # Subgroups
      for sg in subgroups:
        sid = sg["id"]
        sname = sg["full_name"]
        node_id = self.tree.insert(
          tree_item_id,
          "end",
          text=f"Group: {sname}",
          values=(sid, "group", "unfetched"),
          open=False
        )
        # Insert a dummy child so it can be expanded
        self.tree.insert(node_id, "end", text="Loading...")

      # Projects
      for proj in projects:
        pid = proj["id"]
        pnamef = proj["name_with_namespace"]
        pname = proj["name"]
        debug(f"Fetching pipeline for project {pnamef} (ID {pid}).")
        pstatus = self.get_latest_pipeline_status(token, pid)
        if pstatus == "No pipeline found":
          # No pipeline info to show; skip or show text anyway
          continue

        # Decide which icon & tag to use
        icon = None
        tag = ""
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

        text = f"Project: {pname} - Pipeline: {pstatus}"
        debug(f"Inserting project node with text='{text}'.")

        # Insert with image if available, and tag for color
        # We'll store pipeline status in values for reference
        self.tree.insert(
          tree_item_id,
          "end",
          text=text,
          image=icon,
          values=(pid, "project", pstatus),
          tags=(tag,)
        )

    except Exception as e:
      debug(f"Error fetching subgroups/projects: {e}")
      messagebox.showerror("Error", str(e))
    finally:
      # Hide loading label
      self.loading_label.config(text="")

  # -------------------------------------------------------------------------
  #  Cache / JSON save & load
  # -------------------------------------------------------------------------

  def save_tree_to_json(self, filename=CACHE_FILE):
    """Save the entire tree structure to JSON, including open/closed states
    and pipeline statuses."""
    if not self.loaded:
      return

    debug(f"Saving tree structure to {filename}...")
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
    
    item_values = self.tree.item(item_id, "values")  # tuple: (id, type, status)
    is_open = self.tree.item(item_id, "open")
    debug(f"Building node dict for {item_text} is_open={bool(is_open)}")

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
    debug(f"Loading tree structure from {filename}...")

    # Clear any existing tree items
    self.tree.delete(*self.tree.get_children())

    try:
      with open(filename, "r", encoding="utf-8") as f:
        data_list = json.load(f)
    except Exception as e:
      debug(f"Could not load {filename}: {e}")
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
      debug(f"Warning: Node '{text}' has invalid 'values': {vals}. Skipping or using defaults.")
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
      elif ps_lower in ("skipped"):
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
    debug(f"Node {text} is_open={bool(is_open)}")
    self.tree.item(item_id, open=bool(is_open))

    if node_type == "group":
      if not children or len(children) == 0:
        # No children, just insert this node
        self.tree.insert(item_id, "end", text="Loading...")

    # Recurse into children
    for child_data in children:
      self.insert_node_from_dict(item_id, child_data)

  def refresh_open_groups(self):
    """
    After loading from JSON, this method finds all group nodes that
    are 'open' and re-fetches them from GitLab, so the 'currently
    showing' projects are refreshed.
    """
    debug("Refreshing open group nodes from GitLab...")
    root_items = self.tree.get_children("")
    for item_id in root_items:
      self.refresh_group_if_open(item_id)

  def refresh_group_if_open(self, item_id):
    """Recursively refresh this group if it is open, then check children."""
    is_open = self.tree.item(item_id, "open")
    text = self.tree.item(item_id, "text")
    children = self.tree.get_children(item_id)
    vals = self.tree.item(item_id, "values")
    if len(vals) < 3:
      return

    node_id, node_type, status_flag = vals
    debug(f"Refreshing node {node_type}:{node_id} ({text}) is open. Refreshing.")

    if node_type == "group":
      # Re-fetch from GitLab (this will delete old children and insert fresh ones)
      if not children or len(children) == 0:
        self.tree.insert(item_id, "end", text="Loading...")
      elif bool(is_open):
        # After refreshing, get children and see if any sub-groups are also open
        for child_id in children:
          self.refresh_group_if_open(child_id)
    else:
      # If it's not an open group, just recurse to children
      # (In case you have subgroups under projects, typically not, but just in case)
      for child_id in self.tree.get_children(item_id):
        self.refresh_group_if_open(child_id)

  # -------------------------------------------------------------------------
  #  GitLab helpers
  # -------------------------------------------------------------------------

  def get_group_id(self, token, group_name):
    debug("get_group_id called.")
    if group_name.isdigit():
      debug("Group name is numeric, using directly.")
      return group_name
    headers = {"Private-Token": token}
    r = requests.get(f"{GITLAB_API_URL}/groups", headers=headers, params={"search": group_name})
    r.raise_for_status()
    groups = r.json()
    debug(f"{len(groups)} groups returned from search.")
    for g in groups:
      # Compare either 'name' or 'path' to group_name, ignoring case
      if g["name"].lower() == group_name.lower() or g["path"].lower() == group_name.lower():
        debug(f"Matched group ID {g['id']}.")
        return g["id"]
    raise ValueError(f"Group not found: {group_name}")

  def get_subgroups(self, token, group_id):
    debug(f"get_subgroups called for group_id={group_id}.")
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
        debug("No more subgroups found.")
        break
      debug(f"Found {len(data)} subgroups on page {page}.")
      subgroups.extend(data)
      page += 1
    return subgroups

  def get_group_projects(self, token, group_id):
    debug(f"get_group_projects called for group_id={group_id}.")
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
        debug("No more projects on this page.")
        break
      debug(f"Found {len(page_projects)} projects on page {page}.")
      projects.extend(page_projects)
      page += 1
    return projects

  def get_latest_pipeline_status(self, token, project_id):
    """
    Returns the status of the pipeline that truly finished last,
    among the specified branches.
    """
    headers = {"Private-Token": token}
    params = {
      # 
    }
    r = requests.get(
      f"{GITLAB_API_URL}/projects/{project_id}/pipelines/latest",
      headers=headers,
      #params=params
    )

    try:
      r.raise_for_status()
    except requests.exceptions.HTTPError as e:
      if r.status_code in (403, 404):
        return "No pipeline found"
      else:
        raise e

    pipeline = r.json()
    if not pipeline:
      return "No pipeline found"
  
    return pipeline["status"]

# -----------------------------------------------------------------------------

if __name__ == "__main__":
  app = PipelineCheckerApp()
  app.mainloop()
