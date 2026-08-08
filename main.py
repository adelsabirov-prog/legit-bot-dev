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
OFERTA="https://legitcheck-perfume.vercel.app/oferta"
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
- ❌-маркер — ТОЛЬКО с конкретным основанием: процитируй, что именно читается/видится на фото, и объясни, чему это должно быть у оригинала. Расплывчатые формулировки («видны несоответствия», «такие как…») БЕЗ конкретики — НЕ маркеры. В ❌-обосновании укажи номер пункта списка (Tier A/B).
- Каждый ❌ и каждый ️ обязан содержать цитату из кадра: процитируй читаемый текст («батч читается как 45L310») или опиши видимый дефект с привязкой к месту («зазор между кольцом и стеклом справа»). Без цитаты — ✅ или ➖, никогда ⚠️/❌.
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

Всё вне списка (целлофан, цвет жидкости, уровень наполнения, «магнит крышки», отсутствие вкладышей, потёртости, код нечитаемый на фото — ➖ если шаг пропущен) — НЕ ❌, максимум ⚠️ с конкретикой. Не выдумывай «обязательные элементы» бренда вне списка. 🔴 — только при 2+ ❌ из списка; ровно 1 ❌ — ⚠️. Деталь не видна или не применима (трубочка у роликового флакона) — «➖ не проверяется», никогда ✅. Форматы батчей по рынкам различаются — сами по себе НЕ маркеры. Нет кадра против света — маркер по трубочке не применяется.
- Каждый ❌ и каждый ⚠️ обязан содержать цитату из кадра: процитируй читаемый текст («батч читается как 45L310») или опиши видимый дефект с привязкой к месту («зазор между кольцом и стеклом справа»). Без цитаты — ✅ или ➖, никогда ️/❌.

ДАТА-ГЕЙТ: если не уверена в продукте или дата > 2024 — TIER B не применяй, только TIER A + пиши «➖ специфическая сверка не проводилась».

В плашке строкой «Итог вынесен по деталям:» перечисли ВСЕ детали, по которым вынесен вывод (все со статусами ✅/⚠️/❌/➖), а не часть.
БАТЧ И ГОД: если уверена в формате батча конкретного бренда — проверь согласованность года выпуска с дизайном флакона и строкой дистрибьютора; несоответствие — маркер (учитывается в детали 03). Если не уверена — не выводи дату и не делай из неё маркер.

Формат — обычный текст, БЕЗ звёздочек и маркдауна:
1) Плашка: эмодзи (🔴/️/🟢) + итог словами из триады + 1-2 предложения основания + отдельной строкой: «Итог вынесен по деталям: [список]».
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

MODE_SCREENSHOT="""Определи тип изображения. Критерии:
- REAL_PHOTO: реальное фото предмета, видны текстуры, освещение, перспектива
- SCREENSHOT: скриншот экрана телефона (видны элементы интерфейса, статус-бар, плоская перспектива)
- MESSENGER_COMPRESSED: фото с сильными артефактами сжатия (размытие, блочность, потеря деталей)

Ответь СТРОГО одним словом: REAL_PHOTO, SCREENSHOT или MESSENGER_COMPRESSED."""

START_TEXT=("👋 Legit Check Perfume — разбор парфюмерии по фото на признаки несоответствия оригиналу.\n\n"
"Как это работает:\n"
"1. Напишите название аромата — составим список необходимых кадров под ваш флакон.\n"
"2. По шагам соберём фотографии — принимаем ТОЛЬКО документом (без сжатия), чтобы разбор был точным.\n"
"3. После подтверждения пригодности фото — оплата: 500 ₽ (Стандартный, до 3 ч) или 1000 ₽ (Экспресс, до 15 минут)\n"
"4. Получаете структурированный отчёт с общим итогом по деталям.\n\n"
"Напишите название аромата.\nПример: «Dior Sauvage», «Chanel №5», «Черный опиум»")

