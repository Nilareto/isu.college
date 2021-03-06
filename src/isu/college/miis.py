from zope.component import adapter, getGlobalSiteManager
from isu.college.interfaces import IAcademicPlan
from isu.college.components import AcademicPlan, AcademicCourse
import xlrd
from isu.college import enums
import re
import marisa_trie
import pymorphy2
from pprint import pprint, pformat
import numpy as np
from collections import namedtuple

morph = pymorphy2.MorphAnalyzer()

# Movement commands (dx,dy)
L, R, D, U = (-1, 0), (1, 0), (0, 1), (0, -1)

MOVES = {
    "L": L,
    "R": R,
    "D": D,
    "U": U
}


class CellNotFoundError(Exception):
    pass


class NormalizationError(Exception):
    pass


mark = object()


def normal(phrase, *tags, **kw):
    tags = set(tags)

    def norm(word):
        for p in morph.parse(word):
            if tags in p.tag:
                return p.normal_form
        raise NormalizationError(
            "cannot normaize '{}' within {}".format(word, tags))

    phrase = phrase.strip()
    if phrase.find(" ") >= 0:
        assert "n" in kw is not None, \
            "no number of word in " \
            "the sentence to be normaized"
        n = kw["n"]
        words = phrase.split()
        f, word, l = words[:n], words[n],  words[n + 1:]
        word = norm(word)
        phrase = " ".join(f + [word] + l)
        return phrase
    else:
        return norm(phrase)


def move(row, col, direction):
    dx, dy = MOVES[direction]
    yield row + dy, col + dx


class Object(object):

    def __str__(self):
        s = "{}<{}>:\n".format(self.__class__.__name__, hex(id(self)))
        for k in dir(self):
            if not k.startswith("_"):
                val = getattr(self, k)
                s += "{}={}\n".format(k, val)
        s += "\n"
        return s


class String(str, Object):
    pass


class Index(int):
    """A class of hierarchical index.
    """


