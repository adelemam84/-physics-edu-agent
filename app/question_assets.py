from __future__ import annotations
import fitz
from fastapi import Depends, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field
from .main import app
from .db import connect
from .security import require_admin
from .services.storage import get_bytes, put_bytes

class AssetCrop(BaseModel):
    crop_x: float = Field(ge=0, le=1)
    crop_y: float = Field(ge=0, le=1)
    crop_width: float = Field(gt=0, le=1)
    crop_height: float = Field(gt=0, le=1)

@app.get('/api/questions/{question_id}/asset', dependencies=[Depends(require_admin)])
def get_asset(question_id:int):
    with connect() as con: row=con.execute('SELECT * FROM question_assets WHERE question_id=%s',(question_id,)).fetchone()
    if not row: raise HTTPException(404,'Question asset not found')
    return row

@app.get('/api/questions/{question_id}/asset/image', dependencies=[Depends(require_admin)])
def get_asset_image(question_id:int):
    with connect() as con: row=con.execute('SELECT object_key FROM question_assets WHERE question_id=%s',(question_id,)).fetchone()
    if not row: raise HTTPException(404,'Question asset not found')
    return Response(get_bytes(row['object_key']),media_type='image/jpeg',headers={'Cache-Control':'private,max-age=300'})

@app.post('/api/questions/{question_id}/asset', dependencies=[Depends(require_admin)])
def save_asset(question_id:int,crop:AssetCrop):
    if crop.crop_x+crop.crop_width>1.000001 or crop.crop_y+crop.crop_height>1.000001: raise HTTPException(400,'Crop outside page')
    with connect() as con:
        q=con.execute('SELECT q.document_id,coalesce(q.source_page,q.page) page_number,f.object_key FROM questions q JOIN document_files f ON f.document_id=q.document_id WHERE q.id=%s',(question_id,)).fetchone()
    if not q: raise HTTPException(404,'Question source not found')
    raw=get_bytes(q['object_key']); pdf=fitz.open(stream=raw,filetype='pdf'); page=pdf.load_page(int(q['page_number'])-1); r=page.rect
    clip=fitz.Rect(r.x0+crop.crop_x*r.width,r.y0+crop.crop_y*r.height,r.x0+(crop.crop_x+crop.crop_width)*r.width,r.y0+(crop.crop_y+crop.crop_height)*r.height)
    if clip.width<8 or clip.height<8: pdf.close(); raise HTTPException(400,'Crop too small')
    pix=page.get_pixmap(matrix=fitz.Matrix(2,2),clip=clip,alpha=False); image=pix.tobytes('jpeg',jpg_quality=90); iw,ih=pix.width,pix.height; pdf.close()
    key=f'question-assets/{question_id}.jpg'; put_bytes(key,image,'image/jpeg')
    with connect() as con:
        return con.execute('''INSERT INTO question_assets(question_id,document_id,page_number,object_key,crop_x,crop_y,crop_width,crop_height,image_width,image_height) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(question_id) DO UPDATE SET document_id=excluded.document_id,page_number=excluded.page_number,object_key=excluded.object_key,crop_x=excluded.crop_x,crop_y=excluded.crop_y,crop_width=excluded.crop_width,crop_height=excluded.crop_height,image_width=excluded.image_width,image_height=excluded.image_height,updated_at=now() RETURNING *''',(question_id,q['document_id'],q['page_number'],key,crop.crop_x,crop.crop_y,crop.crop_width,crop.crop_height,iw,ih)).fetchone()

