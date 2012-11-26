import logging
logger = logging.getLogger(__name__)

import settings

from django.db.models import Q

from legacy.legacyprojects.models import (
    Project as LegacyProject,
    Link as LegacyLink,
    Testimonial as LegacyTestimonial,
    Message as LegacyMessage,
    NeedCategory, Need
)

from apps.projects.models import (
    Project, IdeaPhase, FundPhase, ActPhase, ResultsPhase,
    Link, Testimonial, Message, BudgetLine, PartnerOrganization
)

from .base import MigrateModel, UniqueSlugMixin

from .mappings import (
    MappingMapping, EducateDateTimeMapping,
    StringMapping, OneToManyMapping, CountryMapping,
    TolerantSlugifyCroppingMapping, IdentityMapping, WebsiteMapping,
    StringToDecimalMapping, ConcatenatingStringMapping,
    PathToFileMapping, CropMapping, DateTimeToDateMapping,
    AutoUpdatedDateTimeMapping
)

from .organizations import MigrateOrganization
from .accounts import MigrateMemberAuth
from .tags import copy_tags, test_tags


# We want a handy reference to these status objects
phases = Project.ProjectPhases
statuses = FundPhase.PhaseStatuses
results_phase_tag = 'evaluatie'

class PhaseMapping(IdentityMapping):
    """ Map a Project into its current phase. """

    # Mapping from legacy project status in DB to UI:
    #   wizard -> Is being created
    #   created -> Created
    #   confirmed -> With 1%Coach
    #   approved -> Waiting for referrals
    #   validated -> Open
    #   done -> Realized
    #   closed -> Closed
    #   declined -> Declined
    # These are used in this mapping and in MigrateIdea, MigrateFund, MigrateAct, MigrateResults
    idea_statuses = ('wizard', 'created', 'confirmed', 'approved', 'declined')
    fund_statuses = ('validated',)
    act_statuses = ('done', 'closed')

    def __init__(self, to_field=None, reportDataChanges=False):
        super(PhaseMapping, self).__init__(to_field, reportDataChanges)
        self.cached_project_tags = {}

    def map_value(self, old_value):
        if old_value in self.idea_statuses:
            # Idea phase
            phase = phases.idea

        elif old_value in self.fund_statuses:
            # Fund phase
            phase = phases.fund

        elif old_value in self.act_statuses:
            # The act phase is used temporarily for the act and results phase.
            # The correct phase is set in the map() method below.
            phase = phases.act

        else:
            raise Exception(u"Could not map '%s' to a phase.", old_value)

        return phase

    # Caches the project tags so they can be used in both the map() and check() methods.
    def get_project_tags(self, from_instance):
        if self.cached_project_tags.has_key(from_instance.pk):
            return self.cached_project_tags[from_instance.pk]
        else:
            project_tags = []
            for tag_object in from_instance.projecttag_set.all():
                project_tags.append(tag_object.tag.name)
            self.cached_project_tags[from_instance.pk] = project_tags
            return project_tags

    # Override map() to set the act or results phase based on the 'evaluatie' tag.
    def map(self, from_instance, from_field):
        value_dict = super(PhaseMapping, self).map(from_instance, from_field)

        to_field = self.get_to_field(from_field)
        if value_dict[to_field] == phases.act:
            if results_phase_tag in self.get_project_tags(from_instance):
                value_dict[to_field] = phases.results

        return value_dict

    # Override check() to check the act or results phase base on the 'evaluatie' tag.
    def check(self, from_instance, to_instance, from_field):
        new_value = getattr(to_instance, self.get_to_field(from_field))

        if new_value == phases.act:
            return results_phase_tag not in self.get_project_tags(from_instance)
        elif new_value == phases.results:
            return results_phase_tag in self.get_project_tags(from_instance)
        else:
            return super(PhaseMapping, self).check(from_instance, to_instance, from_field)


