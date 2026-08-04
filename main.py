import os, base64, logging, io
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
- Запрещены слова «ИИ», «нейросеть», «модель», «узлы», «алгоритм». Используй «детали», «чек-лист», «разбор», «бот».
- Никаких процентов и числовой уверенности. Вердикт — только словами.
- Никаких «100% гарантия», «официальный чек-лист», категоричных «контрафакт/фейк». Используй «признаки подделки», «не подтверждён как оригинал».
- Не выдумывай: деталь не видна или знаний недостаточно — честно «➖ не проверяется».

СЛОИ ЗНАНИЙ (по приоритету):
ур.1 — специфические признаки конкретного продукта (название, линейка, форм-фактор): тексты этикетки, индексы, регулятор, формат батча, дизайн упаковки. Применяй, только если уверена в особенностях оригинала.
ур.2 — общие признаки подлинности форм-фактора: качество полиграфии, тиснение, швы и облой литья, посадка крышки и ход механизмов, способ нанесения и шрифт гравировки, согласованность маркировки с упаковкой.
ур.3 — не знаешь продукт или знание может устареть — не проверяй специфические признаки, честно пиши об этом и оценивай только ур.2.

ОСИ НАДЁЖНОСТИ ЧТЕНИЯ: «подтверждено по макро» — сильный; «видно на общем плане» — средний; «косвенно» — слабый, в красный вердикт не считается.

ВЕРДИКТЫ (только словами):
🔴 «Выявлены признаки подделки» — только при 2+ независимых маркерах, подтверждённых по макро или общему плану.
⚠️ «Есть сомнение в подлинности» — 1 надёжный маркер или несколько слабых.
🟢 «Признаков несоответствия не выявлено» — маркеры не найдены по проверенным деталям; обязательно укажи, по каким деталям вынесен вердикт.

ВЕСА И ЛОГИКА:
- Критические детали: 01 Упаковка и полиграфия, 02 Тара и литьё, 03 Маркировка и батч-код — ядро вердикта.
- Маркировка и батч-код — топ-вес; сверка батча на таре и коробке — главный ловитель переупаковки.
- 04-06 (продукт, механизмы, комплектация) — дополнительные: обычно усиливают/ослабляют; аномалия по ним может быть самостоятельным маркером.
- Нормальная текстура/содержимое — односторонний маркер: не снимает 🔴/⚠️.
- Конфликт «коробка читается как оригинал, тара — нет» — признак переупаковки, усиливает 🔴. Хорошая коробка не перевешивает маркеры по таре.

СПИСОК «НЕ ПРОВЕРЯЕТСЯ»: детали из этого списка помечай «➖ не проверяется», выводов по ним не делай; вердикт выноси только по проверенным и укажи это в плашке."""

MODE_LIST="""Продукт: «{name}». Определи форм-фактор (банка, тюбик, флакон с помпой, стик помады, кушон, тушь, палетка и т.п.) и выдай два блока простым клиентским языком:

ОБЯЗАТЕЛЬНО (ядро проверки):
[нумерованные 4-5 кадров под форм-фактор: тара лицо, коробка лицо, батч-код на таре макро, батч-код на коробке макро]

ДОБАВЬТЕ, ЧТОБЫ РАЗБОР ШЁЛ ПО ВСЕМ 6 ДЕТАЛЯМ ЧЕК-ЛИСТА:
[2-3 вторичных ракурса под форм-фактор: текстура на белом листе, крышка и мембрана, коробка зад и дно, механизм, комплектация]

