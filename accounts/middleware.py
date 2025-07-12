from django.utils import timezone

class UpdateLastActivityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            # Update last_activity on your UserModel instance, assuming one per user
            try:
                user_model_instance = request.user.userModel.first()  # because related_name='userModel' is a reverse FK manager
                if user_model_instance:
                    user_model_instance.last_activity = timezone.now()
                    user_model_instance.save(update_fields=['last_activity'])
            except Exception:
                pass  # Handle missing userModel gracefully

        response = self.get_response(request)
        return response