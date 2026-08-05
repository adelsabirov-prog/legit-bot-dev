import os, base64, logging, io, time, re
import telebot
from telebot import types
import requests
from PIL import Image
from dotenv import load_dotenv

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except Exception:
    pass

load_dotenv()
TOKEN=os.getenv("BOT_TOKEN")
QWEN_KEY=os.getenv("QWEN_API_KEY")
QWEN_MODEL=os.getenv("QWEN_MODEL","qwen/qwen2.5-vl-72b-instruct")
QWEN_CHEAP=os.getenv("QWEN_MODEL_CHEAP","qwen/qwen2.5-vl-7b-instruct")
BASE=os.getenv("DASHSCOPE_BASE_URL","https://openrouter.ai/api/v1")
OFERTA="https://legitcheck-cosmetics.netlify.app/oferta.html"
PRIVACY=OFERTA+"#privacy"

bot=telebot.TeleBot(TOKEN,threaded=True)
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

MODE_BOX="""Продукт: «{name}». Если название похоже на опечатку — попробуй понять, что имелось в виду.
Ответь СТРОГО двумя строками:
ФОРМ-ФАКТОР: [одно из: банка, тюбик, флакон с помпой, стик помады, кушон, тушь, палетка, другое]
КОРОБКА: да/нет/не знаю (продаётся ли этот продукт обычно в картонной коробке)"""

MODE_LIST="""Продукт: «{name}». Форм-фактор продукта: {ff}. Продукт обычно продаётся в картонной коробке: {box}.

Начни ответ так:
Что снять:
Для разбора продукта «{name}» необходимы следующие снимки:

Затем выдай ОДИН нумерованный список КОРОТКИХ названий шагов в порядке важности, покрывающий все 6 деталей чек-листа: 01 Упаковка и полиграфия, 02 Тара и литьё, 03 Маркировка и батч-код, 04 Продукт внутри, 05 Механизмы и фурнитура, 06 Комплектация и защита.

Правила списка:
- Названия шагов — короткие, без пояснений и БЕЗ слова «макро». НЕ используй названия деталей чек-листа как названия шагов — используй названия кадров. Примеры: «Батч-код на таре», «Лицо тары», «Батч-код на коробке (при наличии)», «Лицо коробки (при наличии)», «Продукт внутри», «Крышка и мембрана», «Коробка зад/дно (при наличии)», «Механизм в действии». Без повторов одного и того же шага.
- Если «да» или «не знаю» — включай коробочные шаги, каждый помечай «(при наличии)». Пометка «(при наличии)» — ТОЛЬКО для коробочных шагов.
- Если «нет» — НЕ включай коробочные шаги вообще.
- Неприменимые к форм-фактору детали (например, механизм у банки) — не включай.
- Порядок по важности: батч-код на таре → лицо тары → батч-код на коробке (при наличии) → лицо коробки (при наличии) → продукт внутри → крышка и мембрана → коробка зад/дно (при наличии) → механизм (если применим).

Без звёздочек и маркдауна — обычный текст. Не упоминай «слои знаний», «режимы» и внутренние правила."""

MODE0C="""РЕЖИМ 0 (цепочка). Продукт: «{name}».
Текущий шаг: {current}
Оставшиеся шаги:
{remaining}
На фото косметика или уход? Если явно другой предмет — строго одной строкой:
ТИП: не косметика
Иначе определи, какому шагу соответствует фото. ВНИМАНИЕ: клиент скорее всего снимает текущий шаг — сначала сравни фото с описанием текущего шага, и только потом ищи среди остальных.
Ответь СТРОГО в формате:
ШАГ: [номер из списка; 0, если не подходит ни к одному]
ЧИТАЕМО: да/нет
СОВЕТ: [если нечитаемо — одним предложением как переснять]
Если изображение размыто или текст не различим отчётливо — это «нечитаемо». Не угадывай текст."""

