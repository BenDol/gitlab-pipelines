import sys
import threading
import asyncio
import pystray
from pystray import MenuItem as item
import tkinter as tk
from PIL import Image

# internal imports
import util

class TrayAppBase:
  def __init__(self, app, icon_path="assets/images/logo"):
    # Create the Tkinter window
    self.root = app
    self.root.event_bus.subscribe("on_close", self.on_closing)
    self.event_loop = app.event_loop or asyncio.get_event_loop()
    self.icon_path = icon_path
    self.closed = False

    # By default, keep the window visible
    self.is_hidden = False

    # Create the system tray icon in a separate thread
    # because pystray needs a "run loop" of its own.
    self.icon = None
    self.tray_thread = threading.Thread(target=self.setup_tray_icon, daemon=True)
    self.tray_thread.start()

    self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

  def setup_tray_icon(self):
    util.debug("Setting up tray icon")
    image = Image.open(self.icon_path + ".png")

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
    self.root.show_notification("Minimized to tray", "Click the tray icon to restore.", 2)

  def show_window(self):
    """Show the main window and hide tray icon."""
    if self.icon:
      self.icon.visible = False

    self.is_hidden = False
    self.root.deiconify() # Show the Tk window

  def exit_app(self):
    """Exit app from tray."""
    self.closed = True
    if self.icon:
      self.icon.stop()
    self.root.on_closing()
    # Safely destroy the Tk mainloop
    self.root.quit()
    self.event_loop.stop()

  def on_closing(self):
    """
    When user clicks the window's close button, 
    optionally minimize to tray or fully exit.
    """
    self.hide_window()

  def run(self):
    """Start the Tkinter mainloop and integrate with asyncio."""
    self.root.mainloop()


class TrayAppWin32(TrayAppBase):
  def __init__(self, app, icon_path="assets/images/logo"):
    super().__init__(app, icon_path)


class TrayAppLinux(TrayAppBase):
  def __init__(self, app, icon_path="assets/images/logo"):
    super().__init__(app, icon_path)


if sys.platform.startswith('win'):
  class TrayApp(TrayAppWin32):
    pass
elif sys.platform.startswith('linux'):
  class TrayApp(TrayAppLinux):
    pass
