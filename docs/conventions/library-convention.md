# Altium Library Conventions

This document defines naming, organization, and reuse conventions for the Altium component library synchronized with InvenTree.

The main goals are:

- consistent and predictable naming;
- human-readable library identifiers;
- stable references between InvenTree and Altium;
- reuse of symbols and footprints between multiple parts;
- compatibility with Git and synchronization/validation scripts;
- clear separation between electrical, mechanical, and purchasing data.

---

## 1. General Principles

### 1.1 Language

All library identifiers shall use English.

Examples:

```text
Resistor
Capacitor
Ferrite_Bead
Connectors.PcbLib
```

### 1.2 Character Set

Names shall use ASCII characters only.

Preferred characters:

```text
A-Z
a-z
0-9
_
-
.
%
```

Usage of special characters shall be limited to cases defined by this document.

Avoid:

```text
space
/
\
:
*
?
"
<
>
|
```

### 1.3 Decimal Separator

A period `.` shall be used as the decimal separator.

Correct:

```text
0.5
0.65
1.27
3.3
```

Do not replace the decimal point with `P`.

Avoid:

```text
0P5
0P65
1P27
```

### 1.4 Units

Units shall normally be omitted from footprint names when the unit is defined by convention.

Unless otherwise specified, mechanical dimensions in footprint names are in millimetres.

Example:

```text
QFN_32_5X5_P0.5
```

means:

- body: 5 mm × 5 mm;
- pitch: 0.5 mm.

---

# 2. Library File Names

Library file names shall use **PascalCase**.

Do not use spaces or hyphens as word separators.

Examples:

```text
Passives.SchLib
Diodes.SchLib
Transistors.SchLib
Analog.SchLib
Digital.SchLib
Connectors.SchLib

Resistors.PcbLib
Capacitors.PcbLib
Inductors.PcbLib
Diodes.PcbLib
Transistors.PcbLib
SOIC.PcbLib
QFN.PcbLib
QFP.PcbLib
Connectors.PcbLib
Mechanical.PcbLib
```

An underscore may be used when a library requires an additional qualifier:

```text
Connectors_Molex.PcbLib
Connectors_JST.PcbLib
Modules_Espressif.PcbLib
```

Format:

```text
<Family>.PcbLib
<Family>_<Qualifier>.PcbLib

<Family>.SchLib
<Family>_<Qualifier>.SchLib
```

---

# 3. Library Organization

Libraries shall be split only where the split provides a practical organizational benefit.

Unnecessary fragmentation shall be avoided.

In particular, resistor and capacitor footprints shall **not** be divided into separate SMD and THT libraries.

Recommended organization:

```text
libraries/
├── symbols/
│   ├── Passives.SchLib
│   ├── Diodes.SchLib
│   ├── Transistors.SchLib
│   ├── Analog.SchLib
│   ├── Digital.SchLib
│   ├── MCU.SchLib
│   ├── Memory.SchLib
│   ├── Sensors.SchLib
│   ├── Connectors.SchLib
│   ├── Electromechanical.SchLib
│   └── Modules.SchLib
│
└── footprints/
    ├── Resistors.PcbLib
    ├── Capacitors.PcbLib
    ├── Inductors.PcbLib
    ├── Diodes.PcbLib
    ├── Transistors.PcbLib
    ├── SOIC.PcbLib
    ├── TSSOP.PcbLib
    ├── QFN.PcbLib
    ├── QFP.PcbLib
    ├── BGA.PcbLib
    ├── Connectors.PcbLib
    ├── Modules.PcbLib
    └── Mechanical.PcbLib
```

The exact library split may evolve as the number of components grows.

Moving a symbol or footprint between library files shall not require changing its canonical name.

---

# 4. Symbol Naming

## 4.1 General Format

Symbol names shall use descriptive names rather than single-letter identifiers.

Do not use canonical symbol names such as:

```text
R
C
L
```

Use:

```text
Resistor
Capacitor
Inductor
```

Words within a symbol name shall be separated by `_`.

Each regular word starts with an uppercase letter.

Format:

```text
<Base_Type>[_<Qualifier>][_<Qualifier>...]
```