MODE0C2="""РЕЖИМ 0 (контрольный вопрос). Продукт: «{name}».
Текущий шаг: {step}.
Каким должен быть кадр: {hint}
Сравни фото с этим описанием. Соответствует ли фото описанию? Читаемо ли оно?
Ответь СТРОГО в формате:
СОВПАДЕНИЕ: да/нет
ЧИТАЕМО: да/нет
СОВЕТ: [если нечитаемо — одним предложением как переснять]"""

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
НАЗВАНИЯ ДЕТАЛЕЙ в отчёте пиши ТОЛЬКО точно так, без изменений формулировок:
01 Упаковка и полиграфия
02 Тара и литьё
03 Маркировка и батч-код
04 Продукт внутри
05 Механизмы и фурнитура
06 Комплектация и защита
В плашке строкой «Вердикт вынесен по деталям:» перечисли ВСЕ детали, по которым вынесен вывод (все со статусами ✅/⚠️/), а не часть.
БАТЧ И ГОД: если уверена в формате батча конкретного бренда — проверь согласованность года выпуска с дизайном упаковки, строкой дистрибьютора и линейкой; несоответствие — маркер (учитывается в детали 03). Если не уверена — не выводи дату и не делай из неё маркер.
Формат — обычный текст, БЕЗ звёздочек и маркдауна:
1) Плашка: эмодзи (🔴/️/🟢) + вердикт словами из триады + 1-2 предложения основания + отдельной строкой: «Вердикт вынесен по деталям: [список]».
2) Шесть деталей, по каждой строка статуса строго из набора (✅ проверено / ⚠️ сомнение / ❌ маркер / ➖ не проверяется; знак для непроверяемых — именно ➖, не тире) и 1-2 предложения обоснования.
3) Строка: «Состав и безопасность самого содержимого по фото не верифицируются.»
4) Строка: «Результат — оценочное мнение по видимым признакам; не является экспертизой или юридическим заключением.»"""

START_TEXT=("👋 Legit Check Cosmetics — проверка признаков подлинности косметики по фото.\n\n"
"Как это работает:\n"
"1. Напишите название продукта и бренд — составим список необходимых кадров под ваш продукт.\n"
"2. По шагам соберём фотографии для проверки по всем 6 деталям чек-листа.\n"
"3. После подтверждения пригодности фото — оплата: 500 ₽ (Стандартный, проверка до 3 ч) или 1000 ₽ (Экспресс, проверка до 15 минут)\n"
"4. Получаете структурированный отчёт с итоговым вердиктом.\n\n"
"Напишите название продукта и бренд.\nПример: «Крем Loreal», «Помада Dior»")

HELP_TEXT=("Я бот LEGIT·CHECK: разбираю косметику по фото на признаки несоответствия оригиналу — по чек-листу из 6 деталей.\n\n"
"Стоимость: 500 ₽ (Стандартный, до 3 ч) или 1000 ₽ (Экспресс, до 15 мин).\n\n"
"Чтобы начать, напишите название продукта и бренд.\nПример: «Крем Loreal», «Помада Dior».")

SKILLS_TEXT=("🔍 Что определяет бот:\n\n"
"01 Упаковка и полиграфия\n"
"— размытая печать, «плывущие» шрифты, несовпадение оттенков\n"
"— отсутствие тиснения или фольги там, где они у оригинала\n\n"
"02 Тара и литьё\n"
"— кривые швы, облой, грубый пластик\n"
"— неплотная посадка крышки\n\n"
"03 Маркировка и батч-код\n"
"— стёртый или криво нанесённый батч-код\n"
"— несовпадение кода на таре и коробке (переупаковка)\n\n"
"04 Продукт внутри\n"
"— аномальная текстура, цвет, консистенция\n\n"
"05 Механизмы и фурнитура\n"
"— тугой ход помпы, люфт стика\n\n"
"06 Комплектация и защита\n"
"— отсутствие защитной мембраны или пломбы\n\n"
"Вердикт выносится по проверенным деталям.\nНепроверенные детали помечаются — «не проверяется».")

FALLBACK_BOX=["Батч-код на таре","Лицо тары","Батч-код на коробке (при наличии)","Лицо коробки (при наличии)","Продукт внутри","Крышка и мембрана/пломба","Коробка зад/дно (при наличии)"]
FALLBACK_NOBOX=["Батч-код на таре","Лицо тары","Продукт внутри","Крышка и мембрана/пломба"]

NOBOX_KEYWORDS=["himalay"]

def norm_ff(s):
    s=(s or "").lower()
    if "банк" in s: return "bank"
    if "тюб" in s: return "tube"
    if "помп" in s or "флакон" in s: return "bottle"
    if "стик" in s or "помад" in s: return "stick"
    if "кушон" in s: return "cushion"
    if "туш" in s: return "mascara"
    if "палет" in s: return "palette"
    return "default"

FF_LABEL={"bank":"банка","tube":"тюбик","bottle":"флакон","stick":"стик","cushion":"кушон","mascara":"тушь","palette":"палетка","default":"тара"}

def hint_for(step,ff):
    s=step.lower()
    if "батч" in s and "короб" in s:
        return "Код на дне или боку коробки. Снимите крупным планом, чтобы текст читался."
    if "батч" in s:
        return {
        "bank":"Код на дне банки. Переверните банку и снимите дно крупным планом, чтобы текст читался.",
        "tube":"Код на плоском шве в конце тюбика. Снимите этот шов крупным планом, чтобы текст читался.",
        "bottle":"Код на дне флакона или в нижней части этикетки. Снимите крупным планом, чтобы текст читался.",
        "stick":"Код на дне тубы или на боку стика. Снимите крупным планом, чтобы текст читался.",
        "mascara":"Код на дне тубы или на этикетке у основания колпачка. Снимите крупным планом, чтобы текст читался.",
        "cushion":"Код на дне упаковки кушона. Переверните и снимите дно крупным планом, чтобы текст читался.",
        "palette":"Код на дне или боку палетки. Снимите крупным планом, чтобы текст читался."}.get(ff,"Код на дне упаковки или в нижней части этикетки. Снимите крупным планом, чтобы текст читался.")
    if "текстура" in s or "продукт" in s:
        return "Подойдёт один из двух вариантов: снимите сам продукт в открытой упаковке ИЛИ выдавите немного на чистый белый лист и снимите крупным планом."
    if "крышк" in s or "мембран" in s or "пломб" in s:
        return "Снимите крышку и защитную плёнку или мембрану под ней (если есть)."
    if "короб" in s and ("зад" in s or "дно" in s):
        return "Задняя сторона коробки с составом и дно. Снимите так, чтобы текст читался."
    if "короб" in s:
        return "Коробка целиком спереди, чтобы были видны все надписи."
    if "механизм" in s or "помп" in s or "дозатор" in s:
        return "Покажите механизм в действии: нажмите помпу или выкрутите стик."
    if "тар" in s or "лицо" in s or "упаковк" in s or "полиграф" in s:
        return {
        "bank":"Поставьте банку на ровную поверхность этикеткой к камере. Снимите спереди, чтобы читались название и весь текст. Не держите в руке.",
        "tube":"Положите тюбик на ровную поверхность лицевой стороной вверх. Снимите, чтобы читался весь текст на этикетке.",
        "bottle":"Поставьте флакон на ровную поверхность этикеткой к камере. Снимите спереди, чтобы читался весь текст.",
        "stick":"Если колпачок закрывает этикетку — снимите его. Снимите корпус спереди, чтобы читалась этикетка."}.get(ff,"Поставьте продукт на ровную поверхность этикеткой к камере. Снимите спереди, чтобы читался весь текст. Не держите в руке.")
    return ""

def ask_qwen(images,user_text,model,timeout=120,attempts=2):
    content=[{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b}"}} for b in images]
    content.append({"type":"text","text":user_text})
    r=None
    for attempt in range(attempts):
        try:
            r=requests.post(BASE+"/chat/completions",
                headers={"Authorization":"Bearer "+QWEN_KEY,"Content-Type":"application/json"},
                json={"model":model,"messages":[{"role":"system","content":SYSTEM},{"role":"user","content":content}]},
                timeout=timeout)
        except requests.exceptions.RequestException as e:
            logging.error("QWEN NET %s",e)
            if attempt<attempts-1:
                time.sleep(2)
                continue
            raise
        if r.status_code in (429,500,502,503):
            logging.error("QWEN RETRY %s %s",r.status_code,r.text[:500])
            if attempt<attempts-1:
                time.sleep(3)
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
    return S.setdefault(cid,{"name":"","photos":[],"shots":"","queue":[],"closed":[],"cannot":[],"last_missing":[],"stage":"name","source":"","tariff":"","comp_warned":False,"ff":"default","pending":-1,"pending_b64":"","retakes":0,"chain_complete":False})

def kb_main():
    kb=types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔍 Что умеет бот",callback_data="skills"))
    kb.add(types.InlineKeyboardButton("📄 Оферта",url=OFERTA),types.InlineKeyboardButton("🔒 Политика конфиденциальности",url=PRIVACY))
    return kb

def reset(cid):
    S[cid]={"name":"","photos":[],"shots":"","queue":[],"closed":[],"cannot":[],"last_missing":[],"stage":"name","source":"","tariff":"","comp_warned":False,"ff":"default","pending":-1,"pending_b64":"","retakes":0,"chain_complete":False}
    bot.send_message(cid,START_TEXT,reply_markup=kb_main())

def parse(res,key):
    for line in res.splitlines():
        if line.upper().startswith(key):
            return line.split(":",1)[1].strip()
    return ""

def clean_missing(s):
    bad=("нет","none","-","—","")
    return [x.strip() for x in s.split(",") if x.strip().lower() not in bad]

def dedup_shots(shots):
    head=[]; steps=[]; seen=set()
    for l in shots.splitlines():
        m=re.match(r"^\s*(\d+)[\.\)]\s*(.+)$",l.strip())
        if m:
            name=m.group(2).strip()
            key=name.lower()
            if key not in seen:
                seen.add(key); steps.append(name)
        elif not steps:
            head.append(l)
    return "\n".join(head+[f"{i+1}. {q}" for i,q in enumerate(steps)]), steps

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
    h=hint_for(s["queue"][ni],s.get("ff","default"))
    return f"➡️ Шаг {ni+1}/{len(s['queue'])}: {s['queue'][ni]}" + (f"\n{h}" if h else "")

def retake_extra(s):
    s["retakes"]=s.get("retakes",0)+1
    return "\nЕсли не получается — напишите «нет», пропустим этот шаг и пойдём дальше." if s["retakes"]>=2 else ""

def accept_step(cid,s,n,b64):
    s["closed"].append(n-1)
    s["photos"].append(b64)
    s["pending"]=-1; s["pending_b64"]=""
    s["retakes"]=0
    ni=first_open(s)
    if ni>=0:
        bot.send_message(cid,f"✅ Отлично! Шаг {n} принят.\n"+step_msg(s,ni))
    else:
        end_chain(cid)

def end_chain(cid):
    s=st(cid)
    s["chain_complete"]=True
    bot.send_message(cid,"✅ Все кадры собраны.")
    audit(cid)

def send_tariffs(cid):
    s=st(cid)
    s["stage"]="tariffs"
    warn=""
    if s["cannot"]:
        warn="\n\nОбратите внимание: "+", ".join(s["cannot"])+" — не будет проверяться. Вердикт будет вынесен по остальным деталям."
    kb=types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("Стандартный — 500 ₽ · до 3 часов",callback_data="std"))
    kb.add(types.InlineKeyboardButton("Экспресс — 1000 ₽ · до 15 минут",callback_data="exp"))
    bot.send_message(cid,f"Фото подходят для проверки.{warn}\n\nВыберите тариф:\n\nОплачивая, вы принимаете условия оферты: {OFERTA}",reply_markup=kb)

@bot.message_handler(commands=["start"])
def start(m):
    parts=m.text.split()
    S[m.chat.id]={"name":"","photos":[],"shots":"","queue":[],"closed":[],"cannot":[],"last_missing":[],"stage":"name","source":parts[1] if len(parts)>1 else "","tariff":"","comp_warned":False,"ff":"default","pending":-1,"pending_b64":"","retakes":0,"chain_complete":False}
    bot.send_message(m.chat.id,START_TEXT,reply_markup=kb_main())

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
    try:
        b64,comp=img_b64(m)
    except Exception:
        logging.exception("img_b64")
        bot.send_message(cid,"Не смог прочитать файл. Пришлите фото в JPG/PNG или отправьте как обычное фото.")
        return
    if comp and not s["comp_warned"]:
        s["comp_warned"]=True
        bot.send_message(cid,"⚠️ Фото пришло сжатым (как обычное фото). Мелкие детали — батч, полиграфия — могли потеряться. Для максимальной точности прикрепляйте как документ: скрепка 📎 → «Файл» или «Документ». Продолжаю разбор с тем, что есть.")
    if s["stage"]=="chain":
        s["pending"]=-1; s["pending_b64"]=""
        bot.send_message(cid,"📥 Загружаю фото…")
        cur=first_open(s)
        cur_hint=hint_for(s["queue"][cur],s.get("ff","default")) if cur>=0 else ""
        remaining="\n".join(f"{i+1}. {s['queue'][i]}" for i in range(len(s["queue"])) if i not in s["closed"])
        try:
            res=ask_qwen([b64],MODE0C.format(name=s["name"] or "?",current=f"{cur+1}. {s['queue'][cur]}. Каким должен быть кадр: {cur_hint}" if cur>=0 else "нет",remaining=remaining),QWEN_CHEAP,timeout=60,attempts=1)
        except Exception:
            logging.exception("mode0c")
            bot.send_message(cid,"Техническая ошибка. Попробуйте ещё раз.")
            return
        if "не косметика" in res.lower():
            bot.send_message(cid,"📥 Получено, но это не косметика или уход — я проверяю только их. Пришлите фото нужного продукта или напишите «Начать заново».")
            return
        num="".join(ch for ch in parse(res,"ШАГ") if ch.isdigit())
        n=int(num) if num else 0
        readable=parse(res,"ЧИТАЕМО").lower().startswith("да")
        if n==0 and cur>=0:
            try:
                res2=ask_qwen([b64],MODE0C2.format(name=s["name"] or "?",step=s["queue"][cur],hint=cur_hint),QWEN_CHEAP,timeout=45,attempts=1)
            except Exception:
                logging.exception("mode0c2")
                res2=""
            if res2 and parse(res2,"СОВПАДЕНИЕ").lower().startswith("да"):
                n=cur+1
                readable=parse(res2,"ЧИТАЕМО").lower().startswith("да")
                if not readable:
                    bot.send_message(cid,f"📥 Шаг {n}: получено, но пока нечитаемо. {parse(res2,'СОВЕТ') or 'Снимите при дневном свете, без вспышки.'} Попробуйте ещё раз — у вас получится!{retake_extra(s)}")
                    return
            elif res2 and parse(res2,"СОВПАДЕНИЕ").lower().startswith("нет") and not parse(res2,"ЧИТАЕМО").lower().startswith("да"):
                bot.send_message(cid,f"📥 Получено, но пока нечитаемо. {parse(res2,'СОВЕТ') or 'Снимите при дневном свете, без вспышки.'} Попробуйте ещё раз — у вас получится!{retake_extra(s)}")
                return
            else:
                s["pending"]=cur; s["pending_b64"]=b64
                bot.send_message(cid,f"📥 Фото получено. Это кадр для шага «{s['queue'][cur]}»? Напишите «да» — приму его, или просто пришлите новый кадр по подсказке:\n{cur_hint}")
                return
        if n<1 or n>len(s["queue"]) or (n-1) in s["closed"]:
            bot.send_message(cid,"Этот кадр не подходит ни к одному из оставшихся шагов. Осталось:\n"+remaining)
            return
        if not readable:
            bot.send_message(cid,f"📥 Шаг {n}: получено, но пока нечитаемо. {parse(res,'СОВЕТ') or 'Снимите при дневном свете, без вспышки, камеру держите параллельно.'} Попробуйте ещё раз — у вас получится!{retake_extra(s)}")
            return
        accept_step(cid,s,n,b64)
        return
    bot.send_message(cid,"📥 Загружаю фото…")
    try:
        res=ask_qwen([b64],MODE0I.format(name=s["name"] or "?"),QWEN_CHEAP,timeout=60,attempts=1)
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
            boxres=ask_qwen([],MODE_BOX.format(name=t),QWEN_CHEAP,timeout=45,attempts=1)
        except Exception:
            logging.exception("mode_box")
            boxres="ФОРМ-ФАКТОР: другое\nКОРОБКА: не знаю"
        s["ff"]=norm_ff(parse(boxres,"ФОРМ-ФАКТОР"))
        bl=parse(boxres,"КОРОБКА").lower()
        box="нет" if bl.startswith("нет") else ("да" if bl.startswith("да") else "не знаю")
        if any(k in t.lower() for k in NOBOX_KEYWORDS):
            box="нет"
        try:
            s["shots"]=ask_qwen([],MODE_LIST.format(name=t,ff=FF_LABEL[s["ff"]],box=box),QWEN_CHEAP,timeout=60,attempts=1)
        except Exception:
            logging.exception("mode_list")
            s["shots"]="\n".join(f"{i+1}. {q}" for i,q in enumerate(FALLBACK_NOBOX if box=="нет" else FALLBACK_BOX))
        if box=="нет":
            lines=[l for l in s["shots"].splitlines() if "короб" not in l.lower()]
            out=[]; n=0
            for l in lines:
                m=re.match(r"^\s*(\d+)[\.\)]\s*(.+)$",l.strip())
                if m:
                    n+=1; out.append(f"{n}. {m.group(2).strip()}")
                else:
                    out.append(l)
            s["shots"]="\n".join(out)
        s["shots"]="\n".join(l if "короб" in l.lower() else l.replace("(при наличии)","").strip() for l in s["shots"].splitlines())
        s["shots"],steps=dedup_shots(s["shots"])
        s["queue"]=steps or (FALLBACK_NOBOX[:] if box=="нет" else FALLBACK_BOX[:])
        s["closed"]=[]
        s["stage"]="chain"
        bot.send_message(cid,f"Принято: {t}.\n\n{s['shots']}\n\nСобираем кадры по шагам — буду подсказывать каждый и скажу, если нужно переснять. Лучше прикреплять как документ (скрепка 📎 → «Документ»): Telegram сжимает обычные фото, и мелкие детали теряются. Шаги с «(при наличии)» пропускайте, если коробки или детали нет — просто напишите «нет». Если в названии опечатка — напишите «Начать заново» и введите название заново.\n\n"+step_msg(s,0))
        return
    if s["stage"]=="chain":
        low=t.lower()
        if s.get("pending",-1)>=0:
            if low in ("да","yes","ага","да, это"):
                ni=s["pending"]; b64=s["pending_b64"]
                accept_step(cid,s,ni+1,b64)
            else:
                s["pending"]=-1; s["pending_b64"]=""
                ni=first_open(s)
                if ni>=0:
                    bot.send_message(cid,"Хорошо, жду новый кадр.\n"+step_msg(s,ni))
            return
        if low in ("не могу","нет","не получится","без коробки","нет коробки"):
            s["retakes"]=0
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
            send_tariffs(cid)
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
        res=ask_qwen(s["photos"],MODE0F.format(name=s["name"] or "?",cannot=", ".join(s["cannot"]) or "нет"),QWEN_CHEAP,timeout=90,attempts=2)
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
    if s.get("chain_complete"):
        send_tariffs(cid)
        return
    missing=clean_missing(parse(res,"MISSING"))
    if missing:
        s["stage"]="photos"; s["last_missing"]=missing
        bot.send_message(cid,"Не хватает деталей: "+", ".join(missing)+".\nДобавьте фото или напишите «не могу» — продолжим разбор как есть, эти детали будут помечены «не проверяется».")
    else:
        send_tariffs(cid)

@bot.callback_query_handler(func=lambda c: c.data in ("std","exp","report","restart","close","fb_up","fb_down","skills"))
def cb(c):
    cid=c.message.chat.id; s=st(cid)
    if c.data=="skills":
        bot.answer_callback_query(c.id)
        bot.send_message(cid,SKILLS_TEXT)
        return
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
            rep=ask_qwen(s["photos"],MODE2.format(name=s["name"] or "?")+note,QWEN_MODEL,timeout=150,attempts=2)
        except Exception:
            logging.exception("mode2")
            bot.send_message(cid,"Техническая ошибка. Попробуйте ещё раз.")
            return
        rep=rep.replace("— не проверяется","➖ не проверяется").replace("- не проверяется","➖ не проверяется")
        for chunk in [rep[i:i+4000] for i in range(0,len(rep),4000)]:
            bot.send_message(cid,chunk)
        s["stage"]="done"
        kb=types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("👍 Полезно",callback_data="fb_up"),types.InlineKeyboardButton("👎 Не помогло",callback_data="fb_down"))
        kb.add(types.InlineKeyboardButton("🔄 Новая проверка",callback_data="restart"),types.InlineKeyboardButton("✅ Готово",callback_data="close"))
        bot.send_message(cid,"Отчёт готов. Оцените, был ли он полезен.",reply_markup=kb)

bot.infinity_polling(timeout=60)