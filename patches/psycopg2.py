# Required for pypy to access postgres.
# from: http://pypi.python.org/pypi/psycopg2ct
from psycopg2ct import compat
compat.register()
