import os, base64, logging, io, time, re
import telebot
from telebot import types
import requests
from PIL import Image
from dotenv import load_dotenv

load_dotenv()
TOKEN=os.getenv("BOT_TOKEN")
QWEN_KEY=os.getenv("QWEN_API_KEY")
QWEN_MODEL=os.getenv("QWEN_MODEL","qwen/qwen2.5-vl-72b-instruct")
QWEN_CHEAP=os.getenv("QWEN_MODEL_CHEAP","qwen/qwen2.5-vl-7b-instruct")
BASE=os.getenv("DASHSCOPE_BASE_URL","https://openrouter.ai/api/v1")
OFERTA="https://legitcheck-cosmetics.netlify.app/oferta.html"
PRIVACY=OFERTA+"#privacy"

bot=telebot.TeleBot(TOKEN)
S={}

SYSTEM="""Ты — экспертная система разбора LEGIT·CHECK (косметика и уход). Анализируешь фото продукта по чек-листу и даёшь структурированные ответы на русском.

ЖЁСТКИЕ ПРАВИЛА клиентского текста:
- Запрещены слова «ИИ», «нейросеть», «модель», «узлы», «алгоритм», «контрафакт», «фейк», «слои знаний», «режимы». Используй «детали», «чек-лист», «разбор», «бот».
- Никаких процентов и числовой уверенности. Вердикт — только словами.
- Никаких «100% гарантия», «официальный чек-лист». Вердикт — только из триада с формулировками ниже.
- Не выдумывай: деталь не видна или знаний недостаточно — честно «➖ не проверяется».
- Если изображение размыто, пикселизировано или текст не различим отчётливо — это «нечитаемо». Не угадывай и не восстанавливай текст по размытому снимку.
- Без звёздочек и маркдауна — только обычный текст.

СЛОИ ЗНАНИЙ (по приоритету):
ур.1 — специфические признаки конкретного продукта (название, линейка, форм-фактор): тексты этикетки, индексы, регулятор, формат батча, дизайн упаковки. Применяй, только если уверена в особенностях оригинала.
ур.2 — общие признаки подлинности форм-фактора: качество полиграфии, тиснение, швы и облой литья, посадка крышки и ход механизмов, способ нанесения и шрифт гравировки, согласованность маркировки с упаковкой.
ур.3 — не знаешь продукт или знание может устареть — не проверяй специфические признаки, честно пиши об этом и оценивай только ур.2.

ОСИ НАДЁЖНОСТИ ЧТЕНИЯ: «подтверждено по макро» — сильный; «видно на общем плане» — средний; «косвенно» — слабый, в красный вердикт не считается.

ВЕРДИКТЫ (только словами):
🔴 «Выявлены признаки несоответствия оригиналу» — только при 2+ независимых маркерах, подтверждённых по макро или общему плану.
⚠️ «Есть сомнения в соответствии оригиналу» — 1 надёжный маркер или несколько слабых.
🟢 «Признаков несоответствия оригиналу не выявлено» — маркеры не найдены по проверенным деталям; обязательно укажи, по каким деталям вынесен вердикт.

ВЕСА И ЛОГИКА:
- Критические детали: 01 Упаковка и полиграфия, 02 Тара и литьё, 03 Маркировка и батч-код — ядро вердикта.
- 01 Упаковка и полиграфия — вся полиграфия: коробка (если есть), этикетка, крышка, гравировка. Нет коробки — оценивай по полиграфии тары.
- Маркировка и батч-код — топ-вес; сверка батча на таре и коробке — главный ловитель переупаковки.
- 04-06 (продукт, механизмы, комплектация) — дополнительные: обычно усиливают/ослабляют; аномалия по ним может быть самостоятельным маркером.
- Нормальная текстура/содержимое — односторонний маркер: не снимает 🔴/⚠️.
- Конфликт «коробка читается как оригинал, тара — нет» — признак переупаковки, усиливает 🔴. Хорошая коробка не перевешивает маркеры по таре.

СПИСОК «НЕ ПРОВЕРЯЕТСЯ»: детали из этого списка помечай «➖ не проверяется», выводов по ним не делай; вердикт выноси только по проверенным и укажи это в плашке."""

