import os
import sys
import json
import ctypes
from ctypes import wintypes
import threading

if sys.platform.startswith("win"):
  import winreg
  advapi32 = ctypes.WinDLL("Advapi32.dll")
  user32 = ctypes.WinDLL('user32', use_last_error=True)

DEBUG_ENABLED = False
TIMERS = []

import threading

class Timer:
  def __init__(self, seconds, function, *args, **kwargs):
    self.seconds = seconds
    self.function = function
    self.args = args if args is not None else []
    self.kwargs = kwargs if kwargs is not None else {}
    self.on_finish = None
    self.timer = None

  def start(self):
    def _run():
      self.function(*self.args, **self.kwargs)

      if self.on_finish:
        self.on_finish(*self.args, **self.kwargs)

    self.timer = threading.Timer(self.seconds, _run)
    self.timer.start()

  def cancel(self):
    if self.timer:
      self.timer.cancel()

  def is_alive(self):
    return self.timer.is_alive() if self.timer else False

  def set_on_finish(self, on_finish):
    self.on_finish = on_finish

def debug(msg):
  if DEBUG_ENABLED:
    print(f"[DEBUG] {msg}")

def set_env_var(name, value, system=False):
  if sys.platform.startswith("win"):
    scope = winreg.HKEY_CURRENT_USER if not system else winreg.HKEY_LOCAL_MACHINE
    sub_key = r'Environment'
    with winreg.OpenKey(scope, sub_key, 0, winreg.KEY_SET_VALUE) as key:
      winreg.SetValueEx(key, name, 0, winreg.REG_EXPAND_SZ, value)
  else:
    os.environ[name] = value

def get_env_var(name, system=False):
  if sys.platform.startswith("win"):
    scope = winreg.HKEY_CURRENT_USER if not system else winreg.HKEY_LOCAL_MACHINE
    sub_key = r'Environment'
    with winreg.OpenKey(scope, sub_key, 0, winreg.KEY_READ) as key:
      try:
        value, _ = winreg.QueryValueEx(key, name)
        return value
      except WindowsError:
        return None
  else:
    return os.environ.get(name)

def get_script_name():
  script_path = sys.argv[0]
  script_name = os.path.splitext(os.path.basename(script_path))[0]
  return script_name

def load_json(file):
  if not file.endswith(".json"):
    file += ".json"
  f = open(os.getcwd() + '/' + file, )
  conf = json.load(f)
  f.close()
  return conf

def execute_after_delay(seconds, my_event, *args, **kwargs):
  timer = Timer(seconds, my_event, *args, **kwargs)
  timer.start()
  TIMERS.append(timer)
  timer.set_on_finish(lambda: TIMERS.remove(timer))
  return timer

def cancel_delay_timers():
  for timer in TIMERS:
    if timer and timer.is_alive():
      timer.cancel()
  del TIMERS[:]