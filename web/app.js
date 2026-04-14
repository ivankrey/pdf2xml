/* =======================================================================
   PDF → XML (УПД/Акт ФНС 5.03) — веб-версия.
   Работает полностью в браузере. PDF извлекается через pdf.js (Mozilla).
   XML формируется в кодировке windows-1251 и скачивается как файл.
   ======================================================================= */

/* ------------------------- windows-1251 encoder ------------------------- */
// Только спец-символы; основная кириллица — через формулу code - 0x0350.
const CP1251 = {
  0x0402:0x80, 0x0403:0x81, 0x201A:0x82, 0x0453:0x83, 0x201E:0x84,
  0x2026:0x85, 0x2020:0x86, 0x2021:0x87, 0x20AC:0x88, 0x2030:0x89,
  0x0409:0x8A, 0x2039:0x8B, 0x040A:0x8C, 0x040C:0x8D, 0x040B:0x8E,
  0x040F:0x8F, 0x0452:0x90, 0x2018:0x91, 0x2019:0x92, 0x201C:0x93,
  0x201D:0x94, 0x2022:0x95, 0x2013:0x96, 0x2014:0x97, 0x2122:0x99,
  0x0459:0x9A, 0x203A:0x9B, 0x045A:0x9C, 0x045C:0x9D, 0x045B:0x9E,
  0x045F:0x9F, 0x00A0:0xA0, 0x040E:0xA1, 0x045E:0xA2, 0x0408:0xA3,
  0x00A4:0xA4, 0x0490:0xA5, 0x00A6:0xA6, 0x00A7:0xA7, 0x0401:0xA8,
  0x00A9:0xA9, 0x0404:0xAA, 0x00AB:0xAB, 0x00AC:0xAC, 0x00AD:0xAD,
  0x00AE:0xAE, 0x0407:0xAF, 0x00B0:0xB0, 0x00B1:0xB1, 0x0406:0xB2,
  0x0456:0xB3, 0x0491:0xB4, 0x00B5:0xB5, 0x00B6:0xB6, 0x00B7:0xB7,
  0x0451:0xB8, 0x2116:0xB9, 0x0454:0xBA, 0x00BB:0xBB, 0x0458:0xBC,
  0x0405:0xBD, 0x0455:0xBE, 0x0457:0xBF,
};
function encodeCp1251(str) {
  const out = new Uint8Array(str.length * 2); // с запасом
  let k = 0;
  for (let i = 0; i < str.length; i++) {
    const code = str.charCodeAt(i);
    if (code < 0x80) out[k++] = code;
    else if (CP1251[code] !== undefined) out[k++] = CP1251[code];
    else if (code >= 0x0410 && code <= 0x044F) out[k++] = code - 0x0350;
    else out[k++] = 0x3F; // ?
  }
  return out.slice(0, k);
}

