# NOTE: local.py must be an empty file when using this configuration.

from .defaults import *

# Put migration environment specific overrides below

SECRET_KEY = 'hbqnTEq+m7Tk61bvRV/TLANr3i0WZ6hgBXDh3aYpSU8m+E1iCtlU3Q=='

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql_psycopg2',
        'NAME': 'onepercentsite_migration',
        'USER': 'jenkins'
    },
    'legacy': {
        'ENGINE': 'django.db.backends.postgresql_psycopg2',
        'NAME': 'legacy',
        'USER': 'jenkins'
    }
}

import logging

# Log debug messages to standard output by default
logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s %(levelname)-8s %(message)s',
                    datefmt='[%d/%b/%Y %H:%M:%S]')

# Increase DB debug level
logging.getLogger('django.db.backends').setLevel(logging.WARNING)

# Do not run legacy migrations in debugger on testing server
LEGACY_MIGRATIONS_DEBUG = False

# On the devserver we expect static assets to live here
LEGACY_MIGRATIONS_MEDIA_ROOT = '/home/onepercent/data/live'
