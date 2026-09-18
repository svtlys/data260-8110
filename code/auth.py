
import time
from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="templates")

VALID_USERS = {
    "landlord": "rentals123",
}

IDLE_TIMEOUT_SECONDS = 60  

def get_current_user(request: Request):
    user = request.session.get("user")
    last_activity = request.session.get("last_activity")

    if not user or last_activity is None:
        return None

    if time.time() - last_activity > IDLE_TIMEOUT_SECONDS:
        request.session.clear()
        return None

    request.session["last_activity"] = time.time()
    return user


@router.get("/")
def home(request: Request):
    user = get_current_user(request)
    return templates.TemplateResponse(
        request, "home.html", {"user": user}
    )


@router.get("/login")
def login_form(request: Request):
    user = get_current_user(request)
    if user:
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse(
        request, "login.html", {"error": None}
    )


@router.post("/login")
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    if VALID_USERS.get(username) == password:
        request.session["user"] = username
        request.session["last_activity"] = time.time()
        return RedirectResponse(url="/dashboard", status_code=302)

    return templates.TemplateResponse(
        request, "login.html",
        {"error": "Invalid username or password."},
        status_code=401,
    )


@router.get("/dashboard")
def dashboard(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse(
        request, "dashboard.html", {"user": user}
    )


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=302)