MODE_LIST="""Продукт: «{name}». Определи форм-фактор (банка, тюбик, флакон с помпой, стик помады, кушон, тушь, палетка и т.п.) и выдай два блока простым клиентским языком.

ОБЯЗАТЕЛЬНО (ядро проверки):
[строго нумерованный список 4-5 кадров под форм-фактор: тара лицо, коробка лицо, батч-код на таре макро, батч-код на коробке макро]

ЖЕЛАТЕЛЬНО (чтобы разбор шёл по всем 6 деталям чек-листа):
[нумерованные 2-3 вторичных ракурса под форм-фактор: текстура на белом листе, крышка и мембрана, коробка зад и дно, механизм, комплектация]

Без других вступлений. Без звёздочек и маркдауна — обычный текст. Не упоминай «слои знаний», «режимы» и внутренние правила — только список снимков."""

MODE0C="""РЕЖИМ 0 (цепочка). Продукт: «{name}».
Оставшиеся обязательные шаги:
{remaining}
На фото косметика или уход? Если явно другой предмет — строго одной строкой:
ТИП: не косметика
Иначе определи, какому из оставшихся шагов (по номеру) соответствует фото, и читаемо ли оно.
Ответь СТРОГО в формате:
ШАГ: [номер из списка; 0, если не подходит ни к одному]
ЧИТАЕМО: да/нет
СОВЕТ: [если нечитаемо — одним предложением как переснять]
Если изображение размыто или текст не различим отчётливо — это «нечитаемо». Не угадывай текст."""

MODE0I="""РЕЖИМ 0 (добавочные фото). Продукт: «{name}».
Сначала определи: на фото косметика или уход? Если явно другой предмет — строго одной строкой:
ТИП: не косметика
Иначе ответь СТРОГО в формате:
ДЕТАЛЬ: [какая деталь чек-листа на фото; «не понял», если не ясно]
ЧИТАЕМО: да/нет
СОВЕТ: [если нет — коротко как переснять]
Если изображение размыто или текст не различим отчётливо — это «нечитаемо». Не угадывай текст."""

MODE0F="""РЕЖИМ 0 (финальный). Продукт: «{name}». Клиент не может предоставить: {cannot}.
Посмотри все фото и оцени каждую критическую деталь отдельно:
01 Упаковка и полиграфия — читаемо, если видна упаковка или этикетка и различим текст.
02 Тара и литьё — читаемо, если видна тара общим планом (банка/флакон/тюбик).
03 Маркировка и батч-код — читаемо, если различим батч-код на таре или коробке.
Если изображение размыто или текст не различим отчётливо — это «нечитаемо». Не угадывай текст по размытому снимку.
Ответь СТРОГО в формате, без других слов:
01: читаемо/нечитаемо
02: читаемо/нечитаемо
03: читаемо/нечитаемо
MISSING: [НАЗВАНИЯ деталей из 6 (не номера), по которым нет читаемых фото, кроме тех, что клиент не может предоставить; «нет», если все покрыты]"""

MODE2="""РЕЖИМ 2. Дай финальный клиентский отчёт по продукту «{name}». Детали из списка «НЕ ПРОВЕРЯЕТСЯ» и детали без читаемых фото помечай «➖ не проверяется» без выводов по ним.
БАТЧ И ГОД: если уверена в формате батча конкретного бренда — проверь согласованность года выпуска с дизайном упаковки, строкой дистрибьютора и линейкой; несоответствие — маркер (учитывается в детали 03). Если не уверена — не выводи дату и не делай из неё маркер.
Формат — обычный текст, БЕЗ звёздочек и маркдауна:
1) Плашка: эмодзи (🔴/⚠️/🟢) + вердикт словами из триада + 1-2 предложения основания + отдельной строкой: «Вердикт вынесен по деталям: [список]».
2) Шесть деталей, по каждой строка статуса строго из набора (✅ проверено / ⚠️ сомнение / ❌ маркер / ➖ не проверяется; знак для непроверяемых — именно ➖, не тире) и 1-2 предложения обоснования:
01 Упаковка и полиграфия
02 Тара и литьё
03 Маркировка и батч-код
04 Продукт внутри
05 Механизмы и фурнитура
06 Комплектация и защита
3) Строка: «Состав и безопасность самого содержимого по фото не верифицируются.»
4) Строка: «Результат — оценочное мнение по видимым признакам; не является экспертизой или юридическим заключением.»"""

