"""Формирование XML по приказу ФНС от 19.12.2023 № ЕД-7-26/970@
(функция ДОП — документ о передаче, УПД со статусом 2).

Структура подогнана под эталон, выгружаемый Диадоком (Контур).
Кодировка — windows-1251 (как у Диадока).
"""
from __future__ import annotations
import re
import os
from datetime import datetime
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom

from parser import Invoice, Item, Party


VERS_FORM = "5.03"
VERS_PROG = "pdf2xml 1.0"
KND_UPD = "1115131"

# стандартные тексты из приказа ФНС
DOC_POFACT = ("Документ об отгрузке товаров (выполнении работ), передаче "
              "имущественных прав (документ об оказании услуг)")
DOC_NAIM = ("Счет-фактура и документ об отгрузке товаров (выполнении работ), "
            "передаче имущественных прав (документ об оказании услуг)")

# федеральные города с известными кодами регионов
FED_CITIES = {
    "москва": ("77", "г. Москва"),
    "санкт-петербург": ("78", "г. Санкт-Петербург"),
    "севастополь": ("92", "г. Севастополь"),
}


# ---------- утилиты ----------

def _fmt_date_ru(iso: str) -> str:
    if not iso:
        return ""
    y, m, d = iso.split("-")
    return f"{d}.{m}.{y}"


def _amount(s: str) -> str:
    try:
        return f"{float(s):.2f}"
    except (ValueError, TypeError):
        return "0.00"


def _q(s: str) -> str:
    try:
        f = float(s)
        if f == int(f):
            return str(int(f))
        return f"{f:.6f}".rstrip("0").rstrip(".")
    except (ValueError, TypeError):
        return s or "0"


def _split_fio(full: str) -> tuple[str, str, str]:
    parts = (full or "").strip().split()
    if len(parts) >= 3:
        return parts[0], parts[1], " ".join(parts[2:])
    if len(parts) == 2:
        return parts[0], parts[1], ""
    return (full or "").strip(), "", ""


def _naim_subj(p: Party) -> str:
    """«НаимЭконСубСост» — как у Диадока: «ФИО, ИНН ...» для ИП, «Наим, ИНН..., КПП...» для ЮЛ."""
    if p.is_ip:
        return f"{p.name}, ИНН {p.inn}".strip()
    parts = [p.name.strip()]
    if p.inn:
        parts.append(f"ИНН {p.inn}")
    if p.kpp:
        parts.append(f"КПП {p.kpp}")
    return ", ".join(parts)


def _parse_address(addr: str) -> dict:
    """Попытка разбить адрес на компоненты АдрРФ. Возвращает словарь атрибутов.
    Если не удалось определить код региона — возвращается {'_fallback': True, 'АдрТекст': addr}.
    """
    if not addr:
        return {"_fallback": True, "АдрТекст": ""}

    s = addr.strip()
    out: dict = {}

    # индекс
    m = re.search(r"\b(\d{6})\b", s)
    if m:
        out["Индекс"] = m.group(1)
        s = (s[:m.start()] + s[m.end():]).strip(" ,")

    # регион
    low = s.lower()
    code, name = None, None
    for key, (c, n) in FED_CITIES.items():
        if key in low:
            code, name = c, n
            break
    if not code:
        # регион не определён — fallback на АдрИнф
        return {"_fallback": True, "АдрТекст": addr}

    out["КодРегион"] = code
    out["НаимРегион"] = name

    # убираем упоминание города из строки
    s = re.sub(r"г\.?\s*[А-ЯЁа-яё\-]+", "", s, count=1, flags=re.IGNORECASE).strip(" ,")

    # улица: по префиксу
    m = re.search(r"(ул\.|пер\.|пр-?кт\.?|шоссе|б-р|наб\.?|пл\.?)\s*([А-ЯЁа-яё\-\d ]+?)(?=,|$)",
                  s, flags=re.IGNORECASE)
    if m:
        street_prefix = m.group(1)
        street = m.group(2).strip()
        out["Улица"] = f"{street_prefix} {street}" if "пер" in street_prefix.lower() else street
        s = (s[:m.start()] + s[m.end():]).strip(" ,")

    # дом: «д.6,к.1» или «д 13»
    m = re.search(r"д\.?\s*(\d+(?:\s*[,/]?\s*к\.?\s*\d+)?)", s, flags=re.IGNORECASE)
    if m:
        dom = m.group(1).replace(" ", "")
        # «6,к.1» → «6, к.1»
        dom = re.sub(r",к\.", ", к.", dom)
        out["Дом"] = dom
        s = (s[:m.start()] + s[m.end():]).strip(" ,")

    # квартира/офис/помещение
    m = re.search(r"(кв\.?|офис|помещ\.?)\s*(\S+)", s, flags=re.IGNORECASE)
    if m:
        val = m.group(2).strip(",.")
        out["Кварт"] = val
        s = (s[:m.start()] + s[m.end():]).strip(" ,")

    # что осталось — это «Район»
    rest = s.strip(" ,")
    if rest:
        out["Район"] = rest

    return out


