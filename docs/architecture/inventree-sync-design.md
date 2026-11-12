# Архітектура inventree-sync: InvenTree → таблиці компонентів → Altium DbLib

Статус: Milestone 1A — основа й API-клієнт; Milestone 1B — scoped retrieval та `inspect`; Milestone 1C — динамічна схема, Altium-перетворення та unit-aware `PreparedTables`; Milestone 1D — SQLite writer, перевірка, безпечна публікація та робочі `validate`/`sync`.

Назва програми та console command — `inventree-sync`, назва Python-пакета — `inventree_sync`. Синхронізація одностороння: InvenTree є джерелом істини, згенерована база — відтворюваним проміжним артефактом для Altium DbLib. Скрипт читає InvenTree і не змінює його категорії або компоненти.

**SQLite — остаточно вибраний і єдиний підтримуваний backend. Microsoft Access більше не планується і не підтримується `inventree-sync`.** Шар `PreparedDataset → PreparedTables` залишається незалежним від SQL. `sqlite.py` використовує стандартний Python `sqlite3` без зовнішнього драйвера для генерації. Користувач підтвердив успішне підключення sample SQLite database до Altium DbLib через SQLite ODBC; перевірка нового згенерованого production snapshot в Altium залишається ручною інтеграційною перевіркою. Історію попереднього рішення коротко зафіксовано в розділі 10.

## 1. Контракт і джерела правил

Документи `docs/conventions/inventree-category-structure.md`, `docs/conventions/ipn-naming-convention.md` і `docs/conventions/library-convention.md` описують правила проєкту для людини, але не є джерелом структури компонентної бази під час експорту і не парсяться програмою.

InvenTree є єдиним джерелом істини для дерева категорій, Parts, IPN, фактичних параметрів Parts та метаданих параметрів. InvenTree сам відповідає за призначення параметрів категоріям та їх успадкування. `inventree-sync` не відтворює цю логіку і не зчитує category parameter assignments для побудови export schema.

Під час створення Part InvenTree додає до конкретного компонента параметри, що застосовуються до нього, у тому числі успадковані від категорій вищого рівня. Тому схема таблиці визначається за фактичними параметрами експортованих Parts. Скрипт не дублює структуру параметрів у конфігураційних або інших версіонованих файлах репозиторію.

Для Altium використовуємо саме `Altium Symbol = бібліотека:символ` і `Altium Footprint = бібліотека:посадкове_місце`. Старі назви `Symbol`/`Footprint` та значення без бібліотеки автоматично не підставляються. Переміщення моделі між файлами потребує оновлення відповідного параметра в InvenTree.

- Одна leaf-категорія, що містить хоча б один експортований InvenTree Part, → одна логічна таблиця компонентів. Порожні leaf-категорії ігноруються і таблиць не створюють.
- Назва таблиці точно дорівнює `category.name`, без aliases, префіксів і суфіксів.
- Один InvenTree Part → один рядок. Stock Item, Supplier Part і Manufacturer Part не створюють додаткових рядків.
- `Part.IPN` → колонка `IPN`, ключ і назва компонента у базі Altium. `Part.name` не використовується як заміна.
- Інші поля компонента беруться з фактичних параметрів конкретного Part. Виняток — чотири технічні колонки, обчислені з двох Altium-посилань.
- IPN не генерується заново і не розбирається для отримання Value, Package чи електричних характеристик.
- За замовчуванням експортуються всі Parts у вибраному дереві; фільтри active/template/virtual можливі лише явно в конфігурації, із кількістю виключених записів у звіті.
- Компонент без категорії або безпосередньо в non-leaf категорії — помилка перевірки області експорту. Його не розподіляємо довільно між дочірніми категоріями.

---

## 2. Структура програми

Пропонована структура всередині наявної папки `tools`:

```text
tools/inventree-sync/
├── pyproject.toml
├── config.example.toml
├── src/inventree_sync/
│   ├── __init__.py
│   ├── __main__.py        # виклик CLI
│   ├── cli.py             # inspect, validate, sync та console summaries
│   ├── config.py          # TOML, env, перевірка конфігурації
│   ├── api.py             # HTTP, auth, timeout, retry, pagination
│   ├── adapters.py        # особливості версій REST API
│   ├── models.py          # моделі InvenTree, ModelRef, ColumnDefinition, TableSchema, PreparedTables
│   ├── categories.py      # дерево, scope, листки, перевірка назв таблиць
│   ├── retrieval.py       # retrieve_dataset, PreparedDataset, спільні індекси
│   ├── schema.py          # build_table_schemas: union фактичних параметрів → логічні колонки
│   ├── transform.py       # parse_model_ref, LibraryLayout, prepare_tables
│   ├── validate.py        # логічна перевірка колонок, посилань і рядків
│   ├── sqlite.py          # TEXT schema, insert, verify, destination lock, atomic publish
│   ├── report.py          # майбутній JSON-звіт і маніфест
│   └── pipeline.py        # майбутня послідовність повного експорту
└── tests/
    ├── fixtures/          # знеособлені відповіді підтримуваних API
    ├── test_api.py
    ├── test_categories.py
    ├── test_retrieval.py
    ├── test_cli.py
    ├── test_schema.py
    ├── test_transform.py
    ├── test_validate.py
    └── test_sqlite.py     # round-trip, constraints, verification, publication failures
```

