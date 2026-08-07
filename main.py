import os, base64, logging, io, time, re, threading
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
QWEN_CHEAP=os.getenv("QWEN_MODEL_CHEAP","qwen/qwen2.5-vl-72b-instruct")
BASE=os.getenv("DASHSCOPE_BASE_URL","https://openrouter.ai/api/v1")
OFERTA="https://legitcheck-cosmetics.netlify.app/oferta.html"
PRIVACY=OFERTA+"#privacy"

bot=telebot.TeleBot(TOKEN,threaded=True)
S={}
LOCKS={}
def chat_lock(cid):
    if cid not in LOCKS:
        LOCKS[cid]=threading.Lock()
    return LOCKS[cid]

SYSTEM="""Ты — экспертная система разбора LEGIT·CHECK (парфюмерия). Анализируешь фото продукта по чек-листу и даёшь структурированные ответы на русском.

ЖЁСТКИЕ ПРАВИЛА клиентского текста:
- Запрещены слова «ИИ», «нейросеть», «модель», «узлы», «алгоритм», «контрафакт», «фейк», «слои знаний», «режимы». Используй «детали», «чек-лист», «разбор», «бот».
- Никаких процентов и числовой уверенности. Итог — только словами.
- Никаких «100% гарантия», «официальный чек-лист». Итог — только из триады с формулировками ниже.
- Не выдумывай: деталь не видна или знаний недостаточно — честно «➖ не проверяется».
- Если изображение размыто, пикселизировано или текст не различим отчётливо — это «нечитаемо». Не угадывай и не восстанавливай текст по размытому снимку.
- Без звёздочек и маркдауна — только обычный текст.

КАЛИБРОВКА МАРКЕРОВ (СТРОГО):
- ЗАКРЫТЫЙ СПИСОК ❌-МАРКЕРОВ. ❌ разрешён ТОЛЬКО по этим типам и ни по каким другим:

TIER A (ур.2, всегда активен):
1) следы вмешательства в код на флаконе: стёртость, затирание, наклейка поверх места гравировки;
2) несовпадение батча на флаконе и коробке, когда обе видны в кадре;
3) кривая завальцовка, видимая в кадре: перекос металлического кольца, зазоры между кольцом и стеклом;
4) толстая или кривая трубочка — ТОЛЬКО при наличии кадра против света;
5) дефект полиграфии, видимый и процитированный из кадра (плывущий шрифт, кривая печать, опечатка на этикетке или коробке);
6) дефект стекла и литья, видимый в кадре: пузыри, муть, облой, сколы, трещины, кривые швы;
7) конфликт «коробка выглядит оригинальной ↔ флакон нет».

TIER B (ур.1, активен ТОЛЬКО по дата-гейту — продукт распознан И дата ≤ 2024):
8) анахронизм эпохи: батч ↔ строка дистрибьютора — ТОЛЬКО парой и ТОЛЬКО при точном знании бренда;
9) несоответствие гравировки/логотипа/формы флакона эталону бренда, при точном знании;
10) несоответствие формата батча официальному формату бренда, при цитируемом знании.

НЕ выдумывай «обязательные элементы» защиты/маркировки бренда вне этого списка. Всё вне списка (целлофан и его швы, цвет жидкости, уровень наполнения, «магнит крышки», отсутствие вкладышей, потёртости и царапины) — НЕ может быть ❌; максимум ⚠️ «слабый признак» с конкретикой.
- Батч, нечитаемый на фото (тусклая гравировка, блики), — НЕ ❌-маркер: если шаг пропущен или фото нечитаемо, деталь 03 помечается «➖ не проверяется».
- Каждый ❌ и каждый ⚠️ обязан содержать цитату из кадра: процитируй читаемый текст («батч читается как 45L310») или опиши видимый дефект с привязкой к месту («зазор между кольцом и стеклом справа»). Без цитаты — ✅ или ➖, никогда ⚠️/.
- ❌-маркер — ТОЛЬКО с конкретным основанием: процитируй, что именно читается/видится на фото, и объясни, чему это должно быть у оригинала. Расплывчатые формулировки («видны несоответствия», «такие как…») БЕЗ конкретики — НЕ маркеры. В ❌-обосновании укажи номер пункта списка (Tier A/B).
- 🔴 — ТОЛЬКО при 2+ независимых ❌ из списка. Ровно 1 ❌ — строго ⚠️.
- ✅ ставится ТОЛЬКО по детали, которая реально видна в кадре. Деталь не видна или не применима к форм-фактору (например, трубочка у роликового флакона) — строго «➖ не проверяется», никогда ✅.
- Батч и дата: форматы батчей различаются по рынкам и сами по себе НЕ маркеры без цитируемого официального формата бренда.
- Следы использования (потёртости, царапины, сниженный уровень жидкости) — нормальное состояние ношеного флакона, НЕ маркеры.

ДАТА-ГЕЙТ УР.1: если продукт не распознан из обучения ИЛИ дата продукта > 2024 — ур.1-признаки не применяются, Tier B маркеры запрещены, только Tier A (ур.2). Честно пиши «➖ специфическая сверка не проводилась».

СЛОИ ЗНАНИЙ (по приоритету):
ур.1 — специфические признаки конкретного аромата: форма флакона, гравировка, логотип, формат батча, строка дистрибьютора. Применяй, только если уверена в особенностях оригинала.
ур.2 — общие признаки форм-фактора: качество полиграфии, однородность стекла, швы и облой литья, ровность завальцовки, посадка крышки, согласованность маркировки с упаковкой.
ур.3 — не знаешь продукт или знание может устареть — не проверяй специфические признаки, честно пиши об этом и оценивай только ур.2.

ОСИ НАДЁЖНОСТИ ЧТЕНИЯ: «подтверждено по макро» — сильный; «видно на общем плане» — средний; «косвенно» — слабый, в красный итог не считается.

ИТОГИ (только словами):
🔴 «Выявлены признаки несоответствия оригиналу» — только при 2+ независимых ❌ из закрытого списка.
⚠️ «Есть сомнения в соответствии оригиналу» — 1 ❌ из списка, либо слабые признаки вне списка, либо нечитаемо ключевое.
🟢 «Признаков несоответствия оригиналу не выявлено» — маркеры не найдены по проверенным деталям; обязательно укажи, по каким деталям вынесен итог.

ВЕСА ДЕТАЛЕЙ (по убыванию): 03 Маркировка и батч-код — топ; 01 Упаковка и полиграфия; 02 Флакон и стекло; 04 Распылитель и завальцовка; 05 Крышка.
- Маркировка и батч-код — топ-вес; сверка батча на флаконе и коробке — главный ловитель переупаковки.
- 04-05 — дополнительные: аномалия по ним может быть ⚠️, но ❌ — только по закрытому списку.
- Конфликт «коробка читается как оригинал, флакон — нет» — пункт 7 закрытого списка.

СПИСОК «НЕ ПРОВЕРЯЕТСЯ»: детали из этого списка помечай «➖ не проверяется», выводов по ним не делай; итог выноси только по проверенным и укажи это в плашке. Аромат и состав содержимого по фото не верифицируются никогда."""

