import sys
from apps.projects.models import Project
from apps.wallposts.models import MediaWallPost, TextWallPost, MediaWallPostPhoto
from legacy.legacymigration.reactions import ReactionMigrationMixin
import settings
from legacy.legacymembers.models import Member
from legacy.legacymigration.mappings import CropMapping, OneToManyMapping, StringMapping, PathToFileMapping
from legacy.legacyprojects.models import Video as LegacyVideo
from legacy.legacyprojects.models import Message as LegacyProjectMessage
from legacy.legacyalbums.models import Album as LegacyAlbum
from legacy.legacyalbums.models import Picture as LegacyPicture
from .base import MigrateModel
from .projects import MigrateProject
from .mappings import AutoUpdatedDateTimeMapping

import logging
logger = logging.getLogger(__name__)


class MigrateVideoWallPosts(ReactionMigrationMixin, MigrateModel):
    from_model = LegacyVideo
    to_model = MediaWallPost
    reaction_to_field = 'prj_project_videos'

    def migrate_single(self, from_instance, to_instance):
        super(MigrateVideoWallPosts, self).migrate_single(from_instance, to_instance)
        setattr(to_instance, 'author_id', from_instance.project.owner_usr.id)

    def post_save(self, from_instance, to_instance):
        # Migrate the reactions.
        self.migrate_reactions(from_instance, to_instance, self.reaction_to_field)

    def get_to(self, from_instance):
        # Create a new MediaWallPost to migrate to.
        project = Project.objects.get(pk=from_instance.project_id)
        return MediaWallPost(content_object=project)

    def test_multiple(self, from_qs):
        # Test the album query set counts.
        video_success = self.test_count_querysets()

        # Test the reaction queryset counts.
        reaction_success = self.test_migrated_reactions(from_qs, self.reaction_to_field)

        # Return true when everything worked.
        return video_success and reaction_success

    def list_from(self):
        qs = super(MigrateVideoWallPosts, self).list_from()

        # Don't migrate videos for projects we're not migrating.
        m = MigrateProject()
        project_list = m._list_from()
        qs = qs.filter(project__in=project_list)

        return qs

    field_mapping = {
        'id': None,
        'event': None,
        'url': None,
        'created': OneToManyMapping(
            AutoUpdatedDateTimeMapping(to_field='created'),
            AutoUpdatedDateTimeMapping(to_field='updated'),
        ),
        'name': CropMapping(length=60, to_field='title', reportDataChanges=True),
        'project': None,  # Mapped when MediaWallPost is created in get_to() above.
        'thumb': None,
        'watch_url': 'video_url'
    }


class MigrateTextWallPosts(ReactionMigrationMixin, MigrateModel):
    from_model = LegacyProjectMessage
    to_model = TextWallPost
    reaction_to_field = 'prj_messages'

    def migrate_single(self, from_instance, to_instance):
        super(MigrateTextWallPosts, self).migrate_single(from_instance, to_instance)

        # Don't set the author_id for messages from guests.
        if not hasattr(self, '_legacy_guest_list'):
            self._legacy_guest_list = Member.objects.using(MigrateModel.from_db).filter(username='guest').all()
        member = [m for m in self._legacy_guest_list if m.id == from_instance.member_id]
        if not member:
            setattr(to_instance, 'author_id', from_instance.member_id)

    def post_save(self, from_instance, to_instance):
        # Migrate the reactions.
        self.migrate_reactions(from_instance, to_instance, self.reaction_to_field)

    def get_to(self, from_instance):
        # Create a new TextWallPost to migrate to.
        project = Project.objects.get(pk=from_instance.project_id)
        return TextWallPost(content_object=project)

    def test_multiple(self, from_qs):
        # Test the album query set counts.
        message_success = self.test_count_querysets()

        # Test the reaction queryset counts.
        reaction_success = self.test_migrated_reactions(from_qs, self.reaction_to_field)

        # Return true when everything worked.
        return message_success and reaction_success

    def list_from(self):
        qs = super(MigrateTextWallPosts, self).list_from()

        # Don't migrate messages for projects we're not migrating.
        m = MigrateProject()
        project_list = m._list_from()
        qs = qs.filter(project__in=project_list)

        qs = qs.filter(event__isnull=False)

        return qs

    field_mapping = {
        'id': None,
        'event': None,
        'created': OneToManyMapping(
            AutoUpdatedDateTimeMapping(to_field='created'),
            AutoUpdatedDateTimeMapping(to_field='updated'),
        ),
        'deleted': AutoUpdatedDateTimeMapping(),
        'member': None,  # Migrated in migrate_single above.
        'member_id': None, # Migrated in migrate_single above.
        'text': True,
        'project': None,  # Mapped when TextWallPost is created in get_to() above.
        'project_id': None,
    }


