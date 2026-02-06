"""
Approval Agent - A2A Server for approval workflows.
Calls the real Approval API with token-based scope validation.
"""

import os
import sys
import logging
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

# The Approval API is mounted on the same server
APPROVAL_API_BASE = "http://localhost:8003/api/approval"


class ApprovalAgent:
    """
    Approval Agent - Handles approval requests and workflows via Approval API.
    Calls the real Approval API endpoints with the scoped token.
    Required scopes: approval:read, approval:write
    """

    REQUIRED_SCOPES = ["approval:read", "approval:write"]

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.settings = get_settings()
        app_config = load_yaml_config()
        agent_config = app_config.get("agents", {}).get("approval_agent", {})
        self.required_scopes = agent_config.get("required_scopes", self.REQUIRED_SCOPES)
        logger.info(f"Approval Agent initialized")
        logger.info(f"  Required scopes: {self.required_scopes}")
        logger.info(f"  Approval API: {APPROVAL_API_BASE}")

    async def _call_api(self, method: str, path: str, token: str, json_data: dict = None) -> Dict[str, Any]:
        """Make an authenticated call to the Approval API."""
        url = f"{APPROVAL_API_BASE}{path}"
        logger.info(f"[APPROVAL_AGENT] API call: {method} {url}")
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.request(
                method=method,
                url=url,
                headers={"Authorization": f"Bearer {token}"},
                json=json_data
            )
            if response.status_code >= 400:
                error_detail = response.text
                logger.error(f"[APPROVAL_AGENT] API error {response.status_code}: {error_detail}")
                return {"success": False, "error": f"API error {response.status_code}: {error_detail}"}
            result = response.json()
            if isinstance(result, dict):
                result["success"] = True
            else:
                result = {"success": True, "data": result}
            return result

    def _classify_privilege_domain(self, query: str) -> str | None:
        """Determine the domain a privilege request should be routed to after approval."""
        q = query.lower()
        hr_keywords = ["hr privilege", "hr access", "hr role", "employee management",
                        "payroll access", "hr admin", "hr permission", "hr system"]
        it_keywords = ["it privilege", "it access", "system access", "admin access",
                        "vpn access", "server access", "it permission", "it admin"]
        booking_keywords = ["booking privilege", "booking access", "travel admin",
                            "booking permission"]

        if any(kw in q for kw in hr_keywords):
            return "hr"
        if any(kw in q for kw in it_keywords):
            return "it"
        if any(kw in q for kw in booking_keywords):
            return "booking"
        return None

    async def create_approval_request(self, request_data: Dict[str, Any], token: str) -> Dict[str, Any]:
        """Create approval request via Approval API (POST /api/approval/requests)."""
        payload = {
            "request_type": request_data.get("type", "access_request"),
            "target_user": request_data.get("target_user", "employee@company.com"),
            "target_resource": request_data.get("target_resource"),
            "approver_email": request_data.get("approver", "manager@company.com"),
            "reason": request_data.get("reason", "Standard approval request"),
            "priority": request_data.get("priority", "normal")
        }
        logger.info(f"[APPROVAL_AGENT] Creating approval request via API: {payload['request_type']}")
        result = await self._call_api("POST", "/requests", token, payload)

        # Add routing info if this is a privilege request
        domain = request_data.get("domain")
        if domain and result.get("success"):
            result["route_to"] = domain
            result["route_reason"] = f"Approved privilege request should be fulfilled by {domain} agent"

        return result

    async def approve_request(self, request_id: str, token: str) -> Dict[str, Any]:
        """Approve a pending request via Approval API (POST /api/approval/requests/{id}/approve)."""
        logger.info(f"[APPROVAL_AGENT] Approving request {request_id} via API")
        return await self._call_api("POST", f"/requests/{request_id}/approve", token)

    async def reject_request(self, request_id: str, token: str) -> Dict[str, Any]:
        """Reject a pending request via Approval API (POST /api/approval/requests/{id}/reject)."""
        logger.info(f"[APPROVAL_AGENT] Rejecting request {request_id} via API")
        return await self._call_api("POST", f"/requests/{request_id}/reject", token)

    async def get_request(self, request_id: str, token: str) -> Dict[str, Any]:
        """Get approval request by ID via Approval API (GET /api/approval/requests/{id})."""
        return await self._call_api("GET", f"/requests/{request_id}", token)

    async def list_requests(self, token: str, status: str = None) -> Dict[str, Any]:
        """List approval requests via Approval API (GET /api/approval/requests)."""
        path = "/requests"
        if status:
            path += f"?status={status}"
        url = f"{APPROVAL_API_BASE}{path}"
        logger.info(f"[APPROVAL_AGENT] Listing approval requests via API")
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}"}
            )
            if response.status_code >= 400:
                return {"success": False, "error": f"API error {response.status_code}: {response.text}"}
            return {"success": True, "requests": response.json()}

    def _extract_request_id(self, query: str) -> str | None:
        """Extract approval request ID from query."""
        import re
        match = re.search(r'APR-[A-Z0-9]+', query.upper())
        if match:
            return match.group(0)
        return None

    async def process_request(self, query: str, token: str = None) -> str:
        """Process approval request from query by calling real API endpoints."""
        if not token:
            return "❌ No token provided. Authentication required."

        query_lower = query.lower()

        # Detect privilege-related requests and classify domain
        is_privilege_request = any(kw in query_lower for kw in [
            "privilege", "access", "permission", "role", "grant", "elevat"
        ])

        # Check for approve/reject existing request
        request_id = self._extract_request_id(query)
        if request_id:
            if "reject" in query_lower:
                result = await self.reject_request(request_id, token)
                if result.get("success"):
                    return (
                        f"❌ Approval request rejected via API!\n"
                        f"- ID: {result.get('request_id', request_id)}\n"
                        f"- Status: {result.get('status', 'rejected')}"
                    )
                return f"❌ Failed: {result.get('error')}"

            if any(kw in query_lower for kw in ["approve", "accept"]):
                result = await self.approve_request(request_id, token)
                if result.get("success"):
                    return (
                        f"✅ Approval request approved via API!\n"
                        f"- ID: {result.get('request_id', request_id)}\n"
                        f"- Status: {result.get('status', 'approved')}\n"
                        f"- Approved by: {result.get('approved_by', 'N/A')}"
                    )
                return f"❌ Failed: {result.get('error')}"

            # Get status of specific request
            result = await self.get_request(request_id, token)
            if result.get("success"):
                return (
                    f"📋 Approval Request Details:\n"
                    f"- ID: {result.get('request_id')}\n"
                    f"- Type: {result.get('request_type')}\n"
                    f"- Target: {result.get('target_user')}\n"
                    f"- Status: {result.get('status')}\n"
                    f"- Approver: {result.get('approver_email')}"
                )
            return f"❌ Failed: {result.get('error')}"

        # Create new approval request
        if any(kw in query_lower for kw in ["create", "request", "submit", "need approval",
                                              "grant", "give", "assign", "approve"]):
            domain = self._classify_privilege_domain(query) if is_privilege_request else None

            # Extract user name from query
            target_user = "employee@company.com"
            for marker in ["for ", "to "]:
                if marker in query_lower:
                    idx = query_lower.index(marker) + len(marker)
                    rest = query[idx:].strip().split()
                    if rest:
                        target_user = " ".join(rest[:2])
                        break

            result = await self.create_approval_request(
                {
                    "type": "privilege_request" if is_privilege_request else "access_request",
                    "domain": domain,
                    "target_user": target_user,
                    "reason": query[:200]
                },
                token
            )

            if result.get("success"):
                # Auto-approve for demo flow (create then approve)
                created_id = result.get("request_id")
                if created_id:
                    approve_result = await self.approve_request(created_id, token)
                    if approve_result.get("success"):
                        response = (
                            f"✅ Approval request created and approved via API!\n"
                            f"- ID: {approve_result.get('request_id', created_id)}\n"
                            f"- Status: {approve_result.get('status', 'approved')}\n"
                            f"- Approver: {approve_result.get('approved_by', 'N/A')}"
                        )
                        if result.get("route_to"):
                            response += (
                                f"\n\n🔀 Routing recommendation: This approved request should be "
                                f"forwarded to the **{result['route_to'].upper()} Agent** to "
                                f"fulfill the privilege grant."
                            )
                        return response

                # Fallback if auto-approve didn't work
                response = (
                    f"✅ Approval request created via API!\n"
                    f"- ID: {result.get('request_id')}\n"
                    f"- Status: {result.get('status', 'pending')}\n"
                    f"- Type: {result.get('request_type')}"
                )
                if result.get("route_to"):
                    response += (
                        f"\n\n🔀 Routing recommendation: After approval, forward to "
                        f"**{result['route_to'].upper()} Agent**."
                    )
                return response
            return f"❌ Failed: {result.get('error')}"

        # List/status check
        if any(kw in query_lower for kw in ["status", "check", "pending", "list", "show"]):
            status_filter = None
            if "pending" in query_lower:
                status_filter = "pending"
            elif "approved" in query_lower:
                status_filter = "approved"
            elif "rejected" in query_lower:
                status_filter = "rejected"

            result = await self.list_requests(token, status_filter)
            if result.get("success"):
                requests = result.get("requests", [])
                if not requests:
                    return f"📋 No {'(' + status_filter + ') ' if status_filter else ''}approval requests found."
                lines = [f"📋 Approval Requests ({len(requests)} total):"]
                for r in requests:
                    lines.append(f"  - {r.get('request_id')}: {r.get('request_type')} ({r.get('status')})")
                return "\n".join(lines)
            return f"❌ Failed: {result.get('error')}"

        return (
            "👋 Approval Agent ready!\n"
            "I can:\n"
            "- Create approval requests (calls POST /api/approval/requests)\n"
            "- Approve requests (calls POST /api/approval/requests/{id}/approve)\n"
            "- Reject requests (calls POST /api/approval/requests/{id}/reject)\n"
            "- Check status (calls GET /api/approval/requests)\n"
            "- Route approved privilege requests to HR/IT/Booking agents\n"
            "All operations use your scoped token (approval:read, approval:write)"
        )

    async def stream(self, query: str, token: str = None) -> AsyncIterable[Dict[str, Any]]:
        response = await self.process_request(query, token)
        yield {"content": response}
