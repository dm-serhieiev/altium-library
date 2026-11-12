# Архітектура inventree-sync: InvenTree → таблиці компонентів → Altium DbLib

Статус: Milestone 1A реалізував основу й API-клієнт; Milestone 1B — читання вибраного піддерева та команду `inspect`; Milestone 1C — динамічні логічні схеми, Altium-перетворення й перевірені таблиці в пам'яті. Запис бази даних і налаштування DbLib залишаються наступними етапами.

Назва програми та console command — `inventree-sync`, назва Python-пакета — `inventree_sync`. Синхронізація одностороння: InvenTree є джерелом істини, згенерована база — відтворюваним проміжним артефактом для Altium DbLib. Скрипт читає InvenTree і не змінює його категорії або компоненти.

Історичний вибір Microsoft Access `.accdb` і проєкт його безпечного запису збережено нижче. Завдання Milestone 1C повторно відкриває вибір **Access або SQLite**: шар `PreparedDataset → PreparedTables` незалежний від backend. SQL, типи й ліміти сховища, драйвери та публікація належать майбутньому writer. Наявні конвенції назв таблиць і полів залишаються чинними для обох варіантів; рішення щодо SQLite writer або його сумісності з Altium ще не прийнято.

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
│   ├── cli.py             # inspect; validate/sync поки не реалізовані
│   ├── config.py          # TOML, env, перевірка конфігурації
│   ├── api.py             # HTTP, auth, timeout, retry, pagination
│   ├── adapters.py        # особливості версій REST API
│   ├── models.py          # моделі InvenTree, ModelRef, ColumnDefinition, TableSchema, PreparedTables
│   ├── categories.py      # дерево, scope, листки, перевірка назв таблиць
│   ├── retrieval.py       # retrieve_dataset, PreparedDataset, спільні індекси
│   ├── schema.py          # build_table_schemas: union фактичних параметрів → логічні колонки
│   ├── transform.py       # parse_model_ref, LibraryLayout, prepare_tables
│   ├── validate.py        # логічна перевірка колонок, посилань і рядків
│   ├── access.py          # запланований варіант Access writer; ще не реалізований
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
    └── test_sync.py       # майбутні тести запису/публікації
