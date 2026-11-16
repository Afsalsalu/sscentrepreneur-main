from django.core.management.base import BaseCommand, CommandError

from exam.models import TemporaryUser

from integrations.services import get_or_create_sync, sync_qualified_user


class Command(BaseCommand):
    help = "Synchronize one final-exam-qualified candidate to sscegov.com"

    def add_arguments(self, parser):
        parser.add_argument("--candidate-id", type=int, required=True)

    def handle(self, *args, **options):
        try:
            candidate = TemporaryUser.objects.select_related("user").get(
                pk=options["candidate_id"]
            )
        except TemporaryUser.DoesNotExist as exc:
            raise CommandError("Candidate was not found") from exc

        sync_record, _ = get_or_create_sync(candidate)
        result = sync_qualified_user(sync_record)
        self.stdout.write(result.message)
        if not result.success and result.status != "rejected":
            raise CommandError(result.message)
