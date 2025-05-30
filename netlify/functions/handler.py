import os
import sys

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), '..', '..')
sys.path.insert(0, PROJECT_ROOT)

from serverless_wsgi import handle
from app import app as application

def handler(event, context):
    return handle(application, event, context)