function xmlEscape(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function attrs(obj) {
  const parts = [];
  for (const [k, v] of Object.entries(obj)) {
    if (v === undefined || v === null || v === '') continue;
    parts.push(`${k}="${xmlEscape(v)}"`);
  }
  return parts.length ? ' ' + parts.join(' ') : '';
}

/* ------------------------- helpers ------------------------- */

const MONTHS = {
  'января':'01','февраля':'02','марта':'03','апреля':'04',
  'мая':'05','июня':'06','июля':'07','августа':'08',
  'сентября':'09','октября':'10','ноября':'11','декабря':'12',
};

function parseRuDate(s) {
  if (!s) return '';
  const m = s.trim().match(/(\d{1,2})\s+([а-яёА-ЯЁ]+)\s+(\d{4})/);
  if (!m) return '';
  const mm = MONTHS[m[2].toLowerCase()];
  if (!mm) return '';
  return `${m[3]}-${mm}-${String(+m[1]).padStart(2,'0')}`;
}

function fmtDateRu(iso) {
  if (!iso) return '';
  const [y,m,d] = iso.split('-');
  return `${d}.${m}.${y}`;
}

function cleanAmount(s) {
  return String(s || '').replace(/\u00a0/g,'').replace(/\s/g,'').replace(',','.').trim();
}

function fmtAmount(s) {
  const f = parseFloat(s);
  return Number.isFinite(f) ? f.toFixed(2) : '0.00';
}

function fmtQty(s) {
  const f = parseFloat(cleanAmount(s));
  if (!Number.isFinite(f)) return s || '0';
  if (f === Math.floor(f)) return String(f);
  return f.toFixed(6).replace(/0+$/,'').replace(/\.$/,'');
}

function splitFio(full) {
  const parts = (full || '').trim().split(/\s+/);
  if (parts.length >= 3) return [parts[0], parts[1], parts.slice(2).join(' ')];
  if (parts.length === 2) return [parts[0], parts[1], ''];
  return [full || '', '', ''];
}

/* ------------------------- PDF → текст (pdf.js) ------------------------- */

async function extractPdfPages(file) {
  const buf = await file.arrayBuffer();
  const pdf = await pdfjsLib.getDocument({ data: buf }).promise;
  const pages = [];
  for (let i = 1; i <= pdf.numPages; i++) {
    const page = await pdf.getPage(i);
    const content = await page.getTextContent();
    // группируем по строкам через округление y
    const items = content.items.map(it => ({
      s: it.str,
      x: it.transform[4],
      y: Math.round(it.transform[5]),
    }));
    const byY = new Map();
    for (const it of items) {
      const bucket = [...byY.keys()].find(k => Math.abs(k - it.y) <= 2);
      const key = bucket !== undefined ? bucket : it.y;
      if (!byY.has(key)) byY.set(key, []);
      byY.get(key).push(it);
    }
    const sortedKeys = [...byY.keys()].sort((a, b) => b - a);
    const lines = sortedKeys.map(k =>
      byY.get(k).sort((a, b) => a.x - b.x).map(i => i.s).join(' ').replace(/\s+/g, ' ').trim()
    ).filter(Boolean);
    pages.push(lines.join('\n'));
  }
  return pages;
}

/* ------------------------- парсинг документа ------------------------- */

function parseInvoice(pages) {
  const p1 = pages[0] || '';
  const p2 = pages[1] || '';
  const full = pages.join('\n');

  const inv = {
    doc_number: '', doc_date_iso: '', status: '2',
    seller: { is_ip: false, raw_name: '', name: '', inn: '', kpp: '', address_raw: '',
              bank_account: '', bank_name: '', bank_bik: '', bank_corr: '' },
    buyer:  { is_ip: false, raw_name: '', name: '', inn: '', kpp: '', address_raw: '' },
    currency_name: 'Российский рубль', currency_code: '643',
    items: [],
    total_without_tax: '', total_with_tax: '',
    basis: '', basis_name: 'Счет', basis_number: '', basis_date_iso: '',
    shipment_date_iso: '',
    signer_name: '', signer_position: '',
  };

  let m;

  // номер и дата
  m = p1.match(/№\s*(\S+)\s+от\s+(\d{1,2}\s+[а-яё]+\s+\d{4})/i);
  if (m) {
    inv.doc_number = m[1].trim();
    inv.doc_date_iso = parseRuDate(m[2]);
  }

  // статус
  m = p1.match(/Передаточный\s+[\s\S]*?документ\s*[—–-]\s*([12])/i);
  if (m) inv.status = m[1];

  // продавец
  m = p1.match(/Продавец\s+([^\n]+?)\s*\(2\)/);
  if (m) {
    const raw = m[1].replace(/\s+/g, ' ').trim();
    inv.seller.raw_name = raw;
    if (/^индивидуальный предприниматель/i.test(raw)) {
      inv.seller.is_ip = true;
      inv.seller.name = raw.replace(/^индивидуальный предприниматель\s*/i, '').trim();
    } else {
      inv.seller.name = raw;
    }
  }

  m = p1.match(/Адрес\s+([^\n]+?)\s*\(2а\)/);
  if (m) inv.seller.address_raw = m[1].replace(/\s+/g, ' ').trim();

  m = p1.match(/ИНН\/КПП\s+([\d—–\-]+)\s*\/\s*([\d—–\-]+)\s*\(2б\)/);
  if (m) {
    inv.seller.inn = m[1].trim();
    const kpp = m[2].trim();
    inv.seller.kpp = /^[—–\-]$/.test(kpp) ? '' : kpp;
  }

  m = p1.match(/Банковские реквизиты\s+([^\n]+)/);
  if (m) {
    const bl = m[1];
    const mb1 = bl.match(/Р\/с\s*([\d—–\-]+)/);
    if (mb1) inv.seller.bank_account = mb1[1];
    const mb2 = bl.match(/БИК\s*(\d+)/);
    if (mb2) inv.seller.bank_bik = mb2[1];
    const mb3 = bl.match(/к\/с\s*(\d+)/);
    if (mb3) inv.seller.bank_corr = mb3[1];
    const mb4 = bl.match(/,\s*([^,]+?),\s*БИК/);
    if (mb4) inv.seller.bank_name = mb4[1].trim();
  }

  // покупатель
  m = p1.match(/Покупатель\s+([^\n]+?)\s*\(6\)/);
  if (m) {
    const raw = m[1].replace(/\s+/g, ' ').trim();
    inv.buyer.raw_name = raw;
    inv.buyer.name = raw;
    inv.buyer.is_ip = /^(индивидуальный предприниматель|ип\s)/i.test(raw);
  }

  m = p1.match(/Адрес\s+([^\n]+?)\s*\(6а\)/);
  if (m) inv.buyer.address_raw = m[1].replace(/\s+/g, ' ').trim();

  m = p1.match(/ИНН\/КПП\s+([\d—–\-]+)\s*\/\s*([\d—–\-]+)\s*\(6б\)/);
  if (m) {
    inv.buyer.inn = m[1].trim();
    const kpp = m[2].trim();
    inv.buyer.kpp = /^[—–\-]$/.test(kpp) ? '' : kpp;
  }

  // валюта
  m = p1.match(/Валюта:\s*наименование,\s*код\s+(.+?),\s*(\d{3})\s*\(7\)/);
  if (m) {
    inv.currency_name = m[1].trim();
    inv.currency_code = m[2].trim();
  }

  // позиции — ищем строку между шапкой таблицы («А 1 1a …») и «Всего к оплате»
  const tableBlock = p1.match(/А\s+1\s+1а?\s+1б[\s\S]+?Всего к оплате/i);
  if (tableBlock) {
    const lines = tableBlock[0].split('\n');
    let n = 1;
    for (const line of lines) {
      // строка позиции: обычно начинается «— N Наименование …» или «N Наименование»
      const mi = line.match(/^(?:[—–\-]\s+)?(\d+)\s+(.+?)\s+([—–\-]|\d+)\s+(\d{3})\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+(?:\s+\S+)?)\s+(без НДС|\d+%?|без\s+НДС)/);
      if (mi) {
        inv.items.push({
          num: +mi[1] || n++,
          name: mi[2].trim(),
          unit_code: mi[4],
          unit_name: mi[5],
          qty: cleanAmount(mi[6]),
          price: cleanAmount(mi[7]),
          sum_without_tax: cleanAmount(mi[8]),
          excise: 'без акциза',
          tax_rate: 'без НДС',
          tax_sum: 'без НДС',
          sum_with_tax: cleanAmount(mi[8]),
        });
      }
    }
  }

  // fallback для единственной позиции — если таблицу не удалось распарсить
  if (inv.items.length === 0) {
    m = p1.match(/^([—–\-]\s+)?(\d+)\s+([\s\S]+?)\s+(\d{3})\s+([А-яa-z]{1,8})\s+(\d+(?:[.,]\d+)?)\s+(\d+(?:[.,]\d+)?)\s+(\d+(?:[.,]\d+)?)\s+(Без акциза|без акциза)\s+(без НДС)/m);
    if (m) {
      inv.items.push({
        num: +m[2] || 1,
        name: m[3].replace(/\s+/g, ' ').trim(),
        unit_code: m[4],
        unit_name: m[5],
        qty: cleanAmount(m[6]),
        price: cleanAmount(m[7]),
        sum_without_tax: cleanAmount(m[8]),
        excise: m[9],
        tax_rate: 'без НДС',
        tax_sum: 'без НДС',
        sum_with_tax: cleanAmount(m[8]),
      });
    }
  }

  // итоги
  m = p1.match(/Всего к оплате \(9\)\s+([\d\s.,]+)\s+x\s+x\s+(\S+(?:\s+НДС)?)\s+([\d\s.,]+)/);
  if (m) {
    inv.total_without_tax = cleanAmount(m[1]);
    inv.total_with_tax = cleanAmount(m[3]);
  } else if (inv.items.length) {
    // если не вышло — считаем сами
    const sum = inv.items.reduce((s, i) => s + (parseFloat(cleanAmount(i.sum_without_tax)) || 0), 0);
    inv.total_without_tax = sum.toFixed(2);
    inv.total_with_tax = sum.toFixed(2);
  }

  // основания передачи
  m = p2.match(/Основания передачи \(сдачи\) \/ получения \(приемки\)\s+([\s\S]+?)\s*\(10\)/);
  if (m) {
    inv.basis = m[1].replace(/\s+/g, ' ').trim();
    const mb = inv.basis.match(/([А-Яа-яЁё\s\-]+?)\s*№\s*(\S+)(?:\s+от\s+(\d{1,2}\s+[а-яё]+\s+\d{4}))?/);
    if (mb) {
      const nameRaw = mb[1].trim();
      inv.basis_name = nameRaw ? nameRaw.split(/\s+/)[0] : 'Счет';
      inv.basis_number = mb[2].trim();
      if (mb[3]) inv.basis_date_iso = parseRuDate(mb[3]);
    }
  }

  // дата отгрузки
  m = p2.match(/Дата отгрузки, передачи \(сдачи\)\s+(\d{1,2}\s+[а-яё]+\s+\d{4})/i);
  if (m) inv.shipment_date_iso = parseRuDate(m[1]);

  // подписант
  m = p2.match(/(\S+)\s+Электронная подпись\s+([^\n(]+?)\s*\((?:12|15)\)/);
  if (m) {
    inv.signer_position = m[1].trim();
    inv.signer_name = m[2].replace(/\s+/g, ' ').trim();
  } else if (inv.seller.is_ip) {
    inv.signer_position = 'ИП';
    inv.signer_name = inv.seller.name;
  }

  return inv;
}

/* ------------------------- разбор адреса (для АдрРФ) ------------------------- */

const FED_CITIES = {
  'москва': { code: '77', name: 'г. Москва' },
  'санкт-петербург': { code: '78', name: 'г. Санкт-Петербург' },
  'севастополь': { code: '92', name: 'г. Севастополь' },
};

function parseAddress(addr) {
  if (!addr) return { _fallback: true, text: '' };
  let s = addr.trim();
  const out = {};

  const mi = s.match(/\b(\d{6})\b/);
  if (mi) {
    out['Индекс'] = mi[1];
    s = (s.slice(0, mi.index) + s.slice(mi.index + mi[0].length)).replace(/^[\s,]+|[\s,]+$/g,'');
  }

  let region = null;
  const low = s.toLowerCase();
  for (const [key, v] of Object.entries(FED_CITIES)) {
    if (low.includes(key)) { region = v; break; }
  }
  if (!region) return { _fallback: true, text: addr };

  out['КодРегион'] = region.code;
  out['НаимРегион'] = region.name;
  s = s.replace(/г\.?\s*[А-ЯЁа-яё\-]+/i, '').replace(/^[\s,]+|[\s,]+$/g,'');

  let mStreet = s.match(/(ул\.|пер\.|пр-?кт\.?|шоссе|б-р|наб\.?|пл\.?)\s*([А-ЯЁа-яё\-\d ]+?)(?=,|$)/i);
  if (mStreet) {
    const pref = mStreet[1];
    const street = mStreet[2].trim();
    out['Улица'] = /пер/i.test(pref) ? `${pref} ${street}` : street;
    s = (s.slice(0, mStreet.index) + s.slice(mStreet.index + mStreet[0].length)).replace(/^[\s,]+|[\s,]+$/g,'');
  }

  let mHouse = s.match(/д\.?\s*(\d+(?:\s*[,\/]?\s*к\.?\s*\d+)?)/i);
  if (mHouse) {
    let dom = mHouse[1].replace(/\s+/g, '');
    dom = dom.replace(/,к\./, ', к.');
    out['Дом'] = dom;
    s = (s.slice(0, mHouse.index) + s.slice(mHouse.index + mHouse[0].length)).replace(/^[\s,]+|[\s,]+$/g,'');
  }

  let mKv = s.match(/(кв\.?|офис|помещ\.?)\s*(\S+)/i);
  if (mKv) {
    out['Кварт'] = mKv[2].replace(/[,.]$/, '');
    s = (s.slice(0, mKv.index) + s.slice(mKv.index + mKv[0].length)).replace(/^[\s,]+|[\s,]+$/g,'');
  }

  const rest = s.replace(/^[\s,]+|[\s,]+$/g,'').trim();
  if (rest) out['Район'] = rest;

  return out;
}

/* ------------------------- XML builder ------------------------- */

function naimSubj(p) {
  if (p.is_ip) return `${p.name}, ИНН ${p.inn}`.trim();
  const parts = [p.name.trim()];
  if (p.inn) parts.push(`ИНН ${p.inn}`);
  if (p.kpp) parts.push(`КПП ${p.kpp}`);
  return parts.join(', ');
}

function buildAddress(addr) {
  const parsed = parseAddress(addr);
  if (parsed._fallback) {
    return `<Адрес><АдрИнф${attrs({КодСтр:'643', АдрТекст: parsed.text || addr})}/></Адрес>`;
  }
  const order = ['КодРегион','НаимРегион','Индекс','Район','Улица','Дом','Кварт'];
  const o = {};
  for (const k of order) if (parsed[k]) o[k] = parsed[k];
  return `<Адрес><АдрРФ${attrs(o)}/></Адрес>`;
}

function buildParty(p) {
  const addr = p.address_raw ? buildAddress(p.address_raw) : '';
  let idsv;
  if (p.is_ip) {
    const [last, first, middle] = splitFio(p.name);
    const fio = { Фамилия: last, Имя: first };
    if (middle) fio['Отчество'] = middle;
    idsv = `<ИдСв><СвИП${attrs({ИННФЛ: p.inn})}><ФИО${attrs(fio)}/></СвИП></ИдСв>`;
  } else {
    const o = { НаимОрг: p.name, ИННЮЛ: p.inn };
    if (p.kpp) o['КПП'] = p.kpp;
    idsv = `<ИдСв><СвЮЛУч${attrs(o)}/></ИдСв>`;
  }
  let bank = '';
  if (p.bank_account || p.bank_name) {
    const svb = {};
    if (p.bank_name) svb['НаимБанк'] = p.bank_name;
    if (p.bank_bik) svb['БИК'] = p.bank_bik;
    if (p.bank_corr) svb['КорСчет'] = p.bank_corr;
    bank = `<БанкРекв${attrs({НомерСчета: p.bank_account || ''})}><СвБанк${attrs(svb)}/></БанкРекв>`;
  }
  return idsv + addr + bank;
}

function buildXml(inv, pdfName) {
  const now = new Date();
  const pad = n => String(n).padStart(2, '0');
  const stem = pdfName ? pdfName.replace(/\.pdf$/i, '') : `doc_${now.getTime()}`;

  const DOC_POFACT = 'Документ об отгрузке товаров (выполнении работ), передаче имущественных прав (документ об оказании услуг)';
  const DOC_NAIM = 'Счет-фактура и документ об отгрузке товаров (выполнении работ), передаче имущественных прав (документ об оказании услуг)';

  const docAttrs = attrs({
    КНД: '1115131',
    ВремИнфПр: `${pad(now.getHours())}.${pad(now.getMinutes())}.${pad(now.getSeconds())}`,
    ДатаИнфПр: fmtDateRu(inv.doc_date_iso) || `${pad(now.getDate())}.${pad(now.getMonth()+1)}.${now.getFullYear()}`,
    Функция: 'ДОП',
    ПоФактХЖ: DOC_POFACT,
    НаимДокОпр: DOC_NAIM,
    НаимЭконСубСост: naimSubj(inv.seller),
  });

  const rowsXml = inv.items.map(it => {
    const svAttrs = attrs({
      НомСтр: String(it.num),
      НалСт: 'без НДС',
      НаимТов: it.name,
      ОКЕИ_Тов: it.unit_code || '796',
      НаимЕдИзм: it.unit_name || '',
      КолТов: fmtQty(it.qty),
      ЦенаТов: fmtAmount(it.price),
      СтТовБезНДС: fmtAmount(it.sum_without_tax),
      СтТовУчНал: fmtAmount(it.sum_with_tax || it.sum_without_tax),
    });
    return `<СведТов${svAttrs}>` +
      `<ДопСведТов/>` +
      `<Акциз><БезАкциз>без акциза</БезАкциз></Акциз>` +
      `<СумНал><БезНДС>без НДС</БезНДС></СумНал>` +
      `</СведТов>`;
  }).join('');

  const vsego = attrs({
    СтТовБезНДСВсего: fmtAmount(inv.total_without_tax),
    СтТовУчНалВсего: fmtAmount(inv.total_with_tax),
  });

  const soder = inv.items.length === 1
    ? inv.items[0].name
    : 'Работы (услуги) выполнены (оказаны) в полном объёме';

  const svPer = attrs({ СодОпер: soder, ДатаПер: fmtDateRu(inv.shipment_date_iso) });

  let osnPer = '';
  if (inv.basis_number) {
    const basisDate = inv.basis_date_iso || inv.doc_date_iso;
    osnPer = `<ОснПер${attrs({
      РеквНаимДок: inv.basis_name || 'Счет',
      РеквНомерДок: inv.basis_number,
      РеквДатаДок: fmtDateRu(basisDate),
    })}/>`;
  }

  const [last, first, middle] = splitFio(inv.signer_name);
  const podpAttrs = attrs({
    СпосПодтПолном: '1',
    Должн: inv.seller.is_ip ? 'Индивидуальный предприниматель' : (inv.signer_position || 'Руководитель'),
  });
  const fioAttrs = attrs({ Фамилия: last, Имя: first, Отчество: middle });

  const xml =
    `<?xml version="1.0" encoding="windows-1251"?>\n` +
    `<Файл${attrs({ИдФайл: stem, ВерсФорм: '5.03', ВерсПрог: 'pdf2xml-web 1.0'})}>\n` +
    `  <Документ${docAttrs}>\n` +
    `    <СвСчФакт${attrs({НомерДок: inv.doc_number, ДатаДок: fmtDateRu(inv.doc_date_iso)})}>\n` +
    `      <СвПрод>${buildParty(inv.seller)}</СвПрод>\n` +
    `      <СвПокуп>${buildParty(inv.buyer)}</СвПокуп>\n` +
    `      <ДенИзм${attrs({КодОКВ: inv.currency_code || '643', НаимОКВ: inv.currency_name || 'Российский рубль'})}/>\n` +
    `    </СвСчФакт>\n` +
    `    <ТаблСчФакт>\n` +
    `      ${rowsXml}\n` +
    `      <ВсегоОпл${vsego}><СумНалВсего><БезНДС>без НДС</БезНДС></СумНалВсего></ВсегоОпл>\n` +
    `    </ТаблСчФакт>\n` +
    `    <СвПродПер><СвПер${svPer}>${osnPer}</СвПер></СвПродПер>\n` +
    `    <Подписант${podpAttrs}><ФИО${fioAttrs}/></Подписант>\n` +
    `  </Документ>\n` +
    `</Файл>\n`;

  return { stem, bytes: encodeCp1251(xml) };
}

/* ------------------------- UI ------------------------- */

const state = { inv: null, pdfName: '' };
const FIELDS = [
  'doc_number','doc_date_iso','status',
  'seller_raw_name','seller_inn','seller_kpp','seller_address','seller_is_ip',
  'buyer_name','buyer_inn','buyer_kpp','buyer_address',
  'currency_name','currency_code',
  'total_without_tax','total_with_tax',
  'basis','shipment_date_iso','signer_name','signer_position',
];

function el(sel) { return document.querySelector(sel); }
function els(sel) { return [...document.querySelectorAll(sel)]; }

function loadToForm(inv) {
  const v = {
    doc_number: inv.doc_number,
    doc_date_iso: inv.doc_date_iso,
    status: inv.status,
    seller_raw_name: inv.seller.raw_name,
    seller_inn: inv.seller.inn,
    seller_kpp: inv.seller.kpp,
    seller_address: inv.seller.address_raw,
    seller_is_ip: inv.seller.is_ip ? 'true' : 'false',
    buyer_name: inv.buyer.name,
    buyer_inn: inv.buyer.inn,
    buyer_kpp: inv.buyer.kpp,
    buyer_address: inv.buyer.address_raw,
    currency_name: inv.currency_name,
    currency_code: inv.currency_code,
    total_without_tax: inv.total_without_tax,
    total_with_tax: inv.total_with_tax,
    basis: inv.basis,
    shipment_date_iso: inv.shipment_date_iso,
    signer_name: inv.signer_name,
    signer_position: inv.signer_position,
  };
  for (const f of FIELDS) {
    const input = el(`[data-field="${f}"]`);
    if (input) input.value = v[f] ?? '';
  }

  const tbody = el('#items-table tbody');
  tbody.innerHTML = '';
  for (const it of inv.items) {
    const tr = document.createElement('tr');
    const cells = [it.num, it.name, it.unit_code, it.unit_name, it.qty, it.price,
                   it.sum_without_tax, it.tax_rate, it.sum_with_tax];
    for (let i = 0; i < cells.length; i++) {
      const td = document.createElement('td');
      td.textContent = cells[i] ?? '';
      if (i !== 0) td.contentEditable = 'true';
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
}

function collectFromForm() {
  const get = f => (el(`[data-field="${f}"]`)?.value ?? '').trim();
  const inv = state.inv || {};
  inv.doc_number = get('doc_number');
  inv.doc_date_iso = get('doc_date_iso');
  inv.status = get('status') || '2';

  inv.seller = inv.seller || {};
  inv.seller.raw_name = get('seller_raw_name');
  inv.seller.inn = get('seller_inn');
  inv.seller.kpp = get('seller_kpp');
  inv.seller.address_raw = get('seller_address');
  inv.seller.is_ip = get('seller_is_ip') === 'true';
  if (inv.seller.is_ip) {
    let name = inv.seller.raw_name;
    name = name.replace(/^(индивидуальный предприниматель|ип)\s*/i, '').trim();
    inv.seller.name = name;
  } else {
    inv.seller.name = inv.seller.raw_name;
  }

  inv.buyer = inv.buyer || {};
  inv.buyer.name = get('buyer_name');
  inv.buyer.raw_name = inv.buyer.name;
  inv.buyer.inn = get('buyer_inn');
  inv.buyer.kpp = get('buyer_kpp');
  inv.buyer.address_raw = get('buyer_address');

  inv.currency_name = get('currency_name') || 'Российский рубль';
  inv.currency_code = get('currency_code') || '643';
  inv.total_without_tax = get('total_without_tax');
  inv.total_with_tax = get('total_with_tax');
  inv.basis = get('basis');
  inv.shipment_date_iso = get('shipment_date_iso');
  inv.signer_name = get('signer_name');
  inv.signer_position = get('signer_position');

  // позиции из таблицы
  inv.items = [];
  const rows = els('#items-table tbody tr');
  rows.forEach((tr, idx) => {
    const c = [...tr.children].map(td => td.textContent.trim());
    inv.items.push({
      num: +c[0] || (idx + 1),
      name: c[1],
      unit_code: c[2],
      unit_name: c[3],
      qty: c[4],
      price: c[5],
      sum_without_tax: c[6],
      tax_rate: c[7] || 'без НДС',
      sum_with_tax: c[8],
    });
  });

  // если в inv ещё нет basis_name/number — повторно распарсим
  if (inv.basis) {
    const mb = inv.basis.match(/([А-Яа-яЁё\s\-]+?)\s*№\s*(\S+)(?:\s+от\s+(\d{1,2}\s+[а-яё]+\s+\d{4}))?/);
    if (mb) {
      inv.basis_name = (mb[1].trim().split(/\s+/)[0]) || 'Счет';
      inv.basis_number = mb[2].trim();
      inv.basis_date_iso = mb[3] ? parseRuDate(mb[3]) : (inv.basis_date_iso || '');
    }
  }
  return inv;
}

async function onFile(file) {
  if (!file) return;
  el('#file-status').textContent = `Читаю ${file.name}…`;
  try {
    const pages = await extractPdfPages(file);
    const inv = parseInvoice(pages);
    state.inv = inv;
    state.pdfName = file.name;
    loadToForm(inv);
    el('#drop-zone').classList.add('hidden');
    el('#form-section').classList.remove('hidden');
  } catch (e) {
    console.error(e);
    el('#file-status').textContent = `Ошибка: ${e.message}`;
  }
}

function onSave() {
  const inv = collectFromForm();
  const { stem, bytes } = buildXml(inv, state.pdfName);
  const blob = new Blob([bytes], { type: 'application/xml' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${stem}.xml`;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 1000);
}

function wireUp() {
  // drop zone
  const dz = el('#drop-zone');
  const input = el('#file-input');
  input.addEventListener('change', e => onFile(e.target.files[0]));
  dz.addEventListener('dragover', e => { e.preventDefault(); dz.classList.add('drag'); });
  dz.addEventListener('dragleave', () => dz.classList.remove('drag'));
  dz.addEventListener('drop', e => {
    e.preventDefault();
    dz.classList.remove('drag');
    const f = e.dataTransfer.files[0];
    if (f && f.type === 'application/pdf') onFile(f);
    else el('#file-status').textContent = 'Нужен PDF-файл';
  });

  // вкладки
  els('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      els('.tab-btn').forEach(b => b.classList.remove('active'));
      els('.tab-content').forEach(c => c.classList.remove('active'));
      btn.classList.add('active');
      el('#tab-' + btn.dataset.tab).classList.add('active');
    });
  });

  el('#btn-save').addEventListener('click', onSave);
  el('#btn-new').addEventListener('click', () => {
    state.inv = null;
    state.pdfName = '';
    input.value = '';
    el('#file-status').textContent = '';
    el('#form-section').classList.add('hidden');
    el('#drop-zone').classList.remove('hidden');
  });
}

wireUp();
