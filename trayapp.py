import tkinter as tk
import threading
import pystray
from pystray import MenuItem as item
from PIL import Image

class TrayApp:
  def __init__(self, app, icon_path="assets/images/logo.png"):
    # Create the Tkinter window
    self.root = app
    self.icon_path = icon_path

    # Button to minimize to tray
    #tk.Button(self.root, text="Minimize to Tray", command=self.hide_window).pack(pady=20)

    # By default, keep the window visible
    self.is_hidden = False

    # Create the system tray icon in a separate thread
    # because pystray needs a "run loop" of its own.
    self.icon = None
    self.tray_thread = threading.Thread(target=self.setup_tray_icon, daemon=True)
    self.tray_thread.start()

    self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

  def setup_tray_icon(self):
    image = Image.open(self.icon_path)

    # Build a menu for the tray icon
    menu = (
      item(text="Left-Click-Action", action=self.show_window, default=True, visible=False),
      item("Show", self.show_window),
      item("Exit", self.exit_app)
    )

    self.icon = pystray.Icon("tray_icon", image, self.root.title(), menu)
    self.icon.run(self.tray_setup)

  def tray_setup(self, icon):
    """Called just before Icon.run() enters its event loop."""
    icon.visible = True

  def hide_window(self):
    """Hide the main window and show tray icon (if not already)."""
    if self.icon:
      # Show the icon in the tray
      self.icon.visible = True

    self.is_hidden = True
    self.root.withdraw()

  def show_window(self, icon=None, item=None):
    """Show the main window and hide tray icon."""
    if self.icon:
      self.icon.visible = False

    self.is_hidden = False
    self.root.deiconify()  # Show the Tk window

  def exit_app(self, icon=None, item=None):
    """Exit app from tray."""
    if self.icon:
      self.icon.stop()
    # Safely destroy the Tk mainloop
    self.root.quit()

  def on_closing(self):
    """
    When user clicks the window's close button, 
    optionally minimize to tray or fully exit.
    """
    # If you want to ALWAYS go to tray instead of closing:
    self.hide_window()
    # If you want to exit instead:
    # self.exit_app()

  def run(self):
    self.root.mainloop()
