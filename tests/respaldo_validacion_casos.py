"""Casos ejecutados únicamente con GESTOR_DATA_DIR temporal aislado."""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from aislamiento import exigir_directorio_temporal
exigir_directorio_temporal("siged-prueba-respaldo-")

from app import respaldo
from app.configuracion import DATA_DIR, DB_PATH, STORAGE_DIR
from app.database import inicializar_db


class ValidacionZipTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        inicializar_db()
        STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        (STORAGE_DIR / "ficticio.txt").write_bytes(b"contenido ficticio")
        respaldo.SECRET_PATH.write_text("clave-local-ficticia-no-modificar", encoding="utf-8")
        cls.original = respaldo.crear_respaldo(DATA_DIR / "original.zip")
        with zipfile.ZipFile(cls.original) as z:
            cls.entries = [(i.filename, z.read(i)) for i in z.infolist()]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=DATA_DIR)
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def zip(self, entries):
        path = self.root / "prueba.zip"
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as z:
            for name, data in entries:
                z.writestr(name, data)
        return path

    def rechazar(self, path):
        antes = DB_PATH.read_bytes(), (STORAGE_DIR / "ficticio.txt").read_bytes(), respaldo.SECRET_PATH.read_bytes()
        staging = self.root / "validado"
        with self.assertRaises(Exception):
            respaldo.validar_respaldo(path, staging)
        self.assertFalse(staging.exists() and any(staging.iterdir()))
        with self.assertRaises(Exception):
            respaldo.restaurar_respaldo(path)
        self.assertEqual(antes, (DB_PATH.read_bytes(), (STORAGE_DIR / "ficticio.txt").read_bytes(), respaldo.SECRET_PATH.read_bytes()))
        self.assertFalse(list(DATA_DIR.glob("siged-restaurar-*")))

    def test_formato_actual_y_anterior(self):
        self.assertEqual(respaldo.validar_respaldo(self.original)["format_version"], 1)
        anterior = [(n, d) for n, d in self.entries if n != "storage/"]
        self.assertEqual(respaldo.validar_respaldo(self.zip(anterior))["format_version"], 1)

    def test_rutas_peligrosas(self):
        for ruta in ("../fuera", "/absoluta", "C:/fuera", "//servidor/recurso", "storage/../fuera",
                     "storage/CON.txt", "storage/AUX", "storage/Lpt¹.txt", "storage/a.",
                     "storage/a ", "storage/a:flujo", "storage/a\\b", "storage//a", "otro/archivo"):
            with self.subTest(ruta=ruta):
                self.rechazar(self.zip(self.entries + [(ruta, b"x")]))

    def test_duplicados_y_colisiones(self):
        for extras in ([('storage/ficticio.txt', b'x')], [('storage/FICTICIO.txt', b'x')],
                       [('storage/carpeta', b'x'), ('storage/carpeta/a', b'x')],
                       [('storage/Carpeta/a', b'x'), ('storage/carpeta/b', b'x')]):
            with self.subTest(extras=extras):
                with __import__('warnings').catch_warnings():
                    __import__('warnings').simplefilter('ignore', UserWarning)
                    self.rechazar(self.zip(self.entries + extras))

    def test_limites_configurables(self):
        for var, valor in (("GESTOR_RESPALDO_MAX_ENTRADAS", "2"),
                           ("GESTOR_RESPALDO_MAX_ARCHIVO_BYTES", "10"),
                           ("GESTOR_RESPALDO_MAX_TOTAL_BYTES", "10"),
                           ("GESTOR_RESPALDO_MAX_ENTRADAS", "0")):
            with self.subTest(var=var), patch.dict(os.environ, {var: valor}):
                self.rechazar(self.original)

    def test_manifiesto_tamano_corrupto_y_truncado(self):
        for cambio in ("hash", "tamano"):
            entries = []
            for nombre, datos in self.entries:
                if nombre == "manifest.json":
                    manifest = json.loads(datos)
                    campo = manifest["files"]["storage/ficticio.txt"]
                    campo["sha256" if cambio == "hash" else "size"] = "0" * 64 if cambio == "hash" else 999
                    datos = json.dumps(manifest).encode()
                entries.append((nombre, datos))
            with self.subTest(cambio=cambio):
                self.rechazar(self.zip(entries))
        truncado = self.root / "truncado.zip"
        truncado.write_bytes(self.original.read_bytes()[:-30])
        self.rechazar(truncado)

    def test_enlace_y_datos_corruptos(self):
        ruta = self.root / "enlace.zip"
        with zipfile.ZipFile(ruta, "w") as z:
            for nombre, datos in self.entries:
                z.writestr(nombre, datos)
            enlace = zipfile.ZipInfo("storage/enlace")
            enlace.create_system = 3
            enlace.external_attr = 0o120777 << 16
            z.writestr(enlace, "destino")
        self.rechazar(ruta)
        ruta = self.root / "corrupto.zip"
        with zipfile.ZipFile(ruta, "w", compression=zipfile.ZIP_STORED) as z:
            for nombre, datos in self.entries:
                z.writestr(nombre, datos)
        contenido = ruta.read_bytes().replace(b"contenido ficticio", b"Contenido ficticio", 1)
        ruta.write_bytes(contenido)
        self.rechazar(ruta)

    def test_bytes_reales_y_limpieza_interrupcion(self):
        abrir = zipfile.ZipFile.open
        def alterado(archivo, nombre, *args, **kwargs):
            if getattr(nombre, "filename", nombre) == "storage/ficticio.txt":
                return io.BytesIO(b"contenido ficticio" + b"sobrante")
            return abrir(archivo, nombre, *args, **kwargs)
        with patch.object(zipfile.ZipFile, "open", alterado):
            self.rechazar(self.original)
        staging = self.root / "interrumpido"
        def interrumpir(archivo, nombre, *args, **kwargs):
            if getattr(nombre, "filename", nombre) == "storage/ficticio.txt":
                raise KeyboardInterrupt()
            return abrir(archivo, nombre, *args, **kwargs)
        with patch.object(zipfile.ZipFile, "open", interrumpir):
            with self.assertRaises(KeyboardInterrupt):
                respaldo.validar_respaldo(self.original, staging)
        self.assertFalse(any(staging.iterdir()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