MODE_BOX="""Продукт: «{name}». Если название похоже на опечатку — попробуй понять, что имелось в виду.
Ответь СТРОГО двумя строками:
ФОРМ-ФАКТОР: [одно из: флакон с распылителем, роликовый флакон, флакон без распылителя, пробник/миниатюра]
НАЗВАНИЕ: [исправленное название продукта, если была опечатка, иначе исходное название]"""

MODE_LIST="""Продукт: «{name}». Форм-фактор продукта: {ff}. Продукт обычно продаётся в картонной коробке: {box}.

Начни ответ так:
Что снять:
Для разбора продукта «{name}» необходимы следующие снимки:

Затем выдай ОДИН нумерованный список КОРОТКИХ названий шагов в порядке важности, покрывающий все 5 деталей чек-листа: 01 Упаковка и полиграфия, 02 Флакон и стекло, 03 Маркировка и батч-код, 04 Распылитель и завальцовка, 05 Крышка.

Правила списка:
- Названия шагов — короткие, без пояснений и БЕЗ слова «макро». Используй названия кадров, не названия деталей. Примеры: «Батч-код на флаконе», «Флакон спереди с этикеткой», «Батч-код на коробке (при наличии)», «Сторона коробки с названием (при наличии)», «Распылитель и завальцовка», «Трубочка на просвет», «Крышка». Без повторов.
- Если «да» или «не знаю» — включай коробочные шаги, каждый помечай «(при наличии)». Пометка «(при наличии)» — ТОЛЬКО для коробочных шагов.
- Если «нет» — НЕ включай коробочные шаги вообще.
- Неприменимые к форм-фактору детали — не включай (у роликового флакона нет трубочки на просвет).
- Порядок по важности: батч-код на флаконе → флакон спереди с этикеткой → батч-код на коробке (при наличии) → сторона коробки с названием (при наличии) → распылитель и завальцовка → трубочка на просвет → крышка.

Без звёздочек и маркдауна — обычный текст. Не упоминай «слои знаний», «режимы» и внутренние правила."""

MODE0C="""РЕЖИМ 0 (цепочка). Продукт: «{name}».
Текущий шаг: {current}
Оставшиеся шаги:
{remaining}
На фото парфюмерия, ИЛИ часть её упаковки (этикетка, крышка, завальцовка, батч-код, дно флакона, трубочка)? Если да или похоже — анализируй шаг.
ТИП: не парфюмерия — ТОЛЬКО если на фото явно посторонний предмет: еда, одежда, техника, документ, человек, пустой стол.
Иначе определи, какому шагу соответствует фото. ВНИМАНИЕ: клиент скорее всего снимает текущий шаг — сначала сравни фото с описанием текущего шага, и только потом ищи среди остальных.
ВАЖНО: фото дна флакона — это шаг «Батч-код на флаконе» (код гравируется на дне), пока «Батч-код на флаконе» есть в оставшихся шагах. Относи фото дна к другим шагам ТОЛЬКО если «Батч-код на флаконе» уже снят или отсутствует в списке.
Ответь СТРОГО в формате:
ШАГ: [номер из списка; 0, если не подходит ни к одному]
ЧИТАЕМО: да/нет
СОВЕТ: [если нечитаемо — одним предложением как переснять]
Если изображение размыто или текст не различим отчётливо — это «нечитаемо». Не угадывай текст."""

