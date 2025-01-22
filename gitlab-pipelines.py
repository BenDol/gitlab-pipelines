import tkinter as tk
from tkinter import ttk, messagebox
import requests
import os

# Toggle this flag to enable/disable debug logs
DEBUG_ENABLED = True

def debug(message: str):
  """Prints debug messages if DEBUG_ENABLED is True."""
  if DEBUG_ENABLED:
    print(f"[DEBUG] {message}")

GITLAB_API_URL = "https://gitlab.com/api/v4"

# -------------------------------------------------------------------
# Replace with your group name (or group ID).
GROUP_NAME = "insurance-insight"
# -------------------------------------------------------------------

class PipelineCheckerApp(tk.Tk):
  def __init__(self):
    super().__init__()

    self.title("GitLab Pipelines Status - Debug Edition")

    # Frame for input
    input_frame = ttk.Frame(self)
    input_frame.pack(padx=10, pady=10, fill="x")

    # Label for the Token
    ttk.Label(input_frame, text="Personal Access Token:").pack(side="left")

    # Entry for the token
    self.token_var = tk.StringVar()
    # If you prefer, load from environment variable:
    self.token_var.set(os.getenv("GITLAB_TOKEN", ""))
    self.token_entry = ttk.Entry(input_frame, textvariable=self.token_var, width=50, show="*")
    self.token_entry.pack(side="left", padx=5)

    # Button to fetch statuses
    fetch_button = ttk.Button(input_frame, text="Fetch Pipelines", command=self.fetch_and_display_pipelines)
    fetch_button.pack(side="left", padx=5)

    # Frame for results
    results_frame = ttk.Frame(self)
    results_frame.pack(fill="both", expand=True, padx=10, pady=(0,10))

    # Scrollable listbox
    self.listbox = tk.Listbox(results_frame, height=20, width=100)
    self.listbox.pack(side="left", fill="both", expand=True)

    scrollbar = ttk.Scrollbar(results_frame, orient="vertical", command=self.listbox.yview)
    scrollbar.pack(side="right", fill="y")
    self.listbox.config(yscrollcommand=scrollbar.set)

  def fetch_and_display_pipelines(self):
    """Fetches the latest pipeline for each project in the given group (including subgroups)
    and displays them.
    """
    debug("Starting fetch_and_display_pipelines ...")
    
    token = self.token_var.get().strip()
    if not token:
      messagebox.showerror("Error", "Please provide a valid GitLab Personal Access Token.")
      debug("No token provided; aborting.")
      return

    # Clear the listbox before inserting new results
    self.listbox.delete(0, tk.END)

    try:
      debug(f"Attempting to get the group ID for: {GROUP_NAME}")
      # 1. Get group ID if the user has provided a group name instead of numeric ID.
      group_id = self.get_group_id(token, GROUP_NAME)
      debug(f"Found group ID: {group_id}")

      # 2. Get all projects in this group (including subgroups)
      debug("Fetching all projects (including subgroups) ...")
      projects = self.get_group_projects(token, group_id)
      debug(f"Total projects found (including subgroups): {len(projects)}")

      # 3. For each project, get the latest pipeline
      if not projects:
        self.listbox.insert(tk.END, "No projects found (including subgroups).")
        debug("No projects found to process.")
      else:
        for project in projects:
          project_id = project["id"]
          project_name = project["name_with_namespace"]
          debug(f"Fetching latest pipeline status for project: {project_name} (ID: {project_id})")
          
          pipeline_status = self.get_latest_pipeline_status(token, project_id)
          
          display_text = f"{project_name}: {pipeline_status}"
          self.listbox.insert(tk.END, display_text)

          debug(f"Pipeline status for {project_name}: {pipeline_status}")

    except requests.exceptions.RequestException as e:
      messagebox.showerror("Request Error", str(e))
      debug(f"Request Error: {e}")
    except Exception as ex:
      messagebox.showerror("Error", str(ex))
      debug(f"General Error: {ex}")

    debug("Finished fetch_and_display_pipelines.")

  def get_group_id(self, token, group_name):
    """
    Returns the numeric group ID from a group name (string) or numeric ID.
    If `group_name` is already numeric, just return it.
    """
    debug("Entered get_group_id()")
    # If group_name is purely digits, assume it's already a group ID:
    if group_name.isdigit():
      debug("group_name is numeric, returning as group ID directly.")
      return group_name

    # Otherwise, search for the group by name
    headers = {"Private-Token": token}
    params = {"search": group_name}
    debug(f"Searching groups endpoint for '{group_name}'...")
    response = requests.get(f"{GITLAB_API_URL}/groups", headers=headers, params=params)
    response.raise_for_status()
    groups = response.json()
    debug(f"Groups returned: {len(groups)} potential matches.")

    for g in groups:
      # Match on either the group name or the path
      if g["name"].lower() == group_name.lower() or g["path"].lower() == group_name.lower():
        debug(f"Match found - group ID: {g['id']}")
        return g["id"]

    raise ValueError(f"Could not find group with name or path: {group_name}")

  def get_group_projects(self, token, group_id):
    """
    Returns a list of projects in the specified group, including subgroups.
    """
    debug(f"Entered get_group_projects() with group_id={group_id}")
    headers = {"Private-Token": token}
    projects = []
    page = 1

    # Paginate to fetch all projects, including subgroups
    while True:
      params = {
        "per_page": 100,
        "page": page,
        "include_subgroups": "true"  # Key param to include subgroups
      }
      debug(f"Requesting projects for page {page} ...")
      response = requests.get(
        f"{GITLAB_API_URL}/groups/{group_id}/projects",
        headers=headers,
        params=params
      )
      response.raise_for_status()
      page_projects = response.json()

      if not page_projects:
        debug("No more projects found on this page, ending pagination.")
        break

      debug(f"Found {len(page_projects)} projects on page {page}.")
      projects.extend(page_projects)
      page += 1

    debug(f"get_group_projects() returning total of {len(projects)} projects.")
    return projects

  def get_latest_pipeline_status(self, token, project_id):
    """
    Returns the status of the latest pipeline for the given project ID,
    or 'No pipelines found' if none exist.
    """
    debug(f"Entered get_latest_pipeline_status() for project_id={project_id}")
    headers = {"Private-Token": token}
    # Get the project’s pipelines (most recent first)
    params = {
      "per_page": 1,
      "order_by": "updated_at",
      "sort": "desc"
    }

    response = requests.get(
      f"{GITLAB_API_URL}/projects/{project_id}/pipelines",
      headers=headers,
      params=params
    )
    response.raise_for_status()
    pipelines = response.json()

    if not pipelines:
      debug("No pipelines found for this project.")
      return "No pipelines found"

    latest_pipeline = pipelines[0]
    status = latest_pipeline["status"]
    debug(f"Latest pipeline ID: {latest_pipeline['id']}, status: {status}")
    return status


if __name__ == "__main__":
  app = PipelineCheckerApp()
  app.mainloop()