class Plan(AcademicPlan):
    """Represents MIIS.ru Plan XLSX export files as
    IAcademicPlan component.
    """

    def __init__(self, URL):
        self.URL = URL
        self.book = None
        self.attrs = {}
        self.compl = None
        self.load()
        self.load_plan()

    def __str__(self):
        s = "{}<{}>:\n".format(self.__class__.__name__, hex(id(self)))
        for k in self.attrs.keys():
            if not k.startswith("_"):
                val = self.attrs[k]
                s += "{}={}\n".format(k, pformat(val))
        s += "\n"
        return s

    def load(self):
        """Loads spreadsheet on demand
        or not.
        """
        if self.is_loaded():
            return

        self.book = xlrd.open_workbook(self.URL)
        self._setup_rules()
        self._run_recognition()
        # pprint(self.attrs)
        self._represent()
        # print(self.program.direction)
        # self.debug_print()

    def is_loaded(self):
        return self.book is not None

    VALSTRRE = re.compile("(\w+|\d+)")

    def check(self, cell):
        if cell is None:
            return False
        if hasattr(cell, "ctype"):
            if cell.ctype == 0:
                return False
        val = cell.value
        if self.VALSTRRE.search(val) is None:
            return False
        if "_" in val:
            return False
        return True

    def path(self, cell, sheet, row, col,
             direction,
             skip_first=True,
             max_steps=-1,
             steps=-1
             ):

        dx, dy = direction  # MOVES[direction]
        nrows, ncols = sheet.nrows, sheet.ncols
        if not skip_first:
            if self.check(cell):
                yield cell, sheet, row, col
        while True:
            if steps == 0 or max_steps == 0:
                return

            row, col = row + dy, col + dx
            max_steps -= 1
            steps -= 1

            if row < 0 or col < 0 or row >= nrows or col >= ncols:
                return

            cell = sheet.cell(rowx=row, colx=col)
            if self.check(cell):
                if steps < 0 or steps == 0:
                    yield cell.value, sheet, row, col

    def degree_proc(self, val, sheet, row, col):
        sb = "подготовки"
        for val, sheet, row, col in self.path(val, sheet, row, col, D):
            val = val.strip()
            if val.startswith(sb):
                yield (normal(val.replace(sb, ""), "NOUN"), sheet, row, col)
                break

    def debug_print(self):
        book = self.book
        print("The number of worksheets is {0}".format(book.nsheets))
        print("Worksheet name(s): {0}".format(book.sheet_names()))
        sh = book.sheet_by_index(0)
        print("{0} {1} {2}".format(sh.name, sh.nrows, sh.ncols))
        print("Cell D30 is {0}".format(sh.cell_value(rowx=29, colx=3)))
        for rx in range(sh.nrows):
            print(sh.row(rx))

    def _setup_rules(self):
        self.RULES = {
            "Титул": {
                "ministry": ((7, 2), self.identity),
                "institution": ((9, 0), self.identity),
                "managers.rector": ("Ректор", self.slash_clean_proc),
                "program.degree": ("УЧЕБНЫЙ ПЛАН", self.degree_proc),
                "program.direction": (".*[нН]аправлен", self.direction_proc),
                "program.profile": (".*[нН]аправлен", self.profile_proc),
                "program.start_year": ("^[Гг]од начала подготовки$",
                                       self.right_proc),
                "edu_standard": ("^[Оо]бразовательный стандарт$",
                                 self.edu_standard_proc),
                "managers.EW_prorector": ("^[Пп]роректор.*учеб.*работе$",
                                          self.slash_clean_proc),
                "managers.UMU_head": ("^[Нн]ачальник УМУ$",
                                      self.slash_clean_proc),
                "managers.director": ("^[Дд]иректор$", self.slash_clean_proc),
                "approval": ("^[Пп]лан одобрен", self.appov_plan_proc),
                "chair.title": ("^[Кк]афедра:$", self.right_proc),
                "chair.faculty": ("^[Фф]акультет:$", self.right_proc),
                "profession.degree": ("^[Кк]валификация:",
                                      self.colon_split_proc),
                "profession.academicity": ("^[Пп]рограмма подготовки:",
                                           self.colon_split_proc),
                "profession.mural": ("^[Фф]орма обучения:",
                                     self.colon_split_proc),
                "program.duration": ("^[Сс]рок обучения:",
                                     self.g_removal_proc),
                "program.laboriousness": ("^[Тт]рудоемкость ОПОП:",
                                          self.colon_split_proc),
                "profession.activities": ("^[Фф]акультет",
                                          self.activities_proc),
            }
        }

    def _represent(self, d=None, o=None):
        if d is None:
            d = self.attrs
            o = self
        assert "_value" not in d or o != self, "wrong structure"
        for k, v in d.items():
            if k == "_value":
                continue

            if isinstance(v, dict):
                if "_value" in v:
                    n = String(v["_value"])
                else:
                    n = Object()
                self._represent(v, n)
                v = n
            setattr(o, k, v)

    def _run_recognition(self, pages=None):

        # ADDRRE = re.compile("\w+\d+")  # A0 C10

        def find_match(sheet, templ):
            if isinstance(templ, (tuple, list)):
                row, col = templ
                cell = sheet.cell(rowx=row, colx=col)
                if cell.ctype == 0:
                    cell = None
                yield cell, row, col
                return

            rege = re.compile(templ)
            for row in range(sheet.nrows):
                for col in range(sheet.ncols):
                    cell = sheet.cell(rowx=row, colx=col)
                    if cell.ctype != 0:
                        val = cell.value.strip()
                        # print(col, row, val, cell, cell.ctype)
                        m = rege.match(val)
                        if m is not None:
                            yield cell, row, col

        for page, matchs in self.RULES.items():
            if pages is not None:
                if page not in pages:
                    continue
            sheet = self.book.sheet_by_name(page)

            for var, prog in matchs.items():
                templ, body = prog
                # body = getattr(self, body)

                for cell, row, col in find_match(sheet, templ):
                    #assert cell is not None and cell.ctype != 0
                    if cell is None or cell.ctype == 0:
                        print("WARNING: {} search failed!".format(templ))
                        continue
                    for _ in body(cell.value, sheet, row, col):
                        assert len(_) >= 4, "must yield (val, sheet, row, col)"
                        if _[0] is None:
                            continue
                        cell = _[0]
                        break
                    else:
                        continue
                    if cell is not None:
                        if hasattr(cell, "ctype"):
                            if cell.ctype == 0:
                                continue
                            self.assign(cell.value, name=var)
                        else:
                            self.assign(cell, name=var)
                        break

    def assign(self, value, name):
        assert value is not None
        if isinstance(value, dict):
            for k, v in value.items():
                nname = name.rstrip(".")
                if k == "_value":
                    self.assign(v, nname)
                else:
                    nname += "." + k
                    self.assign(v, nname)
        else:
            if isinstance(value, str):
                value = value.strip()
            path = name.split(".")
            attrs = self.attrs
            for name in path:
                attrs = attrs.setdefault(name, {})
            attrs.update({"_value": value})

    def identity(self, cell, *args):
        yield (cell,) + args

    SLRE = re.compile("[\\/]?(.*)[\\/]?")  # Not used

    def slash_clean_proc(self, val, sheet, row, col):
        """/XXXX/ -> XXX """
        for val, _, r, c in self.right_proc(val, sheet, row, col):
            yield val.replace("/", "").replace("\\", "").strip(), sheet, r, c
            break

    DRE = re.compile(".*(\s(\d+\.\d+\.\d+)\.?\s*(.*))")

    def direction_proc(self, val, sheet, row, col):

        val = val.strip()
        m = self.DRE.match(val)
        if m is None:
            return
        assert m is not None, "cannot match {} with {}".format(val, self.DRE)
        val = {
            "code": m.group(2),
            "title": m.group(3).replace("'", '').replace('"', ''),
            "_value": m.group(1)
        }
        yield val, sheet, row, col

    def profile_proc(self, val, sheet, row, col):
        for val, sheet, row, col in self.path(val,
                                              sheet,
                                              row,
                                              col,
                                              direction=D, steps=1):
            val = val.replace("'", '"').split('"')
            # assert val.find('"') < 0, "Removing parents failed"
            if len(val) == 1:
                val = val[0]
            else:
                val = val[1]
            # print(val)
            assert val.find('"') < 0, "Removing parents failed"
            yield val, sheet, row, col
            break

    def right_one_proc(self, val, sheet, row, col):
        for val, sheet, row, col in self.path(val,
                                              sheet,
                                              row,
                                              col,
                                              direction=R, steps=1):
            yield val, sheet, row, col
            break

    def right_proc(self, val, sheet, row, col, max_steps=-1, steps=-1):
        for val, sheet, row, col in self.path(val,
                                              sheet,
                                              row,
                                              col,
                                              direction=R,
                                              steps=steps,
                                              max_steps=max_steps
                                              ):
            yield val, sheet, row, col
            break

    def down_proc(self, val, sheet, row, col, max_steps=-1, steps=-1):
        for val, sheet, row, col in self.path(val,
                                              sheet,
                                              row,
                                              col,
                                              direction=D,
                                              steps=steps,
                                              max_steps=max_steps
                                              ):
            yield val, sheet, row, col
            break

    def down_one_proc(self, val, sheet, row, col, steps=1):
        for val, sheet, row, col in self.path(val,
                                              sheet,
                                              row,
                                              col,
                                              direction=D, steps=1):
            yield val, sheet, row, col
            break

    def edu_standard_proc(self, val, sheet, row, col):
        for code, _, r, c in self.right_proc(val, sheet, row, col):
            break
        else:
            return
        for date, _, r, c in self.down_one_proc(val, sheet, r, c, steps=1):
            break
        else:
            return

        yield {
            "code": code,
            "date": date
        }, sheet, r, c

    def appov_plan_proc(self, v, s, r, c):
        division = v.split("одобрен ")[1].strip()
        for v, s, r, c in self.down_one_proc(v, s, r, c):
            for v, s, r, c in self.right_proc(v, s, r, c):
                number, date = v.split(" от ")
                yield {
                    "division": division,
                    "signature.number": number,
                    "signature.date": date
                }, s, r, c
                return
        else:
            yield {"division": division}, s, r, c

    def proto_number_proc(self, s):
        return s

    def colon_split_proc(self, v, s, r, c):
        yield v.split(":")[1].strip(), s, r, c

    def g_removal_proc(self, v, s, r, c):
        for v, s, r, c in self.colon_split_proc(v, s, r, c):
            yield v.replace("г", ""), s, r, c
            break

    WORDDASHRE = re.compile("(\w+\s?-?\s?\w+)")

    def activities_proc(self, v, s, r, c):
        for v, s, r, c in self.right_proc(v, s, r, c):
            for v, s, r, c in self.down_one_proc(v, s, r, c):
                l = self.WORDDASHRE.findall(v)
                l = [a.strip().replace(" ", "") for a in l]
                l = [a for a in l if a]
                yield l, s, r, c
                return

    def load_lists(self):
        def empty(cell):
            if cell.ctype == 0:
                return None
            val = cell.value.strip()
            if val:
                return val
            return None

        if self.compl is not None:
            return
        sheet = self.book.sheet_by_name("Компетенции")
        self.compl = compl = {}
        self.courl = courl = {}

        cid = None
        courid = None
        for row in range(sheet.nrows):
            A = sheet.cell(rowx=row, colx=0)
            D = sheet.cell(rowx=row, colx=3)
            G = sheet.cell(rowx=row, colx=6)
            if A.ctype != 0:
                try:
                    int(A.value)
                except ValueError:
                    return
                cid = empty(D)
                courid = None
            else:
                courid = empty(D)
            val = empty(G)
            if val is not None:
                if courid is not None:
                    courl.setdefault(courid, (val, set()))
                elif cid is not None:
                    val = normal(val, n=0)
                    compl.setdefault(cid, (val, set()))
                else:
                    continue
                if courid is not None and cid is not None:
                    _, s1 = courl[courid]
                    _, s2 = compl[cid]
                    s1.add(cid)
                    s2.add(courid)

    @property
    def competence_list(self, courid=None):
        self.load_lists()
        yield from self.show_list(self.compl, courid, "{title} ({code})")

    def show_list(self, l, filterid, form):
        for k, v in l.items():
            v, s = v
            if filterid is not None and filterid not in s:
                continue
            name = form.format(code=k, title=v)
            o = String(name)
            o.title = v
            o.code = k
            yield o

    @property
    def course_list(self, compid=None):
        self.load_lists()
        yield from self.show_list(self.courl, compid, "{code}. {title}")

    IDNUMRE = re.compile("((\w|_)+)_(\d+)")

    def scan_row(self, row, sheet, cton):
        cells = sheet.row(row)
        nameset = set()
        for col, cell in enumerate(cells):
            if col == 0:
                continue  # ignore first cell as it is techincal
            # print(cell, end=" ")
            if cell.ctype == 0:
                continue
            val = cell.value.strip()
            if not val:
                continue
            if "%" in val:
                continue
            val = val.split("(")[0].strip()
            val = val.split("[")[0].strip()
            val = val.replace(" ", "_")
            val = val.replace("/", "_")
            val = val.replace("\n", "")
            val = val.replace(".", "")
            val = val.lower()
            m = self.__class__.IDNUMRE.match(val)
            o = Index(col)
            o._leaf = True
            if m is not None:
                val = m.group(1), int(m.group(3))
                o = {val[1]: o}
            else:
                val = (val, None)
            vname, vopt = val

            vname = self.__class__.RENAME.get(vname, vname)
            val = vname, vopt
            name_point = (row, col)
            nameset.add(val)

            # search parent
            parent_cton = None
            r = row - 1
            c = col
            while True:
                if r < 1:
                    cton[name_point] = (val, None, None, o)
                    break
                if (r, c) in cton:
                    parent_cton = cton[(r, c)]
                    cton[name_point] = (val, (r, c), parent_cton, o)
                    break
                r -= 1
            if parent_cton is not None:
                continue
            c = col - 1
            r = row
            while True:
                if c < 2:
                    cton[name_point] = (val, None, None, o)
                    print(name_point, val)
                    break

                if (r, c) in cton:
                    sibling_cton = cton[(r, c)]
                    cton[name_point] = (
                        val, (r, c), sibling_cton[2], o)
                    break
                c -= 1
        # print(nameset)

    RENAME = {
        "ауд": "aud",
        "в_том_числе": "inc",
        "всего": "total",
        "всего_часов": "total_h",
        "закрепленная_кафедра": "chair",
        "зачеты": "credits",
        "зачеты_с_оценкой": "grade_credit",
        "зет": "cu",   # Credit unit
        "зет_в_нед": "cupw",  # Control units per week
        "из_них": "inc",  # Including
        "индекс": "code",
        "итого_часов_в_интерактивной_форме": "tih",  # Total intractive hours
        "итого_часов_в_электронной_форме": "teh",  # Total electric hours
        "код": "code",
        "компетенции": "components",
        "контакт_раб": "contact_work",
        "контроль": "sup",  # Supervision
        "кср": "iwc",  # Independent Work Control
        "курс": "course",
        "курсовые_проекты": "cprojects",  # Course projects
        "курсовые_работы": "cworks",  # Course works
        "лаб": "lab",
        "лек": "lec",
        "наименование": "title",
        "по_зет": "cu",
        "по_плану": "plan",
        "пр": "pr",
        "распределение_по_курсам": "dif",  # Remove from hierarchy
        "распределение_по_курсам_и_семестрам": "dif",  # Remove from hierarchy
        "семестр": "sem",  # semester
        "срс": "siw",  # Students' independent work
        "факт": "fact",
        "формы_контроля": "controls",
        "часов": "h",  # Hours
        "часов_в_зет": "hicu",  # Hours in a control unit.
        "экзамены": "exams",  # Examinations
        "экспертное": "expert",
    }

    def _build_index_tree(self, cton, row):
        """Internal method. It constructs an index
        hierarchy from the scanned header structure.
        """
        self.colidx = Index(2)  # The root index of the hierarchy

        def seta(index, pdef,  o, odef):
            pname, pidx = pdef
            name, oi = odef
            if oi is not None:
                if hasattr(index, name):
                    getattr(index, name).update(o)
                    return
            if pidx is not None and isinstance(index, dict):
                index = index[pidx]
                seta(index, (None, None), o, odef)
                return
            index._leaf = False
            setattr(index, name, o)

        for myloc, _ in cton.items():
            mydef, myloc, parent, myindex = _

            if parent is not None:
                pdef, ploc, pparent, pindex = parent
                seta(pindex, pdef, myindex, mydef)
                continue

            seta(self.colidx, (None, None), myindex, mydef)

    def load_plan(self):
        """Loads main time table.
        """
        def conv(cell):
            if cell.ctype == 0:
                return None
            val = cell.value
            try:
                val = val.strip()
            except AttributeError:
                ival = int(val)
                if abs(float(ival) - val) < 0.001:
                    return int(val)
                return val
            try:
                return int(val)
            except ValueError:
                pass
            try:
                return float(val)
            except ValueError:
                pass
            return val

        cton = {}  # (c,r) to (name, parent_cton) index
        self.indexes = indexes = {}
        sheet = self.book.sheet_by_name("План")
        layout = sheet.cell(0, 0).value.split(";")
        layout = [int(l.strip()) - 1 for l in layout]
        print("Layout", layout)
        for row in range(layout[0]):
            self.scan_row(row + 1, sheet, cton)

        self._build_index_tree(cton, row=layout[0] + 1)

        ci = self.colidx
        pcode = None
        self.courses = courses = {}
        for rown in range(sheet.nrows):
            if rown <= layout[0]:
                continue
            row = sheet.row(rown)
            row = [conv(c) for c in row]

            code = row[ci.code]

            if code == "*":
                pcode = None
                continue
            if isinstance(code, int):
                assert pcode is not None
                code = "{}.{}".format(pcode, code)
            elif code is None:
                code = pcode
            else:
                pcode = code

            if code is None:
                continue

            courses.setdefault(code, []).append(row)

        # self.scan_row(3, sheet, cton)

    def course(self, code):
        self.load_lists()
        course = self.courses[code]
        title = course[0][self.colidx.title]

        c = Course(code=code, title=title, plan=self, data=course)
        return c


