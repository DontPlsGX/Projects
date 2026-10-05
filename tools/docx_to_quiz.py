#!/usr/bin/env python3
"""Chuyển các file .docx câu hỏi trắc nghiệm thành quiz/questions.json.

Cách dùng:  python tools/docx_to_quiz.py [thư_mục_docx] [file_json_ra]
Mặc định:   quiz/source/*.docx  ->  quiz/questions.json

Mỗi file .docx là một bài. Hỗ trợ các kiểu soạn đề phổ biến:
  - "Câu 1: ..." / "Câu 1." / "1. ..." (kể cả đánh số tự động của Word)
  - Đáp án "A. ... B. ..." trên cùng một dòng hoặc mỗi đáp án một dòng
  - Đáp án đúng được đánh dấu bằng: tô màu nền (highlight), chữ màu,
    gạch chân, in đậm, in nghiêng, dấu * ở đầu/cuối,
    dòng "Đáp án: B" ngay dưới câu, hoặc bảng/dòng "ĐÁP ÁN" ở cuối file
    (vd "1.A 2.B 3C ..." hoặc bảng số câu - chữ cái).
"""
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from docx.text.run import Run

ROOT = Path(__file__).resolve().parent.parent
LETTERS = "ABCDEFGH"
FLAGS = ("hl", "color", "u", "b", "i")  # thứ tự ưu tiên khi dò đáp án đúng


def W(tag):
    return qn("w:" + tag)


def wval(el):
    return None if el is None else el.get(W("val"))


def nfc(s):
    return unicodedata.normalize("NFC", s or "")


# ---------------------------------------------------------------------------
# Đánh số tự động của Word -> chữ ("Câu 1:", "A.", ...)
# ---------------------------------------------------------------------------
def roman(n):
    out = ""
    for v, s in ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
                 (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
        while n >= v:
            out += s
            n -= v
    return out


def fmt_num(n, fmt):
    if fmt in ("upperLetter", "lowerLetter"):
        s = ""
        while n > 0:
            n, r = divmod(n - 1, 26)
            s = chr(65 + r) + s
        return s if fmt == "upperLetter" else s.lower()
    if fmt == "upperRoman":
        return roman(n)
    if fmt == "lowerRoman":
        return roman(n).lower()
    return str(n)


class Numbering:
    def __init__(self, doc):
        self.levels, self.key, self.counters = {}, {}, {}
        try:
            root = doc.part.numbering_part.element
        except Exception:
            return
        abstracts = {}
        for an in root.findall(W("abstractNum")):
            abstracts[an.get(W("abstractNumId"))] = self._read_levels(an)
        for num in root.findall(W("num")):
            nid = num.get(W("numId"))
            aid = wval(num.find(W("abstractNumId")))
            lv = {k: list(v) for k, v in abstracts.get(aid, {}).items()}
            restart = False
            for ov in num.findall(W("lvlOverride")):
                ilvl = int(ov.get(W("ilvl")))
                lvl = ov.find(W("lvl"))
                if lvl is not None:
                    lv.update(self._read_levels(ov))
                so = ov.find(W("startOverride"))
                if so is not None:
                    lv.setdefault(ilvl, ["decimal", "%%%d." % (ilvl + 1), 1])[2] = int(wval(so))
                    restart = True
            self.levels[nid] = lv
            self.key[nid] = ("n", nid) if restart else ("a", aid)

    @staticmethod
    def _read_levels(parent):
        lv = {}
        for l in parent.findall(W("lvl")):
            lv[int(l.get(W("ilvl")))] = [
                wval(l.find(W("numFmt"))) or "decimal",
                wval(l.find(W("lvlText"))) or "",
                int(wval(l.find(W("start"))) or 1),
            ]
        return lv

    def label(self, num_id, ilvl):
        lv = self.levels.get(num_id)
        if not lv or ilvl not in lv:
            return None
        c = self.counters.setdefault(self.key[num_id], {})
        c[ilvl] = c[ilvl] + 1 if ilvl in c else lv[ilvl][2]
        for k in [k for k in c if k > ilvl]:
            del c[k]
        fmt, text, _ = lv[ilvl]
        if fmt in ("bullet", "none") or not text:
            return None

        def rep(m):
            n = int(m.group(1)) - 1
            info = lv.get(n, ["decimal", "", 1])
            return fmt_num(c.get(n, info[2]), info[0])

        return re.sub(r"%(\d)", rep, text)


def para_numpr(p):
    """(numId, ilvl) của đoạn văn, tính cả đánh số đến từ style."""
    pPr = p._p.pPr
    numpr = pPr.find(W("numPr")) if pPr is not None else None
    style = p.style
    while numpr is None and style is not None:
        spPr = style.element.find(W("pPr"))
        if spPr is not None:
            numpr = spPr.find(W("numPr"))
        style = style.base_style
    if numpr is None:
        return None
    num_id = wval(numpr.find(W("numId")))
    ilvl = int(wval(numpr.find(W("ilvl"))) or 0)
    if not num_id or num_id == "0":
        return None
    return num_id, ilvl


# ---------------------------------------------------------------------------
# Định dạng từng ký tự (để biết đáp án nào được tô/đậm/gạch chân)
# ---------------------------------------------------------------------------
def style_chain_attr(style, getter):
    while style is not None:
        try:
            v = getter(style.font)
        except Exception:
            v = None
        if v is not None:
            return v
        style = style.base_style
    return None


def run_flags(run, para):
    f = run.font
    rPr = run._r.rPr
    flags = set()

    def eff(getter):
        v = getter(f)
        if v is None and run.style is not None:
            v = style_chain_attr(run.style, getter)
        if v is None:
            v = style_chain_attr(para.style, getter)
        return v

    if eff(lambda x: x.bold):
        flags.add("b")
    if eff(lambda x: x.italic):
        flags.add("i")
    u = eff(lambda x: x.underline)
    if u not in (None, False) and str(u) not in ("NONE", "0"):
        flags.add("u")
    if rPr is not None:
        hl = rPr.find(W("highlight"))
        if hl is not None and wval(hl) not in (None, "none"):
            flags.add("hl")
        shd = rPr.find(W("shd"))
        if shd is not None and (shd.get(W("fill")) or "auto").lower() not in ("auto", "ffffff", "000000"):
            flags.add("hl")
        col = rPr.find(W("color"))
        if col is not None:
            v = (col.get(W("val")) or "auto").lower()
            if col.get(W("themeColor")) and col.get(W("themeColor")) not in ("text1", "dark1"):
                flags.add("color")
            elif v not in ("auto", "000000", "000"):
                # gần đen (xám đậm) thì bỏ qua
                try:
                    r, g, b = int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)
                    if max(r, g, b) > 0x50:
                        flags.add("color")
                except ValueError:
                    pass
    return flags


