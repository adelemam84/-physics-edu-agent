from __future__ import annotations

from fastapi import Body, Depends
from fastapi.responses import HTMLResponse

from .main import app
from .security import require_admin
from .services.science_diagram_specs import preview_diagram_spec, schema_catalog, validate_diagram_spec


@app.get('/api/admin/lesson-studio/diagram-specs', dependencies=[Depends(require_admin)])
def diagram_spec_catalog():
    return schema_catalog()


@app.post('/api/admin/lesson-studio/diagram-specs/validate', dependencies=[Depends(require_admin)])
def diagram_spec_validate(payload: dict = Body(...)):
    return validate_diagram_spec(str(payload.get('kind') or ''), payload.get('parameters'))


@app.post('/api/admin/lesson-studio/diagram-specs/preview', dependencies=[Depends(require_admin)])
def diagram_spec_preview(payload: dict = Body(...)):
    return preview_diagram_spec(
        str(payload.get('kind') or ''),
        str(payload.get('title') or 'رسم علمي'),
        payload.get('parameters'),
    )


PAGE = r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Scientific Diagram Specification Builder</title>
<style>
*{box-sizing:border-box}body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:1120px;margin:auto;padding:14px}.card{background:#fff;border:1px solid #e4e7ec;border-radius:15px;padding:15px;margin:10px 0}.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}select,input,textarea,button{font:inherit;padding:9px;border:1px solid #d0d5dd;border-radius:8px}input,textarea{width:100%}textarea{min-height:330px;font-family:ui-monospace,Consolas,monospace;direction:ltr;text-align:left}button{cursor:pointer}.primary{background:#101828;color:#fff}.muted{color:#667085}.ok{color:#027a48}.bad{color:#b42318}pre{white-space:pre-wrap;word-break:break-word;background:#f8fafc;padding:10px;border-radius:10px;max-height:380px;overflow:auto}.preview{overflow:auto;min-height:180px;border:1px dashed #d0d5dd;border-radius:10px;padding:10px}.schema{max-height:340px;overflow:auto}@media(max-width:760px){.grid{grid-template-columns:1fr}}
</style><main>
<div class=card><a href="/admin/lesson-studio/tools">أدوات الدرس</a> · <a href="/admin/lesson-studio/workspace">مساحة العمل</a> · <a href="/admin/dashboard">لوحة التحكم</a></div>
<div class=card><h1>Scientific Diagram Specification Builder</h1><p class=muted>يبني ويختبر مواصفات الرسومات العلمية قبل إرسالها للـrenderer. الحقول الزائدة أو العلاقات غير الصحيحة تُرفض، ولا يتم استنتاج قيم علمية ناقصة.</p></div>
<div class=grid>
<div class=card><h2>المواصفات</h2><label>نوع الرسم<select id=kind></select></label><label>عنوان الرسم<input id=title value="رسم علمي"></label><label>JSON parameters<textarea id=params>{}</textarea></label><div class=row><button id=validate class=primary>Validate</button><button id=preview>Preview</button><button id=example>تحميل مثال</button></div><div id=status></div></div>
<div><div class=card><h2>Preview</h2><div id=svg class=preview></div><pre id=result>لم يتم الفحص بعد.</pre></div><div class=card><h2>Schema</h2><pre id=schema class=schema></pre></div></div>
</div>
<script>
const $=s=>document.querySelector(s);let catalog=null;
const examples={
resistor_network:{nodes:[{id:"A",x:.1,y:.5},{id:"B",x:.5,y:.25},{id:"C",x:.5,y:.75},{id:"D",x:.9,y:.5}],components:[{type:"resistor",from:"A",to:"B",label:"R1"},{type:"resistor",from:"A",to:"C",label:"R2"},{type:"wire",from:"B",to:"D"},{type:"wire",from:"C",to:"D"}]},
series_parallel_circuit:{nodes:[{id:"A",x:.1,y:.5},{id:"B",x:.4,y:.5},{id:"C",x:.65,y:.25},{id:"D",x:.65,y:.75},{id:"E",x:.9,y:.5}],components:[{type:"resistor",from:"A",to:"B",label:"R1"},{type:"resistor",from:"B",to:"C",label:"R2"},{type:"resistor",from:"B",to:"D",label:"R3"},{type:"wire",from:"C",to:"E"},{type:"wire",from:"D",to:"E"}]},
ray_diagram:{optical_element:{type:"convex_lens",x:.5,label:"عدسة محدبة"},focal_points:[.35,.65],rays:[{points:[[.1,.35],[.5,.35],[.9,.7]]}]},
magnetic_field:{current_direction:"out_of_page",field_direction:"counterclockwise",label:"I"},
solenoid_field:{current_direction:"left_to_right",field_direction:"right_to_left",north_side:"left",turns:8,label:"L1"},
molecule_bond:{atoms:[{id:"C",element:"C",x:.5,y:.5},{id:"O1",element:"O",x:.25,y:.5},{id:"O2",element:"O",x:.75,y:.5}],bonds:[{from:"C",to:"O1",order:2},{from:"C",to:"O2",order:2}]},
chemistry_lab_setup:{vessels:[{id:"A",type:"flask",x:.15,y:.5,label:"دورق"},{id:"B",type:"gas_jar",x:.8,y:.5,label:"وعاء تجميع"}],connections:[{from:"A",to:"B",direction:"from_to",label:"أنبوب توصيل"}]}
};
async function api(url,opts){let r=await fetch(url,opts);if(r.status===401){location.href="/admin/login";throw new Error("auth")}let x=await r.json().catch(()=>null);if(!r.ok)throw new Error(JSON.stringify(x?.detail||x||r.status));return x}
function payload(){let p;try{p=JSON.parse($("#params").value)}catch(e){throw new Error("JSON غير صالح: "+e.message)}return {kind:$("#kind").value,title:$("#title").value,parameters:p}}
function showSchema(){let k=$("#kind").value;$("#schema").textContent=JSON.stringify(catalog?.kinds?.[k]||{},null,2)}
async function load(){catalog=await api("/api/admin/lesson-studio/diagram-specs");$("#kind").innerHTML=Object.keys(catalog.kinds).map(k=>`<option value="${k}">${k}</option>`).join("");showSchema();loadExample()}
function loadExample(){$("#params").value=JSON.stringify(examples[$("#kind").value]||{},null,2);showSchema();$("#svg").innerHTML="";$("#result").textContent="جاهز للفحص."}
async function run(preview){try{let x=await api(preview?"/api/admin/lesson-studio/diagram-specs/preview":"/api/admin/lesson-studio/diagram-specs/validate",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload())});$("#result").textContent=JSON.stringify(x,null,2);$("#status").innerHTML=x.valid?'<p class=ok>✅ المواصفات صالحة.</p>':'<p class=bad>⚠️ المواصفات مرفوضة قبل الرسم.</p>';$("#svg").innerHTML=preview&&x.svg?x.svg:""}catch(e){$("#status").innerHTML='<p class=bad>'+String(e.message)+'</p>';$("#svg").innerHTML=""}}
$("#kind").addEventListener("change",loadExample);$("#example").addEventListener("click",loadExample);$("#validate").addEventListener("click",()=>run(false));$("#preview").addEventListener("click",()=>run(true));load().catch(e=>$("#status").textContent=e.message);
</script></main></html>'''


@app.get('/admin/lesson-studio/diagram-specs', response_class=HTMLResponse)
def diagram_spec_builder_page():
    return PAGE
