from apps.reactions.models import Reaction
from django.contrib.contenttypes.models import ContentType
from legacy.legacyevents.models import Reaction as LegacyReaction

import logging
logger = logging.getLogger(__name__)


class ReactionMigrationMixin(object):
    """
    Adds methods to migrate and test the migrated Reactions. This should be mixed with a MigrateModel.
    See WallPosts for example usage.
    """

    def migrate_reactions(self, from_instance, to_instance, reaction_to_field):
        # TODO: Ask Loek if we should be filter through the events table.
        event_filter = 'event__' + reaction_to_field
        content_type = ContentType.objects.get_for_model(to_instance)
        reactions = LegacyReaction.objects.using(self.from_db).filter(**{event_filter: from_instance})
        for legacy_reaction in reactions:
            reaction = Reaction()
            reaction.author_id = legacy_reaction.from_member_id
            reaction.text = legacy_reaction.text
            reaction.content_type = content_type
            reaction.object_id = to_instance.id
            reaction.save()

            self.migrate_auto_updated_datetime(legacy_reaction, reaction, 'created', 'created')
            self.migrate_auto_updated_datetime(legacy_reaction, reaction, 'created', 'updated')
            if legacy_reaction.deleted:
                self.migrate_auto_updated_datetime(legacy_reaction, reaction, 'deleted', 'deleted')

    def test_migrated_reactions(self, from_qs, reaction_to_field):
        # TODO: Ask Loek if we should be filter through the events table.
        event_filter = 'event__' + reaction_to_field
        reaction_success = True
        for from_instance in from_qs:
            from_reaction_count = LegacyReaction.objects.using(self.from_db).filter(**{event_filter: from_instance}).count()
            from_created = self.make_datetime_timezone_aware(from_instance.created)

            to_instances = self.to_model.objects.filter(created=from_created)
            if len(to_instances) != 1:
                logger.error(u"Can't find from_instance that corresponds to to_instance %s.", from_instance)
                reaction_success = False
                continue

            to_reaction_count = Reaction.objects.for_model(to_instances[0]).count()

            if from_reaction_count != to_reaction_count:
                logger.error(
                    u'LegacyReaction queryset to a %s contains %d objects while Reaction queryset to a %s contains %d',
                    from_instance, from_reaction_count, to_instances[0], to_reaction_count
                )
                reaction_success = False

        return reaction_success
