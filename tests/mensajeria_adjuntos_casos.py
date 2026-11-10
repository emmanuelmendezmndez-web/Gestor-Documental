"""Pruebas de adjuntos con ACL, SQLite y manejadores NTFS reales en datos ficticios."""

import io
import os
import struct
import subprocess
import sys
import unittest
import warnings
import zipfile
import zlib
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch
from uuid import uuid4

from aislamiento import exigir_directorio_temporal

RAIZ = exigir_directorio_temporal("siged-prueba-mensajeria-")

from app import respaldo
from app.configuracion import STORAGE_DIR
from app.database import conectar, inicializar_db
from app.mensajeria import adjuntos, disco, formatos, motor
from app.mensajeria import base_datos as bd
from app.mensajeria import limpieza_adjuntos as limpieza
from app.mensajeria import reconciliacion as rec


class GenerarTexto:
    def __init__(self, cantidad):
        self.cantidad = cantidad

    def read(self, maximo):
        assert 0 < maximo <= formatos.BLOQUE
        cantidad = min(maximo, self.cantidad)
        self.cantidad -= cantidad
        return b"x" * cantidad


def oficio(extra=None, *, relleno=False, sufijo=".docx"):
    principal, tipo, ns, raiz = formatos.OFICINA[sufijo]
    datos = io.BytesIO()
    with zipfile.ZipFile(datos, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   f'<Override PartName="/{principal}" ContentType="application/vnd.openxmlformats-'
                   f'officedocument.{tipo}"/></Types>')
        z.writestr("_rels/.rels",
                   f'<Relationships xmlns="{formatos.NS_REL}"><Relationship Target="{principal}" '
                   'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
                   'Id="rId1"/></Relationships>')
        z.writestr(principal, f'<{raiz} xmlns="http://schemas.openxmlformats.org/{ns}/2006/main"/>')
        if extra:
            z.writestr(extra, b"ficticio")
        if relleno:
            with z.open("word/grande.xml", "w") as f:
                bloque = b"z" * formatos.BLOQUE
                for _ in range(193):
                    f.write(bloque)
    return datos.getvalue()


def png():
    def bloque(tipo, datos):
        return struct.pack(">I", len(datos)) + tipo + datos + struct.pack(">I", zlib.crc32(tipo + datos))
    return (b"\x89PNG\r\n\x1a\n" + bloque(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0))
            + bloque(b"IDAT", zlib.compress(b"\0\0")) + bloque(b"IEND", b""))


def jpeg_minimo():
    marco = struct.pack(">BHHB", 8, 1, 1, 1) + b"\x01\x11\x00"
    barrido = b"\x01\x01\x00\x00\x3f\x00"
    return b"\xff\xd8\xff\xc0\x00\x0b" + marco + b"\xff\xda\x00\x08" + barrido + b"\x01\xff\xd9"


