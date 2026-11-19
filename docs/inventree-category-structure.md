# Структура категорій InvenTree

Цей документ визначає рекомендовану структуру бібліотеки, прямі призначення ParameterTemplates та успадкування. Це не знімок сервера: наявність категорій і призначень в InvenTree тут не підтверджується. Гілку Passive Components збережено за чинною конвенцією; **Active Components — нова пропозиція для окремого впровадження**.

InvenTree є джерелом даних. `inventree-sync` читає фактичні параметри кожного Part; він не читає цей Markdown і не відтворює успадкування локально. Правила експорту визначає [технічна документація](../tools/inventree-sync/README.md#category-and-schema-processing). Назви компонентів визначає [конвенція IPN](ipn-naming-convention.md), посилання на моделі — [конвенція Altium](library-convention.md).

## Назви категорій та таблиці SQLite

Назви категорій англійські; український переклад є поясненням, а не частиною назви. Назва експортованої кінцевої категорії має повністю відповідати:

```regex
[A-Za-z][A-Za-z0-9]*(?: [A-Za-z0-9]+)*
```

Допускаються латинські літери, цифри та одиночні внутрішні пробіли; перший символ — літера. Початкові/кінцеві пробіли, подвійні пробіли, дефіси, `/`, `&`, `_` та інша пунктуація не допускаються. Префікс SQLite `sqlite_` зарезервовано; він також не проходить цей шаблон.

Одна кінцева категорія з експортованими Parts утворює одну таблицю з **точно тією самою назвою**. Назви таких таблиць у всіх гілках мають бути унікальними без урахування регістру. Порожні кінцеві категорії не утворюють таблиць і не потребують визначення схеми. Part у некінцевій категорії спричиняє помилку.

Синхронізатор не перейменовує, не скорочує і не виправляє назви. Окремого обмеження у 64 символи або списку заборонених SQL-слів немає: ідентифікатори екрануються для SQLite. Наприклад, `Select` технічно допустиме, хоча предметна назва категорії корисніша. Діють фактичні обмеження встановленого SQLite.

Додавання дочірніх категорій перетворює колишній лист на батьківську категорію. Перед наступним експортом потрібно вручну перенести її Parts у відповідні листи. Нові назви/гілки можуть замінити таблиці у повному знімку SQLite; відповідні mappings у DbLib змінюються вручну. Цей документ не виконує такої міграції.

## Як читати параметри

У таблицях нижче наведено **лише прямі призначення** конкретній категорії. Дочірня категорія додатково успадковує параметри всіх предків. `—` в одиницях означає порожнє поле units, а «Немає додаткових» — відсутність нових прямих призначень, не відсутність успадкованих параметрів.

Однакова назва з однаковим значенням та одиницями означає спільний ParameterTemplate, призначений кільком категоріям, а не нові однойменні шаблони. Значення вибору зберігаються в InvenTree. Не створюйте локальних копій цих списків для runtime.

`Value` — текст для відображення; електричні параметри мають окремі значення й metadata units. Наприклад, `Value = 4n7`, `Capacitance.data = 4.7n`, `Capacitance.units = F`. Експортер зберігає Value і готує `4.7n F` для Capacitance. Він не перетворює `4n7` на число. Докладніше: [текст та одиниці](../tools/inventree-sync/README.md#text-and-units).

## Рекомендоване дерево

```text
Electronic Components
├── Passive Components
│   ├── Resistors
│   │   ├── Fixed Resistors
│   │   ├── Current Sense and Shunt Resistors
│   │   ├── Resistor Networks and Arrays
│   │   ├── Variable Resistors and Trimmers
│   │   └── Thermistors
│   ├── Capacitors
│   │   ├── Ceramic Capacitors
│   │   ├── Aluminum Electrolytic Capacitors
│   │   ├── Polymer Capacitors
│   │   ├── Tantalum Capacitors
│   │   ├── Film Capacitors
│   │   └── Supercapacitors
│   ├── Inductors
│   ├── Ferrites and Chokes
│   │   ├── Ferrite Beads
│   │   ├── Common Mode Chokes
│   │   └── EMI Filters
│   └── Transformers
│       ├── Power Transformers
│       ├── Signal and Pulse Transformers
│       └── Current Transformers
└── Active Components
    ├── Diodes
    │   ├── Signal Diodes
    │   ├── Rectifier Diodes
    │   ├── Schottky Diodes
    │   ├── Zener Diodes
    │   ├── TVS Diodes
    │   ├── ESD Protection Diodes
    │   └── Bridge Rectifiers
    ├── Transistors
    │   ├── MOSFETs
    │   ├── Bipolar Transistors
    │   ├── JFETs
    │   └── IGBTs
    ├── Thyristors and Triacs
    │   ├── Thyristors
    │   └── Triacs
    └── Integrated Circuits
        ├── Microcontrollers
        ├── Microprocessors
        ├── Programmable Logic ICs
        ├── Memory ICs
        ├── Digital Logic ICs
        ├── Analog ICs
        ├── Data Converter ICs
        ├── Power Management ICs
        ├── Interface ICs
        ├── Driver ICs
        ├── Clock and Timing ICs
        ├── RF ICs
        └── Specialized ICs
```

Усі назви листів у цьому дереві відповідають правилам експорту та не повторюються без урахування регістру. Наявність формату IPN для іншої родини, наприклад роз'ємів, не означає, що її категорії вже визначені цим деревом.

## Electronic Components — Електронні компоненти

Прямі загальні параметри, що успадковуються обома основними гілками:

| ParameterTemplate | Одиниці | Призначення / список |
|---|---|---|
| Value | — | Текстове значення на схемі |
| Package | — | Позначення корпусу; не посилання на footprint |
| Mounting Type | — | Список `Mounting Type`: `SMD`, `THT` |
| Altium Symbol | — | Посилання бібліотека:символ |
| Altium Footprint | — | Посилання бібліотека:посадкове місце |
| KiCad Symbol | — | Посилання KiCad; не експортується до Altium |
| KiCad Footprint | — | Посилання KiCad; не експортується до Altium |

Manufacturer Part та його MPN належать до відповідних сутностей InvenTree; вони не є універсальними параметрами категорії і не створюють додаткових рядків експорту.

## Passive Components — Пасивні компоненти

Прямих додаткових параметрів немає. Нижче збережено чинні назви, одиниці та списки вибору пасивної гілки.

### Resistors — Резистори

| Прямий ParameterTemplate | Одиниці |
|---|---|
| Resistance | Ω |
| Tolerance | % |
| Power Rating | W |

| Дочірня категорія | Українська назва | Лише прямі додаткові параметри |
|---|---|---|
| Fixed Resistors | Постійні резистори | Немає додаткових |
| Current Sense and Shunt Resistors | Вимірювальні та шунтові резистори | `Current Rating` (A) |
| Resistor Networks and Arrays | Резисторні збірки та масиви | `Element Count` (—); `Network Topology` (—) |
| Variable Resistors and Trimmers | Змінні та підлаштувальні резистори | `Adjustment Type` (—) |
| Thermistors | Термістори | `Thermistor Type` (—) |

Списки: `Resistor Network Topology` → `Isolated`, `Bussed`, `Dual Terminator`; `Adjustment Type` → `Single-turn`, `Multi-turn`; `Thermistor Type` → `NTC`, `PTC`. Параметр Network Topology використовує саме список Resistor Network Topology.

### Capacitors — Конденсатори

| Прямий ParameterTemplate | Одиниці |
|---|---|
| Capacitance | F |
| Tolerance | % |
| Voltage Rating | V |
| ESR | Ω |

| Дочірня категорія | Українська назва | Лише прямі додаткові параметри |
|---|---|---|
| Ceramic Capacitors | Керамічні конденсатори | `Dielectric` (—) |
| Aluminum Electrolytic Capacitors | Алюмінієві електролітичні конденсатори | `Ripple Current` (A) |
| Polymer Capacitors | Полімерні конденсатори | `Ripple Current` (A) |
| Tantalum Capacitors | Танталові конденсатори | Немає додаткових |
| Film Capacitors | Плівкові конденсатори | Немає додаткових |
| Supercapacitors | Суперконденсатори | Немає додаткових |

Список `Ceramic Capacitor Dielectric` для Dielectric: `C0G`, `X5R`, `X7R`, `X7S`, `Y5V`.

### Inductors — Індуктивності

Це кінцева категорія.

| Прямий ParameterTemplate | Одиниці |
|---|---|
| Inductance | H |
| Current Rating | A |
| Saturation Current | A |
| DC Resistance | Ω |

### Ferrites and Chokes — Ферити та дроселі

Батьківська категорія не додає параметрів.

| Дочірня категорія | Українська назва | Лише прямі параметри |
|---|---|---|
| Ferrite Beads | Феритові намистини | `Impedance` (Ω), `Impedance Test Frequency` (Hz), `Current Rating` (A), `DC Resistance` (Ω) |
| Common Mode Chokes | Синфазні дроселі | `Impedance` (Ω), `Impedance Test Frequency` (Hz), `Current Rating` (A), `DC Resistance` (Ω) |
| EMI Filters | Фільтри електромагнітних завад | `Filter Type` (—), `Current Rating` (A) |

Список `Filter Type`: `Low-pass`, `High-pass`, `Band-pass`, `Band-stop`. Однакові призначення у двох листах використовують ті самі шаблони; це не успадковані параметри батьківської категорії.

### Transformers — Трансформатори

| Прямий ParameterTemplate | Одиниці |
|---|---|
| Turns Ratio | — |
| Frequency Range | Hz |
| Isolation Voltage | V |

| Дочірня категорія | Українська назва | Лише прямі додаткові параметри |
|---|---|---|
| Power Transformers | Силові трансформатори | `Primary Voltage` (V), `Secondary Voltage` (V), `Power Rating` (W), `Frequency` (Hz) |
| Signal and Pulse Transformers | Сигнальні та імпульсні трансформатори | `Impedance` (Ω) |
| Current Transformers | Вимірювальні трансформатори струму | `Current Rating` (A) |

Обмеження Frequency Range та значення одиниці W пояснені в [питаннях для узгодження](#питання-для-окремого-узгодження). Метадані не змінюються приховано заради успішного експорту.

## Active Components — Активні компоненти

**Уся ця гілка, її прямі призначення і нові списки нижче — рекомендація, не підтверджена конфігурація сервера.** Перш ніж призначати шаблон, перевірте його одиниці, зміст і наявний однойменний шаблон в InvenTree. На Active Components та організаційних батьківських категоріях Diodes, Transistors, Thyristors and Triacs, Integrated Circuits нових універсальних параметрів не пропонується. Вони успадковують Electronic Components.

Параметри нижче — добірка для відповідних листів, а не вимога заповнити всі поля кожного Part. Максимальні, типові й номінальні характеристики та умови вимірювання не взаємозамінні. Умови VGS, струму, температури, частоти й форми імпульсу перевіряються за документацією виробника; одне число без умов не доводить взаємозамінність.

### Diodes — Діоди

| Лист / група IPN | Українська назва | Запропоновані прямі ParameterTemplates (одиниці) |
|---|---|---|
| Signal Diodes / `DIO-SIG` | Сигнальні діоди | `Reverse Voltage` (V), `Forward Current` (A), `Forward Voltage` (V), `Reverse Recovery Time` (s) |
| Rectifier Diodes / `DIO-RECT` | Випрямні діоди | `Reverse Voltage` (V), `Forward Current` (A), `Forward Voltage` (V), `Reverse Recovery Time` (s), якщо визначено |
| Schottky Diodes / `DIO-SCH` | Діоди Шотткі | `Reverse Voltage` (V), `Forward Current` (A), `Forward Voltage` (V) |
| Zener Diodes / `DIO-ZEN` | Стабілітрони | `Zener Voltage` (V), `Zener Test Current` (A), `Power Dissipation` (W), наявний `Tolerance` (%) |
| TVS Diodes / `DIO-TVS` | Захисні TVS-діоди | `Reverse Standoff Voltage` (V), `Breakdown Voltage` (V), `Clamping Voltage` (V), `Peak Pulse Current` (A) |
| ESD Protection Diodes / `DIO-ESD` | Діоди захисту від ESD | `Working Voltage` (V), наявний `Capacitance` (F), `Clamping Voltage` (V) |
| Bridge Rectifiers / `DIO-BRG` | Випрямні мости | `Reverse Voltage` (V), `Forward Current` (A), `Forward Voltage` (V) |

Для мосту Forward Current характеризує міст за умовами виробника, а Forward Voltage потребує уточнення кількості послідовних переходів. Для масивів ESD Capacitance стосується визначеного каналу. TVS/ESD не успадковують універсальну Forward Current: захисні параметри мають інший зміст. Якщо потрібний вибір одно-/двонапрямленого захисту, його окремий шаблон і список слід погодити перед призначенням.

### Transistors — Транзистори

| Лист / група IPN | Українська назва | Запропоновані прямі ParameterTemplates (одиниці) |
|---|---|---|
| MOSFETs / `MOS-N`, `MOS-P` | MOSFET-транзистори | `Channel Type` (—), `Drain-Source Voltage` (V), `Drain Current` (A), `RDS(on)` (Ω), `Power Dissipation` (W) |
| Bipolar Transistors / `BJT-NPN`, `BJT-PNP` | Біполярні транзистори | `Transistor Polarity` (—), `Collector-Emitter Voltage` (V), `Collector Current` (A), `DC Current Gain` (—), `Power Dissipation` (W) |
| JFETs / `JFET-N`, `JFET-P` | Польові транзистори з керувальним переходом | `Channel Type` (—), `Drain-Source Voltage` (V), `Zero Gate Voltage Drain Current` (A), `Gate-Source Cutoff Voltage` (V) |
| IGBTs / `IGBT` | IGBT-транзистори | `Collector-Emitter Voltage` (V), `Collector Current` (A), `Collector-Emitter Saturation Voltage` (V), `Power Dissipation` (W) |

Пропоновані списки: `Channel Type` → `N-channel`, `P-channel`; `Transistor Polarity` → `NPN`, `PNP`. Складені/комплементарні прилади можуть потребувати розширення списків за окремим рішенням; не примушуйте їх до хибного одиничного значення. MOSFET-поля не призначаються батьківській категорії Transistors.

### Thyristors and Triacs — Тиристори та симістори

Це окрема родина керованих напівпровідникових приладів. Такий поділ відповідає, зокрема, [класифікації SCR та симісторів STMicroelectronics](https://www.st.com/en/thyristors-scr-and-ac-switches.html); вони не є підвидами звичайних транзисторів.

| Лист / префікс IPN | Українська назва | Запропоновані прямі ParameterTemplates (одиниці) |
|---|---|---|
| Thyristors / `SCR` | Тиристори SCR | `Repetitive Peak Off-State Voltage` (V), `RMS On-State Current` (A), `Gate Trigger Current` (A), `Holding Current` (A) |
| Triacs / `TRIAC` | Симістори | `Repetitive Peak Off-State Voltage` (V), `RMS On-State Current` (A), `Gate Trigger Current` (A), `Holding Current` (A) |

RMS-струм не підміняє середній або імпульсний струм. Умови/квадрант спрацювання симістора беруться з документації виробника. Однакові шаблони призначаються обом листам без дублювання визначень.

### Integrated Circuits — Інтегральні мікросхеми

Не призначайте всім IC однаковий електричний набір лише через їхню належність до цієї гілки. За потреби для конкретної родини можна додати `Supply Voltage` (V; одне номінальне значення), `Supply Current` (A; за визначеного режиму) та `Operating Temperature Range` (—; текст із явно вказаними °C). Останній має порожні units, щоб текстовий діапазон зберігався без scalar-форматування. Для числового пошуку меж краще окремо погодити мінімальний/максимальний параметри, а не змішувати їх з номінальним.

Нижче — початкова неглибока класифікація. Коди функцій IPN не зобов'язують створювати ще один рівень категорій.

| Лист | Українська назва / коди IC | Приклади виправданих прямих параметрів |
|---|---|---|
| Microcontrollers | Мікроконтролери / MCU | `Maximum Clock Frequency` (Hz), `GPIO Count` (—) |
| Microprocessors | Мікропроцесори / MPU | `Maximum Clock Frequency` (Hz), `Core Count` (—) |
| Programmable Logic ICs | Програмована логіка / FPGA, CPLD | `Logic Element Count` (—), лише з визначенням виробника |
| Memory ICs | Пам'ять / MEM | `Memory Capacity` (bit), `Interface Type` (—) |
| Digital Logic ICs | Цифрова логіка / LOG | `Logic Function` (—), `Channel Count` (—), де застосовно |
| Analog ICs | Аналогові IC / OPA, CMP, INA, ASW | `Channel Count` (—); `Gain Bandwidth Product` (Hz) лише для відповідних підсилювачів |
| Data Converter ICs | Перетворювачі даних / ADC, DAC, CODEC, AFE | `Resolution` (bit), `Sample Rate` (Hz), де ці величини визначені |
| Power Management ICs | Керування живленням / LDO, DCDC, REF, PMIC, LSW, EFUSE, HSS | `Output Voltage` (V), `Output Current` (A) лише для визначеного виходу/режиму |
| Interface ICs | Інтерфейси / RS232, RS485, CAN, LIN, USB, ETH, IOX, BRG | `Interface Type` (—), `Channel Count` (—), де застосовно |
| Driver ICs | Драйвери / GDRV, MDRV, LEDDRV | `Peak Output Current` (A) лише для визначеного каналу та імпульсу |
| Clock and Timing ICs | Тактування / CLK | `Output Frequency` (Hz) для визначеного виходу |
| RF ICs | Радіочастотні IC / RF | `Operating Frequency` (Hz) для одного значення; не текстовий діапазон |
| Specialized ICs | Спеціалізовані IC / SPEC | Універсальних додаткових параметрів не запропоновано |

`bit` тут є точною текстовою одиницею; місткість задають скалярним значенням, не довільною фразою чи непідтримуваним двійковим префіксом. Відсутні характеристики не замінюються нулями. Багатовихідні PMIC, складні AFE та RF-прилади потребують окремого погодження поля/умов, якщо одного значення недостатньо. Не вигадуйте дані для заповнення рекомендованої таблиці.

## Питання для окремого узгодження

- **Frequency Range (Hz):** чинний шаблон пасивної гілки описує діапазон, але formatter приймає лише скаляр із одиницями. `20–20000` з Hz не експортується. Варіанти для наступного рішення: залишити текстовий діапазон із явними одиницями та порожніми metadata units або впровадити два числові шаблони меж із Hz. Це потребує узгодження й міграції даних; тут існуюче визначення збережено.
- **Power Rating (W) для трансформаторів:** W означає активну потужність. Не записуйте значення повної потужності у VA як W. Якщо потрібна саме повна потужність, погодьте окремий шаблон; не змінюйте спільний Power Rating непомітно.
- **Mounting Type:** чинний список містить SMD/THT. Конвенція IPN роз'ємів також передбачає PRESSFIT; категорії роз'ємів та розширення списку ще потребують окремого узгодження.
- **Active Components:** перед ручним впровадженням звірте шаблони, списки, умови характеристик, наявні Parts та mappings DbLib. Ці рекомендації не створюють категорій, не змінюють сервер і не перейменовують існуючих IPN.
