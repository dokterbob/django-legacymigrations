import logging
logger = logging.getLogger(__name__)

import settings

from legacy.legacymembers.models import Profile
from apps.accounts.models import UserProfile, UserAddress

from .base import MigrateModel

from .accounts import MigrateMemberAuth

from .mappings import (
    EducateDateTimeMapping, CountryMapping, Mapping,
    StringMapping, MappingMapping, CropMapping,
    WebsiteMapping, PathToFileMapping
)


class ProfileDeletedDateTimeMapping(EducateDateTimeMapping):
    """
    Migrates deleted users by checking the deleted field in member and profile.
    Yes, it can be marked as deleted members OR profile!
    """
    def map(self, from_instance, from_field):
        profile_deleted = getattr(from_instance, from_field)
        member_deleted = from_instance.member.deleted

        # Deleted can be set in two places.
        if profile_deleted:
            # Use the deleted value from profile first if it's set.
            new_value = self.map_value(profile_deleted)
        elif member_deleted:
            # Use the deleted value from member if it's set and profile.deleted
            # is not set.
            new_value = self.map_value(profile_deleted)
        else:
            # Fallback to using deleted from profile in a normalized form if neither
            # are set.
            new_value = self.map_value(profile_deleted)

        return {self.get_to_field(from_field): new_value}


class MigrateProfile(MigrateModel):
    """
    Migrate from legacy profile to new UserProfile, using the member/user
    PK correspondence.
    """
    from_model = Profile
    to_model = UserProfile

    def get_to_correspondence(self, other_object):
        return {'user__pk': other_object.member.pk}

    def get_from_correspondence(self, other_object):
        return {'member__pk': other_object.user.pk}

    def _get_members(self):
        """ Return all members to migrate. """

        user_migrator = MigrateMemberAuth()

        # Make sure we only fetch ID's from the database
        return user_migrator._list_from().only('id')

    def list_from(self):
        """
        Make sure we only migrate profiles for which the user is migrated
        as well.
        """

        qs = super(MigrateProfile, self).list_from()

        # Only migrate profiles for migrated members
        qs = qs.filter(member__in=self._get_members())

        # Select related members as well, to reduce queries
        qs = qs.select_related('member')

        return qs

    def _get_noprofile_member_pks(self):
        """
        Filter out members without a profile.
        """
        members = self._get_members()

        # Make a list of all members without a profile
        members = members.filter(profile=None)
        member_pks = members.values_list('id', flat=True).order_by('id')

        return list(member_pks)

    def list_to(self):
        """
        Make sure only profiles that have a corresponding legacy profile are
        mapped back.
        """

        qs = super(MigrateProfile, self).list_to()

        # Exclude all the user/member id's for which no profile has been set.
        qs = qs.exclude(user__pk__in=self._get_noprofile_member_pks())

        # Get related user as well, to reduce queries
        qs = qs.select_related('user')

        return qs

    field_mapping = {
        # ID's do not correspond for profiles
        'id': None,

        'member_id': 'user_id',
        'primary_language': 'interface_language',
        'newsletter': MappingMapping({
            'y': True
        }, default=False),
        'birthdate': True,
        'gender': MappingMapping({
            'm': 'male',
            'f': 'female',
        }, default=''),
        'location': StringMapping(),
        'website': WebsiteMapping(),
        'deleted': ProfileDeletedDateTimeMapping(),
        'about': StringMapping(),
        'why': StringMapping(),
        'contribution': StringMapping(),

        'available_time': CropMapping(length=255, to_field='availability'),
        'working_location': CropMapping(length=255),

        # Stuff mapped to Django auth users
        'member': None,
        'firstname': None,
        'lastname': None,
        'created': None,

        # TODO: Migrate with AutoUpdatedDateTimeMapping().
        'updated': None,

        # This will be used by the social auth application
        # (whatever it will be)
        'facebook_connect_enabled': None,
        'facebook_id': None,

        # Migrate to address
        'address': None,
        'zipcode': None,
        'city': None,
        'country': None,

        # Don't know what to do with these for now
        'authorize_capture': None,
        'billingcity': None,
        'billingname': None,
        'billingnumber': None,
        'recurring_donation_amount': None,

        'photo': PathToFileMapping(
            root_path=settings.LEGACY_MEDIA_ROOT + '/assets/files/images/profiles/',
            allow_missing=True,
            download_prefix='assets/files/images/profiles',
            to_field='picture'
        ),
    }


class MemberMapping(Mapping):
    """ Set the target profile through the profile. """

    def __init__(self, *args, **kwargs):
        # Cache the profile migrator as to enable queryset generation caching
        self.profile_mapper = MigrateProfile()
        super(MemberMapping, self).__init__(*args, **kwargs)

    def map(self, instance, from_field):
        to_profile = self.profile_mapper.get_to(instance)

        return {'user_profile': to_profile}

    def check(self, from_instance, to_instance, from_field):
        return from_instance.member.pk == to_instance.user_profile.user.pk


class MigrateUserAddress(MigrateProfile):
    """
    Migrate from Profile to UserAddress, respecting the member/user pk
    correspondence as with the profiles.
    """
    from_model = Profile
    to_model = UserAddress

    def get_to_correspondence(self, other_object):
        return {'user_profile__user__pk': other_object.member.pk}

    def get_from_correspondence(self, other_object):
        return {'member__pk': other_object.user_profile.user.pk}

    def list_to(self):
        """
        Make sure only profiles that have a corresponding legacy profile are
        mapped back.
        """
        qs = super(MigrateProfile, self).list_to()

        # Exclude all the user/member id's for which no profile has been set.
        qs = qs.exclude(
            user_profile__user__pk__in=self._get_noprofile_member_pks()
        )

        # Select related profile user to optimize query
        qs = qs.select_related('user_profile__user')

        return qs

    field_mapping = {
        'member': MemberMapping(),

        'address': StringMapping('line1'),
        'zipcode': StringMapping('zip_code'),
        'city': StringMapping(),
        'country': CountryMapping(),

        # Dump all the other stuff
        'id': None,
        'member_id': None,
        'primary_language': None,
        'newsletter': None,
        'birthdate': None,
        'gender': None,
        'location': None,
        'website': None,
        'deleted': None,
        'about': None,
        'why': None,
        'contribution': None,
        'available_time': None,
        'working_location': None,
        'firstname': None,
        'lastname': None,
        'created': None,
        'updated': None,
        'facebook_connect_enabled': None,
        'facebook_id': None,
        'authorize_capture': None,
        'billingcity': None,
        'billingname': None,
        'billingnumber': None,
        'recurring_donation_amount': None,
        'photo': None

    }