MODE0C2="""РЕЖИМ 0 (контрольный вопрос). Продукт: «{name}».
Шаг: {step}.
Каким должен быть кадр: {hint}
Сравни фото с этим описанием. Соответствует ли фото описанию? Читаемо ли оно?
Ответь СТРОГО в формате:
СОВПАДЕНИЕ: да/нет
ЧИТАЕМО: да/нет
СОВЕТ: [если нечитаемо — одним предложением как переснять]"""

MODE0I="""РЕЖИМ 0 (добавочные фото). Продукт: «{name}».
На фото парфюмерия, ИЛИ часть её упаковки (этикетка, крышка, завальцовка, батч-код, дно флакона, трубочка)? Если да или похоже — анализируй.
ТИП: не парфюмерия — ТОЛЬКО если явно посторонний предмет: еда, одежда, техника, документ, человек, пустой стол.
Иначе ответь СТРОГО в формате:
ДЕТАЛЬ: [какая деталь чек-листа на фото; «не понял», если не ясно]
ЧИТАЕМО: да/нет
СОВЕТ: [если нет — коротко как переснять]
Если изображение размыто или текст не различим отчётливо — это «нечитаемо». Не угадывай текст."""

MODE0F="""РЕЖИМ 0 (финальный). Продукт: «{name}». Клиент не может предоставить: {cannot}.
Посмотри все фото и оцени каждую критическую деталь отдельно:
01 Упаковка и полиграфия — читаемо, если видна коробка или этикетка и различим текст.
02 Флакон и стекло — читаемо, если виден флакон общим планом.
03 Маркировка и батч-код — читаемо, если различим батч-код на флаконе или коробке.
Если изображение размыто или текст не различим отчётливо — это «нечитаемо». Не угадывай текст по размытому снимку.
Ответь СТРОГО в формате, без других слов:
01: читаемо/нечитаемо
02: читаемо/нечитаемо
03: читаемо/нечитаемо
MISSING: [НАЗВАНИЯ деталей из 5 (не номера), по которым нет читаемых фото, кроме тех, что клиент не может предоставить; «нет», если все покрыты]"""

MODE2="""РЕЖИМ 2. Дай финальный клиентский отчёт по продукту «{name}». Детали из списка «НЕ ПРОВЕРЯЕТСЯ» и детали без читаемых фото помечай «➖ не проверяется» без выводов по ним.
НАЗВАНИЯ ДЕТАЛЕЙ в отчёте пиши ТОЛЬКО точно так, без изменений формулировок:
01 Упаковка и полиграфия
02 Флакон и стекло
03 Маркировка и батч-код
04 Распылитель и завальцовка
05 Крышка

КАЛИБРОВКА (строго):
❌ — ТОЛЬКО по закрытому списку:

TIER A (ур.2, всегда активен):
(1) следы вмешательства в код на флаконе (стёртость, затирание, наклейка поверх гравировки);
(2) несовпадение батча флакон↔коробка при обеих видимых;
(3) кривая завальцовка: перекос кольца, зазоры;
(4) толстая или кривая трубочка — ТОЛЬКО при наличии кадра против света;
(5) процитированный дефект полиграфии из кадра (плывущий шрифт, кривая печать, опечатка);
(6) видимый дефект стекла и литья (пузыри, муть, облой, сколы, трещины, кривые швы);
(7) конфликт коробка↔флакон (коробка оригинал, флакон — нет).

TIER B (ур.1, активен ТОЛЬКО по дата-гейту — продукт распознан И дата ≤ 2024):
(8) анахронизм батч↔дистрибьютор парой при точном знании;
(9) несоответствие гравировки/логотипа/формы флакона эталону бренда;
(10) несоответствие формата батча официальному формату бренда.

Всё вне списка (целлофан, цвет жидкости, уровень наполнения, «магнит крышки», отсутствие вкладышей, потёртости, код нечитаемый на фото — ➖ если шаг пропущен) — НЕ ❌, максимум ⚠️ с конкретикой. Не выдумывай «обязательные элементы» бренда вне списка. 🔴 — только при 2+ ❌ из списка; ровно 1 ❌ — ️. Деталь не видна или не применима (трубочка у роликового флакона) — «➖ не проверяется», никогда ✅. Форматы батчей по рынкам различаются — сами по себе НЕ маркеры. Нет кадра против света — маркер по трубочке не применяется.
Каждый ❌ и каждый ⚠️ обязан содержать цитату из кадра: процитируй читаемый текст («батч читается как 45L310») или опиши видимый дефект с привязкой к месту («зазор между кольцом и стеклом справа»). Без цитаты — ✅ или ➖, никогда ⚠️/❌.

ДАТА-ГЕЙТ: если не уверена в продукте или дата > 2024 — TIER B не применяй, только TIER A + пиши «➖ специфическая сверка не проводилась».

В плашке строкой «Итог вынесен по деталям:» перечисли ВСЕ детали, по которым вынесен итог (все со статусами ✅/⚠️//➖), а не часть.
БАТЧ И ГОД: если уверена в формате батча конкретного бренда — проверь согласованность года выпуска с дизайном флакона и строкой дистрибьютора; несоответствие — маркер (учитывается в детали 03). Если не уверена — не выводи дату и не делай из неё маркер.

Формат — обычный текст, БЕЗ звёздочек и маркдауна:
1) Плашка: эмодзи (🔴/⚠️/🟢) + итог словами из триады + 1-2 предложения основания + отдельной строкой: «Итог вынесен по деталям: [список]».
2) Пять деталей, по каждой строка статуса строго из набора (✅ проверено / ⚠️ сомнение / ❌ маркер / ➖ не проверяется; знак для непроверяемых — именно ➖, не тире) и 1-2 предложения обоснования; в ❌-обосновании — конкретика и номер пункта закрытого списка (например, «❌ маркер (п.3 TIER A): металлическое кольцо завальцовки перекошено, зазор между кольцом и стеклом справа, у оригинала кольцо сидит вплотную»), без неё ставь ✅ или ⚠️.
3) Строка: «Аромат и состав самого содержимого по фото не верифицируются.»
4) Строка: «Результат — оценочное мнение по видимым признакам; не является экспертизой или юридическим заключением.»
5) Строка: «Каждый пункт отчёта проверяется по вашим фото. Если с каким-то пунктом не согласны — пришлите более чёткое фото этого места, и мы перепроверим пункт.»"""

