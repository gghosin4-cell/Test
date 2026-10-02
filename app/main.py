import base64, hashlib, os, secrets
from datetime import datetime
from urllib.parse import urlparse

import qrcode
from fastapi import FastAPI, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeSerializer, BadSignature
from sqlalchemy.orm import Session

from .db import SessionLocal, init_db
from .models import User, Config

app = FastAPI(title=os.getenv("APP_NAME", "Soli Panel"))
templates = Jinja2Templates(directory="templates")
serializer = URLSafeSerializer(os.getenv("SECRET_KEY", "dev-secret-change-me"), salt="admin-session")

@app.on_event("startup")
def startup():
    os.makedirs("data", exist_ok=True)
    init_db()

def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()

def base_url(request: Request):
    return os.getenv("PUBLIC_BASE_URL") or str(request.base_url).rstrip("/")

def admin_ok(request: Request):
    raw = request.cookies.get("admin_session")
    if not raw:
        return False
    try:
        return serializer.loads(raw).get("ok") is True
    except BadSignature:
        return False

def bytes_text(n):
    if n <= 0: return "نامحدود"
    units = ["B","KB","MB","GB","TB"]
    x = float(n); i = 0
    while x >= 1024 and i < len(units)-1:
        x /= 1024; i += 1
    return f"{x:.1f} {units[i]}"

def expired(u):
    return bool(u.expires_at and u.expires_at < datetime.utcnow())

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/", response_class=HTMLResponse)
def home():
    return RedirectResponse("/admin")

@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request, s: Session = Depends(db)):
    if not admin_ok(request):
        return templates.TemplateResponse("login.html", {"request": request})
    users = s.query(User).order_by(User.id.desc()).all()
    return templates.TemplateResponse("admin.html", {"request": request, "users": users, "bytes_text": bytes_text})

@app.post("/admin/login")
def login(username: str = Form(...), password: str = Form(...)):
    if username != os.getenv("ADMIN_USERNAME", "admin") or password != os.getenv("ADMIN_PASSWORD", "change-this-password"):
        return RedirectResponse("/admin?error=1", status_code=303)
    r = RedirectResponse("/admin", status_code=303)
    r.set_cookie("admin_session", serializer.dumps({"ok": True}), httponly=True,
                 secure=os.getenv("COOKIE_SECURE","false").lower()=="true", samesite="lax")
    return r

@app.post("/admin/logout")
def logout():
    r = RedirectResponse("/admin", status_code=303)
    r.delete_cookie("admin_session")
    return r

@app.post("/admin/users/create")
def create_user(request: Request, name: str = Form(...), traffic_gb: float = Form(0),
                expires_at: str = Form(""), s: Session = Depends(db)):
    if not admin_ok(request): raise HTTPException(401)
    u = User(name=name.strip(), token=secrets.token_urlsafe(32),
             traffic_limit=max(0, int(traffic_gb * 1024**3)))
    if expires_at:
        try: u.expires_at = datetime.fromisoformat(expires_at)
        except ValueError: pass
    s.add(u); s.commit()
    return RedirectResponse("/admin", status_code=303)

@app.post("/admin/users/{uid}/toggle")
def toggle_user(uid: int, request: Request, s: Session = Depends(db)):
    if not admin_ok(request): raise HTTPException(401)
    u=s.get(User, uid)
    if u: u.active=not u.active; s.commit()
    return RedirectResponse("/admin", status_code=303)

@app.post("/admin/users/{uid}/delete")
def delete_user(uid: int, request: Request, s: Session = Depends(db)):
    if not admin_ok(request): raise HTTPException(401)
    u=s.get(User, uid)
    if u: s.delete(u); s.commit()
    return RedirectResponse("/admin", status_code=303)

@app.get("/admin/users/{uid}", response_class=HTMLResponse)
def edit_user(uid: int, request: Request, s: Session = Depends(db)):
    if not admin_ok(request): return RedirectResponse("/admin")
    u=s.get(User, uid)
    if not u: raise HTTPException(404)
    return templates.TemplateResponse("edit.html", {"request":request,"u":u,"bytes_text":bytes_text,"base_url":base_url(request)})