Залежності: Python 3.11+ (`tomllib`, `dataclasses`, `argparse`, `pathlib`, `logging`, `sqlite3`), `requests` для HTTP, `pytest` для тестування; версії зафіксовані в `pyproject.toml`. Генерація та unit-тести не потребують Altium або ODBC-драйвера. SQLite ODBC потрібен тільки споживачу Altium DbLib і налаштовується вручну.

Основні контракти функцій:

```python
class InvenTreeClient:
    def iter_categories(self): ...
    def iter_parts_with_parameters(self, category_pk: int): ...
    def iter_parts(self): ...                 # лише діагностика
    def iter_parameter_templates(self): ...   # лише діагностика
    def iter_part_parameters(self): ...       # лише діагностика

def retrieve_dataset(config_path) -> PreparedDataset: ...
def build_category_tree(categories): ...
def build_table_schemas(dataset: PreparedDataset) -> tuple[TableSchema, ...]: ...
def parse_model_ref(value: str, kind: ModelKind) -> ModelRef: ...
def resolve_model_path(ref: ModelRef, layout: LibraryLayout) -> str: ...

def format_parameter_value(data: str | None, units: str | None) -> str | None: ...
def prepare_tables(dataset: PreparedDataset, layout: LibraryLayout) -> PreparedTables: ...
def validate_table_name(category_name: str) -> None: ...
def validate_sqlite_tables(prepared: PreparedTables) -> None: ...
def write_sqlite_database(prepared: PreparedTables, destination: Path) -> None: ...
```

HTTP-відповіді нормалізує `adapters.py`; решта програми не залежить від конкретного JSON API. Внутрішні індекси: `categories[pk]`, `parts[pk]`, `templates[pk]`, `parameters[part_pk][template_pk]`.

## 3. Авторизація і REST API

