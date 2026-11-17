from django.core.management.base import BaseCommand, CommandError

from integrations.services import sync_qualified_user
from web.models import CentreUserAccount


class Command(BaseCommand):
    help = (
        'Re-sync one existing CentreUserAccount to SSCEGOV by username or '
        'CentreUserAccount ID.'
    )

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--username', help='Exact CentreUserAccount username.')
        group.add_argument(
            '--centre-account-id',
            type=int,
            help='Primary key of the existing CentreUserAccount.',
        )

    def handle(self, *args, **options):
        lookup = {'username': options['username']} if options['username'] else {
            'pk': options['centre_account_id']
        }
        try:
            centre_user = CentreUserAccount.objects.select_related('user').get(**lookup)
        except CentreUserAccount.DoesNotExist as exc:
            selector = options['username'] or options['centre_account_id']
            raise CommandError(
                f'CentreUserAccount not found for {selector!r}.'
            ) from exc
        except CentreUserAccount.MultipleObjectsReturned as exc:
            raise CommandError(
                f"More than one CentreUserAccount matched username "
                f"{options['username']!r}. Use --centre-account-id."
            ) from exc

        result = sync_qualified_user(centre_user)
        if not result.success:
            raise CommandError(
                f'SSCEGOV sync failed for CentreUserAccount id={centre_user.pk}: '
                f'{result.message}'
            )

        self.stdout.write(
            self.style.SUCCESS(
                f'SSCEGOV sync succeeded for CentreUserAccount '
                f'id={centre_user.pk} username={centre_user.username}.'
            )
        )
