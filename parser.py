"""Парсер PDF-акта (УПД формата ФНС/Диадок) → dict с реквизитами и позициями."""
from __future__ import annotations
import re
from dataclasses import dataclass, field, asdict
from typing import List, Optional
import pdfplumber


# ---------- модели ----------

@dataclass
class Party:
    """Продавец или покупатель."""
    raw_name: str = ""          # как написано в PDF
    is_ip: bool = False         # ИП или ЮЛ
    name: str = ""              # наименование без префикса
    ip_lastname: str = ""       # для ИП
    ip_firstname: str = ""
    ip_middlename: str = ""
    inn: str = ""
    kpp: str = ""
    address_raw: str = ""       # строкой из PDF

    # для банковских реквизитов (только для продавца)
    bank_account: str = ""
    bank_name: str = ""
    bank_bik: str = ""
    bank_corr: str = ""


@dataclass
class Item:
    num: int = 0
    name: str = ""
    unit_code: str = ""         # ОКЕИ, напр. 796
    unit_name: str = ""         # «шт»
    qty: str = ""               # "1"
    price: str = ""             # "17000.00"
    sum_without_tax: str = ""   # "17000.00"
    excise: str = "без акциза"
    tax_rate: str = "без НДС"
    tax_sum: str = "без НДС"
    sum_with_tax: str = ""


@dataclass
class Invoice:
    # шапка
    doc_number: str = ""            # «МД-2675»
    doc_date_raw: str = ""          # «3 апреля 2026»
    doc_date_iso: str = ""          # «2026-04-03»
    status: str = "2"               # статус УПД (1/2)

    seller: Party = field(default_factory=Party)
    buyer: Party = field(default_factory=Party)

    currency_name: str = "Российский рубль"
    currency_code: str = "643"

    items: List[Item] = field(default_factory=list)

    total_without_tax: str = ""
    total_tax: str = "без НДС"
    total_with_tax: str = ""

    # раздел «передача»
    basis: str = ""                 # основания передачи (полная строка)
    basis_name: str = "Счет"        # «Счет» / «Договор» / …
    basis_number: str = ""           # номер документа-основания
    basis_date_iso: str = ""         # дата документа-основания
    shipment_date_raw: str = ""     # «09 апреля 2026»
    shipment_date_iso: str = ""

    signer_name: str = ""           # руководитель / ИП / уполномоченный
    signer_position: str = ""       # «ИП» / должность

    edo_doc_id: str = ""            # GUID документа ЭДО

    # исходный текст (для диагностики)
    raw_page1: str = ""
    raw_page2: str = ""


# ---------- вспомогалки ----------

MONTHS = {
    "января": "01", "февраля": "02", "марта": "03", "апреля": "04",
    "мая": "05", "июня": "06", "июля": "07", "августа": "08",
    "сентября": "09", "октября": "10", "ноября": "11", "декабря": "12",
}


def _parse_ru_date(s: str) -> str:
    """«3 апреля 2026» → «2026-04-03»."""
    s = s.strip()
    m = re.match(r"(\d{1,2})\s+([а-яё]+)\s+(\d{4})", s, re.IGNORECASE)
    if not m:
        return ""
    d, month_name, y = m.groups()
    mm = MONTHS.get(month_name.lower(), "")
    if not mm:
        return ""
    return f"{y}-{mm}-{int(d):02d}"


def _clean_amount(s: str) -> str:
    """«17000,00» → «17000.00»."""
    return s.replace("\u00a0", "").replace(" ", "").replace(",", ".").strip()


def _split_ip_name(full: str) -> tuple[str, str, str]:
    """«Макаров Иван Владимирович» → (фамилия, имя, отчество)."""
    parts = full.strip().split()
    if len(parts) >= 3:
        return parts[0], parts[1], " ".join(parts[2:])
    if len(parts) == 2:
        return parts[0], parts[1], ""
    return full.strip(), "", ""


# ---------- основной парсер ----------

