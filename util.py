import os
import sys
import json

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