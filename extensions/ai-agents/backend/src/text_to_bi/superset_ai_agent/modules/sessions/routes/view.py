from flask import abort, redirect
from flask_appbuilder import expose
from flask_login import current_user
from superset import appbuilder, security_manager
from superset.views.base import BaseSupersetView


class AgentChatView(BaseSupersetView):
    route_base = "/ai-agent"

    @expose("/")
    def page(self):
        """Serve Superset's SPA shell; the extension frontend renders the chat page."""
        if not getattr(current_user, "is_authenticated", False):
            return redirect(appbuilder.get_url_for_login)
        if not security_manager.can_access("can_read", "text_to_bi_chat_api"):
            abort(403)
        return self.render_app_template()


appbuilder.add_view_no_menu(AgentChatView)
