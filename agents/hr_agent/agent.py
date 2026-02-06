"""
HR Agent - A2A Server for employee profile management.
Calls the real HR API with token-based scope validation.
"""

import os
import sys
import json
import logging
from datetime import date
from typing import Optional, Dict, Any, AsyncIterable

import httpx
from dotenv import load_dotenv

# Add project root to path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.join(current_dir, '..', '..')
sys.path.insert(0, project_root)

load_dotenv(os.path.join(project_root, '.env'))

from jose import jwt
from src.config import get_settings
from src.config_loader import load_yaml_config

logger = logging.getLogger(__name__)

# The HR API is mounted on the same server
HR_API_BASE = "http://localhost:8001/api/hr"


class HRAgent:
    """
    HR Agent - Creates employee profiles via HR API.
    Calls the real HR API endpoints with the scoped token.
    Required scopes: hr:read, hr:write
    """

    REQUIRED_SCOPES = ["hr:read", "hr:write"]
    SUPPORTED_CONTENT_TYPES = ["text", "text/plain"]

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.settings = get_settings()

        # Load agent config
        app_config = load_yaml_config()
        agent_config = app_config.get("agents", {}).get("hr_agent", {})
        self.required_scopes = agent_config.get("required_scopes", self.REQUIRED_SCOPES)

        logger.info(f"HR Agent initialized")
        logger.info(f"  Required scopes: {self.required_scopes}")
        logger.info(f"  HR API: {HR_API_BASE}")

    async def _call_api(self, method: str, path: str, token: str, json_data: dict = None) -> Dict[str, Any]:
        """Make an authenticated call to the HR API."""
        url = f"{HR_API_BASE}{path}"
        logger.info(f"[HR_AGENT] API call: {method} {url}")
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.request(
                method=method,
                url=url,
                headers={"Authorization": f"Bearer {token}"},
                json=json_data
            )
            if response.status_code >= 400:
                error_detail = response.text
                logger.error(f"[HR_AGENT] API error {response.status_code}: {error_detail}")
                return {"success": False, "error": f"API error {response.status_code}: {error_detail}"}
            result = response.json()
            result["success"] = True
            return result

    async def create_employee(self, employee_data: Dict[str, Any], token: str) -> Dict[str, Any]:
        """Create employee profile via HR API (POST /api/hr/employees)."""
        payload = {
            "name": employee_data.get("name", "New Employee"),
            "email": employee_data.get("email", "new.employee@company.com"),
            "role": employee_data.get("role", "Software Engineer"),
            "team": employee_data.get("team", "Engineering"),
            "manager_email": employee_data.get("manager_email", "manager@company.com"),
            "start_date": employee_data.get("start_date", date.today().isoformat())
        }
        logger.info(f"[HR_AGENT] Creating employee via API: {payload['name']}")
        return await self._call_api("POST", "/employees", token, payload)

    async def get_employee(self, employee_id: str, token: str) -> Dict[str, Any]:
        """Get employee by ID via HR API (GET /api/hr/employees/{id})."""
        return await self._call_api("GET", f"/employees/{employee_id}", token)

    async def list_employees(self, token: str) -> Dict[str, Any]:
        """List all employees via HR API (GET /api/hr/employees)."""
        url = f"{HR_API_BASE}/employees"
        logger.info(f"[HR_AGENT] Listing employees via API")
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}"}
            )
            if response.status_code >= 400:
                return {"success": False, "error": f"API error {response.status_code}: {response.text}"}
            return {"success": True, "employees": response.json()}

    async def grant_privileges(self, user: str, privilege_details: str, token: str) -> Dict[str, Any]:
        """
        Grant HR privileges to a user.
        Updates employee status via HR API (PATCH /api/hr/employees/{id}/status).
        For demo, creates the user as an employee with elevated role if not found.
        """
        # Try to create an employee record with elevated role to represent the privilege grant
        import re
        safe_email_user = re.sub(r'[^a-z0-9.]', '', user.lower().replace(' ', '.'))
        if not safe_email_user:
            safe_email_user = "privilege.user"
        payload = {
            "name": user,
            "email": f"{safe_email_user}@company.com",
            "role": "HR Admin (Privilege Grant)",
            "team": "HR",
            "manager_email": "admin@company.com",
            "start_date": date.today().isoformat()
        }
        logger.info(f"[HR_AGENT] Granting HR privileges to {user} via API")
        result = await self._call_api("POST", "/employees", token, payload)
        if result.get("success"):
            result["privilege"] = privilege_details
            result["status"] = "granted"
            result["effective_from"] = "immediately"
        return result

    async def process_request(self, query: str, token: str = None) -> str:
        """Process HR request from query by calling real API endpoints."""
        if not token:
            return "❌ No token provided. Authentication required."

        query_lower = query.lower()

        # Detect privilege granting intent (typically routed from Approval Agent)
        is_privilege_request = any(kw in query_lower for kw in [
            "privilege", "grant", "permission", "role", "access", "elevat", "approved"
        ])

        if is_privilege_request and any(kw in query_lower for kw in [
            "grant", "give", "assign", "approved", "fulfill"
        ]):
            # Extract user name (clean heuristic)
            user = "Unknown User"
            for marker in ["to ", "for "]:
                if marker in query_lower:
                    idx = query_lower.index(marker) + len(marker)
                    rest = query[idx:].strip().rstrip(".")
                    # Take only alphabetic words as name parts (skip noise like IDs, punctuation)
                    words = []
                    for w in rest.split():
                        cleaned = w.strip(".,;!?()\"'")
                        if cleaned.isalpha() and cleaned.lower() not in (
                            "approved", "rejected", "pending", "status",
                            "via", "api", "the", "by", "from", "with",
                            "agent", "routing", "recommendation", "forwarded"
                        ):
                            words.append(cleaned)
                        if len(words) >= 2:
                            break
                    if words:
                        user = " ".join(words)
                    break

            result = await self.grant_privileges(user, query, token)
            if result.get("success"):
                return (
                    f"✅ HR privileges granted via API!\n"
                    f"- Employee ID: {result.get('employee_id', 'N/A')}\n"
                    f"- User: {result.get('name', user)}\n"
                    f"- Role: {result.get('role', 'HR Admin')}\n"
                    f"- Status: granted\n"
                    f"- Effective: immediately"
                )
            return f"❌ Failed: {result.get('error')}"

        # Parse for employee creation intent
        if any(kw in query_lower for kw in ["create", "onboard", "hire", "add employee", "new employee"]):
            # Extract name from query
            name = self._extract_name(query)
            import re
            safe_email = re.sub(r'[^a-z0-9.]', '', name.lower().replace(' ', '.'))
            if not safe_email:
                safe_email = "new.employee"

            result = await self.create_employee(
                {"name": name, "email": f"{safe_email}@company.com"},
                token
            )
            if result.get("success"):
                return (
                    f"✅ Employee created via HR API!\n"
                    f"- ID: {result.get('employee_id')}\n"
                    f"- Name: {result.get('name')}\n"
                    f"- Email: {result.get('email')}\n"
                    f"- Status: {result.get('status')}"
                )
            return f"❌ Failed: {result.get('error')}"

        # List employees
        if any(kw in query_lower for kw in ["list", "show", "get employees", "all employees"]):
            result = await self.list_employees(token)
            if result.get("success"):
                employees = result.get("employees", [])
                if not employees:
                    return "📋 No employees found in the system."
                lines = [f"📋 Employees ({len(employees)} total):"]
                for emp in employees:
                    lines.append(f"  - {emp.get('employee_id')}: {emp.get('name')} ({emp.get('role')})")
                return "\n".join(lines)
            return f"❌ Failed: {result.get('error')}"

        return (
            "👋 HR Agent ready!\n"
            "I can:\n"
            "- Create employee profiles (calls POST /api/hr/employees)\n"
            "- List employees (calls GET /api/hr/employees)\n"
            "- Grant HR privileges (after approval)\n"
            "All operations use your scoped token (hr:read, hr:write)"
        )

    def _extract_name(self, query: str) -> str:
        """Extract a person's name from the query text."""
        query_lower = query.lower()
        # Try various patterns
        for marker in ["for ", "named ", "name: ", "profile ", "employee "]:
            if marker in query_lower:
                idx = query_lower.index(marker) + len(marker)
                rest = query[idx:].strip()
                # Take capitalized words as the name
                words = []
                for w in rest.split():
                    cleaned = w.strip(".,;!?()\"'")
                    if cleaned and cleaned[0].isupper():
                        words.append(cleaned)
                    elif words:
                        break
                if words:
                    return " ".join(words[:3])
        return "New Employee"

    async def stream(self, query: str, token: str = None) -> AsyncIterable[Dict[str, Any]]:
        """Stream response - A2A pattern."""
        response = await self.process_request(query, token)
        yield {"content": response}