MODE_RC="""РЕЖИМ ПРОВЕРКИ. Продукт: «{name}». Ниже — выданный ранее отчёт. Клиент не согласен с пунктом {num} и прислал новое, более чёткое фото этого места.
Старый отчёт:
{old}
Смотри ТОЛЬКО на новое фото. Подтверди, сними или уточни маркер по пункту {num}.
Ответь СТРОГО в формате:
СТАТУС: ✅/⚠️/❌/➖
ОБОСНОВАНИЕ: 1-2 предложения с цитатой из нового кадра (что читается или видно и где)."""

MODE_BBOX="""РАЗМЕТКА ФРАГМЕНТОВ. Продукт: «{name}». Присланы фото 1..{n}. Для каждого пункта {nums} укажи, на каком фото виден признак и координаты его области (целые числа от 0 до 1000).
Ответь СТРОГО по одной строке на пункт:
NN: ФОТО: k ОБЛАСТЬ: x1 y1 x2 y2"""
def st(cid):
    if cid not in S:
        S[cid]={"name":"","photos":[],"shots":"","queue":[],"closed":[],"cannot":[],"last_missing":[],"stage":"name","source":"","tariff":"","ff":"default","pending":-1,"pending_b64":"","retakes":0,"chain_complete":False,"last_closed":-1,"details":{},"report_text":"","rechecks":0}
    return S[cid]

def reset(cid):
    if cid in S: del S[cid]
    bot.send_message(cid,"Начинаем заново. Напишите название аромата.")

HINTS={"Батч-код на флаконе":"дно или низ флакона, код должен быть читаемым","Батч-код на коробке":"дно или низ коробки, код читаемый","Флакон спереди с этикеткой":"флакон целиком спереди, этикетка читаема","Сторона коробки с названием":"сторона коробки с названием аромата","Распылитель и завальцовка":"верх флакона сбоку, металлическое кольцо и стекло","Трубочка на просвет":"флакон против источника света, трубочка видна внутри","Крышка":"крышка сверху и снизу","Флакон сзади":"флакон целиком сзади","Флакон сбоку":"флакон целиком сбоку"}

def hint_for(name,ff):
    low=name.lower()
    for k,v in HINTS.items():
        if k.lower() in low: return v
    if "батч" in low: return "дно или низ, код читаемый"
    if "трубочк" in low: return "флакон против света"
    if "распылител" in low or "завальц" in low: return "верх флакона сбоку"
    if "крышк" in low: return "крышка сверху и снизу"
    if "короб" in low or "полиграф" in low: return "сторона коробки"
    if "флакон" in low and "стекло" in low: return "флакон целиком"
    if ff in ("роликовый флакон","пробник/миниатюра"): return "флакон целиком"
    return "флакон целиком с разных ракурсов"

def retake_extra(s):
    n=s.get("retakes",0)
    if n<2: return ""
    if n==2: return " Совет: косой дневной свет без вспышки, камера параллельно объекту."
    return " Если не получается — напишите «нет», пропустим шаг (в отчёте будет помечено «не проверяется»)."

def batch_note(s,step):
    if step!=3: return ""
    n=s.get("retakes",0)
    if n<2: return ""
    if n==2: return " Если код нечитаемый от завода — напишите «нет», проверим согласованность коробки и флакона."
    return " Если не читается — напишите «нет», проверим согласованность."

def norm_ff(x):
    if not x: return "default"
    x=x.lower()
    if "ролик" in x or "ролли" in x: return "роликовый флакон"
    if "без распылителя" in x: return "флакон без распылителя"
    if "пробник" in x or "миниатюр" in x: return "пробник/миниатюра"
    return "флакон с распылителем"

START_TEXT=("👋 Legit Check Perfume — разбор парфюмерии по фото на признаки несоответствия оригиналу.\n\n"
"Как работаем:\n"
"1. Напишите название аромата.\n"
"2. Пришлите фото продукта.\n"
"3. Бот соберёт чек-лист кадров и поможет сделать читаемые снимки.\n"
"4. Получаете структурированный отчёт с итогом по деталям.\n\n"
"Чтобы начать — напишите название.")

