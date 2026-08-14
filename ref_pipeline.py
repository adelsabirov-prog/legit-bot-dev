import os,re,json,time,base64,io,logging
import requests
from PIL import Image

logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")

BASE="https://openrouter.ai/api/v1"
QWEN_KEY=os.environ["QWEN_KEY"]
QWEN3_MODEL="qwen/qwen3-vl-235b-a22b-instruct"
CATALOG_FILE="catalog.json"
REF_STORE_FILE="ref_store.json"
REF_URLS_FILE="ref_urls.txt"

DESIGN_TRANSCRIBE="""Посмотри на фото парфюмерии. Заполни поля дизайна продукта.
Ответь СТРОГО валидным JSON без маркдауна и комментариев:
{"product_visible":true,"silhouette":"cylinder|rectangular|sphere|other","hw_ratio":<число, отношение высоты флакона к ширине, например 2.3>,"glass":"<прозрачность_цвет по-английски через подчёркивание, например transparent_pink, opaque_white, tinted_blue>","logo_text":"<текст логотипа как виден>","logo_case":"lower|upper|mixed","font_style":"serif|sans|script","blocks_order":[<блоки на флаконе сверху вниз из: logo, ornament, name, concentration, volume, other>],"cap_shape":"truncated_cone|cylinder|sphere|flat|other","cap_color":"<цвет по-английски>","box_blocks":[<блоки лицевой стороны коробки сверху вниз, если коробка видна, иначе []>],"label_bbox":[x1,y1,x2,y2],"cap_bbox":[x1,y1,x2,y2]}
Координаты — целые числа 0-1000 (область этикетки флакона и область крышки). Если поле не видно — null. Если флакона нет в кадре — {"product_visible":false}."""

def ask_vision(b64s,prompt):
    content=[{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b}"}} for b in b64s]
    content.append({"type":"text","text":prompt})
    body={"model":QWEN3_MODEL,"messages":[{"role":"user","content":content}],"temperature":0}
    r=requests.post(BASE+"/chat/completions",headers={"Authorization":"Bearer "+QWEN_KEY,"Content-Type":"application/json"},json=body,timeout=120)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

def downscale(b64,limit=1600):
    im=Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
    w,h=im.size; m=max(w,h)
    if m>limit:
        k=limit/m; im=im.resize((int(w*k),int(h*k)),Image.LANCZOS)
    buf=io.BytesIO(); im.save(buf,"JPEG",quality=85)
    return base64.b64encode(buf.getvalue()).decode()

def fetch_main_photo(url):
    r=requests.get(url,timeout=30,headers={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) legitcheck-ref-bot"})
    r.raise_for_status()
    m=re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"',r.text) or re.search(r'<meta[^>]+content="([^"]+)"[^>]+property="og:image"',r.text)
    if not m: return None
    src=m.group(1)
    if src.startswith("//"): src="https:"+src
    im=requests.get(src,timeout=30)
    im.raise_for_status()
    return downscale(base64.b64encode(im.content).decode())

def transcribe(b64):
    raw=ask_vision([b64],DESIGN_TRANSCRIBE)
    m=re.search(r"\{.*\}",raw,re.S)
    if not m: return None
    try:
        d=json.loads(m.group(0))
    except Exception:
        return None
    return d if d.get("product_visible",True) else None

def crop_b64(b64,box):
    im=Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
    w,h=im.size
    x1,y1,x2,y2=box
    x1=int(x1/1000*w); x2=int(x2/1000*w); y1=int(y1/1000*h); y2=int(y2/1000*h)
    im=im.crop((max(0,x1),max(0,y1),min(w,x2),min(h,y2)))
    buf=io.BytesIO(); im.save(buf,"JPEG",quality=88)
    return base64.b64encode(buf.getvalue()).decode()

def norm_name(t):
    import unicodedata
    t=unicodedata.normalize("NFD",t or "")
    t="".join(ch for ch in t if not unicodedata.combining(ch))
    t=re.sub(r"[^a-z0-9а-яё]+"," ",t.lower())
    return re.sub(r"\s+"," ",t).strip()

HARD=("silhouette","logo_case","font_style","cap_shape")

def hard_diff(a,b):
    out=[]
    for f in HARD:
        va,vb=a.get(f),b.get(f)
        if va and vb and str(va).strip().lower()!=str(vb).strip().lower(): out.append(f)
    ra,rb=a.get("blocks_order") or [],b.get("blocks_order") or []
    if ra and rb and ra!=rb: out.append("blocks_order")
    return out

def process_line(line):
    parts=[p.strip() for p in line.split("|")]
    if len(parts)<3: return
    url,name,brand=parts[0],parts[1],parts[2]
    official=parts[3] if len(parts)>3 else None
    m=re.search(r"-(\d+)\.html",url)
    source="fragrantica/"+(m.group(1) if m else norm_name(name))
    photo=fetch_main_photo(url)
    if not photo:
        logging.warning("REF no og:image %s",url); return
    d=transcribe(photo)
    if not d:
        logging.warning("REF transcribe fail %s",url); return
    crops={}
    for key in ("label_bbox","cap_bbox"):
        bb=d.get(key)
        if bb and len(bb)==4 and all(isinstance(v,(int,float)) for v in bb):
            try: crops[key.replace("_bbox","")]=crop_b64(photo,bb)
            except Exception: pass
    status="auto"
    if official:
        try:
            op=fetch_main_photo(official)
            if op:
                od=transcribe(op)
                if od and hard_diff(od,d):
                    status="review"
                    logging.info("REF cross mismatch %s -> review",source)
        except Exception:
            logging.exception("REF official fetch")
    with open(CATALOG_FILE,encoding="utf-8") as f:
        cat=json.load(f)
    rec=next((r for r in cat if norm_name(r.get("name",""))==norm_name(name)),None)
    if not rec:
        rec={"name":name,"brand":brand,"aliases":[]}
        cat.append(rec)
    rec["design"]={"status":status,"source":source,
        "fields":{k:d.get(k) for k in ("silhouette","hw_ratio","glass","logo_text","logo_case","font_style","blocks_order","cap_shape","cap_color","box_blocks")}}
    with open(CATALOG_FILE,"w",encoding="utf-8") as f:
        json.dump(cat,f,ensure_ascii=False,indent=1)
    store={}
    try:
        with open(REF_STORE_FILE,encoding="utf-8") as f: store=json.load(f)
    except Exception: pass
    store[source]={"photo":photo,"crops":crops}
    with open(REF_STORE_FILE,"w",encoding="utf-8") as f:
        json.dump(store,f)
    logging.info("REF done %s status=%s",source,status)

if __name__=="__main__":
    with open(REF_URLS_FILE,encoding="utf-8") as f:
        lines=[l.strip() for l in f if l.strip() and not l.startswith("#")]
    for line in lines:
        try:
            process_line(line)
        except Exception:
            logging.exception("REF line fail")
        time.sleep(2)




