"""Fail closed when private files cannot be verified on their storage backend."""
from botocore.exceptions import BotoCoreError, ClientError

STORAGE_ERRORS = (OSError, BotoCoreError, ClientError)

def file_exists(file):
    try:
        return bool(file and file.name and file.storage.exists(file.name))
    except STORAGE_ERRORS:
        return False
