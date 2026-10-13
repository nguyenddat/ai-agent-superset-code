import json
import logging
import queue
import threading

from flask import Response, current_app, request, stream_with_context
from flask_appbuilder.api import expose, permission_name, protect, safe
from flask_login import current_user
from superset.exceptions import SupersetSecurityException
from superset.models.dashboard import Dashboard
from superset_core.rest_api.api import RestApi
from superset_core.rest_api.decorators import api

from ...agent_package.bi_planning import plan_bi
from ...agent_package.data_builder import build_data
from ...agent_package.metadata_resolution import resolve_metadata, _metadata_resolution_context
from ...agent_package.context.dashboard import get_dashboard_datasets, get_dashboard_title
from ...core.superset_client import superset_client

logger = logging.getLogger(__name__)
MAX_METADATA_PLAN_FEEDBACK_ROUNDS = 2


def _event(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def _metadata_feedback(resolution) -> str | None:
    """Build a short actionable handoff; infrastructure failures are not planning feedback."""
    non_actionable = {
        "metadata_unavailable", "missing_dataset", "missing_dashboard_context",
        "unauthorized_dataset", "validator_exception", "invalid_tool_input",
    }
    if any(item.get("code") in non_actionable for item in resolution.errors):
        return None

    details = [
        str(item.get("message", "")).strip()
        for item in resolution.errors
        if isinstance(item, dict) and item.get("message")
    ][:2]
    if not details and resolution.resolution and resolution.resolution.message:
        details.append(resolution.resolution.message.strip())
    if not details:
        return None
    return "MetadataResolution chưa ánh xạ được BI Plan: " + "; ".join(details)[:450]


def get_chat_context(user_id: int, dashboard_id: int) -> dict:
    datasets = get_dashboard_datasets(dashboard_id, superset_client)
    title = get_dashboard_title(dashboard_id, superset_client)
    return {
        "user_id": user_id,
        "dashboard_id": dashboard_id,
        "allowed_dataset_ids": [dataset.id for dataset in datasets],
        "dataset_names": {
            str(dataset.id): dataset.name or dataset.datasource_name or str(dataset.id)
            for dataset in datasets
        },
        "dashboard_title": title,
    }


@api(
    id="text_to_bi_chat_api",
    name="Superset AI Agent API",
    description="Streaming BI planning API for the Superset AI Agent extension.",
    resource_name="chat",
)
class TextToBIAgentAPI(RestApi):
    openapi_spec_tag = "Superset AI Agent"
    class_permission_name = "text_to_bi_chat_api"

    @expose("/stream", methods=("POST",))
    @protect()
    @safe
    @permission_name("read")
    def stream_chat(self):
        from flask_wtf.csrf import validate_csrf
        from wtforms import ValidationError

        try:
            validate_csrf(request.headers.get("X-CSRFToken"))
        except ValidationError:
            return self.response(403, message="CSRF token không hợp lệ.")

        body = request.get_json(silent=True) or {}
        try:
            dashboard_id = int(body["dashboard_id"])
            query = body["query"]
            if not isinstance(query, str) or not query.strip():
                raise ValueError("query must be a non-empty string")
            dashboard = Dashboard.get(dashboard_id)
            if dashboard is None:
                return self.response(404, message="Dashboard not found")
            dashboard.raise_for_access()
            user_id = int(current_user.id)
        except (KeyError, TypeError, ValueError) as exc:
            return self.response(400, message=f"Invalid request: {exc}")
        except SupersetSecurityException:
            return self.response(403, message="Dashboard access denied")

        @stream_with_context
        def events():
            flask_app = current_app._get_current_object()
            yield _event("status", {"message": "Đang lấy ngữ cảnh dashboard"})
            try:
                context = get_chat_context(user_id, dashboard_id)
                context["user_question"] = query
                yield _event("context", {
                    "dashboard_title": context["dashboard_title"],
                    "authorized_dataset_count": len(context["allowed_dataset_ids"]),
                    "datasets": context["dataset_names"],
                })
                yield _event("status", {"message": "Đang lập kế hoạch BI"})

                event_queue: queue.Queue[str | None] = queue.Queue()

                def run_planner():
                    with flask_app.app_context():
                      try:
                        event_queue.put(_event("agent_start", {"agent": "bi_planner", "iteration": 1}))
                        result = plan_bi(
                            query,
                            context,
                            on_event=lambda name, data: event_queue.put(_event(name, data)),
                        )
                        if result.success and result.contract:
                            contract = result.contract
                            event_queue.put(_event("bi_contract", {
                                "contract": contract.model_dump(mode="json"),
                                "attempts": result.attempts,
                            }))
                            resolution = None
                            for iteration in range(1, MAX_METADATA_PLAN_FEEDBACK_ROUNDS + 2):
                                event_queue.put(_event("agent_start", {
                                    "agent": "metadata_resolution", "iteration": iteration,
                                }))
                                resolution = resolve_metadata(
                                    contract,
                                    context,
                                    on_event=lambda name, data: event_queue.put(_event(name, data)),
                                )
                                if resolution.success:
                                    break

                                feedback = _metadata_feedback(resolution)
                                if not feedback or iteration > MAX_METADATA_PLAN_FEEDBACK_ROUNDS:
                                    break

                                event_queue.put(_event("agent_message", {
                                    "from_agent": "metadata_resolution",
                                    "to_agent": "bi_planner",
                                    "message": feedback,
                                    "iteration": iteration,
                                }))
                                planner_iteration = iteration + 1
                                event_queue.put(_event("agent_start", {
                                    "agent": "bi_planner", "iteration": planner_iteration,
                                }))
                                revised = plan_bi(
                                    query,
                                    context,
                                    previous_contract=contract,
                                    metadata_feedback=feedback,
                                    on_event=lambda name, data: event_queue.put(_event(name, data)),
                                )
                                if not revised.success or not revised.contract:
                                    event_queue.put(_event("planning_failure", {
                                        "errors": revised.errors,
                                        "attempts": revised.attempts,
                                        "reason": "BI Planner không thể cập nhật plan theo phản hồi MetadataResolution.",
                                    }))
                                    break
                                contract = revised.contract
                                event_queue.put(_event("plan_revision", {
                                    "iteration": planner_iteration,
                                    "contract": contract.model_dump(mode="json"),
                                }))
                                event_queue.put(_event("bi_contract", {
                                    "contract": contract.model_dump(mode="json"),
                                    "attempts": revised.attempts,
                                }))
                                event_queue.put(_event("agent_message", {
                                    "from_agent": "bi_planner",
                                    "to_agent": "metadata_resolution",
                                    "message": "Đã cập nhật BI Plan theo phản hồi, giữ nguyên mục tiêu phân tích. Hãy ánh xạ lại plan mới.",
                                    "iteration": planner_iteration,
                                }))

                            if resolution:
                                event_queue.put(_event("metadata_resolution", {
                                    "success": resolution.success,
                                    "resolution": resolution.resolution.model_dump(mode="json") if resolution.resolution else None,
                                    "errors": resolution.errors,
                                    "attempts": resolution.attempts,
                                }))
                            if resolution.success and resolution.resolution:
                                event_queue.put(_event("status", {"message": "Đang tạo và kiểm tra SQL cuối cùng"}))
                                resolved_context = resolution.agent_context or _metadata_resolution_context(
                                    contract, context
                                )
                                event_queue.put(_event("agent_start", {"agent": "data_builder", "iteration": 1}))
                                data_result = build_data(
                                    resolved_context,
                                    context,
                                    resolution.resolution,
                                    on_event=lambda name, data: event_queue.put(_event(name, data)),
                                )
                                event_queue.put(_event("data_builder_result", {
                                    "success": data_result.success,
                                    "sql": data_result.sql,
                                    "summary": data_result.summary,
                                    "chart_url": data_result.chart_url,
                                    "chart_error": data_result.chart_error,
                                    "errors": data_result.errors,
                                    "attempts": data_result.attempts,
                                }))
                        else:
                            event_queue.put(_event("planning_failure", {
                                "errors": result.errors,
                                "attempts": result.attempts,
                            }))
                        event_queue.put(_event("done", {}))
                      except Exception:
                          logger.exception("BI planner failed (dashboard_id=%s)", dashboard_id)
                          event_queue.put(_event("error", {"message": "Không thể hoàn tất bước lập kế hoạch BI."}))
                      finally:
                          event_queue.put(None)

                threading.Thread(target=run_planner, daemon=True).start()
                while True:
                    item = event_queue.get()
                    if item is None:
                        break
                    yield item
            except Exception:
                logger.exception("BI planning stream failed (dashboard_id=%s)", dashboard_id)
                yield _event("error", {"message": "Không thể hoàn tất bước lập kế hoạch BI."})

        return Response(events(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