START_TEXT=("👋 Legit Check Cosmetics — проверка признаков подлинности косметики по фото.\n\n"
"Как это работает:\n"
"1. Напишите бренд и название продукта — подскажу, какие ракурсы снять.\n"
"2. По шагам соберём обязательные кадры, желательные — пачкой.\n"
"3. После подтверждения пригодности фото — оплата: 500 ₽ (Стандартный, до 3 ч) или 1000 ₽ (Экспресс, до 15 мин).\n"
"4. Получаете структурированный отчёт с вердиктом.\n\n"
"Напишите бренд и название продукта.\nПример: «Крем Loreal», «Помада Dior».")

HELP_TEXT=("Я бот LEGIT·CHECK: разбираю косметику по фото на признаки несоответствия оригиналу — по чек-листу из 6 деталей.\n\n"
"Стоимость: 500 ₽ (Стандартный, до 3 ч) или 1000 ₽ (Экспресс, до 15 мин).\n\n"
"Чтобы начать, напишите бренд и название продукта.\nПример: «Крем Loreal», «Помада Dior».")

FALLBACK_STEPS=["Лицо тары (общий вид)","Лицо коробки (общий вид)","Батч-код на таре (макро)","Батч-код на коробке (макро)"]

def ask_qwen(images,user_text,model):
    content=[{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b}"}} for b in images]
    content.append({"type":"text","text":user_text})
    r=None
    for attempt in range(3):
        r=requests.post(BASE+"/chat/completions",
            headers={"Authorization":"Bearer "+QWEN_KEY,"Content-Type":"application/json"},
            json={"model":model,"messages":[{"role":"system","content":SYSTEM},{"role":"user","content":content}]},
            timeout=180)
        if r.status_code in (429,500,502,503):
            logging.error("QWEN RETRY %s %s",r.status_code,r.text[:500])
            time.sleep(4*(attempt+1))
            continue
        break
    if r.status_code!=200:
        logging.error("QWEN ERROR %s %s",r.status_code,r.text[:1500])
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

def downscale_b64(raw):
    im=Image.open(io.BytesIO(raw)).convert("RGB")
    w,h=im.size; m=max(w,h)
    comp=m<1600
    if m>1600:
        k=1600/m; im=im.resize((int(w*k),int(h*k)),Image.LANCZOS)
    buf=io.BytesIO(); im.save(buf,"JPEG",quality=85)
    return base64.b64encode(buf.getvalue()).decode(), comp

def img_b64(m):
    fid=m.photo[-1].file_id if m.content_type=="photo" else m.document.file_id
    fp=bot.get_file(fid).file_path
    r=requests.get(f"https://api.telegram.org/file/bot{TOKEN}/{fp}",timeout=60)
    return downscale_b64(r.content)

def st(cid):
    return S.setdefault(cid,{"name":"","photos":[],"shots":"","queue":[],"closed":[],"cannot":[],"last_missing":[],"stage":"name","source":"","tariff":"","comp_warned":False})

def reset(cid):
    S[cid]={"name":"","photos":[],"shots":"","queue":[],"closed":[],"cannot":[],"last_missing":[],"stage":"name","source":"","tariff":"","comp_warned":False}
    kb=types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("📄 Оферта",url=OFERTA),types.InlineKeyboardButton("🔒 Политика конфиденциальности",url=PRIVACY))
    bot.send_message(cid,START_TEXT,reply_markup=kb)

def parse(res,key):
    for line in res.splitlines():
        if line.upper().startswith(key):
            return line.split(":",1)[1].strip()
    return ""

def clean_missing(s):
    bad=("нет","none","-","—","")
    return [x.strip() for x in s.split(",") if x.strip().lower() not in bad]

def parse_steps(shots):
    steps=[]; inb=False
    for line in shots.splitlines():
        l=line.strip(); u=l.upper()
        if u.startswith("ОБЯЗАТЕЛЬНО"):
            inb=True; continue
        if inb:
            if u.startswith("ЖЕЛАТЕЛЬНО") or u.startswith("ДОПОЛНИТЕЛЬНО"):
                break
            m=re.match(r"^(\d+)[\.\)]\s*(.+)$",l)
            if m: steps.append(m.group(2).strip())
            elif steps and not l:
                break
    return steps

def wish_part(shots):
    idx=shots.upper().find("ЖЕЛАТЕЛЬНО")
    return shots[idx:] if idx>=0 else shots

def first_open(s):
    for i in range(len(s["queue"])):
        if i not in s["closed"]:
            return i
    return -1

