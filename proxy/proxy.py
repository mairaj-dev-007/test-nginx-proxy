from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import JSONResponse
import httpx
import os
import json
import random

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)  # Disable FastAPI docs

# Upstream servers configuration (like Nginx upstream)
# Format: {"server1": "http://host1:port1", "server2": "http://host2:port2"}
UPSTREAM_SERVERS_STR = os.getenv("UPSTREAM_SERVERS", '{"litellm": "http://litellm:4000"}')
try:
    UPSTREAM_SERVERS = json.loads(UPSTREAM_SERVERS_STR)
except json.JSONDecodeError:
    UPSTREAM_SERVERS = {"litellm": "http://litellm:4000"}

# Server routing configuration (like Nginx location blocks)
# Format: {"domain1.com": {"upstream": "server1", "allowed_ips": ["ip1", "ip2"]}}
SERVER_CONFIG_STR = os.getenv("SERVER_CONFIG", "{}")
try:
    SERVER_CONFIG = json.loads(SERVER_CONFIG_STR)
except json.JSONDecodeError:
    SERVER_CONFIG = {}

# Default upstream if no routing configured
DEFAULT_UPSTREAM = os.getenv("DEFAULT_UPSTREAM", "litellm")

@app.middleware("http")
async def nginx_style_proxy(request: Request, call_next):
    client_ip = request.client.host
    host = request.headers.get("host", "").split(":")[0]  # Remove port if present
    
    # If no server config, use default upstream
    if not SERVER_CONFIG:
        # Store upstream for the proxy handler
        request.state.upstream = UPSTREAM_SERVERS.get(DEFAULT_UPSTREAM, list(UPSTREAM_SERVERS.values())[0])
        return await call_next(request)
    
    # Check if the domain/host is configured
    if host in SERVER_CONFIG:
        config = SERVER_CONFIG[host]
        
        # Check IP whitelist if configured
        if "allowed_ips" in config and config["allowed_ips"]:
            if client_ip not in config["allowed_ips"]:
                return Response(
                    f"403 Forbidden: IP {client_ip} not allowed for {host}",
                    status_code=403
                )
        
        # Get upstream server
        upstream_name = config.get("upstream", DEFAULT_UPSTREAM)
        if upstream_name not in UPSTREAM_SERVERS:
            return Response(
                f"502 Bad Gateway: Upstream '{upstream_name}' not configured",
                status_code=502
            )
        
        request.state.upstream = UPSTREAM_SERVERS[upstream_name]
    else:
        # Domain not configured, deny or use default based on config
        if SERVER_CONFIG:  # If config exists, deny unknown hosts
            return Response(
                f"404 Not Found: Host {host} not configured",
                status_code=404
            )
        request.state.upstream = UPSTREAM_SERVERS.get(DEFAULT_UPSTREAM, list(UPSTREAM_SERVERS.values())[0])
    
    return await call_next(request)

@app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"], include_in_schema=False)
@app.get("/", include_in_schema=False)
async def proxy(request: Request, full_path: str = ""):
    # Get upstream from middleware
    upstream_url = getattr(request.state, "upstream", UPSTREAM_SERVERS.get(DEFAULT_UPSTREAM))
    url = f"{upstream_url}/{full_path}" if full_path else upstream_url

    # Copy headers, remove host to avoid conflicts
    headers = dict(request.headers)
    headers.pop("host", None)

    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.request(
                request.method,
                url,
                headers=headers,
                content=await request.body(),
                params=request.query_params,
                timeout=30.0,
            )
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Bad Gateway: {str(e)}")

    # Return response with original status code and headers
    return Response(content=resp.content, status_code=resp.status_code, headers=dict(resp.headers))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