В конце одной строкой: «Можно прислать несколько фото одним сообщением.»
Без других вступлений."""

MODE0I="""РЕЖИМ 0 (инкрементальный). Продукт: «{name}». Нужные ракурсы: {shots}.
Посмотри на фото и ответь СТРОГО в формате:
ДЕТАЛЬ: [какая деталь из списка на фото; «не понял», если не ясно]
ЧИТАЕМО: да/нет
СОВЕТ: [если нет — коротко как переснять: свет сбоку, без вспышки, камера параллельно]"""

MODE0F="""РЕЖИМ 0 (финальный). Продукт: «{name}». Клиент не может предоставить: {cannot}.
Посмотри все фото и ответь СТРОГО в формате:
ДОСТАТОЧНО: да/нет
(«нет» — только если хотя бы одна критическая деталь нечитаема или отсутствует: 01 Упаковка и полиграфия, 02 Тара и литьё, 03 Маркировка и батч-код)
MISSING: [через запятую детали из 6 пунктов чек-листа, по которым нет читаемых фото, КРОМЕ тех, что клиент не может предоставить; «нет», если все 6 покрыты]"""

MODE2="""РЕЖИМ 2. Дай финальный клиентский отчёт по продукту «{name}». Детали из списка «НЕ ПРОВЕРЯЕТСЯ» и детали без читаемых фото помечай «➖ не проверяется» без выводов по ним.
БАТЧ И ГОД: если уверена в формате батча конкретного бренда — проверь согласованность года выпуска с дизайном упаковки, строкой дистрибьютора и линейкой; несоответствие — маркер (учитывается в детали 03). Если не уверена — не выводи дату и не делай из неё маркер.
Формат:
1) Плашка: эмодзи (🔴/⚠️/🟢) + вердикт словами + 1-2 предложения основания + по каким деталям вынесен вердикт.
2) Шесть деталей, по каждой статус и 1-3 предложения обоснования:
01 Упаковка и полиграфия
02 Тара и литьё
03 Маркировка и батч-код
04 Продукт внутри
05 Механизмы и фурнитура
06 Комплектация и защита
3) Строка: «Не 100% гарантия — но снижение риска: проверка по детальному чек-листу. Состав и безопасность самого содержимого по фото не верифицируются.»
4) Строка: «Результат — оценочное мнение по видимым признакам; не является экспертизой или юридическим заключением.»"""

START_TEXT=("👋 Legit Check Cosmetics — проверка признаков подлинности косметики по фото.\n\n"
"Как это работает:\n"
"1. Напишите бренд и название продукта, пришлите фото — подскажу, какие ракурсы нужны.\n"
"2. После подтверждения пригодности фото — оплата: 500 ₽ (Стандартный, до 3 ч) или 1000 ₽ (Экспресс, до 15 мин).\n"
"3. Получаете структурированный отчёт с вердиктом.\n\n"
"Напишите бренд и название продукта.\nПример: «Крем Loreal», «Помада Dior».")

def ask_qwen(images,user_text,model):
    content=[{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b}"}} for b in images]
    content.append({"type":"text","text":user_text})
    r=requests.post(BASE+"/chat/completions",
        headers={"Authorization":"Bearer "+QWEN_KEY,"Content-Type":"application/json"},
        json={"model":model,"messages":[{"role":"system","content":SYSTEM},{"role":"user","content":content}]},
        timeout=180)
    if r.status_code!=200:
        logging.error("QWEN ERROR %s %s",r.status_code,r.text[:1500])
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

def downscale_b64(raw):
    im=Image.open(io.BytesIO(raw)).convert("RGB")
    w,h=im.size; m=max(w,h)
    if m>1600:
        k=1600/m; im=im.resize((int(w*k),int(h*k)),Image.LANCZOS)
    buf=io.BytesIO(); im.save(buf,"JPEG",quality=85)
    return base64.b64encode(buf.getvalue()).decode()

def img_b64(m):
    fid=m.photo[-1].file_id if m.content_type=="photo" else m.document.file_id
    fp=bot.get_file(fid).file_path
    r=requests.get(f"https://api.telegram.org/file/bot{TOKEN}/{fp}",timeout=60)
    return downscale_b64(r.content)

def st(cid):
    return S.setdefault(cid,{"name":"","photos":[],"shots":"","cannot":[],"last_missing":[],"stage":"name","source":"","tariff":""})

def parse(res,key):
    for line in res.splitlines():
        if line.upper().startswith(key):
            return line.split(":",1)[1].strip()
    return ""

def clean_missing(s):
    bad=("нет","none","-","—","")
    return [x.strip() for x in s.split(",") if x.strip().lower() not in bad]

@bot.message_handler(commands=["start"])
def start(m):
    parts=m.text.split()
    S[m.chat.id]={"name":"","photos":[],"shots":"","cannot":[],"last_missing":[],"stage":"name","source":parts[1] if len(parts)>1 else "","tariff":""}
    kb=types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("📄 Оферта",url=OFERTA),types.InlineKeyboardButton("🔒 Политика конфиденциальности",url=PRIVACY))
    bot.send_message(m.chat.id,START_TEXT,reply_markup=kb)

@bot.message_handler(content_types=["photo"])
def photo(m): add_image(m)

@bot.message_handler(content_types=["document"],func=lambda m: m.document and (m.document.mime_type or "").startswith("image"))
def doc(m): add_image(m)

def add_image(m):
    cid=m.chat.id; s=st(cid)
    if s["stage"] not in ("photos","retake"):
        bot.send_message(cid,"Сначала напишите бренд и название продукта.")
        return
    s["photos"].append(img_b64(m))
    try:
        res=ask_qwen([s["photos"][-1]],MODE0I.format(name=s["name"] or "?",shots=s["shots"] or "стандартный список"),QWEN_CHEAP)
    except Exception:
        logging.exception("mode0i")
        bot.send_message(cid,"Техническая ошибка. Попробуйте ещё раз.")
        return
    det=parse(res,"ДЕТАЛЬ") or "фото"
    if parse(res,"ЧИТАЕМО").lower().startswith("да"):
        bot.send_message(cid,f"📥 Получено: {det} ({len(s['photos'])}). Читаемо.")
    else:
        bot.send_message(cid,f"📥 Получено: {det}, но нечитаемо. {parse(res,'СОВЕТ') or 'Переснимите при дневном свете, без вспышки.'}\nПереснимите или напишите «не могу».")

@bot.message_handler(func=lambda m: m.content_type=="text" and not m.text.startswith("/"))
def text(m):
    cid=m.chat.id; s=st(cid); t=m.text.strip()
    if s["stage"]=="name":
        s["name"]=t; s["stage"]="photos"
        try:
            s["shots"]=ask_qwen([],MODE_LIST.format(name=t),QWEN_CHEAP)
        except Exception:
            logging.exception("mode_list")
            s["shots"]=("1. Тара — лицо.\n2. Коробка — лицо.\n3. Батч-код на таре (макро).\n4. Батч-код на коробке (макро).\n"
                        "5. Текстура на белом листе (макро).\n6. Крышка и мембрана/пломба.")
        bot.send_message(cid,f"Принято, проверяем: {t}.\n\nПрикрепляйте фото как документ: скрепка 📎 → «Файл» или «Документ» → выберите фото в галерее. Не отправляйте как обычное фото: Telegram сжимает снимки, мелкие детали теряются.\n\nЧто снять:\n{s['shots']}\n\nПрисылайте по одному или архивом. Когда закончите — напишите «Готово».")
    elif s["stage"] in ("photos","retake"):
        if t.lower() in ("готово","done"):
            audit(cid)
        elif t.lower() in ("не могу","нет","не получится"):
            s["cannot"]+= [x for x in (s["last_missing"] or []) if x not in s["cannot"]]
            s["last_missing"]=[]
            audit(cid)
        else:
            bot.send_message(cid,"Записал. Добавляйте фото или напишите «Готово».")

def audit(cid):
    s=st(cid)
    if not s["photos"]:
        bot.send_message(cid,"Фото не получены — проверка не может быть оказана, оплата не запрашивается.")
        return
    try:
        res=ask_qwen(s["photos"],MODE0F.format(name=s["name"] or "?",cannot=", ".join(s["cannot"]) or "нет"),QWEN_CHEAP)
    except Exception:
        logging.exception("mode0f")
        bot.send_message(cid,"Техническая ошибка. Попробуйте ещё раз.")
        return
    if not parse(res,"ДОСТАТОЧНО").lower().startswith("да"):
        bot.send_message(cid,"По имеющимся фото вердикт вынести невозможно: не хватает критических деталей (упаковка, тара или маркировка). Услуга не оказывается, оплата не запрашивается. Добавьте читаемые фото или начните заново командой /start.")
        return
    missing=clean_missing(parse(res,"MISSING"))
    if missing:
        s["stage"]="retake"; s["last_missing"]=missing
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

@bot.callback_query_handler(func=lambda c: c.data in ("std","exp","report"))
def cb(c):
    cid=c.message.chat.id; s=st(cid)
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

bot.infinity_polling(timeout=60)