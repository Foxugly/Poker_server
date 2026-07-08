from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class UserManager(BaseUserManager):
    """Email-based manager (fleet convention, OPERATIONS.md §3.16).

    The stock ``UserManager`` keys off ``username``, which this model drops, so
    ``createsuperuser`` and programmatic creation must go through email instead.
    """

    use_in_migrations = True

    def _create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("The email must be set.")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    """Email-only user (no ``username``), created in Phase 1 so AUTH_USER_MODEL is
    fixed on a fresh DB and never swapped mid-project (avoids the foxugly
    InconsistentMigrationHistory pain, §3.16). Phase 1 only seeds superusers for
    the deck admin; anonymous room participants are NOT users."""

    username = None
    email = models.EmailField(unique=True)
    # Email ownership gate (Phase 2 auth). Present now so the shape matches the fleet.
    email_confirmed = models.BooleanField(default=False)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    def __str__(self):
        return self.email
