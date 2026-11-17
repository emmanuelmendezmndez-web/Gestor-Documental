"""Extracción auxiliar por reglas en español; los resultados son menciones."""

import re
import unicodedata
from datetime import date

MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
         "octubre", "noviembre", "diciembre")
PAT_MES = "|".join(MESES)
RELATIVAS = ("hoy", "ayer", "antier", "anteayer", "anoche", "mañana", "anteanoche",
             "esta semana", "semana pasada", "este mes", "mes pasado", "este año", "año pasado",
             "hace un rato", "hace rato", "ase rato")
DIAS_SEMANA = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")
FOLIO = re.compile(
    r"\b(?:exp[-/]\d{4}[-/]\d{1,12}|of-\d[a-z0-9]*(?:[-/][a-z0-9]+)*)\b"
    r"|\b(?:folio(?:\s+(?:de|del)\s+expediente)?|oficio(?:\s+(?:n[uú]mero|n[uú]m\.?|no\.?))?)"
    r"\s*[:#]?\s+(?P<valor>(?:[a-z]{1,12}[-/])?\d{1,18}(?:[-/][a-z0-9]+)*)\b",
    re.IGNORECASE,
)
REGISTRO = re.compile(
    r"\b(?:registro(?:\s+interno)?|documento(?:\s+n[uú]mero)?|archivo(?:\s+n[uú]mero)?|ficha)"
    r"\s*[:#]?\s+(?P<valor>[1-9]\d{0,17})(?![\w/-]|\.\d)",
    re.IGNORECASE,
)
REGISTROS = re.compile(
    r"\bregistros(?:\s+internos)?\s+(?P<lista>[1-9]\d{0,17}(?:(?:,\s*|\s+y\s+)[1-9]\d{0,17})+)(?![\w/-])",
    re.IGNORECASE,
)
TITULO = re.compile(
    r"\b(?:documento|archivo|informe|contrato|oficio|acta|expediente|reporte|anexo)\b"
    r"[^«»“”\";.!?\n]{0,65}?[«“\"](?P<valor>[^«»“”\";\n]{1,90})[»”\"]",
    re.IGNORECASE,
)
FECHA = re.compile(
    r"\b(?P<iso>(?:19|20)\d{2}-\d{1,2}-\d{1,2})\b"
    r"|\b(?P<numerica>\d{1,2}[/.]\d{1,2}[/.](?:19|20)\d{2})\b"
    rf"|\b(?P<dia>\d{{1,2}})\s+de\s+(?P<mes>{PAT_MES})(?:\s+(?:de\s+)?(?P<anio>(?:19|20)\d{{2}}))?\b"
    rf"|\b(?P<solo_mes>{PAT_MES})(?:\s+(?:de\s+)?(?P<anio_mes>(?:19|20)\d{{2}}))?\b",
    re.IGNORECASE,
)
ALIAS = {"Recursos Humanos": ("rrhh", "rr hh", "rr. hh.", "r. h."), "Tesorería": ("tesoreria",)}
FRENO = {"pero", "mejor", "sino", "solo", "solamente", "nomas", "luego", "despues", "ademas", "aunque"}


def normalizar(texto):
    return "".join(c for c in unicodedata.normalize("NFD", texto.casefold()) if not unicodedata.combining(c))


def fecha_iso(y, m, d):
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


def interpretar_fecha(m):
    if m["iso"]:
        y, mes, d = map(int, m["iso"].split("-"))
        valor = fecha_iso(y, mes, d)
        return ("exacta", valor) if valor else ("invalida", None)
    if m["numerica"]:
        d, mes, y = map(int, re.split(r"[/.]", m["numerica"]))
        a, b = fecha_iso(y, mes, d), fecha_iso(y, d, mes)
        if a and b and a != b:
            return "ambigua", None
        return ("exacta", a or b) if a or b else ("invalida", None)
    if m["dia"]:
        mes = MESES.index(m["mes"].lower()) + 1
        d = int(m["dia"])
        if not m["anio"]:
            return ("sin_anio", None) if fecha_iso(2000, mes, d) else ("invalida", None)
        valor = fecha_iso(int(m["anio"]), mes, d)
        return ("exacta", valor) if valor else ("invalida", None)
    if m["anio_mes"]:
        return "mes", f"{m['anio_mes']}-{MESES.index(m['solo_mes'].lower())+1:02}"
    return "sin_anio", None