HELP_TEXT=("Я — бот LEGIT·CHECK, разбираю парфюмерию по фото на признаки несоответствия оригиналу. Напишите название аромата — начнём разбор. "
"Если кнопки пропали — напишите «Начать заново».")

BUSY_TEXT="⚠️ Сервис временно перегружен. Попробуйте ещё раз через минуту. Если не получится — напишите «Начать заново»."

SKILLS_TEXT=("Я разбираю парфюмерию по 5 деталям:\n\n"
"• Упаковка и полиграфия: картон, тиснение, шрифты, геометрия склейки, швы целлофана\n"
"• Флакон и стекло: однородность, швы и облой литья, дно, сколы и трещины\n"
"• Маркировка и батч-код: читаемость кода, совпадение флакон↔коробка, способ нанесения\n"
"• Распылитель и завальцовка: ровность кольца, зазоры, трубочка на просвет\n"
"• Крышка: посадка, зазоры, магнит\n\n"
"Итог выносится по проверенным деталям.\n"
"Непроверенные детали помечаются «не проверяется».")

DOC_HELP=("1. Откройте фото в галерее.\n"
"2. Нажмите «Поделиться» → «Telegram».\n"
"3. Выберите этот чат и нажмите 📎 (скрепку).\n"
"4. Выберите «Файл» и отправьте фото как файл.")

def kb_main():
    kb=types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(types.KeyboardButton("Навыки бота"))
    return kb

def img_b64(m):
    if m.content_type=="photo":
        f=bot.get_file(m.photo[-1].file_id)
        comp=True
    else:
        f=bot.get_file(m.document.file_id)
        comp=False
    raw=bot.download_file(f.file_path)
    im=Image.open(io.BytesIO(raw)).convert("RGB")
    w,h=im.size
    side=max(w,h)
    if side>2048: im=im.resize((int(w*2048/side),int(h*2048/side)),Image.LANCZOS)
    buf=io.BytesIO(); im.save(buf,"JPEG",quality=88,subsampling="4:2:0")
    return base64.b64encode(buf.getvalue()).decode(),comp

def ask_qwen(images,prompt,model,timeout=90,attempts=2):
    msgs=[{"role":"user","content":[]}]
    for b in images: msgs[0]["content"].append({"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b}"}})
    msgs[0]["content"].append({"type":"text","text":SYSTEM+"\n\n"+prompt})
    headers={"Authorization":f"Bearer {QWEN_KEY}","Content-Type":"application/json"}
    body={"model":model,"messages":msgs,"max_tokens":2000,"temperature":0.2}
    for i in range(attempts):
        try:
            r=requests.post(f"{BASE}/chat/completions",json=body,headers=headers,timeout=timeout)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
        except Exception:
            if i==attempts-1: raise
            time.sleep(1.0*(i+1))
    return ""

def parse(txt,key):
    if not txt: return ""
    for line in txt.splitlines():
        s=line.strip()
        if s.upper().startswith(key.upper()+":"): return s.split(":",1)[1].strip()
        if s.upper().startswith(key.upper()+" :"): return s.split(":",1)[1].strip()
    return ""

def postprocess_verdict(rep):
    if not rep: return ""
    c=rep.lower()
    if "признаков несоответствия оригиналу не выявлено" in c: return re.sub(r"🔴|⚠️","🟢",rep).replace("Выявлены признаки несоответствия оригиналу","Признаков несоответствия оригиналу не выявлено").replace("Есть сомнения в соответствии оригиналу","Признаков несоответствия оригиналу не выявлено")
    if "есть сомнения" in c: return re.sub(r"🔴|🟢","⚠️",rep).replace("Выявлены признаки несоответствия оригиналу","Есть сомнения в соответствии оригиналу").replace("Признаков несоответствия оригиналу не выявлено","Есть сомнения в соответствии оригиналу")
    return re.sub(r"⚠️|🟢","🔴",rep).replace("Есть сомнения в соответствии оригиналу","Выявлены признаки несоответствия оригиналу").replace("Признаков несоответствия оригиналу не выявлено","Выявлены признаки несоответствия оригиналу")

def parse_details(rep):
    d={}
    for line in rep.splitlines():
        m=re.match(r'^(0[1-5])\s*[\.\)]?\s*(✅|⚠️|❌|➖)',line.strip())
        if m: d[m.group(1)]=m.group(2)
    return d

def verdict_str(d):
    red=sum(1 for v in d.values() if v=="❌")
    if red>=2: return "🔴 «Выявлены признаки несоответствия оригиналу»"
    if red==1: return "⚠️ «Есть сомнения в соответствии оригиналу»"
    return "🟢 «Признаков несоответствия оригиналу не выявлено»"

def crop_b64(b64,box):
    im=Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
    w,h=im.size
    x1,y1,x2,y2=box
    x1=int(x1/1000*w); x2=int(x2/1000*w); y1=int(y1/1000*h); y2=int(y2/1000*h)
    mw,mh=int((x2-x1)*0.6),int((y2-y1)*0.6)
    x1=max(0,x1-mw); y1=max(0,y1-mh); x2=min(w,x2+mw); y2=min(h,y2+mh)
    im=im.crop((x1,y1,x2,y2))
    buf=io.BytesIO(); im.save(buf,"JPEG",quality=88)
    return base64.b64encode(buf.getvalue()).decode()

def recheck_limit(s):
    return 2 if s.get("tariff")=="Экспресс" else 1