def _safe_filename_stem(pdf_path: str, inv: Invoice) -> str:
    """Имя XML-файла без расширения. Если pdf_path передан, берём имя PDF; иначе шаблон ФНС."""
    if pdf_path:
        return os.path.splitext(os.path.basename(pdf_path))[0]
    date_compact = (inv.doc_date_iso or "20000101").replace("-", "")
    import uuid
    return f"ON_NSCHFDOPPR_{inv.buyer.inn or '0'}_{inv.seller.inn or '0'}_{date_compact}_{uuid.uuid4()}"


# ---------- добавление адреса ----------

def _add_address(parent: Element, addr_text: str) -> None:
    adr = SubElement(parent, "Адрес")
    parts = _parse_address(addr_text)
    if parts.get("_fallback"):
        SubElement(adr, "АдрИнф", {"КодСтр": "643", "АдрТекст": addr_text})
    else:
        # порядок атрибутов как у Диадока
        attrs = {}
        for k in ("КодРегион", "НаимРегион", "Индекс", "Район", "Улица", "Дом", "Кварт"):
            if parts.get(k):
                attrs[k] = parts[k]
        SubElement(adr, "АдрРФ", attrs)


# ---------- партия ----------

def _add_party(parent: Element, p: Party) -> None:
    idsv = SubElement(parent, "ИдСв")
    if p.is_ip:
        svip = SubElement(idsv, "СвИП", {"ИННФЛ": p.inn or ""})
        last, first, middle = _split_fio(p.name)
        fio_attrs = {"Фамилия": last, "Имя": first}
        if middle:
            fio_attrs["Отчество"] = middle
        SubElement(svip, "ФИО", fio_attrs)
    else:
        yl_attrs = {"НаимОрг": p.name, "ИННЮЛ": p.inn or ""}
        if p.kpp:
            yl_attrs["КПП"] = p.kpp
        SubElement(idsv, "СвЮЛУч", yl_attrs)

    if p.address_raw:
        _add_address(parent, p.address_raw)

    if p.bank_account or p.bank_name:
        bank = SubElement(parent, "БанкРекв", {"НомерСчета": p.bank_account or ""})
        sv_bank_attrs = {}
        if p.bank_name:
            sv_bank_attrs["НаимБанк"] = p.bank_name
        if p.bank_bik:
            sv_bank_attrs["БИК"] = p.bank_bik
        if p.bank_corr:
            sv_bank_attrs["КорСчет"] = p.bank_corr
        SubElement(bank, "СвБанк", sv_bank_attrs)


# ---------- основной билдер ----------