```

Залежності: Python 3.11+ (`tomllib`, `dataclasses`, `argparse`, `pathlib`, `logging`), `requests` для HTTP, `pytest` для тестування; поточні версії зафіксовані в `pyproject.toml`. Milestone 1C не додає залежностей і не імпортує `sqlite3` або `pyodbc`. У разі вибору Access його writer потребуватиме Windows, `pyodbc` і Microsoft Access Database Engine відповідної розрядності.

Для майбутнього запису Access із сучасним 64-бітним Altium обираємо 64-бітні Python та ACE; перед записом перевірятимемо драйвер `Microsoft Access Driver (*.mdb, *.accdb)`. Команда `inspect` не потребує `pyodbc`, ACE або Altium. Access Runtime включає ODBC/OLE DB-компоненти, але його сумісність із установленим Office потрібно перевірити перед установленням. [Microsoft Access Runtime](https://support.microsoft.com/en-us/access/download-and-install-microsoft-365-access-runtime), [розрядність рушія для Altium](https://www.altium.com/documentation/altium-designer/components-libraries/database-libraries/using-32-64-bit-altium-designer-same-computer).

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
# Заплановані контракти writer/pipeline:
def write_access_database(dataset, template, destination): ...
def sync(config) -> SyncReport: ...
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

`retrieval.retrieve_dataset(config_path)` завантажує конфігурацію, відкриває клієнт, читає категорії, визначає root PK, читає scoped Parts, створює спільні індекси й викликає наявний `group_parts`. Повертається `PreparedDataset` із деревом, root PK, множиною PK піддерева, `parts[pk]`, `parameters[part_pk][template_pk]`, `templates[pk]` та групами непорожніх leaf-категорій. Індекси доступні лише для читання. Частковий набір при помилці не повертається; клієнт закривається і при успіху, і при помилці. Генерації колонок, Access-запису та Altium-перетворень тут немає.

## 4. Категорії та таблиці компонентів

Leaf-категорія визначається відсутністю дочірніх вузлів у повному доступному дереві InvenTree, а не рівнем вкладеності, назвою категорії чи кількістю Parts.

Дерево категорій потрібне для визначення export scope, leaf/non-leaf стану, групування Parts, побудови діагностичного full path і перевірки коректності розміщення Parts. Воно не використовується для відтворення успадкування параметрів.

Порожні leaf-категорії не експортуються. Якщо leaf-категорія не містить жодного Part, який проходить поточні export-фільтри, `inventree-sync` не створює для неї таблицю і не намагається визначити її параметри через category assignments.

Назва кожної логічної таблиці точно дорівнює фактичному `category.name`, отриманому з InvenTree. Поточні назви категорій можуть бути задокументовані окремо для людини, але документація не підміняє серверні дані і не бере участі у побудові схеми.

Правила проєкту для назв експортованих категорій, сумісні з Access:

- Від 1 до 64 символів; англійські літери, цифри й одиночні внутрішні пробіли. Формальна перевірка: `[A-Za-z][A-Za-z0-9]*(?: [A-Za-z0-9]+)*` плюс перевірка довжини.
- Без початкових/кінцевих пробілів, керувальних символів і пунктуації. Це свідомо вужчий набір, ніж усі дозволені Access символи; він усуває неоднозначності SQL та драйверів.
- Назви експортованих leaf-категорій мають бути унікальні без урахування регістру, навіть якщо вони розташовані в різних гілках.
- Зарезервовані слова Access/ACE та системні префікси `MSys`/`USys` не використовуються для таблиць компонентів.
- Скрипт не скорочує, не транслітерує і не додає PK до назв таблиць. Порушення — помилка з category PK і повним шляхом; виправлення має відбутися в InvenTree до синхронізації.

Access дозволяє імена об'єктів до 64 символів і підтримує пробіли. Власні назви SQL завжди обрамляються квадратними дужками після валідації, наприклад `[Fixed Resistors]`. Дужки не є частиною назви таблиці. [Правила Microsoft для імен](https://support.microsoft.com/en-us/access/guidelines-for-naming-fields-controls-and-objects), [створення й найменування таблиць](https://support.microsoft.com/en-us/access/create-a-table-and-add-fields).

Маніфест зберігає category PK/full path/table name для кожної експортованої категорії. Після перейменування категорії в InvenTree наступна повна синхронізація створює таблицю з новою назвою; mapping відповідної таблиці в DbLib також потребує оновлення. Попередня назва не зберігається як alias.

Службові дані записуються в JSON поруч, без додаткових користувацьких таблиць. Системні таблиці Access не є таблицями компонентів. Якщо після застосування scope і export-фільтрів немає жодного Part у leaf-категоріях, синхронізація завершується помилкою конфігурації/даних.

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

Якщо звичайний параметр присутній хоча б на одному експортованому Part у категорії, відповідна колонка входить до таблиці. Виняток — точні імена `KiCad Symbol`, `KiCad Footprint`, `Altium Symbol`, `Altium Footprint`: `schema.EXCLUDED_EXPORT_PARAMETERS` виключає їх до формування колонок. Це фіксований контракт експорту, не конфігурація категорій. Усі інші параметри залишаються динамічними. Якщо конкретний Part параметра не має, значення для його рядка — Python `None`; майбутній writer перетворить його на SQL NULL. Порожній рядок необов'язкового параметра також стає `None`; самі пробіли зберігаються дослівно навіть за наявності units. Форматування непорожніх значень описане нижче.

Порожня leaf-категорія не створює таблиці і не потребує визначення schema.

Один і той самий `ParameterTemplate` дає одну колонку. Дубль параметра того самого template на одному Part, два різні templates з однаковим ім'ям без урахування регістру або колізія імені параметра з технічною колонкою — помилка, без перезаписування значень.

Контракт імен полів: непорожній текст до 64 символів, без початкових пробілів, ASCII-керувальних символів (0–31, 127), крапки, `!`, зворотного апострофа та квадратних дужок. Конвенція назв **категорій** на поля не переноситься. `Value`, `Description`, пробіли всередині назв і Unicode підтримуються; SQL reserved words не забороняються для полів. Quoting ідентифікаторів належить writer. Ліміти кількості колонок і довжини значень конкретної БД у Milestone 1C не застосовуються.

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

При розташуванні `database/Components.DbLib` і `database/components.accdb`:

| Поле Access | Приклад | Mapping у DbLib |
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

`Comment` або `Description`, якщо потрібні, беруться лише з однойменних параметрів Part, отриманих з InvenTree, і налаштовуються в mapping DbLib. Скрипт не вигадує їх із `Part.name`, `Part.description` або IPN. Mapping `Value` на Comment можна окремо налаштувати в DbLib як свідомий вибір.

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

`inspect` зберігає поведінку Milestone 1B і не викликає `prepare_tables`. Немає нової CLI-команди або нових TOML-параметрів. `validate`/`sync` залишаються явно нереалізованими до завершення writer та інтеграційних перевірок. Наступний етап має вибрати backend, відобразити логічні колонки на типи/ліміти сховища й реалізувати безпечний запис та перевірку результату.

У разі вибору Access збережений план DbLib такий: підключити `database/components.accdb` через сумісний Access OLE DB/ODBC-провайдер, увімкнути таблиці експортованих непорожніх leaf-категорій, призначити ключ `IPN` та наведені mappings. Назви таблиць не мають суфікса `$`. Поля Access не містять квадратних дужок у своїх назвах — у колонці mapping вони позначають спеціальні цілі Altium. `.accdb` є джерелом даних; `.DbLib` окремо містить підключення й mapping. [Офіційна документація Altium](https://www.altium.com/documentation/altium-designer/components-libraries/database-libraries/creating-defining).

## 7. Схема і надійний запис Microsoft Access

Це збережений проєкт **можливого Access backend**, а не поведінка Milestone 1C. Типи, SQL, ліміти сховища, транзакції та публікація нижче ще не реалізовані. Вибір Access/SQLite залишається відкритим; вимоги безпеки цього розділу застосовуються при реалізації Access writer.

Файл має формат `.accdb`. Для створення тимчасової бази копіювати заздалегідь підготовлений порожній Access-файл, заданий через `access.template`. Його потрібно один раз створити у Microsoft Access та зберегти як технічний шаблон без користувацьких таблиць, зв'язків, запитів і макросів. Нульовий файл із розширенням `.accdb` не є базою; ODBC-підключення не замінює її створення. Відсутній або некоректний шаблон — помилка preflight; шаблон не змінюється.

Підключення Python до тимчасової бази через `pyodbc`:

```text
DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=<absolute-path-to-staging.accdb>;
```

Рядок підключення будується з коректним ODBC-екрануванням значень. Шлях до бази не підставляється у SQL.

| Група полів | Тип Access | Правила |
|---|---|---|
| IPN | Short Text / `TEXT(255)` | NOT NULL, PRIMARY KEY; непорожній; унікальний також між таблицями |
| Library Ref, Library Path, Footprint Ref, Footprint Path | Short Text / `TEXT(255)` | обов'язкові непорожні значення; понад 255 символів — помилка |
| Звичайні параметри InvenTree, включно з Value та Package; без чотирьох CAD source parameters | Long Text / `LONGCHAR` | остаточний текст із PreparedTables або NULL; без числового перетворення й обрізання |

Long Text для параметрів дозволяє не підбирати типи за першими записами й не втрачати довгі описи. Для таких полів не створюються індекси. Сумісність читання Long Text конкретним DbLib-провайдером перевіряється інтеграційним тестом. Якщо в майбутньому для окремого технічного випадку знадобиться Short Text, це має бути явним налаштуванням формату експорту, а не локальним дублем метаданих параметра InvenTree.

Значення передаються як Python `str`, а відсутнє/порожнє необов'язкове значення — як `None` → SQL NULL. Writer зберігає вже форматовані рядки `PreparedTables` без змін і без додавання апострофів. `0603`, `1%`, `1E3` і `=...` без units лишаються текстом; одиниці додає лише шар перетворення за правилами розділу 5.1.

Основою є `data` параметра, а не числове `data_numeric`. Не конвертувати одиниці, десяткові роздільники чи префікси автоматично; відсутні одиниці додає transformation із метаданих ParameterTemplate, отриманих з InvenTree. Writer не форматує їх повторно. SQL NULL не замінювати на `0` або текстові `None`/`NaN`.

Назви полів — точні назви параметрів; вони перевіряються на обмеження Access, довжину до 64 символів і колізії без урахування регістру. Конвенція назв категорій не перейменовує поля параметрів. Неприпустимі назви — помилка, без автоматичних aliases. Імена таблиць/полів обрамляються `[...]`; значення передаються виключно через placeholders `?`:

```sql
INSERT INTO [Fixed Resistors] ([IPN], [Package], [Value]) VALUES (?, ?, ?)
```

Ідентифікатори не можна передати як SQL-параметри, тому їхня валідація обов'язкова перед побудовою DDL/DML. Заголовки є полями схеми; додатковий запис із назвами полів не створюється. Access не гарантує порядок записів: читати з `ORDER BY [IPN]`, якщо потрібен стабільний порядок.

Враховувати ліміти Access: максимум 255 полів у таблиці, 255 символів у Short Text і 2 GB на файл мінус системні об'єкти. Контролювати розмір бази та помилки місткості записів/рушія; жодне перевищення не призводить до обрізання або часткової публікації. [Специфікація Microsoft Access](https://support.microsoft.com/en-us/access/access-specifications).

Кожен запуск формує повний знімок: копіювати порожній шаблон у тимчасовий `.accdb` у директорії результату, створити схему, вставити дані з `autocommit=False`, виконати commit. При помилці — rollback записів і відхилення тимчасової бази; не покладатися на транзакційність DDL для захисту попереднього результату. Потім закрити з'єднання, повторно відкрити базу й перевірити точний набір користувацьких таблиць, типи полів, кількість записів, IPN та збережені значення.

Після перевірки закрити всі власні cursors/connections і атомарно замінити цільовий `.accdb` у тій самій файловій системі. Якщо Access/Altium утримує файл, завершитися з помилкою без видалення lock-файлів чи примусового закриття сторонніх процесів. Попередній файл зберігається. Паралельні запуски для одного destination забороняються власним блокуванням програми. Маніфест містить hash готового ACCDB для перевірки відповідності звіту.

Повна перебудова відображає видалення Parts, переміщення між категоріями та зміни схеми без застарілих записів. Вихідна база належить `inventree-sync`: ручні зміни в ній не є джерелом даних і будуть замінені наступною успішною синхронізацією.

## 8. Конфігурація та запуск

Нижче збережено приклад цільової конфігурації попереднього Access-дизайну. Реалізована команда `inspect` використовує лише `[inventree]` і `[scope]`, як у `tools/inventree-sync/config.example.toml`; файлові секції належать наступним етапам. Milestone 1C отримує шляхи через `LibraryLayout`, не розширюючи TOML:

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
# Синтаксис майбутнього режиму all ще не визначено; він не реалізований.

[sync]
output = "../../database/components.accdb"
dblib = "../../database/Components.DbLib"

[access]
template = "../../database/templates/empty.accdb"
driver = "Microsoft Access Driver (*.mdb, *.accdb)"

[libraries]
symbols = "../../symbols"
footprints = "../../footprints"
```

