# InvenTree Category Structure — Passive Components

Цей документ описує рекомендовану структуру InvenTree для людини та правила підтримки бібліотеки. `inventree-sync` не парсить цей файл як runtime schema.

У кожній категорії перелічені лише параметри, які призначаються безпосередньо цій категорії.

InvenTree додає до конкретного Part параметри його категорії, у тому числі параметри, успадковані від категорій вищого рівня. `inventree-sync` читає фактичні параметри кожного Part і не відтворює цю логіку успадкування самостійно.

Для параметрів, що є фізичними величинами, вказані рекомендовані одиниці вимірювання. Для параметрів із фіксованим набором допустимих значень вказаний список вибору.

Порожні leaf-категорії не експортуються в Microsoft Access і не створюють таблиць.

## Назви категорій для inventree-sync і Microsoft Access

Канонічна назва категорії — англійська частина заголовка без номера розділу й українського пояснення у дужках. Вона записується в `name` категорії InvenTree. Для кожної leaf-категорії, що містить хоча б один експортований Part, `inventree-sync` створює однойменну таблицю Access: `table.name = category.name`, без псевдонімів або автоматичного скорочення. Порожні leaf-категорії ігноруються.

Конвенція проєкту: від 1 до 64 символів, англійські літери й цифри, одиночні пробіли між словами; перший символ — літера. Пунктуація та початкові/кінцеві пробіли не використовуються. Назви експортованих leaf-категорій у вибраному дереві мають бути унікальними без урахування регістру; зарезервовані слова Access/ACE і системні префікси `MSys`/`USys` не використовуються. Це вужча конвенція проєкту в межах [правил найменування Microsoft Access](https://support.microsoft.com/en-us/access/guidelines-for-naming-fields-controls-and-objects).

Узгоджені перейменування:

| Попередня назва | Канонічна назва |
|---|---|
| Current Sense / Shunt Resistors | Current Sense and Shunt Resistors |
| Resistor Networks / Arrays | Resistor Networks and Arrays |
| Variable Resistors / Trimmers | Variable Resistors and Trimmers |
| Signal / Pulse Transformers | Signal and Pulse Transformers |
| Ferrites & Chokes | Ferrites and Chokes |

Остання категорія є батьківською і власної таблиці не створює. Якщо в InvenTree ще використовуються попередні назви, їх потрібно перейменувати зі збереженням category PK. `inventree-sync` перевіряє назви, але не перейменовує категорії через API. Деталі: [архітектура inventree-sync](../architecture/inventree-sync-design.md).

---

# 1. Electronic Components (Електронні компоненти)

**Загальні параметри**

- **Value (Номінал / значення)**

- **Package (Корпус)**

- **Mounting Type (Тип монтажу)**
  - Список вибору: `Mounting Type`
  - Значення: `SMD`, `THT`

- **Altium Symbol (Символ Altium)**

- **Altium Footprint (Посадкове місце Altium)**

- **KiCad Symbol (Символ KiCad)**

- **KiCad Footprint (Посадкове місце KiCad)**

&nbsp;

## 1.1. Passive Components (Пасивні компоненти)

&nbsp;

### 1.1.1. Resistors (Резистори)

**Загальні параметри**

- **Resistance (Опір)**
  - Одиниці: `Ω`

- **Tolerance (Допуск)**
  - Одиниці: `%`

- **Power Rating (Номінальна потужність)**
  - Одиниці: `W`

&nbsp;

#### 1.1.1.1. Fixed Resistors (Постійні резистори)

&nbsp;

#### 1.1.1.2. Current Sense and Shunt Resistors (Струмовимірювальні / шунтові резистори)

**Параметри**

- **Current Rating (Номінальний струм)**
  - Одиниці: `A`

&nbsp;

#### 1.1.1.3. Resistor Networks and Arrays (Резисторні збірки / масиви)

**Параметри**

- **Element Count (Кількість елементів)**

- **Network Topology (Топологія збірки)**
  - Список вибору: `Resistor Network Topology`
  - Значення: `Isolated`, `Bussed`, `Dual Terminator`

&nbsp;

#### 1.1.1.4. Variable Resistors and Trimmers (Змінні / підлаштувальні резистори)

**Параметри**

- **Adjustment Type (Тип регулювання)**
  - Список вибору: `Adjustment Type`
  - Значення: `Single-turn`, `Multi-turn`

&nbsp;

#### 1.1.1.5. Thermistors (Термістори)

**Параметри**

- **Thermistor Type (Тип термістора)**
  - Список вибору: `Thermistor Type`
  - Значення: `NTC`, `PTC`

---

### 1.1.2. Capacitors (Конденсатори)

**Загальні параметри**

- **Capacitance (Ємність)**
  - Одиниці: `F`

- **Tolerance (Допуск)**
  - Одиниці: `%`

- **Voltage Rating (Номінальна напруга)**
  - Одиниці: `V`

- **ESR (Еквівалентний послідовний опір)**
  - Одиниці: `Ω`

&nbsp;

#### 1.1.2.1. Ceramic Capacitors (Керамічні конденсатори)

**Параметри**

- **Dielectric (Діелектрик)**
  - Список вибору: `Ceramic Capacitor Dielectric`
  - Значення: `C0G`, `X5R`, `X7R`, `X7S`, `Y5V`

&nbsp;

#### 1.1.2.2. Aluminum Electrolytic Capacitors (Алюмінієві електролітичні конденсатори)

**Параметри**

- **Ripple Current (Допустимий струм пульсацій)**
  - Одиниці: `A`

&nbsp;

#### 1.1.2.3. Polymer Capacitors (Полімерні конденсатори)

**Параметри**

- **Ripple Current (Допустимий струм пульсацій)**
  - Одиниці: `A`

&nbsp;

#### 1.1.2.4. Tantalum Capacitors (Танталові конденсатори)

&nbsp;

#### 1.1.2.5. Film Capacitors (Плівкові конденсатори)

&nbsp;

#### 1.1.2.6. Supercapacitors (Суперконденсатори)

---

### 1.1.3. Inductors (Індуктори / дроселі)

**Параметри**

- **Inductance (Індуктивність)**
  - Одиниці: `H`

- **Current Rating (Номінальний струм)**
  - Одиниці: `A`

- **Saturation Current (Струм насичення)**
  - Одиниці: `A`

- **DC Resistance (Опір постійному струму)**
  - Одиниці: `Ω`

---

### 1.1.4. Ferrites and Chokes (Ферити та дроселі)

&nbsp;

#### 1.1.4.1. Ferrite Beads (Феритові намистини)

**Параметри**

- **Impedance (Імпеданс)**
  - Одиниці: `Ω`

- **Impedance Test Frequency (Частота вимірювання імпедансу)**
  - Одиниці: `Hz`

- **Current Rating (Номінальний струм)**
  - Одиниці: `A`

- **DC Resistance (Опір постійному струму)**
  - Одиниці: `Ω`

&nbsp;

#### 1.1.4.2. Common Mode Chokes (Синфазні дроселі)

**Параметри**

- **Impedance (Імпеданс)**
  - Одиниці: `Ω`

- **Impedance Test Frequency (Частота вимірювання імпедансу)**
  - Одиниці: `Hz`

- **Current Rating (Номінальний струм)**
  - Одиниці: `A`

- **DC Resistance (Опір постійному струму)**
  - Одиниці: `Ω`

&nbsp;

#### 1.1.4.3. EMI Filters (EMI-фільтри)

**Параметри**

- **Filter Type (Тип фільтра)**
  - Список вибору: `Filter Type`
  - Значення: `Low-pass`, `High-pass`, `Band-pass`, `Band-stop`

- **Current Rating (Номінальний струм)**
  - Одиниці: `A`

---

### 1.1.5. Transformers (Трансформатори)

**Загальні параметри**

- **Turns Ratio (Коефіцієнт трансформації)**

- **Frequency Range (Діапазон частот)**
  - Одиниці: `Hz`

- **Isolation Voltage (Напруга ізоляції)**
  - Одиниці: `V`

&nbsp;

#### 1.1.5.1. Power Transformers (Силові трансформатори)

**Параметри**

- **Primary Voltage (Напруга первинної обмотки)**
  - Одиниці: `V`

- **Secondary Voltage (Напруга вторинної обмотки)**
  - Одиниці: `V`

- **Power Rating (Номінальна потужність)**
  - Одиниці: `W`

- **Frequency (Частота)**
  - Одиниці: `Hz`

&nbsp;

#### 1.1.5.2. Signal and Pulse Transformers (Сигнальні / імпульсні трансформатори)

**Параметри**

- **Impedance (Імпеданс)**
  - Одиниці: `Ω`

&nbsp;

#### 1.1.5.3. Current Transformers (Трансформатори струму)

**Параметри**

- **Current Rating (Номінальний струм)**
  - Одиниці: `A`