def finish_chain(cid):
    s=st(cid)
    s["stage"]="photos"
    warn=""
    if s["cannot"]:
        warn="\nОбратите внимание: "+", ".join(s["cannot"])+" — не будет проверяться."
    bot.send_message(cid,f"✅ Обязательный блок собран.{warn}\n\n{wish_part(s['shots'])}\nДобавьте эти кадры одним сообщением или напишите «Готово». Если снять не получается — «не могу».")

@bot.message_handler(commands=["start"])
def start(m):
    parts=m.text.split()
    S[m.chat.id]={"name":"","photos":[],"shots":"","queue":[],"closed":[],"cannot":[],"last_missing":[],"stage":"name","source":parts[1] if len(parts)>1 else "","tariff":"","comp_warned":False}
    kb=types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("📄 Оферта",url=OFERTA),types.InlineKeyboardButton("🔒 Политика конфиденциальности",url=PRIVACY))
    bot.send_message(m.chat.id,START_TEXT,reply_markup=kb)

@bot.message_handler(content_types=["photo"])
def photo(m): add_image(m)

@bot.message_handler(content_types=["document"],func=lambda m: m.document and (m.document.mime_type or "").startswith("image"))
def doc(m): add_image(m)

def add_image(m):
    cid=m.chat.id; s=st(cid)
    if s["stage"]=="name":
        bot.send_message(cid,"Сначала напишите бренд и название продукта.")
        return
    if s["stage"]=="tariffs":
        bot.send_message(cid,"Выберите тариф кнопками ниже. Если кнопки пропали — напишите «Начать заново».")
        return
    if s["stage"] in ("done","feedback"):
        bot.send_message(cid,"Отчёт выдан. Для новой проверки напишите «Начать заново».")
        return
    b64,comp=img_b64(m)
    if comp and not s["comp_warned"]:
        s["comp_warned"]=True
        bot.send_message(cid,"⚠️ Фото пришло сжатым (как обычное фото). Мелкие детали — батч, полиграфия — могли потеряться. Для максимальной точности прикрепляйте как документ: скрепка 📎 → «Файл» или «Документ». Продолжаю разбор с тем, что есть.")
    if s["stage"]=="chain":
        remaining="\n".join(f"{i+1}. {s['queue'][i]}" for i in range(len(s["queue"])) if i not in s["closed"])
        try:
            res=ask_qwen([b64],MODE0C.format(name=s["name"] or "?",remaining=remaining),QWEN_CHEAP)
        except Exception:
            logging.exception("mode0c")
            bot.send_message(cid,"Техническая ошибка. Попробуйте ещё раз.")
            return
        if "не косметика" in res.lower():
            bot.send_message(cid,"📥 Получено, но это не косметика или уход — я проверяю только их. Пришлите фото нужного продукта или напишите «Начать заново».")
            return
        num="".join(ch for ch in parse(res,"ШАГ") if ch.isdigit())
        n=int(num) if num else 0
        if n<1 or n>len(s["queue"]) or (n-1) in s["closed"]:
            bot.send_message(cid,"Этот кадр не подходит ни к одному из оставшихся шагов. Осталось:\n"+remaining)
            return
        if not parse(res,"ЧИТАЕМО").lower().startswith("да"):
            bot.send_message(cid,f"📥 Шаг {n} ({s['queue'][n-1]}): нечитаемо. {parse(res,'СОВЕТ') or 'Переснимите при дневном свете, без вспышки.'} Пришлите новый кадр для этого шага.")
            return
        s["closed"].append(n-1)
        s["photos"].append(b64)
        ni=first_open(s)
        if ni>=0:
            bot.send_message(cid,f"✅ Шаг {n} принят. ➡️ Шаг {ni+1}/{len(s['queue'])}: {s['queue'][ni]}")
        else:
            finish_chain(cid)
        return
    try:
        res=ask_qwen([b64],MODE0I.format(name=s["name"] or "?"),QWEN_CHEAP)
    except Exception:
        logging.exception("mode0i")
        bot.send_message(cid,"Техническая ошибка. Попробуйте ещё раз.")
        return
    if "не косметика" in res.lower():
        bot.send_message(cid,"📥 Получено, но это не косметика или уход — я проверяю только их. Пришлите фото нужного продукта или напишите «Начать заново».")
        return
    s["photos"].append(b64)
    det=parse(res,"ДЕТАЛЬ") or "фото"
    if parse(res,"ЧИТАЕМО").lower().startswith("да"):
        bot.send_message(cid,f"📥 Фото {len(s['photos'])} получено: {det}. Читаемо.")
    else:
        bot.send_message(cid,f"📥 Фото {len(s['photos'])} получено: {det}, но нечитаемо. {parse(res,'СОВЕТ') or 'Переснимите при дневном свете, без вспышки.'}")

