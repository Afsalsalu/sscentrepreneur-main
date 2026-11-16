from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("exam", "0021_alter_temporaryuser_email"),
    ]

    operations = [
        migrations.CreateModel(
            name="QualifiedUserSync",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source_user_id", models.PositiveBigIntegerField()),
                ("source_candidate_id", models.PositiveBigIntegerField(unique=True)),
                ("idempotency_key", models.CharField(max_length=255, unique=True)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("succeeded", "Succeeded"), ("failed", "Failed"), ("rejected", "Rejected")], default="pending", max_length=20)),
                ("attempt_count", models.PositiveIntegerField(default=0)),
                ("last_sync_at", models.DateTimeField(blank=True, null=True)),
                ("next_retry_at", models.DateTimeField(blank=True, null=True)),
                ("last_http_status", models.PositiveIntegerField(blank=True, null=True)),
                ("last_error", models.TextField(blank=True, default="")),
                ("response_excerpt", models.CharField(blank=True, default="", max_length=1000)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("candidate", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="qualified_user_sync", to="exam.temporaryuser")),
            ],
            options={"ordering": ("-updated_at",)},
        ),
    ]
