import sys
import os

APP_DIR = "/var/www/ib"
sys.path.insert(0, APP_DIR)
os.chdir(APP_DIR)

from ib import ib as application