def solapa(inicio, fin, otras):
    return any(inicio < r["fin"] and fin > r["inicio"] for r in otras)


class ExtractorClippy:
    """Usa tokenización española, Matcher y PhraseMatcher sin pipeline entrenado."""

    VERSION_REGLAS = 1

    def __init__(self, departamentos):
        import spacy
        from spacy.matcher import Matcher, PhraseMatcher

        self.version_spacy = spacy.__version__
        self.nlp = spacy.blank("es")
        self.frases = PhraseMatcher(self.nlp.vocab, attr="NORM")
        self.areas = {}
        for nombre in departamentos:
            etiqueta = f"area:{nombre}"
            self.frases.add(etiqueta, [self._doc(p) for p in (nombre, *ALIAS.get(nombre, ()))])
            self.areas[self.nlp.vocab.strings[etiqueta]] = nombre
        self.frases.add("relativa", [self._doc(p) for p in RELATIVAS])
        self.relativa = self.nlp.vocab.strings["relativa"]
        self.reglas = Matcher(self.nlp.vocab)
        self.reglas.add("negacion", [[{"NORM": {"IN": ["no", "ni", "nunca", "jamas", "sin", "nel"]}}],
                                     [{"NORM": {"REGEX": "^(?:no{3,}|noborre|nopuedo|noquiero)$"}}],
                                     [{"NORM": "nose"}, {"NORM": {"IN": ["si", "que"]}}]])
        self.reglas.add("relativa_compuesta", [
            [{"NORM": "hace"}, {"LIKE_NUM": True}, {"NORM": {"IN": ["hora", "horas", "dia", "dias", "semana", "semanas"]}}],
            [{"NORM": "el", "OP": "?"}, {"NORM": {"IN": list(DIAS_SEMANA)}},
             {"NORM": {"IN": ["pasado", "proximo"]}, "OP": "?"}],
        ])
        self.reglas.add("marca_titulo", [[{"NORM": {"IN": ["llamado", "llamada", "titulado", "titulada"]}}],
                                         [{"NORM": "se"}, {"NORM": "llama"}]])
        self.ids_reglas = {self.nlp.vocab.strings[name]: name
                           for name in ("negacion", "relativa_compuesta", "marca_titulo")}

    def _doc(self, texto):
        doc = self.nlp.make_doc(texto)
        for token in doc:
            token.norm_ = normalizar(token.text)
        return doc

    @staticmethod
    def _mencion(texto, inicio, fin, valor, estado="mencion"):
        return {"texto": texto[inicio:fin], "inicio": inicio, "fin": fin, "valor": valor, "estado": estado}

    def extraer(self, texto):
        if not isinstance(texto, str):
            raise TypeError("La frase debe ser texto")
        if len(texto) > 300:
            raise ValueError("La frase supera 300 caracteres")
        campos = {k: [] for k in ("folios", "fechas", "departamentos", "referencias", "negaciones")}
        if not texto.strip():
            return campos
        doc = self._doc(texto)
        def agregar(clave, inicio, fin, valor, estado="mencion"):
            campos[clave].append(self._mencion(texto, inicio, fin, valor, estado))

        for m in FOLIO.finditer(texto):
            i, f = m.span("valor") if m["valor"] else m.span()
            if FECHA.fullmatch(texto[i:f]) or re.match(r"\s+de\s+(?:" + PAT_MES + r")\b", texto[f:], re.IGNORECASE):
                continue
            agregar("folios", i, f, texto[i:f].upper())
        for m in REGISTRO.finditer(texto):
            i, f = m.span("valor")
            agregar("referencias", i, f, "registro:" + m["valor"], "registro")
        for m in REGISTROS.finditer(texto):
            for numero in re.finditer(r"\d+", m["lista"]):
                i, f = (m.start("lista") + punto for punto in numero.span())
                agregar("referencias", i, f, "registro:" + numero[0], "registro")
        for m in TITULO.finditer(texto):
            i, f = m.span("valor")
            agregar("referencias", i, f, "titulo:" + normalizar(m["valor"].strip()), "titulo")
        for m in FECHA.finditer(texto):
            if not solapa(*m.span(), campos["folios"] + campos["referencias"]):
                estado, valor = interpretar_fecha(m)
                agregar("fechas", *m.span(), valor, estado)

        for clave, i, f in self.frases(doc):
            trozo = doc[i:f]
            if clave == self.relativa:
                agregar("fechas", trozo.start_char, trozo.end_char, None, "relativa")
                continue
            nombre = self.areas[clave]
            contexto = " ".join(t.norm_ for t in doc[max(0, i-3):i])
            if nombre in {"Archivos", "Otro"} and not re.search(r"\b(?:departamento|area)(?: de)?$", contexto):
                continue
            agregar("departamentos", trozo.start_char, trozo.end_char, nombre)

        vistos = set()
        for clave, i, f in self.reglas(doc):
            regla = self.ids_reglas[clave]
            if regla == "relativa_compuesta":
                trozo = doc[i:f]
                agregar("fechas", trozo.start_char, trozo.end_char, None, "relativa")
            elif regla == "marca_titulo":
                anteriores = {t.norm_ for t in doc[max(0, i-5):i]}
                if not anteriores & {"documento", "archivo", "informe", "expediente", "oficio", "acta", "contrato", "reporte"}:
                    continue
                j = f
                while j < len(doc) and not doc[j].is_punct and doc[j].norm_ not in FRENO:
                    if j > f and doc[j].norm_ in {"para", "porfa", "porfavor"}:
                        break
                    j += 1
                if j > f and not solapa(doc[f].idx, doc[j-1].idx+len(doc[j-1]), campos["referencias"]):
                    trozo = doc[f:j]
                    agregar("referencias", trozo.start_char, trozo.end_char, "titulo:" + normalizar(trozo.text), "titulo")
            elif i not in vistos:
                vistos.add(i)
                siguientes = [t.norm_ for t in doc[f:min(f+3, len(doc))]]
                if doc[i].norm_ == "no" and (
                    siguientes[:1] in (["solo"], ["solamente"], ["mas"])
                    or siguientes[:2] in (["seas", "malito"], ["seas", "gacho"])
                ):
                    continue
                j = f
                while j < len(doc) and not doc[j].is_punct and doc[j].norm_ not in FRENO:
                    j += 1
                trozo = doc[i:j]
                agregar("negaciones", trozo.start_char, trozo.end_char, doc[i].norm_, "alcance_aproximado")

        for clave, menciones in campos.items():
            ordenadas = sorted(menciones, key=lambda r: (r["inicio"], -r["fin"]))
            if clave == "fechas":
                limpias = []
                for mencion in ordenadas:
                    if not solapa(mencion["inicio"], mencion["fin"], limpias):
                        limpias.append(mencion)
                ordenadas = limpias
            campos[clave] = ordenadas
        for clave in ("folios", "fechas", "departamentos", "referencias"):
            for mencion in campos[clave]:
                mencion["negada"] = any(r["inicio"] <= mencion["inicio"] < r["fin"] for r in campos["negaciones"])
        return campos


class ExtraccionSombra:
    """En el trabajador solo expone métricas, manteniendo los valores en memoria."""

    def __init__(self, paquetes, departamentos):
        import sys

        carpeta = str(paquetes.resolve())
        if paquetes.is_dir() and carpeta not in sys.path:
            sys.path.append(carpeta)
        try:
            self.extractor = ExtractorClippy(departamentos)
        except Exception:  # noqa: BLE001 - dependencia experimental opcional
            self.extractor = None

    def resumir(self, texto):
        from time import perf_counter

        if self.extractor is None:
            return {"estado": "no_disponible"}
        inicio = perf_counter()
        try:
            salida = self.extractor.extraer(texto)
        except Exception:  # noqa: BLE001 - conserva las predicciones de Clippy
            return {"estado": "fallo_extraccion"}
        return {"estado": "ok", "reglas": self.extractor.VERSION_REGLAS, "spacy": self.extractor.version_spacy,
                "conteos": {k: len(v) for k, v in salida.items()}, "latencia_ms": (perf_counter() - inicio) * 1000}

