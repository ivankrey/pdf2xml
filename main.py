"""PDF→XML (УПД/Акт ФНС, формат 5.03) — GUI-приложение.

Как пользоваться:
1) Нажать «Открыть PDF»
2) Проверить распознанные поля и, при необходимости, поправить
3) Нажать «Сохранить XML» — файл будет сохранён рядом с PDF
"""
from __future__ import annotations
import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Optional

from parser import parse_pdf, Invoice, Item
from xml_builder import build_xml


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PDF → XML (УПД/Акт ФНС 5.03)")
        self.geometry("980x760")
        self.inv: Optional[Invoice] = None
        self.pdf_path: Optional[str] = None

        self._build_ui()

    # ---------- UI ----------

    def _build_ui(self):
        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        ttk.Button(top, text="Открыть PDF…", command=self.open_pdf).pack(side="left")
        self.lbl_path = ttk.Label(top, text="Файл не выбран", foreground="#666")
        self.lbl_path.pack(side="left", padx=10)

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=4)

        # вкладка «Шапка»
        tab1 = ttk.Frame(nb, padding=10)
        nb.add(tab1, text="Шапка документа")
        self._build_header_tab(tab1)

        # вкладка «Позиции»
        tab2 = ttk.Frame(nb, padding=10)
        nb.add(tab2, text="Позиции")
        self._build_items_tab(tab2)

        # вкладка «Подпись»
        tab3 = ttk.Frame(nb, padding=10)
        nb.add(tab3, text="Подписант / передача")
        self._build_signer_tab(tab3)

        bottom = ttk.Frame(self, padding=8)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="Сохранить XML…", command=self.save_xml).pack(side="right")
        self.lbl_status = ttk.Label(bottom, text="", foreground="#080")
        self.lbl_status.pack(side="left")

    def _build_header_tab(self, parent):
        self.vars = {}

        def row(label, key, width=60):
            fr = ttk.Frame(parent)
            fr.pack(fill="x", pady=2)
            ttk.Label(fr, text=label, width=22).pack(side="left")
            v = tk.StringVar()
            self.vars[key] = v
            ttk.Entry(fr, textvariable=v, width=width).pack(side="left", fill="x", expand=True)

        # документ
        ttk.Label(parent, text="Документ", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(4, 2))
        row("№ документа", "doc_number")
        row("Дата (ISO YYYY-MM-DD)", "doc_date_iso")
        row("Статус УПД (1/2)", "status")

        # продавец
        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=6)
        ttk.Label(parent, text="Продавец", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(4, 2))
        row("Наименование (полное)", "seller_raw_name")
        row("ИНН", "seller_inn")
        row("КПП", "seller_kpp")
        row("Адрес", "seller_address")
        row("ИП? (True/False)", "seller_is_ip")

        # покупатель
        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=6)
        ttk.Label(parent, text="Покупатель", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(4, 2))
        row("Наименование", "buyer_name")
        row("ИНН", "buyer_inn")
        row("КПП", "buyer_kpp")
        row("Адрес", "buyer_address")

        # валюта
        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=6)
        ttk.Label(parent, text="Валюта", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(4, 2))
        row("Наименование", "currency_name")
        row("Код ОКВ", "currency_code")

    def _build_items_tab(self, parent):
        cols = ("num", "name", "unit_code", "unit_name", "qty", "price",
                "sum_without_tax", "tax_rate", "sum_with_tax")
        headers = ("№", "Наименование", "Код ОКЕИ", "Ед.изм.", "Кол-во",
                   "Цена", "Сумма без НДС", "Ставка НДС", "Сумма с НДС")

        self.tree = ttk.Treeview(parent, columns=cols, show="headings", height=12)
        widths = (40, 320, 70, 70, 70, 90, 110, 90, 110)
        for c, h, w in zip(cols, headers, widths):
            self.tree.heading(c, text=h)
            self.tree.column(c, width=w, anchor="w" if c == "name" else "center")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", self._edit_cell)

        ttk.Label(parent, text="Двойной клик по ячейке — редактирование.",
                  foreground="#666").pack(anchor="w", pady=4)

        # итоги
        fr = ttk.Frame(parent)
        fr.pack(fill="x", pady=6)
        ttk.Label(fr, text="Итого без НДС:").pack(side="left")
        self.vars["total_without_tax"] = tk.StringVar()
        ttk.Entry(fr, textvariable=self.vars["total_without_tax"], width=15).pack(side="left", padx=4)

        ttk.Label(fr, text="Итого с НДС:").pack(side="left", padx=(20, 0))
        self.vars["total_with_tax"] = tk.StringVar()
        ttk.Entry(fr, textvariable=self.vars["total_with_tax"], width=15).pack(side="left", padx=4)

    def _build_signer_tab(self, parent):
        def row(label, key, width=60):
            fr = ttk.Frame(parent)
            fr.pack(fill="x", pady=2)
            ttk.Label(fr, text=label, width=28).pack(side="left")
            v = tk.StringVar()
            self.vars[key] = v
            ttk.Entry(fr, textvariable=v, width=width).pack(side="left", fill="x", expand=True)

        ttk.Label(parent, text="Передача", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(4, 2))
        row("Основания передачи", "basis")
        row("Дата отгрузки (ISO)", "shipment_date_iso")

        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=6)
        ttk.Label(parent, text="Подписант", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(4, 2))
        row("ФИО", "signer_name")
        row("Должность / статус (ИП, Директор…)", "signer_position")

    # ---------- логика ----------

    def _edit_cell(self, event):
        """Редактирование ячейки Treeview по двойному клику."""
        row_id = self.tree.identify_row(event.y)
        col_id = self.tree.identify_column(event.x)
        if not row_id or not col_id:
            return
        x, y, w, h = self.tree.bbox(row_id, col_id)
        col_idx = int(col_id.replace("#", "")) - 1
        old = self.tree.set(row_id, self.tree["columns"][col_idx])
        entry = ttk.Entry(self.tree)
        entry.place(x=x, y=y, width=w, height=h)
        entry.insert(0, old)
        entry.focus()

        def save(_=None):
            self.tree.set(row_id, self.tree["columns"][col_idx], entry.get())
            entry.destroy()

        entry.bind("<Return>", save)
        entry.bind("<FocusOut>", save)

    def open_pdf(self):
        path = filedialog.askopenfilename(
            title="Выберите PDF",
            filetypes=[("PDF", "*.pdf"), ("Все файлы", "*.*")],
        )
        if not path:
            return
        try:
            self.inv = parse_pdf(path)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось прочитать PDF:\n{e}")
            return
        self.pdf_path = path
        self.lbl_path.config(text=path)
        self._load_to_ui(self.inv)
        self.lbl_status.config(text="PDF разобран. Проверьте поля и сохраните XML.")

    def _load_to_ui(self, inv: Invoice):
        v = self.vars
        v["doc_number"].set(inv.doc_number)
        v["doc_date_iso"].set(inv.doc_date_iso)
        v["status"].set(inv.status)

        v["seller_raw_name"].set(inv.seller.raw_name)
        v["seller_inn"].set(inv.seller.inn)
        v["seller_kpp"].set(inv.seller.kpp)
        v["seller_address"].set(inv.seller.address_raw)
        v["seller_is_ip"].set(str(inv.seller.is_ip))

        v["buyer_name"].set(inv.buyer.name)
        v["buyer_inn"].set(inv.buyer.inn)
        v["buyer_kpp"].set(inv.buyer.kpp)
        v["buyer_address"].set(inv.buyer.address_raw)

        v["currency_name"].set(inv.currency_name)
        v["currency_code"].set(inv.currency_code)

        v["total_without_tax"].set(inv.total_without_tax)
        v["total_with_tax"].set(inv.total_with_tax)

        v["basis"].set(inv.basis)
        v["shipment_date_iso"].set(inv.shipment_date_iso)
        v["signer_name"].set(inv.signer_name)
        v["signer_position"].set(inv.signer_position)

        # позиции
        for r in self.tree.get_children():
            self.tree.delete(r)
        for it in inv.items:
            self.tree.insert("", "end", values=(
                it.num, it.name, it.unit_code, it.unit_name, it.qty, it.price,
                it.sum_without_tax, it.tax_rate, it.sum_with_tax,
            ))

    def _collect_from_ui(self) -> Invoice:
        v = self.vars
        inv = self.inv or Invoice()

        inv.doc_number = v["doc_number"].get().strip()
        inv.doc_date_iso = v["doc_date_iso"].get().strip()
        inv.status = v["status"].get().strip() or "2"

        inv.seller.raw_name = v["seller_raw_name"].get().strip()
        inv.seller.inn = v["seller_inn"].get().strip()
        inv.seller.kpp = v["seller_kpp"].get().strip()
        inv.seller.address_raw = v["seller_address"].get().strip()
        inv.seller.is_ip = v["seller_is_ip"].get().strip().lower() in ("true", "1", "да", "yes")
        if inv.seller.is_ip:
            # пересчитать ФИО при изменении имени
            name = inv.seller.raw_name
            for pref in ("Индивидуальный предприниматель", "ИП "):
                if name.lower().startswith(pref.lower()):
                    name = name[len(pref):].strip()
                    break
            inv.seller.name = name
            parts = name.split()
            inv.seller.ip_lastname = parts[0] if parts else ""
            inv.seller.ip_firstname = parts[1] if len(parts) > 1 else ""
            inv.seller.ip_middlename = " ".join(parts[2:]) if len(parts) > 2 else ""

        inv.buyer.name = v["buyer_name"].get().strip()
        inv.buyer.raw_name = inv.buyer.name
        inv.buyer.inn = v["buyer_inn"].get().strip()
        inv.buyer.kpp = v["buyer_kpp"].get().strip()
        inv.buyer.address_raw = v["buyer_address"].get().strip()

        inv.currency_name = v["currency_name"].get().strip() or "Российский рубль"
        inv.currency_code = v["currency_code"].get().strip() or "643"

        inv.total_without_tax = v["total_without_tax"].get().strip()
        inv.total_with_tax = v["total_with_tax"].get().strip()

        inv.basis = v["basis"].get().strip()
        inv.shipment_date_iso = v["shipment_date_iso"].get().strip()
        inv.signer_name = v["signer_name"].get().strip()
        inv.signer_position = v["signer_position"].get().strip()

        inv.items = []
        for i, row_id in enumerate(self.tree.get_children(), 1):
            vals = self.tree.item(row_id, "values")
            it = Item(
                num=int(vals[0]) if str(vals[0]).isdigit() else i,
                name=vals[1],
                unit_code=vals[2],
                unit_name=vals[3],
                qty=vals[4],
                price=vals[5],
                sum_without_tax=vals[6],
                tax_rate=vals[7],
                sum_with_tax=vals[8],
            )
            inv.items.append(it)

        return inv

    def save_xml(self):
        if not self.inv:
            messagebox.showwarning("Нет данных", "Сначала откройте PDF.")
            return
        inv = self._collect_from_ui()
        try:
            stem, xml_bytes = build_xml(inv, pdf_path=self.pdf_path or "")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось сформировать XML:\n{e}")
            return

        init_dir = os.path.dirname(self.pdf_path) if self.pdf_path else os.path.expanduser("~")
        init_name = stem + ".xml"
        path = filedialog.asksaveasfilename(
            title="Сохранить XML",
            initialdir=init_dir,
            initialfile=init_name,
            defaultextension=".xml",
            filetypes=[("XML", "*.xml")],
        )
        if not path:
            return
        try:
            with open(path, "wb") as f:
                f.write(xml_bytes)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось сохранить:\n{e}")
            return
        self.lbl_status.config(text=f"Сохранено: {path}")
        messagebox.showinfo("Готово", f"XML сохранён:\n{path}")


if __name__ == "__main__":
    App().mainloop()