def clean_missing(s):
    if not s or s.strip().lower()=="нет": return []
    out=[]
    for p in re.split(r"[,;\n]+",s):
        p=p.strip()
        if not p: continue
        for pref in ["нет:","missing:","пропущены:","не хватает:"]:
            if p.lower().startswith(pref): p=p[len(pref):].strip()
        if p and p.lower()!="нет": out.append(p)
    return out

def first_open(s):
    for i in range(len(s["queue"])):
        if i not in s["closed"]: return i
    return -1

def step_msg(s,ni):
    h=hint_for(s["queue"][ni],s.get("ff","default"))
    remaining=len([i for i in range(len(s["queue"])) if i not in s["closed"]])
    return f"Следующий шаг {ni+1} из оставшихся {remaining}: «{s['queue'][ni]}». Каким должен быть кадр: {h}."

def kb_tariffs():
    kb=types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("Стандартный — 500 ₽ (до 3 ч)",callback_data="std"))
    kb.add(types.InlineKeyboardButton("Экспресс — 1000 ₽ (до 15 мин)",callback_data="exp"))
    return kb

def send_tariffs(cid):
    s=st(cid)
    s["stage"]="tariffs"
    warn=""
    if s["cannot"]:
        warn="\n\nОбратите внимание: "+", ".join(s["cannot"])+" — не будет проверяться. Итог будет вынесен по остальным деталям."
    bot.send_message(cid,"Отчёт готов к выдаче. (Тестовый режим: оплата отключена.) Выберите тариф:"+warn,reply_markup=kb_tariffs())

def start_chain(cid,box):
    s=st(cid)
    s["shots"]=box
    bot.send_message(cid,"📋 Составляю список кадров под продукт…")
    try:
        lst=ask_qwen([],MODE_LIST.format(name=s["name"] or "?",ff=s.get("ff","default"),box=box),QWEN_CHEAP,timeout=60,attempts=2)
    except Exception:
        logging.exception("mode_list")
        bot.send_message(cid,BUSY_TEXT)
        return
    lines=[]
    for line in lst.splitlines():
        line=line.strip()
        m=re.match(r"^(\d+)\.\s*(.+)$",line)
        if m: lines.append(m.group(2))
    if not lines: lines=[l.strip(" -•*") for l in lst.splitlines() if l.strip() and l.strip()!="Что снять:"]
    s["queue"]=lines
    s["stage"]="chain"
    ni=first_open(s)
    if ni>=0:
        bot.send_message(cid,"Готово. Нужно сделать кадров: "+str(len(lines))+".\n"+step_msg(s,ni))
    else:
        bot.send_message(cid,"Список пуст. Пришлите фото или напишите «Начать заново».")

def accept_step(cid,s,n,b64):
    s["photos"].append(b64)
    s["closed"].append(n-1)
    s["retakes"]=0
    ni=first_open(s)
    if ni>=0:
        bot.send_message(cid,f"📥 Шаг {n}: принято.\n"+step_msg(s,ni))
    else:
        bot.send_message(cid,"📥 Все кадры получены.")
        end_chain(cid)

def end_chain(cid):
    s=st(cid)
    s["chain_complete"]=True
    if not s["photos"]:
        bot.send_message(cid,"Фото не получены — разбор не может быть оказан, оплата не запрашивается.")
        return
    audit(cid)
def audit(cid):
    s=st(cid)
    if not s["photos"]:
        bot.send_message(cid,"Фото не получены — разбор не может быть оказан, оплата не запрашивается.")
        return
    cannot=", ".join(s["cannot"]) or "нет"
    try:
        res=ask_qwen(s["photos"],MODE0F.format(name=s["name"] or "?",cannot=cannot),QWEN_CHEAP,timeout=90,attempts=2)
    except Exception:
        logging.exception("mode0f")
        bot.send_message(cid,BUSY_TEXT)
        return
    missing=clean_missing(parse(res,"MISSING"))
    names={"01":"Упаковка и полиграфия","02":"Флакон и стекло","03":"Маркировка и батч-код"}
    for k in ("01","02","03"):
        if (parse(res,k) or "").lower().startswith("нечитаемо") and names[k] not in missing:
            missing.append(names[k])
    if missing:
        s["last_missing"]=missing
        s["stage"]="audit"
        bot.send_message(cid,"⚠️ По имеющимся фото итог вынести невозможно: не хватает критических деталей ("+", ".join(missing)+").\n\nДослать фото сейчас? Напишите «да» или «нет».")
    else:
        s["last_missing"]=[]
        send_tariffs(cid)

def accept_step(cid,s,n,b64):
    s["photos"].append(b64)
    if (n-1) not in s["closed"]: s["closed"].append(n-1)
    s["retakes"]=0
    ni=first_open(s)
    if ni>=0:
        bot.send_message(cid,"📥 Шаг "+str(n)+": принято.\n"+step_msg(s,ni))
    else:
        bot.send_message(cid,"📥 Все кадры получены.")
        end_chain(cid)

def end_chain(cid):
    s=st(cid)
    s["chain_complete"]=True
    if not s["photos"]:
        bot.send_message(cid,"Фото не получены — разбор не может быть оказан, оплата не запрашивается.")
        return
    audit(cid)