ASSET_ADMIN=r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>قص السؤال</title><style>body{font-family:system-ui;background:#f5f7fb;margin:0;color:#172033}main{max-width:1200px;margin:auto;padding:16px}.box{background:#fff;border-radius:16px;padding:14px;margin:10px 0}.grid{display:grid;grid-template-columns:280px 1fr 280px;gap:12px}.item{padding:8px;border-bottom:1px solid #eee;cursor:pointer}.stage{position:relative;display:inline-block;max-width:100%;touch-action:none}.stage img{display:block;max-width:100%;max-height:78vh}.sel{position:absolute;border:3px solid #175cd3;background:#175cd322;display:none;pointer-events:none}.asset{max-width:100%;border-radius:10px}.muted{color:#667085;font-size:13px}input,button{padding:10px;border:1px solid #ccd2dd;border-radius:9px}@media(max-width:900px){.grid{grid-template-columns:1fr}.stage img{max-height:none}}</style><main><h1>قص السؤال والرسم من المصدر</h1><div class=box><a href="/admin/dashboard">لوحة التحكم</a> · <a href="/admin/workflow">العودة للمراجعة</a><span id=msg></span></div><div class=grid><div class=box><h3>الأسئلة</h3><div id=questions></div></div><div class=box><div id=title class=muted>اختر سؤالًا</div><div id=stage class=stage><img id=pageImg><div id=selBox class=sel></div></div><p><button onclick=resetCrop()>مسح التحديد</button> <button onclick=saveCrop()>حفظ القصاصة</button></p><div id=cropMsg class=muted></div></div><div class=box><h3>القصاصة المحفوظة</h3><img id=assetImg class=asset><div id=assetMeta class=muted></div></div></div></main><script>let qs=[],q=null,start=null,crop=null,drag=false;function h(){return {}}async function blobUrl(u){let r=await fetch(u,{headers:h(),cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);return URL.createObjectURL(await r.blob())}async function loadQs(){qs=await fetch('/api/questions?limit=1000',{headers:h()}).then(async r=>{if(r.status===401){location.href='/admin/login';return []}return r.json()});questions.innerHTML=qs.length?qs.map(x=>`<div class=item onclick="pick(${x.id})">#${x.id} · صفحة ${x.source_page||x.page}<br>${String(x.text_verbatim).slice(0,100)}</div>`).join(''):'لا توجد أسئلة. أضف سؤالًا أولًا من لوحة المراجعة.'}async function pick(id){q=qs.find(x=>x.id==id);resetCrop();title.textContent=`${q.source_filename} — صفحة ${q.source_page||q.page} — سؤال #${q.id}`;pageImg.src=await blobUrl(`/api/documents/${q.document_id}/page/${q.source_page||q.page}/preview`);loadAsset()}function pt(e){let r=pageImg.getBoundingClientRect();return{x:Math.max(0,Math.min(r.width,e.clientX-r.left)),y:Math.max(0,Math.min(r.height,e.clientY-r.top)),w:r.width,h:r.height}}stage.onpointerdown=e=>{if(!q)return;drag=true;start=pt(e);stage.setPointerCapture(e.pointerId);selBox.style.display='block';draw(start,start)};stage.onpointermove=e=>{if(drag)draw(start,pt(e))};stage.onpointerup=e=>{if(!drag)return;drag=false;let p=pt(e),x=Math.min(start.x,p.x),y=Math.min(start.y,p.y),w=Math.abs(start.x-p.x),hh=Math.abs(start.y-p.y);draw(start,p);if(w<12||hh<12){resetCrop();return}crop={crop_x:x/p.w,crop_y:y/p.h,crop_width:w/p.w,crop_height:hh/p.h};cropMsg.textContent='تم التحديد. اضغط حفظ القصاصة.'};function draw(a,b){let x=Math.min(a.x,b.x),y=Math.min(a.y,b.y),w=Math.abs(a.x-b.x),hh=Math.abs(a.y-b.y);Object.assign(selBox.style,{left:x+'px',top:y+'px',width:w+'px',height:hh+'px'})}function resetCrop(){crop=null;selBox.style.display='none';cropMsg.textContent='اسحب بإصبعك أو الماوس حول السؤال بالكامل مع الرسم والاختيارات.'}async function saveCrop(){if(!q||!crop){cropMsg.textContent='اختر سؤالًا وحدد منطقته أولًا';return}let r=await fetch(`/api/questions/${q.id}/asset`,{method:'POST',headers:{...h(),'Content-Type':'application/json'},body:JSON.stringify(crop)}),x=await r.json();cropMsg.textContent=r.ok?'تم حفظ Question Asset بنجاح':(x.detail||'خطأ');if(r.ok)loadAsset()}async function loadAsset(){assetImg.removeAttribute('src');assetMeta.textContent='';let r=await fetch(`/api/questions/${q.id}/asset`,{headers:h()});if(!r.ok){assetMeta.textContent='لا توجد قصاصة محفوظة بعد';return}let a=await r.json();assetImg.src=await blobUrl(`/api/questions/${q.id}/asset/image`);assetMeta.textContent=`${a.image_width}×${a.image_height} · صفحة ${a.page_number}`}loadQs();</script></html>'''
@app.get('/admin/assets',response_class=HTMLResponse)
def admin_assets(): return ASSET_ADMIN
