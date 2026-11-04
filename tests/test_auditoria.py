"""Pruebas aisladas de transacciones y actividad obligatoria."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class AuditoriaAisladaTest(unittest.TestCase):
    def test_fallos_de_auditoria(self):
        raiz = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="siged-auditoria-") as carpeta:
            entorno = os.environ.copy()
            entorno.update(GESTOR_DATA_DIR=carpeta, GESTOR_SECRET_KEY="clave-ficticia-auditoria",
                           LOCALAPPDATA=carpeta, PYTHONPATH=str(raiz))
            subprocess.run([sys.executable, str(raiz / "tests" / "auditoria_casos.py")],
                           cwd=raiz, env=entorno, check=True, timeout=120)
