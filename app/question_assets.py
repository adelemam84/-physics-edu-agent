from __future__ import annotations
import fitz
import io
import re
import zipfile
from fastapi import Depends, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field
from .content_phase_guard import require_content_ingestion_enabled
from .main import app
from .db import connect
from .security import require_admin
from .services.storage import get_bytes, put_bytes


def _resolve_visual_review(con, question_id:int) -> None:
    con.execute("""UPDATE question_review_notes
                   SET status='resolved',
                       details=coalesce(details,'')||' | تم ربط Question Asset بصري واضح بالمصدر.',
                       updated_at=now()
                   WHERE question_id=%s AND reason_code='visual_asset_required' AND status='open'""",
                (question_id,))

def _question_ready_for_human_approval(con, question_id:int) -> bool:
    """Return deterministic readiness only; never grant approval."""
    row=con.execute("""SELECT
      q.document_id IS NOT NULL AND coalesce(q.source_page,q.page) IS NOT NULL has_source,
      q.accepted_answer IS NOT NULL AND btrim(q.accepted_answer)<>'' has_answer,
      q.lesson_id IS NOT NULL AND q.subject_id IS NOT NULL AND q.grade_level_id IS NOT NULL
        AND q.curriculum_version_id IS NOT NULL AND q.term_id IS NOT NULL
        AND q.unit_id IS NOT NULL has_scope,
      q.question_type<>'unknown' AND q.difficulty<>'unclassified' classified,
      EXISTS(SELECT 1 FROM question_concepts qc WHERE qc.question_id=q.id) has_concept,
      EXISTS(SELECT 1 FROM question_skills qs WHERE qs.question_id=q.id) has_skill,
      EXISTS(SELECT 1 FROM question_assets a
        WHERE a.question_id=q.id AND a.document_id=q.document_id
          AND a.page_number=coalesce(q.source_page,q.page)) asset_valid,
      NOT EXISTS(SELECT 1 FROM question_review_notes qr
        WHERE qr.question_id=q.id AND qr.status='open') qa_clear
      FROM questions q WHERE q.id=%s""",(question_id,)).fetchone()
    if not row:
        return False
    return all(bool(row[k]) for k in (
        'has_source','has_answer','has_scope','classified',
        'has_concept','has_skill','asset_valid','qa_clear'
    ))

def _store_asset_row(con, question_id:int, document_id:int, page_number:int, key:str,
                     crop_x:float, crop_y:float, crop_width:float, crop_height:float,
                     iw:int, ih:int):
    row=con.execute("""INSERT INTO question_assets
        (question_id,document_id,page_number,object_key,crop_x,crop_y,crop_width,crop_height,image_width,image_height)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT(question_id) DO UPDATE SET
          document_id=excluded.document_id,page_number=excluded.page_number,object_key=excluded.object_key,
          crop_x=excluded.crop_x,crop_y=excluded.crop_y,crop_width=excluded.crop_width,crop_height=excluded.crop_height,
          image_width=excluded.image_width,image_height=excluded.image_height,updated_at=now()
        RETURNING *""",
        (question_id,document_id,page_number,key,crop_x,crop_y,crop_width,crop_height,iw,ih)).fetchone()
    _resolve_visual_review(con,question_id)
    ready=_question_ready_for_human_approval(con,question_id)
    return {**row,'ready_for_human_approval':ready,'approval_changed':False}

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
        return _store_asset_row(con,question_id,q['document_id'],q['page_number'],key,
                                crop.crop_x,crop.crop_y,crop.crop_width,crop.crop_height,iw,ih)

@app.post('/api/questions/{question_id}/asset/upload', dependencies=[Depends(require_admin)])
async def upload_asset(question_id:int,file:UploadFile=File(...)):
    require_content_ingestion_enabled()
    raw=await file.read()
    if not raw: raise HTTPException(400,'Empty image')
    if len(raw)>12*1024*1024: raise HTTPException(413,'Image too large (12 MB max)')
    ctype=(file.content_type or '').lower()
    allowed={'image/jpeg':'jpeg','image/jpg':'jpeg','image/png':'png','image/webp':'webp'}
    if ctype not in allowed: raise HTTPException(415,'Use JPG, PNG or WEBP')
    with connect() as con:
        q=con.execute('SELECT document_id,coalesce(source_page,page) page_number FROM questions WHERE id=%s',(question_id,)).fetchone()
    if not q: raise HTTPException(404,'Question not found')
    try:
        doc=fitz.open(stream=raw,filetype=allowed[ctype])
        if doc.page_count<1: raise ValueError('No image page')
        page=doc.load_page(0)
        pix=page.get_pixmap(alpha=False)
        if pix.width<16 or pix.height<16: raise ValueError('Image too small')
        image=pix.tobytes('jpeg',jpg_quality=90); iw,ih=pix.width,pix.height
        doc.close()
    except Exception as exc:
        raise HTTPException(400,'Invalid image') from exc
    key=f'question-assets/{question_id}.jpg'
    put_bytes(key,image,'image/jpeg')
    with connect() as con:
        return _store_asset_row(con,question_id,q['document_id'],q['page_number'],key,0,0,1,1,iw,ih)