class PartnerMapping(IdentityMapping):
    """ migrate projects with partner organizations """

    def __init__(self, to_field=None, reportDataChanges=False):
        super(PartnerMapping, self).__init__(to_field, reportDataChanges)

    def get_partner_organization(self, slug):
        """
            We gonna look up if we can find partner org.
            If not than we should stop right here...
        """
        try:
            org = PartnerOrganization.objects.get(slug=slug)
            return org
        except PartnerOrganization.DoesNotExist:
            raise Exception(u"PartnerOrganization %s not found. "
              u"Did you load fixture project_partnerorganization_data.json?" % slug)
        return None

    def map(self, instance, from_field):
        new_value = None
        if getattr(instance, 'derde_helft'):
            new_value = self.get_partner_organization('derde_helft')
        if getattr(instance, 'earth_charter'):
            new_value = self.get_partner_organization('earth_charter')
        if getattr(instance, 'macro_micro'):
            new_value = self.get_partner_organization('macro_micro')
        return {self.get_to_field(from_field): new_value}

    def check(self, from_instance, to_instance, from_field):
        org = getattr(to_instance, 'partner_organization')
        if org == None:
            # If there's no partner org then these
            # values shouldnt be set
            if getattr(from_instance, 'derde_helft'):
                return False
            if getattr(from_instance, 'earth_charter'):
                return False
            if getattr(from_instance, 'macro_micro'):
                return False
            return True
        elif getattr(from_instance, 'derde_helft'):
            if org.slug == 'derde_helft':
                return True
            return False
        elif getattr(from_instance, 'earth_charter'):
            if org.slug == 'earth_charter':
                return True
            return False
        elif getattr(from_instance, 'macro_micro'):
            if org.slug == 'macro_micro':
                return True
            return False
        return False


class MigrateProjectBase(MigrateModel):
    from_model = LegacyProject
    to_model = Project

    def list_from_exclusions(self, qs):
        """ Perform explicit exclusions on the queryset for dirty data. """

        # Exclude projects without a name or title, for now
        qs = qs.exclude(Q(name='') | Q(title=''))

        # Exclude test projects
        qs = qs.exclude(
            Q(name__contains='test') | Q(title__contains='test') | \
            Q(name__contains='proef') | Q(title__contains='proef')
        )

        return qs

    def list_from(self):
        """
        For now, skip projects which we cannot migrate.
        """
        qs = super(MigrateProjectBase, self).list_from()

        # Only migrate for available organizations
        m = MigrateOrganization()
        qs = qs.filter(organization__in=m._list_from())

        return qs

    # Fields handled by project & phases
    mapped_in_project = {
        'name': None,
        'photo': None,
        'owner_usr': None,
        'owner_usr_id': None,
        'organization': None,
        'organization_id': None,
        'derde_helft': None,
        'macro_micro': None,
        'earth_charter': None,
        'country': None,
        'latitude': None,
        'longitude': None,
        'project_language': None,
        'tags': None,
        'startdate': None,
        'enddate': None,
    }

    mapped_in_idea = {
        'how_support': None,
        'volunteers': None,
        'money_needed_for': None
    }

    mapped_in_fund = {
        'expected_results': None,
        'longdescription':None,
        'money_needed_club': None,
        'target_audience': None,
        'solve_poverty': None,
        'description_duurzaamheid':None,
        'received_other_sources':None,
        'expected_other_sources': None
    }

    mapped_in_act = {
        'planning': None,
    }

    mapped_in_results = {
    }

    # Project fields we'll throw away
    throw_away_fields = {
        'action': None,
        'admin_comments': None,
        'sess_id': None,
        'closed': None,
        'deleted': None,
        'document': None,
        'folder': None,
        'goal': None,
        'picture': None,
        'planning': None,
        'portfolioline': None,
        'project_goals': None,
        'video': None,
        'reported': None,
        'testimonial': None,
        'legacy_budget': None,

        # Explicitly mapped by MigrateProjectAlbums
        'catalog': None,

        # To be migrated later
        'link': None,
        'message': None,
        'task': None,
        'weblog': None,

        'projecttag': None,

        'rate_count': None,
        'rate_current': None,
        'rating': None,

        # Donations and money
        'donationline': None,
        'settlement': None,
        'projectdonations': None,

        'money_needed_for': None,
        'need': None,
    }


