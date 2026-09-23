import os
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend import auth, db, forecasts, keys
from backend.mail import send_contact, send_verify

PUBLIC_URL = os.getenv("DELU_PUBLIC_URL", "http://localhost:8000")
COOKIE_SECURE = os.getenv("DELU_COOKIE_SECURE", "0") == "1"


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init()
    yield


# The machine-readable surface for key holders is /openapi-forecast.json
# only, rendered in-app by the bundled Swagger UI. The default docs routes
# would expose every internal endpoint (auth, sessions, key rotation) to anyone.
app = FastAPI(
    title="DELU",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    return response


# Per-IP fixed windows for the anonymous /api/* surface (/v1 has per-key
# quotas in keys.py). ponytail: in-memory, exact for the single uvicorn
# worker; move to Redis if workers > 1.
_IP_LIMITS = {"/api/export": (10, 60), "/api/default": (60, 60)}
_ip_hits: dict[str, deque[float]] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "?"


@app.middleware("http")
async def public_rate_limit(request: Request, call_next):
    if not request.url.path.startswith("/api/"):
        return await call_next(request)
    limit, window = _IP_LIMITS.get(request.url.path, _IP_LIMITS["/api/default"])
    now = time.monotonic()
    key = f"{_client_ip(request)}:{request.url.path}"
    hits = _ip_hits[key]
    while hits and hits[0] <= now - window:
        hits.popleft()
    if len(_ip_hits) > 10000:
        _ip_hits.clear()
    if len(hits) >= limit:
        retry = int(hits[0] + window - now) + 1
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit reached. Slow down."},
            headers={
                "Retry-After": str(retry),
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": "0",
            },
        )
    hits.append(now)
    response = await call_next(request)
    response.headers["X-RateLimit-Limit"] = str(limit)
    response.headers["X-RateLimit-Remaining"] = str(limit - len(hits))
    return response


class Signup(BaseModel):
    email: str
    password: str


class Login(BaseModel):
    email: str
    password: str


class DeleteAccount(BaseModel):
    password: str


class ContactIn(BaseModel):
    name: str
    email: str
    topic: str
    message: str


# Contact form: 5 sends per IP per hour. ponytail: in-memory like the
# public rate limiter above; move to Redis if workers > 1.
_contact_hits: dict[str, deque[float]] = defaultdict(deque)


def current_user(delu_session: str | None = Cookie(default=None)) -> dict:
    user = auth.session_user(delu_session)
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in first.")
    return user


def verified_user(user: dict = Depends(current_user)) -> dict:
    if not user["verified"]:
        raise HTTPException(
            status_code=403, detail="Confirm your email first. Check your inbox."
        )
    return user