Column = namedtuple("Column", ["v", "i", "e"])


class CourseDescriptor(object):
    """Helping class allowing interpret
    column indices with tabular data they refer to"""

    def __init__(self, index=None, data=None):
        self.index = index
        self.data = data

    def __get__(self, instance, owner):
        # owner is a Class
        #print("Got: ", self, instance, owner)
        plan = instance.plan
        return self.__class__(plan.colidx, instance.data)

    def __getattr__(self, name):
        i = getattr(self.index, name)
        return self.interpret(i)

    def interpret(self, i):
        isi = isinstance(i, Index)
        if isi and i._leaf:
            return self._val(i)
        if isi or isinstance(i, dict):
            return self.__class__(i, self.data)
        else:
            return i

    def __getitem__(self, index):
        i = self.index[index]
        return self.interpret(i)

    def __int__(self):
        return self.index

    def _val(self, i):
        return Column._make((list(self.data[:, i]) + [None, None, None])[:3])

    @property
    def val(self):
        return self._val(self)


class Course(AcademicCourse):
    """Expresses course data

    """
    descriptor = CourseDescriptor()

    def __init__(self, code=None, title=None, plan=None, data=None):
        super(Course, self).__init__(code, title)
        self.plan = plan
        self.data = np.array(data, dtype=object)

    def __getattr__(self, name):
        val = getattr(self.descriptor, name)
        return val
