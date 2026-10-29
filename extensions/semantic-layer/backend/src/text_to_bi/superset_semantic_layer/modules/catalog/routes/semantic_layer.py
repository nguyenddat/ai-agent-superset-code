from flask_appbuilder.api import expose, permission_name, protect, safe
from superset_core.rest_api.api import RestApi
from superset_core.rest_api.decorators import api

from ....core.database import handle_errors
from ....core.security import require_admin
from ....migrations import ensure_dictionary_tables
from ...agent_ladder.routes.agent import AgentLadderRoutes
from ...business_model.routes.business_model import BusinessModelRoutes
from ...data_dictionary.routes.dictionary import DataDictionaryRoutes
from ...glossary.routes.glossary import GlossaryRoutes
from ...semantic_query.routes.consumer import ConsumerRoutes
from ...semantic_query.routes.metrics import MetricContractRoutes
from ...semantic_query.routes.relationships import RelationshipRoutes


@api(
    id="text_to_bi_semantic_layer_api",
    name="Text to BI Semantic Layer API",
    description="Admin API for the Semantic Layer extension.",
    resource_name="semantic-layer",
)
class SemanticLayerAPI(
    MetricContractRoutes,
    ConsumerRoutes,
    AgentLadderRoutes,
    RelationshipRoutes,
    DataDictionaryRoutes,
    BusinessModelRoutes,
    GlossaryRoutes,
    RestApi,
):
    openapi_spec_tag = "Text to BI Semantic Layer"
    class_permission_name = "text_to_bi_semantic_layer_api"

    @expose("/access", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def get_access(self):
        """Return whether the authenticated user is a Superset administrator."""
        require_admin()
        ensure_dictionary_tables()
        return self.response(200, is_admin=True)