Examples:

```text
Resistor
Resistor_Array

Capacitor
Capacitor_Polarized
Capacitor_Variable

Inductor
Inductor_Coupled
Ferrite_Bead

Diode
Diode_Schottky
Diode_Zener
Diode_TVS
LED

Transistor_NMOS
Transistor_PMOS
Transistor_NPN
Transistor_PNP

OpAmp
OpAmp_Dual
Comparator

Crystal
Oscillator

Connector_Generic
Connector_USB_C
Connector_RJ45
```

## 4.2 Abbreviations

Well-established technical abbreviations may remain uppercase:

```text
LED
TVS
NMOS
PMOS
NPN
PNP
USB
RJ45
ADC
DAC
MCU
```

Examples:

```text
Diode_TVS
Connector_USB_C
Transistor_NMOS
```

## 4.3 Symbol Names Describe Electrical Function

A symbol name shall describe the electrical or logical representation, not the manufacturer's package.

For example:

```text
OpAmp_Dual
```

is preferred over:

```text
SOIC8_OpAmp
```

Package information belongs to the footprint.

---

# 5. Footprint Naming

## 5.1 General Style

Footprint names shall use **uppercase structured identifiers** with `_` separating logical fields.

Examples:

```text
RES_0603_H0.55
CAP_0603_H0.90
SOIC_8_3.9X4.9_P1.27
QFN_32_5X5_P0.5_EP3.4
```

Footprint names should describe the physical implementation sufficiently to distinguish mechanically incompatible variants.

---

# 6. Standard SMD Passive Footprints

Common imperial package designations shall be retained because they are widely used and easy to recognize.

Examples:

```text
0201
0402
0603
0805
1206
1210
2010
2512
```

The metric equivalent may be stored in metadata but does not have to be included in the canonical footprint name.

Examples:

```text
RES_0402_H0.40
RES_0603_H0.55
RES_0805_H0.60
RES_1206_H0.65

CAP_0402_H0.50
CAP_0603_H0.80
CAP_0603_H0.90
CAP_0805_H1.25
```

## 6.1 Component Type Is Part of the Footprint Identity

Resistors, capacitors, and inductors with the same nominal package size shall use separate footprints.

For example:

```text
RES_0603_H0.55
CAP_0603_H0.90
IND_0603_H0.80
```

shall be considered different footprints even if their copper land patterns are identical.

This is necessary because a footprint also defines mechanical information such as:

- 3D model;
- body height;
- assembly outline;
- courtyard;
- silkscreen representation.

Therefore:

```text
RES_0603
```

and:

```text
CAP_0603
```

shall not be represented by one shared footprint.

---

# 7. Height Designator

Where component height is relevant to distinguishing mechanical models, the height shall be specified using the prefix:

```text
H
```

Examples:

```text
H0.40
H0.55
H0.90
H1.25
```

The value is in millimetres.

Examples:

```text
RES_0603_H0.55
CAP_0603_H0.90
CAP_0805_H1.25
```

Different package heights may use different footprints even when the PCB land pattern itself is identical.

For example:

```text
CAP_0603_H0.50
CAP_0603_H0.80
CAP_0603_H0.90
```

This allows the associated 3D model to represent the actual mechanical envelope.

Manufacturer-specific footprints should not be created merely because of minor cosmetic differences in the 3D model.

---

# 8. IC Package Footprints

Standard IC packages shall contain the package family followed by the most important mechanical parameters.

Recommended general format:

```text
<PACKAGE>_<PINS>_<BODY>_P<PITCH>[_<ADDITIONAL_PARAMETERS>]
```

Examples:

```text
SOIC_8_3.9X4.9_P1.27
TSSOP_14_4.4X5_P0.65
QFN_32_5X5_P0.5
QFN_32_5X5_P0.5_EP3.4
LQFP_64_10X10_P0.5
```

Where:

```text
P    = pin pitch
EP   = exposed pad
```

Additional prefixes may be introduced when required, but they shall have one consistent meaning across the entire library.

---

# 9. Dimension Formatting

Dimensions within a single field shall use uppercase `X`.

Examples:

```text
5X5
3.9X4.9
10X10
```

Do not use:

```text
5x5
5*5
5_5
```

Examples of complete footprint names:

```text
SOIC_8_3.9X4.9_P1.27
TSSOP_14_4.4X5_P0.65
QFN_32_5X5_P0.5_EP3.4
```

---

# 10. Through-Hole Footprints

Through-hole passive footprints shall remain in the same component-family library as SMD footprints.

Example:

```text
Resistors.PcbLib
```

may contain:

```text
RES_0402_H0.40
RES_0603_H0.55
RES_0805_H0.60

RES_AXIAL_DIN0204_P7.62
RES_AXIAL_DIN0207_P10.16
```

Similarly:

```text
Capacitors.PcbLib
```

may contain both SMD ceramic capacitors and through-hole radial capacitors.

Example:

```text
CAP_0603_H0.90
CAP_0805_H1.25

CAP_RADIAL_D5_P2
CAP_RADIAL_D6.3_P2.5
CAP_RADIAL_D8_P3.5
```

---

# 11. Manufacturer-Specific Footprints

A manufacturer name or series shall only be included when the footprint is genuinely manufacturer- or product-specific.

Examples:

```text
MOLEX_43045_0812
JST_B4B_PH_K
```

Do not create manufacturer-specific copies of standard packages.

Avoid:

```text
TI_SOIC_8
ADI_SOIC_8
ST_SOIC_8
```

when all parts can use the same standard footprint:

```text
SOIC_8_3.9X4.9_P1.27
```

General format:

```text
<MANUFACTURER>_<SERIES_OR_PART>
```

Manufacturer names and established series abbreviations shall be uppercase.

---

# 12. Footprint Variants

Additional suffixes may be introduced when two footprints cannot be distinguished using the normal package parameters.

Such suffixes shall only be introduced when technically necessary.

Examples may include:

```text
QFN_32_5X5_P0.5_EP3.4
QFN_32_5X5_P0.5_EP3.4_VIA
```

or a manufacturer-specific variant where the mechanical implementation is genuinely different.

Avoid creating arbitrary variants such as:

```text
_NEW
_NEW2
_ALT
_FINAL
```

Every suffix shall have a defined technical meaning.

---

# 13. 3D Model Naming

A 3D model shall normally use the same physical-package identifier as its associated footprint.

Example:

```text
RES_0603_H0.55.step
CAP_0603_H0.90.step
SOIC_8_3.9X4.9_P1.27.step
```

If multiple land patterns use exactly the same mechanical body, the same 3D model may be shared.

3D model names describe mechanical geometry rather than individual manufacturer MPNs unless the geometry is manufacturer-specific.

Recommended organization:

```text
models-3d/
├── resistors/
├── capacitors/
├── inductors/
├── ic/
├── connectors/
└── modules/
```

---

# 14. Global Name Uniqueness

Symbol and footprint names shall be globally unique within their respective namespaces.

A footprint name shall identify the same physical footprint regardless of the `.PcbLib` file in which it is stored.

For example:

```text
RES_0603_H0.55
```

shall exist only once in the complete library set.

The synchronization or validation script should detect duplicate footprint names across different `.PcbLib` files.

Example of an invalid state:

```text
Resistors.PcbLib:
    RES_0603_H0.55

Legacy.PcbLib:
    RES_0603_H0.55
```

This shall be treated as an error.

The same rule applies to symbol names unless explicitly documented otherwise.

---

# 15. InvenTree Integration

InvenTree shall reference a symbol or footprint by its canonical name, not by the library filename.

Recommended parameters include:

```text
Symbol
Footprint
Package
```

Example:

```text
Symbol:
Resistor

Package:
0603

Footprint:
RES_0603_H0.55
```

For a capacitor:

```text
Symbol:
Capacitor

Package:
0603

Footprint:
CAP_0603_H0.90
```

The following relationship shall be maintained:

```text
Package != Footprint
```

`Package` is a classification or manufacturer package designation.

`Footprint` identifies the actual PCB library model.

Several InvenTree parts may reference the same symbol and footprint.

---