HELP_TEXT=("Я бот LEGIT·CHECK: разбираю парфюмерию по фото на признаки несоответствия оригиналу — по чек-листу из 5 деталей.\n\n"
"Стоимость: 500 ₽ (Стандартный, до 3 ч) или 1000 ₽ (Экспресс, до 15 мин).\n\n"
"Фото присылайте ТОЛЬКО ДОКУМЕНТОМ (скрепка 📎 → «Документ»/«Файл») — обычные фото Telegram сжимает, и разбор по ним не оказывается.\n\n"
"Чтобы начать, напишите название аромата.\nПример: «Dior Sauvage», «Chanel №5», «Черный опиум».")

SKILLS_TEXT=("🔍 Что определяет бот:\n\n"
"01 Упаковка и полиграфия\n"
"— резкость печати, ровность шрифтов, цветопередача\n"
"— геометрия склейки, швы целлофана\n\n"
"02 Флакон и стекло\n"
"— однородность стекла: пузыри, муть\n"
"— швы литья, обработка дна, сколы и трещины\n\n"
"03 Маркировка и батч-код\n"
"— читаемость кода на флаконе\n"
"— совпадение кода на флаконе и коробке (переупаковка)\n\n"
"04 Распылитель и завальцовка\n"
"— ровность завальцовки, зазоры и перекосы\n"
"— толщина и ровность трубочки (кадр против света)\n\n"
"05 Крышка\n"
"— посадка и зазоры, качество пластика\n\n"
"Итог выносится по проверенным деталям.\nНепроверенные детали помечаются — «не проверяется».")

DOC_HELP=("📎 Как отправить документом (30 секунд):\n"
"Android: скрепка 📎 → «Документ» → выберите фото в галерее → отправить.\n"
"iPhone: откройте фото в «Фото» → кнопка «Поделиться» → «Сохранить в Файлы». Затем в Telegram: скрепка 📎 → «Файл» → найдите фото → отправить.\n"
"Фото придёт без сжатия — я увижу батч и завальцовку.")

SCREENSHOT_HELP=("📥 Для точности разбора нужно фото, снятое на камеру вашего телефона. "
"Скриншоты и фото из мессенджеров теряют детали, необходимые для проверки батч-кода и полиграфии. "
"Откройте Telegram → выберите фото → отправьте как Документ.")

BUSY_TEXT="⚠️ Сервис временно перегружен. Подождите минуту и пришлите фото ещё раз — всё сохранится."

BASE_LISTS={
"spray":["Батч-код на флаконе","Флакон спереди с этикеткой","Распылитель и завальцовка","Трубочка на просвет","Крышка"],
"roll":["Батч-код на флаконе","Флакон спереди с этикеткой","Ролик и горлышко","Крышка"],
"splash":["Батч-код на флаконе","Флакон спереди с этикеткой","Горлышко и ограничитель","Крышка"],
"sample":["Батч-код на флаконе","Флакон спереди с этикеткой","Крышка или распылитель"],
}
BOX_STEPS=["Батч-код на коробке (при наличии)","Сторона коробки с названием (при наличии)"]
NOBOX_KEYWORDS=[]

def build_list(ff,box):
    base=BASE_LISTS.get(ff)
    if not base: return None
    out=base[:1]
    if box!="нет": out+=BOX_STEPS
    out+=base[1:]
    return out

def norm_ff(s):
    s=(s or "").lower()
    if "ролик" in s or "roll" in s: return "roll"
    if "пробник" in s or "мини" in s or "семпл" in s or "vial" in s: return "sample"
    if "сплэш" in s or "splash" in s or "без распыл" in s: return "splash"
    return "spray"

FF_LABEL={"spray":"флакон с распылителем","roll":"роликовый флакон","splash":"флакон без распылителя","sample":"пробник/миниатюра"}

BATCH_NO_NOTE=" Если кода на флаконе нет совсем — напишите «нет», проверим коробку и остальные детали."