Усі майбутні файлові шляхи конфігурації будуть відносні до самого TOML. Кореневий шлях категорії має знаходити рівно один вузол; зараз підтримується лише цей режим. Режим усієї бази залишається відкладеним рішенням, зокрема його TOML-синтаксис і перевірка некатегоризованих Parts. У режимі піддерева summary явно показує межу читання. Порожні leaf-категорії завжди ігноруються і окремої опції для їх експорту немає. Конфігурація задає лише підключення, область синхронізації та технічні параметри експорту. Вона не містить списків категорій, параметрів, units, choices або успадкування.

CLI:

```text
inventree-sync inspect --config config.toml
inventree-sync validate --config config.toml
inventree-sync sync --config config.toml
# Еквівалентний виклик Python-пакета:
python -m inventree_sync inspect --config config.toml
```

`inspect` виконує повне читання і структурну перевірку Milestone 1B. При успіху виводить кореневу категорію/PK/шлях, кількість категорій у піддереві, Parts, експортованих leaf-категорій, фактичних параметрів і різних шаблонів, а також підтвердження вкладеного читання. Код `0` повертається тільки після завершення всіх сторінок і перевірок. Помилка конфігурації/даних → `2`; HTTP або непідтримувана структура API → `3`; неочікувана помилка → `1`. Secrets і raw responses не виводяться.

