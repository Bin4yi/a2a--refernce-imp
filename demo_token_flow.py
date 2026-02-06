"""
Token Flow Demonstration Script
Implements the Asgardeo AI Agent authentication flows exactly as documented:

1. Agent acting on its own (3-step: authorize+direct -> authn -> token)
2. Per-agent actor tokens (same 3-step flow)
3. Token Exchange (RFC 8693) for downscoping
"""

import asyncio
import sys
import os
import httpx
import json
import base64
import hashlib
import secrets
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Force UTF-8 output
sys.stdout.reconfigure(encoding='utf-8')

# Disable SSL warnings for localhost
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ─────────────────────────────────────────────────────────────────
# Configuration from .env
# ─────────────────────────────────────────────────────────────────
BASE_URL = os.getenv("ASGARDEO_BASE_URL", "https://localhost:9443")
AUTHORIZE_URL = f"{BASE_URL}/oauth2/authorize"
AUTHN_URL = f"{BASE_URL}/oauth2/authn"
TOKEN_URL = f"{BASE_URL}/oauth2/token"
CALLBACK_URL = os.getenv("APP_CALLBACK_URL", "http://localhost:8000/callback")

# Token Exchanger Application (used for worker agent flows)
TOKEN_EXCHANGER_CLIENT_ID = os.getenv("TOKEN_EXCHANGER_CLIENT_ID")
TOKEN_EXCHANGER_CLIENT_SECRET = os.getenv("TOKEN_EXCHANGER_CLIENT_SECRET")

# Orchestrator Application (used for orchestrator agent flow)
ORCHESTRATOR_CLIENT_ID = os.getenv("ORCHESTRATOR_CLIENT_ID")
ORCHESTRATOR_CLIENT_SECRET = os.getenv("ORCHESTRATOR_CLIENT_SECRET")

# Orchestrator Agent
ORCHESTRATOR_AGENT_ID = os.getenv("ORCHESTRATOR_AGENT_ID")
ORCHESTRATOR_AGENT_SECRET = os.getenv("ORCHESTRATOR_AGENT_SECRET")

# Worker Agents
AGENTS = {
    "hr_agent": {
        "agent_id": os.getenv("HR_AGENT_ID"),
        "agent_secret": os.getenv("HR_AGENT_SECRET"),
        "scopes": ["hr:read", "hr:write"],
        "audience": "onboarding-api",
    },
    "it_agent": {
        "agent_id": os.getenv("IT_AGENT_ID"),
        "agent_secret": os.getenv("IT_AGENT_SECRET"),
        "scopes": ["it:read", "it:write"],
        "audience": "onboarding-api",
    },
    "approval_agent": {
        "agent_id": os.getenv("APPROVAL_AGENT_ID"),
        "agent_secret": os.getenv("APPROVAL_AGENT_SECRET"),
        "scopes": ["approval:read", "approval:write"],
        "audience": "onboarding-api",
    },
    "booking_agent": {
        "agent_id": os.getenv("BOOKING_AGENT_ID"),
        "agent_secret": os.getenv("BOOKING_AGENT_SECRET"),
        "scopes": ["booking:read", "booking:write"],
        "audience": "onboarding-api",
    },
}