def hint_for(step,ff):
    s=step.lower()
    if "батч" in s and "короб" in s:
        return "Код на дне или боку коробки. Снимите крупным планом, чтобы текст читался."
    if "батч" in s:
        return "Код на дне флакона: гравировка, печать или наклейка; иногда — на боку у основания. Переверните флакон и снимите дно крупным планом, чтобы читался текст и были видны швы стекла."+BATCH_NO_NOTE
    if "короб" in s and ("назван" in s or "сторон" in s):
        return "Снимите коробку спереди, чтобы читались название и все надписи."
    if "флакон" in s or "этикетк" in s:
        return "Поставьте флакон на ровную поверхность этикеткой к камере. Снимите спереди, чтобы читался весь текст. Не держите в руке."
    if "дно" in s:
        return "Переверните флакон и снимите дно крупным планом, чтобы читалась гравировка и были видны швы."
    if "трубочк" in s or "просвет" in s:
        return "Поднесите флакон к свету (окно или лампа) и снимите так, чтобы была видна трубочка внутри. Если не получается — напишите «нет»."
    if "завальц" in s or "распылит" in s:
        return "Снимите верх флакона крупным планом: распылитель и металлическое кольцо (завальцовку), которое его держит."
    if "ролик" in s or "горлышк" in s:
        return "Снимите горлышко крупным планом: ролик, крепление и ограничитель."
    if "крышк" in s:
        return "Снимите крышку: снаружи и изнутри, крупным планом."
    return ""

def batch_note(s,n):
    if 1<=n<=len(s["queue"]) and "батч" in s["queue"][n-1].lower() and "короб" not in s["queue"][n-1].lower():
        return "\nЕсли видите, что кода на флаконе нет совсем — напишите «нет», пойдём дальше."
    return ""

def postprocess_verdict(report):
    red_count=0
    detail_pattern=re.compile(r'^(0[1-5])\s*[\.\)]?\s*(✅|⚠️||➖)')
    for line in report.split('\n'):
        if detail_pattern.match(line.strip()) and '❌' in line:
            red_count+=1
    if '🔴' in report and red_count<2:
        report=report.replace('🔴 «Выявлены признаки несоответствия оригиналу»','⚠️ «Есть сомнения в соответствии оригиналу»')
        report=report.replace('🔴 Выявлены признаки несоответствия оригиналу','⚠️ Есть сомнения в соответствии оригиналу')
        if report.lstrip().startswith('🔴'):
            report='⚠️'+report.lstrip()[1:]
    return report

def parse_details(rep):
    d={}
    for line in rep.splitlines():
        m=re.match(r'^(0[1-5])\s*[\.\)]?\s*(✅|⚠️||➖)',line.strip())
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
                time.sleep(3)
                continue
            raise
        if r.status_code in (429,500,502,503):
            logging.error("QWEN RETRY %s %s",r.status_code,r.text[:500])
            if attempt<attempts-1:
                time.sleep(4)
                continue
        break
    if r.status_code!=200:
        logging.error("QWEN ERROR %s %s",r.status_code,r.text[:1500])
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

def downscale_b64(raw,limit):
    im=Image.open(io.BytesIO(raw)).convert("RGB")
    w,h=im.size; m=max(w,h)
    if m>limit:
        k=limit/m; im=im.resize((int(w*k),int(h*k)),Image.LANCZOS)
    buf=io.BytesIO(); im.save(buf,"JPEG",quality=85)
    return base64.b64encode(buf.getvalue()).decode()

def img_b64(m):
    is_doc=m.content_type=="document"
    fid=m.photo[-1].file_id if not is_doc else m.document.file_id
    fp=bot.get_file(fid).file_path
    r=requests.get(f"https://api.telegram.org/file/bot{TOKEN}/{fp}",timeout=60)
    
    suspect_screenshot=False
    if is_doc:
        try:
            im=Image.open(io.BytesIO(r.content))
            w,h=im.size
            if w>0 and h>0:
                ratio=h/w
                if 2.0<=ratio<=2.44:
                    suspect_screenshot=True
        except Exception:
            pass
    
    return downscale_b64(r.content,2048 if is_doc else 1600), (not is_doc), suspect_screenshot