@app.post('/api/admin/question-assets/bulk-upload', dependencies=[Depends(require_admin)])
async def bulk_upload_assets(file:UploadFile=File(...)):
    require_content_ingestion_enabled()
    raw=await file.read()
    if not raw: raise HTTPException(400,'Empty ZIP')
    if len(raw)>80*1024*1024: raise HTTPException(413,'ZIP too large (80 MB max)')
    try:
        zf=zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise HTTPException(400,'Invalid ZIP file') from exc
    results=[]; seen=set()
    for info in zf.infolist():
        if info.is_dir() or info.file_size<=0: continue
        name=info.filename.rsplit('/',1)[-1]
        m=re.fullmatch(r'(?:q)?(\d+)\.(jpg|jpeg|png|webp)',name,re.I)
        if not m: continue
        question_id=int(m.group(1))
        if question_id in seen: continue
        seen.add(question_id)
        if info.file_size>12*1024*1024:
            results.append({'question_id':question_id,'ok':False,'error':'image_too_large'}); continue
        with connect() as con:
            q=con.execute("""SELECT q.document_id,coalesce(q.source_page,q.page) page_number,
              EXISTS(SELECT 1 FROM question_review_notes qr WHERE qr.question_id=q.id AND qr.status='open' AND qr.reason_code='visual_asset_required') needs_visual
              FROM questions q WHERE q.id=%s""",(question_id,)).fetchone()
        if not q:
            results.append({'question_id':question_id,'ok':False,'error':'question_not_found'}); continue
        image_raw=zf.read(info)
        try:
            doc=fitz.open(stream=image_raw,filetype=m.group(2).lower().replace('jpg','jpeg'))
            page=doc.load_page(0); pix=page.get_pixmap(alpha=False)
            if pix.width<16 or pix.height<16: raise ValueError('small')
            image=pix.tobytes('jpeg',jpg_quality=90); iw,ih=pix.width,pix.height; doc.close()
        except Exception:
            results.append({'question_id':question_id,'ok':False,'error':'invalid_image'}); continue
        key=f'question-assets/{question_id}.jpg'
        put_bytes(key,image,'image/jpeg')
        with connect() as con:
            row=_store_asset_row(con,question_id,q['document_id'],q['page_number'],key,0,0,1,1,iw,ih)
            approved=bool(con.execute("SELECT approved FROM questions WHERE id=%s",(question_id,)).fetchone()['approved'])
        results.append({'question_id':question_id,'ok':True,'approved':approved,
                        'ready_for_human_approval':bool(row['ready_for_human_approval']),
                        'approval_changed':False,'width':iw,'height':ih})
    zf.close()
    ok=sum(1 for r in results if r.get('ok'))
    approved=sum(1 for r in results if r.get('approved'))
    ready=sum(1 for r in results if r.get('ready_for_human_approval'))
    return {'processed':len(results),'stored':ok,'approved':approved,
            'already_approved':approved,'ready_for_human_approval':ready,
            'approval_changed':False,'results':results}