@app.post("/admin/users/{uid}/save")
def save_user(uid:int, request:Request, name:str=Form(...), traffic_gb:float=Form(0),
              traffic_used_gb:float=Form(0), expires_at:str=Form(""), active:bool=Form(False),
              s:Session=Depends(db)):
    if not admin_ok(request): raise HTTPException(401)
    u=s.get(User,uid)
    if not u: raise HTTPException(404)
    u.name=name.strip()
    u.traffic_limit=max(0,int(traffic_gb*1024**3))
    u.traffic_used=max(0,int(traffic_used_gb*1024**3))
    u.active=active
    u.expires_at=datetime.fromisoformat(expires_at) if expires_at else None
    s.commit()
    return RedirectResponse(f"/admin/users/{uid}", status_code=303)

@app.post("/admin/users/{uid}/configs")
def add_config(uid:int, request:Request, name:str=Form(...), content:str=Form(...), s:Session=Depends(db)):
    if not admin_ok(request): raise HTTPException(401)
    if not s.get(User,uid): raise HTTPException(404)
    s.add(Config(user_id=uid,name=name.strip(),content=content.strip()))
    s.commit()
    return RedirectResponse(f"/admin/users/{uid}", status_code=303)

@app.post("/admin/configs/{cid}/delete")
def delete_config(cid:int, request:Request, s:Session=Depends(db)):
    if not admin_ok(request): raise HTTPException(401)
    c=s.get(Config,cid)
    if c:
        uid=c.user_id; s.delete(c); s.commit()
        return RedirectResponse(f"/admin/users/{uid}", status_code=303)
    return RedirectResponse("/admin", status_code=303)

@app.get("/u/{token}", response_class=HTMLResponse)
def user_panel(token:str, request:Request, s:Session=Depends(db)):
    u=s.query(User).filter_by(token=token).first()
    if not u: raise HTTPException(404,"User not found")
    links=[{"name":c.name,"content":c.content} for c in u.configs if c.enabled]
    remaining=max(0,u.traffic_limit-u.traffic_used) if u.traffic_limit else 0
    usage=round(u.traffic_used/u.traffic_limit*100,1) if u.traffic_limit else 0
    return templates.TemplateResponse("user.html", {"request":request,"user":{
        "name":u.name,"active":u.active and not expired(u),"traffic_used":bytes_text(u.traffic_used),
        "traffic_limit":bytes_text(u.traffic_limit),"remaining":bytes_text(remaining),
        "expires":u.expires_at.strftime("%Y-%m-%d %H:%M") if u.expires_at else "بدون انقضا",
        "subscription_url":f"{base_url(request)}/sub/{u.token}",
        "links":links,"usage":usage
    }})

@app.get("/sub/{token}")
def subscription(token:str, s:Session=Depends(db)):
    u=s.query(User).filter_by(token=token).first()
    if not u or not u.active or expired(u):
        raise HTTPException(404,"Subscription unavailable")
    rows=[c.content.strip() for c in u.configs if c.enabled and c.content.strip()]
    payload="\n".join(rows)
    encoded=base64.b64encode(payload.encode()).decode()
    return PlainTextResponse(encoded, headers={"Content-Disposition":"inline; filename=subscription.txt"})

@app.get("/sub/{token}/raw")
def subscription_raw(token:str,s:Session=Depends(db)):
    u=s.query(User).filter_by(token=token).first()
    if not u or not u.active or expired(u): raise HTTPException(404)
    return PlainTextResponse("\n".join(c.content.strip() for c in u.configs if c.enabled))

@app.get("/qr/{token}.png")
def qr(token:str, request:Request, s:Session=Depends(db)):
    u=s.query(User).filter_by(token=token).first()
    if not u: raise HTTPException(404)
    img=qrcode.make(f"{base_url(request)}/sub/{token}")
    import io
    buf=io.BytesIO(); img.save(buf,"PNG"); buf.seek(0)
    return StreamingResponse(buf,media_type="image/png")