def st(cid):
    return S.setdefault(cid,{"name":"","photos":[],"shots":"","queue":[],"closed":[],"cannot":[],"last_missing":[],"stage":"name","source":"","tariff":"","ff":"default","pending":-1,"pending_b64":"","retakes":0,"chain_complete":False,"last_closed":-1,"report_text":"","details":{},"rechecks":0,"rc_photo":""})

def kb_main():
    kb=types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔍 Что умеет бот",callback_data="skills"))
    kb.add(types.InlineKeyboardButton("📄 Оферта",url=OFERTA),types.InlineKeyboardButton("🔒 Политика конфиденциальности",url=PRIVACY))
    return kb

def reset(cid):
    S[cid]={"name":"","photos":[],"shots":"","queue":[],"closed":[],"cannot":[],"last_missing":[],"stage":"name","source":"","tariff":"","ff":"default","pending":-1,"pending_b64":"","retakes":0,"chain_complete":False,"last_closed":-1,"report_text":"","details":{},"rechecks":0,"rc_photo":""}
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

def first_open(s):
    for i in range(len(s["queue"])):
        if i not in s["closed"]:
            return i
    return -1

def step_msg(s,ni):
    h=hint_for(s["queue"][ni],s.get("ff","default"))
    return f"➡️ Шаг {ni+1}/{len(s['queue'])}: {s['queue'][ni]}" + (f"\n{h}" if h else "") + "\nЕсли шаг не подходит или не получается — напишите «нет», пропустим и пойдём дальше."

def retake_extra(s):
    s["retakes"]=s.get("retakes",0)+1
    return "\nЕсли не получается — напишите «нет», пропустим этот шаг и пойдём дальше." if s["retakes"]>=2 else ""

def accept_step(cid,s,n,b64):
    s["closed"].append(n-1)
    s["last_closed"]=n-1
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

def start_chain(cid,box):
    s=st(cid)
    qlist=build_list(s["ff"],box)
    if qlist is not None:
        s["queue"]=qlist
        s["shots"]="Что снять:\nДля разбора продукта «"+s["name"]+"» необходимы следующие снимки:\n\n"+"\n".join(f"{i+1}. {q}" for i,q in enumerate(s["queue"]))
    else:
        try:
            s["shots"]=ask_qwen([],MODE_LIST.format(name=s["name"],ff=FF_LABEL[s["ff"]],box=box),QWEN_CHEAP,timeout=60,attempts=1)
        except Exception:
            logging.exception("mode_list")
            s["shots"]="\n".join(f"{i+1}. {q}" for i,q in enumerate(build_list("spray",box) or []))
        if box=="нет":
            lines=[l for l in s["shots"].splitlines() if "короб" not in l.lower()]
            out=[]; n=0
            for l in lines:
                mm=re.match(r"^\s*(\d+)[\.\)]\s*(.+)$",l.strip())
                if mm:
                    n+=1; out.append(f"{n}. {mm.group(2).strip()}")
                else:
                    out.append(l)
            s["shots"]="\n".join(out)
        s["shots"]="\n".join(l if "короб" in l.lower() else l.replace("(при наличии)","").strip() for l in s["shots"].splitlines())
        s["shots"],steps=dedup_shots(s["shots"])
        s["queue"]=steps or build_list("spray",box)
    s["closed"]=[]
    s["stage"]="chain"
    bot.send_message(cid,f"{s['shots']}\n\nСобираем кадры по шагам — буду подсказывать каждый и скажу, если нужно переснять. Фото принимаю ТОЛЬКО документом:\n{DOC_HELP}\n\n"+step_msg(s,0),reply_markup=types.ReplyKeyboardRemove())

