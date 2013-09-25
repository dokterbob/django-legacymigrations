import logging
logger = logging.getLogger(__name__)

from django.utils import timezone

from legacy.legacydonations.models import (
    DonationLine as LegacyDonationLine
)
from apps.donations.models import Donation
from .base import MigrateModel
from .mappings import StringToDecimalMapping, Mapping, AutoUpdatedDateTimeMapping


class DonationMapping(Mapping):
    """
        Migrate & check amounts
    """

    def add_tz(self, datetime):
        # This is copy pasted from the EducatedDateTime mapping
        if datetime is None:
            return None
        if timezone.is_naive(datetime):
            return timezone.get_default_timezone().localize(datetime)
        return datetime

    def map(self, from_instance, from_field):
        donation = getattr(from_instance, from_field)
        member = donation.member
        user_id = member.id

        if member.type_id == 1 or member.username == 'guest':
            logger.debug("Guest user set donation user to None.")
            user_id = None
        
        return {
            'type': donation.type,
            'user_id': user_id,
            'status': donation.status,
            'created': self.add_tz(donation.created),
        }

    def check(self, from_instance, to_instance, from_field):
        """ Checking amounts here """
        donation = getattr(from_instance, from_field)
        total_amount = 0
        for line in donation.donationline_set.all():
            total_amount += line.amount
        if total_amount != donation.amount:
            logger.warn("Validation error donation_line amounts add op to " +
                     str(total_amount) + " while donation amount is " + 
                     str(donation.amount) + "."
                     )
            return False
        return True


class MigrateDonation(MigrateModel):
    from_model = LegacyDonationLine
    to_model = Donation
    
    def list_from(self):
        qs = super(MigrateDonation, self).list_from()
        qs = qs.select_related('donation', 'donation__member')
        return qs
    
    def list_to(self):
        qs = super(MigrateDonation, self).list_to()
        qs = qs.select_related('user', 'project')
        return qs

    field_mapping = {
        'id': True,
        'donation': DonationMapping(),
        'project': None,
        'project_id': True,
        'amount': StringToDecimalMapping(),
        'settlementline': None,
        # TODO: This doesn't work perfectly. Donations that don't have a value set
        # for 'changed_to_safe' (e.g. 'canceled' and 'chargedback') will have
        # 'updated' set to the migration time. One possible solution is to set
        # the 'updated' field to the 'created' time plus a bit of time (1 hour
        # or 1 day or whatever) when 'changed_to_safe' hasn't been set.
        'changed_to_safe': AutoUpdatedDateTimeMapping(to_field='updated'),

    }