import logging
logger = logging.getLogger(__name__)

import settings

from django.db.models import Q

from legacy.legacyprojects.models import Video as LegacyVideo
from legacy.legacyalbums.models import (
    Album as LegacyAlbum,
    Picture as LegacyPicture
)

from apps.media.models import Album, EmbeddedVideo, LocalPicture
from apps.projects.models import Project

from .base import MigrateModel, UniqueSlugMixin

from .projects import MigrateProject

from .mappings import (
    IdentityMapping, EducateDateTimeMapping, OneToManyMapping,
    TolerantSlugifyCroppingMapping, PathToFileMapping, AutoUpdatedDateTimeMapping
)


class ProjectToAlbumMapping(IdentityMapping):
    """ Map a project to an album with the same slug. """

    def __init__(self, *args, **kwargs):
        """ Allow for setting a prefix to the generated album's slug. """

        self.slug_prefix = kwargs.pop('prefix', '')

        super(ProjectToAlbumMapping, self).__init__(*args, **kwargs)

    def map_value(self, old_value):
        project = Project.objects.get(pk=old_value.pk)

        # Either create or find a 'default' album for a project by
        # project slug
        (album, created) = Album.objects.get_or_create(
            slug='%s-%s' % (self.slug_prefix, project.slug)
        )

        # If created, set title
        if created:
            album.title=project.title
            album.save()

            project.albums.add(album)

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug('Created album %s for project %s',
                    album.__unicode__(), project.__unicode__()
                )

        return album

    def check_value(self, old_value, new_value):
        """ Check whether the album is related to the project. """

        result = super(ProjectToAlbumMapping, self).check_value(
            old_value, new_value
        )

        album = new_value

        if result:
            if album.project_set.filter(pk=old_value.pk).exists():
                return True
            else:
                logger.error(
                    'Album %s should be related to project %s but is '
                    'related to %s instead.',
                    album.__unicode__(), old_value.__repr__(),
                    album.project_set.all().__repr__()
                )

                import ipdb; ipdb.set_trace()

        return False


class MigrateAlbum(UniqueSlugMixin, MigrateModel):
    """
    Migrate albums from old website to new.
    """

    from_model = LegacyAlbum
    to_model = Album

    def _migrate_from(self, from_instance):
        """ Explicitly associate the migrated album with projects. """
        to_instance = super(MigrateAlbum, self)._migrate_from(from_instance)

        if from_instance.catalog:
            for project in from_instance.catalog.project_set.all():
                new_project = Project.objects.get(pk=project.pk)
                to_instance.project_set.add(new_project)

    def list_from_exclusions(self, qs):
        """ Perform explicit exclusions on the queryset for dirty data. """

        # This ignores about 6 albums
        qs = qs.exclude(Q(name='*') | Q(name='.'))

        # Exclude albums without pictures
        qs = qs.exclude(picture=None)

        return qs

    def list_from(self):
        qs = super(MigrateAlbum, self).list_from()

        m = MigrateProject()
        project_list = m._list_from()

        # Only migrate albums for migrated projects
        qs = qs.filter(catalog__project__in=project_list)

        return qs

    def list_to(self):
        """ Prevent video albums from being mapped back. """
        qs = super(MigrateAlbum, self).list_to()

        qs = qs.exclude(slug__startswith='videos-')

        return qs

    field_mapping = {
        'id': True,
        'name': OneToManyMapping(
            IdentityMapping('title'),
            TolerantSlugifyCroppingMapping(
                100, to_field='slug')
        ),
        'description': True,

        'created': EducateDateTimeMapping(),
        'updated': AutoUpdatedDateTimeMapping(),

        # Not migrated
        'folder': None,

        # Left out, albums relate to projects now directly
        'catalog': None
    }


class MigratePicture(MigrateModel):
    from_model = LegacyPicture
    to_model = LocalPicture

    def list_from_exclusions(self, qs):
        """ Perform explicit exclusions on the queryset for dirty data. """

        # Exclude pictures that have no file set
        qs = qs.exclude(Q(file=None) | Q(file__file=None))

        return qs

    def list_from(self):
        qs = super(MigratePicture, self).list_from()

        # Only migrate pictures for migrated albums
        m = MigrateAlbum()
        album_list = m._list_from()

        qs = qs.filter(album__in=album_list)

        return qs

    field_mapping = {
        'id': True,
        'album': None,
        'album_id': True,
        'name': 'title',
        'description': True,
        'created': EducateDateTimeMapping(),
        # Skip for now (automagically overridden)
        #'updated': EducateDateTimeMapping(),

        'project': None,

        'file': {
            'file':
                PathToFileMapping(
                    root_path=settings.LEGACY_MEDIA_ROOT + '/assets/files/filemanager',
                    allow_missing=True,
                    download_prefix='assets/files/filemanager',
                    to_field='picture'
                ),
        }

    }


class MigrateVideo(MigrateModel):
    from_model = LegacyVideo
    to_model = EmbeddedVideo

    def list_from(self):
        qs = super(MigrateVideo, self).list_from()

        # Don't migrate videos for which no project has been set
        qs = qs.exclude(project=None)

        # Don't migrate video's for projects we're not migrating
        m = MigrateProject()
        project_list = m._list_from()
        qs = qs.filter(project__in=project_list)

        return qs

    field_mapping = {
        'id': True,

        'url': None,
        'created': EducateDateTimeMapping(),
        'name': 'title',
        'project': ProjectToAlbumMapping(
            'album', prefix='videos'
        ),

        # This will all be automatic now
        'thumb': None,
        'watch_url': 'url'
    }