def send_tariffs(cid):
    s=st(cid)
    s["stage"]="tariffs"
    warn=""
    if s["cannot"]:
        warn="\n\nОбратите внимание: "+", ".join(s["cannot"])+" — не будет проверяться. Итог будет вынесен по остальным деталям."
    kb=types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("Стандартный — 500 ₽ · до 3 часов",callback_data="std"))
    kb.add(types.InlineKeyboardButton("Экспресс — 1000 ₽ · до 15 минут",callback_data="exp"))
    bot.send_message(cid,f"Фото подходят для проверки.{warn}\n\nВыберите тариф:\n\nОплачивая, вы принимаете условия оферты: {OFERTA}",reply_markup=kb)

def send_crops(cid,s):
    marks=[n for n,v in s["details"].items() if v in ("❌","️")][:3]
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

@bot.message_handler(commands=["start"])
def start(m):
    parts=m.text.split()
    S[m.chat.id]={"name":"","photos":[],"shots":"","queue":[],"closed":[],"cannot":[],"last_missing":[],"stage":"name","source":parts[1] if len(parts)>1 else "","tariff":"","ff":"default","pending":-1,"pending_b64":"","retakes":0,"chain_complete":False,"last_closed":-1,"report_text":"","details":{},"rechecks":0,"rc_photo":""}
    bot.send_message(m.chat.id,START_TEXT,reply_markup=kb_main())

@bot.message_handler(content_types=["photo"])
def photo(m): add_image(m)

@bot.message_handler(content_types=["document"],func=lambda m: m.document and (m.document.mime_type or "").startswith("image"))
def doc(m): add_image(m)

def add_image(m):
    cid=m.chat.id; s=st(cid)
    if s["stage"]=="name":
        bot.send_message(cid,"Сначала напишите название аромата.")
        return
    if s["stage"]=="box":
        bot.send_message(cid,"Сначала нажмите кнопку: «Есть коробка» или «Нет коробки».")
        return
    if s["stage"]=="tariffs":
        bot.send_message(cid,"Выберите тариф кнопками ниже. Если кнопки пропали — напишите «Начать заново».")
        return
    if s["stage"]=="feedback":
        bot.send_message(cid,"Отчёт выдан. Для новой проверки напишите «Начать заново».")
        return
    try:
        b64,comp,suspect=img_b64(m)
    except Exception:
        logging.exception("img_b64")
        bot.send_message(cid,"Не смог прочитать файл. Пришлите фото в JPG/PNG документом.")
        return
    
    # Первичный фильтр скриншотов и сжатых фото
    if suspect and not comp:
        bot.send_message(cid,"🔎 Проверяю качество фото…")
        try:
            screenshot_check=ask_qwen([b64],MODE_SCREENSHOT,QWEN_CHEAP,timeout=45,attempts=1)
            result=screenshot_check.strip().upper()
            if "SCREENSHOT" in result or "MESSENGER" in result:
                logging.info("SCREENSHOT_FILTER cid=%s result=%s",cid,result)
                bot.send_message(cid,SCREENSHOT_HELP)
                return
        except Exception:
            logging.exception("screenshot_check")
            # При ошибке модели пропускаем дальше
    
    if s["stage"]=="done":
        if s.get("rechecks",0)>=recheck_limit(s):
            bot.send_message(cid,"Отчёт выдан, лимит дополнительных проверок исчерпан. Для новой проверки напишите «Начать заново».")
            return
        s["rc_photo"]=b64
        s["stage"]="recheck"
        bot.send_message(cid,"📥 Фото получено. Какой пункт перепроверить? Напишите номер от 01 до 05.")
        return
    if comp and s["stage"] in ("chain","photos"):
        bot.send_message(cid,"📥 Принимаю фото ТОЛЬКО документом: Telegram сжимает обычные фото, и по ним разбор не оказывается — это правило точности. Отправьте, пожалуйста, документом:\n\n"+DOC_HELP)
        return
    with chat_lock(cid):
        process_image(cid,s,b64,comp)