def process_image(cid,b64,comp):
    s=st(cid)
    if s["stage"]=="audit_add":
        s["photos"].append(b64)
        bot.send_message(cid,"📥 Получено. Ещё кадры? Напишите «готово», когда всё.")
        return
    ni=first_open(s)
    if ni<0:
        end_chain(cid); return
    remaining="\n".join(str(i+1)+". "+q for i,q in enumerate(s["queue"]) if i not in s["closed"])
    try:
        res=ask_qwen([b64],MODE0C.format(name=s["name"] or "?",current=s["queue"][ni],remaining=remaining),QWEN_CHEAP,timeout=60,attempts=2)
    except Exception:
        logging.exception("mode0c")
        bot.send_message(cid,BUSY_TEXT); return
    step=parse(res,"ШАГ")
    readable=(parse(res,"ЧИТАЕМО") or "").lower().startswith("да")
    advice=parse(res,"СОВЕТ")
    m=re.search(r"\d+",step or "")
    n=int(m.group(0)) if m else 0
    if n==0 or n>len(s["queue"]) or (n-1) in s["closed"]:
        try:
            res2=ask_qwen([b64],MODE0C2.format(name=s["name"] or "?",step=s["queue"][ni],hint=hint_for(s["queue"][ni],s.get("ff","default"))),QWEN_CHEAP,timeout=60,attempts=2)
        except Exception:
            logging.exception("mode0c2")
            bot.send_message(cid,BUSY_TEXT); return
        match=(parse(res2,"СОВПАДЕНИЕ") or "").lower().startswith("да")
        readable=(parse(res2,"ЧИТАЕМО") or "").lower().startswith("да")
        advice=parse(res2,"СОВЕТ")
        if match and readable:
            accept_step(cid,s,ni+1,b64); return
        s["retakes"]=s.get("retakes",0)+1
        bot.send_message(cid,"⚠️ Кадр не подходит или нечитаем. "+(advice or "")+retake_extra(s)+"\n"+step_msg(s,ni))
        return
    if readable:
        accept_step(cid,s,n,b64)
    else:
        s["retakes"]=s.get("retakes",0)+1
        bot.send_message(cid,"⚠️ Нечитаемо. "+(advice or "")+retake_extra(s)+batch_note(s,n)+"\n"+step_msg(s,ni))

def add_image(m):
    cid=m.chat.id
    s=st(cid)
    if s["stage"]=="name":
        bot.send_message(cid,"Сначала напишите название аромата."); return
    if s["stage"]=="feedback":
        bot.send_message(cid,"Отчёт выдан. Для новой проверки напишите «Начать заново»."); return
    if s["stage"]=="tariffs":
        bot.send_message(cid,"Выберите тариф кнопками ниже."); return
    try:
        b64,comp=img_b64(m)
    except Exception:
        logging.exception("img_b64")
        bot.send_message(cid,"Не смог прочитать файл. Пришлите фото как документ (скрепка → Файл)."); return
    if s["stage"]=="done":
        if s.get("rechecks",0)>=recheck_limit(s):
            bot.send_message(cid,"Отчёт выдан, лимит перепроверок исчерпан. Для новой проверки напишите «Начать заново»."); return
        s["rc_photo"]=b64
        s["stage"]="recheck"
        bot.send_message(cid,"📥 Фото получено. Какой пункт перепроверить? Напишите номер от 01 до 05.")
        return
    with chat_lock(cid):
        process_image(cid,b64,comp)

@bot.message_handler(content_types=["photo"])
def photo(m):
    add_image(m)

@bot.message_handler(content_types=["document"])
def doc(m):
    add_image(m)

def send_crops(cid,s):
    marks=[n for n,v in s["details"].items() if v in ("❌","⚠️")][:3]
    if not marks: return
    try:
        res=ask_qwen(s["photos"],MODE_BBOX.format(name=s["name"] or "?",n=len(s["photos"]),nums=", ".join(marks)),QWEN_CHEAP,timeout=90,attempts=1)
    except Exception:
        logging.exception("mode_bbox")
        return
    for n in marks:
        m=re.search(re.escape(n)+r"\s*:\s*ФОТО:\s*(\d+)\s*ОБЛАСТЬ:\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)[,\s]+(\d+)",res)
        if not m: continue
        pi=int(m.group(1))-1
        if 0<=pi<len(s["photos"]):
            try:
                cb64=crop_b64(s["photos"][pi],[int(x) for x in m.groups()[1:]])
                bot.send_photo(cid,io.BytesIO(base64.b64decode(cb64)),caption="Фрагмент по пункту "+n+".")
            except Exception:
                logging.exception("crop")

