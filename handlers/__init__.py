from .start import router as start_router
from .home import router as home_router
from .settings import router as settings_router
from .admin_users import router as admin_users_router
from .teaching import router as teaching_router
from .admin_subjects import router as admin_subjects_router
from .schedule import router as schedule_router
from .profile import router as profile_router
from .homework import router as homework_router
from .errors import router as errors_router

routers = [
    start_router,
    home_router,
    settings_router,
    admin_users_router,
    teaching_router,
    admin_subjects_router,
    schedule_router,
    profile_router,
    homework_router,
    errors_router
]