# 16. Library File Names Shall Not Be Stored as Component Identity

InvenTree shall not depend on the physical `.SchLib` or `.PcbLib` file containing the model.

Prefer:

```text
Symbol = Resistor
Footprint = RES_0603_H0.55
```

rather than:

```text
SymbolLibrary = Passives.SchLib
Symbol = Resistor

FootprintLibrary = Resistors.PcbLib
Footprint = RES_0603_H0.55
```

The synchronization script shall resolve canonical names to their current library files.

This allows models to be moved between libraries without modifying InvenTree parts.

---

# 17. IPN Formatting Characters

The exact IPN structure is defined separately from the Altium library naming convention.

However, the following character rules apply.

A period `.` may be used as the decimal separator:

```text
0.1
0.5
2.2
4.7
```

The percent sign `%` may be used for tolerances:

```text
1%
0.5%
0.1%
```

Do not replace decimal points with `P` solely to make the IPN filesystem-safe.

For example, where such a parameter belongs to the chosen IPN format:

```text
0.1%
```

is preferred over:

```text
0P1PCT
```

Synchronization scripts shall correctly URL-encode special characters when communicating with InvenTree.

In particular:

```text
% -> %25
```

when encoded as part of a URL.

IPNs shall not be used directly as filenames unless explicitly sanitized.

---

# 18. Separator Summary

The following separators shall be used consistently:

| Context | Separator | Example |
|---|---|---|
| Library words | PascalCase | `Resistors.PcbLib` |
| Library qualifier | `_` | `Connectors_Molex.PcbLib` |
| Symbol words | `_` | `Ferrite_Bead` |
| Footprint fields | `_` | `QFN_32_5X5_P0.5` |
| Decimal values | `.` | `0.65` |
| Dimension pair | `X` | `5X5` |
| IPN structural fields | Defined by IPN standard | — |
| Percentage | `%` | `0.1%` |

---

# 19. Naming Examples

## Symbols

```text
Resistor
Resistor_Array
Capacitor
Capacitor_Polarized
Inductor
Ferrite_Bead
Diode
Diode_Schottky
Diode_Zener
Diode_TVS
Transistor_NMOS
Transistor_PMOS
Transistor_NPN
Transistor_PNP
OpAmp
OpAmp_Dual
Comparator
Crystal
Oscillator
Connector_Generic
Connector_USB_C
```

## Passive Footprints

```text
RES_0402_H0.40
RES_0603_H0.55
RES_0805_H0.60
RES_1206_H0.65
RES_2512_H0.65

CAP_0402_H0.50
CAP_0603_H0.50
CAP_0603_H0.80
CAP_0603_H0.90
CAP_0805_H1.25

IND_0603_H0.80
IND_0805_H1.20
```

## IC Footprints

```text
SOIC_8_3.9X4.9_P1.27
SOIC_14_3.9X8.7_P1.27

TSSOP_14_4.4X5_P0.65
TSSOP_20_4.4X6.5_P0.65

QFN_16_3X3_P0.5_EP1.7
QFN_32_5X5_P0.5_EP3.4

LQFP_48_7X7_P0.5
LQFP_64_10X10_P0.5
```

## Manufacturer-Specific Footprints

```text
MOLEX_43045_0812
JST_B4B_PH_K
```

---

# 20. Validation Rules

The library validation script should eventually verify at least the following:

1. Symbol names follow the defined naming convention.
2. Footprint names follow the defined naming convention.
3. Symbol names are globally unique.
4. Footprint names are globally unique.
5. Referenced 3D models exist.
6. InvenTree `Symbol` values resolve to an existing symbol.
7. InvenTree `Footprint` values resolve to an existing footprint.
8. Duplicate models across library files are detected.
9. Decimal values use `.` rather than `,`.
10. Invalid filesystem characters are rejected.
11. Library file names follow the defined convention.
12. References remain valid after moving models between library files.

---

# 21. Guiding Principle

Names shall be:

> **human-readable, mechanically meaningful, script-friendly, and stable over time.**

The library structure may change as the project grows, but canonical symbol and footprint names should remain stable whenever the underlying electrical or mechanical model has not changed.