`validate` і `sync` поки явно повертають `not implemented` із ненульовим кодом. Їхній майбутній контракт: `validate` перевіряє драйвер, шаблон і весь набір без заміни ACCDB; `sync` додатково публікує базу. На рівні повного експорту обов'язкові `IPN`, `Altium Symbol` і `Altium Footprint`, але `inspect` поки не перевіряє Altium-посилання. Для інших параметрів не відтворюється required-логіка category assignments. Console command: `[project.scripts]`, `inventree-sync = "inventree_sync.cli:main"`.

### Ручний запуск inspect на сервері

У PowerShell із кореня репозиторію (середовище створюється лише за його відсутності):

```powershell
if (-not (Test-Path -LiteralPath ./tools/inventree-sync/.venv)) {
    python -m venv tools/inventree-sync/.venv
}
& ./tools/inventree-sync/.venv/Scripts/python.exe -m pip install -e ./tools/inventree-sync
if (-not (Test-Path -LiteralPath ./tools/inventree-sync/config.toml)) {
    Copy-Item ./tools/inventree-sync/config.example.toml ./tools/inventree-sync/config.toml
}
```

Копіювати приклад лише якщо локального `config.toml` ще немає. У ньому вказати реальні `base_url` сервера (без суфікса `/api/`) та `root_category_path`. Файл ігнорується Git. Якщо токен уже заданий у змінній середовища `INVENTREE_API_TOKEN`:

```powershell
& ./tools/inventree-sync/.venv/Scripts/inventree-sync.exe inspect --config ./tools/inventree-sync/config.toml
```

Альтернатива без токена в історії команд: приховано прочитати його через Python `getpass` і передати дочірньому процесу в env (для стандартного `token_env`):

```powershell
& ./tools/inventree-sync/.venv/Scripts/python.exe -c "import getpass, os, subprocess, sys; os.environ['INVENTREE_API_TOKEN'] = getpass.getpass('InvenTree token: '); sys.exit(subprocess.call([sys.executable, '-m', 'inventree_sync', 'inspect', '--config', 'tools/inventree-sync/config.toml']))"
```

Команда виконує лише GET. Вона не створює файлів ACCDB і не змінює `.DbLib` чи дані InvenTree.

## 9. Послідовність і контроль якості

```text
config + secrets
  → токен → повне доступне дерево категорій → визначення root PK
  → Parts?category=<root_pk>&cascade=true&parameters=true (всі сторінки)
  → нормалізація вкладених parameters/template_detail → спільні індекси
  → перевірка scope, leaf/non-leaf розміщення та унікальності IPN
  → ігнорування leaf-категорій без експортованих Parts
  → групування Parts за leaf-категоріями
  → PreparedDataset (межа Milestone 1B; inspect виводить summary)
  → union фактичних параметрів усіх Parts кожної категорії → виключення чотирьох CAD-колонок
  → перетворення source-only Altium refs і форматування звичайних параметрів з units
  → перевірка всього набору
  → PreparedTables (межа Milestone 1C; таблиці лише в пам'яті)
  → наступний етап: вибір backend і writer
  → у разі вибору Access, попередній план:
  → тимчасовий ACCDB → DDL + INSERT → commit → повторне читання
  → закриття з'єднань → заміна цільового ACCDB
  → JSON-звіт і маніфест
```