class MigratePhotoWallPosts(ReactionMigrationMixin, MigrateModel):
    """
    Migrate photo albums along with the photos.
    """

    from_model = LegacyAlbum
    to_model = MediaWallPost
    reaction_to_field = 'alb_albums'

    photo_mapping = PathToFileMapping(root_path=settings.LEGACY_MEDIA_ROOT + '/assets/files/filemanager',
                                      allow_missing=True, download_prefix='assets/files/filemanager')

    def _get_legacy_project(self, from_instance):
        # Safety check that there's only one legacy project for the album.
        if from_instance.catalog:
            projects = from_instance.catalog.project_set.all()
            if len(projects) != 1:
                logger.error("Can't find required Legacy Project. Album catalog project_set length is not 1.")
                sys.exit(1)
            return projects[0]
        else:
            logger.error("Can't find required Legacy Project. No album catalog found.")
            sys.exit(1)

    def migrate_single(self, from_instance, to_instance):
        super(MigratePhotoWallPosts, self).migrate_single(from_instance, to_instance)
        # Set the author from the legacy project owner.
        legacy_project = self._get_legacy_project(from_instance)
        setattr(to_instance, 'author_id', legacy_project.owner_usr.id)

    def post_save(self, from_instance, to_instance):
        # Create and migrate the album pictures.
        for picture in from_instance.picture_set.all():
            # Create a new MediaWallPostPhoto
            photo = MediaWallPostPhoto()
            photo.mediawallpost = to_instance

            # Manually do the file migration.
            old_value = getattr(picture.file, 'file')
            new_value = self.photo_mapping.map_value(old_value)
            setattr(photo, 'photo', new_value)

            # Save the migrated photo.
            photo.save()

        # Migrate the reactions.
        self.migrate_reactions(from_instance, to_instance, self.reaction_to_field)

    def get_to(self, from_instance):
        # Create a new MediaWallPost to migrate to.
        legacy_project = self._get_legacy_project(from_instance)
        project = Project.objects.get(pk=legacy_project.id)
        return MediaWallPost(content_object=project)

    def test_multiple(self, from_qs):
        # Test the album query set counts.
        album_success = self.test_count_querysets()

        # Test the picture queryset counts.
        picture_success = True
        from_picture_count = LegacyPicture.objects.using(self.from_db).all().count()
        to_picture_count = MediaWallPostPhoto.objects.using(self.to_db).all().count()
        if from_picture_count != to_picture_count:
            logger.error(
                u'LegacyPicture queryset contains %d objects while MediaWallPostPhoto queryset contains %d',
                from_picture_count, to_picture_count
            )
            picture_success = False

        # Test the reaction queryset counts.
        reaction_success = self.test_migrated_reactions(from_qs, self.reaction_to_field)

        # Return true when everything worked.
        return album_success and picture_success and reaction_success

    def list_to(self):
        # This works for the test_count_querysets() for now but might have to be updated in the future.
        return MediaWallPost.objects.using(self.to_db).filter(video_url='')

    def list_from_exclusions(self, qs):
        # Exclude albums without pictures
        return  qs.exclude(picture=None)

    def list_from(self):
        qs = super(MigratePhotoWallPosts, self).list_from()

        # Don't migrate videos for projects we're not migrating.
        m = MigrateProject()
        project_list = m._list_from()
        qs = qs.filter(catalog__project__in=project_list)

        return qs

    field_mapping = {
        'name': CropMapping(to_field='title', length=60, reportDataChanges=True),
        'description': StringMapping(to_field='text'),
        'created': AutoUpdatedDateTimeMapping(),
        'updated': AutoUpdatedDateTimeMapping(),
        'id': None,
        'folder': None,
        'catalog': None,  # Photo wallposts relate to projects now directly.
        'picture': None,
        'event': None,
    }
