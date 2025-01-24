import time
import subprocess
import sys
import os
import asyncio
import threading
import traceback

# internal imports
import util

util.debug("Loading notification module...")

# Attempt to import the Windows-specific winsdk modules
# so we can gracefully handle environments where they're not available.
try:
  import winsdk_toast.notifier
  from winsdk_toast import Notifier, Toast
  from winsdk_toast.notifier import show as show_async
  from winsdk_toast.event import handle_activated, handle_dismissed, handle_failed
  from winsdk.windows.ui.notifications import ToastNotificationManager
except ImportError as e:
  Notifier = None
  Toast = None

class AsyncNotifier:
  """
  A notifier that creates and uses a dedicated asyncio loop
  in a background thread to avoid blocking the main Tk thread.
  """
  def __init__(self, application_id="MyApp"):
    self.application_id = application_id
    self._ready_event = threading.Event()
    self.loop = asyncio.new_event_loop()
    self.thread = threading.Thread(target=self._loop_thread_main, daemon=True)
    self.thread.start()

  def _loop_thread_main(self):
    """
    Runs in the background thread: set up our own event loop,
    create the ToastNotifier, then run the loop forever.
    """
    try:
      asyncio.set_event_loop(self.loop)
      # Create the COM notifier on *this* thread (important for COM apartment rules).
      self.toast_notifier = ToastNotificationManager.create_toast_notifier(self.application_id)
      # Signal that we're done initializing
      self._ready_event.set()
      # Keep this loop alive so we can schedule tasks at any time
      self.loop.run_forever()
    except Exception as e:
      print("[BackgroundNotifier] ERROR in _loop_thread_main:", e)
      traceback.print_exc()
      # If we fail here, set the event anyway so the main thread won't hang.
      self._ready_event.set()

  def show(self, toast: Toast,
           handle_activated=handle_activated,
           handle_dismissed=handle_dismissed,
           handle_failed=handle_failed):
    """
    Non-blocking call to schedule an async toast show on the background thread's loop.
    """
    util.debug("Showing Windows notification asynchronously")
    # Wait until the background thread has created 'self.toast_notifier'
    if not self._ready_event.is_set():
      self._ready_event.wait(timeout=5)

    if not hasattr(self, "toast_notifier"):
      print("[BackgroundNotifier] Cannot show toast. Notifier not created.")
      return

    # Schedule the existing 'show_async(...)' coroutine in our background loop
    fut = asyncio.run_coroutine_threadsafe(
      show_async(self.toast_notifier, toast, handle_activated, handle_dismissed, handle_failed),
      self.loop
    )

    util.debug("Notification scheduled")
    return fut  # a Future, if you ever need to check status

  def shutdown(self):
    """
    Gracefully shut down the background loop/thread if needed.
    """
    try:
      def stop_loop():
        self.loop.stop()
      asyncio.run_coroutine_threadsafe(stop_loop(), self.loop)
      self.thread.join()
    except Exception as e:
      print("[BackgroundNotifier] ERROR in shutdown:", e)


class NotificationWin32:
  """
  Displays a Windows Toast Notification without creating
  a tray icon. Requires 'winsdk' to be installed.
  """
  def __init__(self, app_name, title, message, icon=None, duration=5, on_activated=None, on_dismissed=None, on_failed=None, event_loop=asyncio.get_event_loop()):
    """
    :param title: Title text of the notification.
    :param message: Body text of the notification.
    :param icon: (Optional) Path/URL to the icon image.
    :param duration: Time in seconds to keep the script alive after showing the notification.
                     This helps ensure short-running scripts don't exit immediately.
                     (Windows toast may remain in the Action Center afterward.)
    """
    self.notifier = Notifier(app_name)
    self.async_notifier = AsyncNotifier(app_name)
    self.event_loop = event_loop
    self.title = title
    self.message = message
    self.icon = os.path.abspath(icon)
    self.duration = duration
    self.on_activated = on_activated
    self.on_dismissed = on_dismissed
    self.on_failed = on_failed

  def _on_activated(self, args):
    util.debug("Toast Notification Activated! (User clicked or tapped on it)")
    if self.on_activated:
      self.on_activated(args)

  def _on_dismissed(self, args):
    # Possible reasons: 0 (User canceled), 1 (Application hidden), 2 (Timed out)
    util.debug(f"Toast Notification Dismissed! {args.sender} Reason code: {args.reason}")
    if self.on_dismissed:
      self.on_dismissed(args)

  def _on_failed(self, args):
    util.debug(f"Toast Notification Failed with error: {args.error_code}")
    if self.on_failed:
      self.on_failed(args)

  def show(self, title=None, message=None, duration=None, threaded=False):
    util.debug(f"Showing Windows notification {title}|{message}|{duration}|{threaded}")
    if not Notifier or not Toast:
      raise RuntimeError("The 'winsdk_toast' package is not installed. Please install it.")

    toast = Toast()
    if self.icon:
      toast.add_image(self.icon, placement="appLogoOverride", hint_crop="circle")
    toast.add_text(title or self.title)
    toast.add_text(message or self.message)

    try:
      notifier = threaded and self.async_notifier or self.notifier
      notifier.show(
        toast,
        handle_activated = self._on_activated,
        handle_dismissed = self._on_dismissed,
        handle_failed = self._on_failed
      )

      util.debug(f"Notification displayed for {duration or self.duration} seconds")
      return toast
    except Exception as e:
      util.debug(f"Error displaying notification: {e}")
      if util.DEBUG_ENABLED:
        raise e
      
  def shutdown(self):
    self.async_notifier.shutdown()


class NotificationLinux:
  """
  Displays a Linux notification using `notify-send`.
  """
  def __init__(self, title, message, icon=None, duration=5):
    """
    :param title: Title text of the notification.
    :param message: Body text of the notification.
    :param icon: (Optional) Path/URL to the icon image.
    :param duration: Time in seconds for how long the notification should persist (if supported).
                     `notify-send` takes milliseconds, so it will be converted automatically.
    """
    self.title = title
    self.message = message
    self.icon = icon
    self.duration = duration

  def show(self, title=None, message=None, duration=None):
    # notify-send arguments
    command = ["notify-send", title or self.title, message or self.message]

    # If an icon is specified, attach it
    if self.icon:
      command.extend(["-i", self.icon])

    # Delay (ttl) in milliseconds
    if self.delay:
      command.extend(["-t", str((duration or self.duration) * 1000)])

    # Run notify-send
    subprocess.run(command, check=False)

  def shutdown(self):
    pass


if sys.platform.startswith("win"):
  class Notification(NotificationWin32):
    pass
elif sys.platform.startswith("linux"):
  class Notification(NotificationLinux):
    pass