Помилки блокують публікацію всього файлу: пропущений/дубльований IPN (також колізія без урахування регістру для провайдера БД), дубль параметра, неправильне посилання, відсутня бібліотека, цикл/відсутній предок у дереві, невідповідна категорія, неповна пагінація чи збій HTTP. Стиль IPN перевіряється без автоматичного перейменування: історичні IPN та оригінальні ordering codes не переписуються за новими правилами.

JSON-звіт: час початку/кінця, версія програми та сервера/API, category PK/full path/table name, кількість отриманих і експортованих Parts, виключення, колонки та їх джерела в InvenTree, попередження/помилки із Part PK/IPN, hash результату. Жодних секретів. Багатозапитний REST-експорт не гарантує транзакційний snapshot: для узгодженого виробничого випуску потрібне вікно без редагувань або серверний snapshot. Часи збору фіксуються у звіті.

Коди завершення: `0` успіх, `1` неочікувана помилка, `2` конфігурація/дані, `3` API/авторизація, `4` файловий запис/блокування.

Тести реалізації:

1. Пагінація, 401/403, retry 429, непідтримувана схема, зовнішній/циклічний next.
2. Inductors як листок, порожня leaf-категорія не створює таблицю, точна рівність category.name/table.name для експортованих категорій, назви до 64 символів, відхилення пунктуації й зарезервованих слів, дублікати назв у різних гілках, новий дочірній вузол і Part у колишньому листку.
3. Union фактичних параметрів усіх Parts категорії, параметр лише у другому Part, відсутній параметр → NULL, новий фактичний Part parameter без змін репозиторію, дубль одного template на Part і конфлікт назв templates.
4. Обидва формати бібліотеки з/без розширення, неправильний delimiter, Package не підміняє Footprint, різні IPN зі спільним символом.
   Уточнення 1C: чотири CAD-параметри відсутні в схемі/рядках, але залишаються у джерелі; required refs працюють незалежно від схеми, KiCad values і CAD units не впливають на результат. Missing units додаються, явні еквівалентні одиниці не дублюються, конфлікт/неоднозначність має контекст; вихідний dataset незмінний, повторні перетворення еквівалентні.
5. Повторне читання ACCDB: `0603`, `%`, Unicode одиниць, апострофи і `=...` залишаються текстом; довгі значення не обрізаються; відсутнє значення є NULL; дубль IPN відхиляється; помилка або lock не змінює попередню базу.
6. Інтеграційна перевірка на Windows із конкретним InvenTree та Altium: ACE відповідної розрядності, видимість таблиць і Short/Long Text полів, пошук за IPN, розміщення символу та передача footprint на PCB. Перевірити два послідовні sync, видалення/переміщення Part, перейменування категорії і блокування файлу Altium.

Для Milestone 1B задано цільову версію InvenTree 1.5.6 / API schema 530; Milestone 1C не змінює цей контракт. Живий сервер, права доступу й повнота видимого дерева не перевірялися. Unit-тести використовують локальні fixtures, mocks, тимчасові директорії й тестові файли бібліотек; це не перевірка бінарних моделей або сумісності з Altium. Технічний шаблон `database/templates/empty.accdb` зберігається в репозиторії; його перевірка з конкретним ACE/Altium середовищем та реалізація writer залишаються окремими завданнями.