@bot.message_handler(func=lambda m: m.content_type=="text" and not m.text.startswith("/"))
def text(m):
    cid=m.chat.id; s=st(cid); t=m.text.strip()
    if t.lower() in ("старт","начать","начать заново","заново"):
        reset(cid)
        return
    if t.lower() in ("отмена","стоп","cancel"):
        reset(cid)
        bot.send_message(cid,"Проверка отменена. Для новой — напишите «Начать заново».")
        return
    if s["stage"]=="feedback":
        logging.warning("FEEDBACK DOWN %s: %s",cid,t)
        s["stage"]="done"
        bot.send_message(cid,"Спасибо! Обратная связь записана и будет учтена.")
        return
    if s["stage"]=="name":
        low=t.lower()
        if "?" in t or low in ("привет","здравствуйте","добрый день","добрый вечер","хай","ку") or low.startswith(("что это","как работает","сколько стоит","цена","кто ты","что умеешь")):
            bot.send_message(cid,HELP_TEXT)
            return
        s["name"]=t
        try:
            s["shots"]=ask_qwen([],MODE_LIST.format(name=t),QWEN_CHEAP)
        except Exception:
            logging.exception("mode_list")
            s["shots"]=("ОБЯЗАТЕЛЬНО (ядро проверки):\n1. Лицо тары.\n2. Лицо коробки.\n3. Батч-код на таре (макро).\n4. Батч-код на коробке (макро).\n"
                        "ЖЕЛАТЕЛЬНО (чтобы разбор шёл по всем 6 деталям чек-листа):\n5. Текстура на белом листе (макро).\n6. Крышка и мембрана/пломба.")
        s["queue"]=parse_steps(s["shots"]) or FALLBACK_STEPS[:]
        s["closed"]=[]
        s["stage"]="chain"
        bot.send_message(cid,f"Принято, проверяем: {t}.\n\nСобираем обязательные кадры по шагам. Лучше — как документ (📎 → «Документ»), обычные фото тоже принимаю.\n\n➡️ Шаг 1/{len(s['queue'])}: {s['queue'][0]}")
        return
    if s["stage"]=="chain":
        if t.lower() in ("не могу","нет","не получится"):
            ni=first_open(s)
            if ni>=0:
                s["cannot"].append(s["queue"][ni])
                s["closed"].append(ni)
            n2=first_open(s)
            if n2>=0:
                bot.send_message(cid,f"⚠️ Пропускаю шаг. ➡️ Шаг {n2+1}/{len(s['queue'])}: {s['queue'][n2]}")
            else:
                finish_chain(cid)
            return
        if t.lower() in ("готово","done"):
            ni=first_open(s)
            if ni>=0:
                bot.send_message(cid,"Осталось собрать обязательные кадры:\n"+"\n".join(f"{i+1}. {s['queue'][i]}" for i in range(len(s['queue'])) if i not in s['closed'])+"\nПришлите фото или напишите «не могу».")
            else:
                finish_chain(cid)
            return
        bot.send_message(cid,"Сейчас собираем обязательные кадры. Пришлите фото текущего шага или напишите «не могу».")
        return
    if s["stage"]=="photos":
        if t.lower() in ("готово","done"):
            audit(cid)
        elif t.lower() in ("не могу","нет","не получится"):
            s["cannot"]+= [x for x in (s["last_missing"] or []) if x not in s["cannot"]]
            s["last_missing"]=[]
            audit(cid)
        else:
            bot.send_message(cid,"Записал. Добавляйте фото или напишите «Готово».")
        return
    if s["stage"]=="tariffs":
        bot.send_message(cid,"Выберите тариф кнопками ниже. Если кнопки пропали — напишите «Начать заново».")
    elif s["stage"]=="done":
        bot.send_message(cid,"Отчёт выдан. Для новой проверки напишите «Начать заново».")
    else:
        bot.send_message(cid,"Напишите «Начать заново», чтобы начать проверку.")

