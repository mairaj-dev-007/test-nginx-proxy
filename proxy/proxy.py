from fastapi import FastAPI, Request, Response, HTTPException
import httpx
import os

app = FastAPI()

# Target backend URL (litellm service)
TARGET_URL = os.getenv("TARGET_URL", "http://litellm:4000")

# Optional: Allowed IPs (comma-separated)
ALLOWED_IPS = os.getenv("ALLOWED_IPS", "").split(",")

@app.middleware("http")
async def ip_filter(request: Request, call_next):
    client_ip = request.client.host
    if ALLOWED_IPS and client_ip not in ALLOWED_IPS:
        return Response("Forbidden", status_code=403)
    return await call_next(request)

@app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy(request: Request, full_path: str):
    url = f"{TARGET_URL}/{full_path}"

    # Copy headers, remove host to avoid conflicts
    headers = dict(request.headers)
    headers.pop("host", None)

    try:
        async with httpx.AsyncClient() as client:
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
    return Response(content=resp.content, status_code=resp.status_code, headers=resp.headers)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