@bot.message_handler(func=lambda m: m.text is not None)
def text(m):
    cid=m.chat.id
    t=m.text.strip()
    if t.lower() in ("начать заново",):
        reset(cid); return
    s=st(cid)
    if t.lower()=="навыки бота":
        bot.send_message(cid,SKILLS_TEXT); return
    if s["stage"]=="name":
        if len(t)<2:
            bot.send_message(cid,"Напишите название аромата, например: «Dior Sauvage»."); return
        s["name"]=t
        s["stage"]="box"
        kb=types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("Да",callback_data="box_yes"),types.InlineKeyboardButton("Нет",callback_data="box_no"),types.InlineKeyboardButton("Не знаю",callback_data="box_dk"))
        bot.send_message(cid,"Продукт «"+t+"». Обычно продаётся в картонной коробке?",reply_markup=kb)
        return
    if s["stage"]=="box":
        bot.send_message(cid,"Нажмите кнопку под вопросом."); return
    if s["stage"]=="recheck":
        num="".join(ch for ch in t if ch.isdigit())
        n=("0"+num) if len(num)==1 else num
        if n not in ("01","02","03","04","05"):
            bot.send_message(cid,"Напишите номер пункта от 01 до 05."); return
        bot.send_message(cid,"🔁 Перепроверяю пункт "+n+"…")
        try:
            rc=ask_qwen([s["rc_photo"]],MODE_RC.format(name=s["name"] or "?",num=n,old=s.get("report_text","")),QWEN_MODEL,timeout=90,attempts=2)
        except Exception:
            logging.exception("mode_rc")
            bot.send_message(cid,BUSY_TEXT); return
        line=parse(rc,"СТАТУС")
        newst=next((e for e in ("❌","⚠️","✅","➖") if e in line),"➖")
        old=s["details"].get(n,"➖")
        s["details"][n]=newst
        s["rechecks"]=s.get("rechecks",0)+1
        s["stage"]="done"
        just=parse(rc,"ОБОСНОВАНИЕ")
        msg="Пункт "+n+" после перепроверки: "+newst
        if just: msg+=". "+just
        msg+="\n"+("Общий итог пересчитан: " if newst!=old else "Общий итог не изменился: ")+verdict_str(s["details"])
        if s["rechecks"]<recheck_limit(s):
            msg+="\nЕсли хотите перепроверить ещё пункт — пришлите фото этого места."
        else:
            msg+="\nЛимит перепроверок исчерпан. Для новой проверки напишите «Начать заново»."
        bot.send_message(cid,msg)
        return
    if s["stage"]=="audit":
        if t.lower().startswith("да"):
            s["stage"]="audit_add"
            bot.send_message(cid,"Пришлите недостающие кадры: "+", ".join(s["last_missing"])+"."); return
        if t.lower().startswith("нет"):
            send_tariffs(cid); return
        bot.send_message(cid,"Напишите «да» или «нет»."); return
    if s["stage"]=="audit_add":
        if t.lower() in ("готово","хватит","все"):
            audit(cid); return
        bot.send_message(cid,"Пришлите кадры или напишите «готово»."); return
    if s["stage"]=="chain":
        if t.lower() in ("нет","не могу","пропустить"):
            ni=first_open(s)
            if ni>=0:
                s["closed"].append(ni)
                s["cannot"].append(s["queue"][ni])
                s["retakes"]=0
                n2=first_open(s)
                if n2>=0:
                    bot.send_message(cid,"⚠️ Пропускаю шаг. В отчёте эта деталь будет помечена «не проверяется».\n"+step_msg(s,n2))
                else:
                    bot.send_message(cid,"📥 Все шаги закрыты.")
                    end_chain(cid)
            return
        ni=first_open(s)
        if ni>=0:
            bot.send_message(cid,"Сейчас идёт сбор кадров. "+step_msg(s,ni))
        return
    if s["stage"]=="done":
        bot.send_message(cid,"Отчёт выдан. Если хотите перепроверить пункт — пришлите фото этого места. Для новой проверки напишите «Начать заново».")
        return

@bot.callback_query_handler(func=lambda c: True)
def cb(c):
    cid=c.message.chat.id
    s=st(cid)
    d=c.data
    if d.startswith("box_"):
        box={"box_yes":"да","box_no":"нет","box_dk":"не знаю"}[d]
        try: bot.answer_callback_query(c.id)
        except Exception: pass
        start_chain(cid,box)
        return
    if d=="std":
        s["tariff"]="Стандартный"
    elif d=="exp":
        s["tariff"]="Экспресс"
    else:
        return
    try: bot.answer_callback_query(c.id)
    except Exception: pass
    bot.send_message(cid,"Тариф: "+s["tariff"]+". Собираю отчёт…")
    tariff_note="\nТАРИФ ЭКСПРЕСС: дай максимально подробные обоснования: 2-3 предложения на деталь, процитируй все видимые признаки." if s["tariff"]=="Экспресс" else "\nТАРИФ СТАНДАРТ: обоснования 1-2 предложения на деталь."
    try:
        rep=ask_qwen(s["photos"],MODE2.format(name=s["name"] or "?")+tariff_note,QWEN_MODEL,timeout=120,attempts=2)
    except Exception:
        logging.exception("mode2")
        bot.send_message(cid,BUSY_TEXT); return
    rep=postprocess_verdict(rep)
    s["report_text"]=rep
    s["details"]=parse_details(rep)
    s["rechecks"]=0
    s["stage"]="done"
    for i in range(0,len(rep),4000):
        bot.send_message(cid,rep[i:i+4000])
    if s["tariff"]=="Экспресс":
        send_crops(cid,s)

@bot.message_handler(commands=["start"])
def start(m):
    cid=m.chat.id
    if cid in S: del S[cid]
    bot.send_message(m.chat.id,START_TEXT,reply_markup=kb_main())

if __name__=="__main__":
    logging.basicConfig(level=logging.INFO)
    bot.infinity_polling(timeout=30,long_polling_timeout=30)