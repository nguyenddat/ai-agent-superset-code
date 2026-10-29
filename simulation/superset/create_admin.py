import os

from superset.app import create_app


app = create_app()
with app.app_context():
    security_manager = app.appbuilder.sm
    username = os.getenv("SUPERSET_ADMIN_USERNAME", "admin")
    if security_manager.find_user(username=username) is None:
        admin_role = security_manager.find_role("Admin")
        security_manager.add_user(
            username=username,
            first_name=os.getenv("SUPERSET_ADMIN_FIRST_NAME", "Superset"),
            last_name=os.getenv("SUPERSET_ADMIN_LAST_NAME", "Admin"),
            email=os.getenv("SUPERSET_ADMIN_EMAIL", "admin@example.com"),
            role=admin_role,
            password=os.environ["SUPERSET_ADMIN_PASSWORD"],
        )
