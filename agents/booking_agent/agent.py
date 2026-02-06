"""
Booking Agent - A2A Server for task scheduling.
Calls the real Booking API with token-based scope validation.
"""

import os
import sys
import logging
from datetime import date, timedelta
from typing import Dict, Any, AsyncIterable

import httpx
from dotenv import load_dotenv

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.join(current_dir, '..', '..')
sys.path.insert(0, project_root)
load_dotenv(os.path.join(project_root, '.env'))

from src.config import get_settings
from src.config_loader import load_yaml_config

logger = logging.getLogger(__name__)

# The Booking API is mounted on the same server
BOOKING_API_BASE = "http://localhost:8004/api/booking"


class BookingAgent:
    """
    Booking Agent - Schedules tasks and deliveries via Booking API.
    Calls the real Booking API endpoints with the scoped token.
    Required scopes: booking:read, booking:write
    """

    REQUIRED_SCOPES = ["booking:read", "booking:write"]

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.settings = get_settings()
        app_config = load_yaml_config()
        agent_config = app_config.get("agents", {}).get("booking_agent", {})
        self.required_scopes = agent_config.get("required_scopes", self.REQUIRED_SCOPES)
        logger.info(f"Booking Agent initialized")
        logger.info(f"  Required scopes: {self.required_scopes}")
        logger.info(f"  Booking API: {BOOKING_API_BASE}")

    async def _call_api(self, method: str, path: str, token: str, json_data: dict = None) -> Dict[str, Any]:
        """Make an authenticated call to the Booking API."""
        url = f"{BOOKING_API_BASE}{path}"
        logger.info(f"[BOOKING_AGENT] API call: {method} {url}")
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.request(
                method=method,
                url=url,
                headers={"Authorization": f"Bearer {token}"},
                json=json_data
            )
            if response.status_code >= 400:
                error_detail = response.text
                logger.error(f"[BOOKING_AGENT] API error {response.status_code}: {error_detail}")
                return {"success": False, "error": f"API error {response.status_code}: {error_detail}"}
            result = response.json()
            if isinstance(result, dict):
                result["success"] = True
            else:
                result = {"success": True, "data": result}
            return result

    async def create_task(self, task_data: Dict[str, Any], token: str) -> Dict[str, Any]:
        """Create an onboarding task via Booking API (POST /api/booking/tasks)."""
        scheduled_date = task_data.get("scheduled_date", (date.today() + timedelta(days=3)).isoformat())
        payload = {
            "employee_id": task_data.get("employee_id", "EMP-NEW-001"),
            "task_type": task_data.get("task_type", "orientation"),
            "title": task_data.get("title", "Onboarding Task"),
            "scheduled_date": scheduled_date,
            "duration_hours": task_data.get("duration_hours", 2.0),
            "description": task_data.get("description", "Scheduled onboarding task")
        }
        logger.info(f"[BOOKING_AGENT] Creating task via API: {payload['title']}")
        return await self._call_api("POST", "/tasks", token, payload)

    async def schedule_delivery(self, delivery_data: Dict[str, Any], token: str) -> Dict[str, Any]:
        """Schedule a delivery via Booking API (POST /api/booking/deliveries)."""
        delivery_date = delivery_data.get("delivery_date", (date.today() + timedelta(days=5)).isoformat())
        payload = {
            "employee_id": delivery_data.get("employee_id", "EMP-NEW-001"),
            "item_type": delivery_data.get("item_type", "laptop"),
            "item_description": delivery_data.get("item_description", "Company laptop"),
            "delivery_address": delivery_data.get("delivery_address", "Office HQ, Floor 5"),
            "delivery_date": delivery_date
        }
        logger.info(f"[BOOKING_AGENT] Scheduling delivery via API: {payload['item_type']}")
        return await self._call_api("POST", "/deliveries", token, payload)

    async def list_tasks(self, token: str, employee_id: str = None) -> Dict[str, Any]:
        """List tasks via Booking API (GET /api/booking/tasks)."""
        path = "/tasks"
        if employee_id:
            path += f"?employee_id={employee_id}"
        url = f"{BOOKING_API_BASE}{path}"
        logger.info(f"[BOOKING_AGENT] Listing tasks via API")
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}"}
            )
            if response.status_code >= 400:
                return {"success": False, "error": f"API error {response.status_code}: {response.text}"}
            return {"success": True, "tasks": response.json()}

    async def list_deliveries(self, token: str, employee_id: str = None) -> Dict[str, Any]:
        """List deliveries via Booking API (GET /api/booking/deliveries)."""
        path = "/deliveries"
        if employee_id:
            path += f"?employee_id={employee_id}"
        url = f"{BOOKING_API_BASE}{path}"
        logger.info(f"[BOOKING_AGENT] Listing deliveries via API")
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}"}
            )
            if response.status_code >= 400:
                return {"success": False, "error": f"API error {response.status_code}: {response.text}"}
            return {"success": True, "deliveries": response.json()}

    def _extract_employee_id(self, query: str) -> str:
        """Extract employee ID from query, or return a default."""
        import re
        match = re.search(r'EMP-[A-Z0-9]+', query.upper())
        if match:
            return match.group(0)
        return "EMP-NEW-001"

    async def process_request(self, query: str, token: str = None) -> str:
        """Process booking request from query by calling real API endpoints."""
        if not token:
            return "❌ No token provided. Authentication required."

        query_lower = query.lower()
        employee_id = self._extract_employee_id(query)

        # Schedule orientation or task
        if any(kw in query_lower for kw in ["orientation", "training", "schedule task", "onboarding session"]):
            task_type = "security_training" if "security" in query_lower else "hr_orientation"
            title = "Security Training" if "security" in query_lower else "HR Orientation Session"
            result = await self.create_task(
                {
                    "employee_id": employee_id,
                    "task_type": task_type,
                    "title": title,
                    "description": f"Scheduled via Booking Agent: {query[:100]}"
                },
                token
            )
            if result.get("success"):
                return (
                    f"✅ Task scheduled via Booking API!\n"
                    f"- Task ID: {result.get('task_id', 'N/A')}\n"
                    f"- Employee: {result.get('employee_id', employee_id)}\n"
                    f"- Type: {result.get('task_type', task_type)}\n"
                    f"- Date: {result.get('scheduled_date', 'TBD')}\n"
                    f"- Duration: {result.get('duration_hours', 2.0)}h\n"
                    f"- Status: {result.get('status', 'scheduled')}"
                )
            return f"❌ Task scheduling failed: {result.get('error')}"

        # Schedule delivery
        if any(kw in query_lower for kw in ["delivery", "laptop", "equipment", "ship", "send"]):
            item_type = "laptop" if "laptop" in query_lower else "equipment"
            item_desc = "Company laptop (MacBook Pro)" if "laptop" in query_lower else "Office equipment"
            result = await self.schedule_delivery(
                {
                    "employee_id": employee_id,
                    "item_type": item_type,
                    "item_description": item_desc,
                    "delivery_address": "Office HQ, Floor 5"
                },
                token
            )
            if result.get("success"):
                return (
                    f"✅ Delivery scheduled via Booking API!\n"
                    f"- Delivery ID: {result.get('delivery_id', 'N/A')}\n"
                    f"- Employee: {result.get('employee_id', employee_id)}\n"
                    f"- Item: {result.get('item_description', item_desc)}\n"
                    f"- Delivery Date: {result.get('delivery_date', 'TBD')}\n"
                    f"- Tracking: {result.get('tracking_number', 'N/A')}\n"
                    f"- Status: {result.get('status', 'scheduled')}"
                )
            return f"❌ Delivery scheduling failed: {result.get('error')}"

        # Generic book/schedule
        if any(kw in query_lower for kw in ["schedule", "book"]):
            result = await self.create_task(
                {
                    "employee_id": employee_id,
                    "task_type": "general",
                    "title": f"Scheduled task: {query[:50]}",
                    "description": query[:200]
                },
                token
            )
            if result.get("success"):
                return (
                    f"✅ Task scheduled via Booking API!\n"
                    f"- Task ID: {result.get('task_id', 'N/A')}\n"
                    f"- Employee: {result.get('employee_id', employee_id)}\n"
                    f"- Date: {result.get('scheduled_date', 'TBD')}\n"
                    f"- Status: {result.get('status', 'scheduled')}"
                )
            return f"❌ Scheduling failed: {result.get('error')}"

        # List tasks/deliveries
        if any(kw in query_lower for kw in ["list", "show", "pending", "status", "check"]):
            tasks_result = await self.list_tasks(token, employee_id if "EMP-" in query.upper() else None)
            deliveries_result = await self.list_deliveries(token, employee_id if "EMP-" in query.upper() else None)

            lines = []
            if tasks_result.get("success"):
                tasks = tasks_result.get("tasks", [])
                lines.append(f"📋 Tasks ({len(tasks)} total):")
                for t in tasks:
                    lines.append(f"  - {t.get('task_id')}: {t.get('title')} ({t.get('status')}) on {t.get('scheduled_date')}")
                if not tasks:
                    lines.append("  (none)")

            if deliveries_result.get("success"):
                deliveries = deliveries_result.get("deliveries", [])
                lines.append(f"📦 Deliveries ({len(deliveries)} total):")
                for d in deliveries:
                    lines.append(f"  - {d.get('delivery_id')}: {d.get('item_type')} ({d.get('status')}) - {d.get('tracking_number')}")
                if not deliveries:
                    lines.append("  (none)")

            if lines:
                return "\n".join(lines)
            return "❌ Failed to retrieve tasks/deliveries."

        return (
            "👋 Booking Agent ready!\n"
            "I can:\n"
            "- Schedule orientation sessions (calls POST /api/booking/tasks)\n"
            "- Book equipment deliveries (calls POST /api/booking/deliveries)\n"
            "- List tasks and deliveries (calls GET /api/booking/tasks, /deliveries)\n"
            "All operations use your scoped token (booking:read, booking:write)"
        )

    async def stream(self, query: str, token: str = None) -> AsyncIterable[Dict[str, Any]]:
        """Stream response - A2A pattern."""
        response = await self.process_request(query, token)
        yield {"content": response}
