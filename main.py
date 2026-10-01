from contextlib import asynccontextmanager
from pathlib import Path
import json, os, sqlite3, secrets, hashlib, hmac
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from pydantic import BaseModel, Field
from app.recommendations import generate_recommendations

load_dotenv()
BASE = Path(__file__).resolve().parent
DB_PATH = os.getenv('DATABASE_PATH', str(BASE.parent / 'pocketsmart.db'))
SECRET = os.getenv('SECRET_KEY', 'dev-only-change-this-secret')
signer = URLSafeTimedSerializer(SECRET, salt='pocketsmart-session')
templates = Jinja2Templates(directory=str(BASE / 'templates'))

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as c:
        c.executescript("""CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, password TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, planner TEXT NOT NULL, request TEXT NOT NULL, result TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(user_id) REFERENCES users(id));""")

@asynccontextmanager
async def lifespan(app):
    init_db()
    yield

app = FastAPI(title='PocketSmart AI', version='1.0.0', lifespan=lifespan)
app.mount('/static', StaticFiles(directory=str(BASE / 'static')), name='static')

def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 310000)
    return salt.hex() + '$' + digest.hex()

def verify_password(password, encoded):
    try:
        salt, expected = encoded.split('$', 1)
        got = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 310000).hex()
        return hmac.compare_digest(got, expected)
    except (ValueError, TypeError):
        return False

def current_user(request):
    token = request.cookies.get('pocket_session')
    if not token: return None
    try:
        uid = signer.loads(token, max_age=60*60*24*14)
    except (BadSignature, SignatureExpired): return None
    with db() as c: return c.execute('SELECT id,email FROM users WHERE id=?', (uid,)).fetchone()

def require_user(request):
    user = current_user(request)
    if not user: raise HTTPException(401, 'Please sign in to save and view your plans.')
    return user

@app.get('/', response_class=HTMLResponse)
@app.get('/', response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"user": current_user(request)},
    )

@app.get('/health')
async def health(): return {'status':'ok', 'ai_configured': bool(os.getenv('GEMINI_API_KEY'))}

class Credentials(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=8, max_length=128)

@app.post('/api/register')
async def register(payload: Credentials):
    email = payload.email.strip().lower()
    if '@' not in email: raise HTTPException(400, 'Enter a valid email address.')
    try:
        with db() as c:
            cur = c.execute('INSERT INTO users(email,password) VALUES(?,?)', (email, hash_password(payload.password)))
            uid = cur.lastrowid
    except sqlite3.IntegrityError: raise HTTPException(409, 'An account with this email already exists.')
    response = {'ok': True, 'email': email}
    return session_response(response, uid)

@app.post('/api/login')
async def login(payload: Credentials):
    with db() as c: user = c.execute('SELECT id,email,password FROM users WHERE email=?', (payload.email.strip().lower(),)).fetchone()
    if not user or not verify_password(payload.password, user['password']): raise HTTPException(401, 'Email or password is incorrect.')
    return session_response({'ok': True, 'email': user['email']}, user['id'])

def session_response(payload, uid):
    from fastapi.responses import JSONResponse
    r = JSONResponse(payload); r.set_cookie('pocket_session', signer.dumps(uid), httponly=True, samesite='lax', secure=os.getenv('COOKIE_SECURE','false').lower()=='true', max_age=1209600)
    return r

@app.post('/api/logout')
async def logout():
    from fastapi.responses import JSONResponse
    r=JSONResponse({'ok':True}); r.delete_cookie('pocket_session'); return r

@app.get('/api/session-info')
async def session_info(request: Request):
    u=current_user(request); return {'logged_in': bool(u), 'email': u['email'] if u else None}

@app.get('/api/session-data')
async def session_data(request: Request):
    u=require_user(request)
    with db() as c: count=c.execute('SELECT COUNT(*) FROM history WHERE user_id=?',(u['id'],)).fetchone()[0]
    return {'user_id':u['id'],'email':u['email'],'saved_plans':count}

@app.get('/api/history')
async def history(request: Request):
    u=require_user(request)
    with db() as c: rows=c.execute('SELECT id,planner,request,result,created_at FROM history WHERE user_id=? ORDER BY id DESC LIMIT 30',(u['id'],)).fetchall()
    return {'items':[dict(r, request=json.loads(r['request']), result=json.loads(r['result'])) for r in rows]}

@app.get('/api/recommendations-details/{item_id}')
async def details(item_id: int, request: Request):
    u=require_user(request)
    with db() as c: row=c.execute('SELECT id,planner,request,result,created_at FROM history WHERE id=? AND user_id=?',(item_id,u['id'])).fetchone()
    if not row: raise HTTPException(404,'Plan not found.')
    return dict(row, request=json.loads(row['request']), result=json.loads(row['result']))

class HomeInput(BaseModel):
    budget: float = Field(gt=0, le=100000000)
    currency: str = 'INR'
    rooms: list[str] = Field(min_length=1, max_length=8)
    style: str = 'Modern'
    priorities: str = ''

class PartyInput(BaseModel):
    budget: float = Field(gt=0, le=100000000)
    currency: str = 'INR'
    event_type: str = 'Birthday'
    guests: int = Field(gt=0, le=10000)
    city: str = ''
    preferences: str = ''

async def save_plan(user, planner, data, result):
    with db() as c:
        cur=c.execute('INSERT INTO history(user_id,planner,request,result) VALUES(?,?,?,?)',(user['id'],planner,json.dumps(data),json.dumps(result)))
        return cur.lastrowid

@app.post('/api/generate-home')
async def generate_home_plan(payload: HomeInput, request: Request):
    u = require_user(request)
    data = payload.model_dump()
    result = await generate_recommendations('home', data)
    result['plan_id'] = await save_plan(u, 'home', data, result)
    return result

@app.post('/api/generate-party')
async def party_plan(payload: PartyInput, request: Request):
    u=require_user(request); data=payload.model_dump(); result=await generate_recommendations('party',data)
    result['plan_id']=await save_plan(u,'party',data,result); return result

@app.post('/api/generate-jewelry')
async def jewelry_plan(request: Request, budget: float = Form(gt=0), currency: str = Form('INR'), occasion: str = Form('Celebration'), style: str = Form('Elegant'), preferences: str = Form(''), outfit_image: Optional[UploadFile] = File(None)):
    u=require_user(request)
    image_bytes=None; image_type=None
    if outfit_image and outfit_image.filename:
        if not outfit_image.content_type or not outfit_image.content_type.startswith('image/'): raise HTTPException(400,'Upload a valid image file.')
        image_bytes=await outfit_image.read(5*1024*1024+1)
        if len(image_bytes)>5*1024*1024: raise HTTPException(413,'Image must be 5 MB or smaller.')
        image_type=outfit_image.content_type
    data={'budget':budget,'currency':currency,'occasion':occasion,'style':style,'preferences':preferences,'image_uploaded':bool(image_bytes)}
    result=await generate_recommendations('jewelry',data,image_bytes,image_type)
    result['plan_id']=await save_plan(u,'jewelry',data,result); return result
