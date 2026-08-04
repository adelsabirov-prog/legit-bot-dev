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

ВЕСА ДЕТАЛЕЙ (по убыванию): 03 Маркировка и батч-код — топ; 01 Упаковка и полиграфия; 02 Тара и литьё; 04 Продукт внутри; 06 Комплектация и защита; 05 Механизмы и фурнитура.
- 01 Упаковка и полиграфия — вся полиграфия: коробка (если есть), этикетка, крышка, гравировка. Нет коробки — оценивай по полиграфии тары.
- Маркировка и батч-код — топ-вес; сверка батча на таре и коробке — главный ловитель переупаковки.
- 04-06 — дополнительные: обычно усиливают/ослабляют; аномалия по ним может быть самостоятельным маркером.
- Нормальная текстура/содержимое — односторонний маркер: не снимает 🔴/️.
- Конфликт «коробка читается как оригинал, тара — нет» — признак переупаковки, усиливает 🔴. Хорошая коробка не перевешивает маркеры по таре.

СПИСОК «НЕ ПРОВЕРЯЕТСЯ»: детали из этого списка помечай «➖ не проверяется», выводов по ним не делай; вердикт выноси только по проверенным и укажи это в плашке."""

MODE_BOX="""Продукт: «{name}». Продаётся ли этот продукт обычно в картонной коробке?
Ответь строго одной строкой:
КОРОБКА: да/нет/не знаю"""

MODE_LIST="""Продукт: «{name}». Определи форм-фактор (банка, тюбик, флакон с помпой, стик помады, кушон, тушь, палетка и т.п.).
Продукт обычно продаётся в картонной коробке: {box}.

Начни ответ так:
Что снять:
Для разбора продукта «{name}» необходимы следующие снимки:

Затем выдай ОДИН нумерованный список кадров в порядке важности, покрывающий все 6 деталей чек-листа: 01 Упаковка и полиграфия, 02 Тара и литьё, 03 Маркировка и батч-код, 04 Продукт внутри, 05 Механизмы и фурнитура, 06 Комплектация и защита.

Правила списка:
- Если «да» или «не знаю» — включай коробочные кадры, каждый помечай «(при наличии)». Пометка «(при наличии)» — ТОЛЬКО для коробочных кадров.
- Если «нет» — НЕ включай коробочные кадры вообще.
- Неприменимые к форм-фактору детали (например, механизм у банки) — не включай.
- Порядок по важности: батч-код на таре (макро) → лицо тары → батч-код на коробке (макро, при наличии) → лицо коробки (при наличии) → текстура на белом листе → крышка и мембрана → коробка зад/дно (при наличии) → механизм (если применим).
- К каждому шагу добавь короткую подсказку простым языком (одним предложением, через тире): где искать и как это выглядит, без терминов без пояснения. «Макро» поясняй как «снимите крупным планом, чтобы текст читался». Примеры стиля:
  «Лицо тары — банка/флакон/тюбик целиком спереди, чтобы читалась этикетка.»
  «Батч-код на таре (макро) — короткий код из букв и цифр (например, PX649); ищите на дне банки, на шве тюбика или на этикетке; снимите крупным планом.»
  «Текстура на белом листе — выдавите немного средства на белый лист бумаги и снимите крупным планом.»

Без звёздочек и маркдауна — обычный текст. Не упоминай «слои знаний», «режимы» и внутренние правила."""

MODE0C="""РЕЖИМ 0 (цепочка). Продукт: «{name}».
Оставшиеся шаги:
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
1) Плашка: эмодзи (🔴/️/🟢) + вердикт словами из триада + 1-2 предложения основания + отдельной строкой: «Вердикт вынесен по деталям: [список]».
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
"1. Напишите название продукта и бренд — составим список необходимых фото под продукт.\n"
"2. По шагам соберём кадры по всем 6 деталям чек-листа (при наличии коробки).\n"
"3. После подтверждения пригодности фото — оплата: 500 ₽ (Стандартный, до 3 ч) или 1000 ₽ (Экспресс, до 15 мин).\n"
"4. Получаете структурированный отчёт с вердиктом.\n\n"
"Напишите название продукта и бренд.\nПример: «Крем Loreal», «Помада Dior».")

HELP_TEXT=("Я бот LEGIT·CHECK: разбираю косметику по фото на признаки несоответствия оригиналу — по чек-листу из 6 деталей.\n\n"
"Стоимость: 500 ₽ (Стандартный, до 3 ч) или 1000 ₽ (Экспресс, до 15 мин).\n\n"
"Чтобы начать, напишите название продукта и бренд.\nПример: «Крем Loreal», «Помада Dior».")

