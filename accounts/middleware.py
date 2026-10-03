from datetime import timedelta

from django.utils import timezone

# Dashboards poll every few seconds; writing last_activity on every request
# would turn each poll into a database write.
ACTIVITY_WRITE_INTERVAL = timedelta(seconds=60)


class UpdateLastActivityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            try:
                profile = request.user.userModel.first()  # reverse FK manager (related_name='userModel')
                now = timezone.now()
                if profile and (profile.last_activity is None or now - profile.last_activity > ACTIVITY_WRITE_INTERVAL):
                    profile.last_activity = now
                    profile.save(update_fields=['last_activity'])
            except Exception:
                pass  # never block a request because of activity tracking

        return self.get_response(request)
