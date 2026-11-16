from django.core.management.base import BaseCommand

from exam.models import TemporaryUser

from integrations.services import get_or_create_sync, sync_qualified_user


class Command(BaseCommand):
    help = "Synchronize all candidates already marked as final-exam qualified"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=0)

    def handle(self, *args, **options):
        candidates = TemporaryUser.objects.filter(main_exam_passed=True).select_related("user")
        if options["limit"]:
            candidates = candidates[: options["limit"]]

        succeeded = failed = rejected = 0
        for candidate in candidates:
            sync_record, _ = get_or_create_sync(candidate)
            result = sync_qualified_user(sync_record)
            if result.success:
                succeeded += 1
            elif result.status == "rejected":
                rejected += 1
            else:
                failed += 1
            self.stdout.write(f"{candidate.pk}: {result.status} - {result.message}")

        self.stdout.write(
            self.style.SUCCESS(
                f"Completed: {succeeded} succeeded, {failed} failed, {rejected} rejected"
            )
        )