class Line:
    __slots__ = ("text", "flags", "cell")

    def __init__(self, text, flags, cell=None):
        self.text, self.flags, self.cell = text, flags, cell


def para_line(p, numbering, cell=None):
    text, flags = "", []
    num = para_numpr(p)
    if num:
        lab = numbering.label(*num)
        if lab:
            lab = nfc(lab) + " "
            text += lab
            flags += [frozenset()] * len(lab)
    for r in p._p.iter(W("r")):
        run = Run(r, p)
        t = nfc(run.text).replace("\t", " ").replace("\n", " ")
        if not t:
            continue
        fl = frozenset(run_flags(run, p))
        text += t
        flags += [fl] * len(t)
    return Line(text, flags, cell)


def iter_lines(doc):
    numbering = Numbering(doc)
    body = doc.element.body
    tables = []

    def walk(el, cell=None):
        for child in el.iterchildren():
            if child.tag == W("p"):
                yield para_line(Paragraph(child, doc._body), numbering, cell)
            elif child.tag == W("tbl"):
                tid = len(tables)
                tables.append(child)
                for ri, tr in enumerate(child.iter(W("tr"))):
                    for ci, tc in enumerate(tr.findall(W("tc"))):
                        yield from walk(tc, (tid, ri, ci))
            elif child.tag == W("sdt"):
                content = child.find(W("sdtContent"))
                if content is not None:
                    yield from walk(content, cell)

    yield from walk(body)


# ---------------------------------------------------------------------------
# Phân tích câu hỏi
# ---------------------------------------------------------------------------
Q_RE = re.compile(r"^\s*(?:câu|cau|question)(?:\s*hỏi)?\s*(\d+)\s*[:.)\-–]?\s*", re.I)
NUM_RE = re.compile(r"^\s*(\d{1,3})\s*[.):]\s*(?=\S)")
OPT_START_RE = re.compile(r"^\s*\*?\s*([A-Ha-h])\s*[.):/]\s*")
ANS_RE = re.compile(r"^\s*[\[(]?\s*(?:đáp\s*án(?:\s*đúng)?|đa|answer|chọn|=>|→)\s*[:.\-–]?\s*([A-Ha-h])\b\s*[\])]?\s*\.?\s*$", re.I)
KEY_HEADER_RE = re.compile(r"^\s*(?:bảng\s*)?đáp\s*án\s*(?:tham\s*khảo|trắc\s*nghiệm)?\s*[:.]?\s*", re.I)
PAIR_RE = re.compile(r"(?<!\d)(\d{1,3})\s*[.\-:)]?\s*([A-Ha-h])(?![A-Za-zÀ-ỹ])")
TITLE_RE = re.compile(r"^\s*(bài\s*\d+)\s*[:.\-–]?\s*(.*)$", re.I)


