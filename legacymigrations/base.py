import logging
logger = logging.getLogger(__name__)

import time

from datetime import datetime
from django.utils import timezone
from django.db import connections
from django.db import transaction
from django.core.exceptions import (
    ValidationError, NON_FIELD_ERRORS, ObjectDoesNotExist
)

from pytz.exceptions import AmbiguousTimeError

from .mappings import IdentityMapping, NullMapping, RelatedObjectMapping, AutoUpdatedDateTimeMapping
from .settings import ENABLE_EXCLUSIONS
from .utils import Timer


class MigrateModel(object):
    """
    Generic migration class, from one model class to another.

    Migrations can be run by calling :meth:`migrate_all`.
    """

    from_db = 'legacy'
    to_db = 'default'

    def __repr__(self):
        return self.__class__.__name__

    def __init__(self):
        # Used to store auto update datetime fields that need to be migrated.
        self.auto_updated_datetime_fields = {}

    def list_from_exclusions(self, qs):
        """
        Take a source queryset and perform explicit filtering on
        'unclean' data.
        """

        return qs

    def _list_from(self):
        """ Caching wrapper for list_from() method. """

        if not hasattr(self, '_from_qs'):
            self._from_qs = self.list_from()

            if ENABLE_EXCLUSIONS:
                self._from_qs = self.list_from_exclusions(self._from_qs)

        return self._from_qs

    def _list_to(self):
        """ Caching wrapper for list_to() method. """

        if not hasattr(self, '_to_qs'):
            self._to_qs = self.list_to()

        return self._to_qs

    def get_mapping(self, field):
        """
        Get the mapping object for the specified field from `field_mapping`.
        """
        mapping = self.field_mapping.get(field)

        if mapping == True:
            # True means just copy the field
            mapping = IdentityMapping()

        elif mapping == None:
            # None means: throw away the data
            mapping = NullMapping()

        elif isinstance(mapping, basestring):
            # A string can be passed to map to a different field
            mapping = IdentityMapping(mapping)

        elif isinstance(mapping, dict):
            # Instance maps a related object to a destination object
            mapping = RelatedObjectMapping(mapping)

        # By this time mapping should be a callable yielding a dict
        assert callable(mapping), \
            u'No forward mapping defined for mapping %s' % mapping

        return mapping

    def map_fields(self, from_instance, to_instance):
        """
        Copy all fields from one object to another.
        """

        for field in self.field_mapping.iterkeys():
            # Get the mapping
            mapping = self.get_mapping(field)

            # Do the migration of auto updated datetime fields after the model
            # has been saved by django.
            if isinstance(mapping, AutoUpdatedDateTimeMapping):
                self.auto_updated_datetime_fields[field] = mapping.get_to_field(field)
                continue

            value_dict = mapping(from_instance, field)

            assert isinstance(value_dict, dict), \
                'Mapping %s returned %s instead of a dict.' % \
                    (mapping, value_dict)

            for (new_field, new_value) in value_dict.iteritems():
                assert isinstance(new_field, basestring)

                setattr(to_instance, new_field, new_value)

    def list_from(self):
        """
        Return an iterable with all objects to be mapped to the new model.
        """

        # Default is to return all objects
        return self.from_model.objects.using(self.from_db).all()

    def list_to(self):
        """
        Return an iterable with all the new objects that have been mapped
        from the old model.
        """

        # Default is to return all objects
        return self.to_model.objects.using(self.to_db).all()

    def get_to_correspondence(self, other_object):
        """
        Return the kwargs used for finding correspondence between one object
        and another. By default, correspondence by PK is used.
        """

        return {'pk': other_object.pk}

    def get_from_correspondence(self, other_object):
        """
        Return the kwargs used for finding correspondence between one object
        and another. By default, correspondence by PK is used.
        """

        return {'pk': other_object.pk}

    def get_to(self, from_instance):
        """
        Given an existing 'old' instance, return the corresponding 'new'
        instance or None if no corresponding object exists.
        """

        # Default is to look up by id
        try:
            correspondence_args = self.get_to_correspondence(from_instance)

            return self._list_to().get(**correspondence_args)

        except self.to_model.DoesNotExist:
            return None

    def get_from(self, to_instance):
        """
        Given an existing 'new' instance, return the corresponding 'old'
        instance or None if no corresponding object exists.
        """

        # Default is to look up by id
        try:
            correspondence_args = self.get_from_correspondence(to_instance)

            return self._list_from().get(**correspondence_args)

        except self.from_model.DoesNotExist:
            return None

    def test_map_fields(self, from_instance, to_instance):
        """ Test mapping of fields. """

        success = True

        for from_field in self.field_mapping.iterkeys():
            # Get the mapping
            mapping = self.get_mapping(from_field)

            if not mapping.check(from_instance, to_instance, from_field):
                logger.error(
                    u"Mapping '%s' for field '%s' on '%s' does not correspond",
                    mapping, from_field, from_instance.__repr__()
                )

                success = False

        return success


    def test_single(self, from_instance, to_instance):
        """
        Test the migration for a single object. Override this.

        Returns True on success, False on error.
        """
        assert from_instance
        assert to_instance

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(u"Testing migration of '%s' to '%s'",
                from_instance.__repr__(), to_instance.__unicode__())

        return self.test_map_fields(from_instance, to_instance)

    def test_multiple(self, from_qs):
        """
        Test the migration for all objects in to_qs.

        By default, make sure we have at least correspondance.

        Returns True on success, False on error.
        """

        success = True

        # Make sure we have the same number of source and destination objects
        from_count = self._list_from().count()
        to_count = self._list_to().count()
        if from_count != to_count:
            logger.error(
                u'Source queryset contains %d objects while destination queryset contains %d',
                from_count, to_count
            )

            success = False

        # Do per-object checks
        counter = 0
        errors = 0

        for to_instance in self._list_to().all():
            check_success = True

            from_instance = self.get_from(to_instance)

            if from_instance:
                if self.get_to(from_instance) != to_instance:
                    # TODO: This error should cause the other tests not to run AFAIK
                    logger.error(u'No bi-directional correspondence from %s to %s',
                        from_instance.__repr__(), to_instance.__unicode__())

                    check_success = False

                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        u"Correspondence found from '%s' to '%s'.",
                        from_instance.__repr__(), to_instance.__unicode__()
                    )

                if from_instance in from_qs:
                    if not self.test_single(from_instance, to_instance):
                        check_success = False

                else:
                    logger.error(
                        u'Correspondence %s not found in source queryset.',
                        from_instance.__repr__()
                    )

                    check_success = False

            else:
                logger.error(
                    u'No backwards correspondence to %s, skipping tests for this object.',
                    to_instance.__unicode__()
                )

                check_success = False

            counter += 1

            if not check_success:
                errors += 1
                success = False

            # Print a progress message very 50 objects
            if (counter % 50) == 0:
                logger.info('%d objects tested', counter)

        logger.info('%d objects tested, %d fails', counter, errors)

        return success

    def validate_single(self, instance):
        """
        Perform model validation for an instance and report back any errors.
        """

        try:
            instance.full_clean()

        except ValidationError as e:
            for (field, errors) in e.message_dict.iteritems():
                for error in errors:
                    if field is NON_FIELD_ERRORS:
                        logger.warning(
                            u"General validation error for '%s': %s",
                            instance, error
                        )
                    else:
                        try:
                            value = getattr(instance, field)
                        except ObjectDoesNotExist:
                            value = '<Not Found>'

                        logger.warning(
                            u"Validation error for field '%s' with value '%s' of '%s': %s",
                            field, value, instance, error
                        )

            # Eventually, we should *not* let these errors pass
            # raise e


    def migrate_single(self, from_instance, to_instance):
        """ Migrate a single object. """

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(u"Migrating '%s' to '%s'",
                from_instance.__repr__(), to_instance.__unicode__())

        self.map_fields(from_instance, to_instance)

    def _migrate_from(self, from_instance):
        to_instance = self.get_to(from_instance)

        # Not existing? Create one!
        if not to_instance:
            to_instance = self.to_model()

        self.migrate_single(from_instance, to_instance)

        self.pre_validate(from_instance, to_instance)

        # Validate the model
        # (before saving, to find any errors in a timely fashion)
        self.validate_single(to_instance)

        self.pre_save(from_instance, to_instance)

        # Save to the database
        to_instance.save(using=self.to_db)

        # Migrate auto updated datetimes.
        if hasattr(self, 'auto_updated_datetime_fields'):
            for from_field in self.auto_updated_datetime_fields.iterkeys():
                self.migrate_auto_updated_datetime(from_instance, to_instance, from_field,
                                                   self.auto_updated_datetime_fields[from_field])

        self.post_save(from_instance, to_instance)

        return to_instance

    def pre_validate(self, from_instance, to_instance):
        """
        Gets called before the to_instance is validated so that any information
        can processed before the data has been validated. Subclasses should
        override this class.
        """
        pass

    def pre_save(self, from_instance, to_instance):
        """
        Gets called before the to_instance is saved so that any information can
        processed after the data has been validated. Subclasses should override
        this class.
        """
        pass

    def post_save(self, from_instance, to_instance):
        """
        Gets called after the to_instance is saved so that any information can
        processed after the data has been saved to the db. Subclasses should
        override this class.
        """
        pass

    def migrate_auto_updated_datetime(self, from_instance, to_instance, from_field, to_field):
        """
        Migrate an auto updated datetime field with custom SQL. This is needed
        because auto updated datetimes can't be set within Django.
        """

        # Get the old auto updated value.
        from_datetime = getattr(from_instance, from_field)
        if from_datetime is None:
            return
        assert isinstance(from_datetime, datetime)

        # Convert the date to a timezone aware datetime.
        if timezone.is_naive(from_datetime):
            tz = timezone.get_default_timezone()
            try:
                to_datetime = tz.localize(from_datetime)
            except AmbiguousTimeError:
                logger.warning(
                    u"Ambiguous datetime '%s' encountered, assuming DST.",
                    from_datetime
                )
                to_datetime = tz.localize(from_datetime, is_dst=True)
        else:
            to_datetime = from_datetime

        # Custom SQL to set the auto updated date.
        sql_statement = 'UPDATE %s SET %s = \'%s\' WHERE %s = %s' % (self.to_model._meta.db_table,
                                                                     to_field, to_datetime,
                                                                     self.to_model._meta.pk.name,
                                                                     to_instance.pk)
        cursor = connections[self.to_db].cursor()
        cursor.execute(sql_statement)
        transaction.commit_unless_managed(using=self.to_db)

    def _update_pk_sequence(self):
        """
        Explicitly truncate the table and reset sequences.
        """
        from django.db.models import Max

        # Get the field name
        pk_field_name = self.to_model._meta.pk.name

        # Find the latest pk
        qs = self.to_model.objects.using(self.to_db).aggregate(latest=Max(pk_field_name))
        latest_pk = qs['latest']

        assert latest_pk

        sequence_name = \
            '%s_%s_seq' % (self.to_model._meta.db_table, pk_field_name)

        logger.info(u"Updating sequence %s for primary key %s on %s to %d",
            sequence_name, pk_field_name, self.to_model, latest_pk
        )

        # Custom SQL to restart the sequence.
        cursor = connections[self.to_db].cursor()

        # Note: This should be standard SQL
        # Ref: http://stackoverflow.com/a/7655273/231332

        cursor.execute('ALTER SEQUENCE %s RESTART WITH %d' % (
            sequence_name, latest_pk+1
        ))

        transaction.commit_unless_managed(using=self.to_db)

    def migrate_all(self, debug_sql):
        """
        Migrate all the objects returned by list_from().

        This method performs the following tasks:

        1. List all objects to migrate by calling :meth:`_list_from`, the
           caching wrapper around :meth:`list_from`.
        2. Log warnings for fields which are not explicitly mapped.
        3. Start a transaction.
        4. Migrate all the individual objects from the source queryset
           by calling :meth:`_migrate_from`.
        5. Perform integrity tests by calling :meth:`test_multiple` on the
           migrated queryset and raise an exception if any of the tests have
           failed.
        6. Commit the transaction.
        7. Manually update the sequence counter for the target database table
           so new primary keys are generated properly after the migration.

        During the process this method will print out timing information for
        the migration and testing process and will give out progress reports
        for every 50 objects migrated.
        """

        logger.info(u"Starting '<%s>'", self.__repr__())

        # Grab a qs of object to migrate
        from_qs = self._list_from()

        counter = 0

        # Check whether all fields are properly mapped and issue
        # a warning if this is not the case.
        from_fields = from_qs.model._meta.get_all_field_names()

        for from_field in from_fields:
            if from_field not in self.field_mapping:
                logger.warning(
                    u"Field '%s' is not mapped and will be thrown away. To get rid of this warning, please map the field to `None` to throw away the data.",
                    from_field
                )
        # Execute all of this within a single transaction
        with transaction.commit_on_success():

            with Timer() as t:
                # Iterate over all instances
                for from_instance in from_qs.all():
                    # Add a sleep statement so the asychronous SQL debug statements
                    # are in the right place. This should be ok because we're only
                    # using this for debugging.
                    if debug_sql:
                        time.sleep(1)

                    self._migrate_from(from_instance)

                    counter += 1

                    # Print a progress message very 50 objects
                    if (counter % 50) == 0:
                        logger.info(u'%d objects migrated', counter)

            logger.info(u'Migration performed in %.03f seconds.', t.interval)
            logger.info(u'Starting integrity tests.')

            with Timer() as t:
                if not self.test_multiple(from_qs):
                    raise Exception('Integrity tests failed, not committing changes.')

            logger.info(
                u'Integrity tests completed in %.03f seconds.',
                t.interval
            )

        self._update_pk_sequence()

        logger.info(u'%d objects migrated', counter)

        logger.info(u'Migration %s complete.', self.__class__.__name__)


class UniqueSlugMixin(object):
    """
    Mixin overriding the slug field to be unique.

    The name of the slug field can be overridden by setting the `slug_field`
    property on the migration class. It defaults to `slug` when not specified.

    """

    # Default name for (new) slug field, can be overridden
    slug_field = 'slug'

    def _get_slug(self, instance):
        """ Get the slug for an instance. """

        return getattr(instance, self.slug_field)

    def migrate_single(self, from_instance, to_instance):
        """ After calling super migration method, change slug if needed. """

        super(UniqueSlugMixin, self).migrate_single(
            from_instance,
            to_instance
        )

        # Check whether this username already exists. If so, add a number
        counter = 1

        # Make sure we exclude the current object
        qs = self._list_to().exclude(pk=to_instance.pk)

        # Detect and change duplicate slug
        original_slug = self._get_slug(to_instance)

        while qs.filter(**{self.slug_field: self._get_slug(to_instance)}).exists():
            to_instance.slug = '%s-%d' % (original_slug, counter)

            # From Margreet: Don't display this warning for duplicate organizations.
            if self.__class__.__name__ != 'MigrateOrganization':
                logger.warn('Duplicate slug %s, changing to %s',
                    original_slug, to_instance.slug
                )

            counter += 1
