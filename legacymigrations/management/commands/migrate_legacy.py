import logging

from optparse import make_option

from django.core.management.base import BaseCommand

from ...settings import MIGRATIONS, DEBUG_MIGRATIONS
from ...utils import get_migration


class Command(BaseCommand):
    help = 'Migrate existing legacy models.'
    can_import_settings = True
    requires_model_validation = True

    """
    Map verbosity to log levels, according to: (from Django manual)

    0 means no output.
    1 means normal output (default).
    2 means verbose output.
    3 means very verbose output.
    """
    verbosity_loglevel = {
        '0': logging.ERROR,
        '1': logging.WARNING,
        '2': logging.INFO,
        '3': logging.DEBUG
    }

    option_list = BaseCommand.option_list + (
        make_option('--debug-sql',
            action='store_true',
            dest='debugsql',
            default=False,
            help='Display the SQL statements that Django executes.'),
        )


    def _run_migration(self, debug_sql, migration):
        """ Run a single migration. """

        migration_instance = get_migration(migration)
        migration_instance.migrate_all(debug_sql)

    def _run_migrations(self, debug_sql=False, *args):
        """ Run a series of migrations. """

        for migration in MIGRATIONS:
            # Execute all migrations, unless a set of migration classes
            # have been specified on the command line
            if not args or migration.rsplit('.', 1)[1] in args:
                self._run_migration(debug_sql, migration)

    def handle(self, *args, **options):
        # Setup the log level for root logger
        loglevel = self.verbosity_loglevel.get(options['verbosity'])
        logging.getLogger().setLevel(loglevel)

        # from debugsqlshell
        if options['debugsql']:
            from datetime import datetime
            from django.db.backends import util
            from debug_toolbar.utils import ms_from_timedelta, sqlparse

            class PrintQueryWrapper(util.CursorDebugWrapper):
                def execute(self, sql, params=()):
                    starttime = datetime.now()
                    try:
                        return self.cursor.execute(sql, params)
                    finally:
                        try:
                            raw_sql = self.db.ops.last_executed_query(self.cursor, sql, params)
                            execution_time = datetime.now() - starttime
                            print sqlparse.format(raw_sql, reindent=True),
                            print ' [%.2fms]' % (ms_from_timedelta(execution_time),)
                            print
                        except UnicodeEncodeError:
                            print "UnicodeEncodeError"

            util.CursorDebugWrapper = PrintQueryWrapper

        # When debugging, launch ipdb on exception
        if DEBUG_MIGRATIONS:
            # Exception launches ipdb https://github.com/Psycojoker/ipdb#use
            from ipdb import launch_ipdb_on_exception
            with launch_ipdb_on_exception():
                self._run_migrations(options['debugsql'], *args)
        else:
            # Just run the migrations
            self._run_migrations(options['debugsql'], *args)