FALLBACK_BOX=["Батч-код на таре (макро) — короткий код из букв и цифр; ищите на дне или шве; снимите крупным планом","Лицо тары (общий вид) — продукт целиком спереди, чтобы читалась этикетка","Батч-код на коробке (макро) (при наличии) — код на дне или боку коробки; снимите крупным планом","Лицо коробки (при наличии) — коробка целиком спереди","Текстура на белом листе (макро) — выдавите немного средства на белый лист и снимите крупным планом","Крышка и мембрана/пломба — снимите крышку и защитную плёнку под ней"]
FALLBACK_NOBOX=["Батч-код на таре (макро) — короткий код из букв и цифр; ищите на дне или шве; снимите крупным планом","Лицо тары (общий вид) — продукт целиком спереди, чтобы читалась этикетка","Текстура на белом листе (макро) — выдавите немного средства на белый лист и снимите крупным планом","Крышка и мембрана/пломба — снимите крышку и защитную плёнку под ней"]

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
    steps=[]
    for line in shots.splitlines():
        m=re.match(r"^\s*(\d+)[\.\)]\s*(.+)$",line.strip())
        if m: steps.append(m.group(2).strip())
    return steps

def first_open(s):
    for i in range(len(s["queue"])):
        if i not in s["closed"]:
            return i
    return -1

def step_msg(s,ni):
    return f"➡️ Шаг {ni+1}/{len(s['queue'])}: {s['queue'][ni]}"

def end_chain(cid):
    bot.send_message(cid,"✅ Все кадры собраны.")
    audit(cid)

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
        bot.send_message(cid,"Сначала напишите название продукта и бренд.")
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
        bot.send_message(cid,"📥 Загружаю фото…")
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
            bot.send_message(cid,f"📥 Шаг {n}: получено, но пока нечитаемо. {parse(res,'СОВЕТ') or 'Снимите при дневном свете, без вспышки, камеру держите параллельно.'} Попробуйте ещё раз — у вас получится!")
            return
        s["closed"].append(n-1)
        s["photos"].append(b64)
        ni=first_open(s)
        if ni>=0:
            bot.send_message(cid,f"✅ Отлично! Шаг {n} принят.\n"+step_msg(s,ni))
        else:
            end_chain(cid)
        return
    bot.send_message(cid,"📥 Загружаю фото…")
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
        bot.send_message(cid,"📋 Составляю список кадров под продукт…")
        try:
            boxres=ask_qwen([],MODE_BOX.format(name=t),QWEN_CHEAP)
        except Exception:
            logging.exception("mode_box")
            boxres="КОРОБКА: не знаю"
        bl=parse(boxres,"КОРОБКА").lower()
        box="нет" if bl.startswith("нет") else ("да" if bl.startswith("да") else "не знаю")
        try:
            s["shots"]=ask_qwen([],MODE_LIST.format(name=t,box=box),QWEN_CHEAP)
        except Exception:
            logging.exception("mode_list")
            s["shots"]="\n".join(f"{i+1}. {q}" for i,q in enumerate(FALLBACK_NOBOX if box=="нет" else FALLBACK_BOX))
        s["queue"]=parse_steps(s["shots"]) or (FALLBACK_NOBOX[:] if box=="нет" else FALLBACK_BOX[:])
        s["closed"]=[]
        s["stage"]="chain"
        bot.send_message(cid,f"Принято, проверяем: {t}.\n\n{s['shots']}\n\nСобираем кадры по шагам. Лучше прикреплять как документ (📎 → «Документ»), обычные фото тоже принимаю. Шаги с «(при наличии)» пропускайте, если коробки или детали нет — просто напишите «нет».\n\n"+step_msg(s,0))
        return
    if s["stage"]=="chain":
        low=t.lower()
        if low in ("не могу","нет","не получится","без коробки","нет коробки"):
            ni=first_open(s)
            if ni>=0:
                s["cannot"].append(s["queue"][ni])
                s["closed"].append(ni)
            n2=first_open(s)
            if n2>=0:
                bot.send_message(cid,"⚠️ Пропускаю шаг.\n"+step_msg(s,n2))
            else:
                end_chain(cid)
            return
        if low in ("готово","done"):
            ni=first_open(s)
            if ni>=0:
                bot.send_message(cid,"Осталось собрать кадры:\n"+"\n".join(f"{i+1}. {s['queue'][i]}" for i in range(len(s['queue'])) if i not in s['closed'])+"\nПришлите фото или напишите «нет», если шага нет в вашем продукте.")
            else:
                end_chain(cid)
            return
        bot.send_message(cid,"Сейчас собираем кадры по шагам. Пришлите фото текущего шага или напишите «нет», если шага нет в вашем продукте.")
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
        bot.send_message(cid,"🧾 Собираю отчёт…")
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