def process_image(cid,s,b64,comp):
    if s["stage"]=="chain":
        s["pending"]=-1; s["pending_b64"]=""
        bot.send_message(cid,"📥 Загружаю фото…")
        cur=first_open(s)
        cur_hint=hint_for(s["queue"][cur],s.get("ff","default")) if cur>=0 else ""
        remaining="\n".join(f"{i+1}. {s['queue'][i]}" for i in range(len(s["queue"])) if i not in s["closed"])
        try:
            res=ask_qwen([b64],MODE0C.format(name=s["name"] or "?",current=f"{cur+1}. {s['queue'][cur]}. Каким должен быть кадр: {cur_hint}" if cur>=0 else "нет",remaining=remaining),QWEN_CHEAP,timeout=60,attempts=2)
        except Exception:
            logging.exception("mode0c")
            bot.send_message(cid,BUSY_TEXT)
            return
        if "не парфюмерия" in res.lower():
            bot.send_message(cid,"📥 Получено, но это не парфюмерия — я проверяю только её. Пришлите фото нужного продукта или напишите «Начать заново».")
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
                    if "батч" in s["queue"][n-1].lower():
                        s["photos"].append(b64)
                    bot.send_message(cid,f"📥 Шаг {n}: получено, но пока нечитаемо. {parse(res2,'СОВЕТ') or 'Снимите при дневном свете, без вспышки.'} Попробуйте ещё раз — у вас получится!{retake_extra(s)}{batch_note(s,n)}")
                    return
            else:
                prev=s.get("last_closed",-1)
                extra_ok=False
                if prev>=0:
                    try:
                        res3=ask_qwen([b64],MODE0C2.format(name=s["name"] or "?",step=s["queue"][prev],hint=hint_for(s["queue"][prev],s.get("ff","default"))),QWEN_CHEAP,timeout=45,attempts=1)
                    except Exception:
                        logging.exception("mode0c2prev")
                        res3=""
                    if res3 and parse(res3,"СОВПАДЕНИЕ").lower().startswith("да") and parse(res3,"ЧИТАЕМО").lower().startswith("да"):
                        s["photos"].append(b64)
                        bot.send_message(cid,f"📥 Дополнительный кадр к шагу {prev+1} принят.")
                        extra_ok=True
                if extra_ok:
                    return
                if res2 and parse(res2,"СОВПАДЕНИЕ").lower().startswith("нет") and not parse(res2,"ЧИТАЕМО").lower().startswith("да"):
                    if "батч" in s["queue"][cur].lower():
                        s["photos"].append(b64)
                    bot.send_message(cid,f"📥 Получено, но пока нечитаемо. {parse(res2,'СОВЕТ') or 'Снимите при дневном свете, без вспышки.'} Попробуйте ещё раз — у вас получится!{retake_extra(s)}{batch_note(s,cur+1)}")
                    return
                s["pending"]=cur; s["pending_b64"]=b64
                bot.send_message(cid,f"📥 Фото получено. Это кадр для шага «{s['queue'][cur]}»? Напишите «да» — приму его, или просто пришлите новый кадр по подсказке:\n{cur_hint}")
                return
        if n<1 or n>len(s["queue"]) or (n-1) in s["closed"]:
            bot.send_message(cid,"Этот кадр не подходит ни к одному из оставшихся шагов. Осталось:\n"+remaining)
            return
        if not readable:
            if "батч" in s["queue"][n-1].lower():
                s["photos"].append(b64)
            bot.send_message(cid,f"📥 Шаг {n}: получено, но пока нечитаемо. {parse(res,'СОВЕТ') or 'Снимите при дневном свете, без вспышки, камеру держите параллельно.'} Попробуйте ещё раз — у вас получится!{retake_extra(s)}{batch_note(s,n)}")
            return
        accept_step(cid,s,n,b64)
        return
    bot.send_message(cid,"📥 Загружаю фото…")
    try:
        res=ask_qwen([b64],MODE0I.format(name=s["name"] or "?"),QWEN_CHEAP,timeout=60,attempts=2)
    except Exception:
        logging.exception("mode0i")
        bot.send_message(cid,BUSY_TEXT)
        return
    if "не парфюмерия" in res.lower():
        bot.send_message(cid,"📥 Получено, но это не парфюмерия — я проверяю только её. Пришлите фото нужного продукта или напишите «Начать заново».")
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
    if t.lower()=="навыки бота":
        bot.send_message(cid,SKILLS_TEXT,reply_markup=types.ReplyKeyboardRemove())
        return
    if s["stage"]=="feedback":
        logging.warning("FEEDBACK DOWN %s: %s",cid,t)
        s["stage"]="done"
        bot.send_message(cid,"Спасибо! Обратная связь записана и будет учтена.")
        return
    if s["stage"]=="recheck":
        num="".join(ch for ch in t if ch.isdigit())
        n=("0"+num) if len(num)==1 else num
        if n not in ("01","02","03","04","05"):
            bot.send_message(cid,"Напишите номер пункта от 01 до 05.")
            return
        bot.send_message(cid,"🔁 Перепроверяю пункт "+n+"…")
        try:
            rc=ask_qwen([s["rc_photo"]],MODE_RC.format(name=s["name"] or "?",num=n,old=s.get("report_text","")),QWEN_MODEL,timeout=90,attempts=2)
        except Exception:
            logging.exception("mode_rc")
            bot.send_message(cid,BUSY_TEXT)
            return
        line=parse(rc,"СТАТУС")
        newst=next((e for e in ("❌","️","✅","➖") if e in line),"➖")
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
            msg+="\nЛимит дополнительных проверок исчерпан. Для новой проверки напишите «Начать заново»."
        bot.send_message(cid,msg)
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
            boxres="ФОРМ-ФАКТОР: флакон с распылителем\nНАЗВАНИЕ: "+t
        corrected=parse(boxres,"НАЗВАНИЕ") or t
        if corrected.lower()!=t.lower():
            s["name"]=corrected
            bot.send_message(cid,f"Принято: {corrected} (исправлено из «{t}»). Если неверно — напишите «Начать заново».")
        else:
            bot.send_message(cid,f"Принято: {t}.")
        s["ff"]=norm_ff(parse(boxres,"ФОРМ-ФАКТОР"))
        s["stage"]="box"
        kb=types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("📦 Есть коробка",callback_data="box_yes"),types.InlineKeyboardButton("🚫 Нет коробки",callback_data="box_no"))
        bot.send_message(cid,"Есть ли коробка у флакона?",reply_markup=kb)
        return
    if s["stage"]=="box":
        bot.send_message(cid,"Нажмите кнопку: «Есть коробка» или «Нет коробки».")
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
                s["last_closed"]=ni
            n2=first_open(s)
            if n2>=0:
                bot.send_message(cid,"⚠️ Пропускаю шаг. В отчёте эта деталь будет помечена «не проверяется».\n"+step_msg(s,n2))
            else:
                end_chain(cid)
            return
        if low in ("готово","done"):
            ni=first_open(s)
            if ni>=0:
                bot.send_message(cid,"Осталось собрать кадры:\n"+"\n".join(f"{i+1}. {s['queue'][i]}" for i in range(len(s['queue'])) if i not in s["closed"])+"\nПришлите фото или напишите «нет», если шага нет в вашем продукте.")
            else:
                end_chain(cid)
            return
        bot.send_message(cid,"Сейчас собираем кадры по шагам. Пришлите фото текущего шага (документом) или напишите «нет», если шага нет в вашем продукте.")
        return
    if s["stage"]=="photos":
        if t.lower() in ("готово","done"):
            audit(cid)
        elif t.lower() in ("не могу","нет","не получится"):
            s["cannot"]+=[x for x in (s["last_missing"] or []) if x not in s["cannot"]]
            s["last_missing"]=[]
            send_tariffs(cid)
        else:
            bot.send_message(cid,"Записал. Добавляйте фото документом или напишите «Готово».")
        return
    if s["stage"]=="tariffs":
        bot.send_message(cid,"Выберите тариф кнопками ниже. Если кнопки пропали — напишите «Начать заново».")
    elif s["stage"]=="done":
        bot.send_message(cid,"Отчёт выдан. Хотите перепроверить пункт — пришлите фото этого места документом. Для новой проверки напишите «Начать заново».")
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
        bot.send_message(cid,"⚠️ Сервис временно перегружен. Попробуйте ещё раз через минуту.")
        return
    def crit(n):
        for line in res.splitlines():
            t=line.strip().lower()
            if t.startswith(n+":") or t.startswith(n+" :"):
                return "нечитаемо" not in t
        return False
    def all_skipped(kws):
        rel=[q for q in s["queue"] if any(k in q.lower() for k in kws)]
        return bool(rel) and all(q in s["cannot"] for q in rel)
    ok01=crit("01") or all_skipped(["короб","этикетк"])
    ok02=crit("02") or all_skipped(["дно","завальц","трубочк","горлышк","ролик","спереди"])
    ok03=crit("03") or all_skipped(["батч"])
    if not (ok01 and ok02 and ok03):
        kb=types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔄 Начать заново",callback_data="restart"))
        bot.send_message(cid,"По имеющимся фото итог вынести невозможно: не хватает критических деталей (упаковка, флакон или маркировка). Услуга не оказывается, оплата не запрашивается. Добавьте читаемые фото или начните заново.",reply_markup=kb)
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

