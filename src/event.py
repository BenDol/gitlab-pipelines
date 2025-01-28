class EventBus:
  """
  A simple EventBus to publish/subscribe to named events.
  """
  def __init__(self):
    self.listeners = {}

  def subscribe(self, event_name, callback):
    """Subscribe a callback to a specific event_name."""
    if event_name not in self.listeners:
      self.listeners[event_name] = []
    self.listeners[event_name].append(callback)

  def unsubscribe(self, event_name, callback):
    """Unsubscribe a callback from a specific event_name."""
    if event_name in self.listeners and callback in self.listeners[event_name]:
      self.listeners[event_name].remove(callback)

  def publish(self, event_name, *args, **kwargs):
    """Publish an event, invoking all callbacks subscribed to event_name."""
    if event_name in self.listeners:
      for callback in self.listeners[event_name]:
        callback(*args, **kwargs)