Реалізований спосіб — токен зі змінної, заданої `inventree.token_env` (типово `INVENTREE_API_TOKEN`), заголовок `Authorization: Token <token>`. Запланована альтернатива HTTP Basic ще не реалізована; у майбутньому вона допускається лише через HTTPS із username і паролем через `getpass` або env. Не потрібні браузерний логін або збереження сесійних cookies. Токен, пароль і HTTP-заголовки не потрапляють у конфігурацію, Git або звіт. [Документація авторизації InvenTree](https://docs.inventree.org/en/latest/api/).

### 3.1. Основний шлях читання — InvenTree 1.5.6, API schema 530

Цільову версію та можливості API підтверджено у завданні Milestone 1B. Локальної OpenAPI-специфікації в робочому дереві немає; контракт звірено з upstream tag `1.5.6`. Поведінку category/cascade визначає [part/api.py](https://github.com/inventree/InvenTree/blob/1.5.6/src/backend/InvenTree/part/api.py), вкладені parameters — [part/serializers.py](https://github.com/inventree/InvenTree/blob/1.5.6/src/backend/InvenTree/part/serializers.py) і [common/filters.py](https://github.com/inventree/InvenTree/blob/1.5.6/src/backend/InvenTree/common/filters.py), а `template_detail` — [common/serializers.py](https://github.com/inventree/InvenTree/blob/1.5.6/src/backend/InvenTree/common/serializers.py). Читання живого сервера цим клієнтом ще не перевірене.

Основний шлях використовує лише:

| Дані | Endpoint / стратегія |
|---|---|
| Категорії | `GET /api/part/category/`, усі доступні категорії й сторінки |
| Parts, фактичні parameters і templates | `GET /api/part/?category=<root_pk>&cascade=true&parameters=true`, усі сторінки вибраного піддерева |

Спочатку завантажується повне доступне дерево, `scope.root_category_path` знаходить рівно один кореневий PK, після чого запит Parts передає `category=str(root_pk)`, `cascade="true"`, `parameters="true"`. PK має бути додатним цілим числом, а не bool. Основний шлях **не завантажує всі Parts бази для подальшого локального відсіювання**. Локальна перевірка кожного поверненого Part залишається обов'язковою: чужа категорія, non-leaf розміщення або відсутня категорія є помилкою.

Окремі bulk-запити `/api/parameter/` і `/api/parameter/template/` не потрібні, коли вкладена відповідь містить необхідні дані. Попередні методи Milestone 1A залишаються для явної діагностики чи майбутньої обґрунтованої сумісності. Автоматичного fallback, запитів на кожен Part/template або додаткового запиту версії в основному шляху немає. Непідтримувана структура відповіді завершує читання помилкою.

Усі списки читаються повністю з пагінацією: підтримуються `results/next` і непагінований масив, перевіряються повторення сторінок/PK та `count`, якщо він присутній. `next` дозволений лише для того самого origin та endpoint усередині базового API-шляху. Кожен із фільтрів `category`, `cascade`, `parameters` має залишатися рівно один раз із незмінним значенням на всіх сторінках; зникнення, зміна або дублювання фільтра — помилка. HTTP redirects не виконуються. Query parameters кодуються стандартними URL-засобами.

За `C` сторінок категорій і `P` сторінок Parts потрібно **C + P GET-запитів** без урахування повторів після тимчасових HTTP-помилок. Вкладені параметри й шаблони не збільшують цю кількість. Category parameter assignments та реконструкція успадкування не використовуються.

HTTP-політика: перевірка TLS увімкнена, connect/read timeout, обмежені повтори GET для 429 і тимчасових 5xx із Retry-After/backoff; 401/403 — негайна помилка, без перемикання способу авторизації. Відсутність доступу не трактувати як порожню категорію. Обліковий запис повинен бачити все вибране дерево: невидимих через права дочірніх категорій клієнт самостійно виявити не зможе.

### 3.2. Нормалізація й підготовлений набір даних

`adapters.part_with_parameters()` повертає `PartWithParameters`: `Part`, кортеж фактичних `Parameter` і кортеж отриманих `ParameterTemplate`. Властивість `pk` агрегату посилається на Part PK для наявної перевірки пагінації. Raw JSON залишається всередині API/adapter шару.

- `parameters` є обов'язковим списком; `[]` допустимий. Пропуск, null чи інший тип — помилка, без fallback.
- Для параметра потрібні додатні `pk`, `model_id`, `template`; `model_id` має дорівнювати PK батьківського Part. Якщо `model_type` присутній, він має дорівнювати `part.part`; для окремого діагностичного endpoint це поле обов'язкове.
- `data` є текстом або null; лише порожній рядок нормалізується до `None`. `data_numeric` не використовується.
- Кожний вкладений параметр повинен містити об'єкт `template_detail` з `pk`, текстовим `name` і текстовим `units` (порожній рядок допустимий). `template_detail.pk` дорівнює `template`. Підтримувані метадані — PK/name/units; довільні додаткові поля не копіюються у внутрішні моделі.
- Повтор параметра за PK або повтор template на одному Part — помилка. Спільний template PK між різними Parts допустимий лише за однакових name/units; конфлікт завершує читання з контекстом обох Parts і template PK.

`retrieval.retrieve_dataset(config_path)` завантажує конфігурацію, відкриває клієнт, читає категорії, визначає root PK, читає scoped Parts, створює спільні індекси й викликає наявний `group_parts`. Повертається `PreparedDataset` із деревом, root PK, множиною PK піддерева, `parts[pk]`, `parameters[part_pk][template_pk]`, `templates[pk]` та групами непорожніх leaf-категорій. Індекси доступні лише для читання. Частковий набір при помилці не повертається; клієнт закривається і при успіху, і при помилці. Генерації колонок, SQLite-запису та Altium-перетворень тут немає.

## 4. Категорії та таблиці компонентів

Leaf-категорія визначається відсутністю дочірніх вузлів у повному доступному дереві InvenTree, а не рівнем вкладеності, назвою категорії чи кількістю Parts.

Дерево категорій потрібне для визначення export scope, leaf/non-leaf стану, групування Parts, побудови діагностичного full path і перевірки коректності розміщення Parts. Воно не використовується для відтворення успадкування параметрів.

Порожні leaf-категорії не експортуються. Якщо leaf-категорія не містить жодного Part, який проходить поточні export-фільтри, `inventree-sync` не створює для неї таблицю і не намагається визначити її параметри через category assignments.

Назва кожної логічної таблиці точно дорівнює фактичному `category.name`, отриманому з InvenTree. Поточні назви категорій можуть бути задокументовані окремо для людини, але документація не підміняє серверні дані і не бере участі у побудові схеми.

Правила проєкту для назв експортованих категорій:

- Англійські літери, цифри й одиночні внутрішні пробіли. Формальна перевірка: `[A-Za-z][A-Za-z0-9]*(?: [A-Za-z0-9]+)*`. Немає колишнього ліміту 64 символи.
- Без початкових/кінцевих пробілів, керувальних символів і пунктуації. Це конвенція читабельності, яка свідомо вужча за можливості SQLite.
- Назви експортованих leaf-категорій мають бути унікальні без урахування регістру, навіть якщо вони розташовані в різних гілках.
- Префікс `sqlite_` зарезервовано SQLite і явно відхиляється без урахування регістру. Колишні reserved words та префікси `MSys`/`USys` більше не обмежують таблиці; `Select`, `Value`, `GROUP BY` дозволені.
- Скрипт не скорочує, не транслітерує і не додає PK до назв таблиць. Порушення — помилка з category PK і повним шляхом; виправлення має відбутися в InvenTree до синхронізації.

Writer обрамляє ідентифікатори подвійними лапками й подвоює внутрішні лапки. SQL values передаються виключно через placeholders `?`; ідентифікатори не можуть бути SQL value parameters.

Після перейменування категорії в InvenTree наступна повна синхронізація створює таблицю з новою назвою; mapping відповідної таблиці в DbLib також потребує ручного оновлення. Попередня назва не зберігається як alias.

База містить тільки поточні компонентні таблиці. JSON manifest та audit report відкладені; Milestone 1D виводить console summary. Якщо в scope немає жодного Part у leaf-категоріях, синхронізація завершується помилкою конфігурації/даних.

---

## 5. Схема колонок із фактичних Part parameters

Логічна схема кожної таблиці формується **лише з фактичних параметрів експортованих Parts цієї leaf-категорії**. `schema.build_table_schemas(dataset)` використовує групи Milestone 1B і наявну `categories.validate_export_names`; не відтворює дерево чи успадкування. Перевірка індексів не дозволяє втратити Parts/параметри у вручну складеному некоректному наборі.

InvenTree під час створення Part додає до нього параметри, визначені його категорією, включно з успадкованими від категорій вищого рівня. Тому `inventree-sync` не відтворює механізм успадкування категорій і не використовує category parameter assignments для побудови таблиць.

Для кожної непорожньої експортованої leaf-категорії:

```text
усі експортовані Parts категорії
  → фактичні Part parameters кожного Part
  → union ParameterTemplate, на які вони посилаються
  → виключення точних імен KiCad Symbol, KiCad Footprint, Altium Symbol, Altium Footprint
  → логічні колонки
```

Порядок технічних колонок фіксований: `IPN`, `Library Ref`, `Library Path`, `Footprint Ref`, `Footprint Path`.

Після них ідуть параметри InvenTree **строго за зростанням PK `ParameterTemplate`**. Milestone 1C уточнює попередній дизайн: порядок із API більше не є альтернативою. Порядок Parts, параметрів і словників на вході не змінює порядок колонок.

Назви колонок параметрів залишаються точними іменами `ParameterTemplate` з InvenTree. Скрипт не перейменовує `Power Rating` у `Power`, `Mounting Type` у `Mount` тощо.

Якщо звичайний параметр присутній хоча б на одному експортованому Part у категорії, відповідна колонка входить до таблиці. Виняток — точні імена `KiCad Symbol`, `KiCad Footprint`, `Altium Symbol`, `Altium Footprint`: `schema.EXCLUDED_EXPORT_PARAMETERS` виключає їх до формування колонок. Це фіксований контракт експорту, не конфігурація категорій. Усі інші параметри залишаються динамічними. Якщо конкретний Part параметра не має, значення для його рядка — Python `None`; SQLite writer перетворює його на SQL NULL. Порожній рядок необов'язкового параметра також стає `None`; самі пробіли зберігаються дослівно навіть за наявності units. Форматування непорожніх значень описане нижче.

Порожня leaf-категорія не створює таблиці і не потребує визначення schema.

Один і той самий `ParameterTemplate` дає одну колонку. Дубль параметра того самого template на одному Part, два різні templates з однаковим ім'ям без урахування регістру або колізія імені параметра з технічною колонкою — помилка, без перезаписування значень.

Контракт імен полів: непорожній текст без початкових пробілів і керувальних символів (U+0000–001F, U+007F–009F). Конвенція назв **категорій** на поля не переноситься. Unicode, внутрішні пробіли, reserved words і пунктуація включно з подвійними лапками підтримуються. Ліміт 64 символи та заборони пунктуації попереднього backend скасовані. Колізії перевіряються через `casefold`. Quoting ідентифікаторів належить writer. Milestone 1C не застосовує storage limits; 1D перевіряє сумісність із фактично встановленим SQLite engine у пам'яті.

Кожне посилання на template має існувати у спільному індексі; PK ключа/об'єкта повинні збігатися, а параметр має належати відповідному Part. Ці перевірки виконуються до виключення CAD-параметрів і охоплюють також їх. Усі значення — `str | None`. Виключені параметри та їхні templates залишаються доступними у вихідному `PreparedDataset`.

Значення завжди береться з фактичного параметра конкретного Part. Default шаблону не підставляється приховано.

На рівні контракту експорту обов'язкові лише `Part.IPN`, `Altium Symbol` і `Altium Footprint`. `inventree-sync` не намагається повторно реалізувати required-логіку category assignments InvenTree для інших параметрів.

Одиниці та choice lists залишаються метаданими InvenTree. Вони не дублюються в локальній конфігурації та не визначають набір колонок. Наявні `ParameterTemplate.units` використовуються лише шаром перетворення для остаточного тексту звичайних параметрів у `PreparedTables`.

### 5.1. Текстові значення та одиниці у PreparedTables

Уточнення Milestone 1C навмисно змінює попередній контракт дослівного експорту `Parameter.data`. `PreparedDataset` залишається незмінним і містить вихідні дані після нормалізації adapter; `PreparedTables` містить остаточне форматоване представлення. Нових API-запитів немає. `transform.format_parameter_value(data, units)` читає лише текстове `Parameter.data` та `ParameterTemplate.units`, ніколи `data_numeric`.

- `None` і `""` дають `None`; відсутній optional parameter також дає `None`. Самі пробіли зберігаються за попередньою політикою.
- Без units (`None` або `""`) непорожнє значення зберігається дослівно. Пробільні units або units з крайовими пробілами для непорожнього scalar — помилка метаданих, без обрізання.
- Якщо фізичної одиниці немає, до початкового тексту додається один пробіл і точний запис units із InvenTree: `10k` + `ohm` → `10k ohm`, `100n` + `F` → `100n F`, `0.125` + `W` → `0.125 W`. Початкові пробіли самого data не видаляються.
- Наявний сумісний суфікс зберігається без дублювання: `10k ohm`, `10kΩ`, `10 kΩ`, `100nF`, `0.125 W`, `1%`. `ohm`, `Ω` та `Ω` вважаються еквівалентними тільки для розпізнавання; вихідне написання не замінюється.
- Розпізнаються scalar-значення зі знаком, десятковою крапкою або комою та експонентою `e`/`E`; числового перетворення немає. Підтримані case-sensitive суфікси: `ohm`, `Ω`, `Ω`, `V`, `A`, `F`, `H`, `W`, `Hz`, `s`, `m`, `g`, `K`, `°C`, `%`. Перед ними можливий один SI-префікс: `q r y z a f p n u µ μ m c d da h k M G T P E Z Y R Q`; пробіли між magnitude, prefix і unit допустимі. Сумісні одиниці з різними префіксами зберігаються як є (`10mV` + `V` → `10mV`), без перерахунку.
- Точний довільний суфікс із metadata також підтримується, з optional SI-префіксом (наприклад `rpm`, `krpm`, `m/s`). Це не загальний парсер фізичних величин: немає аналізу розмірностей довільних compound units, діапазонів або текстових виразів.
- Голий SI-префікс означає відсутність одиниці (`10k`, `100n`, `4.7u`). Виняток — `m`: коли це не сумісна одиниця довжини, він неоднозначний між milli і metre та дає помилку. Невідомий суфікс/вираз з units також дає помилку замість припущення. Без units довільний текст залишається дозволеним.
- Очевидний конфлікт, наприклад `10 V` при units=`ohm`, завершується `ExportValidationError` із Part PK/IPN, template PK/name, початковим data, units та причиною. Немає часткового результату або виправлення джерела.

Форматування застосовується лише до звичайних динамічних колонок, не до IPN, чотирьох технічних полів моделі чи CAD source parameters. Десяткові роздільники, префікси та написання наявних одиниць не нормалізуються.

Окрім виключення CAD-колонок і форматування одиниць, спеціальний контракт формування DbLib-запису — `Part.IPN` та source parameters `Altium Symbol` і `Altium Footprint`. Їх спеціальна семантика описана в наступному розділі.

---

## 6. Посилання на моделі та DbLib mapping

Приклади вхідних значень:

```text
Altium Symbol    = Passives:Resistor
Altium Footprint = Resistors:RES_0603_H0.55
```

Дозволити також явні розширення: `Passives.SchLib:Resistor` та `Resistors.PcbLib:RES_0603_H0.55`. Парсер вимагає рівно одну двокрапку та дві непорожні частини. Частина бібліотеки — basename без директорій; неправильне розширення, додаткова двокрапка чи шлях — помилка. Для назв застосовуються правила `library-convention.md`; двокрапка є роздільником, а не частиною назви. Windows drive path не є допустимим вхідним значенням.

`parse_model_ref(value, kind)` підтримує `symbol` і `footprint` та повертає незмінний `ModelRef(kind, library_filename, model_name)`. Розширення дописується тільки коли воно відсутнє; явне розширення має бути точно `.SchLib` або `.PcbLib`. Пробіли не обрізаються, регістр і назва моделі не виправляються. Basename — PascalCase/акронім із можливими `_Qualifier`; символ — слова з великими початковими літерами/акроніми та числові кваліфікатори через `_` (однолітерні `R`, `C`, `L` відхиляються); footprint — великі ASCII-літери, цифри, `_`, десяткові крапки й дефіси між непорожніми частинами. Переліків дозволених сімейств немає: IC, connector і manufacturer-specific моделі підтримуються. Семантика електричної функції, механічних розмірів і варіантів не визначається з імені.

При розташуванні `database/Components.DbLib` і `database/components.sqlite`:

| Поле SQLite | Приклад | Mapping у DbLib |
|---|---|---|
| IPN | RES-10K-1%-0603 | ключ запису; параметр IPN |
| Library Ref | Resistor | [Library Ref] |
| Library Path | ..\symbols\Passives.SchLib | [Library Path] |
| Footprint Ref | RES_0603_H0.55 | [Footprint Ref] |
| Footprint Path | ..\footprints\Resistors.PcbLib | [Footprint Path] |
| Value | 10k | Value |
| Package | 0603 | Package |
| Mounting Type | SMD | Mounting Type |
| Resistance | 10 kΩ | Resistance |
| Tolerance | 1% | Tolerance |
| Power Rating | 0.1 W | Power Rating |

`IPN` — ідентифікатор запису бази, `Library Ref` — назва спільного символу. Вони не повинні збігатися. `Altium Symbol` і `Altium Footprint` є лише джерелами чотирьох технічних полів і не експортуються як окремі колонки. `KiCad Symbol` і `KiCad Footprint` ігноруються Altium-перетворенням.

`Comment` або `Description` експортуються лише за наявності однойменних звичайних параметрів Part. Скрипт не генерує `Comment` з `Value`, `Part.name`, `Part.description` або IPN. Перевірений користувачем підхід використовує Comment string символу `=Value`, що посилається на звичайний database parameter `Value`. Скрипт не змінює `.SchLib` для цього налаштування.

Відносні шляхи обчислювати від папки цільового DbLib, не від робочої директорії процесу. Перевіряти існування файлів бібліотек. Перевірка наявності самого символу/footprint усередині бінарної бібліотеки потребує окремого Altium-індексу чи спеціалізованого парсера; перевірка файлу не доводить наявність моделі.

Milestone 1C приймає `LibraryLayout(dblib_path, symbols_dir, footprints_dir)`: три абсолютні native `pathlib.Path`, прив'язані викликаючим кодом до явно вибраної базової директорії. Відносні шляхи об'єкта відхиляються; залежності від поточного working directory немає. Цільовий DbLib та його папка можуть ще не існувати. Для кожної використаної бібліотеки перевіряється `is_file()`; перевірка кешується в межах виклику, файл не читається й не змінюється. Вихідні відносні шляхи завжди мають Windows-роздільники `\`, також при запуску на іншій ОС. Різні диски/UNC shares, між якими відносного шляху немає, дають явну помилку без fallback на абсолютний шлях.

Для кожного Part обов'язкові точні назви `Altium Symbol` і `Altium Footprint`, фактичні призначення та непорожні коректні значення. Null, порожній рядок і самі пробіли відхиляються. `Package`, IPN та опис не використовуються як заміна. `_required_ref()` знаходить source parameters безпосередньо через template PK у `dataset.parameters[part.pk]` і `dataset.templates`, незалежно від вихідної схеми. Декілька призначених templates з одним required-ім'ям на Part є неоднозначністю та помилкою. Оригінальні Altium-значення залишаються лише у `PreparedDataset`, а технічні поля використовують нормалізоване ім'я файлу; units source-параметрів тут не застосовуються.

Глобальна перевірка охоплює лише посилання експортованого набору. Повторне використання моделі тієї самої бібліотеки дозволене; одна назва моделі в різних бібліотеках — помилка з контекстом обох Parts. Symbol і footprint мають окремі простори назв. Порівняння імен і бібліотек не враховує регістр для Windows/Altium; вихідні значення не змінюються. Повного сканування невикористаних бібліотек немає.

### 6.1. Публічний API і PreparedTables — межа Milestone 1C

`prepare_tables(dataset, layout)` спочатку будує всі схеми з виключенням чотирьох CAD-колонок, потім розв'язує обов'язкові source parameters, формує технічні поля, форматує звичайні параметри з units і перевіряє повні рядки. Виклик не виконує HTTP-запитів, SQL чи запису файлів. Єдина взаємодія з файловою системою — read-only перевірка бібліотек. Вхідний `PreparedDataset` не змінюється. При помилці повернення часткового результату немає.

- `ColumnDefinition(name, template_pk)` описує логічну колонку; `template_pk=None` позначає технічну колонку. SQL-типів у моделі немає.
- `TableSchema(category_pk, name, category_path, columns)` — самостійний результат `build_table_schemas` для аналізу схеми.
- `PreparedTable(category_pk, name, category_path, columns, rows)` містить повний шлях категорії, впорядковані колонки та один рядок на Part.
- `PreparedTables(tables)` містить кортеж таблиць за category PK. Динамічні колонки впорядковані за template PK, рядки — за Part PK. Dataclasses frozen, колекції — кортежі, рядки — `MappingProxyType[str, str | None]`.
- `ExportValidationError` — спільний тип помилок; `SchemaError` і `ModelReferenceError` уточнюють причину. Повідомлення включають доступний контекст Part/IPN, категорії/шляху, template/назви, reference або файлу.

Приклад для Python/debugger (шляхи `config_path`, `target_dblib`, `symbol_directory`, `footprint_directory` задає викликаючий код; останні три — абсолютні `Path`):

```python
from inventree_sync.retrieval import retrieve_dataset
from inventree_sync.schema import build_table_schemas
from inventree_sync.transform import LibraryLayout, prepare_tables

dataset = retrieve_dataset(config_path)  # HTTP тільки на етапі Milestone 1B
layout = LibraryLayout(target_dblib, symbol_directory, footprint_directory)
schemas = build_table_schemas(dataset)  # необов'язково, для аналізу колонок
prepared = prepare_tables(dataset, layout)
table = prepared.tables[0]
print(table.name, table.category_path)
print([column.name for column in table.columns])
print(dict(table.rows[0]))  # зручний breakpoint для перегляду результату
```

`inspect` зберігає поведінку Milestone 1B і не викликає `prepare_tables`. Milestone 1D додає файлові налаштування для `validate`/`sync` і реалізує SQLite writer нижче. Підготовлені таблиці залишаються окремим public Python API.

## 7. SQLite writer і безпечна публікація

`sqlite.write_sqlite_database(prepared, destination)` приймає лише готові `PreparedTables`. Він не виконує HTTP, не реконструює успадкування, не форматує units, не розбирає model refs повторно і не змінює `.DbLib`, `.SchLib` або `.PcbLib`.

### 7.1. Схема та перевірка public boundary

Одна непорожня `PreparedTable` → одна таблиця з точною назвою та впорядкованими колонками. Порожній export/table, дубль category PK, case-insensitive колізія table/column names, неправильні technical columns, CAD source columns, некоректний template PK або malformed row — `ExportValidationError`. Використовуються спільні `validate_columns`, `validate_row` та `validate_table_name`; row keys мають точно відповідати порядку колонок. Технічні значення непорожні, всі non-null values — рядки. IPN глобально унікальні через `casefold`, як у retrieval; написання зберігається.

| Колонка | SQLite декларація |
|---|---|
| IPN | `TEXT NOT NULL PRIMARY KEY COLLATE NOCASE` |
| Library Ref, Library Path, Footprint Ref, Footprint Path | `TEXT NOT NULL` |
| Звичайні динамічні параметри | `TEXT`, nullable |

SQLite `NOCASE` забезпечує ASCII case-insensitive PK; Python global `casefold` перевірка додатково зберігає попередній контракт для всього набору. Додаткові identifiers/лічильники, поля, triggers або user tables не створюються. SQLite автоматично створює службовий PK index; це не компонентна таблиця.

`quote_identifier()` перевіряє ім'я й подвоює внутрішні подвійні лапки. SQL values завжди передаються через `?` та `executemany`. Усі підготовлені рядки, включно з `0603`, `1E3`, `=Value`, апострофами, Unicode, довгим текстом та unit-aware значеннями, записуються без перетворення. Python `None` → SQL NULL. Порядок insertion відповідає `PreparedTables`, але reading має явно використовувати `ORDER BY "IPN"`.

`validate_sqlite_tables(prepared)` спочатку перевіряє логічні invariants, потім створює реальну схему, вставляє й перевіряє всі рядки у `:memory:`. Немає filesystem artifacts або output-directory creation. Це також виявляє schema/size limits встановленого SQLite engine (наприклад кількість колонок), без локально вигаданих limits. Помилки сумісності — data validation error, а не truncation.

### 7.2. Staging, verification та replacement

1. Повністю перевірити export у пам'яті. За потреби створити директорію результату.
2. Ексклюзивно створити `<destination>.sync.lock` через стандартний `os.open(O_CREAT | O_EXCL)` і записати PID. Одночасні writer calls до того самого resolved destination відхиляються.
3. Створити у цій самій директорії унікальний `.<destination>.<random>.staging.sqlite` через `tempfile.mkstemp`. Інші staging files не зачіпаються.
4. Відкрити SQLite, установити `journal_mode=DELETE` і `synchronous=FULL`. Явна transaction охоплює DDL та INSERT; commit або rollback, потім закриття connection. WAL не використовується.
5. Повторно відкрити staging через escaped file URI з `mode=ro`. Вимагати `PRAGMA integrity_check` = `ok` і DELETE journal mode.
6. Перевірити точний набір schema objects/table names; ordered columns через `table_xinfo`, TEXT types, nullability, default/PK/hidden flags; єдиний PK index та його NOCASE collation через `index_list`/`index_xinfo`.
7. Явно вибрати всі ordered columns з `ORDER BY "IPN"`. Порівняти count, кожний IPN та кожне значення/NULL з `PreparedTables`. Expected ordering відтворює SQLite ASCII NOCASE; числової конверсії немає.
8. Закрити verification connection. Виконати `os.replace(staging, destination)` на тому самому filesystem. Це єдина зміна published database.
9. Видалити лише власні staging/journal artifacts і власний lock. Ідентичність lock перевіряється перед видаленням; чужий replacement lock не видаляється.

Помилки creation/insertion/commit/verification/replacement не змінюють попередній published file. Якщо Windows/Altium/інший процес блокує replacement, повертається зрозуміла помилка з destination; нікого не закриваємо примусово й не видаляємо чужі journal/lock files. Якщо після успішної публікації не вдалося прибрати власний lock, помилка прямо вказує, що файл уже опубліковано, але cleanup не завершено.

Кожен успішний sync — повна перебудова: видалені/переміщені Parts, видалені параметри, порожні категорії та старі назви таблиць не залишаються у новому snapshot. Ручні зміни вихідної бази не зберігаються.

### 7.3. Відновлення після помилки

При data validation error виправити InvenTree або конфігурацію й повторити `validate`, потім `sync`. Попередня база зберігається. При publication error закрити споживача бази звичайним способом і повторити sync.

Lock не знімається автоматично за віком або PID: це може бути активний чи перерваний процес. Для stale `<destination>.sync.lock` перевірити записаний PID та переконатися, що жоден sync до цього destination не працює, зокрема в іншій сесії. Лише тоді вручну видалити цей lock. Після аварійного завершення можуть залишитися унікальні staging files; після тієї самої перевірки прибрати лише підтверджені abandoned staging artifacts, ніколи published database або SQLite journal іншого застосунку. Відновлення staging не виконується; наступний sync будує новий snapshot.

## 8. Конфігурація, CLI та Altium

Вміст `tools/inventree-sync/config.example.toml`:

```toml
[inventree]
base_url = "https://inventree.example.com"
auth = "token"
token_env = "INVENTREE_API_TOKEN"
connect_timeout = 10
read_timeout = 60
retries = 3

[scope]
root_category_path = ["Electronic Components"]

[sync]
output = "../../database/components.sqlite"
dblib = "../../database/Components.DbLib"

[libraries]
symbols = "../../symbols"
footprints = "../../footprints"
```

Усі filesystem paths прив'язуються до директорії TOML через `pathlib.Path.resolve()`, а не до cwd, Python або модуля CLI. Абсолютні шляхи також допустимі. SQLite output незалежний від DbLib; DbLib і його папка можуть ще не існувати. Output не може збігатися з конфігурацією/DbLib або мати розширення Altium library. `sync` за потреби створює output directory, `validate` її не створює.

`inspect` приймає попередню конфігурацію лише з `[inventree]` і `[scope]`. Для `validate`/`sync` обов'язкові обидві секції `[sync]` та `[libraries]` з усіма ключами. Невідомі sections/settings відхиляються без виведення їхніх значень. Немає backend selector, driver, DSN, database credentials або category/parameter/unit profiles у конфігурації. SQLite ODBC connection налаштовується окремо у споживача.

Із кореня репозиторію у PowerShell (копіювати config лише за його відсутності):

```powershell
if (-not (Test-Path -LiteralPath ./tools/inventree-sync/.venv)) {
    python -m venv tools/inventree-sync/.venv
}
& ./tools/inventree-sync/.venv/Scripts/python.exe -m pip install -e ./tools/inventree-sync
if (-not (Test-Path -LiteralPath ./tools/inventree-sync/config.toml)) {
    Copy-Item ./tools/inventree-sync/config.example.toml ./tools/inventree-sync/config.toml
}
& ./tools/inventree-sync/.venv/Scripts/inventree-sync.exe inspect --config ./tools/inventree-sync/config.toml
& ./tools/inventree-sync/.venv/Scripts/inventree-sync.exe validate --config ./tools/inventree-sync/config.toml
& ./tools/inventree-sync/.venv/Scripts/inventree-sync.exe sync --config ./tools/inventree-sync/config.toml
```

У локальному TOML вказати server URL без `/api/` і scope path. Для старого config додати `[sync]`/`[libraries]` за прикладом, не перезаписуючи локальні settings. Токен надходить зі змінної `INVENTREE_API_TOKEN` або іншої, заданої `token_env`. Його можна безпечно ввести через Python `getpass` і передати дочірньому процесу в env; не вставляти token literal в command history, TOML або Git. Програма сама не читає `.env`: якщо він використовується, завантаження env виконує середовище запуску. `python -m inventree_sync <command> --config ...` еквівалентний console command.

- `inspect`: тільки попереднє scoped retrieval та структурна перевірка, summary root/category/Parts/parameter/template counts. Не виконує Altium-перетворення або SQLite generation.
- `validate`: завантаження повної конфігурації, незмінний retrieval API, `prepare_tables`, library-file existence/model-ref checks та реальна in-memory SQLite schema/insertion/verification. Summary містить root, table/component/library counts, SQLite/reference status. Немає filesystem output, lock або published database changes. Binary models не перевіряються.
- `sync`: ті самі source/transformation checks, повна SQLite validation, staging, reopen verification і atomic publish. Summary містить destination, table/component counts, integrity/publication status.

Коди завершення: `0` успіх; `1` неочікувана внутрішня помилка; `2` configuration/data validation; `3` API/authentication; `4` database/filesystem/locking/publication. Відсутній API token, як і раніше, є configuration error (`2`). `DatabaseError` відокремлений від `ExportValidationError`. Secrets, Authorization headers і raw payloads не виводяться; unexpected exceptions мають безпечне generic повідомлення.

### 8.1. Перегляд і підключення до Altium

Після успішного sync відкрити `components.sqlite` у DB Browser for SQLite або SQLiteStudio. Перевірити список компонентних таблиць, структуру TEXT полів та Browse Data; для стабільного читання використовувати `SELECT ... ORDER BY "IPN"`. Не зберігати ручні виправлення як джерело даних: наступний snapshot їх замінить. Закрити viewer перед публікацією на Windows, якщо він утримує файл.

У Altium повторно використати SQLite ODBC driver/DSN або connection string, з яким користувач уже перевірив sample DbLib; шлях бази змінити на абсолютний шлях `sync.output`. Драйвер має відповідати розрядності Altium. У Database Library вибрати це connection, увімкнути поточні непорожні таблиці й призначити `IPN` ключем. Налаштувати наведений у розділі 6 mapping `Library Ref`, `Library Path`, `Footprint Ref`, `Footprint Path`; квадратні дужки у mapping позначають спеціальні цілі Altium, не SQL quoting і не частину database column names.

`Value` залишити звичайним database parameter; Comment string символу `=Value` налаштовується вручну у Altium, якщо ще не заданий. Не створювати synthetic database `Comment`. Явний InvenTree `Comment` залишається звичайним параметром. Перевірити пошук IPN, placement символу, Comment і передачу footprint на PCB. Після перейменування категорії оновити table mapping DbLib вручну. Скрипт не створює і не редагує DbLib, libraries або binary models.

## 9. Послідовність і контроль якості

```text
config + runtime token
  → повне дерево категорій → root PK
  → Parts?category=<root_pk>&cascade=true&parameters=true (всі сторінки)
  → PreparedDataset [1B, inspect]
  → union фактичних параметрів → CAD exclusions
  → Altium technical fields + unit-aware ordinary values
  → PreparedTables [1C]
  → SQLite schema/data validation у пам'яті [validate]
  → exclusive destination lock → unique staging у destination directory
  → DELETE journal + transaction → commit → close
  → read-only reopen → integrity/schema/constraints/complete data verification
  → close → os.replace → cleanup [1D, sync]
  → components.sqlite → SQLite ODBC → Altium DbLib
```

Unit-тести не використовують live server, credentials, Altium або ODBC. Вони перевіряють 1A/1B pagination/auth/API contracts, 1C union/CAD/model/unit rules, 1D exact TEXT/NULL/Unicode round-trip, quoted/reserved/long identifiers, global IPN collisions, malformed direct inputs, actual SQLite constraints, повні snapshots, corruption та creation/insertion/commit/verification/replacement failures, exclusive locks, cleanup ownership і CLI exit codes. End-to-end CLI тести підміняють лише HTTP transport і створюють справжню тимчасову SQLite базу. `validate` перевіряється на відсутність filesystem changes, включно з наявним destination.

Ціль InvenTree лишається 1.5.6 / API schema 530; retrieval strategy, request count і нормалізація не змінюються. Багатосторінковий REST не гарантує транзакційний source snapshot: для узгодженого production release потрібне вікно без редагувань або server snapshot. Unit-тести не доводять наявність моделей усередині binary libraries або production ODBC/Altium compatibility. Detailed JSON manifest, audit history, binary library indexing та автоматизація DbLib mapping залишаються поза Milestone 1D.

## 10. Історичне рішення — superseded

До Milestone 1C розглядався Microsoft Access із шаблоном порожньої бази; 1C повторно відкрив вибір Access/SQLite. Milestone 1D остаточно обрав SQLite після підтвердженого користувачем ODBC sample test. Попередній Access writer не був реалізований; його інструкції не є чинним планом. Історичні repository artifacts не видаляються як частина цього milestone, але вони не потрібні SQLite pipeline. Active architecture не має альтернативного backend або Access-specific setup.
