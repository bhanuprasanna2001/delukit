import os
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import (
    Cookie,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
)
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend import auth, db, forecasts, keys
from backend.forecast_schema import ForecastResponse
from backend.mail import configured, send_contact, send_verify

PUBLIC_URL = os.getenv("DELU_PUBLIC_URL", "http://localhost:8000")
COOKIE_SECURE = os.getenv("DELU_COOKIE_SECURE", "0") == "1"


@asynccontextmanager
async def lifespan(_: FastAPI):
    if os.getenv("DELU_REQUIRE_MAIL") == "1" and not configured():
        raise RuntimeError("Configure Resend or SMTP before public deployment")
    db.init()
    yield


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
            headers={"Retry-After": str(retry)},
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


@app.get(
    "/v1/forecast",
    operation_id="getForecast",
    tags=["Forecasts"],
    summary="Get a forecast",
    description=(
        "Returns the latest available DE-LU forecast for a quantity and span, "
        "or a specific published run when date and gate are supplied. "
        "Pass your key through the Authorize control or the X-API-Key header. "
        "All series align with timestamps by array position. "
        "The limit is 60 requests per minute and 5,000 per day per key."
    ),
    response_model=ForecastResponse,
    responses={
        401: {"description": "Missing or invalid API key."},
        404: {"description": "No forecast matches the requested run and quantity."},
        429: {"description": "Minute or daily request limit reached."},
    },
)
def v1_forecast(
    date: str | None = Query(
        default=None,
        description="Origin date, YYYY-MM-DD. Omit for the latest matching run.",
    ),
    gate: str | None = Query(
        default=None,
        description="Run time in Europe/Berlin: 0530 or 1130. Omit for the latest available gate.",
    ),
    span: str = Query(
        default="d1", description="d1 for day ahead or d10 for ten days."
    ),
    target: str = Query(
        default="load_actual_mw",
        description="Quantity identifier. GET /api/options lists the published targets and runs.",
    ),
    type: str = Query(
        default="probabilistic",
        description="probabilistic returns P10-P90; point returns P50 with other quantiles null.",
    ),
    _key: dict = Depends(api_key_user),
) -> dict:
    if type not in ("point", "probabilistic"):
        raise HTTPException(status_code=400, detail="Type is point or probabilistic.")
    return _forecast(date, gate, span, target, type)


@app.get("/openapi-forecast.json", include_in_schema=False)
def openapi_forecast() -> dict:
    full = app.openapi()
    paths = {"/v1/forecast": full["paths"]["/v1/forecast"]}
    operation = paths["/v1/forecast"]["get"]
    operation["parameters"] = [
        parameter
        for parameter in operation.get("parameters", [])
        if parameter["name"].lower() not in {"x-api-key", "authorization"}
    ]
    operation["security"] = [{"ApiKey": []}, {"Bearer": []}]

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
        "info": {
            "title": "DELU forecast API",
            "version": full["info"]["version"],
            "description": (
                "Published power forecasts for the DE-LU bidding zone. "
                "Create an account, confirm your email, and authorize with your API key."
            ),
        },
        "paths": paths,
        "tags": [{"name": "Forecasts", "description": "Published forecast series."}],
        "components": components,
    }


@app.get("/api/export")
def api_export(
    start: str,
    end: str,
    target: str = "load_actual_mw",
    gate: str = "0530",
    kind: str = "point",
    tz: str = "Europe/Berlin",
    horizon_days: int = 1,
    format: str = "csv",
    _user: dict = Depends(verified_user),
) -> Response:
    try:
        name, media, data = forecasts.export_file(
            start, end, target, gate, kind, tz, horizon_days, format
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except forecasts.Missing as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(
        data,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@app.post("/api/contact")
def contact(body: ContactIn, request: Request) -> dict:
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
    sent = send_contact(name, email, topic, message)
    if os.getenv("DELU_REQUIRE_MAIL") == "1" and not sent:
        raise HTTPException(
            status_code=503, detail="Mail is unavailable. Try again later."
        )
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
    try:
        send_verify(body.email.strip().lower(), f"{PUBLIC_URL}/?verify={token}")
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail="Account created, but confirmation mail failed. Sign in and retry.",
        ) from exc
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
    try:
        send_verify(user["email"], f"{PUBLIC_URL}/?verify={token}")
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503, detail="Confirmation mail failed."
        ) from exc
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
    if user is None:
        raise HTTPException(status_code=401, detail="Your session is no longer valid.")
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