def split_options(text, first_letter="A"):
    """Tách 'A. x B. y C. z' -> [(letter, start, end)] theo thứ tự chữ cái liên tiếp."""
    m = OPT_START_RE.match(text)
    if not m or m.group(1).upper() != first_letter:
        return None
    lower = m.group(1).islower()
    spans = [(m.group(1).upper(), m.start(1), m.end())]
    pos = m.end()
    while True:
        nxt = LETTERS[LETTERS.index(spans[-1][0]) + 1] if spans[-1][0] != LETTERS[-1] else None
        if not nxt:
            break
        L = nxt.lower() if lower else nxt
        mm = re.compile(r"(?:(?<=\s)|(?<=[;,.]))\*?\s*(" + L + r")\s*[.):/]\s+").search(text, pos)
        if not mm:
            break
        spans.append((nxt, mm.start(1), mm.end()))
        pos = mm.end()
    out = []
    for i, (letter, lstart, cstart) in enumerate(spans):
        end = spans[i + 1][1] if i + 1 < len(spans) else len(text)
        out.append((letter, lstart, cstart, end))
    return out


def is_heading(s):
    letters = [c for c in s if c.isalpha()]
    return len(letters) >= 3 and all(c.isupper() for c in letters)


def clean(s):
    s = re.sub(r"\s+", " ", s).strip()
    return s


class Q:
    def __init__(self, num, text):
        self.num, self.text = num, text
        self.opts = []  # dict(text, flags, star)
        self.answer = None  # chữ cái từ dòng "Đáp án:"


def add_option(q, line, letter, cstart, end, lstart=None):
    raw = line.text[cstart:end]
    fl = line.flags[cstart:end]
    star = raw.strip().startswith("*") or raw.strip().endswith("*") or (
        lstart is not None and line.text[max(0, lstart - 2):lstart].strip() == "*")
    q.opts.append({"text": raw, "flags": list(fl), "star": star})


def parse_lines(lines):
    questions, preamble, key, pending_key_cells = [], [], {}, []
    cur, in_key = None, False
    for line in lines:
        t = line.text
        s = t.strip()
        if not s:
            continue
        if in_key:
            if line.cell:
                pending_key_cells.append((line.cell, s))
            for n, l in PAIR_RE.findall(s):
                key[int(n)] = l.upper()
            continue
        mh = KEY_HEADER_RE.match(s)
        if mh and not ANS_RE.match(s) and (cur is None or cur.opts):
            rest = s[mh.end():]
            pairs = PAIR_RE.findall(rest)
            if not rest or len(pairs) >= 2:
                in_key = True
                for n, l in pairs:
                    key[int(n)] = l.upper()
                continue
        ma = ANS_RE.match(s)
        if ma and cur is not None:
            cur.answer = ma.group(1).upper()
            continue
        # dòng chỉ gồm các cặp "1.A 2.B 3.C" (đáp án ở cuối, không có tiêu đề)
        pairs = PAIR_RE.findall(s)
        if len(pairs) >= 3 and not PAIR_RE.sub("", s).strip(" ,;.|-"):
            for n, l in pairs:
                key[int(n)] = l.upper()
            continue

        mq = Q_RE.match(t)
        mn = NUM_RE.match(t) if not mq else None
        if mq or (mn and (cur is None or len(cur.opts) >= 2)):
            m = mq or mn
            num = int(m.group(1))
            cur = Q(num, "")
            questions.append(cur)
            body = t[m.end():]
            # câu hỏi và đáp án nằm chung một dòng: "Câu 1: ...? A. x B. y"
            mo = re.search(r"(?:(?<=\s)|(?<=[?:.]))([Aa])\s*[.)]\s+", body)
            if mo:
                base = m.end() + mo.start()
                sp = split_options(t[base:], "A" if mo.group(1) == "A" else "A")
                if sp and len(sp) >= 2:
                    cur.text = body[:mo.start()]
                    for letter, ls, cs, e in sp:
                        add_option(cur, line, letter, base + cs, base + e, base + ls)
                    continue
            cur.text = body
            continue

        if cur is not None:
            expected = LETTERS[len(cur.opts)] if len(cur.opts) < len(LETTERS) else None
            sp = split_options(t, expected) if expected else None
            if sp:
                for letter, ls, cs, e in sp:
                    add_option(cur, line, letter, cs, e, ls)
                continue
            if cur.opts and is_heading(s):
                continue  # tiêu đề mục ("PHẦN II. THÔNG HIỂU") giữa các câu
            if not cur.opts:
                cur.text += " " + t
            elif len(cur.opts) < 4:
                o = cur.opts[-1]
                o["text"] += " " + t
                o["flags"] += [frozenset()] + list(line.flags)
            # >= 4 đáp án: dòng thừa (tiêu đề mục...) -> bỏ qua
        else:
            preamble.append(s)

    # bảng đáp án dạng: hàng số câu / hàng chữ cái
    grid = {}
    for (tid, r, c), s in pending_key_cells:
        grid.setdefault(tid, {}).setdefault(r, {})[c] = s
    for rows in grid.values():
        rlist = [rows[k] for k in sorted(rows)]
        for a, b in zip(rlist, rlist[1:]):
            cols = sorted(set(a) & set(b))
            if cols and all(re.fullmatch(r"\d{1,3}", a[c].strip(" .")) for c in cols) and \
                    all(re.fullmatch(r"[A-Ha-h]", b[c].strip(" .")) for c in cols):
                for c in cols:
                    key[int(a[c].strip(" ."))] = b[c].strip(" .").upper()
    return questions, preamble, key