class AdjuntosCasos(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        inicializar_db()
        STORAGE_DIR.mkdir()
        with conectar() as db:
            for nombre in ("alfa", "beta", "gama"):
                db.execute(
                    "INSERT INTO usuarios(usuario,nombre,password_hash,rol) VALUES (?,?,'ficticio','lector')",
                    (nombre, nombre),
                )
        cls.base = bd.inicializar()
        cls.zona = cls.base.parent / "temporales"
        informe = rec.preparar_identidades()
        if rec.reconciliar(informe["confirmacion"])["estado"] != "identidad_coherente":
            raise AssertionError("El conjunto de prueba no está reconciliado")
        with conectar() as db:
            cls.a, cls.b, cls.c = (fila[0] for fila in db.execute("SELECT mensajeria_ref FROM usuarios ORDER BY id"))

    def setUp(self):
        for ruta in self.zona.iterdir():
            ruta.unlink()
        with bd._conectar_infraestructura() as db:
            for tabla in ("archivos_externos", "eventos", "operaciones", "mensajes", "estado_participante",
                          "conversaciones", "cuotas", "limpieza", "reloj_motor"):
                db.execute(f"DELETE FROM {tabla}")
        self.instante = 1780000000
        self.clave = uuid4().hex
        self.enterContext(patch.object(motor, "_ahora", side_effect=lambda: self.instante))
        self.enterContext(patch.dict(os.environ, {"GESTOR_MENSAJERIA_ESPACIO_LIBRE_BYTES": "1048576"}))

    def preparar(self, datos=b"contenido ficticio", nombre="oficio.txt", clave=None):
        flujo = io.BytesIO(datos) if isinstance(datos, bytes) else datos
        return adjuntos.preparar(self.a, self.b, clave or self.clave, nombre, flujo)

    def enviar(self, adjunto, texto="Mensaje ficticio", clave=None):
        return motor.enviar(self.a, self.b, texto, clave or self.clave, adjunto)

    def ruta(self, adjunto):
        return self.zona / (adjunto.referencia + ".bin")

    def test_limites_reales_y_reservas(self):
        for cantidad, codigo in ((0, "archivo_vacio"), (bd.LIMITE_ARCHIVO + 1, "archivo_demasiado_grande")):
            with self.subTest(cantidad=cantidad), self.assertRaisesRegex(motor.ErrorMotor, codigo):
                self.preparar(GenerarTexto(cantidad))
            self.assertEqual(list(self.zona.iterdir()), [])
        with (
            patch.object(adjuntos.shutil, "disk_usage", return_value=type("Disco", (), {"free": 1})()),
            self.assertRaisesRegex(motor.ErrorMotor, "espacio_adjuntos_insuficiente"),
        ):
            self.preparar()
        with (
            patch.dict(os.environ, {"GESTOR_MENSAJERIA_ARCHIVOS_MAX_BYTES": "1000"}),
            self.assertRaisesRegex(motor.ErrorMotor, "capacidad_adjuntos_agotada"),
        ):
            self.preparar()
        self.assertEqual(motor.cuota(self.a)["envios"], 0)
        maximo = self.preparar(GenerarTexto(bd.LIMITE_ARCHIVO))
        self.assertEqual(self.ruta(maximo).stat().st_size, bd.LIMITE_ARCHIVO)
        self.enviar(maximo)
        self.assertEqual(motor.cuota(self.a)["envios"], 1)

    def test_formatos_nombres_contenedores_y_mime_ignorado(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            duplicado = oficio("word/document.xml")
        casos = (
            ("../archivo.txt", b"x", "nombre_invalido"), ("CON.txt", b"x", "nombre_invalido"),
            ("archivo.exe.txt", b"x", "nombre_invalido"), ("nombre.txt:secreto", b"x", "nombre_invalido"),
            ("a" * 201 + ".txt", b"x", "nombre_invalido"), ("archivo.exe", b"x", "formato_no_permitido"),
            ("archivo.pdf", b"Texto", "formato_incompatible"), ("imagen.png", png()[:-1], "formato_incompatible"),
            ("archivo.docx", oficio()[:-2], "formato_incompatible"),
            ("archivo.docx", oficio("../archivo.txt"), "formato_incompatible"),
            ("archivo.docx", duplicado, "formato_incompatible"),
            ("archivo.docx", oficio(relleno=True), "formato_incompatible"),
            ("archivo.xlsx", oficio(), "formato_incompatible"), ("texto.txt", b"\x00", "formato_incompatible"),
        )
        for nombre, datos, codigo in casos:
            with self.subTest(nombre=nombre, longitud=len(datos)), self.assertRaisesRegex(ValueError, codigo):
                sufijo = formatos.extension(nombre)
                formatos.validar(io.BytesIO(datos), sufijo, len(datos), lambda: None)
        validos = (
            ("archivo.DOCX", oficio()), ("imagen.png", png()), ("texto.txt", "ñ".encode()),
            ("libro.xlsx", oficio(sufijo=".xlsx")), ("diapositivas.pptx", oficio(sufijo=".pptx")),
            ("informe.pdf", b"%PDF-1.7\nxref\n0 1\n0000000000 65535 f\nstartxref\n9\n%%EOF\n"),
            ("foto.JPEG", jpeg_minimo()),
        )
        for nombre, datos in validos:
            with self.subTest(nombre=nombre):
                formatos.validar(io.BytesIO(datos), formatos.extension(nombre), len(datos), lambda: None)
        with self.assertRaisesRegex(motor.ErrorMotor, "formato_incompatible"):
            self.preparar(b"Texto", "archivo.pdf")
        self.assertEqual(list(self.zona.iterdir()), [])
        flujo = io.BytesIO(oficio())
        flujo.content_type = "application/x-msdownload"
        self.preparar(flujo, "archivo.docx")
        self.assertEqual(len(list(self.zona.iterdir())), 1)

    def test_idempotencia_contenido_y_nombres_repetidos(self):
        archivo = self.preparar()
        primero = self.enviar(archivo)
        self.assertEqual(archivo, self.preparar())
        self.assertEqual(primero, self.enviar(archivo))
        for nombre, datos in (("otro.txt", b"contenido ficticio"), ("oficio.txt", b"contenido diferente")):
            with self.subTest(nombre=nombre), self.assertRaisesRegex(motor.ErrorMotor, "conflicto_idempotencia"):
                self.preparar(datos, nombre)
        with self.assertRaisesRegex(motor.ErrorMotor, "conflicto_idempotencia"):
            self.enviar(archivo, texto="Otro texto")
        otra_clave = uuid4().hex
        segundo = self.preparar(clave=otra_clave)
        self.assertNotEqual(segundo.referencia, archivo.referencia)
        self.assertEqual(len(list(self.zona.iterdir())), 2)
        self.assertEqual(motor.cuota(self.a)["envios"], 1)
        self.instante += motor.RETENCION
        self.assertEqual(limpieza.limpiar()["retirados"], 2)
        self.assertEqual(motor.depurar_historial(), 1)
        self.assertEqual(self.enviar(self.preparar()), primero)

    def test_publicacion_perdida_y_reversion_confirmacion(self):
        persistir = motor._persistir
        archivo = self.preparar()

        def corte(*args):
            persistir(*args)
            raise OSError("ruta o contenido privado ficticio")

        with patch.object(motor, "_persistir", side_effect=corte), self.assertRaisesRegex(
            motor.ErrorMotor, "^almacenamiento_adjunto_no_disponible$",
        ):
            self.enviar(archivo)
        self.assertEqual(motor.cuota(self.a)["envios"], 0)
        self.assertTrue(self.ruta(archivo).exists())
        resultado_perdido = self.enviar(archivo)
        self.assertEqual(self.enviar(self.preparar()), resultado_perdido)
        self.assertEqual(motor.cuota(self.a)["envios"], 1)

    def test_reserva_inactiva_se_libera_sin_esperar_al_productor(self):
        iniciado, terminar = Event(), Event()

        class Lento:
            def read(self, _):
                iniciado.set()
                if not terminar.wait(60):
                    raise AssertionError("No se liberó la fuente")
                return b"tarde"

        with ThreadPoolExecutor(1) as pool:
            futuro = pool.submit(self.preparar, Lento())
            try:
                self.assertTrue(iniciado.wait(60))
                self.assertEqual(len(list(self.zona.iterdir())), 1)
                self.instante += 61
                self.assertEqual(limpieza.limpiar()["retirados"], 1)
                self.assertEqual(list(self.zona.iterdir()), [])
            finally:
                terminar.set()
            with self.assertRaises(motor.ErrorMotor):
                futuro.result(timeout=60)
        self.preparar()
        self.assertEqual(motor.cuota(self.a)["envios"], 0)

    def test_archivo_inexistente_alterado_y_descargas_ajenas(self):
        falso = motor.Adjunto("externo", uuid4().hex, "oficio.txt", 7)
        with self.assertRaisesRegex(motor.ErrorMotor, "adjunto_no_confirmado"):
            motor.enviar(self.a, self.b, "Ficticio", self.clave, falso, verificar_adjunto=lambda _: True)
        archivo = self.preparar()
        ruta = self.ruta(archivo)
        bytes_originales = ruta.read_bytes()
        ruta.write_bytes(b"x" * len(bytes_originales))
        with self.assertRaisesRegex(motor.ErrorMotor, "adjunto_no_disponible"):
            self.enviar(archivo)
        ruta.unlink()
        with self.assertRaisesRegex(motor.ErrorMotor, "almacenamiento_adjunto_no_disponible"):
            self.enviar(archivo)
        self.assertEqual(motor.cuota(self.a)["envios"], 0)
        otro = uuid4().hex
        mensaje = self.enviar(self.preparar(clave=otro), clave=otro)
        with self.assertRaisesRegex(motor.ErrorMotor, "adjunto_no_disponible"), adjuntos.abrir_descarga(self.c, mensaje):
            self.fail("Un tercero obtuvo la descarga")
        with adjuntos.abrir_descarga(self.a, mensaje) as (f, cabeceras):
            self.assertEqual(f.read(), bytes_originales)
            self.assertIsInstance(f.name, int)
            self.assertEqual(cabeceras["Content-Type"], "application/octet-stream")
            self.assertTrue(cabeceras["Content-Disposition"].startswith("attachment;"))

    def test_vigencia_y_bloqueo_de_windows_durante_descarga(self):
        archivo = self.preparar()
        self.instante += 10
        mensaje = self.enviar(archivo)
        self.instante += motor.VIGENCIA_ARCHIVO - 1
        with adjuntos.abrir_descarga(self.b, mensaje) as (f, _):
            self.assertEqual(f.read(1), b"c")
            self.instante += 1
            with self.assertRaisesRegex(motor.ErrorMotor, "adjunto_no_disponible"), adjuntos.abrir_descarga(self.a, mensaje):
                self.fail("Se inició una descarga vencida")
            self.assertEqual(limpieza.limpiar()["aplazados"], 1)
            self.assertTrue(self.ruta(archivo).exists())
            self.assertEqual(f.read(), b"ontenido ficticio")
        self.instante += 60
        self.assertEqual(limpieza.limpiar()["retirados"], 1)
        self.assertEqual(limpieza.limpiar()["retirados"], 0)
        self.assertFalse(self.ruta(archivo).exists())
        fila = motor.mensajes(self.a, motor.conversacion(self.a, self.b))[0]
        self.assertEqual((fila["estado_archivo"], fila["nombre_original"]), ("vencido", "oficio.txt"))

    def test_corte_abrupto_recuperable_y_carga_interrumpida(self):
        class Interrumpido:
            def __init__(self):
                self.leido = False

            def read(self, _):
                if self.leido:
                    raise OSError("privado")
                self.leido = True
                return b"parcial"

        with self.assertRaisesRegex(motor.ErrorMotor, "^carga_interrumpida$"):
            self.preparar(Interrumpido())
        self.assertEqual(list(self.zona.iterdir()), [])
        programa = f"""
import os
from app.mensajeria import adjuntos, motor
motor._ahora = lambda: {self.instante}
class Interrumpido:
    def read(self, _):
        if getattr(self, "leido", False):
            os._exit(23)
        self.leido = True
        return b"parcial"
adjuntos.preparar({self.a!r}, {self.b!r}, {self.clave!r}, "parcial.txt", Interrumpido())
"""
        proceso = subprocess.run([sys.executable, "-c", programa], check=False, timeout=90)
        self.assertEqual(proceso.returncode, 23)
        parcial, = self.zona.iterdir()
        self.assertEqual(parcial.read_bytes(), b"parcial")
        self.instante += 601
        self.assertEqual(limpieza.limpiar()["retirados"], 1)
        self.assertFalse(parcial.exists())
        self.assertEqual(motor.cuota(self.a)["envios"], 0)

    def test_concurrencia_de_confirmacion_y_limpieza(self):
        archivo = self.preparar()
        entrada, salir = Event(), Event()
        verificar = adjuntos._verificar_archivo

        def pausa(*args):
            resultado = verificar(*args)
            entrada.set()
            if not salir.wait(60):
                raise AssertionError("No se reanudó el confirmador")
            return resultado

        with ThreadPoolExecutor(2) as pool, patch.object(adjuntos, "_verificar_archivo", side_effect=pausa):
            envio = pool.submit(self.enviar, archivo)
            try:
                self.assertTrue(entrada.wait(60))
                self.assertEqual(limpieza.limpiar()["retirados"], 0)
                self.assertTrue(self.ruta(archivo).exists())
            finally:
                salir.set()
            envio.result(timeout=60)
        self.instante += motor.VIGENCIA_ARCHIVO
        with disco.zona() as zona, limpieza._turno(zona) as turno, ThreadPoolExecutor(1) as pool:
            self.assertTrue(turno)
            self.assertEqual(pool.submit(limpieza.limpiar).result(timeout=60)["retirados"], 0)
        self.assertEqual(limpieza.limpiar()["retirados"], 1)

    def test_borrado_rechaza_identidad_ajena_y_reintenta_permiso(self):
        archivo = self.preparar()
        self.enviar(archivo)
        self.instante += motor.VIGENCIA_ARCHIVO
        with patch.object(disco, "borrar", side_effect=PermissionError("privado")):
            self.assertEqual(limpieza.limpiar()["aplazados"], 1)
        self.instante += 60
        ruta = self.ruta(archivo)
        oficial = STORAGE_DIR / "oficial-ficticio.txt"
        oficial.write_bytes(b"documento oficial ficticio")
        ruta.unlink()
        try:
            os.link(oficial, ruta)
            with self.assertRaises(OSError):
                disco.borrar(ruta, "identidad_ficticia")
            # El archivo enlazado conserva la ACL de fuera del almacén.
            with self.assertRaisesRegex(motor.ErrorMotor, "almacenamiento_adjunto_no_disponible"):
                limpieza.limpiar()
            self.assertEqual(oficial.read_bytes(), b"documento oficial ficticio")
            self.assertTrue(ruta.exists())
        finally:
            ruta.unlink(missing_ok=True)
            oficial.unlink()
        self.instante += 60
        self.assertEqual(limpieza.limpiar()["retirados"], 1)
        ajeno = self.zona / (uuid4().hex + ".bin")
        ajeno.write_bytes(b"sin evidencia")
        self.assertEqual(limpieza.limpiar()["sin_evidencia"], 1)
        self.assertEqual(ajeno.read_bytes(), b"sin evidencia")

    def test_corte_tras_borrado_y_permiso_de_creacion(self):
        with (
            patch.object(disco, "abrir", side_effect=PermissionError("ruta privada")),
            self.assertRaisesRegex(motor.ErrorMotor, "^almacenamiento_adjunto_no_disponible$"),
        ):
            self.preparar()
        self.assertEqual(list(self.zona.iterdir()), [])
        archivo = self.preparar()
        mensaje = self.enviar(archivo)
        self.instante += motor.VIGENCIA_ARCHIVO
        limpiar_uno = limpieza._limpiar

        def corte(*args):
            self.assertTrue(limpiar_uno(*args))
            raise OSError("interrupción después del borrado")

        with (
            patch.object(limpieza, "_limpiar", side_effect=corte),
            self.assertRaisesRegex(motor.ErrorMotor, "^almacenamiento_adjunto_no_disponible$"),
        ):
            limpieza.limpiar()
        self.assertFalse(self.ruta(archivo).exists())
        self.assertEqual(limpieza.limpiar()["retirados"], 1)
        self.assertEqual(self.enviar(self.preparar()), mensaje)

    def test_colision_conserva_destino_y_libera_reserva(self):
        token = uuid4()
        ajeno = self.zona / (token.hex + ".bin")
        ajeno.write_bytes(b"preexistente")
        with patch.object(adjuntos, "uuid4", return_value=token), self.assertRaisesRegex(
            motor.ErrorMotor, "^destino_adjunto_ocupado$",
        ):
            self.preparar()
        self.assertEqual(ajeno.read_bytes(), b"preexistente")
        self.assertEqual(limpieza.limpiar()["sin_evidencia"], 1)
        self.assertNotEqual(self.preparar().referencia, token.hex)

    def test_inicio_del_servidor_revisa_pendientes_sin_publicar_rutas(self):
        archivo = self.preparar()
        self.enviar(archivo)
        self.instante += motor.VIGENCIA_ARCHIVO
        programa = f"""
import asyncio
from pathlib import Path
from app.main import app, lifespan
from app.mensajeria import motor
motor._ahora = lambda: {self.instante}
ruta = Path({str(self.ruta(archivo))!r})
async def ejecutar():
    assert not any("mensajeria" in getattr(r, "path", "") for r in app.routes)
    async with lifespan(app):
        async with asyncio.timeout(45):
            while ruta.exists():
                await asyncio.sleep(0.1)
asyncio.run(ejecutar())
"""
        subprocess.run([sys.executable, "-c", programa], check=True, timeout=75)
        self.assertFalse(self.ruta(archivo).exists())

    def test_junction_no_expone_ni_borra_documentos(self):
        archivo = self.preparar()
        ruta = self.ruta(archivo)
        ruta.unlink()
        oficial = STORAGE_DIR / "original-ficticio.txt"
        oficial.write_bytes(b"original")
        cmd = os.path.join(os.environ["SystemRoot"], "System32", "cmd.exe")
        subprocess.run([cmd, "/c", "mklink", "/J", str(ruta), str(STORAGE_DIR)],
                       check=True, capture_output=True, timeout=15)
        try:
            with self.assertRaisesRegex(motor.ErrorMotor, "^almacenamiento_adjunto_no_disponible$"):
                self.enviar(archivo)
            self.instante += 601
            with self.assertRaisesRegex(motor.ErrorMotor, "^almacenamiento_adjunto_no_disponible$"):
                limpieza.limpiar()
            self.assertEqual(oficial.read_bytes(), b"original")
        finally:
            ruta.rmdir()
            oficial.unlink()

    def test_z_respaldo_reconciliacion_y_desactivacion(self):
        clave_vieja = uuid4().hex
        preparado = self.preparar(clave=clave_vieja)
        vigente = self.preparar(b"adjunto-solo-mensajeria")
        mensaje = self.enviar(vigente)
        respaldo_zip = respaldo.crear_respaldo(RAIZ / "con-mensajeria.zip")
        with zipfile.ZipFile(respaldo_zip) as z:
            self.assertFalse(any(".siged-mensajeria" in nombre for nombre in z.namelist()))
            self.assertTrue(all(b"adjunto-solo-mensajeria" not in z.read(nombre) for nombre in z.namelist()))
        respaldo.restaurar_respaldo(respaldo_zip)
        with self.assertRaisesRegex(motor.ErrorMotor, "identidad_no_reconciliada"), adjuntos.abrir_descarga(self.a, mensaje):
            self.fail("Se admitió una generación sin reconciliar")
        informe = rec.diagnosticar()
        self.assertEqual(rec.reconciliar(informe["confirmacion"])["estado"], "identidad_coherente")
        with self.assertRaisesRegex(motor.ErrorMotor, "generacion_cambio"):
            self.enviar(preparado, clave=clave_vieja)
        with adjuntos.abrir_descarga(self.b, mensaje) as (f, _):
            self.assertEqual(f.read(), b"adjunto-solo-mensajeria")
        with (
            patch.dict(os.environ, {"GESTOR_MENSAJERIA_DIR": ""}),
            self.assertRaisesRegex(motor.ErrorMotor, "^almacenamiento_adjunto_no_disponible$"),
        ):
            self.preparar()
        self.assertEqual(motor.cuota(self.a)["envios"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