def parse_pdf(path: str) -> Invoice:
    inv = Invoice()

    with pdfplumber.open(path) as pdf:
        pages = [p.extract_text() or "" for p in pdf.pages]
        tables_p1 = pdf.pages[0].extract_tables() if pdf.pages else []

    inv.raw_page1 = pages[0] if pages else ""
    inv.raw_page2 = pages[1] if len(pages) > 1 else ""

    text = "\n".join(pages)

    # номер и дата документа (ищем в первой строке)
    m = re.search(r"№\s*([^\s]+)\s+от\s+(\d{1,2}\s+[а-яё]+\s+\d{4})", inv.raw_page1, re.IGNORECASE)
    if m:
        inv.doc_number = m.group(1).strip()
        inv.doc_date_raw = m.group(2).strip()
        inv.doc_date_iso = _parse_ru_date(inv.doc_date_raw)

    # статус УПД: ищем «документ — 1» / «документ — 2»
    m = re.search(r"Передаточный\s+.*?документ\s*[—–-]\s*([12])", inv.raw_page1, re.IGNORECASE | re.DOTALL)
    if m:
        inv.status = m.group(1)

    # --- продавец ---
    m = re.search(r"Продавец\s+(.+?)\s*\(2\)", inv.raw_page1, re.DOTALL)
    if m:
        raw = re.sub(r"\s+", " ", m.group(1)).strip()
        inv.seller.raw_name = raw
        if raw.lower().startswith("индивидуальный предприниматель"):
            inv.seller.is_ip = True
            name = re.sub(r"^индивидуальный предприниматель\s*", "", raw, flags=re.IGNORECASE).strip()
            inv.seller.name = name
            inv.seller.ip_lastname, inv.seller.ip_firstname, inv.seller.ip_middlename = _split_ip_name(name)
        else:
            inv.seller.name = raw

    m = re.search(r"Адрес\s+([^\n]+?)\s*\(2а\)", inv.raw_page1)
    if m:
        inv.seller.address_raw = re.sub(r"\s+", " ", m.group(1)).strip()

    m = re.search(r"ИНН/КПП\s+([\d\-—–]+)\s*/\s*([\d\-—–]+)\s*\(2б\)", inv.raw_page1)
    if m:
        inv.seller.inn = m.group(1).strip()
        kpp = m.group(2).strip()
        inv.seller.kpp = "" if kpp in ("—", "–", "-") else kpp

    m = re.search(r"Банковские реквизиты\s+(.+?)\n", inv.raw_page1)
    if m:
        bank_line = m.group(1).strip()
        mb = re.search(r"Р/с\s*([\d\-—–]+)", bank_line)
        if mb: inv.seller.bank_account = mb.group(1)
        mb = re.search(r"БИК\s*(\d+)", bank_line)
        if mb: inv.seller.bank_bik = mb.group(1)
        mb = re.search(r"к/с\s*(\d+)", bank_line)
        if mb: inv.seller.bank_corr = mb.group(1)
        mb = re.search(r",\s*([^,]+?),\s*БИК", bank_line)
        if mb:
            # сохраняем как в PDF — с кавычками-ёлочками, без выреза
            inv.seller.bank_name = mb.group(1).strip()

    # --- покупатель ---
    m = re.search(r"Покупатель\s+(.+?)\s*\(6\)", inv.raw_page1, re.DOTALL)
    if m:
        raw = re.sub(r"\s+", " ", m.group(1)).strip()
        inv.buyer.raw_name = raw
        # кавычки — часть наименования ЮЛ, оставляем
        inv.buyer.name = raw
        inv.buyer.is_ip = raw.lower().startswith("индивидуальный предприниматель") or raw.lower().startswith("ип ")

    m = re.search(r"Адрес\s+([^\n]+?)\s*\(6а\)", inv.raw_page1)
    if m:
        inv.buyer.address_raw = re.sub(r"\s+", " ", m.group(1)).strip()

    m = re.search(r"ИНН/КПП\s+([\d\-—–]+)\s*/\s*([\d\-—–]+)\s*\(6б\)", inv.raw_page1)
    if m:
        inv.buyer.inn = m.group(1).strip()
        kpp = m.group(2).strip()
        inv.buyer.kpp = "" if kpp in ("—", "–", "-") else kpp

    # --- валюта --- «Валюта: наименование, код Российский рубль, 643 (7)»
    m = re.search(r"Валюта:\s*наименование,\s*код\s+(.+?),\s*(\d{3})\s*\(7\)", inv.raw_page1)
    if m:
        inv.currency_name = m.group(1).strip()
        inv.currency_code = m.group(2).strip()

    # --- позиции: берём из первой таблицы. Строки с цифровым №п/п ---
    if tables_p1:
        tbl = tables_p1[0]
        for row in tbl:
            if not row: continue
            # первая ячейка вида "— 1" или "1"
            first = (row[0] or "").strip()
            m = re.match(r"^[—–-]?\s*(\d+)\s*$", first)
            if not m:
                continue
            try:
                it = Item()
                it.num = int(m.group(1))
                it.name = (row[1] or "").replace("\n", " ").strip()
                it.unit_code = (row[3] or "").strip()
                it.unit_name = (row[4] or "").strip()
                it.qty = _clean_amount((row[5] or "").strip())
                it.price = _clean_amount((row[6] or "").strip())
                it.sum_without_tax = _clean_amount((row[7] or "").strip())
                it.excise = (row[8] or "").strip() or "без акциза"
                it.tax_rate = (row[9] or "").strip() or "без НДС"
                it.tax_sum = (row[10] or "").strip() or "без НДС"
                it.sum_with_tax = _clean_amount((row[11] or "").strip())
                inv.items.append(it)
            except (IndexError, ValueError):
                continue

    # --- итоги ---
    m = re.search(r"Всего к оплате \(9\)\s+([\d\s.,]+)\s+x\s+x\s+([^\s]+(?:\s+НДС)?)\s+([\d\s.,]+)", inv.raw_page1)
    if m:
        inv.total_without_tax = _clean_amount(m.group(1))
        inv.total_tax = m.group(2).strip()
        inv.total_with_tax = _clean_amount(m.group(3))

    # --- страница 2: основания, подписант, дата отгрузки ---
    p2 = inv.raw_page2

    m = re.search(r"Основания передачи \(сдачи\) / получения \(приемки\)\s+(.+?)\s*\(10\)", p2, re.DOTALL)
    if m:
        inv.basis = re.sub(r"\s+", " ", m.group(1)).strip()
        # «Счет на виджеты №МД-2675» → наим/номер
        mb = re.match(r"([А-Яа-яЁё\s\-]+?)\s*№\s*(\S+)(?:\s+от\s+(\d{1,2}\s+[а-яё]+\s+\d{4}))?", inv.basis)
        if mb:
            raw_name = mb.group(1).strip()
            # берём первое слово как тип документа: "Счет на виджеты" → "Счет"
            inv.basis_name = raw_name.split()[0] if raw_name else "Счет"
            inv.basis_number = mb.group(2).strip()
            if mb.group(3):
                inv.basis_date_iso = _parse_ru_date(mb.group(3))

    m = re.search(r"Дата отгрузки, передачи \(сдачи\)\s+(\d{1,2}\s+[а-яё]+\s+\d{4})", p2, re.IGNORECASE)
    if m:
        inv.shipment_date_raw = m.group(1).strip()
        inv.shipment_date_iso = _parse_ru_date(inv.shipment_date_raw)

    # подписант: «ИП Электронная подпись Макаров Иван Владимирович (15)» или «… (12)»
    m = re.search(r"\n\s*(\S+)\s+Электронная подпись\s+(.+?)\s*\((?:12|15)\)", p2)
    if m:
        inv.signer_position = m.group(1).strip()
        inv.signer_name = re.sub(r"\s+", " ", m.group(2)).strip()
    elif inv.seller.is_ip:
        inv.signer_position = "ИП"
        inv.signer_name = inv.seller.name

    m = re.search(r"Идентификатор документа\s+([a-f0-9\-]{36})", p2)
    if m:
        inv.edo_doc_id = m.group(1)

    return inv


# диагностический запуск
if __name__ == "__main__":
    import sys, json
    src = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\Olmek amoCRM\Desktop\Акт №МД-2675 от 03.04.26.pdf"
    inv = parse_pdf(src)
    d = asdict(inv)
    d.pop("raw_page1", None)
    d.pop("raw_page2", None)
    out = r"C:\Users\Olmek amoCRM\Desktop\pdf2xml\_parsed.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    print("OK ->", out)
