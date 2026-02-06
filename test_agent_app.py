"""Quick test: which application can worker agents authenticate through?"""
import asyncio, httpx, hashlib, base64, os, secrets
from dotenv import load_dotenv
load_dotenv()

BASE = "https://localhost:9443"
CALLBACK = "http://localhost:8000/callback"

async def try_agent_via_app(agent_name, agent_id, agent_secret, app_name, app_id, app_secret):
    cv = secrets.token_urlsafe(32)
    cc = base64.urlsafe_b64encode(hashlib.sha256(cv.encode()).digest()).rstrip(b"=").decode()
    ba = base64.b64encode(f"{app_id}:{app_secret}".encode()).decode()

    async with httpx.AsyncClient(verify=False, timeout=30) as c:
        r = await c.post(f"{BASE}/oauth2/authorize", data={
            "response_type": "code", "client_id": app_id,
            "redirect_uri": CALLBACK, "scope": "openid",
            "response_mode": "direct", "code_challenge": cc,
            "code_challenge_method": "S256",
        }, headers={"Authorization": f"Basic {ba}", "Accept": "application/json"})
        j = r.json()
        fid = j.get("flowId")
        if not fid:
            print(f"  {agent_name} via {app_name}: Step1 FAILED (no flowId)")
            return

        r2 = await c.post(f"{BASE}/oauth2/authn", json={
            "flowId": fid,
            "selectedAuthenticator": {
                "authenticatorId": "QmFzaWNBdXRoZW50aWNhdG9yOkxPQ0FM",
                "params": {"username": agent_id, "password": agent_secret},
            },
        }, headers={"Content-Type": "application/json"})
        j2 = r2.json()
        status = j2.get("flowStatus")
        code = j2.get("code") or j2.get("authData", {}).get("code")
        if code:
            print(f"  {agent_name} via {app_name}: SUCCESS (code={code[:20]}...)")
        else:
            print(f"  {agent_name} via {app_name}: FAILED ({status})")

async def main():
    apps = {
        "ORCHESTRATOR_APP": (os.getenv("ORCHESTRATOR_CLIENT_ID"), os.getenv("ORCHESTRATOR_CLIENT_SECRET")),
        "TOKEN_EXCHANGER_APP": (os.getenv("TOKEN_EXCHANGER_CLIENT_ID"), os.getenv("TOKEN_EXCHANGER_CLIENT_SECRET")),
    }
    agents = {
        "HR": (os.getenv("HR_AGENT_ID"), os.getenv("HR_AGENT_SECRET")),
        "IT": (os.getenv("IT_AGENT_ID"), os.getenv("IT_AGENT_SECRET")),
        "APPROVAL": (os.getenv("APPROVAL_AGENT_ID"), os.getenv("APPROVAL_AGENT_SECRET")),
        "BOOKING": (os.getenv("BOOKING_AGENT_ID"), os.getenv("BOOKING_AGENT_SECRET")),
        "ORCHESTRATOR": (os.getenv("ORCHESTRATOR_AGENT_ID"), os.getenv("ORCHESTRATOR_AGENT_SECRET")),
    }

    for agent_name, (aid, asec) in agents.items():
        print(f"\n{agent_name} agent ({aid}):")
        for app_name, (cid, csec) in apps.items():
            await try_agent_via_app(agent_name, aid, asec, app_name, cid, csec)

asyncio.run(main())