class ProjectPathToFileMapping(PathToFileMapping):
    """ Special PathToFileMapping that we can detect in the Migrate class """
    def __init__(self, **kwargs):
        self.project = True
        super(ProjectPathToFileMapping, self).__init__(**kwargs)


class MigrateProject(UniqueSlugMixin, MigrateProjectBase):
    """ Migrations for projects. """

    def migrate_single(self, from_instance, to_instance):
        """
        Override migrate_single so that tags can be copied over using the
        Taggit manager.
        """
        super(MigrateProject, self).migrate_single(from_instance, to_instance)

        copy_tags(from_instance, to_instance)

    def test_single(self, from_instance, to_instance):
        """
        Override test_single so that the tags that have been copied over using
        the Taggit manager can be tested.
        """
        super_result = super(MigrateProject, self).test_single(from_instance, to_instance)

        tags_result = test_tags(from_instance, to_instance, logger)

        return super_result and tags_result

    field_mapping = {
        'id': True,

        'name': TolerantSlugifyCroppingMapping(100, to_field='slug'),
        'title': StringMapping(),

        'photo': ProjectPathToFileMapping(
            root_path=settings.LEGACY_MEDIA_ROOT,
            allow_missing=True,
            download_prefix='',
            to_field='image'
        ),

        # Map related PK's for owner and organization directly
        'owner_usr': None,
        'owner_usr_id': 'owner_id',
        'organization': None,
        'organization_id': True,

        'status': PhaseMapping('phase'),

        'created': EducateDateTimeMapping(),

        'country': CountryMapping(),
        'latitude': StringToDecimalMapping(),
        'longitude': StringToDecimalMapping(),

        'derde_helft': PartnerMapping('partner_organization'),
        'earth_charter': None, # Done by derde_helft
        'macro_micro': None, # Done by derde_helft

        'project_language': 'language',

        # Tags are copied over in migrate_single().
        'tags': None,

        # Migrated in phases
        'description': None,

        # User set start/end dates.
        'startdate': 'planned_start_date',
        'enddate': 'planned_end_date',

        # Not mapped in Project but used in some phases.
        'realised': None,
        'validated': None,
    }

    field_mapping.update(MigrateProjectBase.throw_away_fields)
    field_mapping.update(MigrateProjectBase.mapped_in_idea)
    field_mapping.update(MigrateProjectBase.mapped_in_fund)
    field_mapping.update(MigrateProjectBase.mapped_in_act)
    field_mapping.update(MigrateProjectBase.mapped_in_results)


class MigrateIdea(MigrateProjectBase):
    to_model = IdeaPhase

    # Note: We don't need to override list_from() and list_to() because all
    # projects have an idea phase.

    field_mapping = {
        'id': OneToManyMapping(
            IdentityMapping('id'),
            IdentityMapping('project_id')
        ),
        'title': StringMapping(),
        'description': StringMapping(),
        'created': DateTimeToDateMapping(to_field='startdate'),
        'validated': DateTimeToDateMapping(to_field='enddate'),

        # Not mapped in Idea but used in other phases.
        'realised': None,

        'volunteers': ConcatenatingStringMapping(
            to_field='knowledge_description',
            concatenate_with=('how_support',),
            concatenate_str='\n\n',
        ),
        # This field is mapped above but this needs to be here to ignore the
        # warning message about how_support not being mapped.
        'how_support': None,

        'money_needed_for': StringMapping('money_description'),

        # TODO: These are not mapped correctly and need to be fixed.
        'status': MappingMapping({
            'done': statuses.completed,
            'closed': statuses.completed,
            'validated': statuses.completed,
            'confirmed': statuses.completed,
            'declined': statuses.completed,
            'created': statuses.progress,
            'wizard': statuses.hidden,
            'approved': statuses.waiting,
        }),

    }

    field_mapping.update(MigrateProjectBase.throw_away_fields)
    field_mapping.update(MigrateProjectBase.mapped_in_project)
    field_mapping.update(MigrateProjectBase.mapped_in_fund)
    field_mapping.update(MigrateProjectBase.mapped_in_act)
    field_mapping.update(MigrateProjectBase.mapped_in_results)