@bot.callback_query_handler(func=lambda c: c.data in ("std","exp","report","restart","close","fb_up","fb_down","skills","box_yes","box_no"))
def cb(c):
    cid=c.message.chat.id; s=st(cid)
    if c.data=="skills":
        bot.answer_callback_query(c.id)
        bot.send_message(cid,SKILLS_TEXT)
        return
    if c.data in ("box_yes","box_no"):
        bot.answer_callback_query(c.id)
        try: bot.edit_message_reply_markup(cid,c.message.message_id)
        except Exception: pass
        start_chain(cid,"да" if c.data=="box_yes" else "нет")
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
        tariff_note="\nТАРИФ ЭКСПРЕСС: дай максимально подробные обоснования: 2-3 предложения на деталь, процитируй все видимые признаки." if s["tariff"]=="Экспресс" else "\nТАРИФ СТАНДАРТ: обоснования 1-2 предложения на деталь."
        try:
            rep=ask_qwen(s["photos"],MODE2.format(name=s["name"] or "?")+note+tariff_note,QWEN_MODEL,timeout=150,attempts=2)
        except Exception:
            logging.exception("mode2")
            bot.send_message(cid,"⚠️ Сервис временно перегружен. Попробуйте ещё раз через минуту.")
            return
        rep=postprocess_verdict(rep)
        rep=re.sub(r"[➖\-−–—―]\s*не проверяется","➖ не проверяется",rep)
        s["report_text"]=rep
        s["details"]=parse_details(rep)
        s["rechecks"]=0
        for chunk in [rep[i:i+4000] for i in range(0,len(rep),4000)]:
            bot.send_message(cid,chunk)
        if s["tariff"]=="Экспресс":
            send_crops(cid,s)
        s["stage"]="done"
        kb=types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("👍 Полезно",callback_data="fb_up"),types.InlineKeyboardButton("👎 Не помогло",callback_data="fb_down"))
        kb.add(types.InlineKeyboardButton("🔄 Новая проверка",callback_data="restart"),types.InlineKeyboardButton("✅ Готово",callback_data="close"))
        bot.send_message(cid,"Отчёт готов. Оцените, был ли он полезен.",reply_markup=kb)

bot.infinity_polling(timeout=60)