def detect_by_format(opts):
    def frac(o, flag):
        chars = [(ch, fl) for ch, fl in zip(o["text"], o["flags"]) if not ch.isspace() and ch != "*"]
        if not chars:
            return 0
        return sum(1 for _, fl in chars if flag in fl) / len(chars)

    for flag in FLAGS:
        marked = [i for i, o in enumerate(opts) if frac(o, flag) >= 0.6]
        if len(marked) == 1:
            return marked[0], flag
    return None, None


def qid(lesson_id, text):
    return hashlib.sha1((lesson_id + "|" + text).encode("utf-8")).hexdigest()[:10]


def convert_file(path):
    doc = Document(str(path))
    questions, preamble, key = parse_lines(iter_lines(doc))
    lesson_id = slug(path.stem)

    title, subtitle = None, ""
    for s in preamble[:6]:
        m = TITLE_RE.match(s)
        if m:
            title, subtitle = m.group(1), m.group(2)
            break
    if not title:
        m = TITLE_RE.match(nfc(path.stem).strip(" ."))
        title = m.group(1) if m else nfc(path.stem).strip(" .")
    title = re.sub(r"\s+", " ", title).strip().capitalize()

    out, problems, seen = [], [], set()
    for idx, q in enumerate(questions):
        text = clean(q.text)
        opts = [clean(o["text"]).strip("* ").strip() for o in q.opts]
        label = "Câu %d" % q.num
        if len(opts) < 2:
            problems.append("%s: không tìm thấy đủ đáp án (%d) – %s" % (label, len(opts), text[:60]))
            continue
        ans, how = None, None
        if q.answer and q.answer in LETTERS[: len(opts)]:
            ans, how = LETTERS.index(q.answer), "dòng 'Đáp án'"
        elif q.num in key and key[q.num] in LETTERS[: len(opts)]:
            ans, how = LETTERS.index(key[q.num]), "bảng đáp án"
        else:
            stars = [i for i, o in enumerate(q.opts) if o["star"]]
            if len(stars) == 1:
                ans, how = stars[0], "dấu *"
            else:
                ans, how = detect_by_format(q.opts)
        if ans is None:
            problems.append("%s: chưa xác định được đáp án đúng – %s" % (label, text[:60]))
        i = qid(lesson_id, text + "|" + "|".join(opts))
        while i in seen:
            i = qid(lesson_id, i)
        seen.add(i)
        out.append({"id": i, "n": q.num, "q": text, "o": opts, "a": ans})
    return {
        "id": lesson_id,
        "title": title,
        "subtitle": clean(subtitle),
        "questions": out,
    }, problems


def slug(s):
    s = unicodedata.normalize("NFD", nfc(s).lower()).replace("đ", "d")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "bai"


def natural_key(p):
    m = re.search(r"\d+", p.stem)
    return (int(m.group()) if m else 9999, p.stem.lower())


def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "quiz" / "source"
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "quiz" / "questions.json"
    files = sorted((p for p in src.glob("*.docx") if not p.name.startswith("~$")), key=natural_key)
    if not files:
        print("Không có file .docx trong %s – giữ nguyên %s" % (src, dst.name))
        return 0
    lessons, total_bad = [], 0
    for f in files:
        lesson, problems = convert_file(f)
        lessons.append(lesson)
        ok = sum(1 for q in lesson["questions"] if q["a"] is not None)
        print("✔ %-28s → %s: %d câu (%d có đáp án)" % (f.name, lesson["title"], len(lesson["questions"]), ok))
        for p in problems:
            total_bad += 1
            print("   ⚠ " + p)
            if "GITHUB_ACTIONS" in __import__("os").environ:
                print("::warning file=%s::%s" % (f.as_posix(), p))
    dst.write_text(json.dumps({"lessons": lessons}, ensure_ascii=False, separators=(",", ":")), "utf-8")
    print("→ Đã ghi %s (%d bài, %d cảnh báo)" % (dst, len(lessons), total_bad))
    return 0


if __name__ == "__main__":
    sys.exit(main())