class MigrateFund(MigrateProjectBase):
    to_model = FundPhase

    def list_from(self):
        """ Filter by projects in and after fund phase (i.e. not in idea phase) """
        qs = super(MigrateFund, self).list_from()
        qs = qs.exclude(status__in=PhaseMapping.idea_statuses)
        return qs

    def list_to(self):
        """ Filter by projects in and after fund phase."""
        qs = super(MigrateFund, self).list_to()
        qs = qs.filter(project__phase__in=(phases.fund, phases.act, phases.results))
        return qs


    field_mapping = {
        'id': OneToManyMapping(
            IdentityMapping('id'),
            IdentityMapping('project_id')
        ),
        'title': StringMapping(),
        'description': StringMapping(),
        'validated': DateTimeToDateMapping(to_field='startdate'),
        'realised': DateTimeToDateMapping(to_field='enddate'),

        # Not mapped in Fund but used in other phases.
        'created': None,

        # TODO: These are not mapped correctly and need to be fixed.
        'status': MappingMapping({
            'done': statuses.completed,
            'closed': statuses.completed,
            'realised': statuses.completed,

            'confirmed': statuses.progress,
            'validated': statuses.progress
        }),

        'longdescription': ConcatenatingStringMapping(
            to_field='description_long',
            concatenate_with=('project_goals', 'expected_results',),
            concatenate_str='<br/>'
        ),
        'target_audience': ConcatenatingStringMapping(
            to_field='social_impact',
            concatenate_with=('solve_poverty',),
            concatenate_str='<br/>'
        ),
        'solve_poverty': None, # Already mapped above
        'description_duurzaamheid':
            StringMapping('sustainability'),
        'expected_results': None, # Already mapped above
        'money_needed_club': OneToManyMapping(
            StringToDecimalMapping('money_asked'),
            StringToDecimalMapping('budget_total')
        ),
        'received_other_sources': ConcatenatingStringMapping(
            to_field='money_other_sources',
            concatenate_with=('expected_other_sources',),
            concatenate_str='<br/>'
        ),

        'expected_other_sources': None, #Already mapped above
    }

    def pre_validate(self, from_instance, to_instance):
        # Set money_donated to 0 so validation passes before the model is saved.
        to_instance.money_donated = 0

    field_mapping.update(MigrateProjectBase.throw_away_fields)
    field_mapping.update(MigrateProjectBase.mapped_in_project)
    field_mapping.update(MigrateProjectBase.mapped_in_idea)
    field_mapping.update(MigrateProjectBase.mapped_in_act)
    field_mapping.update(MigrateProjectBase.mapped_in_results)


class MigrateAct(MigrateProjectBase):
    to_model = ActPhase

    def list_from(self):
        """ Filter by projects in and after fund phase."""
        qs = super(MigrateAct, self).list_from()
        qs = qs.exclude(status__in=(PhaseMapping.idea_statuses + PhaseMapping.fund_statuses))
        return qs

    def list_to(self):
        """ Filter by projects in and after the act phase."""
        qs = super(MigrateAct, self).list_to()
        qs = qs.filter(project__phase__in=(phases.act, phases.results))
        return qs

    field_mapping = {
        'id': OneToManyMapping(
            IdentityMapping('id'),
            IdentityMapping('project_id')
        ),
        'title': StringMapping(),
        'description': StringMapping(),
        'realised': OneToManyMapping(
            DateTimeToDateMapping(to_field='startdate'),
            DateTimeToDateMapping(to_field='enddate'),
        ),

        # Not mapped in Act but used in other phases.
        'created': None,
        'validated': None,

        # TODO: These are not mapped correctly and need to be fixed.
        'status': MappingMapping({
            'done': statuses.completed,
            'closed': statuses.completed,
        }),

        'planning': True
    }

    field_mapping.update(MigrateProjectBase.throw_away_fields)
    field_mapping.update(MigrateProjectBase.mapped_in_project)
    field_mapping.update(MigrateProjectBase.mapped_in_idea)
    field_mapping.update(MigrateProjectBase.mapped_in_fund)
    field_mapping.update(MigrateProjectBase.mapped_in_results)