def build_xml(inv: Invoice, pdf_path: str = "") -> tuple[str, bytes]:
    """Собрать XML. Возвращает (имя_без_расширения, байты в windows-1251)."""
    now = datetime.now()
    stem = _safe_filename_stem(pdf_path, inv)

    # корень — ИдФайл, ВерсФорм, ВерсПрог (порядок Диадока)
    root = Element("Файл", {
        "ИдФайл": stem,
        "ВерсФорм": VERS_FORM,
        "ВерсПрог": VERS_PROG,
    })

    # Документ
    doc = SubElement(root, "Документ", {
        "КНД": KND_UPD,
        "ВремИнфПр": now.strftime("%H.%M.%S"),
        "ДатаИнфПр": _fmt_date_ru(inv.doc_date_iso) or now.strftime("%d.%m.%Y"),
        "Функция": "ДОП",
        "ПоФактХЖ": DOC_POFACT,
        "НаимДокОпр": DOC_NAIM,
        "НаимЭконСубСост": _naim_subj(inv.seller),
    })

    # --- СвСчФакт ---
    svf = SubElement(doc, "СвСчФакт", {
        "НомерДок": inv.doc_number,
        "ДатаДок": _fmt_date_ru(inv.doc_date_iso),
    })
    sv_prod = SubElement(svf, "СвПрод")
    _add_party(sv_prod, inv.seller)

    sv_pok = SubElement(svf, "СвПокуп")
    _add_party(sv_pok, inv.buyer)

    SubElement(svf, "ДенИзм", {
        "КодОКВ": inv.currency_code or "643",
        "НаимОКВ": inv.currency_name or "Российский рубль",
    })

    # --- ТаблСчФакт — в Документ, не в СвСчФакт! ---
    tabl = SubElement(doc, "ТаблСчФакт")
    for it in inv.items:
        sved = SubElement(tabl, "СведТов", {
            "НомСтр": str(it.num),
            "НалСт": "без НДС",
            "НаимТов": it.name,
            "ОКЕИ_Тов": it.unit_code or "796",
            "НаимЕдИзм": it.unit_name or "",
            "КолТов": _q(it.qty),
            "ЦенаТов": _amount(it.price),
            "СтТовБезНДС": _amount(it.sum_without_tax),
            "СтТовУчНал": _amount(it.sum_with_tax),
        })
        SubElement(sved, "ДопСведТов")  # пустой тег как у Диадока
        akcz = SubElement(sved, "Акциз")
        SubElement(akcz, "БезАкциз").text = "без акциза"
        sum_nal = SubElement(sved, "СумНал")
        SubElement(sum_nal, "БезНДС").text = "без НДС"

    vsego = SubElement(tabl, "ВсегоОпл", {
        "СтТовБезНДСВсего": _amount(inv.total_without_tax),
        "СтТовУчНалВсего": _amount(inv.total_with_tax),
    })
    sum_all = SubElement(vsego, "СумНалВсего")
    SubElement(sum_all, "БезНДС").text = "без НДС"

    # --- СвПродПер ---
    sv_prod_per = SubElement(doc, "СвПродПер")
    # содержание операции — наим. первой позиции (или общее, если позиций много)
    if len(inv.items) == 1:
        soder = inv.items[0].name
    else:
        soder = "Работы (услуги) выполнены (оказаны) в полном объёме"
    sv_per_attrs = {"СодОпер": soder}
    if inv.shipment_date_iso:
        sv_per_attrs["ДатаПер"] = _fmt_date_ru(inv.shipment_date_iso)
    sv_per = SubElement(sv_prod_per, "СвПер", sv_per_attrs)

    if inv.basis_number:
        osn_attrs = {
            "РеквНаимДок": inv.basis_name or "Счет",
            "РеквНомерДок": inv.basis_number,
        }
        # если дата не распознана — используем дату основного документа
        basis_date = inv.basis_date_iso or inv.doc_date_iso
        if basis_date:
            osn_attrs["РеквДатаДок"] = _fmt_date_ru(basis_date)
        SubElement(sv_per, "ОснПер", osn_attrs)

    # --- Подписант ---
    last, first, middle = _split_fio(inv.signer_name)
    podp_attrs = {"СпосПодтПолном": "1"}
    if inv.seller.is_ip:
        podp_attrs["Должн"] = "Индивидуальный предприниматель"
    else:
        podp_attrs["Должн"] = inv.signer_position or "Руководитель"
    podp = SubElement(doc, "Подписант", podp_attrs)
    fio_attrs = {"Фамилия": last, "Имя": first}
    if middle:
        fio_attrs["Отчество"] = middle
    SubElement(podp, "ФИО", fio_attrs)

    # сериализация в windows-1251, как у Диадока
    xml_bytes = tostring(root, encoding="utf-8")
    # pretty-print, потом перекодируем
    pretty = minidom.parseString(xml_bytes).toprettyxml(indent="  ", encoding="windows-1251")
    return stem, pretty


# диагностический запуск
if __name__ == "__main__":
    from parser import parse_pdf
    src = r"C:\Users\Olmek amoCRM\Desktop\Акт №МД-2675 от 03.04.26.pdf"
    inv = parse_pdf(src)
    stem, xml = build_xml(inv, pdf_path=src)
    out = rf"C:\Users\Olmek amoCRM\Desktop\pdf2xml\_test.xml"
    with open(out, "wb") as f:
        f.write(xml)
    print("OK ->", out)