ASSET_ADMIN=r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>قص السؤال</title><style>body{font-family:system-ui;background:#f5f7fb;margin:0;color:#172033}main{max-width:1200px;margin:auto;padding:16px}.box{background:#fff;border-radius:16px;padding:14px;margin:10px 0}.grid{display:grid;grid-template-columns:280px 1fr 280px;gap:12px}.item{padding:8px;border-bottom:1px solid #eee;cursor:pointer}.stage{position:relative;display:inline-block;max-width:100%;touch-action:none}.stage img{display:block;max-width:100%;max-height:78vh}.sel{position:absolute;border:3px solid #175cd3;background:#175cd322;display:none;pointer-events:none}.asset{max-width:100%;border-radius:10px}.muted{color:#667085;font-size:13px}input,button{padding:10px;border:1px solid #ccd2dd;border-radius:9px}@media(max-width:900px){.grid{grid-template-columns:1fr}.stage img{max-height:none}}</style><main><h1>قص السؤال والرسم من المصدر</h1><div class=box><a href="/admin/dashboard">لوحة التحكم</a> · <a href="/admin/workflow">العودة للمراجعة</a><span id=msg></span></div><div class=box><h3>رفع جماعي للمراجعة</h3><p class=muted>ارفع ZIP يحتوي صورًا باسم q84.jpg أو 84.png. سيُربط كل ملف بالسؤال ويُغلق سبب الرسم عند تطابق المصدر. رفع الصورة لا يعتمد السؤال تلقائيًا؛ إذا اكتملت بقية شروط الجودة يصبح السؤال جاهزًا للاعتماد اليدوي.</p><input id=bulkFile type=file accept=".zip,application/zip"><button onclick=bulkUpload()>رفع ملف الرسومات</button><div id=bulkMsg class=muted></div></div><div class=grid><div class=box><h3>الأسئلة</h3><div><button id=prevBtn onclick="changePage(-1)">السابق</button> <button id=nextBtn onclick="changePage(1)">التالي</button> <span id=pageInfo class=muted></span></div><div id=questions></div></div><div class=box><div id=title class=muted>اختر سؤالًا</div><div id=stage class=stage><img id=pageImg><div id=selBox class=sel></div></div><p><button onclick=resetCrop()>مسح التحديد</button> <button onclick=saveCrop()>حفظ القصاصة</button></p><div id=cropMsg class=muted></div></div><div class=box><h3>القصاصة المحفوظة</h3><img id=assetImg class=asset><div id=assetMeta class=muted></div><hr><h3>رفع مباشر</h3><p class=muted>استخدمه عندما يكون المصدر في Google Drive أو عندما تريد رفع الرسم/السؤال كصورة جاهزة.</p><input id=uploadFile type=file accept="image/jpeg,image/png,image/webp"><p><button onclick=uploadAsset()>رفع وربط الصورة</button></p><div id=uploadMsg class=muted></div></div></div></main><script>let qs=[],q=null,start=null,crop=null,drag=false,offset=0,total=0;const pageSize=100;function h(){return {}}async function blobUrl(u){let r=await fetch(u,{headers:h(),cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);return URL.createObjectURL(await r.blob())}async function loadQs(){let r=await fetch('/api/admin/question-catalog?limit='+pageSize+'&offset='+offset,{headers:h(),cache:'no-store'});if(r.status===401){location.href='/admin/login';return}let x=await r.json();if(!r.ok){questions.textContent='تعذر تحميل الأسئلة';return}qs=x.items||[];total=Number(x.total||0);pageInfo.textContent=total?('عرض '+(offset+1)+'–'+Math.min(offset+qs.length,total)+' من '+total):'0 سؤال';prevBtn.disabled=offset<=0;nextBtn.disabled=!x.has_more;questions.innerHTML=qs.length?qs.map(v=>`<div class=item onclick="pick(${v.id})">#${v.id} · صفحة ${v.source_page||v.page}<br>${String(v.text_verbatim).slice(0,100)}<br><span class=muted>${v.workflow_state==='reviewed'?'جاهز للاعتماد اليدوي':v.workflow_state==='approved'?'معتمد':v.workflow_state}</span></div>`).join(''):'لا توجد أسئلة في هذه الصفحة.'}function changePage(dir){let next=Math.max(0,offset+dir*pageSize);if(next>=total&&dir>0)return;offset=next;q=null;loadQs()}async function pick(id){q=qs.find(x=>x.id==id);resetCrop();title.textContent=`${q.source_filename||'المصدر'} — صفحة ${q.source_page||q.page} — سؤال #${q.id}`;pageImg.removeAttribute('src');try{pageImg.src=await blobUrl(`/api/documents/${q.document_id}/page/${q.source_page||q.page}/preview`);cropMsg.textContent='اسحب حول السؤال والرسم، أو استخدم الرفع المباشر.'}catch(e){cropMsg.textContent='معاينة الصفحة غير متاحة لهذا المصدر؛ استخدم الرفع المباشر من اليمين.'}loadAsset()}function pt(e){let r=pageImg.getBoundingClientRect();return{x:Math.max(0,Math.min(r.width,e.clientX-r.left)),y:Math.max(0,Math.min(r.height,e.clientY-r.top)),w:r.width,h:r.height}}stage.onpointerdown=e=>{if(!q)return;drag=true;start=pt(e);stage.setPointerCapture(e.pointerId);selBox.style.display='block';draw(start,start)};stage.onpointermove=e=>{if(drag)draw(start,pt(e))};stage.onpointerup=e=>{if(!drag)return;drag=false;let p=pt(e),x=Math.min(start.x,p.x),y=Math.min(start.y,p.y),w=Math.abs(start.x-p.x),hh=Math.abs(start.y-p.y);draw(start,p);if(w<12||hh<12){resetCrop();return}crop={crop_x:x/p.w,crop_y:y/p.h,crop_width:w/p.w,crop_height:hh/p.h};cropMsg.textContent='تم التحديد. اضغط حفظ القصاصة.'};function draw(a,b){let x=Math.min(a.x,b.x),y=Math.min(a.y,b.y),w=Math.abs(a.x-b.x),hh=Math.abs(a.y-b.y);Object.assign(selBox.style,{left:x+'px',top:y+'px',width:w+'px',height:hh+'px'})}function resetCrop(){crop=null;selBox.style.display='none';cropMsg.textContent='اسحب بإصبعك أو الماوس حول السؤال بالكامل مع الرسم والاختيارات.'}async function saveCrop(){if(!q||!crop){cropMsg.textContent='اختر سؤالًا وحدد منطقته أولًا';return}let r=await fetch(`/api/questions/${q.id}/asset`,{method:'POST',headers:{...h(),'Content-Type':'application/json'},body:JSON.stringify(crop)}),x=await r.json();cropMsg.textContent=r.ok?(x.ready_for_human_approval?'تم حفظ القصاصة وأصبح السؤال جاهزًا للاعتماد اليدوي.':'تم حفظ القصاصة؛ ما زالت هناك متطلبات جودة قبل الاعتماد.'):(x.detail||'خطأ');if(r.ok)loadAsset()}async function bulkUpload(){let f=bulkFile.files[0];if(!f){bulkMsg.textContent='اختر ملف ZIP أولًا';return}let fd=new FormData();fd.append('file',f);bulkMsg.textContent='جارٍ معالجة ملف الرسومات...';let r=await fetch('/api/admin/question-assets/bulk-upload',{method:'POST',body:fd,headers:h()}),x=await r.json();if(!r.ok){bulkMsg.textContent=x.detail||'تعذر رفع الملف';return}bulkMsg.textContent='تمت معالجة '+x.processed+' صورة؛ حُفظ '+x.stored+'، وجاهز للاعتماد اليدوي '+x.ready_for_human_approval+' سؤالًا. لا يحدث اعتماد تلقائي.';if(x.stored)loadQs()}
async function uploadAsset(){if(!q){uploadMsg.textContent='اختر سؤالًا أولًا';return}let f=uploadFile.files[0];if(!f){uploadMsg.textContent='اختر صورة JPG أو PNG أو WEBP';return}let fd=new FormData();fd.append('file',f);uploadMsg.textContent='جارٍ الرفع...';let r=await fetch(`/api/questions/${q.id}/asset/upload`,{method:'POST',body:fd,headers:h()}),x=await r.json();uploadMsg.textContent=r.ok?(x.ready_for_human_approval?'تم رفع وربط الصورة؛ السؤال جاهز الآن للاعتماد اليدوي.':'تم رفع وربط الصورة؛ ما زالت هناك متطلبات جودة قبل الاعتماد.'):(x.detail||'تعذر الرفع');if(r.ok){uploadFile.value='';loadAsset()}}async function loadAsset(){assetImg.removeAttribute('src');assetMeta.textContent='';let r=await fetch(`/api/questions/${q.id}/asset`,{headers:h()});if(!r.ok){assetMeta.textContent='لا توجد قصاصة محفوظة بعد';return}let a=await r.json();assetImg.src=await blobUrl(`/api/questions/${q.id}/asset/image`);assetMeta.textContent=`${a.image_width}×${a.image_height} · صفحة ${a.page_number}`}loadQs();</script></html>'''
@app.get('/admin/assets',response_class=HTMLResponse)
def admin_assets(): return ASSET_ADMIN
