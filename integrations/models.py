from django.db import models


class QualifiedUserSync(models.Model):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"

    STATUS_CHOICES = [
        (PENDING, "Pending"),
        (SUCCEEDED, "Succeeded"),
        (FAILED, "Failed"),
        (REJECTED, "Rejected"),
    ]

    candidate = models.OneToOneField(
        "exam.TemporaryUser",
        on_delete=models.CASCADE,
        related_name="qualified_user_sync",
    )
    source_user_id = models.PositiveBigIntegerField()
    source_candidate_id = models.PositiveBigIntegerField(unique=True)
    idempotency_key = models.CharField(max_length=255, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)
    attempt_count = models.PositiveIntegerField(default=0)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    last_http_status = models.PositiveIntegerField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    response_excerpt = models.CharField(max_length=1000, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)

    def __str__(self):
        return f"{self.source_candidate_id}: {self.status}"
