#!/bin/bash -ex

DB_NAME=onepercentsite_migration
SQL_DATA_ARCHIVE=migrated_data.sql.bz2
MEDIA_DATA_ARCHIVE=migrated_media.tar
MEDIA_DATA_DIR=static/media

# Set resource limits to 1800MB max only when --server-migration has been set.
if [ $# -gt 0 -a "x$1" = "x--server-migration" ]; then
   ulimit -v 1800000
fi

# Drop database and remove existing files (always succeed)
dropdb $DB_NAME || true
rm -rf $MEDIA_DATA_DIR || true
rm -f $MEDIA_DATA_ARCHIVE || true
rm -f $SQL_DATA_ARCHIVE || true

# Create new database
createdb -T template0 -E utf8 $DB_NAME

# Setup datastructure and project
bash -x prepare.sh

# Get into our environment
source env/bin/activate

# Use migration settings when running on the server.
if [ $# -gt 0 -a "x$1" = "x--server-migration" ]; then
    export DJANGO_SETTINGS_MODULE=bluebottle.settings.migration

    # Clear the local.py settings when running with the migration settings.
    # This is required for the migration settings to work.
    echo "" > bluebottle/settings/local.py
fi

# Setup new database
python manage.py syncdb --noinput --migrate

# Load fixtures before the migration
python manage.py loaddata auth_group_data
python manage.py loaddata region_subregion_country_data
python manage.py loaddata project_partnerorganization_data
python manage.py loaddata project_theme_data

# Do the migration. The migrations are being done individually so that the memory consumption is reset after each run.
for migration in $(grep "legacy\.legacymigration\." bluebottle/settings/defaults.py | sed -e "s/'.*\.//" -e "s/',*//"); do
  python manage.py migrate_legacy -v 2 $migration
done

# Finish the script if this is being run on the server.
if [ $# -gt 0 -a "x$1" = "x--server-migration" ]; then
    continue
else
    exit 0
fi

# Dump database and archive media
pg_dump -x --no-owner $DB_NAME | bzip2 -c > $SQL_DATA_ARCHIVE
tar cvf $MEDIA_DATA_ARCHIVE $MEDIA_DATA_DIR

# Remove the files that have been archived to save space.
rm -rf $MEDIA_DATA_DIR || true

# Fail if there's not enough space to make a copy of the archived files.
# For some reason jenkins doesn't marked the build as failed when the server
# runs out of disk space.
# Note: The 'grep xvda' in the line below is specific to Linode.
AVAILABLE_SPACE=$(expr $(df | grep xvda | awk 'NF = 4' | awk '{ print $NF }') \* 1024)
MEDIA_DATA_SIZE=$(ls -l $MEDIA_DATA_ARCHIVE | awk 'NF = 5' | awk '{ print $NF }')
if [ $MEDIA_DATA_SIZE -gt $AVAILABLE_SPACE ]; then
    echo "The server does not have enough hard-drive space to finish the migration."
    exit 1
fi
