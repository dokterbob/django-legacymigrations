# coding=utf8

import logging
logger = logging.getLogger(__name__)

from django.db.models import Q

from django.contrib.auth.models import User, Group
from django.contrib.auth import authenticate

from legacy.legacymembers.models import Member

from .base import MigrateModel

from .mappings import (
    CropMapping, EducateDateTimeMapping, SubstitutionMapping, Mapping,
)


class ActivatedMapping(Mapping):
    """
    Make sure that deleted users cannot login, as well as unactivated users.
    """
    def map(self, from_instance, from_field):
        activated = getattr(from_instance, from_field)

        # Accounts can be marked as deleted in members or profiles.
        account_deleted = from_instance.deleted
        if from_instance.profile:
            profile_deleted = from_instance.profile.deleted
        else:
            profile_deleted = False

        # Deleted users should not be able to log in
        if account_deleted or profile_deleted:
            activated = False

        return {'is_active': activated}

    def check(self, from_instance, to_instance, from_field):
        old_activated = getattr(from_instance, from_field)
        member_deleted = from_instance.deleted
        if from_instance.profile:
            profile_deleted = from_instance.profile.deleted
        else:
            profile_deleted = False
        new_activated = to_instance.is_active

        return (not member_deleted and not profile_deleted and old_activated) is new_activated


class AdminMapping(Mapping):
    """
    1. admin = 1 should turn into is_superuser = TRUE (otherwise FALSE)
    2. admin > 0 should turn into is_staff = TRUE (otherwise FALSE)
    """

    # TODO: Only the 1%DEV team should be superusers. Need to create a 1%CREW Group.
    def map(self, from_instance, from_field):
        admin = getattr(from_instance, from_field)

        if admin > 0:
            if admin == 1:
                return {
                    'is_superuser': True,
                    'is_staff': True
                }
            else:
                return {'is_staff': True}

        return {}

    def check(self, from_instance, to_instance, from_field):
        old_value = getattr(from_instance, from_field)

        superuser = to_instance.is_superuser
        staff = to_instance.is_staff

        return (superuser and staff and old_value == 1) or \
            (staff and old_value > 1) or \
            not (superuser or old_value)


class MigrateMemberAuth(MigrateModel):
    """
    Migrate legacy members to Django users.

    Spec:
        Field mapping
        id = mem_member.id
        username = mem_member.username
        firstname = mem_profile.first_name, see 5
        lastname  = mem_profile.last_name, see 5
        email = mem_members.email
        password = mem_members.password
        is_staff = see 2
        is_superuser = see 1
        last_login = mem_members.updated (don't think we actually have a
                     'lastlogin', this comes closest)
        date_joined = mem_members.created
    """

    def __init__(self):

        try:
            self.assistant_group = Group.objects.get(name="Assistant")
        except Group.DoesNotExist:
            raise Exception("Assistant group not found. "
                            "Is the auth_group_data.json fixture loaded?")


    def post_save(self, from_instance, to_instance):
        """
        Set auth groups. This needs to be done in the post save hook because the
        User needs a pk before it can get a Group.
        """
        # Admin mapping from old db to UI:
        #   0 -> Member
        #   1 -> Admin          TODO: Add a 1%CREW or Admin group
        #   2 -> Assistents
        #   3 -> Coaches        TODO: Add a Coach group

        if from_instance.admin == 2:
            to_instance.groups.add(self.assistant_group)
            to_instance.save()

    def test_multiple(self, from_qs):
        """
        Test whether the login of just a few users actually works.
        """

        # First, call the method from the superclass
        success = super(MigrateMemberAuth, self).test_multiple(from_qs)

        # Now, test a bunch of users
        # (these users have been manually added for testing purposes)
        test_users = (
            # Activated user
            ('usermigrationtest2', 'pohji8'),

            # Activated user usermigrationtest2
            ('mathijs@visualspace.nl', 'pohji8'),

            # Thai, in Thai
            ('glavangadje', 'ภาษาไทย'),

            # Previous user glavangadje
            ('drbob@dokterbob.net', 'ภาษาไทย')
        )

        for user in test_users:
            logger.info('Attempting login for test user %s', user)

            if not authenticate(username=user[0], password=user[1]):
                logger.error(
                    "Test user '%s' could not login with password '%s'",
                    user[0], user[1]
                )
                success = False

        return success

    def test_single(self, from_instance, to_instance):
        success = super(MigrateMemberAuth, self).test_single(from_instance, to_instance)

        # Ensure that the first and last name are correct for at least one user.
        # This checks that bug BB-61 is propperly fixed.
        if to_instance.username == 'ecvdzee':
            if to_instance.first_name != 'Eva' or to_instance.last_name != 'van der Zee':
                logger.error("Member first and last names have not been migrated correctly.")
                success = False

        return success


    def list_from_exclusions(self, qs):
        """ Perform explicit exclusions on the queryset for dirty data. """

        # Don't migrate users with username 'guest' and 'weg'.
        # Users 'weg' should be deleted at some point.
        # Users 'guest' should be turned into 'guest' users.
        qs = qs.exclude(
            Q(username='guest') | Q(username='weg') | 
            Q(username='testaccountacceptemagverwijderd')
        )

        # Exclude all Loek's accounts that are not Loek himself
        qs = qs.exclude(
            Q(email='loek@1procentclub.nl') & ~Q(username='gannetson')
        )

        return qs

    from_model = Member
    to_model = User

    field_mapping = {
        'id': True, # True means just copy the field
        'email': CropMapping(75),

        'username': CropMapping(30),
        'profile': {
            'firstname': CropMapping(30, 'first_name'),
            'lastname': CropMapping(30, 'last_name')
        },

        'password': SubstitutionMapping('legacy$%s'),

        'created': EducateDateTimeMapping(tz=None, to_field='date_joined'),
        'updated': EducateDateTimeMapping(tz=None, to_field='last_login'),

         # Mapped in ActivatedMapping
        'deleted': None,

        'admin': AdminMapping(),
        'activated':  ActivatedMapping(),

        # Explcitly map stuff to /dev/null
        'accepte_user': None,
        'activation': None,
        'alert': None,
        'batch': None,
        'document': None,
        'donation': None,
        'ignore_activity': None,
        'invitee': None,
        'inviter': None,
        'language': None,
        'login': None,
        'membertag': None,
        'organizationmember': None,
        'passwordrequest': None,
        'paymentcluster': None,
        'portfolioline': None,
        'project': None,
        'project_message_set': None,
        'rating': None,
        'receiver': None,
        'reported': None,
        'sender': None,
        'task': None,
        'taskmember': None,
        'taskmessage': None,
        'testimonial': None,
        'type': None,
        'validated': None,
        'voucher': None,
        'weblog_message_set': None
    }
