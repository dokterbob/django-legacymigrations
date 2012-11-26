import logging
logger = logging.getLogger(__name__)

from legacy.legacyorganizations.models import (
    Organization as LegacyOrganization,
    OrganizationMember as LegacyOrganizationMember,
)

from apps.organizations.models import (
    Organization, OrganizationMember, OrganizationAddress
)

from .base import MigrateModel, UniqueSlugMixin
from .mappings import (
    EducateDateTimeMapping,
    StringMapping, OneToManyMapping, CountryMapping,
    IdentityMapping, AutoUpdatedDateTimeMapping,
    WebsiteMapping, TolerantSlugifyCroppingMapping,
    ConcatenatingStringMapping, CropMapping
)


class MigrateOrganizationBase(MigrateModel):
    """ Base class for migrations departing from organizations. """
    from_model = LegacyOrganization

    def list_from_exclusions(self, qs):
        """ Perform explicit exclusions on the queryset for dirty data. """

        # Exclude unnamed organizations
        qs = qs.exclude(name='')

        return qs


class OrgTolerantSlugifyCroppingMapping(TolerantSlugifyCroppingMapping):
    """ Special PathToFileMapping that we can detect in the Migrate class """
    def __init__(self, *args, **kwargs):
        self.organization = True
        super(OrgTolerantSlugifyCroppingMapping, self).__init__(*args, **kwargs)


class MigrateOrganization(UniqueSlugMixin, MigrateOrganizationBase):
    to_model = Organization

    field_mapping = {
        'id': True,
        'name': OneToManyMapping(
            IdentityMapping('name'),
            OrgTolerantSlugifyCroppingMapping(100, to_field='slug')
        ),
        'legalstatus': 'legal_status',
        'phonenumber': StringMapping('phone_number'),
        # From Margreet: Don't migrate Organization email addresses.
        'email': None,
        'website': WebsiteMapping(),
        'description': StringMapping(),

        'created': EducateDateTimeMapping(),
        'updated': AutoUpdatedDateTimeMapping(),
        'deleted': EducateDateTimeMapping(),

        'partner_organisations': StringMapping(),

        # Bank account details
        'account_number': True,
        'account_name': True,
        'account_city': True,
        'account_bank_name': StringMapping(),
        'account_bank_address': StringMapping(),

        # For now, don't map this until we have an actual FK on countries
        'account_bank_country_id': None,

        'account_iban': StringMapping(),
        'account_bicswift': StringMapping(),

        # Will be mapped through the address
        'street': None,
        'street_number': None,
        'postalcode': None,
        'city': None,
        'country_id': None,

        # Will be mapped through OrganizationMember
        'organizationmember': None,

        # Should not be mapped from the reverse side
        'project': None
    }


class MigrateOrganizationMember(MigrateModel):
    from_model = LegacyOrganizationMember
    to_model = OrganizationMember

    def list_from(self):
        """ Only migrate members for migrated organizations. """
        qs = super(MigrateOrganizationMember, self).list_from()

        m = MigrateOrganization()
        organization_list = m._list_from()

        qs = qs.filter(org__in=organization_list)

        return qs

    def get_to_correspondence(self, other_object):
        """ Do correspondence by the member and organization id's. """

        return {
            'user_id': other_object.mem.id,
            'organization_id': other_object.org.id
        }

    def get_from_correspondence(self, other_object):
        """ Do correspondence by the member and organization id's. """

        return {
            'mem_id': other_object.user.id,
            'org_id': other_object.organization.id
        }

    def pre_validate(self, from_instance, to_instance):
        # BB-66: Current organization member is the owner.
        to_instance.function = OrganizationMember.MemberFunctions.owner

    field_mapping = {
        # This legacy table has no pk (!?)
        # 'id': True,

        'mem': None,
        'mem_id': 'user_id',

        'org': None,
        'org_id': 'organization_id'
    }


class MigrateOrganizationAddress(MigrateOrganizationBase):
    to_model = OrganizationAddress

    def list_from_exclusions(self, qs):
        """ Perform explicit exclusions on the queryset for dirty data. """
        qs = super(MigrateOrganizationAddress, self).list_from_exclusions(qs)

        # TODO: Split the street into multiple address lines
        qs = qs.exclude(pk__in=(1311, 1015, 1568))

        return qs

    field_mapping = {
        'id': OneToManyMapping(
            IdentityMapping('id'),
            IdentityMapping('organization_id')
        ),

        # Will be mapped through the address
        'street': ConcatenatingStringMapping(
            concatenate_with=('street_number', ),
            to_field='line1',
            concatenate_str=' '
        ),
        'street_number': None,
        'postalcode': CropMapping(20, to_field='zip_code'),
        'city': True,

        'country': CountryMapping(),

        # Already mapped fields
        'name': None,
        'legalstatus': None,
        'phonenumber': None,
        'email': None,
        'website': None,
        'description': None,
        'created': None,
        'updated': None,
        'deleted': None,
        'partner_organisations': None,
        'account_number': None,
        'account_name': None,
        'account_city': None,
        'account_bank_name': None,
        'account_bank_address': None,
        'account_bank_country_id': None,
        'account_iban': None,
        'account_bicswift': None,

        # Will be mapped through OrganizationMember
        'organizationmember': None,

        # Should be mapped later
        'referrals': None,

        # Should not be mapped from the reverse side
        'project': None

    }
