"""Las pruebas destructivas deben rechazar rutas inseguras incluso con -O."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aislamiento import exigir_directorio_temporal

RAIZ = Path(__file__).resolve().parents[1]
CASOS = {
    "auditoria_casos.py": "siged-auditoria-",
    "concurrencia_casos.py": "siged-prueba-concurrencia-",
    "eliminaciones_casos.py": "siged-prueba-eliminaciones-",
    "respaldo_casos.py": "siged-prueba-respaldo-",
}


class AislamientoTest(unittest.TestCase):
    def test_scripts_rechazan_directorio_no_vacio_con_y_sin_optimizacion(self):
        for archivo, prefijo in CASOS.items():
            for optimizado in (False, True):
                with (
                    self.subTest(archivo=archivo, optimizado=optimizado),
                    tempfile.TemporaryDirectory(prefix=prefijo) as carpeta,
                ):
                    raiz = Path(carpeta)
                    centinela = raiz / "gestor.db"
                    centinela.write_bytes(b"base ficticia que no debe modificarse")
                    entorno = os.environ.copy()
                    entorno.update(
                        GESTOR_DATA_DIR=carpeta,
                        PYTHONPATH=str(RAIZ),
                        PYTHONDONTWRITEBYTECODE="1",
                    )
                    comando = [sys.executable, "-B"]
                    if optimizado:
                        comando.append("-O")
                    comando.append(str(RAIZ / "tests" / archivo))
                    resultado = subprocess.run(
                        comando,
                        cwd=RAIZ,
                        env=entorno,
                        capture_output=True,
                        timeout=30,
                        check=False,
                    )
                    self.assertNotEqual(resultado.returncode, 0)
                    self.assertIn(b"Aislamiento de pruebas", resultado.stderr)
                    self.assertEqual(
                        centinela.read_bytes(), b"base ficticia que no debe modificarse"
                    )
                    self.assertEqual({p.name for p in raiz.iterdir()}, {"gestor.db"})

    def test_valida_configuraciones_temporales(self):
        prefijo = "siged-prueba-aislamiento-"
        with tempfile.TemporaryDirectory(prefix=prefijo) as carpeta:
            raiz = Path(carpeta)
            with patch.dict(os.environ, {"GESTOR_DATA_DIR": carpeta}):
                self.assertEqual(exigir_directorio_temporal(prefijo), raiz.resolve())
                with self.assertRaises(RuntimeError):
                    exigir_directorio_temporal("prefijo-incorrecto-")
                subdirectorio = raiz / (prefijo + "anidado123")
                subdirectorio.mkdir()
                with (
                    patch.dict(os.environ, {"GESTOR_DATA_DIR": str(subdirectorio)}),
                    self.assertRaises(RuntimeError),
                ):
                    exigir_directorio_temporal(prefijo)
                with self.assertRaises(RuntimeError):
                    exigir_directorio_temporal(prefijo)
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(RuntimeError):
            exigir_directorio_temporal(prefijo)

    def test_scripts_rechazan_variable_ausente_con_y_sin_optimizacion(self):
        # El paquete ficticio impide que un fallo de la barrera importe la app real.
        with tempfile.TemporaryDirectory(prefix="siged-barrera-ficticia-") as carpeta:
            paquete = Path(carpeta) / "app"
            paquete.mkdir()
            (paquete / "__init__.py").write_text("raise RuntimeError('app ficticia')\n")
            for archivo in CASOS:
                for optimizado in (False, True):
                    with self.subTest(archivo=archivo, optimizado=optimizado):
                        entorno = os.environ.copy()
                        entorno.pop("GESTOR_DATA_DIR", None)
                        entorno.update(PYTHONPATH=carpeta, PYTHONDONTWRITEBYTECODE="1")
                        comando = [sys.executable, "-B"]
                        if optimizado:
                            comando.append("-O")
                        comando.append(str(RAIZ / "tests" / archivo))
                        resultado = subprocess.run(
                            comando,
                            cwd=carpeta,
                            env=entorno,
                            capture_output=True,
                            timeout=30,
                            check=False,
                        )
                        self.assertNotEqual(resultado.returncode, 0)
                        self.assertIn(b"Aislamiento de pruebas", resultado.stderr)


if __name__ == "__main__":
    unittest.main()