def api_key_user(
    request: Request,
    response: Response,
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> dict:
    raw = x_api_key
    if raw is None and authorization and authorization.startswith("Bearer "):
        raw = authorization[len("Bearer ") :]
    if not raw:
        raise HTTPException(status_code=401, detail="Send your API key.")
    found = keys.lookup(raw)
    if found is None:
        raise HTTPException(status_code=401, detail="That API key is not valid.")
    ok, retry = keys.check_and_hit(found["id"])
    response.headers["X-RateLimit-Minute"] = str(keys.MIN_LIMIT)
    response.headers["X-RateLimit-Day"] = str(keys.DAY_LIMIT)
    if not ok:
        raise HTTPException(
            status_code=429,
            detail="Rate limit reached. Slow down.",
            headers={
                "Retry-After": str(retry),
                "X-RateLimit-Minute": str(keys.MIN_LIMIT),
                "X-RateLimit-Day": str(keys.DAY_LIMIT),
            },
        )
    keys.touch(found["id"])
    return found


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.get("/api/options")
def api_options() -> dict:
    return forecasts.options()


def _forecast(day, gate, span, target, kind) -> dict:
    try:
        return forecasts.load(day, gate, span, target, kind)
    except forecasts.Missing as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/forecast")
def api_forecast(
    date: str | None = None,
    gate: str | None = None,
    span: str = "d1",
    target: str = "load_actual_mw",
    type: str = "probabilistic",
) -> dict:
    if type not in ("point", "probabilistic"):
        raise HTTPException(status_code=400, detail="Type is point or probabilistic.")
    return _forecast(date, gate, span, target, type)


@app.get("/v1/forecast", operation_id="getForecast")
def v1_forecast(
    date: str | None = None,
    gate: str | None = None,
    span: str = "d1",
    target: str = "load_actual_mw",
    type: str = "probabilistic",
    _key: dict = Depends(api_key_user),
) -> dict:
    """Fetch a stored forecast. Send the API key as X-API-Key or a Bearer token."""
    if type not in ("point", "probabilistic"):
        raise HTTPException(status_code=400, detail="Type is point or probabilistic.")
    return _forecast(date, gate, span, target, type)


@app.get("/openapi-forecast.json", include_in_schema=False)
def openapi_forecast() -> dict:
    full = app.openapi()
    paths = {"/v1/forecast": full["paths"]["/v1/forecast"]}

    def gather(node, out: set[str]) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "$ref" and isinstance(v, str) and v.startswith("#/components/"):
                    out.add(v)
                else:
                    gather(v, out)
        elif isinstance(node, list):
            for v in node:
                gather(v, out)

    # Keep only the components the forecast path actually references
    # (e.g. the generic 422 validation schemas), nothing from auth/keys.
    pending: set[str] = set()
    gather(paths, pending)
    kept: dict[str, dict] = {}
    source = full.get("components", {})
    while pending:
        ref = pending.pop()
        _, _, section, name = ref.split("/", 3)
        section_src = source.get(section, {})
        if name not in section_src or name in kept.get(section, {}):
            continue
        schema = section_src[name]
        kept.setdefault(section, {})[name] = schema
        gather(schema, pending)

    components = {
        "securitySchemes": {
            "ApiKey": {"type": "apiKey", "in": "header", "name": "X-API-Key"},
            "Bearer": {"type": "http", "scheme": "bearer"},
        },
        **kept,
    }
    return {
        "openapi": full["openapi"],
        "info": {"title": "DELU forecast API", "version": full["info"]["version"]},
        "paths": paths,
        "components": components,
        "security": [{"ApiKey": []}],
    }


@app.get("/api/export")
def api_export(
    start: str,
    end: str,
    target: str = "load_actual_mw",
    gate: str = "1130",
    kind: str = "point",
    tz: str = "Europe/Berlin",
    horizon_days: int = 1,
    format: str = "csv",
    _user: dict = Depends(verified_user),
) -> Response:
    """Custom forecast export as CSV, parquet or XLSX, for key holders."""
    try:
        name, media, data = forecasts.export_file(
            start, end, target, gate, kind, tz, horizon_days, format
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except forecasts.Missing as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    # ponytail: whole file in memory; ~5MB at 75 days, stream from disk if bigger.
    return Response(
        data,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@app.post("/api/contact")
def contact(body: ContactIn, request: Request) -> dict:
    """Forward a contact-form message to the operator inbox via Resend/SMTP."""
    from backend import auth as _auth

    name = body.name.strip()[:80]
    email = body.email.strip().lower()[:254]
    topic = body.topic.strip()[:60]
    message = body.message.strip()
    if len(name) < 2:
        raise HTTPException(status_code=400, detail="Tell us your name.")
    if not _auth.EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    if len(message) < 10:
        raise HTTPException(
            status_code=400, detail="Write a message of 10+ characters."
        )
    if len(message) > 4000:
        raise HTTPException(status_code=400, detail="Keep it under 4000 characters.")
    if not topic:
        topic = "General"
    ip = request.client.host if request.client else "?"
    now = time.monotonic()
    hits = _contact_hits[f"contact:{ip}"]
    while hits and hits[0] <= now - 3600:
        hits.popleft()
    if len(hits) >= 5:
        raise HTTPException(
            status_code=429, detail="Too many messages. Try again in an hour."
        )
    hits.append(now)
    send_contact(name, email, topic, message)
    return {"ok": True, "detail": "Message sent. Expect a reply within 2 working days."}


@app.post("/auth/signup")
def signup(body: Signup, request: Request) -> dict:
    ip = request.client.host if request.client else "?"
    try:
        auth.check_throttle(f"signup:{ip}")
    except ValueError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    try:
        user_id = auth.signup(body.email, body.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    auth.note_ok(f"signup:{ip}")
    token = auth.issue_verify_token(user_id)
    send_verify(body.email.strip().lower(), f"{PUBLIC_URL}/?verify={token}")
    return {"ok": True, "detail": "Account created. Check your inbox to confirm."}


@app.get("/auth/verify")
def verify(token: str = "") -> dict:
    user_id = auth.consume_verify_token(token)
    if user_id is None:
        raise HTTPException(status_code=400, detail="That link is invalid or expired.")
    if keys.describe(user_id) is None:
        prefix, raw = keys.issue(user_id)
        return {
            "ok": True,
            "detail": "Email confirmed. Here is your API key.",
            "api_key": raw,
            "prefix": prefix,
        }
    return {"ok": True, "detail": "Email confirmed. You can sign in now."}


@app.post("/auth/resend")
def resend(user: dict = Depends(current_user)) -> dict:
    token = auth.issue_verify_token(user["id"])
    send_verify(user["email"], f"{PUBLIC_URL}/?verify={token}")
    return {"ok": True, "detail": "Confirmation sent. Check your inbox."}


@app.post("/auth/login")
def login(body: Login, request: Request, response: Response) -> dict:
    ip = request.client.host if request.client else "?"
    gate = f"login:{body.email.strip().lower()}:{ip}"
    try:
        auth.check_throttle(gate)
    except ValueError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    token = auth.login(body.email, body.password)
    if token is None:
        auth.note_fail(gate)
        # Same error either way: no account enumeration.
        raise HTTPException(status_code=401, detail="Email or password is wrong.")
    auth.note_ok(gate)
    response.set_cookie(
        auth.SESSION_COOKIE,
        token,
        max_age=auth.SESSION_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
    )
    user = auth.session_user(token)
    return {"email": user["email"], "verified": user["verified"]}


@app.post("/auth/logout")
def logout(response: Response, delu_session: str | None = Cookie(default=None)) -> dict:
    if delu_session:
        auth.logout(delu_session)
    response.delete_cookie(auth.SESSION_COOKIE)
    return {"ok": True}


@app.get("/auth/me")
def me(user: dict = Depends(current_user)) -> dict:
    return {
        "email": user["email"],
        "verified": user["verified"],
        "key": keys.describe(user["id"]) if user["verified"] else None,
    }


@app.delete("/auth/account")
def delete_account(
    body: DeleteAccount,
    response: Response,
    user: dict = Depends(current_user),
) -> dict:
    """Permanently remove the account, key, sessions and usage counters."""
    gate = f"delete:{user['id']}"
    try:
        auth.check_throttle(gate)
    except ValueError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    try:
        auth.delete_account(user["id"], body.password)
    except ValueError as exc:
        auth.note_fail(gate)
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    auth.note_ok(gate)
    response.delete_cookie(auth.SESSION_COOKIE)
    return {"ok": True}


@app.post("/v1/keys/refresh")
def refresh_key(user: dict = Depends(verified_user)) -> dict:
    prefix, raw = keys.issue(user["id"])
    return {
        "prefix": prefix,
        "api_key": raw,
        "detail": "This is the only time the key is shown. The previous key no longer works.",
    }


STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
else:

    @app.get("/")
    def root() -> dict:
        return {"service": "delu"}


@app.exception_handler(forecasts.Missing)
async def missing_handler(_: Request, exc: forecasts.Missing) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})