# ─────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────
def generate_pkce():
    """Generate PKCE code_verifier and code_challenge (S256)."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode('ascii')).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b'=').decode('ascii')
    return verifier, challenge


def print_header(title: str):
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_token(name: str, token: str, description: str = ""):
    print(f"\n  [{name}]")
    if description:
        print(f"    Description: {description}")
    if len(token) > 100:
        print(f"    Value: {token[:100]}...")
    else:
        print(f"    Value: {token}")


def decode_jwt_payload(token: str) -> dict:
    """Decode JWT payload without verification (for display only)."""
    try:
        parts = token.split(".")
        if len(parts) >= 2:
            payload = parts[1]
            payload += "=" * (4 - len(payload) % 4)
            decoded = base64.urlsafe_b64decode(payload)
            return json.loads(decoded)
    except Exception:
        pass
    return {}


def print_jwt_claims(token: str):
    """Print decoded JWT claims."""
    claims = decode_jwt_payload(token)
    print(f"    Subject (sub): {claims.get('sub', 'N/A')}")
    print(f"    Audience (aud): {claims.get('aud', 'N/A')}")
    print(f"    Scopes: {claims.get('scope', 'N/A')}")
    if "act" in claims:
        print(f"    Actor (act): {claims['act']}")
    return claims


# ─────────────────────────────────────────────────────────────────
# 3-Step Agent Authentication Flow (Agent Acting On Its Own)
# As per Asgardeo docs:
#   Step 1: POST /oauth2/authorize (response_mode=direct) -> flowId
#   Step 2: POST /oauth2/authn (flowId + agent creds) -> code
#   Step 3: POST /oauth2/token (authorization_code + code_verifier) -> access_token
# ─────────────────────────────────────────────────────────────────

async def step1_get_flow_id(
    client: httpx.AsyncClient,
    client_id: str,
    client_secret: str,
    scopes: list[str],
    code_challenge: str,
) -> str:
    """
    Step 1: Initiate authorize request with response_mode=direct.
    POST /oauth2/authorize -> Returns JSON with flowId.
    """
    data = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": CALLBACK_URL,
        "scope": " ".join(scopes),
        "response_mode": "direct",
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }

    # Use HTTP Basic Auth (client_secret_basic) for WSO2 IS
    import base64 as b64
    basic_auth = b64.b64encode(f"{client_id}:{client_secret}".encode()).decode()

    response = await client.post(
        AUTHORIZE_URL,
        data=data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "Authorization": f"Basic {basic_auth}",
        },
    )

    print(f"    POST {AUTHORIZE_URL}")
    print(f"    Status: {response.status_code}")

    result = response.json()
    flow_id = result.get("flowId")
    flow_status = result.get("flowStatus")
    print(f"    flowId: {flow_id}")
    print(f"    flowStatus: {flow_status}")

    # If session is active, authorize may return SUCCESS_COMPLETED with code directly
    if flow_status == "SUCCESS_COMPLETED":
        direct_code = result.get("code") or result.get("authData", {}).get("code")
        if direct_code:
            return None, direct_code  # No flowId needed, we have code directly

    if not flow_id:
        print(f"    ERROR - Full response: {json.dumps(result, indent=2)}")
        raise ValueError(f"flowId not found in response: {result}")

    return flow_id, None


async def step2_authenticate_agent(
    client: httpx.AsyncClient,
    flow_id: str,
    agent_id: str,
    agent_secret: str,
) -> str:
    """
    Step 2: Authenticate agent using flowId + agent credentials (agent_id as username, agent_secret as password).
    POST /oauth2/authn -> Returns JSON with authorization code.
    """
    payload = {
        "flowId": flow_id,
        "selectedAuthenticator": {
            "authenticatorId": "QmFzaWNBdXRoZW50aWNhdG9yOkxPQ0FM",
            "params": {
                "username": agent_id,
                "password": agent_secret,
            },
        },
    }

    response = await client.post(
        AUTHN_URL,
        json=payload,
        headers={"Content-Type": "application/json"},
    )

    print(f"    POST {AUTHN_URL}")
    print(f"    Status: {response.status_code}")

    result = response.json()
    flow_status = result.get("flowStatus")
    print(f"    flowStatus: {flow_status}")

    # Code can be at top-level or inside authData
    code = result.get("code") or result.get("authData", {}).get("code")
    print(f"    code: {code}")

    if not code:
        print(f"    ERROR - Full response: {json.dumps(result, indent=2)}")
        raise ValueError(f"Authorization code not found in response: {result}")

    return code


async def step3_exchange_code_for_token(
    client: httpx.AsyncClient,
    client_id: str,
    client_secret: str,
    code: str,
    code_verifier: str,
) -> str:
    """
    Step 3: Exchange authorization code for access token (actor token).
    POST /oauth2/token with grant_type=authorization_code.
    """
    data = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "code_verifier": code_verifier,
        "redirect_uri": CALLBACK_URL,
    }

    response = await client.post(
        TOKEN_URL,
        data=data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )

    print(f"    POST {TOKEN_URL}")
    print(f"    Status: {response.status_code}")

    if response.status_code != 200:
        print(f"    ERROR: {response.text}")
        raise ValueError(f"Token exchange failed: {response.status_code} - {response.text}")

    result = response.json()
    access_token = result.get("access_token")
    print(f"    access_token received: {access_token[:60]}...")

    return access_token


async def get_actor_token_3step(
    client: httpx.AsyncClient,
    agent_id: str,
    agent_secret: str,
    app_client_id: str,
    app_client_secret: str,
    scopes: list[str] = None,
    label: str = "AGENT",
) -> str:
    """
    Complete 3-step flow to get an actor token for an agent.
    Uses the given app_client_id/secret for authorize and token endpoints.
    - Orchestrator agent: pass Orchestrator application credentials
    - Worker agents: pass Token Exchanger application credentials
    """
    if scopes is None:
        scopes = ["openid"]

    print_header(f"3-STEP ACTOR TOKEN FLOW: {label}")
    print(f"  Agent ID: {agent_id}")
    print(f"  Application Client ID: {app_client_id}")

    # Generate PKCE
    code_verifier, code_challenge = generate_pkce()
    print(f"  PKCE code_verifier: {code_verifier[:30]}...")
    print(f"  PKCE code_challenge: {code_challenge[:30]}...")

    # Use a FRESH client per flow to avoid session cookie carryover
    async with httpx.AsyncClient(verify=False, timeout=30.0) as fresh_client:

        # Step 1: POST /oauth2/authorize (response_mode=direct) -> flowId
        print(f"\n  --- Step 1: Get flowId (response_mode=direct) ---")
        flow_id, direct_code = await step1_get_flow_id(
            fresh_client,
            client_id=app_client_id,
            client_secret=app_client_secret,
            scopes=scopes,
            code_challenge=code_challenge,
        )

        if direct_code:
            # Session was active, authorize returned code directly - skip step 2
            print(f"  (Session active - got code directly from authorize)")
            code = direct_code
        else:
            # Step 2: POST /oauth2/authn (flowId + agent creds) -> code
            print(f"\n  --- Step 2: Authenticate agent (agent_id/secret) -> code ---")
            code = await step2_authenticate_agent(
                fresh_client,
                flow_id=flow_id,
                agent_id=agent_id,
                agent_secret=agent_secret,
            )

        # Step 3: POST /oauth2/token (authorization_code) -> actor token
        print(f"\n  --- Step 3: Exchange code -> actor token ---")
        actor_token = await step3_exchange_code_for_token(
            fresh_client,
            client_id=app_client_id,
            client_secret=app_client_secret,
            code=code,
            code_verifier=code_verifier,
        )

    print_token(
        f"{label}_ACTOR_TOKEN",
        actor_token,
        f"Actor token for {label} (agent_id: {agent_id})",
    )
    print_jwt_claims(actor_token)

    return actor_token


# ─────────────────────────────────────────────────────────────────
# Token Exchange (RFC 8693) - Downscoping
# ─────────────────────────────────────────────────────────────────

async def token_exchange_downscope(
    client: httpx.AsyncClient,
    subject_token: str,
    actor_token: str,
    target_scopes: list[str],
    label: str = "AGENT",
) -> str:
    """
    RFC 8693 Token Exchange: downscope using subject_token (orchestrator)
    + actor_token (specific agent) into a scoped token for the respective API.
    """
    data = {
        "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
        "subject_token": subject_token,
        "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
        "actor_token": actor_token,
        "actor_token_type": "urn:ietf:params:oauth:token-type:access_token",
        "scope": " ".join(target_scopes),
    }

    # Use HTTP Basic Auth (client_secret_basic) for WSO2 IS
    import base64 as b64
    basic_auth = b64.b64encode(f"{TOKEN_EXCHANGER_CLIENT_ID}:{TOKEN_EXCHANGER_CLIENT_SECRET}".encode()).decode()

    response = await client.post(
        TOKEN_URL,
        data=data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {basic_auth}",
        },
    )

    print(f"    POST {TOKEN_URL}")
    print(f"    Status: {response.status_code}")

    if response.status_code != 200:
        print(f"    ERROR: {response.text}")
        raise ValueError(f"Token exchange failed: {response.status_code} - {response.text}")

    result = response.json()
    exchanged_token = result.get("access_token")

    print_token(
        f"{label}_EXCHANGED_TOKEN",
        exchanged_token,
        f"Downscoped token for {label} with scopes {target_scopes}",
    )
    print_jwt_claims(exchanged_token)

    return exchanged_token


# ─────────────────────────────────────────────────────────────────
# Main Flow
# ─────────────────────────────────────────────────────────────────

async def main():
    print_header("A2A TOKEN FLOW DEMONSTRATION")
    print(f"  Time: {datetime.now().isoformat()}")
    print(f"  Identity Server: {BASE_URL}")
    print(f"  Token Exchanger Client ID: {TOKEN_EXCHANGER_CLIENT_ID}")
    print(f"  Orchestrator Agent ID: {ORCHESTRATOR_AGENT_ID}")

    async with httpx.AsyncClient(verify=False, timeout=30.0) as client:

        # ─────────────────────────────────────────────────────────
        # PHASE 1: Get Orchestrator Agent Actor Token
        # 3-step flow: authorize(direct) -> authn(agent creds) -> token
        # ─────────────────────────────────────────────────────────
        try:
            orchestrator_actor_token = await get_actor_token_3step(
                client,
                agent_id=ORCHESTRATOR_AGENT_ID,
                agent_secret=ORCHESTRATOR_AGENT_SECRET,
                app_client_id=ORCHESTRATOR_CLIENT_ID,
                app_client_secret=ORCHESTRATOR_CLIENT_SECRET,
                scopes=["openid"],
                label="ORCHESTRATOR",
            )
        except Exception as e:
            print(f"\n  [FATAL] Failed to get orchestrator actor token: {e}")
            import traceback
            traceback.print_exc()
            return

        # ─────────────────────────────────────────────────────────
        # PHASE 2: For each worker agent:
        #   a) Get agent's actor token (same 3-step flow)
        #   b) Token Exchange: orchestrator_token (subject)
        #      + agent_token (actor) -> downscoped token
        # ─────────────────────────────────────────────────────────
        for agent_key, agent_cfg in AGENTS.items():
            agent_id = agent_cfg["agent_id"]
            agent_secret = agent_cfg["agent_secret"]
            target_scopes = agent_cfg["scopes"]

            if not agent_id or not agent_secret:
                print(f"\n  [SKIP] {agent_key}: missing agent_id or agent_secret")
                continue

            try:
                # Step A: Get this agent's actor token (3-step flow, Token Exchanger app)
                agent_actor_token = await get_actor_token_3step(
                    client,
                    agent_id=agent_id,
                    agent_secret=agent_secret,
                    app_client_id=TOKEN_EXCHANGER_CLIENT_ID,
                    app_client_secret=TOKEN_EXCHANGER_CLIENT_SECRET,
                    scopes=["openid"],
                    label=agent_key.upper(),
                )

                # Step B: Token Exchange (downscope)
                # Subject = orchestrator actor token
                # Actor = this agent's actor token
                # Scopes = agent-specific scopes
                print_header(f"TOKEN EXCHANGE (DOWNSCOPE): {agent_key.upper()}")
                print(f"  Subject Token: ORCHESTRATOR_ACTOR_TOKEN")
                print(f"  Actor Token: {agent_key.upper()}_ACTOR_TOKEN")
                print(f"  Target Scopes: {target_scopes}")

                exchanged_token = await token_exchange_downscope(
                    client,
                    subject_token=orchestrator_actor_token,
                    actor_token=agent_actor_token,
                    target_scopes=target_scopes,
                    label=agent_key.upper(),
                )

            except Exception as e:
                print(f"\n  [ERROR] {agent_key}: {e}")
                import traceback
                traceback.print_exc()
                continue

        # ─────────────────────────────────────────────────────────
        # Summary
        # ─────────────────────────────────────────────────────────
        print_header("TOKEN FLOW SUMMARY")
        print("""
  Flow per the Asgardeo AI Agent Authentication doc:

  1. ORCHESTRATOR_ACTOR_TOKEN (3-step flow)
     Step 1: POST /oauth2/authorize (response_mode=direct) -> flowId
     Step 2: POST /oauth2/authn (flowId + orchestrator agent_id/secret) -> code
     Step 3: POST /oauth2/token (authorization_code + code_verifier) -> actor token

  2. Per-Agent ACTOR_TOKENs (same 3-step flow per agent)
     |-- HR_AGENT_ACTOR_TOKEN
     |-- IT_AGENT_ACTOR_TOKEN
     |-- APPROVAL_AGENT_ACTOR_TOKEN
     |-- BOOKING_AGENT_ACTOR_TOKEN

  3. EXCHANGED_TOKENs (RFC 8693 Token Exchange / Downscoping)
     Subject: Orchestrator Actor Token
     Actor:   Agent Actor Token
     Scopes:  Per-agent scopes
     |-- HR_AGENT_EXCHANGED_TOKEN       (scopes: hr:read hr:write)
     |-- IT_AGENT_EXCHANGED_TOKEN       (scopes: it:read it:write)
     |-- APPROVAL_AGENT_EXCHANGED_TOKEN (scopes: approval:read approval:write)
     |-- BOOKING_AGENT_EXCHANGED_TOKEN  (scopes: booking:read booking:write)
        """)


if __name__ == "__main__":
    asyncio.run(main())