def audit(cid):
    s=st(cid)
    if not s["photos"]:
        bot.send_message(cid,"Фото не получены — проверка не может быть оказана, оплата не запрашивается.")
        return
    bot.send_message(cid,"🔎 Проверяю фото…")
    try:
        res=ask_qwen(s["photos"],MODE0F.format(name=s["name"] or "?",cannot=", ".join(s["cannot"]) or "нет"),QWEN_CHEAP)
    except Exception:
        logging.exception("mode0f")
        bot.send_message(cid,"Техническая ошибка. Попробуйте ещё раз.")
        return
    def crit(n):
        for line in res.splitlines():
            t=line.strip().lower()
            if t.startswith(n+":") or t.startswith(n+" :"):
                return "нечитаемо" not in t
        return False
    if not (crit("01") and crit("02") and crit("03")):
        kb=types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔄 Начать заново",callback_data="restart"))
        bot.send_message(cid,"По имеющимся фото вердикт вынести невозможно: не хватает критических деталей (упаковка, тара или маркировка). Услуга не оказывается, оплата не запрашивается. Добавьте читаемые фото или начните заново.",reply_markup=kb)
        return
    missing=clean_missing(parse(res,"MISSING"))
    if missing:
        s["stage"]="photos"; s["last_missing"]=missing
        bot.send_message(cid,"Не хватает деталей: "+", ".join(missing)+".\nДобавьте фото или напишите «не могу» — продолжим разбор как есть, эти детали будут помечены «не проверяется».")
    else:
        s["stage"]="tariffs"
        warn=""
        if s["cannot"]:
            warn="\n\nОбратите внимание: "+", ".join(s["cannot"])+" — не будет проверяться. Вердикт будет вынесен по остальным деталям."
        kb=types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("Стандартный — 500 ₽ · до 3 часов",callback_data="std"))
        kb.add(types.InlineKeyboardButton("Экспресс — 1000 ₽ · до 15 минут",callback_data="exp"))
        bot.send_message(cid,f"Фото подходят для проверки.{warn}\n\nВыберите тариф:\n\nОплачивая, вы принимаете условия оферты: {OFERTA}",reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data in ("std","exp","report","restart","close","fb_up","fb_down"))
def cb(c):
    cid=c.message.chat.id; s=st(cid)
    if c.data=="close":
        bot.answer_callback_query(c.id)
        try: bot.edit_message_reply_markup(cid,c.message.message_id)
        except Exception: pass
        return
    if c.data=="restart":
        bot.answer_callback_query(c.id)
        reset(cid)
        return
    if c.data=="fb_up":
        bot.answer_callback_query(c.id)
        try: bot.edit_message_reply_markup(cid,c.message.message_id)
        except Exception: pass
        bot.send_message(cid,"Спасибо за оценку! 🙏")
        return
    if c.data=="fb_down":
        bot.answer_callback_query(c.id)
        s["stage"]="feedback"
        bot.send_message(cid,"Сожалею, что отчёт не помог. Напишите, что было не так — обратная связь будет учтена.")
        return
    if c.data in ("std","exp"):
        s["tariff"]="Стандартный" if c.data=="std" else "Экспресс"
        kb=types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("📄 Получить отчёт",callback_data="report"))
        bot.send_message(cid,f"Тариф: {s['tariff']}. (Тестовый режим: оплата отключена.) Жмите кнопку — соберу отчёт.",reply_markup=kb)
    elif c.data=="report":
        bot.send_message(cid,"Собираю отчёт…")
        note="\nНЕ ПРОВЕРЯЕТСЯ: "+", ".join(s["cannot"]) if s["cannot"] else ""
        try:
            rep=ask_qwen(s["photos"],MODE2.format(name=s["name"] or "?")+note,QWEN_MODEL)
        except Exception:
            logging.exception("mode2")
            bot.send_message(cid,"Техническая ошибка. Попробуйте ещё раз.")
            return
        for chunk in [rep[i:i+4000] for i in range(0,len(rep),4000)]:
            bot.send_message(cid,chunk)
        s["stage"]="done"
        kb=types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("👍 Полезно",callback_data="fb_up"),types.InlineKeyboardButton("👎 Не помогло",callback_data="fb_down"))
        kb.add(types.InlineKeyboardButton("🔄 Новая проверка",callback_data="restart"),types.InlineKeyboardButton("✅ Готово",callback_data="close"))
        bot.send_message(cid,"Отчёт готов. Оцените, был ли он полезен.",reply_markup=kb)

bot.infinity_polling(timeout=60)