class MigrateResults(MigrateProjectBase):
    to_model = ResultsPhase

    def list_from(self):
        """ Filter by project status. """
        qs = super(MigrateResults, self).list_from()
        # Projects in the results phase have the 'evaluatie' tag.
        qs = qs.filter(projecttag__tag__name=results_phase_tag)
        return qs

    def list_to(self):
        """ Filter by projects in results phase. """
        qs = super(MigrateResults, self).list_to()
        qs = qs.filter(project__phase=phases.results)
        return qs

    field_mapping = {
        'id': OneToManyMapping(
            IdentityMapping('id'),
            IdentityMapping('project_id')
        ),
        'title': StringMapping(),
        'description': StringMapping(),
        'realised': OneToManyMapping(
            DateTimeToDateMapping(to_field='startdate'),
            DateTimeToDateMapping(to_field='enddate'),
        ),

        # Not mapped in Results but used in other phases.
        'created': None,
        'validated': None,

        'status': MappingMapping({
            'done': statuses.completed,
            'closed': statuses.completed,
        }),
    }

    field_mapping.update(MigrateProjectBase.throw_away_fields)
    field_mapping.update(MigrateProjectBase.mapped_in_project)
    field_mapping.update(MigrateProjectBase.mapped_in_idea)
    field_mapping.update(MigrateProjectBase.mapped_in_fund)
    field_mapping.update(MigrateProjectBase.mapped_in_act)


class MigrateLink(MigrateModel):
    from_model = LegacyLink
    to_model = Link

    def list_from(self):
        """ Filter by project status. """
        qs = super(MigrateLink, self).list_from()

        m = MigrateProject()
        project_list = m._list_from()

        qs = qs.filter(project__in=project_list)

        return qs

    field_mapping = {
        'id': True,

        'project': None,
        'project_id': True,

        'name': True,
        'url': WebsiteMapping(),
        'description': True,
        'ordering': True

    }


class MigrateTestimonial(MigrateLink):
    from_model = LegacyTestimonial
    to_model = Testimonial

    def list_from(self):
        """ Only filter addresses for migrated members. """
        qs = super(MigrateTestimonial, self).list_from()

        m = MigrateMemberAuth()
        member_list = m._list_from()

        qs = qs.filter(member__in=member_list)

        return qs

    field_mapping = {
        'id': True,

        'project': None,
        'project_id': True,

        'member': None,
        'member_id': 'user_id',

        'description': True,

        'created': EducateDateTimeMapping(),
        'updated': AutoUpdatedDateTimeMapping(),
    }


class MigrateMessage(MigrateTestimonial):
    from_model = LegacyMessage
    to_model = Message

    field_mapping = {
        'id': True,

        'project': None,
        'project_id': True,

        'member': None,
        'member_id': 'user_id',

        'text': 'body',

        'created': EducateDateTimeMapping(),
        'deleted': EducateDateTimeMapping()
    }


class DescriptionCropMapping(CropMapping):
    """
    Custom version of CropMapping for description in MigrateBudgetLine.
    """

    def map(self, from_instance, from_field):
        value_dict = super(DescriptionCropMapping, self).map(from_instance, from_field)

        to_field = self.get_to_field(from_field)
        if not value_dict[to_field]:
            value_dict[to_field] = str(from_instance.money_needed)

        return value_dict

    def check(self, from_instance, to_instance, from_field):
        old_value = getattr(from_instance, from_field)
        if not old_value:
            return to_instance.description == str(to_instance.money_amount)
        else:
            return super(DescriptionCropMapping, self).check(from_instance, to_instance, from_field)


# SubClass of MigrateLink only to use the list_from() method.
class MigrateBudgetLine(MigrateLink):
    from_model = Need
    to_model = BudgetLine

    field_mapping = {
        'id': True,

        'project': None,
        'project_id': True,

        'category': None,
        'category_id': None,

        'description': DescriptionCropMapping(length=255),

        'money_needed': StringToDecimalMapping('money_amount'),
    }

